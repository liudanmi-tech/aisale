"""左侧 Agent：滑动窗口记忆（「继续」接上之前的指令）、任意人群 / 标签 / 语言 / 机型写剧本。"""
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app import agent, settings_store  # noqa: E402
from app.adapters import llm  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ChatMessage  # noqa: E402

ASK = "给埃塞俄比亚的「大学生、自拍美颜、短视频创作、基督教」人群写 3 个 Infinix Hot 60 的剧本，用阿姆哈拉语口播"


def test_free_audience_and_follow_up():
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "记忆", "market": "埃塞俄比亚"}).json()["id"]
        P = f"/api/v1/projects/{pid}"
        c.post(P + "/agent/chat", json={"text": ASK, "selection": []})
        patch = c.get(P + "/canvas").json()["pending_patch"]
        assert patch and patch["summary"] == "写剧本"
        aud = next(o for o in patch["ops"] if o["op"] == "create_node" and o["type"] == "aud")
        assert aud["data"]["audience"] == "大学生" and "基督教" in aud["data"]["tags"]
        script = next(o for o in patch["ops"] if o["op"] == "create_node" and o["type"] == "script")
        assert script["data"]["language"] == "阿姆哈拉语" and script["data"]["model_sku"] == "Infinix Hot 60"
        assert any("新建人群包「大学生」" in s for s in patch["steps"])
        # 「继续」：接上一条指令，不再反问
        c.post(P + "/agent/chat", json={"text": "继续", "selection": []})
        again = c.get(P + "/canvas").json()["pending_patch"]
        assert again and again["id"] != patch["id"] and again["summary"] == "写剧本"
        assert next(o for o in again["ops"] if o["type"] == "aud")["data"]["audience"] == "大学生"
        # 确认执行：新人群包和剧本都上了画布
        assert c.post(f"{P}/patches/{again['id']}/apply").status_code == 200
        nodes = c.get(P + "/canvas").json()["nodes"]
        assert any(n["type"] == "aud" and n["title"] == "人群包 · 大学生" for n in nodes)
        assert sum(n["type"] == "script" for n in nodes) == 3


def test_history_window(monkeypatch):
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "窗口"}).json()["id"]
        with SessionLocal() as db:
            for k in range(30):
                db.add(ChatMessage(project_id=pid, role="user" if k % 2 == 0 else "agent", content={"text": f"第{k}条 " + "长" * (1500 if k == 27 else 10)}))
            db.add(ChatMessage(project_id=pid, role="user", content={"text": "当前这条"}))
            db.commit()
            h = agent.history(db, pid)
        assert len(h) <= agent.HISTORY_MESSAGES and h[-1]["content"].startswith("第29条") and "当前这条" not in json.dumps(h, ensure_ascii=False)
        assert all(len(x["content"]) <= agent.HISTORY_EACH for x in h) and sum(len(x["content"]) for x in h) <= agent.HISTORY_CHARS
        assert h[-1]["role"] == "assistant" and h[-2]["role"] == "user"

        # 模型路径：历史对话放在当前消息前面一起发给模型
        seen = {}

        async def fake_chat(messages, **kw):
            seen["messages"] = messages
            return {"tool_calls": [{"function": {"name": "summary", "arguments": "{}"}}]}

        monkeypatch.setattr(llm, "chat", fake_chat)
        monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
        c.post(f"/api/v1/projects/{pid}/agent/chat", json={"text": "继续", "selection": []})
        msgs = seen["messages"]
        assert msgs[0]["role"] == "system" and "记忆" in msgs[0]["content"] and msgs[-1] == {"role": "user", "content": "继续"}
        assert any(m["content"].startswith("当前这条") for m in msgs[1:-1])


def test_openrouter_errors_are_readable():
    """OpenRouter 出错时给出原因：余额不够画图（文字调用照常）这种情况最常见。"""
    import httpx
    import pytest
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    body = {"error": {"message": "This request requires at least $1.00 in balance for image or video output", "code": 402}}
    with pytest.raises(RuntimeError, match="生成图片要求账户余额至少 \\$1"):
        llm._check(httpx.Response(402, json=body, request=req))
    with pytest.raises(RuntimeError, match="Key 无效"):
        llm._check(httpx.Response(401, json={"error": {"message": "No auth"}}, request=req))
    llm._check(httpx.Response(200, json={}, request=req))


def test_redraw_with_custom_prompt_and_find_product(monkeypatch):
    """重画演员 / 场景时可以改提示词（存下来，下次沿用，可恢复默认）；视频找商品时认得「Infinix Hot 60」和「Hot 60」是同一款。"""
    from app import assets, production
    from app.models import Asset
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    calls = []

    async def fake_gen(aid):
        calls.append(aid)
    monkeypatch.setattr(assets, "generate_image", fake_gen)
    with TestClient(app) as c:
        a = c.post("/api/v1/library", json={"kind": "scene", "name": "简洁产品展示台", "description": "深灰背景"}).json()
        assert a["gen_prompt"] == a["default_prompt"] and "简洁产品展示台" in a["gen_prompt"]
        assert c.post(f"/api/v1/library/{a['id']}/generate", json={"prompt": "木纹桌面，暖光，没有手机"}).status_code == 200
        b = next(x for x in c.get("/api/v1/library").json() if x["id"] == a["id"])
        assert b["gen_prompt"] == "木纹桌面，暖光，没有手机" and b["data"]["prompt"] == "木纹桌面，暖光，没有手机"
        c.post(f"/api/v1/library/{a['id']}/generate", json={"prompt": ""})  # 恢复默认
        assert next(x for x in c.get("/api/v1/library").json() if x["id"] == a["id"])["gen_prompt"] == b["default_prompt"]
        assert len(calls) == 2
        with SessionLocal() as db:
            p = Asset(id="as_hot60test", kind="product", name="Infinix Hot 60", description="", images=["/x.png"], tags=[],
                      data={"brand": "Infinix", "model_sku": "Hot 60"}, source="upload", status="ready")
            db.add(p)
            db.commit()
        assert production._find_product("Infinix", "Infinix Hot 60") == "as_hot60test"
        assert production._find_product("Infinix", "hot60") == "as_hot60test"


def test_stop_video_and_phone_shots(monkeypatch):
    """停止生成：后台任务取消，正在做的镜头标「已停止」、做好的保留，之后能单镜重做；有人用手机的镜头升级成手持商品镜头。"""
    import asyncio

    from app import canvas, production
    from app.models import Node, Project
    assert production.phone_spec({"roles": ["r1"], "product": False}, "朋友聚会，女生举起手机自拍")["product_tier"] == "hand"
    assert production.phone_spec({"roles": [], "product": False}, "城市夜景空镜") == {"roles": [], "product": False}
    assert production.phone_spec({"roles": ["r1"], "product": False}, "两人在街上聊天")["product"] is False

    async def slow_run(video_id, *a):
        production._shot(video_id, 0, phase="完成", keyframe="/kf0.png")
        production._shot(video_id, 1, phase="生成视频", keyframe="/kf1.png")
        await asyncio.sleep(30)
    monkeypatch.setattr(production, "_run", slow_run)
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "停止"}).json()["id"]
        with SessionLocal() as db:
            v = canvas.create_node(db, db.get(Project, pid), "video", status="run", data={"tasks": []})
            db.commit()
            vid = v.id

        async def go():
            t = asyncio.create_task(production.run(vid))
            await asyncio.sleep(0.05)
            assert production.stop(vid) == 1
            await asyncio.gather(t, return_exceptions=True)
        asyncio.run(go())
        with SessionLocal() as db:
            n = db.get(Node, vid)
            ph = [t["phase"] for t in n.data["tasks"]]
            assert n.status == "failed" and "已停止" in n.sub and ph == ["完成", "已停止"] and n.data["tasks"][1]["keyframe"] == "/kf1.png"
        assert c.post(f"/api/v1/nodes/{vid}/stop").json()["ok"]  # 没有在跑的任务也能点，不报错


def test_fal_reject_falls_back_and_redo_during_run(monkeypatch):
    """Seedance 2.5 拒收（如含真人脸）→ 用关键帧自动改走 Seedance 1 Pro；整条生成收尾不覆盖期间单独重做过的镜头。"""
    import asyncio

    import httpx

    from app import canvas, production
    from app.adapters import fal
    from app.models import Node, Project
    req = httpx.Request("GET", "https://queue.fal.run/x")
    r = httpx.Response(422, json={"detail": [{"loc": ["body", "image_url"], "msg": "The image contains a real human face"}]}, request=req)
    assert "真人脸" in fal._message(r) and "image_url" in fal._message(r)

    calls = []

    async def ref(prompt, urls, duration=5):
        calls.append(("ref", prompt))
        return {"model": "bytedance/seedance-2.5/reference-to-video", "request_id": "r1"}

    async def i2v(prompt, image, duration=5, model=None, end_image=None):
        calls.append(("i2v", model, prompt))
        return {"model": model, "request_id": "r2"}

    async def wait(job, timeout_seconds=900):
        if job["request_id"] == "r1":
            return {"status": "failed", "error": "模型不接受含真人脸的图片（image_url：The image contains a real human face）", "rejected": True}
        return {"status": "completed", "video_url": "https://v.fal.media/ok.mp4"}
    monkeypatch.setattr(fal, "submit_ref", ref)
    monkeypatch.setattr(fal, "submit_i2v", i2v)
    monkeypatch.setattr(fal, "wait", wait)
    monkeypatch.setattr(settings_store, "video_provider", lambda: "fal")
    async def ref(prompt, urls, duration=5, model=None):
        calls.append(("ref", model))
        # 2.5 全能参考拒收；2.0 全能参考也拒收 → 最后走 2.0 图生视频
        return {"model": model or "bytedance/seedance-2.5/reference-to-video", "request_id": "r1"}
    monkeypatch.setattr(fal, "submit_ref", ref)
    async def kling(prompt, start, imgs, duration=5, end_image=None):
        calls.append(("kling", prompt, start, imgs))
        return {"model": fal.FACE_REF, "request_id": "r3"}
    monkeypatch.setattr(fal, "submit_kling_ref", kling)
    # 真人脸：2.0 也会拒收，直接走可灵 O3 Pro 全能参考（关键帧做开场，商品图作为 @Element1）
    res = asyncio.run(production.clip("@Image1 is the opening frame. The phone is the one in @Image2 and @Image3.", "data:kf", ["data:kf", "b", "c"]))
    assert res["video_url"] == "https://v.fal.media/ok.mp4" and "可灵 O3 Pro 全能参考" in res["fallback"]
    k = next(x for x in calls if x[0] == "kling")
    assert k[2] == "data:kf" and k[3] == ["b", "c"] and "@Element1" in k[1] and "@Image" not in k[1]
    assert not any(x == ("ref", fal.FALLBACK_REF) for x in calls)

    # 其他原因被拒：退回 Seedance 2.0（全能参考 → 图生视频）
    calls.clear()

    async def wait2(job, timeout_seconds=900):
        if job["request_id"] == "r1":
            return {"status": "failed", "error": "模型不接受这些参数（duration：bad value）", "rejected": True}
        return {"status": "completed", "video_url": "https://v.fal.media/ok.mp4"}
    monkeypatch.setattr(fal, "wait", wait2)
    res = asyncio.run(production.clip("@Image1 is the opening frame. The phone is the one in @Image2 and @Image3.", "data:image/jpeg;base64,xx", ["a", "b"]))
    assert res["video_url"] == "https://v.fal.media/ok.mp4" and "Seedance 2.0 图生视频" in res["fallback"]
    assert calls[1] == ("ref", fal.FALLBACK_REF) and calls[2][1] == fal.FALLBACK_I2V == "bytedance/seedance-2.0/image-to-video" and "@Image" not in calls[2][2]

    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "并行"}).json()["id"]
        with SessionLocal() as db:
            v = canvas.create_node(db, db.get(Project, pid), "video", status="run", data={"stage": "单镜修改", "tasks": [
                {"shot": 1, "phase": "关键帧待确认", "keyframe": "/new.png", "redo_seq": 5.0}, {"shot": 2, "phase": "完成", "url": "https://x/2.mp4"}]})
            db.commit()
            vid = v.id
        # 整条生成算出来的结果（第 1 镜是旧的失败结果）
        production._finalize(vid, {}, [["3", "a"], ["4", "b"]], [{"shot": 1, "phase": "失败", "status": "failed"}, {"shot": 2, "phase": "完成", "url": "https://x/2.mp4"}])
        with SessionLocal() as db:
            n = db.get(Node, vid)
            assert n.data["tasks"][0]["keyframe"] == "/new.png" and n.status == "input"


def test_video_plan_and_redo_with_choices(monkeypatch):
    """重做视频浮窗：读上一轮的模式 / 模型 / 提示词，切模式出新提示词，按建议改写；按选的模型和模式重新生成。"""
    import time

    from app import canvas, config, production
    from app.adapters import fal
    from app.models import Asset, Node, Project
    import cv2
    import numpy as np
    kdir = config.MEDIA_DIR / "keyframes"
    kdir.mkdir(parents=True, exist_ok=True)
    for name in ("vp1.png", "vp2.png"):
        cv2.imwrite(str(kdir / name), np.full((1280, 720, 3), 90, np.uint8))
    calls = []

    async def kling_i2v(prompt, image, duration=5, end_image=None):
        calls.append(("kling_i2v", prompt, bool(end_image)))
        return {"model": fal.FACE_I2V, "request_id": "k"}

    async def wait(job, timeout_seconds=900):
        return {"status": "completed", "video_url": "https://v.fal.media/k.mp4"}
    monkeypatch.setattr(fal, "submit_kling_i2v", kling_i2v)
    monkeypatch.setattr(fal, "wait", wait)
    monkeypatch.setattr(settings_store, "video_provider", lambda: "fal")
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "浮窗"}).json()["id"]
        with SessionLocal() as db:
            db.add(Asset(id="as_vp", kind="product", name="TECNO Pova 8 Pro", description="", images=["/api/v1/media/keyframes/vp1.png"], tags=[],
                         data={"views": {"/api/v1/media/keyframes/vp1.png": {"view": "back"}}}, source="upload", status="ready"))
            sc = canvas.create_node(db, db.get(Project, pid), "script", status="pass", data={"shots": [["3", "男主拿着手机", "Look!", ""], ["4", "街景", "Go", ""]],
                "cast": {"genre": "情景剧", "roles": {"r1": "x"}, "scenes": {}, "names": {}, "product": "as_vp", "specs": [
                    {"shot": 0, "size": "MS", "move": "固定", "roles": ["r1"], "scene": None, "product": True, "product_tier": "hand", "line": "Look!"},
                    {"shot": 1, "size": "WS", "move": "推", "roles": [], "scene": None, "product": False, "line": "Go"}]}})
            db.flush()
            v = canvas.create_node(db, db.get(Project, pid), "video", status="failed", data={"script_id": sc.id, "stage": "完成", "shots": sc.data["shots"], "tasks": [
                {"shot": 1, "phase": "失败", "status": "failed", "keyframe": "/api/v1/media/keyframes/vp1.png", "clip_mode": "ref", "model": "bytedance/seedance-2.5/reference-to-video",
                 "clip_prompt": "@Image1 is the opening frame ... 上一轮", "error": "模型不接受含真人脸的图片", "qc": {"status": "fail", "checks": {}, "issues": ["手机正反面不对"]}},
                {"shot": 2, "phase": "完成", "status": "completed", "keyframe": "/api/v1/media/keyframes/vp2.png", "url": "https://x/2.mp4"}]})
            db.commit()
            vid = v.id
        p = c.post(f"/api/v1/nodes/{vid}/shots/0/video-plan", json={}).json()
        assert p["mode"] == "ref" and set(p["modes"]) == {"ref", "first", "first_last"} and p["last"]["prompt"].endswith("上一轮")
        assert p["last"]["issues"] == ["手机正反面不对"] and "kling" in p["engines"] and p["refs"][0]["url"].endswith("vp1.png")
        p2 = c.post(f"/api/v1/nodes/{vid}/shots/0/video-plan", json={"mode": "first_last"}).json()
        assert p2["mode"] == "first_last" and p2["refs"][-1]["url"].endswith("vp2.png") and "last frame" in p2["prompt"]
        p3 = c.post(f"/api/v1/nodes/{vid}/shots/0/video-plan", json={"mode": "first", "prompt": "Man holds phone.", "suggestion": "动作慢一点"}).json()
        assert "动作慢一点" in p3["prompt"]  # 没配大模型时把建议附在后面
        assert c.post(f"/api/v1/nodes/{vid}/shots/0/clip", json={"engine": "nope"}).status_code == 400
        r = c.post(f"/api/v1/nodes/{vid}/shots/0/clip", json={"prompt": "Man holds the phone, slow.", "mode": "first_last", "engine": "kling", "comment": "慢一点"})
        assert r.status_code == 200
        for _ in range(100):
            with SessionLocal() as db:
                t = db.get(Node, vid).data["tasks"][0]
            if t.get("phase") == "完成":
                break
            time.sleep(0.05)
        assert t["phase"] == "完成" and t["clip_mode"] == "first_last" and t["engine_choice"] == "kling" and t["clip_prompt"] == "Man holds the phone, slow."
        assert calls == [("kling_i2v", "Man holds the phone, slow.", True)]


def test_fal_failure_always_has_reason(monkeypatch):
    """可灵 / fal 任务「完成」但没给视频、或 FAILED 只带 error 字段：都要写出原因，不能是空的。"""
    import asyncio as _a

    import httpx as _h

    from app.adapters import fal as _fal

    def run(status: dict, result: dict) -> dict:
        def handler(req):
            return _h.Response(200, json=status if req.url.path.endswith("/status") else result)
        monkeypatch.setattr(_fal, "transport", _h.MockTransport(handler))
        monkeypatch.setattr(_fal, "_headers", lambda key=None: {})
        job = {"model": _fal.FACE_REF, "status_url": "https://q.test/r/1/status", "response_url": "https://q.test/r/1"}
        return _a.run(_fal.wait(job, 5))

    r = run({"status": "COMPLETED"}, {"detail": "content moderation"})
    assert r["status"] == "failed" and "没有返回视频" in r["error"] and "content moderation" in r["error"]
    r = run({"status": "FAILED", "error": "Kling internal error"}, {})
    assert r["status"] == "failed" and "Kling internal error" in r["error"]


def test_fal_polling_survives_network_blips(monkeypatch):
    """视频在 fal 那边生成要几分钟：轮询中途网络断一两下不能判失败；一直连不上才报错。"""
    import asyncio as _a

    import httpx as _h

    from app.adapters import fal as _fal
    monkeypatch.setattr(_fal, "NET_RETRY_WAIT", 0.001)
    monkeypatch.setattr(_fal, "POLL_SECONDS", 0.001)
    monkeypatch.setattr(_fal, "_headers", lambda key=None: {})
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] in (2, 3):
            raise _h.ConnectError("All connection attempts failed")
        if req.url.path.endswith("/status"):
            return _h.Response(200, json={"status": "IN_PROGRESS" if calls["n"] < 5 else "COMPLETED"})
        return _h.Response(200, json={"video": {"url": "https://v.fal/x.mp4"}})

    monkeypatch.setattr(_fal, "transport", _h.MockTransport(handler))
    job = {"model": _fal.FACE_REF, "status_url": "https://q.test/r/1/status", "response_url": "https://q.test/r/1"}
    assert _a.run(_fal.wait(job, 5))["video_url"] == "https://v.fal/x.mp4"

    def down(req):
        raise _h.ConnectError("All connection attempts failed")
    monkeypatch.setattr(_fal, "transport", _h.MockTransport(down))
    try:
        _a.run(_fal.wait(job, 5))
        raise AssertionError("应该报错")
    except _h.ConnectError as e:
        assert "HTTPS_PROXY" in _fal.describe(e)
