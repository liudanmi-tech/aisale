"""TikTok 账号监控：维护监控账号、触发同步、查看打分后的视频、加入爆款库。"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import canvas, monitor, settings_store
from app.db import get_db
from app.events import spawn
from app.models import SourceVideo, VideoSnapshot, WatchAccount, new_id
from app.routers.ops import ad_dict

router = APIRouter(prefix="/api/v1/watch")
log = logging.getLogger(__name__)


def acc_dict(a: WatchAccount, n_videos: int = 0) -> dict:
    return {"id": a.id, "platform": a.platform, "handle": a.handle, "brand": a.brand, "market": a.market, "kind": a.kind,
            "enabled": a.enabled, "nickname": a.nickname, "followers": a.followers, "verified": a.verified,
            "status": "syncing" if a.id in monitor._running else a.status, "error": a.error,
            "last_synced": a.last_synced.isoformat() if a.last_synced else None, "videos": n_videos}


@router.get("/accounts")
def accounts(db: Session = Depends(get_db)):
    counts: dict[str, int] = {}
    for (aid,) in db.query(SourceVideo.account_id):
        counts[aid] = counts.get(aid, 0) + 1
    return {"ready": bool(settings_store.get_secret("apify")),
            "items": [acc_dict(a, counts.get(a.id, 0)) for a in db.query(WatchAccount).order_by(WatchAccount.created_at)]}


class AccountIn(BaseModel):
    handles: str  # 一个或多个，空格 / 逗号 / 换行分隔，可带 @ 或主页链接
    brand: str = ""
    market: str = "尼日利亚"
    kind: str = "竞品官方"


def _parse_handle(s: str) -> str:
    s = s.strip().rstrip("/")
    if "tiktok.com/" in s:
        s = s.split("tiktok.com/", 1)[1].split("?")[0].split("/")[0]
    return s.lstrip("@").strip()


@router.post("/accounts")
def add_accounts(body: AccountIn, db: Session = Depends(get_db)):
    raw = body.handles.replace(",", " ").replace("，", " ").split()
    handles = [h for h in (_parse_handle(x) for x in raw) if h]
    if not handles:
        raise HTTPException(400, "请填写账号")
    bad = [h for h in handles if not all(c.isalnum() or c in "._" for c in h) or len(h) > 24]
    if bad:
        raise HTTPException(400, f"账号格式不正确：{', '.join(bad)}")
    existing = {a.handle.lower() for a in db.query(WatchAccount)}
    added = []
    for h in handles:
        if h.lower() in existing:
            continue
        existing.add(h.lower())
        a = WatchAccount(id=new_id("wa"), handle=h, brand=body.brand.strip(), market=body.market, kind=body.kind)
        db.add(a)
        added.append(a)
    canvas.audit(db, "-", "user", "watch_add", {"handles": [a.handle for a in added]})
    db.commit()
    return {"added": len(added), "skipped": len(handles) - len(added)}


class AccountPatch(BaseModel):
    brand: str | None = None
    market: str | None = None
    kind: str | None = None
    enabled: bool | None = None


@router.patch("/accounts/{aid}")
def patch_account(aid: str, body: AccountPatch, db: Session = Depends(get_db)):
    a = db.get(WatchAccount, aid)
    if not a:
        raise HTTPException(404, "not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(a, k, v)
    db.commit()
    return acc_dict(a)


@router.delete("/accounts/{aid}")
def delete_account(aid: str, db: Session = Depends(get_db)):
    a = db.get(WatchAccount, aid)
    if not a:
        raise HTTPException(404, "not found")
    vids = [v.id for v in db.query(SourceVideo).filter(SourceVideo.account_id == aid)]
    if vids:
        db.query(VideoSnapshot).filter(VideoSnapshot.video_id.in_(vids)).delete(synchronize_session=False)
        db.query(SourceVideo).filter(SourceVideo.account_id == aid).delete(synchronize_session=False)
    db.delete(a)
    canvas.audit(db, "-", "user", "watch_delete", {"handle": a.handle})
    db.commit()
    return {"ok": True}


class SyncIn(BaseModel):
    account_ids: list[str] | None = None


@router.post("/sync")
def sync(body: SyncIn):
    """后台同步，立即返回；前端轮询账号状态。"""
    if not settings_store.get_secret("apify"):
        raise HTTPException(400, "还没有填写 Apify Token，请到设置页添加")

    async def run():
        try:
            await monitor.sync(body.account_ids)
        except Exception:  # noqa: BLE001
            log.exception("同步失败")

    spawn(run())
    return {"ok": True}


class SearchIn(BaseModel):
    queries: list[str]


@router.post("/search")
def search(body: SearchIn):
    """在 TikTok 上按关键词找账号（后台运行，约 1–3 分钟），返回任务号供轮询。"""
    if not settings_store.get_secret("apify"):
        raise HTTPException(400, "还没有填写 Apify Token，请到设置页添加")
    qs = [q.strip() for q in body.queries if q.strip()][:20]
    if not qs:
        raise HTTPException(400, "请填写搜索词")
    job_id = monitor.start_search(qs)
    spawn(monitor.search_accounts(job_id, qs))
    return {"job_id": job_id}


@router.get("/search/{job_id}")
def search_result(job_id: str):
    job = monitor._searches.get(job_id)
    if not job:
        raise HTTPException(404, "not found")
    return job


@router.get("/videos")
def videos(market: str | None = None, brand: str | None = None, grade: str | None = None, sort: str = "hot_score",
           db: Session = Depends(get_db)):
    rows = monitor.scored_videos(db)
    if market:
        rows = [r for r in rows if r["account"]["market"] == market]
    if brand:
        rows = [r for r in rows if r["account"]["brand"] == brand]
    if grade:
        rows = [r for r in rows if r["grade"] == grade]
    key = sort if sort in ("hot_score", "quality_score", "plays", "multiple", "engagement", "posted_at") else "hot_score"
    return sorted(rows, key=lambda r: r.get(key) or 0, reverse=True)


@router.post("/videos/{vid}/promote")
def promote(vid: str, db: Session = Depends(get_db)):
    try:
        ad = monitor.promote(db, vid)
    except KeyError:
        raise HTTPException(404, "not found") from None
    canvas.audit(db, "-", "user", "watch_promote", {"video": vid, "ref_ad_no": ad.no})
    db.commit()
    return ad_dict(ad)
