"""关键帧局部重绘：只改涂过的地方（遮罩外像素和原图一致），旧版本可撤回；FLUX Fill 和 Gemini 两种方式。"""
import asyncio
import base64
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

import cv2  # noqa: E402
import httpx  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import canvas, config, inpaint, production, settings_store  # noqa: E402
from app.adapters import fal, llm  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Node, Project  # noqa: E402


def _png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def test_inpaint_only_changes_masked_area(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    (tmp_path / "keyframes").mkdir()
    orig = np.full((640, 360, 3), (200, 120, 40), np.uint8)
    cv2.imwrite(str(tmp_path / "keyframes" / "k0.png"), orig)
    red = _png(np.full((640, 360, 3), (0, 0, 255), np.uint8))  # 模型「重画」出来的整张图都是红的
    mask = np.zeros((640, 360, 4), np.uint8)
    mask[200:400, 100:260, 3] = 255  # 只涂了中间一块
    mask_url = "data:image/png;base64," + base64.b64encode(_png(mask)).decode()
    sent = {}

    def fal_handler(req):
        if req.method == "POST":
            import json
            sent["body"] = json.loads(req.content)
            return httpx.Response(200, json={"request_id": "r1"})
        if req.url.path.endswith("/status"):
            return httpx.Response(200, json={"status": "COMPLETED"})
        if req.url.host == "v3.fal.media":
            return httpx.Response(200, content=red)
        return httpx.Response(200, json={"images": [{"url": "https://v3.fal.media/files/out.png"}]})

    monkeypatch.setattr(fal, "transport", httpx.MockTransport(fal_handler))
    monkeypatch.setattr(inpaint, "transport", httpx.MockTransport(fal_handler))
    monkeypatch.setattr(fal, "_headers", lambda key=None: {})
    monkeypatch.setattr(fal, "POLL_SECONDS", 0.001)
    monkeypatch.setattr(settings_store, "get_secret", lambda name: "k" if name == "fal" else None)
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "局部重绘"}).json()["id"]
        with SessionLocal() as db:
            p = db.get(Project, pid)
            s = canvas.create_node(db, p, "script", data={"shots": [["0–2s", "两人站着", "hi", ""]], "cast": {"roles": {}, "scenes": {}, "specs": [{}], "product": None}})
            v = canvas.create_node(db, p, "video", status="wait", data={"script_id": s.id, "shots": [["0–2s", "两人站着", "hi", ""]],
                                                                       "tasks": [{"shot": 1, "keyframe": "/api/v1/media/keyframes/k0.png", "phase": "完成",
                                                                                  "status": "completed", "url": "https://v/1.mp4"}]})
            canvas.connect(db, pid, s.id, v.id)
            db.commit()
            vid = v.id
        assert c.post(f"/api/v1/nodes/{vid}/shots/0/inpaint", json={"mask": mask_url, "prompt": " "}).status_code == 400
        asyncio.run(production._inpaint_keyframe(vid, 0, mask_url, "把手里的东西换成一部手机", "flux"))
        with SessionLocal() as db:
            t = db.get(Node, vid).data["tasks"][0]
        assert sent["body"]["prompt"] == "把手里的东西换成一部手机" and sent["body"]["mask_url"].startswith("data:image/png")
        assert t["keyframe"] != "/api/v1/media/keyframes/k0.png" and t["kf_history"] == ["/api/v1/media/keyframes/k0.png"]
        assert t["phase"] == "关键帧待确认" and t["url"] is None and t["kf_edits"][-1]["engine"] == "flux"
        out = cv2.imread(str(tmp_path / "keyframes" / t["keyframe"].rsplit("/", 1)[1]))
        assert (out[20:150, 20:340] == orig[20:150, 20:340]).all() and (out[500:620] == orig[500:620]).all()  # 没涂的地方一个像素都不变
        assert out[300, 180, 2] > 230 and out[300, 180, 0] < 30  # 涂过的地方换成新画的

        # Gemini：带商品图时走 Gemini，看到原图 + 标红的遮罩图
        got = {}

        async def fake_image(content, task="keyframe", **kw):
            got["n"] = len(content)
            got["text"] = content[0]["text"]
            return red, "image/png"
        monkeypatch.setattr(llm, "image", fake_image)
        asyncio.run(production._inpaint_keyframe(vid, 0, mask_url, "手机换成正面朝镜头", "gemini"))
        with SessionLocal() as db:
            t = db.get(Node, vid).data["tasks"][0]
        assert got["n"] == 3 and "highlighted in red" in got["text"] and len(t["kf_history"]) == 2

        # 撤回两次回到原图；再撤回没有版本了
        assert c.post(f"/api/v1/nodes/{vid}/shots/0/keyframe-undo").status_code == 200
        assert c.post(f"/api/v1/nodes/{vid}/shots/0/keyframe-undo").json()["keyframe"] == "/api/v1/media/keyframes/k0.png"
        assert c.post(f"/api/v1/nodes/{vid}/shots/0/keyframe-undo").status_code == 400

        # 涂了个空遮罩：报原因，关键帧和视频状态不动
        empty = "data:image/png;base64," + base64.b64encode(_png(np.zeros((640, 360, 4), np.uint8))).decode()
        asyncio.run(production._inpaint_keyframe(vid, 0, empty, "随便", "flux"))
        with SessionLocal() as db:
            t = db.get(Node, vid).data["tasks"][0]
        assert "遮罩是空的" in t["keyframe_error"] and t["keyframe"] == "/api/v1/media/keyframes/k0.png"
