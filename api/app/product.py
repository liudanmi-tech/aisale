"""商品主体：把一张商品图升级成可复用的「主体」，后面的关键帧、视频、质检都只引用它。

素材库里商品的 data 里存：
- views：{图片地址: {"view": 视角, "cutout": 抠图地址, "status": "checking" | "ok" | "warn" | "bad", "issues": [...], "checks": {...}}}
  视角：正面 / 正面亮屏 / 背面 / 侧面 / 45° / 摄像头特写 / 其他。拼图、有多台手机的图标 bad，不拿来做参考。
- spec_card：商品说明卡（颜色、摄像头模组、logo、屏幕、机身），上传后由多模态模型提取一次，人可以改（改过就不再自动覆盖）。

抠图：有 fal Key 时用 BiRefNet；没有时，纯色背景的实拍用 OpenCV 按背景色抠；背景太乱就不抠，提示换图。
"""
import asyncio
import logging

import httpx

from app import assets, config, settings_store
from app.adapters import fal, llm
from app.db import SessionLocal
from app.models import Asset

log = logging.getLogger(__name__)
VIEWS = {"front": "正面", "front_on": "正面亮屏", "back": "背面", "side": "侧面", "angle": "45°", "detail": "摄像头特写", "other": "其他"}
SPEC_FIELDS = {"color": "颜色", "camera_module": "摄像头模组", "logo": "logo 位置", "screen": "屏幕", "body": "机身", "notes": "其他特征"}
MIN_SIDE = 1024
media_transport: httpx.AsyncBaseTransport | None = None  # 测试时注入（下载抠图结果）

CHECK_PROMPT = """你在审核一张手机商品图，它会被拿来当 AI 生成广告时的商品参考。只输出 JSON：
{"view": "front / front_on / back / side / angle / detail / other 之一（front_on = 正面且屏幕亮着）",
 "phones": 画面里有几台手机（整数）,
 "is_collage": 是不是多张图拼在一起、或同一台手机的正反面放在一张图里（true/false）,
 "background": "plain（纯色或干净棚拍背景）/ busy（杂乱背景或生活场景）",
 "sharp": 是否清晰（true/false）,
 "occluded": 手机是否被手或物体大面积挡住（true/false）}"""

SPEC_PROMPT = """下面是同一款手机的几张实拍图（标注了视角）。为 AI 生成广告写一张「商品说明卡」，生成画面时会照着它画、质检时会照着它查。
只写看得见的外观事实，越具体越好（数量、形状、排列、位置、颜色），不要写卖点。只输出 JSON：
{"color": "机身颜色和质感，如 雾面钛灰",
 "camera_module": "摄像头模组的形状、镜头数量和排列、闪光灯位置，如 左上角竖排三摄 + 右侧单独一颗小镜头，闪光灯在模组右侧",
 "logo": "logo / 文字的内容和位置，如 背面左下竖排 TECNO CAMON",
 "screen": "屏幕形态，如 直屏、居中挖孔、四边等宽窄边框",
 "body": "机身比例和边框，如 窄长机身、直角金属中框、圆角",
 "notes": "其他容易画错的特征，没有写 无"}"""


def _views(a: Asset) -> dict:
    return dict((a.data or {}).get("views") or {})


def _local_path(url: str):
    return config.MEDIA_DIR / url.split("/api/v1/media/", 1)[1] if url and "/api/v1/media/" in url else None


def _set_view(asset_id: str, url: str, **fields) -> None:
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        if not a:
            return
        views = _views(a)
        views[url] = {**views.get(url, {}), **fields}
        a.data = {**(a.data or {}), "views": views}
        db.commit()


# ---------- 抠图 ----------

def local_cutout(url: str) -> str | None:
    """纯色背景的商品图：按边缘的背景色抠出商品，存成透明 PNG。背景不干净就返回 None。"""
    import cv2
    import numpy as np
    img = cv2.imread(str(_local_path(url)), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    edge = np.concatenate([img[:6].reshape(-1, 3), img[-6:].reshape(-1, 3), img[:, :6].reshape(-1, 3), img[:, -6:].reshape(-1, 3)]).astype(np.float32)
    bg = np.median(edge, axis=0)
    if float(np.linalg.norm(edge - bg, axis=1).mean()) > 18:  # 边缘颜色不统一：不是纯色背景
        return None
    dist = np.linalg.norm(img.astype(np.float32) - bg, axis=2)
    mask = (dist > 28).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        return None
    big = max(range(1, n), key=lambda i: stats[i, cv2.CC_STAT_AREA])  # 只留最大的一块：裁剪图边上可能带进相邻手机的一条边
    if stats[big, cv2.CC_STAT_AREA] < 0.05 * h * w:
        return None
    keep = [big]
    mask = np.isin(labels, keep).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros_like(mask)
    cv2.drawContours(mask, contours, -1, 255, thickness=cv2.FILLED)  # 填掉屏幕反光、镜头高光这类和背景同色的洞
    mask = cv2.GaussianBlur(mask, (3, 3), 0)
    rgba = np.dstack([img, mask])
    ok, buf = cv2.imencode(".png", rgba)
    return assets.save_image(buf.tobytes(), "image/png") if ok else None


async def cutout(url: str) -> tuple[str | None, str]:
    """返回 (抠图地址, 方式)。"""
    if settings_store.get_secret("fal"):
        try:
            remote = await fal.remove_background(assets.jpeg_data_url(url, max_w=2048, quality=92) or "")
            async with httpx.AsyncClient(timeout=60, transport=media_transport, follow_redirects=True) as c:
                r = await c.get(remote)
                r.raise_for_status()
            return assets.save_image(r.content, "image/png"), "BiRefNet"
        except Exception as e:  # noqa: BLE001  fal 抠图失败就本地抠
            log.warning("fal 抠图失败，改用本地：%s", e)
    try:
        return await asyncio.to_thread(local_cutout, url), "本地"
    except Exception as e:  # noqa: BLE001
        log.warning("本地抠图失败：%s", e)
        return None, ""


# ---------- 检查 ----------

def _size(url: str) -> tuple[int, int]:
    import cv2
    img = cv2.imread(str(_local_path(url)))
    return (img.shape[1], img.shape[0]) if img is not None else (0, 0)


async def check_image(url: str, view_hint: str | None) -> dict:
    """单张图的检查：分辨率（本地）+ 视角、几台手机、是否拼图、背景、清晰度（多模态模型）。"""
    issues, status = [], "ok"
    try:
        w, h = await asyncio.to_thread(_size, url)
    except Exception:  # noqa: BLE001
        w = h = 0
    if w and min(w, h) < MIN_SIDE:
        issues.append(f"分辨率偏低（{w}×{h}），建议短边 ≥ {MIN_SIDE}")
        status = "warn"
    out: dict = {}
    if settings_store.llm_enabled():
        try:
            msg = await llm.chat([{"role": "user", "content": [{"type": "text", "text": CHECK_PROMPT},
                                                               {"type": "image_url", "image_url": {"url": assets.jpeg_data_url(url) or ""}}]}],
                                 json_mode=True, task="qc", timeout=60)
            out = llm.parse_json(msg.get("content") or "")
        except Exception as e:  # noqa: BLE001
            log.warning("商品图检查失败：%s", e)
    phones = int(out.get("phones") or 1) if str(out.get("phones", 1)).isdigit() else 1
    if out.get("is_collage") or phones > 1:
        issues.append("这是拼图或画面里有多台手机：AI 会照着画出两台，不会用它做参考。请上传单独一台手机的实拍图")
        status = "bad"
    if out.get("background") == "busy":
        issues.append("背景杂乱，抠图和参考效果会变差，建议纯色背景")
        status = status if status == "bad" else "warn"
    if out.get("sharp") is False:
        issues.append("图片不清晰")
        status = status if status == "bad" else "warn"
    if out.get("occluded"):
        issues.append("手机被挡住了一部分")
        status = status if status == "bad" else "warn"
    view = view_hint if view_hint in VIEWS else (out.get("view") if out.get("view") in VIEWS else "other")
    return {"view": view, "status": status, "issues": issues, "checks": {"width": w, "height": h, **out}}


async def extract_spec(asset_id: str) -> None:
    """用能用的几张图提取商品说明卡；人改过的说明卡不覆盖。"""
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        if not a or (a.data or {}).get("spec_card_edited") or not settings_store.llm_enabled():
            return
        good = [(u, v) for u, v in _views(a).items() if v.get("status") != "bad"][:4]
    if not good:
        return
    content = [{"type": "text", "text": SPEC_PROMPT}]
    for u, v in good:
        content += [{"type": "text", "text": f"视角：{VIEWS.get(v.get('view'), '其他')}"}, {"type": "image_url", "image_url": {"url": assets.jpeg_data_url(u) or ""}}]
    try:
        msg = await llm.chat([{"role": "user", "content": content}], json_mode=True, task="qc", timeout=90)
        card = {k: str(v)[:160] for k, v in llm.parse_json(msg.get("content") or "").items() if k in SPEC_FIELDS and v}
    except Exception as e:  # noqa: BLE001
        log.warning("商品说明卡提取失败：%s", e)
        return
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        if a and not (a.data or {}).get("spec_card_edited"):
            a.data = {**(a.data or {}), "spec_card": card}
            db.commit()


async def process_upload(asset_id: str, url: str, view_hint: str | None = None) -> None:
    """商品图上传后：检查 → 抠图 → 更新说明卡。"""
    _set_view(asset_id, url, view=view_hint if view_hint in VIEWS else "other", status="checking", issues=[])
    res = await check_image(url, view_hint)
    _set_view(asset_id, url, **res)
    if res["status"] != "bad":
        cut, how = await cutout(url)
        _set_view(asset_id, url, cutout=cut, cutout_by=how,
                  **({} if cut else {"issues": [*res["issues"], "没能自动抠图（背景不是纯色），商品特写会直接用原图"]}))
    await extract_spec(asset_id)


# ---------- 下游取用 ----------

ORDER = {"hero": ["back", "angle", "side", "front", "front_on", "detail", "other"],
         "hand": ["back", "front", "front_on", "angle", "side", "detail", "other"]}


def good_views(asset_id: str | None, purpose: str = "hero", limit: int = 3) -> list[dict]:
    """能用的商品图（排除拼图等），按用途排好序：[{url, view, cutout}]。没做过检查的老图也算能用。"""
    if not asset_id:
        return []
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        if not a:
            return []
        views = _views(a)
        imgs = list(a.images or [])
    items = [{"url": u, **views.get(u, {"view": "other"})} for u in imgs]
    items = [x for x in items if x.get("status") != "bad"]
    order = ORDER.get(purpose, ORDER["hero"])
    items.sort(key=lambda x: order.index(x.get("view")) if x.get("view") in order else len(order))
    out, seen = [], set()
    for x in items:  # 同一视角只取一张，尽量覆盖不同角度
        if x.get("view") in seen and x.get("view") != "other":
            continue
        seen.add(x.get("view"))
        out.append(x)
    return out[:limit]


def spec_text(asset_id: str | None) -> str:
    """说明卡拼成一句话，写进提示词和质检清单。"""
    if not asset_id:
        return ""
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        card = (a.data or {}).get("spec_card") if a else None
    return "；".join(f"{SPEC_FIELDS[k]}：{v}" for k, v in (card or {}).items() if k in SPEC_FIELDS and v and v != "无")


def summary(a: Asset) -> dict:
    """前端用：视角覆盖情况和问题。"""
    views = _views(a)
    have = {v.get("view") for u, v in views.items() if u in (a.images or []) and v.get("status") != "bad"}
    missing = [VIEWS[k] for k in ("back", "front", "side") if k not in have]
    bad = sum(1 for u, v in views.items() if u in (a.images or []) and v.get("status") == "bad")
    return {"missing": missing, "bad": bad, "checking": any(v.get("status") == "checking" for v in views.values())}
