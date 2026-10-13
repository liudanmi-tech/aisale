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
        assert d["skipped_text"] == ([] if compose.font_file(cjk=True) else [3])  # 没有中文字体：只有中文贴片那一镜不烧

        # 片段没齐（有一镜还没出视频）：报出是哪一镜，不出半截成片
        with SessionLocal() as db:
            v = db.get(Node, (db.get(Node, cid).data or {})["video_id"])
            v.data = {**v.data, "tasks": [{"url": list(clips)[0]}, {"url": ""}, {"url": list(clips)[2]}]}
            db.commit()
        asyncio.run(compose.run(cid))
        with SessionLocal() as db:
            n = db.get(Node, cid)
            assert n.status == "failed" and "第 2 镜" in n.data["error"]

        # 有关键帧、没视频的镜头（例如商品镜头等人工确认）：用关键帧静帧占位，照样出完整成片，但不自动进评测
        import cv2
        import numpy as np
        kdir = config.MEDIA_DIR / "keyframes"
        kdir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(kdir / "test-kf.png"), np.full((1280, 720, 3), 200, np.uint8))
        advanced.clear()
        with SessionLocal() as db:
            v = db.get(Node, (db.get(Node, cid).data or {})["video_id"])
            v.data = {**v.data, "tasks": [{"url": list(clips)[0]}, {"url": "", "keyframe": "/api/v1/media/keyframes/test-kf.png"}, {"url": list(clips)[2]}]}
            db.commit()
        asyncio.run(compose.run(cid))
        with SessionLocal() as db:
            n = db.get(Node, cid)
            assert n.status == "pass" and n.data["stills"] == [2] and "暂用关键帧" in n.sub and advanced == []
            assert abs(_probe(config.MEDIA_DIR / "cuts" / n.data["video_url"].rsplit("/", 1)[1])["duration"] - 7.5) < 0.3


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


def test_backfill_old_projects():
    """成片节点上线前就通过的视频：启动时补上成片节点；原来已经评测过的不再自动重跑评测。"""
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "老项目"}).json()["id"]
        with SessionLocal() as db:
            project = db.get(Project, pid)
            v1 = canvas.create_node(db, project, "video", status="pass", data={"tasks": []})
            v2 = canvas.create_node(db, project, "video", status="wait", data={"tasks": []})
            ev = canvas.create_node(db, project, "eval", status="wait")
            canvas.connect(db, pid, v1.id, ev.id)
            project.flags = {**(project.flags or {}), "cuts_backfilled": False}
            db.commit()
            made = agent.backfill_cuts(db)
            cuts = canvas.nodes_of(db, pid, "cut")
            assert len(cuts) == 1 and cuts[0].id in made and cuts[0].data["video_id"] == v1.id and v2.id not in str(cuts[0].data)
            assert any(n.type == "cut" for n in canvas.downstream(db, v1.id))
            cuts[0].status = "pass"
            assert agent.auto_advance(db, project, cuts[0]) == [] and len(canvas.nodes_of(db, pid, "eval")) == 1
            assert agent.backfill_cuts(db) == []  # 每个项目只补一次
        # 聊天说「合成成片」：已有成片的重新合成
        P = f"/api/v1/projects/{pid}"
        c.post(P + "/agent/chat", json={"text": "合成成片"})
        assert "开始合成" in c.get(P + "/chat").json()[-1]["text"]


def test_delete_and_undo():
    """画布上任何节点都能删，删掉的节点、连线、待审核任务撤销后原样恢复。"""
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "删除"}).json()["id"]
        P = f"/api/v1/projects/{pid}"
        canvas_ = lambda: c.get(P + "/canvas").json()  # noqa: E731
        before = canvas_()
        sp = next(n for n in before["nodes"] if n["type"] == "sp")
        n_edges = len(before["edges"])
        r = c.post(P + "/nodes/delete", json={"ids": [sp["id"]]}).json()
        assert r["deleted"] == [sp["id"]]
        after = canvas_()
        assert all(n["id"] != sp["id"] for n in after["nodes"]) and all(sp["id"] not in (e["source"], e["target"]) for e in after["edges"])
        assert c.post(P + "/undo").json()["ok"]
        back = canvas_()
        n = next(n for n in back["nodes"] if n["id"] == sp["id"])
        assert (n["title"], n["x"], n["y"], n["data"]) == (sp["title"], sp["x"], sp["y"], sp["data"]) and len(back["edges"]) == n_edges
        assert c.post(P + "/nodes/delete", json={"ids": ["nope"]}).status_code == 404
