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
        if "所以先分析，再出清单" in system:
            return {"keep": ["前 2 秒反问痛点", "第 3 镜产品特写"], "replace": ["小米 → TECNO POVA 6", "拉各斯 → 内罗毕"]}
        if len([x for x in calls if "所以先分析，再出清单" not in x[0]]) == 1:  # 第一版：第 1 镜照抄了参考原话
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
        assert sum(1 for x in calls if "所以先分析，再出清单" in x[0]) == 1

        # 改清单后重写：不再重新出清单，用改过的
        r = c.post(f"/api/v1/nodes/{nid}/wash-plan", json={"keep": ["保留提问钩子"], "replace": ["小米 → TECNO SPARK 30", " "]})
        assert r.status_code == 200
        with SessionLocal() as db:
            db.get(Node, nid).status = "wait"
            db.commit()
        asyncio.run(workflows.generate_script(nid))
        with SessionLocal() as db:
            d = db.get(Node, nid).data
        assert (d["wash"]["plan"]["keep"], d["wash"]["plan"]["replace"]) == (["保留提问钩子"], ["小米 → TECNO SPARK 30"]) and d["wash"]["plan_edited"]
        assert sum(1 for x in calls if "所以先分析，再出清单" in x[0]) == 1 and "TECNO SPARK 30" in calls[-1][1]


def test_similarity_is_real():
    s = wash.similarity([["0–3s", "雨夜街头举着手机问", "Can your phone ever survive this?", ""]], {"shots": REF_SHOTS})
    assert s["line_max"] == 1.0 and s["visual_max"] > 0.5
    s = wash.similarity([["0–3s", "厨房", "Totally new words here", ""]], None, {"text": "Can your phone ever survive this?"})
    assert s["line_max"] < 0.4 and not s["has_breakdown"]
    assert wash._ratio("Mvua kubwa leo", "Rain, mud, water") == 0 and wash._ratio("Can your phone survive dis?", "Can your phone ever survive this?") > 0.6


def test_wash_keeps_core_hook(monkeypatch):
    """原片看点是「铲车倒一整斗水」：不能选更弱的方案；复查发现洗弱了就带着问题重写；可以换成自己写的方案。"""
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    monkeypatch.setattr(workflows, "spawn", lambda coro: coro.close())
    calls = []
    weak = [[3, "女孩拿着手机", "Your phone fit survive?", ""], [4, "朋友用水桶往手机上浇水", "Water dey come!", ""],
            [3, "空的台面上手机特写", "6000mAh", ""], [4, "大家比赞", "Buy am today", ""]]
    strong = [weak[0], [4, "农用无人机从空中对着手机猛喷", "Drone don come!", ""], *weak[2:]]

    async def fake_json(system, user, task="script", timeout=90):
        calls.append((system, user))
        if "所以先分析，再出清单" in system:
            return {"analysis": {"core": "用铲车往手机上倒一整斗水", "why": "规模荒诞，反差极大", "intensity": "工程机械级别", "must_not_lose": "考验规模远超日常"},
                    "options": [{"idea": "用水桶浇水", "intensity": "更弱"}, {"idea": "农用无人机从空中喷洒", "intensity": "更强"}, {"idea": "消防车高压水枪", "intensity": "相当"}],
                    "chosen": 1, "keep": ["保持工程级别的荒诞规模"], "replace": ["用铲车往手机上倒一整斗水 → 用水桶浇水", "小米 → TECNO"]}
        if "检查一版洗稿剧本" in system:
            bad = "水桶" in user
            return {"kept_core": not bad, "intensity": "更弱" if bad else "更强", "score": 2 if bad else 5,
                    "problems": "第 2 镜水桶浇水，反差没了" if bad else "", "fix": "改成无人机从空中喷"}
        written = [x for x in calls if "改写成我方剧本" in x[0]]
        return {"shots": weak if len(written) == 1 else strong, "map": [{"ref": k + 1, "kept": "", "changed": ""} for k in range(4)], "product_shots": [3]}

    monkeypatch.setattr(llm, "chat_json", fake_json)
    with TestClient(app) as c:
        no = _ad(url="https://www.tiktok.com/@x/video/2", breakdown={"shots": REF_SHOTS, "video_duration": 14})
        pid = c.post("/api/v1/projects", json={"name": "看点"}).json()["id"]
        with SessionLocal() as db:
            nid = canvas.create_node(db, db.get(Project, pid), "script", data={"ref_ad_no": no, "selling_point": "续航", "audience": "学生"}).id
            db.commit()
        asyncio.run(workflows.generate_script(nid))
        with SessionLocal() as db:
            w = db.get(Node, nid).data["wash"]
            shots = db.get(Node, nid).data["shots"]
        assert w["plan"]["chosen"] == 1  # 模型选了「更弱」的水桶，自动换成更强的无人机
        assert w["plan"]["analysis"]["core"] == "用铲车往手机上倒一整斗水"
        assert "无人机" in shots[1][1] and w["check"]["rewrote"] and w["check"]["score"] == 5
        assert any("核心看点分析" in u for s_, u in calls if "改写成我方剧本" in s_)

        # 自己写一个方案：替换清单第 1 条跟着换，按它重写
        assert c.post(f"/api/v1/nodes/{nid}/wash-plan", json={"idea": "直升机吊着水箱往下倒"}).status_code == 200
        with SessionLocal() as db:
            p = db.get(Node, nid).data["wash"]["plan"]
        assert p["replace"][0] == "用铲车往手机上倒一整斗水 → 直升机吊着水箱往下倒" and p["options"][p["chosen"]]["idea"] == "直升机吊着水箱往下倒"
        assert "小米 → TECNO" in p["replace"] and len(p["replace"]) == 2


def test_fit_recommends_tier():
    from app import wash_plan
    same = wash_plan.fit({"market": "尼日利亚", "selling_point": "续航"}, {"market": "尼日利亚", "selling_point": "6000mAh 大电池续航"},
                         {"audience": {"match": "match"}, "product": {"match": "match"}})
    assert same["recommended"] == "high" and same["score"] == 1.0
    mid = wash_plan.fit({"market": "肯尼亚", "breakdown": {"selling_point": "防水耐用"}}, {"market": "尼日利亚", "selling_point": "续航"},
                        {"audience": {"match": "match"}, "product": {"match": "partial"}})
    assert mid["items"]["market"]["match"] == "partial" and mid["items"]["selling_point"]["match"] == "no" and mid["recommended"] == "low"
    assert "推荐" in mid["reason"]


def test_wash_node_confirm_then_script(monkeypatch):
    """洗稿方案节点：六行表按档位定保留 / 替换；换档位时人改过的行不动；确认后剧本按表写，高档不按相似度拦，但查竞品品牌。"""
    from app import wash_plan
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    monkeypatch.setattr(workflows, "spawn", lambda coro: coro.close())
    calls = []
    rows = {k: {"ref": f"原片{k}", "ours": f"我方{k}", "why": "因为"} for k, _ in wash_plan.ROWS}

    async def fake_json(system, user, task="script", timeout=90):
        calls.append((system, user))
        if "洗稿方案" in system and "六个要素" in system:
            return {"rows": rows, "audience_fit": {"match": "match"}, "product_fit": {"match": "partial"},
                    "analysis": {"core": "铲车倒水", "why": "反差", "intensity": "工程级", "must_not_lose": "规模"},
                    "options": [{"idea": "水桶浇水", "intensity": "更弱"}, {"idea": "无人机喷水", "intensity": "更强"}], "chosen": 1}
        if "检查一版洗稿剧本" in system:
            return {"kept_core": True, "intensity": "相当", "score": 4, "problems": "", "fix": ""}
        first = sum(1 for s_, _ in calls if "改写成我方剧本" in s_) == 1
        line = "Redmi no fit!" if first else "Can your phone ever survive this?"  # 第一版留着竞品品牌；高档台词像原片也不拦
        return {"shots": [[3, "女孩举着手机", line, ""], [4, "无人机喷水", "Water!", ""], [3, "手机特写", "6000mAh", ""], [4, "比赞", "Buy", ""]],
                "map": [{"ref": k + 1, "kept": "", "changed": ""} for k in range(4)], "product_shots": [3]}

    monkeypatch.setattr(llm, "chat_json", fake_json)
    with TestClient(app) as c:
        no = _ad(url="https://www.tiktok.com/@x/video/3", breakdown={"shots": REF_SHOTS, "video_duration": 14, "selling_point": "防水"})
        pid = c.post("/api/v1/projects", json={"name": "洗稿方案"}).json()["id"]
        with SessionLocal() as db:
            p = db.get(Project, pid)
            wn = canvas.create_node(db, p, "wash", data={"ref_ad_no": no, "selling_point": "续航", "audience": "学生", "tier": "high", "tier_source": "agent"})
            sn = canvas.create_node(db, p, "script", data={"ref_ad_no": no, "selling_point": "续航", "audience": "学生"})
            canvas.connect(db, pid, wn.id, sn.id)
            db.commit()
            wid, sid = wn.id, sn.id
        asyncio.run(workflows.plan_wash(wid))
        with SessionLocal() as db:
            w = db.get(Node, wid)
            d, status = w.data, w.status
        assert status == "wait" and d["tier"] == "high" and d["fit"]["recommended"] in ("mid", "low")  # Agent 指定了高档，推荐档单独显示
        assert [(r["key"], r["action"]) for r in d["rows"]] == list(wash_plan.TIERS["high"]["actions"].items())
        assert d["rows"][2]["ours"] == "我方scene" and d["chosen"] == 1 and d["analysis"]["core"] == "铲车倒水"

        # 人改了场景一行，再换到中档：场景这一行不动，其他行按中档重排
        rows_edit = [dict(r) for r in d["rows"]]
        rows_edit[2].update(ours="纯室外，不要雨棚", edited=True)
        c.patch(f"/api/v1/projects/{pid}/nodes/{wid}", json={"data": {"rows": rows_edit}})
        assert c.post(f"/api/v1/nodes/{wid}/wash-tier", json={"tier": "bad"}).status_code == 400
        assert c.post(f"/api/v1/nodes/{wid}/wash-tier", json={"tier": "mid"}).status_code == 200
        asyncio.run(workflows.plan_wash(wid))
        with SessionLocal() as db:
            d = db.get(Node, wid).data
        assert d["tier"] == "mid" and d["tier_source"] == "user" and d["rows"][2]["ours"] == "纯室外，不要雨棚"
        assert d["rows"][0]["action"] == "adapt" and d["rows"][4]["action"] == "replace"

        # 回到高档后确认：剧本按六行表写
        c.post(f"/api/v1/nodes/{wid}/wash-tier", json={"tier": "high"})
        asyncio.run(workflows.plan_wash(wid))
        assert c.post("/api/v1/reviews/pass-nodes", json={"node_ids": [wid]}).json() == {"passed": 1}
        with SessionLocal() as db:
            assert db.get(Node, sid).status == "run"
        asyncio.run(workflows.generate_script(sid))
        with SessionLocal() as db:
            sd = db.get(Node, sid).data
        user = next(u for s_, u in calls if "改写成我方剧本" in s_)
        assert "纯室外，不要雨棚" in user and "场景照原片" in user  # 人改的那一行进了写剧本的清单
        assert sd["wash"]["tier"] == "high" and sd["wash"]["from_node"] == wid
        assert sd["shots"][0][2] == "Can your phone ever survive this?"  # 竞品品牌那版被换掉；高档台词像原片不重写
        assert sd["similarity"]["note"].startswith("高相似档") and not sd["similarity"].get("competitor_shots")


def test_wash_waits_for_video_breakdown(monkeypatch):
    """洗稿方案必须看过视频：没拆解就先拆；拆不了（比如下载失败）就停下要视频，上传拆完自动接着出方案。"""
    from app import breakdown as bdm
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    monkeypatch.setattr(workflows, "BREAKDOWN_POLL", 0.01)
    spawned = []
    monkeypatch.setattr(bdm, "spawn", lambda coro: spawned.append(coro))
    monkeypatch.setattr(workflows, "spawn", lambda coro: coro.close())
    rows = {k: {"ref": f"原片{k}", "ours": f"我方{k}"} for k in ("hook", "cast", "scene", "rhythm", "lines", "camera")}
    seen = []

    async def fake_json(system, user, task="script", timeout=90):
        seen.append(user)
        return {"rows": rows, "analysis": {"core": "用铲车往手机上倒一整斗水"}}

    monkeypatch.setattr(llm, "chat_json", fake_json)
    state = {"ok": False}

    async def fake_run(no):  # 第一次下载失败；上传视频后成功
        if state["ok"]:
            bdm._set(no, breakdown={"shots": REF_SHOTS, "core": {"device": "用铲车往手机上倒一整斗水"}, "video_duration": 14}, breakdown_status="done")
        else:
            bdm._set(no, breakdown_status="failed", breakdown_error="Apify 账户额度不够了")
        bdm._resume_washes(no)

    monkeypatch.setattr(bdm, "run", fake_run)
    with TestClient(app) as c:
        no = _ad(url="https://www.tiktok.com/@x/video/9")
        pid = c.post("/api/v1/projects", json={"name": "要看视频"}).json()["id"]
        with SessionLocal() as db:
            wid = canvas.create_node(db, db.get(Project, pid), "wash", data={"ref_ad_no": no, "selling_point": "续航", "audience": "学生"}).id
            db.commit()

        async def go():
            task = asyncio.create_task(workflows.plan_wash(wid))
            while not spawned:
                await asyncio.sleep(0.01)
            await spawned.pop()
            await task
        asyncio.run(go())
        with SessionLocal() as db:
            n = db.get(Node, wid)
            assert n.status == "input" and n.data["need_video"] and "额度" in n.data["breakdown_error"] and not n.data.get("rows")
        assert not seen  # 没看过视频，不出方案

        # 上传视频 → 拆解成功 → 自动接着出方案（用的是视频拆解）
        state["ok"] = True
        resumed = []
        monkeypatch.setattr(workflows, "plan_wash", lambda nid, comment="": resumed.append(nid) or asyncio.sleep(0))
        monkeypatch.setattr(bdm, "spawn", lambda coro: asyncio.run(coro) if not asyncio.iscoroutine(coro) or "fake_run" in repr(coro) else coro.close())
        r = c.post(f"/api/v1/ref-ads/{no}/breakdown", json={"video": "data:video/mp4;base64," + base64.b64encode(b"x" * 20000).decode()})
        assert r.status_code == 200 and resumed == [wid]
        bdm.upload_path(no).unlink(missing_ok=True)
