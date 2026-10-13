"""成片合成：每镜片段按剧本时长剪好、顺序拼成 9:16 成片，烧上口播字幕和贴片（用真的 ffmpeg）。"""
import asyncio
import json
import os
import subprocess

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import agent, canvas, compose, config  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Node, Project  # noqa: E402

pytestmark = pytest.mark.skipif(not compose.ffmpeg_exe(), reason="没有 ffmpeg")


def _clip(path, color: str, secs: float, size="480x854") -> bytes:
    subprocess.run([compose.ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}:d={secs}:r=24",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path.read_bytes()


def _probe(path) -> dict:
    """用 ffmpeg 自己读出时长和画面尺寸（imageio-ffmpeg 不带 ffprobe）。"""
    p = subprocess.run([compose.ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    import re
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    s = re.search(r"Video: .*?(\d{3,4})x(\d{3,4})", p.stderr)
    return {"duration": int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]), "w": int(s[1]), "h": int(s[2])}


def test_compose_real_clips(tmp_path, monkeypatch):
    # 片段比剧本时长长（模型常出 5 秒），横竖比例也不一样：要剪到剧本时长、裁成 720×1280
    clips = {f"https://cdn.test/s{k}.mp4": _clip(tmp_path / f"in{k}.mp4", c, 5, size)
             for k, (c, size) in enumerate([("red", "480x854"), ("green", "640x360"), ("blue", "480x854")])}
    fetched = []

    def handler(req: httpx.Request) -> httpx.Response:
        fetched.append(str(req.url))
        return httpx.Response(200, content=clips[str(req.url)])

    monkeypatch.setattr(compose, "transport", httpx.MockTransport(handler))
    advanced = []
    monkeypatch.setattr(agent, "auto_advance", lambda db, project, node: advanced.append(node.id) or [])
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "成片测试"}).json()["id"]
        with SessionLocal() as db:
            project = db.get(Project, pid)
            script = canvas.create_node(db, project, "script", status="pass", data={
                "shots": [["2", "停电的夜市", "NEPA take light again!", ""], ["3s", "接单", "Phone still dey work", ""], ["0–2.5s", "产品", "6000mAh", ""]],
                "cast": {"specs": [{"overlay": ""}, {"overlay": ""}, {"overlay": "6000mAh 大电池"}]}})
            video = canvas.create_node(db, project, "video", status="pass", data={
                "script_id": script.id, "tasks": [{"url": u, "keyframe": None} for u in clips]})
            cut = canvas.create_node(db, project, "cut", data={"video_id": video.id, "captions": True})
            db.commit()
            cid = cut.id
        asyncio.run(compose.run(cid))
        with SessionLocal() as db:
            n = db.get(Node, cid)
            d = n.data
            assert n.status == "pass", d.get("error")
            assert advanced == [cid]  # 合成完交给 auto_advance 进评测
        assert sorted(fetched) == sorted(clips)
        assert [p["dur"] for p in d["parts"]] == [2.0, 3.0, 2.5] and d["duration"] == 7.5
        assert d["parts"][2]["overlay"] == "6000mAh 大电池" and d["parts"][0]["line"] == "NEPA take light again!"
        out = config.MEDIA_DIR / "cuts" / d["video_url"].rsplit("/", 1)[1]
        info = _probe(out)
        assert (info["w"], info["h"]) == (720, 1280)
        assert abs(info["duration"] - 7.5) < 0.3
        assert d["captions"] is True and d["burned"] == bool(compose.font_file())

        # 片段没齐（有一镜还没出视频）：报出是哪一镜，不出半截成片
        with SessionLocal() as db:
            v = db.get(Node, (db.get(Node, cid).data or {})["video_id"])
            v.data = {**v.data, "tasks": [{"url": list(clips)[0]}, {"url": ""}, {"url": list(clips)[2]}]}
            db.commit()
        asyncio.run(compose.run(cid))
        with SessionLocal() as db:
            n = db.get(Node, cid)
            assert n.status == "failed" and "第 2 镜" in n.data["error"]


def test_compose_endpoint_guards():
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "成片测试 2"}).json()["id"]
        with SessionLocal() as db:
            project = db.get(Project, pid)
            v = canvas.create_node(db, project, "video", status="pass")
            db.commit()
            vid = v.id
        assert c.post(f"/api/v1/nodes/{vid}/compose", json={}).status_code == 404
        assert json.loads(json.dumps(compose.secs("3–7s"))) == 4.0
