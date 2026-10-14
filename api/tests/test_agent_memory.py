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

    async def i2v(prompt, image, duration=5, model=None):
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
