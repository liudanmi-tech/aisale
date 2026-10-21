"""剧本库：结合本地热点生成原创爆款剧本、40 人评测、用到画布。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import scriptlab, settings_store
from app.creators import PRODUCT_LINES
from app.db import get_db
from app.events import spawn
from app.models import LibScript

router = APIRouter(prefix="/api/v1/scripts")


@router.get("")
def list_scripts(market: str = "", concepts: bool = False, db: Session = Depends(get_db)):
    q = db.query(LibScript)
    if market:
        q = q.filter(LibScript.market == market)
    if not concepts:
        q = q.filter(LibScript.status != "concept")
    items = [scriptlab.script_dict(s) for s in q.order_by(LibScript.created_at.desc()).limit(200)]
    return {"items": items, "llm": settings_store.llm_enabled(), "products": list(PRODUCT_LINES), "selling_points": scriptlab.SELLING_POINTS,
            "formats": scriptlab.FORMATS, "audiences": scriptlab.AUDIENCES}


@router.get("/trends")
def trends(market: str = "尼日利亚"):
    return scriptlab.trends(market)


class GenIn(BaseModel):
    market: str = "尼日利亚"
    product: str = "TECNO Pova"
    selling_point: str = "打游戏不卡"
    audience: str = "学生"
    formats: list[str] = []
    trends: list[str] = []
    brief: str = ""
    specs: str = ""  # 已知参数（IP 等级、电池容量……），剧本只能用这些
    count: int = 3


@router.post("/generate")
def generate(body: GenIn):
    if not settings_store.llm_enabled():
        raise HTTPException(400, "剧本库需要大模型：到「设置」里填 OpenRouter Key")
    jid = scriptlab.start_job(body.model_dump())
    spawn(scriptlab.generate(jid))
    return scriptlab._jobs[jid]


@router.get("/jobs/{jid}")
def job(jid: str):
    j = scriptlab._jobs.get(jid)
    if not j:
        raise HTTPException(404, "任务不存在（后端重启过）")
    return j


def _get(db: Session, sid: str) -> LibScript:
    s = db.get(LibScript, sid)
    if not s:
        raise HTTPException(404, "没有这个剧本")
    return s


@router.get("/{sid}")
def get_script(sid: str, db: Session = Depends(get_db)):
    return scriptlab.script_dict(_get(db, sid))


@router.delete("/{sid}")
def delete_script(sid: str, db: Session = Depends(get_db)):
    db.delete(_get(db, sid))
    db.commit()
    return {"ok": True}


class WriteIn(BaseModel):
    comment: str = ""


@router.post("/{sid}/write")
def write(sid: str, body: WriteIn, db: Session = Depends(get_db)):
    """备选创意写成剧本；已经写好的按意见改写。"""
    s = _get(db, sid)
    if s.status in ("writing", "evaluating"):
        raise HTTPException(409, "正在处理，稍后再试")
    if s.shots and not body.comment.strip():
        raise HTTPException(400, "写一句修改意见")
    if not settings_store.llm_enabled():
        raise HTTPException(400, "需要大模型：到「设置」里填 OpenRouter Key")
    s.status = "writing"
    db.commit()
    spawn(scriptlab._write_one(sid, (s.critic or {}).get("improve", ""), body.comment.strip()))
    return {"ok": True}


@router.post("/{sid}/evaluate")
def evaluate(sid: str, db: Session = Depends(get_db)):
    s = _get(db, sid)
    if not s.shots:
        raise HTTPException(400, "先写成剧本再评测")
    if s.status in ("writing", "evaluating"):
        raise HTTPException(409, "正在处理，稍后再试")
    if not settings_store.llm_enabled():
        raise HTTPException(400, "评测需要大模型：到「设置」里填 OpenRouter Key")
    s.status = "evaluating"
    db.commit()
    spawn(scriptlab.evaluate(sid))
    return {"ok": True}


class UseIn(BaseModel):
    project_id: str


@router.post("/{sid}/use")
def use(sid: str, body: UseIn):
    try:
        return {"node_id": scriptlab.to_canvas(sid, body.project_id)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
