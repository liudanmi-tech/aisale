"""爆款多模态拆解（真视频抽帧 + 模型逐镜拆）和按拆解洗剧本（清单 → 剧本 → 相似度）。"""
import asyncio
import base64
import json
import os
import subprocess

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import breakdown, canvas, compose, settings_store, storyboard, wash, workflows  # noqa: E402
from app.adapters import llm  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Node, Project, RefAd, new_id  # noqa: E402

REF_SHOTS = [
    {"t": "0–2s", "scene": "雨夜街头", "people": "主角", "action": "举着手机问", "camera": "近景", "line": "Can your phone ever survive this?",
     "emotion": "焦虑", "beat": "钩子", "product": False},
    {"t": "2–6s", "scene": "公交车站", "people": "主角", "action": "手机淋雨", "camera": "中景", "line": "Rain, mud, water", "emotion": "紧张", "beat": "冲突", "product": False},
    {"t": "6–10s", "scene": "木桌", "people": "无", "action": "手机特写", "camera": "特写", "line": "IP68 tough", "emotion": "自信", "beat": "产品展示", "product": True},
    {"t": "10–14s", "scene": "街边", "people": "主角和朋友", "action": "比赞", "camera": "中景", "line": "Get yours now", "emotion": "开心", "beat": "行动号召", "product": False},
]


def _ad(no_offset: int = 0, **dna) -> int:
    with SessionLocal() as db:
        no = max([n for (n,) in db.query(RefAd.no)] or [0]) + 1 + no_offset
        db.add(RefAd(id=new_id("ad"), no=no, source="TikTok 账号监控", platform="TikTok", brand="小米", market="尼日利亚", title="Can your phone survive",
                     hook="提问", selling_point="续航", days_running=1, variants=1, ctr_range="未公开", vtr=0, is_estimated=False, hot_score=80, dna=dna))
        db.commit()
    return no


@pytest.mark.skipif(not compose.ffmpeg_exe(), reason="没有 ffmpeg")
def test_breakdown_reads_frames(tmp_path, monkeypatch):
    clip = tmp_path / "in.mp4"
    subprocess.run([compose.ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x568:d=6:r=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
    seen = {}

    async def fake_chat(messages, **kw):
        parts = messages[1]["content"]
        seen["images"] = sum(1 for p in parts if p["type"] == "image_url")
        seen["audio"] = any(p["type"] == "input_audio" for p in parts)
        seen["task"] = kw.get("task")
        return {"content": json.dumps({"summary": "雨天手机", "duration": 6, "shots": REF_SHOTS[:2], "essence": ["前 2 秒提问"], "replaceable": ["机型"]})}

    monkeypatch.setattr(llm, "chat", fake_chat)
    with TestClient(app) as c:
        no = _ad(url="")
        monkeypatch.setattr(breakdown, "spawn", lambda coro: coro.close())  # 测试里同步跑
        breakdown.upload_path(no).unlink(missing_ok=True)
        assert c.post(f"/api/v1/ref-ads/{no}/breakdown", json={}).status_code == 400  # 没链接也没上传
        data = "data:video/mp4;base64," + base64.b64encode(clip.read_bytes()).decode()
        assert c.post(f"/api/v1/ref-ads/{no}/breakdown", json={"video": data}).json()["dna"]["breakdown_status"] == "running"
        asyncio.run(breakdown.run(no))
        dna = c.get(f"/api/v1/ref-ads/{no}").json()["dna"]
    assert dna["breakdown_status"] == "done", dna.get("breakdown_error")
    bd = dna["breakdown"]
    assert seen == {"images": len(bd["frames"]), "audio": True, "task": "analysis"} and 5 <= len(bd["frames"]) <= 7
    assert bd["inputs"][0] == "人工上传的视频" and "音轨" in bd["inputs"]
    assert all(s["frame"].startswith("/api/v1/media/breakdown/") for s in bd["shots"]) and abs(bd["video_duration"] - 6) < 0.5


def test_wash_script_follows_breakdown(monkeypatch):
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    monkeypatch.setattr(workflows, "spawn", lambda coro: coro.close())  # 不接着画分镜
    calls = []
    new_shots = [[3, "内罗毕马塔图车站，女孩举着手机", "Si hii simu inaweza?", "这手机扛得住吗？"],
                 [4, "女孩在雨里", "Mvua kubwa leo", "今天雨好大"],
                 [3, "空的台面上手机特写", "6000mAh battery", "6000mAh 大电池"],
                 [4, "朋友们比赞", "Nunua sasa", "现在就买"]]

    async def fake_json(system, user, task="script", timeout=90):
        calls.append((system, user))
        if "列出洗稿清单" in system:
            return {"keep": ["前 2 秒反问痛点", "第 3 镜产品特写"], "replace": ["小米 → TECNO POVA 6", "拉各斯 → 内罗毕"]}
        if len([x for x in calls if "列出洗稿清单" not in x[0]]) == 1:  # 第一版：第 1 镜照抄了参考原话
            return {"shots": [[3, "女孩举着手机", "Can your phone ever survive this?", ""], *new_shots[1:]],
                    "map": [{"ref": 1, "kept": "提问钩子", "changed": "场景"}] * 4, "product_shots": [3]}
        return {"shots": new_shots, "map": [{"ref": k + 1, "kept": "提问钩子", "changed": "场景和语言"} for k in range(4)], "product_shots": [3]}

    monkeypatch.setattr(llm, "chat_json", fake_json)
    with TestClient(app) as c:
        no = _ad(url="https://www.tiktok.com/@x/video/1", breakdown={"shots": REF_SHOTS, "video_duration": 14, "summary": "雨天"})
        pid = c.post("/api/v1/projects", json={"name": "洗剧本", "market": "肯尼亚"}).json()["id"]
        with SessionLocal() as db:
            n = canvas.create_node(db, db.get(Project, pid), "script", data={"ref_ad_no": no, "selling_point": "续航", "audience": "学生"})
            db.commit()
            nid = n.id
        asyncio.run(workflows.generate_script(nid))
        with SessionLocal() as db:
            d = db.get(Node, nid).data
            sub = db.get(Node, nid).sub
        assert d["wash"]["plan"]["replace"] == ["小米 → TECNO POVA 6", "拉各斯 → 内罗毕"] and d["wash"]["ref_shots"] == 4
        assert d["shots"][0][2] == "Si hii simu inaweza?"  # 太像参考那一版被重写掉了
        assert d["wash"]["similarity"]["rewrote"] == [1] and d["similarity"]["line_max"] < wash.THRESHOLD
        assert d["product_shots"] == [2] and storyboard.product_shots(d, 4) == {2} and "14s" in sub
        assert [m["ref"] for m in d["wash"]["map"]] == [1, 2, 3, 4]
        assert sum(1 for x in calls if "列出洗稿清单" in x[0]) == 1

        # 改清单后重写：不再重新出清单，用改过的
        r = c.post(f"/api/v1/nodes/{nid}/wash-plan", json={"keep": ["保留提问钩子"], "replace": ["小米 → TECNO SPARK 30", " "]})
        assert r.status_code == 200
        with SessionLocal() as db:
            db.get(Node, nid).status = "wait"
            db.commit()
        asyncio.run(workflows.generate_script(nid))
        with SessionLocal() as db:
            d = db.get(Node, nid).data
        assert d["wash"]["plan"] == {"keep": ["保留提问钩子"], "replace": ["小米 → TECNO SPARK 30"]} and d["wash"]["plan_edited"]
        assert sum(1 for x in calls if "列出洗稿清单" in x[0]) == 1 and "TECNO SPARK 30" in calls[-1][1]


def test_similarity_is_real():
    s = wash.similarity([["0–3s", "雨夜街头举着手机问", "Can your phone ever survive this?", ""]], {"shots": REF_SHOTS})
    assert s["line_max"] == 1.0 and s["visual_max"] > 0.5
    s = wash.similarity([["0–3s", "厨房", "Totally new words here", ""]], None, {"text": "Can your phone ever survive this?"})
    assert s["line_max"] < 0.4 and not s["has_breakdown"]
    assert wash._ratio("Mvua kubwa leo", "Rain, mud, water") == 0 and wash._ratio("Can your phone survive dis?", "Can your phone ever survive this?") > 0.6
