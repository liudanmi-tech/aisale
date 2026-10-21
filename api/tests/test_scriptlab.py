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
            a = WatchAccount(id=new_id("wa"), handle="tr_" + new_id("x")[-5:], market="加纳", kind="达人")
            off = WatchAccount(id=new_id("wa"), handle="tro_" + new_id("x")[-5:], market="加纳", kind="竞品官方")
            db.add_all([a, off])
            db.add(SourceVideo(id=new_id("sv"), external_id=new_id("e"), account_id=off.id, plays=9_000_000, text="x", hashtags=["titanpower"], music="Ad jingle"))
            for k in range(3):
                db.add(SourceVideo(id=new_id("sv"), external_id=new_id("e"), account_id=a.id, plays=1000 * (k + 1), text="Blackout again",
                                   hashtags=["fyp", "lightout", "samsung", "ghanacomedy"] if k < 2 else ["lightout"], music="Afro hit"))
            db.commit()
        t = scriptlab.trends("加纳")
        assert [x["tag"] for x in t["tags"]][:2] == ["lightout", "ghanacomedy"]  # fyp、品牌词过滤掉；按出现次数和播放排
        assert t["tags"][0]["videos"] == 3 and t["music"][0]["music"] == "Afro hit"
        assert [x["tag"] for x in t["campaign_tags"]] == ["titanpower"] and "titanpower" not in [x["tag"] for x in t["tags"]]  # 竞品官方号的广告标签单列
        assert all(m["music"] != "Ad jingle" for m in t["music"])
        assert scriptlab.trends("尼日利亚")["evergreen"]  # 预置的本地常青话题
        with SessionLocal() as db:
            db.query(SourceVideo).filter(SourceVideo.account_id.in_([a.id, off.id])).delete()
            db.query(WatchAccount).filter(WatchAccount.id.in_([a.id, off.id])).delete()
            db.commit()


def test_generate_evaluate_use(monkeypatch):
    """创意锦标赛：8 路引擎 × 3 个编剧模型想 40 个创意 → 5 评委初筛 → 前 k 名写分镜（过可拍性自检）→ 正式打分；观众模拟；用到画布。"""
    import json as _json
    import re as _re
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    seen = {"idea": [], "write": [], "fix": 0}

    async def fake_json(system, user, task="script", timeout=90, model=None):
        if "这次的创意引擎" in system:
            eng = _re.search(r"这次的创意引擎：(.+?)——", system).group(1)
            seen["idea"].append((model, eng, system))
            return {"ideas": [{"title": f"{eng}{k}", "format": eng, "logline": f"{eng} 故事{k}", "hook": "手机掉进水桶", "twist": "还能打游戏",
                               "product_moment": "溅水后继续打 PUBG", "trend": "NEPA 停电" if k == 0 else "", "why_viral": "好笑", "risk": ""} for k in range(5)]}
        if "超出了我们 AI 生成流程" in system:
            seen["fix"] += 1
            return {"shots": [[2, "特写：手机被溅到水", "Wahala!", "完了！"], [3, "中景：他擦干手机继续玩", "E still dey work", "还能用"],
                              [2, "近景：他得意地笑", "No wahala", "没事"], [2, "近景：室友惊讶", "How?", "怎么做到的"], [2, "中景：两人击掌", "Yes!", "耶"],
                              [3, "特写：手机正面朝镜头", "TECNO Pova", "TECNO Pova"]]}
        seen["write"].append(user)
        return {"shots": [[2, "特写：手机掉进水桶", "Wahala!", "完了！"], [3, "中景：一群学生围着看", "E still dey work", "还能用"],
                          [3, "特写：手机", "TECNO Pova", "TECNO Pova"]]}
    monkeypatch.setattr(llm, "chat_json", fake_json)
    hi = {"荒诞升级0": 9, "恶作剧反转1": 9, "荒诞升级2": 9, "荒诞升级3": 9}

    async def fake_chat(messages, model=None, **kw):
        system, user = messages[0]["content"], messages[1]["content"]
        if "一批" in system:  # 创意初筛：按编号给分
            rows = []
            for line in user.splitlines():
                n, title = line.split(". ", 1)[0], line.split(". ", 1)[1].split("：")[0]
                v = hi.get(title, 6)
                rows.append({"i": int(n), **{k: v for k in ("hook", "local", "selling", "feasible", "safe")}})
            return {"content": _json.dumps({"scores": rows})}
        return {"content": _json.dumps({"scores": {k: 7 for k in ("hook", "local", "selling", "feasible", "safe")}, "issues": []})}
    monkeypatch.setattr(llm, "chat", fake_chat)

    async def fake_panel(personas, shots, tasks, fallback, seed=""):
        assert len(personas) == 40 and tasks == []
        return {"reactions": [{"completed": i % 2 == 0, "clicked": i == 0, "comment": "lol"} for i in range(40)],
                "scores": {"hook": 8, "clarity": 7, "trust": 6, "local": 9, "intent": 6}, "issue": "第 3 镜流失最多", "retention": [100, 70, 50, 40],
                "shot_rel": [1, 0, -1, 0], "agents": 40, "engine": "40 个独立 Agent"}
    monkeypatch.setattr(panel, "run", fake_panel)
    with TestClient(app) as c:
        j = c.post("/api/v1/scripts/generate", json={"market": "尼日利亚", "product": "TECNO Pova", "selling_point": "防水防尘", "audience": "学生",
                                                     "trends": ["#lightout", "NEPA 停电"], "count": 3}).json()
        j = _wait(c, f"/api/v1/scripts/jobs/{j['id']}")
        assert j["status"] == "done", j
        assert len(seen["idea"]) == 8 and len({m for m, _, _ in seen["idea"]}) == 3  # 8 路引擎，3 个编剧模型轮流
        assert all("NEPA 停电" in sy and "防水防尘" in sy and "最多 2 个主要人物" in sy for _, _, sy in seen["idea"])  # 热点、卖点、生产边界都写进去了
        items = c.get("/api/v1/scripts", params={"market": "尼日利亚"}).json()["items"]
        mine = [x for x in items if x["batch"] == j["batch"]]
        # 初筛前四名有 3 个「荒诞升级」：同一路引擎最多 2 个，第 3 名换成「恶作剧反转」
        assert sorted(x["title"] for x in mine) == ["恶作剧反转1", "荒诞升级0", "荒诞升级2"]
        assert all(x["status"] == "ok" and x["critic"]["picked"] and x["critic"]["of"] == 40 for x in mine)
        assert seen["fix"] == 3 and all("一群" not in sh[1] for x in mine for sh in x["shots"])  # 可拍性自检：群戏镜头自动改掉
        assert all(x["evaluation"]["judges"]["total"] == 70 for x in mine)  # 写完自动正式打分
        s = mine[0]
        allx = c.get("/api/v1/scripts", params={"market": "尼日利亚", "concepts": True}).json()["items"]
        concepts = [x for x in allx if x["batch"] == j["batch"] and x["status"] == "concept"]
        assert len(concepts) == 37 and concepts[0]["critic"]["total"] >= concepts[-1]["critic"]["total"]  # 备选创意按初筛分排
        # 备选创意写成剧本
        assert c.post(f"/api/v1/scripts/{concepts[0]['id']}/write", json={}).status_code == 200
        for _ in range(100):
            if c.get(f"/api/v1/scripts/{concepts[0]['id']}").json()["status"] == "ok":
                break
            time.sleep(0.03)
        assert c.get(f"/api/v1/scripts/{concepts[0]['id']}").json()["shots"]
        # 观众模拟
        assert c.post(f"/api/v1/scripts/{s['id']}/evaluate").status_code == 200
        for _ in range(100):
            ev = c.get(f"/api/v1/scripts/{s['id']}").json()
            if ev["status"] == "ok" and ev["evaluation"].get("audience"):
                break
            time.sleep(0.03)
        au = ev["evaluation"]["audience"]
        assert au["score"] == 72 and au["completion"] == 50 and au["clicks"] == 1 and ev["evaluation"]["judges"]  # 评委结果还在
        # 用到画布：建剧本节点并进入审核
        pid = c.post("/api/v1/projects", json={"name": "剧本库"}).json()["id"]
        monkeypatch.setattr(settings_store, "llm_enabled", lambda: False)
        nid = c.post(f"/api/v1/scripts/{s['id']}/use", json={"project_id": pid}).json()["node_id"]
        with SessionLocal() as db:
            n = db.get(Node, nid)
            assert n.type == "script" and n.status == "wait" and n.data["from_library"] == s["id"] and len(n.data["shots"]) == 6
            assert db.get(LibScript, s["id"]).used[0]["node_id"] == nid


def test_lint_rules():
    shots = [["0–2s", "特写：一群学生围着他", "a", "a"], ["2–7s", "手机屏幕上显示游戏角色在奔跑", "b", "b"],
             ["7–9s", "中景：他盯着手机〔后期贴屏〕，屏幕上显示游戏画面", "c", "c"]]
    rules = [(x["shot"], x["rule"]) for x in scriptlab.lint(shots)]
    has = lambda n, prefix: any(r[0] == n and r[1].startswith(prefix) for r in rules)  # noqa: E731
    assert has(1, "人群 / 群戏") and has(2, "这一镜 5 秒") and has(2, "屏幕内容") and has(0, "镜头数 3")
    assert not any(r[0] == 3 for r in rules)  # 标了后期贴屏的不算


def test_memes_refresh(monkeypatch):
    """热梗雷达：Google 热搜 + 联网搜索 + 雷达数据 → 梗卡片（带来源；有风险的标成不建议用）。"""
    import httpx
    from app import memes
    rss = """<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss"><channel>
      <item><title>Super Eagles vs Ghana</title><ht:approx_traffic>50000+</ht:approx_traffic>
        <ht:news_item><ht:news_item_title>Eagles win</ht:news_item_title><ht:news_item_url>https://n/1</ht:news_item_url><ht:news_item_source>Punch</ht:news_item_source></ht:news_item></item>
      <item><title>Seyi Vibez</title><ht:approx_traffic>2000+</ht:approx_traffic></item></channel></rss>"""
    monkeypatch.setattr(memes, "transport", httpx.MockTransport(lambda req: httpx.Response(200, text=rss)))
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    seen = {}

    async def fake_chat(messages, web=0, **kw):
        seen["web"] = web
        return {"content": "1. 'Sapa' memes are everywhere... https://x/sapa", "annotations": [{"type": "url_citation", "url_citation": {"url": "https://x/sapa", "title": "Sapa memes"}}]}

    async def fake_json(system, user, task="analysis", timeout=90):
        seen["distill"] = user
        return {"items": [{"name": "Sapa", "kind": "俚语 / 口头禅", "what": "没钱了的自嘲", "how": "月底没钱也能玩", "say": "Sapa don hold me", "heat": 5, "sources": [1], "risk": "", "use": True},
                          {"name": "某政治事件", "kind": "社会话题", "what": "x", "how": "", "heat": 4, "sources": [], "risk": "政治", "use": True}]}
    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(llm, "chat_json", fake_json)
    with TestClient(app) as c:
        assert c.post("/api/v1/scripts/memes/refresh", params={"market": "尼日利亚"}).status_code == 200
        for _ in range(100):
            m = c.get("/api/v1/scripts/memes", params={"market": "尼日利亚"}).json()
            if m.get("updated") and not m["refreshing"]:
                break
            time.sleep(0.03)
        assert seen["web"] == 10 and "Super Eagles vs Ghana" in seen["distill"] and "Sapa memes" in seen["distill"]
        assert m["google"][0]["title"] == "Super Eagles vs Ghana" and m["google"][0]["news"][0]["source"] == "Punch"
        sapa, pol = m["items"]
        assert sapa["sources"][0]["url"] == "https://x/sapa" and sapa["use"] and not pol["use"]  # 有风险的不建议用
        assert "Sapa don hold me" in memes.as_trend(sapa)
