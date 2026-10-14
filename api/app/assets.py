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
    "scene": ("Photorealistic location photo for a smartphone TikTok ad, vertical 9:16, natural cinematic light. This is an EMPTY SET: "
              "absolutely no people, no hands, no silhouettes, and no phones, tablets, laptops, screens or any electronic device anywhere — "
              "the actors and the real product are added later. Tables, counters and display stands are left empty. "
              "No text, no logo, no readable signs. Location: {name}. {description}"),
}
TURNAROUND = ("Character turnaround sheet of the SAME person as the reference photo, for keeping the actor consistent across shots. "
              "Horizontal 16:9, plain light-grey studio background, even soft light, photorealistic. Four full-body views side by side, "
              "left to right: front, three-quarter, side profile, back. Identical face, hairstyle, outfit and accessories in every view. "
              "No text, no labels, no logo. Character: {name}. {description}")


def default_prompt(a: Asset) -> str:
    return PROMPTS[a.kind].format(name=a.name, description=a.description) if a.kind in PROMPTS else ""


def prompt_for(a: Asset) -> str:
    """重画用的提示词：用户改过就用改过的（data.prompt），否则按名称和描述拼默认的。"""
    return ((a.data or {}).get("prompt") or "").strip() or default_prompt(a)


def asset_dict(a: Asset) -> dict:
    d = {"id": a.id, "kind": a.kind, "name": a.name, "description": a.description, "images": a.images or [], "tags": a.tags or [],
         "data": a.data or {}, "source": a.source, "status": a.status, "created_at": a.created_at.isoformat()}
    if a.kind in PROMPTS:
        d["gen_prompt"] = prompt_for(a)
        d["default_prompt"] = default_prompt(a)
    if a.kind == "product":
        from app import product  # product 依赖本模块
        d["product"] = product.summary(a)
    return d


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


def jpeg_data_url(url: str | None, max_w: int = 1080, quality: int = 88) -> str | None:
    """本地图片缩到 max_w 宽、转 JPEG 后的 data URI。发给外部模型时用：2MB 的 PNG 关键帧会变成 200–400KB。没装 OpenCV 就发原图。"""
    data = media_data_url(url) if url else None
    if not data:
        return None
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(base64.b64decode(data.split(",", 1)[1]), np.uint8), cv2.IMREAD_UNCHANGED)
        if img.ndim == 3 and img.shape[2] == 4:  # 抠图（透明背景）：铺在白底上，否则透明处会变黑
            a = img[:, :, 3:4].astype(np.float32) / 255
            img = (img[:, :, :3].astype(np.float32) * a + 255 * (1 - a)).astype(np.uint8)
        elif img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        h, w = img.shape[:2]
        if w > max_w:
            img = cv2.resize(img, (max_w, int(h * max_w / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return f"data:image/jpeg;base64,{base64.b64encode(buf.tobytes()).decode()}" if ok else data
    except Exception:  # noqa: BLE001
        return data


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
        prompt = prompt_for(a)
        kind = a.kind
        aspect = "3:4" if a.kind == "actor" else "9:16"
        a.status = "generating"
        db.commit()
    check = None
    try:
        raw, mime = await llm.image(prompt, task="keyframe", aspect_ratio=aspect)
        if kind == "scene":
            # 场景图里混进了人或手机，画关键帧时会和演员 / 商品打架：查一下，有就加重要求再画一次
            check = await scene_check(raw, mime)
            if check and (check.get("people") or check.get("phone")):
                raw2, mime2 = await llm.image(prompt + "\nIMPORTANT: the previous attempt contained "
                                              + " and ".join(x for x, k in (("people", "people"), ("a phone/device", "phone")) if check.get(k))
                                              + ". Remove them completely — show only the empty environment.", task="keyframe", aspect_ratio=aspect)
                check2 = await scene_check(raw2, mime2)
                if not check2 or not (check2.get("people") or check2.get("phone")) or not (check.get("people") and check.get("phone")):
                    raw, mime, check = raw2, mime2, check2
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
            a.status = "generating" if a.kind == "actor" else "ready"
            a.data = {**{k: v for k, v in (a.data or {}).items() if k != "error"}, "last_prompt": prompt, **({"gen_step": "三视图"} if a.kind == "actor" else {}),
                      **({"scene_check": check} if a.kind == "scene" else {})}
            db.commit()
    if a and a.kind == "actor":
        await generate_turnaround(asset_id)
    return True


async def scene_check(raw: bytes, mime: str) -> dict | None:
    """看场景图里有没有人物 / 手 / 手机等电子设备。查不了（没 Key、出错）返回 None，不挡流程。"""
    try:
        url = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        msg = await llm.chat([{"role": "user", "content": [
            {"type": "text", "text": "Look at this location photo. Answer only JSON: {\"people\": true/false (any person, face, hand or silhouette, "
                                     "even small or in the background), \"phone\": true/false (any phone, tablet, laptop, monitor or other screen device), "
                                     "\"note\": \"中文，一句话说明在哪里\"}"},
            {"type": "image_url", "image_url": {"url": url}}]}], json_mode=True, task="qc", timeout=60)
        return llm.parse_json(msg.get("content") or "")
    except Exception as e:  # noqa: BLE001
        log.info("场景检查跳过：%s", e)
        return None


async def generate_turnaround(asset_id: str) -> None:
    """演员三视图（正面 / 四分之三 / 侧面 / 背面），参考定妆照生成；关键帧时和定妆照一起作参考，保证不同机位下是同一个人。"""
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        if not a or not a.images:
            return
        ref = media_data_url(a.images[0])
        text = TURNAROUND.format(name=a.name, description=a.description)
        a.status, a.data = "generating", {**(a.data or {}), "gen_step": "三视图"}
        db.commit()
    url, err = None, ""
    try:
        raw, mime = await llm.image([{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": ref}}], task="keyframe", aspect_ratio="16:9")
        url = save_image(raw, mime)
    except Exception as e:  # noqa: BLE001  三视图失败不影响定妆照
        err = str(e)[:200]
        log.warning("三视图生成失败 %s: %s", asset_id, e)
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        if a:
            d = {k: v for k, v in (a.data or {}).items() if k != "gen_step"}
            a.data = {**d, "turnaround": url} if url else {**d, "turnaround_error": err}
            a.status = "ready"
            db.commit()


def add_upload(asset_id: str, data_url: str) -> Asset:
    raw, mime = decode_data_url(data_url)
    url = save_image(raw, mime)
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        if not a:
            raise KeyError(asset_id)
        a.images = [url, *[i for i in (a.images or []) if i != url]][:10 if a.kind == "product" else 6]
        a.source = "upload"
        a.status = "ready"
        db.commit()
        db.refresh(a)
        db.expunge(a)
        return a
