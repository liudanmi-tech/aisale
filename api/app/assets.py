"""素材库：演员 / 场景 / 商品。图片存在 MEDIA_DIR/assets，接口只返回本地地址。

- 演员、场景可以由 AI 生成（定妆照 / 场景图，真实质感），也可以上传；
- 商品必须上传实拍图（AI 不能编造商品外观），没有图时用到它的视频会停下来等上传。
"""
import base64
import hashlib
import logging

from app import config, settings_store
from app.adapters import llm
from app.db import SessionLocal
from app.models import Asset, new_id

log = logging.getLogger(__name__)
KINDS = {"actor": "演员", "scene": "场景", "product": "商品"}
MAX_UPLOAD = 8 * 1024 * 1024

PROMPTS = {
    "actor": ("Photorealistic casting photo for a smartphone TikTok ad. Vertical 3:4. Full body plus clear face, natural light, "
              "plain light-grey studio background, neutral pose, no text, no logo. Character: {name}. {description}"),
    "scene": ("Photorealistic location photo for a smartphone TikTok ad, vertical 9:16, no people in frame, natural cinematic light, "
              "no text, no logo. Location: {name}. {description}"),
}


def asset_dict(a: Asset) -> dict:
    return {"id": a.id, "kind": a.kind, "name": a.name, "description": a.description, "images": a.images or [], "tags": a.tags or [],
            "data": a.data or {}, "source": a.source, "status": a.status, "created_at": a.created_at.isoformat()}


def save_image(raw: bytes, mime: str) -> str:
    ext = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/webp": "webp", "image/png": "png"}.get(mime, "png")
    d = config.MEDIA_DIR / "assets"
    d.mkdir(parents=True, exist_ok=True)
    name = f"{hashlib.sha1(raw).hexdigest()[:16]}.{ext}"
    (d / name).write_bytes(raw)
    return f"/api/v1/media/assets/{name}"


def decode_data_url(data_url: str) -> tuple[bytes, str]:
    if not data_url.startswith("data:image/") or "," not in data_url:
        raise ValueError("只支持 JPG / PNG / WebP 图片")
    head, b64 = data_url.split(",", 1)
    raw = base64.b64decode(b64)
    if len(raw) > MAX_UPLOAD:
        raise ValueError("图片不能超过 8MB")
    return raw, head[5:].split(";")[0]


def media_data_url(url: str) -> str | None:
    """本地媒体地址 → data URI（传给模型做参考图）。"""
    if not url or "/api/v1/media/" not in url:
        return None
    path = config.MEDIA_DIR / url.split("/api/v1/media/", 1)[1]
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    ext = path.suffix.lstrip(".").lower()
    return f"data:image/{'jpeg' if ext in ('jpg', 'jpeg') else ext};base64,{base64.b64encode(raw).decode()}"


def create(kind: str, name: str, description: str = "", data: dict | None = None, tags: list | None = None) -> Asset:
    with SessionLocal() as db:
        a = Asset(id=new_id("as"), kind=kind, name=name.strip()[:60], description=description.strip()[:600], data=data or {},
                  tags=tags or [], images=[], source="ai" if kind != "product" else "upload", status="ready")
        db.add(a)
        db.commit()
        db.refresh(a)
        db.expunge(a)
        return a


async def generate_image(asset_id: str) -> bool:
    """AI 生成演员定妆照 / 场景图，追加为主图。需要 OpenRouter Key；商品不生成。"""
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        if not a or a.kind not in PROMPTS or not settings_store.llm_enabled():
            return False
        prompt = PROMPTS[a.kind].format(name=a.name, description=a.description)
        aspect = "3:4" if a.kind == "actor" else "9:16"
        a.status = "generating"
        db.commit()
    try:
        raw, mime = await llm.image(prompt, task="keyframe", aspect_ratio=aspect)
        url = save_image(raw, mime)
    except Exception as e:  # noqa: BLE001
        log.warning("素材图生成失败 %s: %s", asset_id, e)
        with SessionLocal() as db:
            a = db.get(Asset, asset_id)
            if a:
                a.status = "error"
                a.data = {**(a.data or {}), "error": str(e)[:200]}
                db.commit()
        return False
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        if a:
            a.images = [url, *(a.images or [])][:6]
            a.status = "ready"
            a.data = {k: v for k, v in (a.data or {}).items() if k != "error"}
            db.commit()
    return True


def add_upload(asset_id: str, data_url: str) -> Asset:
    raw, mime = decode_data_url(data_url)
    url = save_image(raw, mime)
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        if not a:
            raise KeyError(asset_id)
        a.images = [url, *[i for i in (a.images or []) if i != url]][:6]
        a.source = "upload"
        a.status = "ready"
        db.commit()
        db.refresh(a)
        db.expunge(a)
        return a
