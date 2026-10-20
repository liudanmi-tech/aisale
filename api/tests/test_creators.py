"""达人雷达：找人（关键词 + 竞品 @）→ 指标 / 分级 / 适配分 / 报价 → 外联演示。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")

import time
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app import creators, settings_store
from app.adapters import apify
from app.db import SessionLocal
from app.main import app
from app.models import Creator, SourceVideo, WatchAccount, new_id


def _vid(handle, k, plays, text="Phone review #tech", followers=250_000, is_ad=False, days=0):
    return {"external_id": f"{handle}-{k}", "handle": handle, "nickname": handle.title(), "followers": followers, "verified": False,
            "bio": "Tech reviews | biz: hello@" + handle + ".com", "url": f"https://www.tiktok.com/@{handle}/video/{k}", "cover": "",
            "text": text, "hashtags": ["tech"], "is_ad": is_ad, "posted_at": datetime.utcnow() - timedelta(days=days),
            "plays": plays, "likes": plays // 20, "comments": plays // 200, "shares": plays // 500, "collects": 0, "raw": {}}


def test_stats_tier_fit_price():
    items = [_vid("a", k, 10_000 * (k + 1), days=k * 3) for k in range(10)]
    items.append(_vid("a", 99, 50_000, text="Unboxing the new Redmi #ad #xiaomi", is_ad=True, days=5))
    st = creators.compute_stats(items)
    assert st["n"] == 11 and st["median_plays"] == 50_000 and st["sponsored"] == 1 and st["competitor_recent"] == ["小米"]
    assert creators.tier_of(1_200_000) == "头部" and creators.tier_of(250_000) == "腰部" and creators.tier_of(9_000) == "素人"
    score, line, parts = creators.fit_of(st, {"product_fit": [{"line": "TECNO Phantom", "score": 90}], "brand_safety": "ok"})
    assert line == "TECNO Phantom" and parts["近期没接竞品"] == 0 and 0 < score < 100
    p = creators.price_of(st, "尼日利亚", {"尼日利亚": 2.0})
    assert p["low"] == 70 and p["high"] == 130 and p["assumed"]  # 50k ÷ 1000 × $2 = $100，×0.7–1.3


def test_discover_and_outreach_demo(monkeypatch):
    monkeypatch.setattr(settings_store, "get_secret", lambda n: "tok" if n == "apify" else "")
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: False)
    calls = {}

    async def fake_search(queries, per_query=30, on_progress=None, **kw):
        calls["search"] = queries
        return [_vid("naijareviewer", 1, 80_000), _vid("xiaomi_ng_official", 2, 900_000, followers=500_000) | {"verified": True, "nickname": "Xiaomi"},
                _vid("tinyacc", 3, 500, followers=800)]

    async def fake_profiles(handles, per_profile=20, **kw):
        calls["profiles"] = sorted(handles)
        return [_vid(h, k, 20_000 + k * 1000, days=k * 2) for h in handles for k in range(12)]
    monkeypatch.setattr(apify, "search_videos", fake_search)
    monkeypatch.setattr(apify, "fetch_profiles", fake_profiles)
    with TestClient(app) as c:
        with SessionLocal() as db:
            a = WatchAccount(id=new_id("wa"), handle="realme_cr_" + new_id("x")[-4:], brand="realme", market="肯尼亚")
            db.add(a)
            db.add(SourceVideo(id=new_id("sv"), external_id=new_id("e"), account_id=a.id, text="Huge thanks @collab_queen for this review! #realme"))
            db.commit()
        j = c.post("/api/v1/creators/discover", json={"market": "肯尼亚", "keywords": ["phone review kenya"], "limit": 10}).json()
        for _ in range(100):
            j = c.get(f"/api/v1/creators/jobs/{j['id']}").json()
            if j["status"] != "running":
                break
            time.sleep(0.05)
        assert j["status"] == "done", j
        assert calls["profiles"] == ["collab_queen", "naijareviewer"]  # 官方号、粉丝太少的不要；竞品 @ 过的排前面
        items = c.get("/api/v1/creators", params={"market": "肯尼亚"}).json()["items"]
        by = {x["handle"]: x for x in items}
        assert by["collab_queen"]["source"] == "竞品合作" and "@ 过" in by["collab_queen"]["found_by"]
        x = by["naijareviewer"]
        assert x["tier"] == "腰部" and x["email"] == "hello@naijareviewer.com" and x["best_product"] and x["price"]["high"] > 0
        cid = x["id"]
        o = c.post(f"/api/v1/creators/{cid}/outreach/draft", json={}).json()
        assert o["draft"]["subject"] and "rate card" in o["draft"]["body"]
        assert c.post(f"/api/v1/creators/{cid}/outreach/reply").status_code == 400  # 还没发
        o = c.post(f"/api/v1/creators/{cid}/outreach/send", json=o["draft"]).json()
        assert o["stage"] == "已发送" and o["thread"][0]["demo"]
        o = c.post(f"/api/v1/creators/{cid}/outreach/reply").json()
        assert o["stage"] == "报价中" and o["quote"]["amount"] > 0 and o["counter"]["amount"] <= o["quote"]["amount"]
        assert c.post(f"/api/v1/creators/{cid}/outreach/stage", json={"stage": "已签约"}).json()["stage"] == "已签约"
        assert c.get("/api/v1/creators", params={"market": "肯尼亚", "stage": "已签约"}).json()["items"][0]["id"] == cid
        with SessionLocal() as db:  # 共用一个测试库：别把竞品账号留给竞品雷达的测试
            db.query(SourceVideo).filter(SourceVideo.account_id == a.id).delete()
            db.query(WatchAccount).filter(WatchAccount.id == a.id).delete()
            db.query(Creator).filter(Creator.market == "肯尼亚").delete()
            db.commit()


def test_demo_data(monkeypatch):
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: False)
    with TestClient(app) as c:
        n = c.post("/api/v1/creators/demo", params={"market": "巴基斯坦"}).json()["added"]
        items = c.get("/api/v1/creators", params={"market": "巴基斯坦"}).json()["items"]
        assert n == 0 or len([x for x in items if x["demo"]]) >= n
        g = next(x for x in items if x["handle"] == "demo_pubgking_pk")
        assert g["tier"] == "头部" and g["best_product"] in ("Infinix GT", "TECNO Pova") and "游戏" in g["categories"]
        with SessionLocal() as db:
            assert db.query(Creator).filter(Creator.demo.is_(True)).count() >= 5
