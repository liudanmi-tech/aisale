"""达人雷达：找达人、看评估、外联（外联目前是演示）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import creators, outreach, settings_store
from app.db import get_db
from app.events import spawn
from app.models import Creator
from app.routers.monitor import _parse_handle

router = APIRouter(prefix="/api/v1/creators")


@router.get("")
def list_creators(market: str = "", tier: str = "", product: str = "", stage: str = "", db: Session = Depends(get_db)):
    q = db.query(Creator)
    if market:
        q = q.filter(Creator.market == market)
    if tier:
        q = q.filter(Creator.tier == tier)
    items = [creators.creator_dict(c) for c in q.order_by(Creator.fit_score.desc())]
    if product:
        items = [x for x in items if x["best_product"] == product]
    if stage:
        items = [x for x in items if x["stage"] == stage]
    return {"items": items, "ready": bool(settings_store.get_secret("apify")), "llm": settings_store.llm_enabled(),
            "tiers": [n for _, n in creators.TIERS], "products": list(creators.PRODUCT_LINES), "stages": outreach.STAGES,
            "settings": creators.get_settings()}


@router.get("/{cid}")
def get_creator(cid: str, db: Session = Depends(get_db)):
    c = db.get(Creator, cid)
    if not c:
        raise HTTPException(404, "没有这个达人")
    if creators.show_videos(c)[1]:  # 还没缓存的封面后台补下载，下次打开就是本地的
        spawn(creators.cache_covers(cid))
    return creators.creator_dict(c, full=True)


@router.delete("/{cid}")
def delete_creator(cid: str, db: Session = Depends(get_db)):
    c = db.get(Creator, cid)
    if c:
        db.delete(c)
        db.commit()
    return {"ok": True}


class DiscoverIn(BaseModel):
    market: str = "尼日利亚"
    keywords: list[str] | None = None  # 不传用设置里这个市场的默认关键词
    from_competitors: bool = True
    limit: int = 15


def _need_apify():
    if not settings_store.get_secret("apify"):
        raise HTTPException(400, "还没填 Apify Token：到「设置」里填上才能抓真实达人数据；也可以先点「载入演示数据」看看效果")


@router.post("/discover")
def discover(body: DiscoverIn):
    _need_apify()
    kws = [k.strip() for k in (body.keywords if body.keywords is not None else creators.get_settings()["keywords"].get(body.market, [])) if k.strip()]
    if not kws and not body.from_competitors:
        raise HTTPException(400, "至少填一个关键词，或者勾上「从竞品合作里找」")
    jid = creators.start_job("discover", body.market)
    spawn(creators.discover(jid, body.market, kws[:8], body.from_competitors, max(1, min(40, body.limit))))
    return creators._jobs[jid]


class AddIn(BaseModel):
    handles: str
    market: str = "尼日利亚"


@router.post("/add")
def add(body: AddIn):
    _need_apify()
    hs = [h for h in (_parse_handle(x) for x in body.handles.replace(",", " ").replace("，", " ").split()) if h][:20]
    if not hs:
        raise HTTPException(400, "请填写达人账号或主页链接")
    jid = creators.start_job("add", body.market)
    spawn(creators.add_manual(jid, body.market, hs))
    return creators._jobs[jid]


@router.get("/jobs/{jid}")
def job(jid: str):
    j = creators._jobs.get(jid)
    if not j:
        raise HTTPException(404, "任务不存在（后端重启过）")
    return j


@router.post("/demo")
def demo(market: str = "尼日利亚"):
    return {"added": creators.load_demo(market)}


@router.post("/{cid}/analyze")
def analyze(cid: str, db: Session = Depends(get_db)):
    c = db.get(Creator, cid)
    if not c:
        raise HTTPException(404, "没有这个达人")
    if not c.demo:
        _need_apify()
    spawn(creators.reanalyze(cid))
    return {"ok": True}


class SettingsIn(BaseModel):
    cpm: dict[str, float] | None = None
    keywords: dict[str, list[str]] | None = None


@router.put("/settings")
def put_settings(body: SettingsIn):
    return creators.set_settings(body.model_dump(exclude_none=True))


# ---------- 外联（演示） ----------

class DraftIn(BaseModel):
    product: str = ""
    brief: str = ""


@router.post("/{cid}/outreach/draft")
async def outreach_draft(cid: str, body: DraftIn):
    try:
        return await outreach.draft(cid, body.product, body.brief)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None


class SendIn(BaseModel):
    subject: str
    body: str


@router.post("/{cid}/outreach/send")
def outreach_send(cid: str, body: SendIn):
    if not body.subject.strip() or not body.body.strip():
        raise HTTPException(400, "标题和正文不能为空")
    return outreach.send(cid, body.subject.strip(), body.body.strip())


@router.post("/{cid}/outreach/reply")
def outreach_reply(cid: str, db: Session = Depends(get_db)):
    c = db.get(Creator, cid)
    if not c or (c.outreach or {}).get("stage") not in ("已发送", "已回复", "报价中"):
        raise HTTPException(400, "先发出邀约邮件，才能模拟回复")
    return outreach.simulate_reply(cid)


class StageIn(BaseModel):
    stage: str
    note: str = ""


@router.post("/{cid}/outreach/stage")
def outreach_stage(cid: str, body: StageIn):
    try:
        return outreach.set_stage(cid, body.stage, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
