"""素材库接口：演员 / 场景 / 商品的增删改、上传图片、AI 生成图片；画布上的素材节点换素材。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import agent, assets, canvas, catalog, product, production, settings_store
from app.db import SessionLocal, get_db
from app.events import emit, spawn
from app.models import Asset, Node, Project

router = APIRouter(prefix="/api/v1")


def _uses(db: Session) -> dict[str, int]:
    out: dict[str, int] = {}
    for n in db.query(Node).filter(Node.type.in_(["actor", "scene", "product"])):
        aid = (n.data or {}).get("asset_id")
        if aid:
            out[aid] = out.get(aid, 0) + 1
    return out


@router.get("/library/catalog")
def catalog_list():
    """传音机型库（TECNO / Infinix / itel 近两年发布的手机），标出哪些已经导入。"""
    return catalog.listing()


class CatalogImportIn(BaseModel):
    ids: list[str]


@router.post("/library/catalog/import")
def catalog_import(body: CatalogImportIn):
    """导入选中的机型：建商品，后台下载官方渲染图、裁成单台、检查抠图、提取说明卡。"""
    if not body.ids:
        raise HTTPException(400, "没有选机型")
    res = catalog.start(body.ids[:60])
    for r in res:
        if r["created"]:
            spawn(catalog.run_import(r["asset_id"], r["catalog_id"]))
    return {"items": res, "created": sum(r["created"] for r in res)}


@router.get("/library")
def library(kind: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Asset)
    if kind:
        q = q.filter(Asset.kind == kind)
    uses = _uses(db)
    return [{**assets.asset_dict(a), "uses": uses.get(a.id, 0)} for a in q.order_by(Asset.created_at.desc())]


class AssetIn(BaseModel):
    kind: str
    name: str
    description: str = ""
    data: dict = {}
    tags: list[str] = []
    image: str | None = None  # data URI，上传图片
    generate: bool = False  # 演员 / 场景：AI 生成图片
    consent: bool = False  # 演员上传真人照片：确认已取得本人肖像授权
    view: str | None = None  # 商品图的视角（front / back / side / angle / detail / front_on），不填由模型判断


CONSENT_TEXT = "我确认已取得照片中本人的书面授权，同意其肖像用于 AI 生成广告并在 TikTok 等平台投放"


def _check_consent(kind: str, consent: bool) -> dict:
    """演员上传真人照片必须确认肖像授权；记下确认时间和条款，备查。"""
    if kind != "actor":
        return {}
    if not consent:
        raise HTTPException(400, "上传真人照片前，请确认已取得本人的肖像授权")
    return {"consent": {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "text": CONSENT_TEXT}}


@router.post("/library")
def create_asset(body: AssetIn):
    if body.kind not in assets.KINDS:
        raise HTTPException(400, "kind 只能是 actor / scene / product")
    if not body.name.strip():
        raise HTTPException(400, "请填写名称")
    extra = _check_consent(body.kind, body.consent) if body.image else {}
    a = assets.create(body.kind, body.name, body.description, data={**body.data, **extra}, tags=body.tags)
    if body.image:
        try:
            a = assets.add_upload(a.id, body.image)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        if a.kind == "actor" and settings_store.llm_enabled():
            spawn(assets.generate_turnaround(a.id))
        if a.kind == "product":
            spawn(product.process_upload(a.id, a.images[0], body.view))
    elif body.generate and body.kind != "product":
        if not settings_store.llm_enabled():
            raise HTTPException(400, "AI 生成图片需要 OpenRouter Key")
        spawn(assets.generate_image(a.id))
    return assets.asset_dict(a)


class AssetPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    data: dict | None = None
    tags: list[str] | None = None


@router.patch("/library/{aid}")
def patch_asset(aid: str, body: AssetPatch, db: Session = Depends(get_db)):
    a = db.get(Asset, aid)
    if not a:
        raise HTTPException(404, "not found")
    for k, v in body.model_dump(exclude_none=True).items():
        if k == "data" and "spec_card" in v:  # 人改过说明卡，之后上传新图不再自动覆盖
            v = {**v, "spec_card": {f: str(t)[:200] for f, t in (v["spec_card"] or {}).items() if f in product.SPEC_FIELDS}, "spec_card_edited": True}
        setattr(a, k, {**(a.data or {}), **v} if k == "data" else v)
    db.commit()
    return assets.asset_dict(a)


class ViewIn(BaseModel):
    url: str
    view: str


@router.post("/library/{aid}/view")
def set_view(aid: str, body: ViewIn, db: Session = Depends(get_db)):
    """改商品图的视角标注（模型判断错了时）。"""
    a = db.get(Asset, aid)
    if not a or body.url not in (a.images or []):
        raise HTTPException(404, "not found")
    if body.view not in product.VIEWS:
        raise HTTPException(400, "视角不对")
    views = dict((a.data or {}).get("views") or {})
    views[body.url] = {**views.get(body.url, {}), "view": body.view}
    a.data = {**(a.data or {}), "views": views}
    db.commit()
    return assets.asset_dict(a)


class ImageIn(BaseModel):
    url: str


@router.post("/library/{aid}/remove-image")
def remove_image(aid: str, body: ImageIn, db: Session = Depends(get_db)):
    """删掉素材里的一张图（比如拼图、旧款图）。"""
    a = db.get(Asset, aid)
    if not a or body.url not in (a.images or []):
        raise HTTPException(404, "not found")
    a.images = [u for u in a.images if u != body.url]
    views = {u: v for u, v in ((a.data or {}).get("views") or {}).items() if u != body.url}
    a.data = {**(a.data or {}), "views": views}
    db.commit()
    return assets.asset_dict(a)


class UploadIn(BaseModel):
    image: str  # data URI
    consent: bool = False
    view: str | None = None  # 商品图视角


@router.post("/library/{aid}/upload")
def upload(aid: str, body: UploadIn, db: Session = Depends(get_db)):
    a = db.get(Asset, aid)
    if not a:
        raise HTTPException(404, "not found")
    extra = _check_consent(a.kind, body.consent)
    if extra:
        a.data = {**(a.data or {}), **extra}
        db.commit()
    try:
        a = assets.add_upload(aid, body.image)
    except KeyError:
        raise HTTPException(404, "not found") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    resumed = production.resume_waiting(aid)
    for vid in resumed:
        v = db.get(Node, vid)
        if v:
            agent.say(db, v.project_id, f"收到「{a.name}」的图片，{agent.ref(v)} 继续生成。")
            emit(v.project_id, "chat")
    db.commit()
    for vid in resumed:
        spawn(production.run(vid))
    if a.kind == "actor" and settings_store.llm_enabled():
        spawn(assets.generate_turnaround(aid))  # 换了定妆照，三视图跟着重画
    if a.kind == "product":
        spawn(product.process_upload(aid, a.images[0], body.view))
    _touch(db, aid)
    return {**assets.asset_dict(a), "resumed": resumed}


@router.post("/library/{aid}/generate")
def generate(aid: str, db: Session = Depends(get_db)):
    a = db.get(Asset, aid)
    if not a:
        raise HTTPException(404, "not found")
    if a.kind == "product":
        raise HTTPException(400, "商品图需要上传实拍图，不能 AI 生成")
    if not settings_store.llm_enabled():
        raise HTTPException(400, "AI 生成图片需要 OpenRouter Key")

    async def run():
        await assets.generate_image(aid)
        with SessionLocal() as s:
            _touch(s, aid)

    spawn(run())
    a.status = "generating"
    db.commit()
    _touch(db, aid)
    return {"ok": True}


@router.delete("/library/{aid}")
def delete_asset(aid: str, db: Session = Depends(get_db)):
    a = db.get(Asset, aid)
    if not a:
        raise HTTPException(404, "not found")
    if _uses(db).get(aid):
        raise HTTPException(409, "画布上还在用这个素材，先在画布上换掉再删除")
    db.delete(a)
    db.commit()
    return {"ok": True}


def _touch(db: Session, aid: str) -> None:
    """素材变了：刷新用到它的画布。"""
    for pid in {n.project_id for n in db.query(Node).filter(Node.type.in_(["actor", "scene", "product"])) if (n.data or {}).get("asset_id") == aid}:
        emit(pid, "canvas")


class SwapIn(BaseModel):
    asset_id: str


@router.post("/nodes/{nid}/asset")
def swap_asset(nid: str, body: SwapIn, db: Session = Depends(get_db)):
    """画布上的演员 / 场景 / 商品节点换成素材库里的另一个；本项目剧本的选角同步替换。视频需要重新生成才会用上。"""
    n, a = db.get(Node, nid), db.get(Asset, body.asset_id)
    if not n or n.type not in ("actor", "scene", "product"):
        raise HTTPException(404, "node not found")
    if not a or a.kind != n.type:
        raise HTTPException(400, "只能换成同类型的素材")
    old = (n.data or {}).get("asset_id")
    n.data = {**(n.data or {}), "asset_id": a.id}
    n.title = f"{assets.KINDS[a.kind]} · {a.name}"
    for s in canvas.nodes_of(db, n.project_id, "script"):
        cast = (s.data or {}).get("cast")
        if not cast:
            continue
        roles = {k: (a.id if v == old else v) for k, v in cast.get("roles", {}).items()}
        scenes = {k: (a.id if v == old else v) for k, v in cast.get("scenes", {}).items()}
        names = {k: (a.name if (roles.get(k) == a.id or scenes.get(k) == a.id) else v) for k, v in cast.get("names", {}).items()}
        s.data = {**s.data, "cast": {**cast, "roles": roles, "scenes": scenes, "names": names,
                                     "product": a.id if cast.get("product") == old else cast.get("product")}}
    canvas.bump(db.get(Project, n.project_id))
    canvas.audit(db, n.project_id, "user", "swap_asset", {"node_id": nid, "from": old, "to": a.id})
    db.commit()
    emit(n.project_id, "canvas")
    return canvas.node_dict(n)
