"""分镜重画：看到这一镜的提示词，改了按改过的画，之后整体重画也沿用；画面描述改了就回到默认。"""
import asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app import canvas, settings_store, storyboard  # noqa: E402
from app.adapters import llm  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Node, Project  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def test_redraw_with_custom_prompt(monkeypatch):
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    sent = []

    async def fake_image(content, task="storyboard", **kw):
        sent.append(content if isinstance(content, str) else content[0]["text"])
        return PNG, "image/png"

    monkeypatch.setattr(llm, "image", fake_image)
    monkeypatch.setattr("app.routers.ops.spawn", lambda coro: coro.close())
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "分镜提示词"}).json()["id"]
        with SessionLocal() as db:
            shots = [["0–3s", "女孩在雨里跑", "Rain!", ""], ["3–6s", "女孩甩掉手机上的水", "No wahala", ""]]
            nid = canvas.create_node(db, db.get(Project, pid), "script", data={"shots": shots, "audience": "学生"}).id
            db.commit()
        asyncio.run(storyboard.run(nid))
        p = c.get(f"/api/v1/nodes/{nid}/storyboard/1/prompt").json()
        assert not p["custom"] and p["has_ref"] and "女孩甩掉手机上的水" in p["prompt"] and p["prompt"] == p["default"]
        mine = p["default"] + "\n她穿黄色雨衣，背景是霓虹灯。"
        assert c.post(f"/api/v1/nodes/{nid}/storyboard", json={"indices": [0, 1], "prompt": "x"}).status_code == 400
        assert c.post(f"/api/v1/nodes/{nid}/storyboard", json={"indices": [1], "prompt": mine}).status_code == 200
        asyncio.run(storyboard.run(nid, [1], {1: mine}))
        assert sent[-1] == mine
        p = c.get(f"/api/v1/nodes/{nid}/storyboard/1/prompt").json()
        assert p["custom"] and p["prompt"] == mine
        asyncio.run(storyboard.run(nid, [0, 1]))  # 全部重画：第 2 镜沿用改过的
        assert mine in sent[-2:]
        with SessionLocal() as db:  # 画面描述改了：改过的提示词作废，回到按新描述拼的默认
            n = db.get(Node, nid)
            n.data = {**n.data, "shots": [shots[0], ["3–6s", "女孩在屋檐下打电话", "No wahala", ""]]}
            db.commit()
        p = c.get(f"/api/v1/nodes/{nid}/storyboard/1/prompt").json()
        assert not p["custom"] and p["stale"] and "屋檐下打电话" in p["prompt"]
