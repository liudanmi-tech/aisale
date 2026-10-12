"""TikTok 账号监控：添加账号 → Apify 同步（模拟 HTTP）→ 快照与打分 → 加入爆款库 → 可用于洗剧本。"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.adapters import apify  # noqa: E402
from app.main import app  # noqa: E402

TOKEN = "apify_api_test1234abcd"
W = "/api/v1/watch"
runs: list[dict] = []
day = {"n": 0}  # 第几次同步，用来让播放量增长


def item(handle, vid, plays, likes, shares, days_ago, text="Battery test 6000mAh"):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {"id": vid, "text": text, "createTimeISO": ts, "webVideoUrl": f"https://www.tiktok.com/@{handle}/video/{vid}",
            "authorMeta": {"name": handle, "nickName": handle.upper(), "fans": 120000, "verified": True},
            "videoMeta": {"duration": 21, "coverUrl": f"https://p16.example/{vid}.jpg"}, "musicMeta": {"musicName": "Afro beat"},
            "hashtags": [{"name": "techtok"}], "playCount": plays, "diggCount": likes, "commentCount": likes // 20,
            "shareCount": shares, "collectCount": 3, "isAd": False}


def handler(req: httpx.Request) -> httpx.Response:
    assert req.headers["authorization"] in (f"Bearer {TOKEN}", "Bearer bad-token-000")
    if req.headers["authorization"] == "Bearer bad-token-000":
        return httpx.Response(401, json={"error": {"type": "token-not-valid"}})
    p = req.url.path
    if p == "/v2/users/me":
        return httpx.Response(200, json={"data": {"username": "transsion-ads"}})
    if req.method == "POST" and p.endswith("/runs"):
        runs.append({"actor": p.split("/")[3], "input": json.loads(req.content)})
        return httpx.Response(201, json={"data": {"id": "run1", "status": "RUNNING", "defaultDatasetId": "ds1"}})
    if p == "/v2/actor-runs/run1":
        return httpx.Response(200, json={"data": {"id": "run1", "status": "SUCCEEDED", "defaultDatasetId": "ds1"}})
    if p == "/v2/datasets/ds1/items" and "searchQueries" in runs[-1]["input"]:
        a = item("samsungnigeria", "s1", 90000, 3000, 100, 3)
        a["authorMeta"].update(fans=800000, signature="Official Samsung Nigeria")
        b = item("lagos_tech_guy", "t1", 250000, 20000, 900, 2, "Samsung A56 review")
        b["authorMeta"].update(fans=60000, verified=False)
        d = item("officialsamsungng", "o1", 2000, 50, 1, 4)
        d["authorMeta"].update(fans=121500, verified=False, nickName="Samsung Nigeria", signature="Official TikTok of Samsung Nigeria")
        e = item("maikuditaila", "m1", 7000, 50, 1, 4)
        e["authorMeta"].update(fans=1500, verified=False, nickName="Ali Maikuditela", signature="CEO Mekudi Tela Phones")
        c = item("galaxyfan123", "f1", 500, 20, 0, 1)
        c["authorMeta"].update(fans=300, verified=False)
        return httpx.Response(200, json=[a, b, dict(b, id="t2"), c, d, e])
    if p == "/v2/datasets/ds1/items":
        g = 1 + day["n"] * 0.2
        rows = [item("xiaomi_ng", f"x{k}", int(20000 * g), 900, 20, 10 + k) for k in range(8)]
        rows.append(item("xiaomi_ng", "xhot", int(400000 * g), 30000, 4000, 6, "Night camera vs iPhone"))  # 自然爆款
        rows.append(item("xiaomi_ng", "xpaid", int(300000 * g), 1500, 30, 5))  # 播放高、互动低：疑似加热
        rows.append(item("xiaomi_ng", "xnew", 50000, 4000, 500, 1))  # 不足 72 小时
        return httpx.Response(200, json=rows)
    return httpx.Response(404)


def wait_until(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_watch_sync_score_promote():
    apify.transport = httpx.MockTransport(handler)
    apify.POLL_SECONDS = 0.01
    with TestClient(app) as c:
        assert c.post(W + "/sync", json={}).status_code == 400  # 没填 Token
        assert c.post("/api/v1/settings/secrets/apify/test", json={"value": "bad-token-000"}).json()["ok"] is False
        assert c.put("/api/v1/settings/secrets/apify", json={"value": TOKEN}).status_code == 200
        t = c.post("/api/v1/settings/secrets/apify/test", json={}).json()
        assert t["ok"] and "transsion-ads" in t["message"]

        r = c.post(W + "/accounts", json={"handles": "@xiaomi_ng, https://www.tiktok.com/@Xiaomi_NG?lang=en ghost.acc", "brand": "小米", "market": "尼日利亚"}).json()
        assert r == {"added": 2, "skipped": 1}
        assert c.post(W + "/accounts", json={"handles": "bad handle!"}).status_code == 400
        accs = c.get(W + "/accounts").json()
        assert accs["ready"] and {a["handle"] for a in accs["items"]} == {"xiaomi_ng", "ghost.acc"}

        for n in range(2):  # 两次同步 → 两次快照 → 有增速
            day["n"] = n
            c.post(W + "/sync", json={})
            wait_until(lambda: all(a["status"] in ("ok", "error") for a in c.get(W + "/accounts").json()["items"]))
            if n == 0:  # 第二次快照需要间隔 1 小时以上才算增速：把第一次快照往前挪
                from app.db import SessionLocal
                from app.models import VideoSnapshot
                with SessionLocal() as db:
                    for s in db.query(VideoSnapshot):
                        s.ts -= timedelta(days=1)
                    db.commit()
        assert runs[0]["actor"] == "clockworks~tiktok-scraper" and runs[0]["input"]["resultsPerPage"] == 50
        assert runs[1]["input"]["resultsPerPage"] == 30
        items = {a["handle"]: a for a in c.get(W + "/accounts").json()["items"]}
        assert items["xiaomi_ng"]["status"] == "ok" and items["xiaomi_ng"]["videos"] == 11 and items["xiaomi_ng"]["followers"] == 120000
        assert items["ghost.acc"]["status"] == "error"

        vids = {v["external_id"]: v for v in c.get(W + "/videos").json()}
        hot, paid, new = vids["xhot"], vids["xpaid"], vids["xnew"]
        assert hot["grade"] == "爆款" and hot["multiple"] > 10 and hot["velocity"] > 0 and len(hot["trend"]) == 2
        assert paid["boosted"] and not hot["boosted"]
        assert new["grade"] == "观察中"
        assert c.get(W + "/videos", params={"grade": "爆款"}).json()[0]["external_id"] == "xhot"

        ad = c.post(f"{W}/videos/{hot['id']}/promote").json()
        assert ad["source"] == "TikTok 账号监控" and ad["selling_point"] == "拍照" and ad["brand"] == "小米"
        assert c.post(f"{W}/videos/{hot['id']}/promote").json()["no"] == ad["no"]  # 重复加入不新建
        assert any(a["no"] == ad["no"] for a in c.get("/api/v1/ref-ads").json())
        pid = c.post("/api/v1/projects", json={"name": "小米爆款洗稿", "market": "尼日利亚", "selling_point": "拍照"}).json()["id"]
        assert c.post(f"/api/v1/projects/{pid}/wash", json={"ref_ad_no": ad["no"]}).status_code == 200

        aid = items["ghost.acc"]["id"]
        assert c.delete(f"{W}/accounts/{aid}").json()["ok"]
        c.delete("/api/v1/settings/secrets/apify")
    apify.transport = None


def test_search_accounts():
    runs.clear()
    apify.transport = httpx.MockTransport(handler)
    apify.POLL_SECONDS = 0.01
    with TestClient(app) as c:
        assert c.post(W + "/search", json={"queries": ["Samsung Nigeria"]}).status_code == 400  # 没填 Token
        c.put("/api/v1/settings/secrets/apify", json={"value": TOKEN})
        job = c.post(W + "/search", json={"queries": ["Samsung Nigeria", " "]}).json()["job_id"]
        wait_until(lambda: c.get(f"{W}/search/{job}").json()["status"] != "running")
        res = c.get(f"{W}/search/{job}").json()
        assert res["status"] == "done" and runs[-1]["input"]["searchQueries"] == ["Samsung Nigeria"]
        r = {x["handle"]: x for x in res["results"]}
        assert res["results"][0]["handle"] == "samsungnigeria"
        assert r["samsungnigeria"]["brand"] == "三星" and r["samsungnigeria"]["kind"] == "竞品官方" and r["samsungnigeria"]["bio"]
        assert r["galaxyfan123"]["brand"] == "三星" and r["galaxyfan123"]["kind"] == "达人"  # 名字带品牌但没认证：不当官方号
        assert r["officialsamsungng"]["brand"] == "三星" and r["officialsamsungng"]["kind"] == "竞品官方"  # 没蓝 V 但简介写明官方
        assert r["maikuditaila"]["brand"] == ""  # 名字里含 "itel" 字母不算 itel
        assert r["lagos_tech_guy"]["videos"] == 2 and r["lagos_tech_guy"]["kind"] == "达人"
        c.delete("/api/v1/settings/secrets/apify")
    apify.transport = None


def test_report():
    """分析报告：逐条拆解（带封面图）→ 代码统计 → 汇总洞察；拆解结果缓存并用于入库。"""
    from app import analysis
    from app.adapters import llm

    seen = {"analysis": 0, "report": 0, "image": 0}

    def llm_handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if body["model"] == "google/gemini-2.5-flash":
            seen["analysis"] += 1
            user = body["messages"][1]["content"]
            if isinstance(user, list):
                seen["image"] += any(p["type"] == "image_url" and p["image_url"]["url"].startswith("data:image/") for p in user)
                user = user[0]["text"]
            night = "Night camera" in user
            out = {"brand": "小米", "product": "Redmi Note 15" if night else "Redmi A5", "selling_points": ["夜拍"] if night else ["续航", "快充"],
                   "scene": "拉各斯夜市" if night else "停电的家", "scene_tags": ["夜晚", "户外市场"] if night else ["家庭"],
                   "script_type": ["痛点对比"], "hook": "黑夜里两台手机同时拍照", "hook_type": "对比", "talent": "本地年轻男性",
                   "talent_tag": "年轻男性", "language": "英语", "pacing": "约 20 秒，6 个镜头",
                   "shots": ["0–3s 黑夜对比", "3-8s 放大细节", "结尾 logo"], "why_viral": "对比直观", "confidence": "中"}
        else:
            seen["report"] += 1
            assert "【统计】" in body["messages"][1]["content"]
            out = {"headline": "小米主打夜拍对比", "takeaways": ["夜拍对比最火"], "products": "Redmi", "selling_points": "夜拍",
                   "script_types": "痛点对比", "scenes": "夜市", "talent": "年轻男性", "hooks": "对比", "pacing": "快切",
                   "why_viral": "内容", "recommendations": ["做夜拍对比"]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}]})

    def media_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\xff\xd8\xff fake jpeg", headers={"content-type": "image/jpeg"})

    apify.transport = httpx.MockTransport(handler)
    apify.POLL_SECONDS = 0.01
    llm.transport = httpx.MockTransport(llm_handler)
    analysis.media_transport = httpx.MockTransport(media_handler)
    with TestClient(app) as c:
        assert c.post(W + "/reports", json={}).status_code == 400  # 没有 OpenRouter Key
        c.put("/api/v1/settings/secrets/apify", json={"value": TOKEN})
        c.put("/api/v1/settings/secrets/openrouter", json={"value": "sk-or-test-5678wxyz"})
        c.post(W + "/accounts", json={"handles": "xiaomi_ng", "brand": "小米", "market": "尼日利亚"})
        c.post(W + "/sync", json={})
        wait_until(lambda: all(a["status"] in ("ok", "error") for a in c.get(W + "/accounts").json()["items"]))

        rid = c.post(W + "/reports", json={"market": "尼日利亚", "days": 30, "top": 5}).json()["id"]
        wait_until(lambda: c.get(f"{W}/reports/{rid}").json()["status"] != "running")
        r = c.get(f"{W}/reports/{rid}").json()
        assert r["status"] == "done", r["error"]
        d = r["data"]
        assert seen["analysis"] == 5 and seen["image"] == 5 and seen["report"] == 1
        assert d["insight"]["headline"] == "小米主打夜拍对比" and len(d["videos"]) == 5
        assert d["videos"][0]["inputs"] == ["文案与数据", "封面"]
        sp = {x["name"]: x for x in d["stats"]["selling_points"]}
        assert sp["夜拍"]["videos"] == 1 and sp["夜拍"]["share"] > 30  # xhot 播放最高
        assert any(x["name"] == "Redmi Note 15" for x in d["stats"]["products"]) and d["stats"]["brands"][0]["name"] == "小米"
        assert c.get(W + "/reports").json()[0]["headline"] == "小米主打夜拍对比"

        rid2 = c.post(W + "/reports", json={"market": "尼日利亚", "top": 5}).json()["id"]  # 已拆解的视频走缓存
        wait_until(lambda: c.get(f"{W}/reports/{rid2}").json()["status"] != "running")
        assert seen["analysis"] == 5 and seen["report"] == 2

        v = next(v for v in d["videos"] if not v["ref_ad_no"] and "Night camera" not in v["text"])
        ad = c.post(f"{W}/videos/{v['id']}/promote").json()
        assert ad["selling_point"] == "续航" and ad["hook"] == "黑夜里两台手机同时拍照" and ad["title"] == "Battery test 6000mAh"
        assert ad["dna"]["shots"][:2] == [["0–3s", "黑夜对比"], ["3-8s", "放大细节"]] and ad["dna"]["product"] == "Redmi A5"
        latest = {x["id"]: x["ref_ad_no"] for x in c.get(f"{W}/reports/{rid}").json()["data"]["videos"]}
        assert latest[v["id"]] == ad["no"]  # 报告里的入库状态是实时的
        for name in ("apify", "openrouter"):
            c.delete(f"/api/v1/settings/secrets/{name}")
    apify.transport = llm.transport = analysis.media_transport = None
