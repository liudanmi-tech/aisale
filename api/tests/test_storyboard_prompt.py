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


def test_storyboard_follows_reference_frame(monkeypatch, tmp_path):
    """洗稿剧本画分镜：原片对应那一帧作为第 1 张参考图，照它的景别、站位、手机朝向画；有人出镜的「产品」镜头不改成手机特写。"""
    from app import config
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    (tmp_path / "breakdown").mkdir()
    (tmp_path / "breakdown" / "31-000.jpg").write_bytes(PNG)
    sent = []

    async def fake_image(content, task="storyboard", **kw):
        sent.append(content)
        return PNG, "image/png"

    monkeypatch.setattr(llm, "image", fake_image)
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "照原片构图"}).json()["id"]
        ref = [{"t": "0–2s", "frame": "/api/v1/media/breakdown/31-000.jpg", "camera": "中景、正面平视、固定", "people": "一男一女",
                "framing": "两人并排站在画面中央，黄色铲车在后方正对镜头", "phone_facing": "屏幕", "product": False}]
        with SessionLocal() as db:
            shots = [["0–2s", "两人站在空地上举着手机，背后铲车", "Can your phone?", ""], ["2–4s", "手机特写", "6000mAh", ""]]
            nid = canvas.create_node(db, db.get(Project, pid), "script", data={"shots": shots, "product_shots": [0, 1], "wash": {
                "ref_no": None, "tier": "high", "ref": ref, "map": [{"ref": 1}, {"ref": None}]}}).id
            db.commit()
        asyncio.run(storyboard.run(nid))
        first = sent[0]
        assert isinstance(first, list) and first[1]["image_url"]["url"].startswith("data:image/")  # 原片这一帧
        text = first[0]["text"]
        assert "第 1 张参考图是原片第 1 镜" in text and "中景、正面平视" in text and "铲车在后方正对镜头" in text and "屏幕" in text
        assert "不要改成手机特写" in text and "这一镜是产品特写" not in text  # 有人出镜：按原片景别
        second = sent[1]  # 没有对应原片的镜头：只参考本片第 1 镜，仍是产品特写
        assert len(second) == 2 and "这一镜是产品特写" in second[0]["text"] and "原片" not in second[0]["text"]
        p = c.get(f"/api/v1/nodes/{nid}/storyboard/0/prompt").json()
        assert p["ref_no"] == 1 and p["ref_frame"].endswith("31-000.jpg")
