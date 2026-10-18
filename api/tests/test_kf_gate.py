"""关键帧闸门 + 候选 + 可用率统计：整条生成先停在关键帧；每轮画多张候选挑质检最好的，可以换；每镜累计画了几张、几条、为什么失败。"""
import asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app import canvas, production, qc, settings_store  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Node, Project  # noqa: E402


def _video(c, n_shots=2):
    pid = c.post("/api/v1/projects", json={"name": "闸门"}).json()["id"]
    shots = [[f"{k}–{k + 1}s", f"第 {k + 1} 镜画面", "hi", ""] for k in range(n_shots)]
    with SessionLocal() as db:
        p = db.get(Project, pid)
        s = canvas.create_node(db, p, "script", status="pass", data={"shots": shots, "cast": {"roles": {}, "scenes": {}, "specs": [{}] * n_shots, "product": None}})
        v = canvas.create_node(db, p, "video", status="run", data={"script_id": s.id, "shots": shots, "cast_confirmed": True,
                                                                  "tasks": [{"shot": k + 1} for k in range(n_shots)]})
        canvas.connect(db, pid, s.id, v.id)
        db.commit()
        return v.id, shots


def test_candidates_pick_best_and_stats(monkeypatch):
    drawn = []

    async def fake_kf(video_id, i, sh, spec, cast, frame, market, note, prompt, drop, placeholder=False, **kw):
        drawn.append(note)
        return f"/api/v1/media/keyframes/c{len(drawn)}.png", {"prompt": "p"}

    verdict = {"/api/v1/media/keyframes/c1.png": "fail", "/api/v1/media/keyframes/c2.png": "pass", "/api/v1/media/keyframes/c3.png": "warn"}

    async def fake_qc(kf, sh, spec, cast, sketch=None):
        st = verdict[kf]
        return {"status": st, "issues": [] if st == "pass" else ["商品外观不对"], "checks": {"product": {"status": st, "reason": "x"}}}

    monkeypatch.setattr(production, "keyframe", fake_kf)
    monkeypatch.setattr(qc, "check_keyframe", fake_qc)
    with TestClient(app) as c:
        settings_store.set_retries({"kf_candidates": 3, "keyframe": 0})
        vid, shots = _video(c)
        kf, kq, tries, err = asyncio.run(production.make_keyframe(vid, 0, shots[0], {}, {}, None, "尼日利亚", "", 0))
        assert kf.endswith("c2.png") and kq["status"] == "pass" and tries == 3 and len(drawn) == 3
        with SessionLocal() as db:
            t = db.get(Node, vid).data["tasks"][0]
        assert sorted(x["status"] for x in t["kf_candidates"]) == ["fail", "pass", "warn"]  # 按画完的先后排
        assert t["stats"]["kf"] == 3 and [f["kind"] for f in t["stats"]["fails"]] == ["商品外观"]

        # 换一张候选：不花钱，停在关键帧待确认
        production._shot(vid, 0, phase="关键帧待确认", status="keyframe_ready")  # 整条生成里由调用方收尾
        with SessionLocal() as db:
            n = db.get(Node, vid)
            n.status = "input"
            db.commit()
        assert c.post(f"/api/v1/nodes/{vid}/shots/0/keyframe-pick", json={"url": "/api/v1/media/keyframes/nope.png"}).status_code == 404
        assert c.post(f"/api/v1/nodes/{vid}/shots/0/keyframe-pick", json={"url": "/api/v1/media/keyframes/c3.png"}).status_code == 200
        with SessionLocal() as db:
            t = db.get(Node, vid).data["tasks"][0]
        assert t["keyframe"].endswith("c3.png") and t["phase"] == "关键帧待确认" and t["qc"]["status"] == "warn"
        settings_store.set_retries({"kf_candidates": 2, "keyframe": 2})


def test_gate_stops_before_video_and_generate_all(monkeypatch):
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    clips = []

    async def fake_make_kf(video_id, i, sh, spec, cast, frame, market, comment, retries, *a):
        production._shot(video_id, i, keyframe=f"/api/v1/media/keyframes/s{i}.png",
                         kf_candidates=[{"url": f"/api/v1/media/keyframes/s{i}.png", "status": "pass"}, {"url": f"/c{i}.png", "status": "warn"}])
        return f"/api/v1/media/keyframes/s{i}.png", {"status": "pass", "issues": [], "checks": {}}, 1, ""

    async def fake_make_clip(*a, **kw):
        clips.append(a[1])
        return {"shot": a[1] + 1, "status": "completed", "phase": "完成", "url": "https://v/x.mp4"}

    monkeypatch.setattr(production, "make_keyframe", fake_make_kf)
    monkeypatch.setattr(production, "make_clip", fake_make_clip)
    spawned = []
    monkeypatch.setattr("app.routers.ops.spawn", lambda coro: spawned.append(coro))
    with TestClient(app) as c:
        settings_store.set_retries({"kf_candidates": 1, "kf_gate": 1})
        vid, shots = _video(c, 3)
        async def no_sb(*a, **kw):
            return None
        monkeypatch.setattr(production.storyboard, "run", no_sb)
        asyncio.run(production.run(vid))
        with SessionLocal() as db:
            v = db.get(Node, vid)
            phases = [t.get("phase") for t in v.data["tasks"]]
            status, sub = v.status, v.sub
            cands = [len(t.get("kf_candidates") or []) for t in v.data["tasks"]]
        assert cands == [2, 2, 2]  # 收尾不能把候选冲掉，人还要挑
        assert clips == [] and phases == ["关键帧待确认"] * 3 and status == "input" and "全部满意" in sub  # 没生成视频
        r = c.post(f"/api/v1/nodes/{vid}/clips", json={}).json()
        assert r["shots"] == [0, 1, 2] and len(spawned) == 3
        for co in spawned:
            co.close()
        settings_store.set_retries({"kf_candidates": 2})


def test_ref_other_shots(monkeypatch):
    """重画关键帧时选其他镜头的关键帧当参考：放在草图后面（草图仍是第 1 张），本镜和没画好的镜头不算。"""
    with TestClient(app):
        vid, _ = _video(TestClient(app), 3)
        production._shot(vid, 0, keyframe="/api/v1/media/keyframes/a.png")
        production._shot(vid, 2, keyframe="/api/v1/media/keyframes/c.png")
        refs = production.shot_refs(vid, 2, [0, 1, 2])
        assert [r["url"] for r in refs] == ["/api/v1/media/keyframes/a.png"] and refs[0]["kind"] == "shot"
        sent = {}

        async def fake_image(content, **kw):
            sent["content"] = content
            return b"\x89PNG", "image/png"
        monkeypatch.setattr(production.llm, "image", fake_image)
        monkeypatch.setattr(production, "keyframe_refs", lambda *a: [{"kind": "storyboard", "label": "分镜草图", "url": "/s.png", "note": "草图"},
                                                                     {"kind": "actor", "label": "A", "url": "/a1.png", "note": "演员"}])
        monkeypatch.setattr(production.assets, "jpeg_data_url", lambda u, **k: "data:image/jpeg;base64,eA==" + u)
        _, meta = asyncio.run(production.keyframe(vid, 2, ["1", "画面"], {}, {"product": None}, "/s.png", "尼日利亚", "", extra=refs))
        assert [r["kind"] for r in meta["refs"]] == ["storyboard", "shot", "actor"]
        assert "镜 1 已经画好的关键帧" in sent["content"][0]["text"]


def test_stopped_keyframes_still_wait_for_confirm(monkeypatch):
    """停止生成后再「全部重新生成」：没确认过的关键帧沿用（不重画），但仍停在关键帧待确认，不直接生成视频；确认过的才直接生成视频。"""
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    kfs, clips = [], []

    async def fake_make_kf(video_id, i, *a, **kw):
        kfs.append(i)
        return f"/api/v1/media/keyframes/n{i}.png", {"status": "pass", "issues": [], "checks": {}}, 1, ""

    async def fake_make_clip(*a, **kw):
        clips.append(a[1])
        return {"shot": a[1] + 1, "status": "completed", "phase": "完成", "url": "https://v/x.mp4"}
    monkeypatch.setattr(production, "make_keyframe", fake_make_kf)
    monkeypatch.setattr(production, "make_clip", fake_make_clip)
    with TestClient(app) as c:
        settings_store.set_retries({"kf_candidates": 1, "kf_gate": 1})
        vid, shots = _video(c, 2)

        async def no_sb(*a, **kw):
            return None
        monkeypatch.setattr(production.storyboard, "run", no_sb)
        asyncio.run(production.run(vid))  # 第一轮：停在关键帧
        with SessionLocal() as db:
            v = db.get(Node, vid)
            tasks = [dict(t) for t in v.data["tasks"]]
            tasks[0].update(status="failed", phase="已停止")  # 模拟停止：没确认的关键帧
            tasks[1].update(status="failed", phase="失败", kf_ok=True)  # 确认过、视频失败
            v.data = {**v.data, "tasks": tasks}
            db.commit()
        kfs.clear()
        asyncio.run(production.run(vid))
        with SessionLocal() as db:
            phases = [t.get("phase") for t in db.get(Node, vid).data["tasks"]]
        assert kfs == [] and clips == [1] and phases == ["关键帧待确认", "完成"]
        settings_store.set_retries({"kf_candidates": 2})


def test_keyframe_failure_never_falls_back_to_video(monkeypatch):
    """开着闸门时关键帧没画出来：这一镜标失败、写清原因，不退回文生视频。"""
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    clips = []

    async def fail_kf(*a, **kw):
        return None, None, 2, "连不上生图模型（ConnectError：All connection attempts failed）"

    async def fake_make_clip(*a, **kw):
        clips.append(a[1])
        return {"shot": a[1] + 1, "status": "completed", "phase": "完成", "url": "https://v/x.mp4"}
    monkeypatch.setattr(production, "make_keyframe", fail_kf)
    monkeypatch.setattr(production, "make_clip", fake_make_clip)
    with TestClient(app) as c:
        settings_store.set_retries({"kf_candidates": 1, "kf_gate": 1})
        vid, _ = _video(c, 2)

        async def no_sb(*a, **kw):
            return None
        monkeypatch.setattr(production.storyboard, "run", no_sb)
        asyncio.run(production.run(vid))
        with SessionLocal() as db:
            t = db.get(Node, vid).data["tasks"]
        assert clips == [] and all(x["status"] == "failed" and "没有生成视频" in x["error"] and "连不上" in x["error"] for x in t)
        assert production.fail_kind(t[0]["keyframe_error"]) == "网络"
        settings_store.set_retries({"kf_candidates": 2})


def test_pin_candidate_stops_drawing(monkeypatch):
    """还在画候选时选定一张：画关键帧的循环停下，不再等其他候选、不再重画，用选定的那张。"""
    monkeypatch.setattr(production, "PIN_POLL", 0.05)
    n = {"k": 0}

    async def fake_kf(video_id, i, *a, **kw):
        n["k"] += 1
        k = n["k"]
        await asyncio.sleep(0.01 if k == 1 else 5)  # 第 1 张很快画好，第 2 张要很久
        return f"/api/v1/media/keyframes/p{k}.png", {"mode": "ai"}

    async def fake_qc(url, *a, **kw):
        return {"status": "fail", "issues": ["商品：不对"], "checks": {}}
    monkeypatch.setattr(production, "keyframe", fake_kf)
    monkeypatch.setattr(qc, "check_keyframe", fake_qc)
    with TestClient(app) as c:
        settings_store.set_retries({"kf_candidates": 2})
        vid, shots = _video(c)

        async def go():
            task = asyncio.ensure_future(production.make_keyframe(vid, 0, shots[0], {}, {}, None, "尼日利亚", "", 2))
            for _ in range(100):
                await asyncio.sleep(0.02)
                with SessionLocal() as db:
                    t = db.get(Node, vid).data["tasks"][0]
                if t.get("kf_candidates"):
                    break
            assert production.pin_candidate(vid, 0, "/api/v1/media/keyframes/p1.png")
            return await asyncio.wait_for(task, 2)
        kf, kq, tries, err = asyncio.run(go())
        assert kf.endswith("p1.png") and n["k"] == 2 and tries == 2  # 没有再画第 2 轮
