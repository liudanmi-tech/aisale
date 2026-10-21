"""TikTok 账号监控：同步账号视频 → 记快照 → 打分 → 人工加入爆款库。

打分（见 docs/爆款挖掘技术方案.md 第 4 节，自然流量部分）：
- 爆款倍数 = 播放 ÷ 该账号最近 30 条视频播放中位数
- 互动率 = (点赞+评论+分享) ÷ 播放；分享率 = 分享 ÷ 播放
- 增速 = 最近两次快照间的日均播放增长（至少两次快照才有）
- 爆款分 = 同市场百分位加权：倍数 0.35 + 播放 0.25 + 分享率 0.20 + 增速 0.10 + 购买意向 0.10（暂缺，权重按比例分给其他项）
- 精品分 = 互动率百分位 0.6 + 分享率百分位 0.4
- 疑似加热：倍数 ≥ 3 且互动率低于账号中位数一半（花钱买的播放互动少）
"""
import asyncio
import logging
import re
import statistics
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import httpx

from app import config, settings_store
from app.adapters import apify
from app.db import SessionLocal
from app.models import RefAd, SourceVideo, VideoAnalysis, VideoSnapshot, WatchAccount, new_id

log = logging.getLogger(__name__)
HOT_PLAYS = 100_000  # 进「爆款」榜的最低播放，两个试点市场先用 10 万
SYNC_EVERY = timedelta(hours=20)
_running: set[str] = set()


COVER_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Referer": "https://www.tiktok.com/"}
media_transport: httpx.AsyncBaseTransport | None = None  # 测试时注入


def _cover_file(external_id: str):
    return config.MEDIA_DIR / "covers" / f"{external_id}.jpg"


def cover_url(external_id: str, remote: str = "") -> str:
    """有本地缓存用本地（不会过期），否则用 TikTok 原链接。"""
    return f"/api/v1/media/covers/{external_id}.jpg" if external_id and _cover_file(external_id).exists() else remote


async def ensure_covers(video_ids: list[str] | None = None) -> int:
    """把还没缓存的封面下载到本地。拿不到就跳过，下次同步再试。"""
    with SessionLocal() as db:
        q = db.query(SourceVideo.external_id, SourceVideo.cover)
        if video_ids is not None:
            q = q.filter(SourceVideo.id.in_(video_ids))
        todo = [(e, c) for e, c in q if c and c.startswith("http") and not _cover_file(e).exists()]
    return await download_covers(todo)


async def download_covers(todo: list[tuple[str, str]]) -> int:
    """[(视频 ID, TikTok 封面链接)] → 存到本地封面缓存（竞品雷达、达人雷达共用）。"""
    todo = [(e, u) for e, u in todo if e and u and u.startswith("http") and not _cover_file(e).exists()]
    if not todo:
        return 0
    (config.MEDIA_DIR / "covers").mkdir(parents=True, exist_ok=True)
    sem, saved = asyncio.Semaphore(6), [0]

    async def one(c: httpx.AsyncClient, ext: str, url: str) -> None:
        async with sem:
            try:
                r = await c.get(url, headers=COVER_UA)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") and len(r.content) < 3_000_000:
                    _cover_file(ext).write_bytes(r.content)
                    saved[0] += 1
            except Exception:  # noqa: BLE001
                pass

    async with httpx.AsyncClient(timeout=20, transport=media_transport, follow_redirects=True) as c:
        await asyncio.gather(*(one(c, e, u) for e, u in todo))
    return saved[0]


async def sync(account_ids: list[str] | None = None) -> dict:
    """拉取账号最新视频。account_ids 为空时同步全部启用的账号。"""
    if not settings_store.get_secret("apify"):
        raise RuntimeError("还没有填写 Apify Token，请到设置页添加")
    with SessionLocal() as db:
        q = db.query(WatchAccount).filter(WatchAccount.enabled.is_(True))
        if account_ids:
            q = q.filter(WatchAccount.id.in_(account_ids))
        accs = [a for a in q if a.id not in _running]
        if not accs:
            return {"accounts": 0, "videos": 0}
        for a in accs:
            a.status, a.error = "syncing", ""
            _running.add(a.id)
        db.commit()
        by_handle = {a.handle.lower(): a.id for a in accs}
        first = {a.id for a in accs if a.last_synced is None}
    try:
        items = await apify.fetch_profiles(list(by_handle), per_profile=50 if first else 30)
    except Exception as e:  # noqa: BLE001
        with SessionLocal() as db:
            for aid in by_handle.values():
                a = db.get(WatchAccount, aid)
                a.status, a.error = "error", str(e)[:300]
            db.commit()
        _running.difference_update(by_handle.values())
        raise
    now = datetime.utcnow()
    count = 0
    with SessionLocal() as db:
        seen: set[str] = set()
        for it in items:
            aid = by_handle.get(it["handle"].lower())
            if not aid:
                continue
            seen.add(aid)
            a = db.get(WatchAccount, aid)
            a.nickname = it["nickname"] or a.nickname
            a.followers = it["followers"] or a.followers
            a.verified = a.verified or it["verified"]
            v = db.query(SourceVideo).filter(SourceVideo.external_id == it["external_id"]).first()
            fields = {k: it[k] for k in ("url", "cover", "text", "hashtags", "music", "duration", "is_ad", "posted_at",
                                         "plays", "likes", "comments", "shares", "collects", "raw")}
            if not v:
                v = SourceVideo(id=new_id("sv"), external_id=it["external_id"], account_id=aid, first_seen=now, **fields)
                db.add(v)
                db.flush()
            else:
                for k, val in fields.items():
                    setattr(v, k, val)
            v.last_seen = now
            db.add(VideoSnapshot(video_id=v.id, ts=now, plays=v.plays, likes=v.likes, comments=v.comments, shares=v.shares))
            count += 1
        for aid in by_handle.values():
            a = db.get(WatchAccount, aid)
            a.last_synced = now
            a.status, a.error = ("ok", "") if aid in seen else ("error", "没有拉到视频：请确认账号名正确、账号公开")
        db.commit()
    _running.difference_update(by_handle.values())
    try:
        await ensure_covers()
    except Exception:  # noqa: BLE001
        log.exception("封面缓存失败")
    return {"accounts": len(by_handle), "videos": count}


async def scheduler() -> None:
    """启动后先补存缺的封面；之后每小时检查一次，把超过 20 小时没同步的账号同步一遍（需已填 Apify Token）。"""
    await asyncio.sleep(5)
    try:
        await ensure_covers()
    except Exception:  # noqa: BLE001
        log.exception("封面缓存失败")
    while True:
        await asyncio.sleep(3600)
        try:
            if not settings_store.get_secret("apify"):
                continue
            with SessionLocal() as db:
                cutoff = datetime.utcnow() - SYNC_EVERY
                due = [a.id for a in db.query(WatchAccount).filter(WatchAccount.enabled.is_(True))
                       if a.last_synced is None or a.last_synced < cutoff]
            if due:
                await sync(due)
        except Exception:  # noqa: BLE001
            log.exception("定时同步失败")


# 品牌识别：账号名 / 昵称里出现这些词就认为是该品牌的账号
BRAND_KEYS = {"samsung": "三星", "galaxy": "三星", "xiaomi": "小米", "redmi": "小米", "poco": "小米", "realme": "realme",
              "oppo": "OPPO", "vivo": "vivo", "honor": "Honor", "tecno": "TECNO", "infinix": "Infinix", "itel": "itel"}
_searches: dict[str, dict] = {}


def guess_brand(*texts: str) -> str:
    # 品牌词前面必须是开头或非字母：避免 "Maikuditela" 被认成 itel；后面不限，因为账号名常连写（realmenigeria）
    t = " ".join(texts).lower()
    return next((b for k, b in BRAND_KEYS.items() if re.search(rf"(?<![a-z]){k}", t)), "")


def looks_official(c: dict) -> bool:
    """已认证；或简介写明 official 且粉丝过万（不少品牌的国家号没有蓝 V）。"""
    return bool(c["brand"]) and (c["verified"] or ("official" in (c["bio"] or "").lower() and (c["followers"] or 0) >= 10_000))


async def search_accounts(job_id: str, queries: list[str]) -> None:
    """按关键词搜视频，把作者汇总成候选账号：已认证、名字带品牌、粉丝多的排前面。"""
    job = _searches[job_id]
    try:
        items = await apify.search_videos(queries, on_progress=lambda p: job.update(progress=p))
    except Exception as e:  # noqa: BLE001
        job.update(status="error", error=str(e)[:300] or type(e).__name__)
        return
    with SessionLocal() as db:
        existing = {a.handle.lower() for a in db.query(WatchAccount)}
    found: dict[str, dict] = {}
    for it in items:
        h = it["handle"]
        if not h:
            continue
        c = found.setdefault(h.lower(), {"handle": h, "nickname": it["nickname"], "verified": it["verified"], "followers": it["followers"],
                                         "bio": it["bio"], "videos": 0, "max_plays": 0, "sample_url": it["url"], "sample_text": it["text"][:80],
                                         "added": h.lower() in existing})
        c["videos"] += 1
        if it["plays"] > c["max_plays"]:
            c.update(max_plays=it["plays"], sample_url=it["url"], sample_text=it["text"][:80])
        c["followers"] = c["followers"] or it["followers"]
        c["verified"] = c["verified"] or it["verified"]
    for c in found.values():
        c["brand"] = guess_brand(c["handle"], c["nickname"])
        c["kind"] = "竞品官方" if looks_official(c) else "达人"
    job.update(status="done", results=sorted(found.values(), key=lambda c: (not c["brand"], not c["verified"], -(c["followers"] or 0))))


def start_search(queries: list[str]) -> str:
    job_id = new_id("ws")
    _searches[job_id] = {"status": "running", "queries": queries, "results": [], "error": "", "progress": None}
    for old in list(_searches)[:-20]:  # 只留最近 20 次
        _searches.pop(old, None)
    return job_id


def _pct(values: list[float]) -> dict[int, float]:
    """返回 index → 百分位(0–100)，并列取平均名次。"""
    if not values:
        return {}
    order = sorted(range(len(values)), key=lambda k: values[k])
    ranks: dict[int, float] = {}
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = (i + j) / 2
        for k in order[i:j + 1]:
            ranks[k] = 100 * r / max(1, len(values) - 1)
        i = j + 1
    return ranks


def scored_videos(db: Session) -> list[dict]:
    accs = {a.id: a for a in db.query(WatchAccount)}
    vids = db.query(SourceVideo).all()
    snaps: dict[str, list[VideoSnapshot]] = {}
    for s in db.query(VideoSnapshot).order_by(VideoSnapshot.ts):
        snaps.setdefault(s.video_id, []).append(s)
    by_acc: dict[str, list[SourceVideo]] = {}
    for v in vids:
        by_acc.setdefault(v.account_id, []).append(v)
    base: dict[str, tuple[float, float]] = {}
    for aid, vs in by_acc.items():
        recent = sorted(vs, key=lambda v: v.posted_at or v.first_seen, reverse=True)[:30]
        med_plays = statistics.median([v.plays for v in recent]) if recent else 0
        engs = [(v.likes + v.comments + v.shares) / v.plays for v in recent if v.plays]
        base[aid] = (med_plays, statistics.median(engs) if engs else 0)
    now = datetime.utcnow()
    rows = []
    for v in vids:
        a = accs[v.account_id]
        med_plays, med_eng = base[v.account_id]
        eng = (v.likes + v.comments + v.shares) / v.plays if v.plays else 0
        ss = snaps.get(v.id, [])
        velocity = None
        if len(ss) >= 2 and (ss[-1].ts - ss[-2].ts).total_seconds() > 3600:
            velocity = (ss[-1].plays - ss[-2].plays) / ((ss[-1].ts - ss[-2].ts).total_seconds() / 86400)
        multiple = v.plays / med_plays if med_plays else 0
        age_h = ((now - v.posted_at).total_seconds() / 3600) if v.posted_at else None
        rows.append({
            "id": v.id, "external_id": v.external_id, "url": v.url, "cover": cover_url(v.external_id, v.cover), "text": v.text, "hashtags": v.hashtags,
            "music": v.music, "duration": v.duration, "is_ad": v.is_ad,
            "posted_at": v.posted_at.isoformat() if v.posted_at else None, "age_hours": round(age_h, 1) if age_h is not None else None,
            "plays": v.plays, "likes": v.likes, "comments": v.comments, "shares": v.shares, "collects": v.collects,
            "account": {"id": a.id, "handle": a.handle, "brand": a.brand, "market": a.market, "kind": a.kind, "followers": a.followers},
            "multiple": round(multiple, 2), "engagement": round(eng * 100, 2), "share_rate": round((v.shares / v.plays * 100) if v.plays else 0, 3),
            "velocity": round(velocity) if velocity is not None else None,
            "boosted": multiple >= 3 and med_eng > 0 and eng < med_eng / 2,
            "trend": [{"ts": s.ts.isoformat(), "plays": s.plays} for s in ss[-14:]],
            "ref_ad_no": v.ref_ad_no,
        })
    for market in {r["account"]["market"] for r in rows}:
        idx = [k for k, r in enumerate(rows) if r["account"]["market"] == market]
        cols = {name: _pct([rows[k][name] for k in idx]) for name in ("multiple", "plays", "share_rate", "engagement")}
        vel_idx = [k for k in idx if rows[k]["velocity"] is not None]
        vp = _pct([rows[k]["velocity"] for k in vel_idx])
        vel = {k: vp[j] for j, k in enumerate(vel_idx)}
        for pos, k in enumerate(idx):
            parts = {"multiple": (0.35, cols["multiple"][pos]), "plays": (0.25, cols["plays"][pos]), "share_rate": (0.20, cols["share_rate"][pos])}
            if k in vel:
                parts["velocity"] = (0.10, vel[k])
            wsum = sum(w for w, _ in parts.values())
            hot = sum(w * p for w, p in parts.values()) / wsum
            quality = 0.6 * cols["engagement"][pos] + 0.4 * cols["share_rate"][pos]
            r = rows[k]
            r["hot_score"], r["quality_score"] = round(hot), round(quality)
            r["breakdown"] = {name: round(p) for name, (_, p) in parts.items()}
            if r["age_hours"] is not None and r["age_hours"] < 72:
                r["grade"] = "观察中"
            elif hot >= 85 and r["plays"] >= HOT_PLAYS:
                r["grade"] = "爆款"
            elif quality >= 85 and r["multiple"] >= 3:
                r["grade"] = "精品"
            else:
                r["grade"] = ""
    return rows


SP_WORDS = {"续航": ["battery", "mah", "charge", "charging", "power", "电池", "续航"],
            "拍照": ["camera", "photo", "selfie", "night", "zoom", "lens", "拍照", "镜头"],
            "存储": ["storage", "memory", "gb", "rom", "存储"],
            "性能": ["gaming", "game", "fps", "chip", "processor", "speed", "性能"]}


def guess_selling_point(text: str, tags: list[str]) -> str:
    t = (text + " " + " ".join(tags)).lower()
    hits = {sp: sum(t.count(w) for w in ws) for sp, ws in SP_WORDS.items()}
    sp, n = max(hits.items(), key=lambda x: x[1])
    return sp if n else "其他"


def promote(db: Session, video_id: str) -> RefAd:
    """人工审核通过：把视频加入爆款库，可在画布里「一键洗剧本」。"""
    row = next((r for r in scored_videos(db) if r["id"] == video_id), None)
    v = db.get(SourceVideo, video_id)
    if not v or not row:
        raise KeyError(video_id)
    if v.ref_ad_no:
        return db.query(RefAd).filter(RefAd.no == v.ref_ad_no).first()
    a = db.get(WatchAccount, v.account_id)
    no = (max([n for (n,) in db.query(RefAd.no)] or [0])) + 1
    text = (v.text or "").strip()
    hook = (text.split("\n")[0][:28] or f"@{a.handle} 视频")
    va = db.get(VideoAnalysis, v.id)
    ai = (va.data if va else {}) or {}
    ai_sps = [x for x in (ai.get("selling_points") or []) if isinstance(x, str)]
    # 平台卖点库只有续航 / 拍照 / 存储 / 性能，AI 卖点映射过去，映射不到再按文案猜
    sp_map = {"续航": "续航", "快充": "续航", "拍照": "拍照", "夜拍": "拍照", "自拍美颜": "拍照", "存储": "存储", "性能游戏": "性能"}
    sp = next((sp_map[x] for x in ai_sps if x in sp_map), None) or guess_selling_point(text, v.hashtags or [])
    if ai.get("hook") and ai["hook"] != "未知":
        hook = ai["hook"][:28]
    shots = []
    for line in ai.get("shots") or []:
        m = re.match(r"\s*([0-9]+\s*[–\-~]\s*[0-9]+\s*s)\s*(.*)", str(line))
        shots.append([m.group(1).replace(" ", ""), m.group(2)] if m else ["", str(line)])
    days = max(0, (datetime.utcnow() - v.posted_at).days) if v.posted_at else 0
    ad = RefAd(id=new_id("ad"), no=no, source="TikTok 账号监控", platform="TikTok", brand=a.brand or a.handle, market=a.market,
               title=(text.split("\n")[0][:28] or f"@{a.handle} 视频"), hook=hook, selling_point=sp, days_running=days, variants=1,
               ctr_range="未公开", vtr=0, is_estimated=False, hot_score=row["hot_score"],
               dna={"source_video_id": v.id, "external_id": v.external_id, "url": v.url, "account": f"@{a.handle}", "text": text, "hashtags": v.hashtags,
                    "music": v.music, "duration": v.duration, "plays": v.plays, "likes": v.likes, "comments": v.comments,
                    "shares": v.shares, "multiple": row["multiple"], "engagement": row["engagement"], "grade": row["grade"],
                    "hook": hook, "selling_point": sp,
                    **({"shots": shots} if shots else {}),
                    **({k: ai[k] for k in ("product", "scene", "talent", "pacing", "cta", "why_viral", "script_type", "selling_point_detail") if ai.get(k)}),
                    **({"persona": ai["talent"], "bgm": v.music} if ai.get("talent") else {})})
    db.add(ad)
    v.ref_ad_no = no
    db.commit()
    return ad
