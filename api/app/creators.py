"""达人雷达：按市场找 TikTok 达人 → 拉最近的公开视频算指标 → 分级 → 判断适合带哪条产品线 → 适配分 + 报价预估。
外联（写邮件、发送、回复、报价）是二期，目前只做演示：不会真的发邮件。

- 找人：关键词搜视频取作者（Apify）；竞品雷达里竞品官方号视频 @ 过的达人（不花钱，已经接过手机单）；手动添加
- 指标（最近 20 条）：播放中位数 / 平均数、互动率、分享率、更新频率、带广告标的比例、提到过的手机品牌
- 分级：头部 ≥100 万粉；肩部 50–100 万；腰部 10–50 万；尾部 1–10 万；素人 <1 万
- 适配分 = 内容匹配 0.40 + 互动 0.25 + 播放稳定 0.15 + 品牌安全 0.10 + 近期没接竞品 0.10
- 报价预估 = 播放中位数 ÷ 1000 × 该市场 CPM（假设值，设置里可改，拿到真实报价后校准）× 0.7–1.3
"""
import asyncio
import logging
import random
import re
import statistics
from datetime import datetime, timedelta

from app import settings_store
from app.adapters import apify, llm
from app.db import SessionLocal
from app.models import Creator, Setting, SourceVideo, WatchAccount, new_id
from app.monitor import BRAND_KEYS, guess_brand, looks_official

log = logging.getLogger(__name__)

TIERS = [(1_000_000, "头部"), (500_000, "肩部"), (100_000, "腰部"), (10_000, "尾部"), (0, "素人")]
MIN_FOLLOWERS = 5_000  # 搜到的作者粉丝太少的不要
OWN = {"TECNO", "Infinix", "itel"}
CATEGORIES = ["科技测评", "开箱", "搞笑短剧", "生活方式 / Vlog", "时尚美妆", "游戏", "音乐舞蹈", "美食", "体育", "学生 / 校园",
              "家庭育儿", "商业 / 创业", "宗教 / 励志", "新闻时事", "其他"]
PRODUCT_LINES = {
    "TECNO Camon": "拍照 / 人像自拍，适合时尚美妆、生活方式、年轻女性",
    "TECNO Pova": "游戏性能 + 大电池，适合游戏、年轻男性、性能党",
    "TECNO Spark": "性价比入门，适合学生、搞笑短剧、大众",
    "TECNO Phantom": "旗舰 / 折叠屏，适合科技测评、商务、高收入人群",
    "Infinix Note": "续航快充，适合商务、科技测评、跑生意的人",
    "Infinix Hot": "年轻性价比，适合学生、音乐舞蹈、潮流",
    "Infinix Zero": "自拍 / 前摄，适合时尚美妆、Vlog",
    "Infinix GT": "电竞游戏，适合游戏主播",
    "itel": "入门长续航，适合家庭、乡村生活、首次换智能机的人",
}
# 没有大模型时按关键词粗分内容类型
CAT_WORDS = {
    "科技测评": ["review", "tech", "specs", "camera test", "vs", "comparison", "benchmark", "测评"],
    "开箱": ["unbox", "unboxing", "开箱"],
    "搞笑短剧": ["comedy", "skit", "funny", "prank", "lol", "😂", "naijacomedy"],
    "生活方式 / Vlog": ["vlog", "dayinmylife", "lifestyle", "routine", "grwm"],
    "时尚美妆": ["makeup", "beauty", "fashion", "outfit", "style", "skincare"],
    "游戏": ["gaming", "pubg", "codm", "freefire", "game", "gamer", "efootball"],
    "音乐舞蹈": ["dance", "music", "afrobeats", "song", "challenge", "amapiano"],
    "美食": ["food", "recipe", "cooking", "jollof", "kitchen"],
    "体育": ["football", "soccer", "sport", "gym", "fitness", "cricket"],
    "学生 / 校园": ["student", "school", "campus", "university", "exam"],
    "家庭育儿": ["family", "mom", "baby", "kids", "parenting"],
    "商业 / 创业": ["business", "money", "hustle", "entrepreneur", "sales"],
}
CAT_LINES = {"科技测评": ["TECNO Phantom", "Infinix Note", "TECNO Pova"], "开箱": ["TECNO Phantom", "TECNO Camon"],
             "搞笑短剧": ["TECNO Spark", "Infinix Hot"], "生活方式 / Vlog": ["TECNO Camon", "Infinix Zero"],
             "时尚美妆": ["TECNO Camon", "Infinix Zero"], "游戏": ["Infinix GT", "TECNO Pova"], "音乐舞蹈": ["Infinix Hot", "TECNO Spark"],
             "美食": ["itel", "TECNO Spark"], "体育": ["TECNO Pova", "Infinix Hot"], "学生 / 校园": ["TECNO Spark", "Infinix Hot"],
             "家庭育儿": ["itel", "TECNO Spark"], "商业 / 创业": ["Infinix Note", "TECNO Phantom"]}
DEFAULT_KEYWORDS = {
    "尼日利亚": ["phone review nigeria", "naija tech", "unboxing lagos", "naija comedy skit", "lagos lifestyle vlog"],
    "巴基斯坦": ["mobile review pakistan", "urdu tech review", "pakistan unboxing", "pakistani vlog", "pubg pakistan"],
}
DEFAULT_CPM = {"尼日利亚": 1.5, "巴基斯坦": 1.0, "其他": 3.0}  # 美元 / 千次播放：假设值，拿到真实报价后在设置里改
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SPONSOR_RE = re.compile(r"#(ad|sponsored|partner|paidpartnership|collab)\b|paid partnership|in partnership with", re.I)
_jobs: dict[str, dict] = {}


# ---------- 设置 ----------

def get_settings() -> dict:
    with SessionLocal() as db:
        s = db.get(Setting, "creators")
        v = (s.value if s else {}) or {}
    return {"cpm": {**DEFAULT_CPM, **(v.get("cpm") or {})}, "keywords": {**DEFAULT_KEYWORDS, **(v.get("keywords") or {})}}


def set_settings(values: dict) -> dict:
    cpm = {str(k): max(0.05, min(100.0, float(x))) for k, x in (values.get("cpm") or {}).items() if str(x).replace(".", "", 1).isdigit()}
    kw = {str(k): [str(w).strip() for w in ws if str(w).strip()][:10] for k, ws in (values.get("keywords") or {}).items() if isinstance(ws, list)}
    with SessionLocal() as db:
        s = db.get(Setting, "creators") or Setting(key="creators", value={})
        old = dict(s.value or {})
        s.value = {**old, "cpm": {**(old.get("cpm") or {}), **cpm}, "keywords": {**(old.get("keywords") or {}), **kw}}
        db.merge(s)
        db.commit()
    rescore_all()
    return get_settings()


# ---------- 指标 / 分级 / 适配分 / 报价 ----------

def tier_of(followers: int | None) -> str:
    f = followers or 0
    return next(name for floor, name in TIERS if f >= floor)


def _brands_in(text: str) -> set[str]:
    t = (text or "").lower()
    return {b for k, b in BRAND_KEYS.items() if re.search(rf"(?<![a-z]){k}", t)}


def compute_stats(items: list[dict], now: datetime | None = None) -> dict:
    """items：apify.normalize 后的视频。"""
    now = now or datetime.utcnow()
    vs = sorted(items, key=lambda v: v.get("posted_at") or now, reverse=True)[:20]
    plays = [v["plays"] for v in vs]
    engs = [(v["likes"] + v["comments"] + v["shares"]) / v["plays"] for v in vs if v["plays"]]
    shares = [v["shares"] / v["plays"] for v in vs if v["plays"]]
    dates = [v["posted_at"] for v in vs if v.get("posted_at")]
    span_days = max(1.0, (max(dates) - min(dates)).total_seconds() / 86400) if len(dates) >= 2 else None
    sponsored, brand_counts, comp_recent = [], {}, set()
    for v in vs:
        text = f"{v.get('text', '')} {' '.join('#' + h for h in v.get('hashtags') or [])}"
        is_sp = bool(v.get("is_ad") or SPONSOR_RE.search(text))
        bs = _brands_in(text)
        for b in bs:
            brand_counts[b] = brand_counts.get(b, 0) + 1
        if is_sp:
            sponsored.append(v)
            if v.get("posted_at") and now - v["posted_at"] < timedelta(days=60):
                comp_recent |= {b for b in bs if b not in OWN}
    med, avg = (statistics.median(plays), statistics.mean(plays)) if plays else (0, 0)
    tags: dict[str, int] = {}
    for v in vs:
        for h in v.get("hashtags") or []:
            tags[h.lower()] = tags.get(h.lower(), 0) + 1
    return {
        "n": len(vs), "median_plays": int(med), "avg_plays": int(avg), "max_plays": max(plays) if plays else 0,
        "stability": round(med / avg, 2) if avg else 0,
        "engagement": round(statistics.median(engs) * 100, 2) if engs else 0,
        "share_rate": round(statistics.median(shares) * 100, 3) if shares else 0,
        "posts_per_week": round(len(dates) / span_days * 7, 1) if span_days else None,
        "sponsored": len(sponsored), "sponsored_ratio": round(len(sponsored) / len(vs), 2) if vs else 0,
        "brands": dict(sorted(brand_counts.items(), key=lambda x: -x[1])),
        "competitor_recent": sorted(comp_recent),  # 最近 60 天接过的竞品单
        "own_brands": sorted(b for b in brand_counts if b in OWN),
        "top_tags": [t for t, _ in sorted(tags.items(), key=lambda x: -x[1])[:10]],
        "last_post": max(dates).isoformat() if dates else None,
    }


def pick_videos(items: list[dict], n: int = 6) -> list[dict]:
    out = []
    for v in sorted(items, key=lambda v: -v["plays"])[:n]:
        text = f"{v.get('text', '')} {' '.join('#' + h for h in v.get('hashtags') or [])}"
        out.append({"url": v.get("url", ""), "cover": v.get("cover", ""), "text": (v.get("text") or "")[:160], "plays": v["plays"],
                    "engagement": round((v["likes"] + v["comments"] + v["shares"]) / v["plays"] * 100, 2) if v["plays"] else 0,
                    "posted_at": v["posted_at"].isoformat() if v.get("posted_at") else None,
                    "sponsored": bool(v.get("is_ad") or SPONSOR_RE.search(text)), "brands": sorted(_brands_in(text))})
    return out


def price_of(stats: dict, market: str, cpm: dict | None = None) -> dict:
    cpm = cpm or get_settings()["cpm"]
    rate = cpm.get(market) or cpm.get("其他") or 3.0
    base = (stats.get("median_plays") or 0) / 1000 * rate
    return {"low": int(round(base * 0.7, -1)) if base >= 15 else int(base * 0.7), "high": int(round(base * 1.3, -1)) if base >= 15 else int(base * 1.3) + 1,
            "currency": "USD", "cpm": rate, "basis": f"播放中位数 {stats.get('median_plays', 0):,} ÷ 1000 × CPM ${rate:g}（假设值）× 0.7–1.3",
            "assumed": True}


def fit_of(stats: dict, analysis: dict) -> tuple[int, str, dict]:
    """返回 (适配分, 最合适的产品线, 分项)。"""
    fits = sorted(analysis.get("product_fit") or [], key=lambda f: -(f.get("score") or 0))
    content = (fits[0].get("score") or 0) if fits else 40
    eng = min(100.0, (stats.get("engagement") or 0) * 10)  # 互动率 10% 及以上满分
    stab = min(100.0, (stats.get("stability") or 0) * 125)
    safety = {"ok": 100, "caution": 60, "risk": 0}.get(analysis.get("brand_safety") or "ok", 60)
    exclusive = 0 if stats.get("competitor_recent") else 100
    parts = {"内容匹配": round(content), "互动": round(eng), "播放稳定": round(stab), "品牌安全": safety, "近期没接竞品": exclusive}
    score = 0.40 * content + 0.25 * eng + 0.15 * stab + 0.10 * safety + 0.10 * exclusive
    return round(score), (fits[0].get("line") if fits else ""), parts


# ---------- 内容判断（大模型；没配置时按关键词粗分） ----------

ANALYZE_PROMPT = """你是传音（TECNO / Infinix / itel）在{market}的达人营销负责人，判断这个 TikTok 达人适不适合合作、适合带哪条产品线。
只输出 JSON：
{{"categories": ["从这些里选 1–3 个：{cats}"],
  "audience": "粉丝大概是什么人（年龄段、性别、城乡、消费能力），一句话，看不出来写「看不出」",
  "language": "主要用什么语言（英语 / 皮钦语 / 约鲁巴语 / 乌尔都语……）",
  "style": "内容风格一句话",
  "product_fit": [{{"line": "从这些里选：{lines}", "score": 0-100, "reason": "为什么适合 / 不适合，一句话"}}],
  "brand_safety": "ok / caution / risk（有没有低俗、政治、争议内容）",
  "safety_note": "有问题时说明，没有写空字符串",
  "summary": "一句话结论：值不值得合作、怎么合作（如 开箱测评 / 剧情植入 / 挑战赛）"}}
product_fit 给 3 条最合适的，score 是内容和产品线的匹配度。"""


def _heuristic(c: Creator, items: list[dict]) -> dict:
    text = " ".join(f"{v.get('text', '')} {' '.join(v.get('hashtags') or [])}" for v in items).lower() + " " + (c.bio or "").lower()
    hits = sorted(((sum(text.count(w) for w in ws), cat) for cat, ws in CAT_WORDS.items()), reverse=True)
    cats = [cat for n, cat in hits if n > 0][:2] or ["其他"]
    lines: dict[str, int] = {}
    for k, cat in enumerate(cats):
        for j, line in enumerate(CAT_LINES.get(cat, ["TECNO Spark"])):
            lines[line] = max(lines.get(line, 0), 80 - k * 15 - j * 10)
    return {"categories": cats, "audience": "看不出（没有配置大模型，只按关键词粗分）", "language": "", "style": "",
            "product_fit": [{"line": l, "score": s, "reason": f"内容以「{cats[0]}」为主"} for l, s in sorted(lines.items(), key=lambda x: -x[1])[:3]],
            "brand_safety": "ok", "safety_note": "", "summary": "", "by": "关键词"}


async def analyze_content(c: Creator, items: list[dict], stats: dict) -> dict:
    if not settings_store.llm_enabled():
        return _heuristic(c, items)
    caps = "\n".join(f"- 播放 {v['plays']:,}：{(v.get('text') or '')[:150]} {' '.join('#' + h for h in (v.get('hashtags') or [])[:6])}"
                     for v in sorted(items, key=lambda v: -v["plays"])[:15])
    user = (f"账号 @{c.handle}（{c.nickname}），粉丝 {c.followers or '未知'}，简介：{c.bio or '无'}\n"
            f"最近 {stats['n']} 条：播放中位数 {stats['median_plays']:,}，互动率 {stats['engagement']}%，带广告标 {stats['sponsored']} 条，"
            f"提到的手机品牌 {stats['brands'] or '无'}\n视频文案：\n{caps}")
    try:
        out = await llm.chat_json(ANALYZE_PROMPT.format(market=c.market, cats="、".join(CATEGORIES), lines="、".join(PRODUCT_LINES)), user,
                                  task="analysis", timeout=90)
    except Exception as e:  # noqa: BLE001  模型出错就退回关键词判断
        log.warning("达人分析失败 @%s：%s", c.handle, e)
        return {**_heuristic(c, items), "note": f"大模型分析失败，按关键词粗分：{str(e)[:80]}"}
    fits = [{"line": str(f.get("line") or ""), "score": max(0, min(100, int(f.get("score") or 0))), "reason": str(f.get("reason") or "")}
            for f in out.get("product_fit") or [] if isinstance(f, dict) and f.get("line") in PRODUCT_LINES][:3]
    return {"categories": [x for x in out.get("categories") or [] if x in CATEGORIES][:3] or ["其他"],
            "audience": str(out.get("audience") or ""), "language": str(out.get("language") or ""), "style": str(out.get("style") or ""),
            "product_fit": fits or _heuristic(c, items)["product_fit"],
            "brand_safety": out.get("brand_safety") if out.get("brand_safety") in ("ok", "caution", "risk") else "ok",
            "safety_note": str(out.get("safety_note") or ""), "summary": str(out.get("summary") or ""),
            "by": settings_store.get_models()["analysis"]}


def apply(c: Creator, items: list[dict], analysis: dict) -> None:
    """把拉到的视频和分析结果写到达人上（不提交）。"""
    st = compute_stats(items)
    first = next((v for v in items if v.get("followers")), {})
    raw = (first.get("raw") or {}).get("authorMeta") or {}
    c.followers = first.get("followers") or c.followers
    c.nickname = first.get("nickname") or c.nickname
    c.verified = bool(first.get("verified")) or c.verified
    c.bio = first.get("bio") or c.bio
    c.avatar = raw.get("avatar") or raw.get("originalAvatarUrl") or c.avatar
    m = EMAIL_RE.search(c.bio or "")
    c.email = m.group(0) if m else c.email
    c.tier = tier_of(c.followers)
    c.stats = st
    c.videos = pick_videos(items)
    c.analysis = analysis
    c.fit_score, c.best_product, parts = fit_of(st, analysis)
    c.stats = {**st, "fit_parts": parts}
    c.price = price_of(st, c.market)
    c.status, c.error, c.analyzed_at = "ok", "", datetime.utcnow()


def rescore_all() -> None:
    """改了 CPM：重算报价（适配分不变）。"""
    cpm = get_settings()["cpm"]
    with SessionLocal() as db:
        for c in db.query(Creator):
            if c.stats:
                c.price = price_of(c.stats, c.market, cpm)
        db.commit()


# ---------- 找人 ----------

def start_job(kind: str, market: str) -> str:
    jid = new_id("cj")
    _jobs[jid] = {"id": jid, "kind": kind, "market": market, "status": "running", "stage": "准备", "found": 0, "added": [], "error": "",
                  "started": datetime.utcnow().isoformat()}
    for old in list(_jobs)[:-20]:
        _jobs.pop(old, None)
    return jid


def competitor_mentions(market: str) -> dict[str, str]:
    """竞品雷达里竞品官方号视频文案 @ 过的账号（多半是合作达人）。返回 {handle: 来源说明}。"""
    out: dict[str, str] = {}
    with SessionLocal() as db:
        accs = {a.id: a for a in db.query(WatchAccount).filter(WatchAccount.market == market)}
        own = {a.handle.lower() for a in accs.values()}
        for v in db.query(SourceVideo).filter(SourceVideo.account_id.in_(list(accs))):
            for h in re.findall(r"@([A-Za-z0-9._]{2,24})", v.text or ""):
                h = h.rstrip(".")
                if h.lower() not in own and not guess_brand(h):
                    out.setdefault(h, f"@{accs[v.account_id].handle}（{accs[v.account_id].brand or '竞品'}）的视频里 @ 过")
    return out


async def _profiles(job: dict, handles: list[str]) -> dict[str, list[dict]]:
    job["stage"] = f"拉取 {len(handles)} 个达人最近的视频（Apify）"
    items = await apify.fetch_profiles(handles, per_profile=20)
    by: dict[str, list[dict]] = {}
    for it in items:
        by.setdefault((it["handle"] or "").lower(), []).append(it)
    return by


async def _build(job: dict, cands: list[dict], market: str) -> None:
    """cands：[{handle, source, found_by}]。拉视频 → 算指标 → 分析 → 入库。"""
    by = await _profiles(job, [c["handle"] for c in cands])
    sem = asyncio.Semaphore(3)

    async def one(cand: dict) -> None:
        items = by.get(cand["handle"].lower()) or []
        if not items:
            job.setdefault("skipped", []).append(f"@{cand['handle']}：没拉到视频（私密或不存在）")
            return
        c = Creator(id=new_id("cr"), handle=items[0]["handle"] or cand["handle"], market=market, source=cand["source"], found_by=cand.get("found_by", ""))
        stats = compute_stats(items)
        c.followers, c.bio, c.nickname = items[0].get("followers"), items[0].get("bio") or "", items[0].get("nickname") or ""
        async with sem:
            job["stage"] = f"分析 @{c.handle}"
            analysis = await analyze_content(c, items, stats)
        apply(c, items, analysis)
        with SessionLocal() as db:
            if db.query(Creator).filter(Creator.handle.ilike(c.handle), Creator.market == market).first():
                return
            db.add(c)
            db.commit()
        job["added"].append(c.handle)

    await asyncio.gather(*(one(c) for c in cands))


async def discover(jid: str, market: str, keywords: list[str], from_competitors: bool, limit: int) -> None:
    job = _jobs[jid]
    try:
        with SessionLocal() as db:
            have = {c.handle.lower() for c in db.query(Creator).filter(Creator.market == market)}
            watched = {a.handle.lower() for a in db.query(WatchAccount)}
        cands: dict[str, dict] = {}
        if from_competitors:
            for h, why in competitor_mentions(market).items():
                cands.setdefault(h.lower(), {"handle": h, "source": "竞品合作", "found_by": why, "followers": None, "rank": 0})
        if keywords:
            job["stage"] = f"按关键词搜视频：{'、'.join(keywords)}（Apify）"
            items = await apify.search_videos(keywords, per_query=30, on_progress=lambda p: job.update(progress=p))
            for it in items:
                h = it["handle"]
                info = {"handle": h, "nickname": it["nickname"], "verified": it["verified"], "followers": it["followers"], "bio": it["bio"],
                        "brand": guess_brand(h, it["nickname"])}
                if not h or looks_official(info) or (it["followers"] or 0) < MIN_FOLLOWERS:
                    continue
                q = next((k for k in keywords if any(w in (it["text"] or "").lower() for w in k.lower().split())), keywords[0])
                cands.setdefault(h.lower(), {"handle": h, "source": "搜索", "found_by": f"搜「{q}」", "followers": it["followers"], "rank": 1})
        pick = [c for k, c in cands.items() if k not in have and k not in watched]
        pick = sorted(pick, key=lambda c: (c["rank"], -(c["followers"] or 0)))[:limit]
        job["found"] = len(pick)
        if not pick:
            job.update(status="done", stage="没有找到新的达人（已经在列表里的会跳过）")
            return
        await _build(job, pick, market)
        job.update(status="done", stage=f"完成：新增 {len(job['added'])} 个达人")
    except Exception as e:  # noqa: BLE001
        log.exception("达人发现失败")
        job.update(status="error", error=str(e)[:300] or type(e).__name__, stage="失败")


async def add_manual(jid: str, market: str, handles: list[str]) -> None:
    job = _jobs[jid]
    try:
        job["found"] = len(handles)
        await _build(job, [{"handle": h, "source": "手动", "found_by": "手动添加"} for h in handles], market)
        job.update(status="done", stage=f"完成：新增 {len(job['added'])} 个达人")
    except Exception as e:  # noqa: BLE001
        log.exception("添加达人失败")
        job.update(status="error", error=str(e)[:300] or type(e).__name__, stage="失败")


async def reanalyze(cid: str) -> None:
    with SessionLocal() as db:
        c = db.get(Creator, cid)
        if not c:
            return
        c.status, c.error = "analyzing", ""
        db.commit()
        handle, demo = c.handle, c.demo
    try:
        if demo:
            with SessionLocal() as db:
                items = _demo_items_for(db.get(Creator, cid))
        else:
            items = [it for it in await apify.fetch_profiles([handle], per_profile=20) if (it["handle"] or "").lower() == handle.lower()]
        if not items:
            raise RuntimeError("没拉到视频（账号私密、改名或不存在）")
        with SessionLocal() as db:
            c = db.get(Creator, cid)
            analysis = await analyze_content(c, items, compute_stats(items)) if not demo else _heuristic(c, items)
            apply(c, items, analysis)
            db.commit()
    except Exception as e:  # noqa: BLE001
        with SessionLocal() as db:
            c = db.get(Creator, cid)
            if c:
                c.status, c.error = "error", str(e)[:300] or type(e).__name__
                db.commit()


# ---------- 演示数据（没有 Apify 余额时展示用；标明「演示」） ----------

DEMO = {
    "尼日利亚": [
        ("demo_naijatechguy", "Naija Tech Guy", 1_420_000, "tech", "Honest phone reviews 🇳🇬 | Business: naijatechguy.biz@gmail.com"),
        ("demo_lagosbeauty", "Tolu | Lagos Beauty", 612_000, "beauty", "Makeup • Skincare • GRWM 💄 collabs: tolubeauty.collab@gmail.com"),
        ("demo_mrfunnyskits", "Mr Funny Skits", 2_300_000, "comedy", "Comedy skits every day 😂 Bookings via DM"),
        ("demo_campus_ade", "Ade on Campus", 184_000, "student", "UNILAG student life 📚 | adecampus@gmail.com"),
        ("demo_gamerkingng", "GamerKing NG", 356_000, "gaming", "CODM • Free Fire • eFootball 🎮 gamerkingng@outlook.com"),
        ("demo_mamaiyabo_kitchen", "Mama Iyabo Kitchen", 72_000, "food", "Naija recipes for busy families 🍲"),
        ("demo_afrodance_tee", "Tee Afro Dance", 95_000, "dance", "Afrobeats & Amapiano dance challenges 💃"),
        ("demo_hustle_with_kay", "Hustle With Kay", 28_000, "business", "Small business tips for Nigerians | kay.hustle@gmail.com"),
    ],
    "巴基斯坦": [
        ("demo_urdutechreview", "Urdu Tech Review", 980_000, "tech", "Mobile reviews in Urdu 🇵🇰 business: urdutech@gmail.com"),
        ("demo_lahore_vlogs", "Lahore Vlogs", 430_000, "vlog", "Daily vlogs from Lahore ✨"),
        ("demo_pubgking_pk", "PUBG King PK", 1_150_000, "gaming", "PUBG Mobile montages 🎮 sponsor: pubgkingpk@gmail.com"),
        ("demo_ayesha_style", "Ayesha Style", 210_000, "beauty", "Fashion & makeup | ayesha.style.pk@gmail.com"),
        ("demo_karachi_comedy", "Karachi Comedy Club", 64_000, "comedy", "Funny sketches every Friday 😂"),
    ],
}
DEMO_TEXT = {
    "tech": ["Full review: is this the best phone under 200k? #phonereview #tech", "Camera test vs Samsung A15 #tech #comparison",
             "Unboxing the new Redmi Note #unboxing #xiaomi #ad", "Battery drain test 🔋 #tech #review"],
    "beauty": ["GRWM for a Lagos wedding 💄 #grwm #makeup", "5 minute makeup routine #beauty #makeup", "Skincare that works in this heat #skincare",
               "Selfie lighting hack 📸 #beauty #selfie"],
    "comedy": ["When NEPA takes light during the match 😂 #comedy #skit", "Mum vs my phone 😂 #naijacomedy #skit", "Office boss be like #comedy #funny",
               "POV: your phone dies at the bus stop #skit"],
    "student": ["Day in my life as a UNILAG student #student #campus", "Exam week survival tips #school", "What's in my school bag #student #vlog",
                "Campus hostel tour #campus"],
    "gaming": ["1v4 clutch in CODM 🔥 #gaming #codm", "Free Fire settings for low-end phones #freefire #gaming", "eFootball top goals #efootball",
               "This phone runs PUBG at 90fps? #gaming #pubg"],
    "food": ["Jollof rice the right way #food #jollof", "Cooking for 6 on a budget #recipe #family", "Egusi soup recipe #cooking", "Market run vlog #food"],
    "dance": ["New Amapiano challenge 💃 #dance #amapiano", "Afrobeats choreography #dance #afrobeats", "Dance with my mum 😂 #dance #challenge",
              "Trending sound remix #music #dance"],
    "business": ["How I started with 20k naira #business #hustle", "3 side hustles that work #money #business", "Selling on WhatsApp tips #sales",
                 "My phone runs my business #entrepreneur"],
    "vlog": ["A day in Lahore old city #vlog #lifestyle", "Ramadan iftar vlog #vlog", "Road trip to Murree #vlog #travel", "My morning routine #routine"],
}


def _demo_items(seed_key: str, kind: str = "", followers: int = 100_000, handle: str = "demo") -> list[dict]:
    rnd = random.Random(seed_key)
    texts = DEMO_TEXT.get(kind) or DEMO_TEXT["vlog"]
    now = datetime.utcnow()
    items = []
    reach = rnd.uniform(0.03, 0.4)  # 每个达人的「播放 / 粉丝」水平不同
    eng = rnd.uniform(0.015, 0.08)  # 互动率水平不同
    spiky = rnd.random() < 0.4  # 有的达人靠一两条爆款撑着，平时播放很低
    for k in range(20):
        plays = int(followers * reach * rnd.lognormvariate(0, 1.0 if spiky else 0.35))
        items.append({"external_id": f"{seed_key}-{k}", "handle": handle, "nickname": "", "followers": followers, "verified": False, "bio": "",
                      "url": f"https://www.tiktok.com/@{handle}", "cover": "", "text": texts[k % len(texts)], "hashtags": [],
                      "is_ad": "#ad" in texts[k % len(texts)], "posted_at": now - timedelta(days=k * rnd.uniform(1.5, 4)),
                      "plays": plays, "likes": int(plays * eng * rnd.uniform(0.7, 1.3)), "comments": int(plays * eng * 0.08),
                      "shares": int(plays * eng * rnd.uniform(0.03, 0.12)), "collects": 0, "raw": {}})
    return items


def load_demo(market: str) -> int:
    rows = DEMO.get(market) or DEMO["尼日利亚"]
    n = 0
    with SessionLocal() as db:
        have = {c.handle.lower() for c in db.query(Creator).filter(Creator.market == market)}
        for handle, nick, fans, kind, bio in rows:
            if handle in have:
                continue
            c = Creator(id=new_id("cr"), handle=handle, nickname=nick, market=market, followers=fans, bio=bio, source="演示",
                        found_by="演示数据", demo=True)
            items = _demo_items(c.id, kind, fans, handle)
            for it in items:
                it.update(nickname=nick, bio=bio)
            c.stats = {"demo_kind": kind}
            apply(c, items, _heuristic(c, items))
            c.analysis = {**c.analysis, "summary": "演示数据：账号和数据都是虚构的，只用来展示页面。"}
            c.stats = {**c.stats, "demo_kind": kind}
            db.add(c)
            n += 1
        db.commit()
    return n


def _demo_items_for(c: Creator) -> list[dict]:
    return _demo_items(c.id, (c.stats or {}).get("demo_kind", ""), c.followers or 100_000, c.handle)


def creator_dict(c: Creator, full: bool = False) -> dict:
    d = {"id": c.id, "handle": c.handle, "nickname": c.nickname, "market": c.market, "followers": c.followers, "verified": c.verified,
         "email": c.email, "avatar": c.avatar, "source": c.source, "found_by": c.found_by, "tier": c.tier, "fit_score": c.fit_score,
         "best_product": c.best_product, "price": c.price, "status": c.status, "error": c.error, "demo": c.demo,
         "categories": (c.analysis or {}).get("categories") or [], "summary": (c.analysis or {}).get("summary") or "",
         "stats": {k: (c.stats or {}).get(k) for k in ("median_plays", "avg_plays", "engagement", "share_rate", "posts_per_week", "sponsored",
                                                        "competitor_recent", "own_brands", "fit_parts", "stability")},
         "stage": (c.outreach or {}).get("stage") or "待联系",
         "analyzed_at": c.analyzed_at.isoformat() if c.analyzed_at else None}
    if full:
        d.update(bio=c.bio, stats_full=c.stats, videos=c.videos, analysis=c.analysis, outreach=c.outreach or {})
    return d
