"""本地热梗雷达：当地人这两周在玩的梗、俚语、热门 BGM / 挑战、流行文化（球赛、明星、剧），给剧本库借势用。

三个来源，各自独立（一个失败不影响其他），结果缓存在设置表里，手动「刷新」：
1. Google Trends 当地每日热搜（RSS，免费、实时）
2. 大模型联网搜索（OpenRouter web 插件）：最近两周的梗、俚语、TikTok 挑战、榜单歌曲、流行文化，带来源网页
3. 竞品雷达 / 达人雷达抓到的本地视频：达人视频的话题标签和 BGM（竞品官方号的标签单列为「竞品在推的活动」，不当热梗）
最后让模型把这些材料整理成「梗卡片」：是什么、怎么用进手机广告、当地怎么说、热度、来源、风险。
只整理材料里有的，不许编；政治、宗教、灾难、暴力相关的标成不建议用。
"""
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from app import settings_store
from app.adapters import llm
from app.db import SessionLocal
from app.models import Setting

log = logging.getLogger(__name__)
GEO = {"尼日利亚": "NG", "巴基斯坦": "PK", "肯尼亚": "KE", "加纳": "GH", "南非": "ZA", "埃及": "EG", "孟加拉": "BD", "印尼": "ID", "菲律宾": "PH"}
COUNTRY = {"尼日利亚": "Nigeria", "巴基斯坦": "Pakistan", "肯尼亚": "Kenya", "加纳": "Ghana", "南非": "South Africa", "埃及": "Egypt",
           "孟加拉": "Bangladesh", "印尼": "Indonesia", "菲律宾": "Philippines"}
KINDS = ["梗", "俚语 / 口头禅", "BGM / 歌", "挑战 / 玩法", "球赛 / 体育", "明星 / 网红", "剧 / 影视", "节日 / 活动", "社会话题"]
transport: httpx.AsyncBaseTransport | None = None  # 测试时注入（Google Trends）
_running: set[str] = set()


def _key(market: str) -> str:
    return f"memes:{market}"


def get(market: str) -> dict:
    with SessionLocal() as db:
        s = db.get(Setting, _key(market))
        v = dict((s.value if s else {}) or {})
    v["refreshing"] = market in _running
    v.setdefault("items", [])
    return v


def _save(market: str, value: dict) -> None:
    with SessionLocal() as db:
        s = db.get(Setting, _key(market)) or Setting(key=_key(market), value={})
        s.value = value
        db.merge(s)
        db.commit()


async def google_trends(market: str) -> list[dict]:
    geo = GEO.get(market)
    if not geo:
        return []
    async with httpx.AsyncClient(timeout=20, transport=transport, follow_redirects=True) as c:
        r = await c.get("https://trends.google.com/trending/rss", params={"geo": geo})
        r.raise_for_status()
    ns = {"ht": "https://trends.google.com/trending/rss"}
    out = []
    for it in ET.fromstring(r.text).iter("item"):
        news = [{"title": (n.findtext("ht:news_item_title", "", ns) or "").strip(), "url": n.findtext("ht:news_item_url", "", ns) or "",
                 "source": n.findtext("ht:news_item_source", "", ns) or ""} for n in it.findall("ht:news_item", ns)][:2]
        out.append({"title": (it.findtext("title") or "").strip(), "traffic": it.findtext("ht:approx_traffic", "", ns) or "",
                    "at": it.findtext("pubDate") or "", "news": news})
    return [x for x in out if x["title"]][:25]


WEB_PROMPTS = [
    # 梗、俚语、段子：TikTok / X 上的说法和玩法
    """Today is {today}. Search the web (TikTok, X/Twitter, Instagram, Nairaland, local entertainment blogs) for what people in {country} are joking about
RIGHT NOW (the past 14 days): viral memes and meme formats, new slang and catchphrases (quote them exactly as locals say them, e.g. Pidgin),
comedy skit trends, viral moments from influencers and comedians, and everyday frustrations people are laughing about (prices, power, traffic, school).
Give 12–15 concrete items. For each: the exact phrase or name as locals say it, what it means / what happened, how people use it in videos,
the approximate date, and the source URL. Skip anything you cannot find a source for. Skip politics.""",
    # 流行文化：歌、挑战、球赛、明星、剧
    """Today is {today}. Search the web for the pop culture people in {country} are into RIGHT NOW (the past 14 days): the most used TikTok sounds
and dance / transition challenges, chart-topping local songs, football and sports moments people are posting about, celebrity / Nollywood /
reality-TV moments, and upcoming festivals or seasonal events. Give 10–12 concrete items with what it is, why it's hot now, the approximate date
and the source URL. Skip anything you cannot find a source for.""",
]

DISTILL_PROMPT = """你是传音在{market}的本地内容策划，要从下面的材料里整理出「本地热梗卡片」，给手机广告的整活剧本借势用。
只能整理材料里出现过的东西，不许自己编；看不出来的字段写空字符串。只输出 JSON：
{{"items": [{{"name": "梗 / 热点的名字，用当地原话", "kind": "从这些里选：{kinds}", "what": "是什么、为什么最近火（中文一句话）",
"how": "怎么用进手机广告的整活剧本（中文一句话，具体到情节或台词）", "say": "当地人会怎么说（原文，一句）", "heat": 1-5 热度,
"date": "大概日期", "sources": [引用的来源编号], "risk": "政治 / 宗教 / 灾难 / 暴力 / 争议明星等风险，没有写空字符串", "use": true/false 品牌能不能安全地用}}]}}
规则：
- 要的是「梗」和「流行文化」：俚语、段子玩法、热门 BGM / 挑战、球赛、明星、剧、节日。金融、政策、公司新闻、国际比赛的普通赛事预告不是梗，不要
- BGM / 歌最多 5 条，挑 TikTok 上被拿来做段子 / 转场用得最多的
- how 要写成一个整活桥段的点子，并和一个手机卖点挂钩（续航省电、打游戏不卡、防水、拍照、外放音量、快充、耐摔），
  比如「Sapa 月底没钱只能蹭邻居 Wi-Fi，结果 Pova 一晚上都没断电」；不要写「展示用户用手机看 / 分享 X」这种空话
- 梗本身好笑但出自政治事件、争议明星、灾难的，risk 写清楚，use=false
- 材料里能看出是 60 天以前的，heat 最多 2，date 写上
- 最多 20 条，按适合拿来做广告的程度排序；同一件事只写一条"""


async def web_scan(market: str) -> tuple[str, list[dict]]:
    """两次联网搜索（梗和俚语 / 流行文化）并发跑；一次失败只用另一次。"""
    today, country = datetime.utcnow().strftime("%Y-%m-%d"), COUNTRY.get(market, market)
    got = await asyncio.gather(*(llm.chat([{"role": "user", "content": p.format(today=today, country=country)}], task="analysis", timeout=150, web=10)
                                 for p in WEB_PROMPTS), return_exceptions=True)
    ok = [m for m in got if isinstance(m, dict)]
    if not ok:
        raise got[0]
    srcs, texts = [], []
    for msg in ok:
        texts.append(str(msg.get("content") or ""))
        for a in msg.get("annotations") or []:
            u = (a or {}).get("url_citation") or {}
            if u.get("url") and u["url"] not in {s["url"] for s in srcs}:
                srcs.append({"url": u["url"], "title": u.get("title") or u["url"]})
    return "\n\n".join(texts), srcs


async def refresh(market: str) -> None:
    if market in _running:
        return
    _running.add(market)
    errors, gt, web_text, srcs = [], [], "", []
    try:
        try:
            gt = await google_trends(market)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Google Trends 没拉到：{str(e)[:100]}")
        if settings_store.llm_enabled():
            try:
                web_text, srcs = await web_scan(market)
            except Exception as e:  # noqa: BLE001
                errors.append(f"联网搜索失败：{str(e)[:120]}")
        else:
            errors.append("没有配置大模型：没法联网搜热梗，也没法整理成梗卡片（只显示 Google 热搜）")
        from app.scriptlab import trends as radar
        rd = radar(market, days=14)
        items = []
        if settings_store.llm_enabled() and (gt or web_text or rd["tags"]):
            src_list = "\n".join(f"[{k + 1}] {s['title']} {s['url']}" for k, s in enumerate(srcs))
            gt_text = "\n".join(f"- {g['title']}（{g['traffic']} 次搜索）" + "".join(f"；新闻：{n['title']}" for n in g["news"][:1]) for g in gt)
            rd_text = "\n".join(f"- #{t['tag']}（{t['videos']} 条视频，{t['plays']:,} 播放）{t['sample'][:60]}" for t in rd["tags"][:15]) + \
                "\n".join(f"- BGM：{m['music']}（{m['videos']} 条）" for m in rd["music"][:6])
            user = (f"【联网搜索结果】\n{web_text or '（没有）'}\n来源：\n{src_list or '（没有）'}\n\n【Google 当地热搜】\n{gt_text or '（没有）'}\n\n"
                    f"【我们抓到的本地达人视频里的话题和 BGM（最近 14 天）】\n{rd_text or '（没有）'}")
            try:
                out = await llm.chat_json(DISTILL_PROMPT.format(market=market, kinds="、".join(KINDS)), user, task="analysis", timeout=120)
                for it in out.get("items") or []:
                    if not isinstance(it, dict) or not it.get("name"):
                        continue
                    idx = [int(x) - 1 for x in it.get("sources") or [] if str(x).isdigit() and 0 < int(x) <= len(srcs)]
                    items.append({"name": str(it["name"])[:60], "kind": it.get("kind") if it.get("kind") in KINDS else "梗",
                                  "what": str(it.get("what") or "")[:160], "how": str(it.get("how") or "")[:160], "say": str(it.get("say") or "")[:100],
                                  "heat": max(1, min(5, int(it.get("heat") or 3))) if str(it.get("heat") or "3").isdigit() else 3,
                                  "date": str(it.get("date") or "")[:30], "sources": [srcs[i] for i in idx][:3],
                                  "risk": str(it.get("risk") or "")[:100], "use": bool(it.get("use", True)) and not it.get("risk")})
            except Exception as e:  # noqa: BLE001
                errors.append(f"整理梗卡片失败：{str(e)[:120]}")
        old = get(market)
        _save(market, {"items": items or old.get("items") or [], "google": gt or old.get("google") or [], "sources": srcs,
                       "campaign_tags": rd.get("campaign_tags", [])[:12], "updated": datetime.utcnow().isoformat() if (items or gt) else old.get("updated"),
                       "errors": errors, "model": settings_store.get_models()["analysis"]})
    finally:
        _running.discard(market)


def as_trend(item: dict) -> str:
    """选中的梗卡片 → 写给编剧模型的一条热点说明。"""
    return f"{item['name']}（{item.get('kind')}：{item.get('what')}" + (f"；当地说法：{item['say']}" if item.get("say") else "") + \
        (f"；可以这样用：{item['how']}" if item.get("how") else "") + "）"


async def refresh_all(markets: list[str]) -> None:
    for m in markets:
        await refresh(m)
        await asyncio.sleep(1)
