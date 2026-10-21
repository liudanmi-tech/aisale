"""剧本库：热点 → 8 个创意 → 评审挑 3 个 → 写分镜（备选创意也存着）→ 40 人评测 → 用到画布。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")

import time

from fastapi.testclient import TestClient

from app import panel, scriptlab, settings_store
from app.adapters import llm
from app.db import SessionLocal
from app.main import app
from app.models import LibScript, Node, SourceVideo, WatchAccount, new_id


def _wait(c, url):
    for _ in range(200):
        j = c.get(url).json()
        if j.get("status") not in ("running",):
            return j
        time.sleep(0.03)
    return j


def test_trends_from_radar_data():
    with TestClient(app):
        with SessionLocal() as db:
            a = WatchAccount(id=new_id("wa"), handle="tr_" + new_id("x")[-5:], market="加纳")
            db.add(a)
            for k in range(3):
                db.add(SourceVideo(id=new_id("sv"), external_id=new_id("e"), account_id=a.id, plays=1000 * (k + 1), text="Blackout again",
                                   hashtags=["fyp", "lightout", "samsung", "ghanacomedy"] if k < 2 else ["lightout"], music="Afro hit"))
            db.commit()
        t = scriptlab.trends("加纳")
        assert [x["tag"] for x in t["tags"]][:2] == ["lightout", "ghanacomedy"]  # fyp、品牌词过滤掉；按出现次数和播放排
        assert t["tags"][0]["videos"] == 3 and t["music"][0]["music"] == "Afro hit"
        assert scriptlab.trends("尼日利亚")["evergreen"]  # 预置的本地常青话题
        with SessionLocal() as db:
            db.query(SourceVideo).filter(SourceVideo.account_id == a.id).delete()
            db.query(WatchAccount).filter(WatchAccount.id == a.id).delete()
            db.commit()


def test_generate_evaluate_use(monkeypatch):
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    seen = {}

    async def fake_json(system, user, task="script", timeout=90):
        if "整活" in system and "8 个" in system:
            seen["idea"] = system
            return {"ideas": [{"title": f"创意{k}", "format": "整活", "logline": f"故事{k}", "hook": "手机掉进水桶", "twist": "还能打游戏",
                               "product_moment": "水里继续打 PUBG", "trend": "NEPA 停电" if k == 0 else "", "why_viral": "好笑", "risk": ""} for k in range(8)]}
        if "评审" in system:
            seen["critic"] = user
            return {"reviews": [{"i": k + 1, "scores": {"novelty": 9 - k % 4, "hook": 8, "integration": 8, "local": 7, "feasible": 8, "safe": 9}, "verdict": "好"}
                                for k in range(8)], "picked": [{"i": 1, "improve": "钩子再狠一点"}, {"i": 3, "improve": ""}]}
        seen.setdefault("write", []).append(user)
        return {"shots": [[2, "特写：手机掉进水桶", "Wahala!", "完了！"], [3, "中景：他捞出手机继续打游戏，随后切特写：屏幕朝镜头", "E still dey work", "还能用"],
                          [3, "特写：手机", "TECNO Pova", "TECNO Pova"]]}
    monkeypatch.setattr(llm, "chat_json", fake_json)

    async def fake_panel(personas, shots, tasks, fallback, seed=""):
        assert len(personas) == 40 and tasks == []
        return {"reactions": [{"completed": i % 2 == 0, "clicked": i == 0, "comment": "lol"} for i in range(40)],
                "scores": {"hook": 8, "clarity": 7, "trust": 6, "local": 9, "intent": 6}, "issue": "第 3 镜流失最多", "retention": [100, 70, 50, 40],
                "shot_rel": [1, 0, -1, 0], "agents": 40, "engine": "40 个独立 Agent"}
    monkeypatch.setattr(panel, "run", fake_panel)
    with TestClient(app) as c:
        j = c.post("/api/v1/scripts/generate", json={"market": "尼日利亚", "product": "TECNO Pova", "selling_point": "防水防尘", "audience": "学生",
                                                     "trends": ["#lightout", "NEPA 停电"], "count": 2}).json()
        j = _wait(c, f"/api/v1/scripts/jobs/{j['id']}")
        assert j["status"] == "done", j
        assert "NEPA 停电" in seen["idea"] and "防水防尘" in seen["idea"] and "钩子再狠一点" in "".join(seen["write"])
        items = c.get("/api/v1/scripts", params={"market": "尼日利亚"}).json()["items"]
        mine = [x for x in items if x["batch"] == j["batch"]]
        assert len(mine) == 2 and all(x["status"] == "ok" and x["critic"]["picked"] for x in mine)
        s = next(x for x in mine if x["title"] == "创意0")
        assert len(s["shots"]) == 4 and s["shots"][1][1].startswith("中景")  # 「随后切」拆成两镜
        allx = c.get("/api/v1/scripts", params={"market": "尼日利亚", "concepts": True}).json()["items"]
        concepts = [x for x in allx if x["batch"] == j["batch"] and x["status"] == "concept"]
        assert len(concepts) == 6 and concepts[0]["critic"]["total"] > 0
        # 备选创意写成剧本
        assert c.post(f"/api/v1/scripts/{concepts[0]['id']}/write", json={}).status_code == 200
        for _ in range(100):
            if c.get(f"/api/v1/scripts/{concepts[0]['id']}").json()["status"] == "ok":
                break
            time.sleep(0.03)
        assert c.get(f"/api/v1/scripts/{concepts[0]['id']}").json()["shots"]
        # 评测
        assert c.post(f"/api/v1/scripts/{s['id']}/evaluate").status_code == 200
        for _ in range(100):
            ev = c.get(f"/api/v1/scripts/{s['id']}").json()
            if ev["status"] == "ok" and ev["evaluation"]:
                break
            time.sleep(0.03)
        assert ev["evaluation"]["score"] == 72 and ev["evaluation"]["completion"] == 50 and ev["evaluation"]["clicks"] == 1
        # 用到画布：建剧本节点并进入审核
        pid = c.post("/api/v1/projects", json={"name": "剧本库"}).json()["id"]
        monkeypatch.setattr(settings_store, "llm_enabled", lambda: False)
        nid = c.post(f"/api/v1/scripts/{s['id']}/use", json={"project_id": pid}).json()["node_id"]
        with SessionLocal() as db:
            n = db.get(Node, nid)
            assert n.type == "script" and n.status == "wait" and n.data["from_library"] == s["id"] and len(n.data["shots"]) == 4
            assert db.get(LibScript, s["id"]).used[0]["node_id"] == nid
