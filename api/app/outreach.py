"""达人外联（二期，目前是演示）：写邀约邮件 → 「发送」→ 模拟达人回复报价 → 起草还价 → 签约 / 拒绝。
不会真的发邮件：发送和回复都只记在达人的 outreach 里，界面上标明「演示」。接入真实邮箱后，send / 收信换成真实实现即可。
"""
import random
import re
from datetime import datetime

from app import settings_store
from app.adapters import llm
from app.creators import PRODUCT_LINES
from app.db import SessionLocal
from app.models import Creator

STAGES = ["待联系", "已发送", "已回复", "报价中", "已签约", "已拒绝"]
SENDER = "TECNO Partnerships"
MARKET_EN = {"尼日利亚": "Nigeria", "巴基斯坦": "Pakistan", "肯尼亚": "Kenya", "加纳": "Ghana", "南非": "South Africa", "埃及": "Egypt",
             "孟加拉": "Bangladesh", "印尼": "Indonesia", "菲律宾": "Philippines"}
# 演示回复里的合作条款：（邮件里用的英文，界面上显示的中文）
TERMS = [("1 round of revisions, 30-day usage rights", "含 1 次修改，素材授权 30 天"),
         ("2 rounds of revisions, Spark Ads not included", "含 2 次修改，不含 Spark Ads 授权"),
         ("I need the phone 7 days before posting, 60-day usage rights", "需要提前 7 天拿到样机，素材授权 60 天")]

DRAFT_PROMPT = """You write a short, warm, specific first outreach email from {sender} to a TikTok creator, inviting a paid collaboration.
Mention one of their real videos by its topic, why their audience fits the product, the proposed format, and ask for their rate card.
No hype, under 140 words, plain text. Output JSON only: {{"subject": "...", "body": "..."}}"""


def _now() -> str:
    return datetime.utcnow().isoformat()


def _template(c: Creator, product: str, brief: str) -> dict:
    top = (c.videos or [{}])[0].get("text") or "your recent videos"
    top = re.sub(r"\s*#\S+", "", top).strip() or top
    body = (f"Hi {c.nickname or '@' + c.handle},\n\nI'm with the {product.split()[0]} team in {MARKET_EN.get(c.market, c.market)}. We loved your video \"{top[:70]}\" — "
            f"your audience is a great match for the new {product}.\n\n"
            f"We'd like to invite you to a paid collaboration: {brief or '1 TikTok video (30–60s) featuring the phone in your usual style'}.\n\n"
            "Could you share your rate card and availability for the next 2–4 weeks?\n\nBest regards,\n" + SENDER)
    return {"subject": f"Paid collab with {product} — @{c.handle}", "body": body}


async def draft(cid: str, product: str = "", brief: str = "") -> dict:
    with SessionLocal() as db:
        c = db.get(Creator, cid)
        if not c:
            raise ValueError("没有这个达人")
        product = product if product in PRODUCT_LINES else (c.best_product or "TECNO Spark")
        mail = _template(c, product, brief)
        if settings_store.llm_enabled() and not c.demo:
            try:
                vids = "; ".join((v.get("text") or "")[:80] for v in (c.videos or [])[:3])
                out = await llm.chat_json(DRAFT_PROMPT.format(sender=SENDER),
                                          f"Creator @{c.handle} ({c.nickname}), {c.followers} followers, market {c.market}, content: "
                                          f"{(c.analysis or {}).get('categories')}, audience: {(c.analysis or {}).get('audience')}. Recent videos: {vids}. "
                                          f"Product: {product} ({PRODUCT_LINES[product]}). Proposed format: {brief or '1 TikTok video, 30–60s'}.",
                                          task="script", timeout=60)
                if out.get("subject") and out.get("body"):
                    mail = {"subject": str(out["subject"])[:200], "body": str(out["body"])[:3000]}
            except Exception:  # noqa: BLE001  模型失败用模板
                pass
        o = dict(c.outreach or {})
        o.update(stage=o.get("stage") or "待联系", product=product, brief=brief, draft=mail, to=c.email or "")
        c.outreach = o
        db.commit()
        return o


def send(cid: str, subject: str, body: str) -> dict:
    """演示：不真的发出，只记一条发件记录。"""
    with SessionLocal() as db:
        c = db.get(Creator, cid)
        o = dict(c.outreach or {})
        o.setdefault("thread", [])
        o["thread"] = [*o["thread"], {"dir": "out", "subject": subject, "body": body, "to": c.email or f"@{c.handle} 的私信", "at": _now(), "demo": True}]
        o.update(stage="已发送", draft=None, sent_at=_now())
        c.outreach = o
        db.commit()
        return o


def simulate_reply(cid: str) -> dict:
    """演示：模拟达人回信报价（通常比预估高 10–60%），并起草一封在预估区间内的还价。"""
    with SessionLocal() as db:
        c = db.get(Creator, cid)
        o = dict(c.outreach or {})
        rnd = random.Random(c.id + str(len(o.get("thread") or [])))
        p = c.price or {"low": 100, "high": 200, "currency": "USD"}
        mid = (p["low"] + p["high"]) / 2 or 100  # 预估是单条视频的价
        n = rnd.choice([1, 1, 2, 3])
        per = max(10, int(round(mid * rnd.uniform(1.1, 1.6), -1)))  # 达人开价一般比预估高
        ask = per * n
        en, zh = rnd.choice(TERMS)
        reply = (f"Hi team,\n\nThanks for reaching out! I'd love to work with {(o.get('product') or 'TECNO').split()[0]}. "
                 f"My rate is ${ask} for {n} TikTok video{'s' if n > 1 else ''} ({en}). I can post within 2 weeks of receiving the phone.\n\n"
                 f"Best,\n{c.nickname or c.handle}")
        target = max(10, int(round(min(per, p["high"]) * 0.9, -1))) * n  # 还价：每条压到预估上限的 9 成以内
        counter = (f"Hi {c.nickname or c.handle},\n\nThanks for the quick reply. Our budget for this campaign is ${target} for {n} video"
                   f"{'s' if n > 1 else ''}, including the phone, which you keep. If that works for you, we'll send the brief and the device this week.\n\n"
                   f"Best regards,\n{SENDER}")
        o["thread"] = [*(o.get("thread") or []), {"dir": "in", "subject": "Re: " + ((o.get("thread") or [{}])[-1].get("subject") or "collab"),
                                                   "body": reply, "at": _now(), "demo": True}]
        o.update(stage="报价中", quote={"amount": ask, "currency": "USD", "videos": n, "terms": zh, "per_video": per,
                                     "vs_estimate": round(per / mid, 2), "demo": True},
                 counter={"amount": target, "body": counter, "within_budget": target / n <= p["high"]})
        c.outreach = o
        db.commit()
        return o


def set_stage(cid: str, stage: str, note: str = "") -> dict:
    if stage not in STAGES:
        raise ValueError("阶段不对")
    with SessionLocal() as db:
        c = db.get(Creator, cid)
        o = dict(c.outreach or {})
        o["stage"] = stage
        if note:
            o["thread"] = [*(o.get("thread") or []), {"dir": "note", "body": note, "at": _now()}]
        c.outreach = o
        db.commit()
        return o
