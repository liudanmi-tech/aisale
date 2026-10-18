"""竞品热点分析报告。

1. 选视频：按市场 / 品牌 / 时间范围，取爆款分最高的 N 条（默认不含传音自有账号）。
2. 逐条拆解（设置里的「analysis」模型，默认 Gemini 2.5 Flash）：看封面图 + 文案 + 字幕 + 公开数据，
   输出手机型号、卖点、场景、剧本类型、钩子、人物、节奏镜头、为什么火。结果按视频缓存。
3. 汇总：代码统计各维度的条数与播放占比（可复核），再交给「report」模型（默认 Claude Sonnet 5.5）写洞察和给传音的建议。

依据说明：模型没有逐秒看视频，镜头和节奏是根据封面、字幕和文案推断的，报告里会标注。
"""
import asyncio
import base64
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta

import httpx

from app import monitor, settings_store
from app.adapters import llm
from app.db import SessionLocal
from app.monitor import scored_videos
from app.models import Report, SourceVideo, VideoAnalysis, new_id

log = logging.getLogger(__name__)
media_transport: httpx.AsyncBaseTransport | None = None  # 测试时注入
CONCURRENCY = 4
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Referer": "https://www.tiktok.com/"}

SELLING_POINTS = ["续航", "快充", "拍照", "夜拍", "自拍美颜", "屏幕", "性能游戏", "存储", "外观轻薄", "耐用防水", "价格优惠", "AI 功能", "信号网络", "音质"]
SCRIPT_TYPES = ["真人测评", "情景剧", "痛点对比", "开箱", "产品展示", "达人口播", "挑战话题", "生活 vlog", "搞笑段子", "促销活动", "名人代言"]
HOOK_TYPES = ["痛点", "悬念", "对比", "反差", "提问", "数字冲击", "名人 / 达人", "福利促销", "情绪共鸣"]

VIDEO_PROMPT = f"""你是手机品牌的短视频广告分析师，在拆解竞品在 TikTok 上的热门视频。
根据给你的封面图、文案、字幕和公开数据，判断这条视频，只输出 JSON：
{{
  "brand": "品牌",
  "product": "具体机型（看不出写「未知」）",
  "price_tier": "入门 / 中端 / 旗舰 / 未知",
  "selling_points": ["从这些里选 1–3 个：{'、'.join(SELLING_POINTS)}；都不合适可自拟 2–4 字"],
  "selling_point_detail": "视频里卖点的原话或具体说法",
  "scene": "场景一句话",
  "scene_tags": ["2–3 个短标签，如 家庭、户外、市场、婚礼聚会、办公室、校园、夜晚、棚拍"],
  "script_type": ["从这些里选 1–2 个：{'、'.join(SCRIPT_TYPES)}"],
  "hook": "开头 3 秒大概怎么抓人",
  "hook_type": "从这些里选 1 个：{'、'.join(HOOK_TYPES)}",
  "talent": "出镜人物：性别、年龄段、风格、是否名人 / 达人；无人出镜写「无真人」",
  "talent_tag": "从这些里选 1 个：年轻女性、年轻男性、情侣 / 家庭、多人群像、名人、达人、无真人",
  "language": "口播 / 字幕语言，如 英语、皮钦语、乌尔都语",
  "pacing": "时长、镜头数和剪辑节奏",
  "shots": ["分镜 3–6 条，每条格式「起止秒 画面」，如「0–3s …」"],
  "cta": "行动号召，如 到店购买、点链接、无",
  "why_viral": "为什么火：结合数据（播放、互动率、爆款倍数、是否疑似加热投放）给出 1–2 句判断",
  "confidence": "高 / 中 / 低（信息少时写低）"
}}
规则：
- 只写有依据的内容。依据就是给你的封面图、文案、字幕和数据；文案里没写、封面里看不到的人物、场景、镜头，写「未知」。
- 只有文案、没有封面和字幕时：scene、talent、shots、pacing 只能从文案明确推出的部分写，推不出就写「未知」/ 空数组，confidence 写「低」。
- 不要套用上面格式说明里的示例，不要编造具体数字。"""

REPORT_PROMPT = """你是传音（TECNO / Infinix / itel）的海外营销策略分析师。下面是近期竞品在 TikTok 上的热门视频统计和逐条拆解。
请写一份给营销团队看的分析，用中文，具体、有判断，引用数据（条数、播放占比、代表视频的账号）。只输出 JSON：
{
  "headline": "一句话核心结论",
  "takeaways": ["3–6 条最重要的发现"],
  "products": "竞品主推哪些产品、价位段，各品牌打法差异",
  "selling_points": "集中在哪些卖点，怎么表达的，哪些说法最有效",
  "script_types": "什么类型的剧本最多、哪类播放最好",
  "scenes": "常见场景，以及为什么选这些场景",
  "talent": "模特 / 出镜人物的选择规律",
  "hooks": "钩子的常见套路，举 2–3 个代表例子",
  "pacing": "节奏和镜头的共性（说明这是根据封面、字幕推断的）",
  "why_viral": "这些视频为什么火：内容因素 vs 投放加热",
  "recommendations": ["给传音的 3–6 条可执行建议，具体到卖点、场景、剧本类型、人物、钩子"]
}"""


def _vtt_text(vtt: str) -> str:
    lines = []
    for ln in vtt.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith(("WEBVTT", "NOTE")) or "-->" in ln or ln.isdigit():
            continue
        if not lines or lines[-1] != ln:
            lines.append(re.sub(r"<[^>]+>", "", ln))
    return " ".join(lines)


async def _media(c: httpx.AsyncClient, v: SourceVideo) -> tuple[str | None, str]:
    """封面转成 data URL（TikTok 图片链接需要服务器代取）；字幕取英文优先。拿不到就跳过。"""
    cover = None
    if v.cover:
        try:
            r = await c.get(v.cover, headers=UA)
            if r.status_code == 200 and r.content and len(r.content) < 3_000_000:
                ctype = r.headers.get("content-type", "image/jpeg").split(";")[0]
                if ctype.startswith("image/"):
                    cover = f"data:{ctype};base64,{base64.b64encode(r.content).decode()}"
                    f = monitor._cover_file(v.external_id)  # 顺手存进本地封面缓存：TikTok 链接会过期，报告页以后用本地的
                    if v.external_id and not f.exists():
                        f.parent.mkdir(parents=True, exist_ok=True)
                        f.write_bytes(r.content)
        except Exception:  # noqa: BLE001
            pass
    subs = ""
    links = ((v.raw or {}).get("videoMeta") or {}).get("subtitleLinks") or []
    links = sorted(links, key=lambda x: 0 if str(x.get("language", "")).lower().startswith("en") else 1)
    for link in links[:2]:
        for url in (link.get("downloadLink"), link.get("tiktokLink")):
            if not url:
                continue
            try:
                r = await c.get(url, headers=UA)
                if r.status_code == 200 and r.text:
                    subs = _vtt_text(r.text)[:2000]
                    break
            except Exception:  # noqa: BLE001
                pass
        if subs:
            break
    return cover, subs


def _facts(row: dict) -> str:
    a = row["account"]
    return (f"账号 @{a['handle']}（{a['brand']}，{a['market']}，{a['kind']}，粉丝 {a['followers'] or '未知'}）\n"
            f"发布：{row['posted_at'] or '未知'}，时长 {row['duration'] or '未知'} 秒，音乐：{row['music'] or '未知'}\n"
            f"播放 {row['plays']:,}，点赞 {row['likes']:,}，评论 {row['comments']:,}，分享 {row['shares']:,}；"
            f"互动率 {row['engagement']}%，爆款倍数 {row['multiple']}×（相对账号近 30 条中位数），"
            f"{'疑似加热投放' if row['boosted'] else '未见加热迹象'}{'，平台标注为广告' if row['is_ad'] else ''}\n"
            f"文案：{row['text'] or '（无）'}\n话题：{' '.join('#' + t for t in row['hashtags']) or '（无）'}")


async def analyze_video(c: httpx.AsyncClient, v: SourceVideo, row: dict) -> tuple[dict, list[str]]:
    cover, subs = await _media(c, v)
    inputs = ["文案与数据"] + (["字幕"] if subs else []) + (["封面"] if cover else [])
    text = _facts(row) + (f"\n字幕：{subs}" if subs else "\n字幕：（没有拿到）")
    content: list[dict] | str = [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": cover}}] if cover else text
    msg = await llm.chat([{"role": "system", "content": VIDEO_PROMPT}, {"role": "user", "content": content}],
                         json_mode=True, task="analysis", timeout=120)
    return llm.parse_json(msg.get("content") or ""), inputs


def _as_list(x) -> list[str]:
    if isinstance(x, list):
        return [str(i).strip() for i in x if str(i).strip() and str(i).strip() != "未知"]
    return [str(x).strip()] if x and str(x).strip() != "未知" else []


def aggregate(items: list[tuple[dict, dict]]) -> dict:
    """items: (视频行, 拆解)。每个维度统计条数与播放占比，按播放排序。"""
    total = sum(r["plays"] for r, _ in items) or 1
    dims: dict[str, dict[str, dict]] = defaultdict(dict)

    def add(dim: str, key: str, r: dict) -> None:
        d = dims[dim].setdefault(key, {"name": key, "videos": 0, "plays": 0, "examples": []})
        d["videos"] += 1
        d["plays"] += r["plays"]
        if len(d["examples"]) < 3:
            d["examples"].append({"id": r["id"], "handle": r["account"]["handle"], "url": r["url"], "plays": r["plays"]})

    for r, a in items:
        brand = r["account"]["brand"] or a.get("brand") or "未知"  # 账号品牌由人确认过，比模型识别的写法统一
        add("brands", brand, r)
        prod = a.get("product") or "未知"
        add("products", prod if prod != "未知" else f"{brand} · 未知机型", r)
        for k in _as_list(a.get("selling_points")):
            add("selling_points", k, r)
        for k in _as_list(a.get("script_type")):
            add("script_types", k, r)
        for k in _as_list(a.get("scene_tags")):
            add("scenes", k, r)
        for k in _as_list(a.get("hook_type")):
            add("hook_types", k, r)
        for k in _as_list(a.get("talent_tag")):
            add("talent", k, r)
        for k in _as_list(a.get("language")):
            add("languages", k, r)
    out = {}
    for dim, d in dims.items():
        rows = sorted(d.values(), key=lambda x: -x["plays"])
        for x in rows:
            x["share"] = round(100 * x["plays"] / total, 1)
        out[dim] = rows
    return out


def _brief(r: dict, a: dict) -> str:
    return (f"- @{r['account']['handle']}（{a.get('brand')} {a.get('product')}）播放 {r['plays']:,}，互动 {r['engagement']}%，"
            f"{'疑似加热' if r['boosted'] else '自然'}；卖点 {'、'.join(_as_list(a.get('selling_points')))}（{a.get('selling_point_detail', '')}）；"
            f"场景 {a.get('scene')}；剧本 {'、'.join(_as_list(a.get('script_type')))}；钩子[{a.get('hook_type')}] {a.get('hook')}；"
            f"人物 {a.get('talent')}；节奏 {a.get('pacing')}；为什么火：{a.get('why_viral')}")


def start(params: dict) -> str:
    rid = new_id("rp")
    with SessionLocal() as db:
        db.add(Report(id=rid, params=params, status="running", progress={"stage": "准备", "done": 0, "total": 0}))
        db.commit()
    return rid


def _set(rid: str, **fields) -> None:
    with SessionLocal() as db:
        r = db.get(Report, rid)
        for k, v in fields.items():
            setattr(r, k, v)
        db.commit()


async def run(rid: str) -> None:
    try:
        await _run(rid)
    except Exception as e:  # noqa: BLE001
        log.exception("报告生成失败")
        _set(rid, status="error", error=(str(e) or type(e).__name__)[:300])


async def _run(rid: str) -> None:
    with SessionLocal() as db:
        p = db.get(Report, rid).params
        since = datetime.utcnow() - timedelta(days=int(p.get("days") or 30))
        rows = [r for r in scored_videos(db)
                if (not p.get("market") or r["account"]["market"] == p["market"])
                and (not p.get("brand") or r["account"]["brand"] == p["brand"])
                and (p.get("include_own") or r["account"]["kind"] != "传音自有")
                and r["posted_at"] and datetime.fromisoformat(r["posted_at"]) >= since]
        rows = sorted(rows, key=lambda r: -r["hot_score"])[: int(p.get("top") or 30)]
        cached = {a.video_id: a for a in db.query(VideoAnalysis).filter(VideoAnalysis.video_id.in_([r["id"] for r in rows]))}
        videos = {v.id: v for v in db.query(SourceVideo).filter(SourceVideo.id.in_([r["id"] for r in rows]))}
        cached = {k: (a.data, a.inputs) for k, a in cached.items()}
    if not rows:
        raise RuntimeError("这个范围里没有视频：换个市场 / 时间范围，或先同步账号")
    model = settings_store.get_models()["analysis"]
    results: dict[str, tuple[dict, list[str]]] = {k: v for k, v in cached.items() if not p.get("refresh")}
    done = {"n": len([r for r in rows if r["id"] in results])}
    _set(rid, progress={"stage": "逐条拆解视频", "done": done["n"], "total": len(rows)})
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(c: httpx.AsyncClient, r: dict) -> None:
        async with sem:
            try:
                data, inputs = await analyze_video(c, videos[r["id"]], r)
            except Exception as e:  # noqa: BLE001  单条失败不影响整份报告
                log.warning("视频拆解失败 %s: %s", r["id"], e)
                return
            results[r["id"]] = (data, inputs)
            with SessionLocal() as db:
                db.merge(VideoAnalysis(video_id=r["id"], data=data, model=model, inputs=inputs, created_at=datetime.utcnow()))
                db.commit()
            done["n"] += 1
            _set(rid, progress={"stage": "逐条拆解视频", "done": done["n"], "total": len(rows)})

    async with httpx.AsyncClient(timeout=20, transport=media_transport, follow_redirects=True) as c:
        await asyncio.gather(*(one(c, r) for r in rows if r["id"] not in results))
    items = [(r, results[r["id"]][0]) for r in rows if r["id"] in results]
    if not items:
        raise RuntimeError("视频拆解全部失败：请检查 OpenRouter Key 和「视频拆解」模型设置")
    _set(rid, progress={"stage": "撰写报告", "done": len(items), "total": len(rows)})
    stats = aggregate(items)
    stat_text = "\n".join(f"{dim}：" + "；".join(f"{x['name']} {x['videos']} 条 / 播放占比 {x['share']}%" for x in xs[:10])
                          for dim, xs in stats.items())
    briefs = "\n".join(_brief(r, a) for r, a in items[:40])
    head = f"范围：{p.get('market') or '全部市场'}，{p.get('brand') or '全部品牌'}，近 {p.get('days') or 30} 天，爆款分前 {len(items)} 条视频，合计播放 {sum(r['plays'] for r, _ in items):,}。"
    msg = await llm.chat([{"role": "system", "content": REPORT_PROMPT},
                          {"role": "user", "content": f"{head}\n\n【统计】\n{stat_text}\n\n【逐条拆解】\n{briefs}"}],
                         json_mode=True, task="report", timeout=180)
    insight = llm.parse_json(msg.get("content") or "")
    videos_out = [{**{k: r[k] for k in ("id", "url", "cover", "text", "plays", "likes", "comments", "shares", "engagement",
                                         "multiple", "boosted", "is_ad", "hot_score", "posted_at", "ref_ad_no")},
                   "account": r["account"], "analysis": a, "inputs": results[r["id"]][1]} for r, a in items]
    _set(rid, status="done", data={"summary": head, "insight": insight, "stats": stats, "videos": videos_out,
                                   "models": {"analysis": model, "report": settings_store.get_models()["report"]},
                                   "failed": len(rows) - len(items)})


def report_dict(r: Report, full: bool = True) -> dict:
    d = {"id": r.id, "params": r.params, "status": r.status, "progress": r.progress, "error": r.error,
         "created_at": r.created_at.isoformat(), "headline": (r.data or {}).get("insight", {}).get("headline", "")}
    if full:
        d["data"] = r.data
    return d
