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

    async def fake_kf(video_id, i, sh, spec, cast, frame, market, note, prompt, drop, placeholder=False):
        drawn.append(note)
        return f"/api/v1/media/keyframes/c{len(drawn)}.png", {"prompt": "p"}

    verdict = {"/api/v1/media/keyframes/c1.png": "fail", "/api/v1/media/keyframes/c2.png": "pass", "/api/v1/media/keyframes/c3.png": "warn"}

    async def fake_qc(kf, sh, spec, cast):
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
        assert [x["status"] for x in t["kf_candidates"]] == ["fail", "pass", "warn"]
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
        production._shot(video_id, i, keyframe=f"/api/v1/media/keyframes/s{i}.png")
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
        assert clips == [] and phases == ["关键帧待确认"] * 3 and status == "input" and "全部满意" in sub  # 没生成视频
        r = c.post(f"/api/v1/nodes/{vid}/clips", json={}).json()
        assert r["shots"] == [0, 1, 2] and len(spawned) == 3
        for co in spawned:
            co.close()
        settings_store.set_retries({"kf_candidates": 2})
