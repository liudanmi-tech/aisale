"""关键帧局部重绘：人在关键帧上涂遮罩，只重画涂到的地方。

两种重绘方式：
- flux：fal 的 FLUX Fill（真正按遮罩补画的模型），适合改人物动作、表情、背景、去掉多余东西；
- gemini：设置里的 keyframe 模型（多图参考），带上商品实拍图，适合把手机换成 / 修成我们的商品。
不管哪种，最后都把遮罩外的像素换回原图（边缘羽化），保证没涂的地方一个像素都不变。
改之前的关键帧存进 kf_history，可以撤回。
"""
import base64
import logging
import re

import httpx

from app import assets, config, product, settings_store
from app.adapters import fal, llm

log = logging.getLogger(__name__)
FILL_MODEL = "fal-ai/flux-pro/v1/fill"
HISTORY = 6
transport: httpx.AsyncBaseTransport | None = None  # 测试时注入（下载 fal 结果）


def _decode(data_url: str):
    import cv2
    import numpy as np
    m = re.match(r"data:image/[\w.+-]+;base64,(.+)", data_url or "", re.S)
    if not m:
        raise ValueError("遮罩不是图片")
    img = cv2.imdecode(np.frombuffer(base64.b64decode(m.group(1)), np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("遮罩读不出来")
    return img


def mask_from(data_url: str, size: tuple[int, int]):
    """前端传来的遮罩（涂过的地方不透明 / 白）→ 和关键帧同尺寸的 0–255 单通道图。"""
    import cv2
    import numpy as np
    img = _decode(data_url)
    if img.ndim == 3 and img.shape[2] == 4:
        m = img[:, :, 3]
    elif img.ndim == 3:
        m = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        m = img
    m = cv2.resize(m, size, interpolation=cv2.INTER_NEAREST)
    m = np.where(m > 20, 255, 0).astype(np.uint8)
    if m.mean() < 0.2:
        raise ValueError("遮罩是空的：先在图上涂出要重画的地方")
    return m


def composite(orig, new, mask, feather: int = 7):
    """遮罩里用新图、遮罩外用原图，边缘羽化过渡。"""
    import cv2
    import numpy as np
    h, w = orig.shape[:2]
    new = cv2.resize(new, (w, h), interpolation=cv2.INTER_AREA)
    k = feather * 2 + 1
    a = cv2.GaussianBlur(cv2.dilate(mask, np.ones((3, 3), np.uint8)), (k, k), 0).astype(np.float32)[:, :, None] / 255
    return (orig.astype(np.float32) * (1 - a) + new.astype(np.float32) * a).clip(0, 255).astype(np.uint8)


def _png_url(img) -> str:
    import cv2
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _jpg_url(img, quality: int = 92) -> str:
    import cv2
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def _load(url: str):
    import cv2
    p = config.MEDIA_DIR / url.split("/api/v1/media/", 1)[1] if "/api/v1/media/" in (url or "") else None
    img = cv2.imread(str(p), cv2.IMREAD_COLOR) if p and p.exists() else None
    if img is None:
        raise ValueError("找不到这一镜的关键帧图片")
    return img


async def _flux(orig, mask, prompt: str) -> bytes:
    import cv2
    import numpy as np
    grow = cv2.dilate(mask, np.ones((15, 15), np.uint8))  # 给模型一点边缘余量，接缝更自然
    job = await fal._submit(FILL_MODEL, {"prompt": prompt, "image_url": _jpg_url(orig), "mask_url": _png_url(grow),
                                         "num_images": 1, "output_format": "png", "safety_tolerance": "2"})
    res = await fal._result(job, 300)
    if res["status"] != "completed":
        raise RuntimeError(res.get("error") or "局部重绘失败")
    url = ((res["data"].get("images") or [{}])[0] or {}).get("url")
    if not url:
        raise RuntimeError(f"FLUX Fill 没有返回图片：{str(res['data'])[:200]}")
    async with httpx.AsyncClient(timeout=60, transport=transport, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


async def _gemini(orig, mask, prompt: str, refs: list[str]) -> bytes:
    import cv2
    import numpy as np
    show = orig.copy()
    red = np.zeros_like(orig)
    red[:, :] = (40, 40, 230)
    m = (mask > 0)[:, :, None]
    show = np.where(m, (orig * 0.45 + red * 0.55).astype(np.uint8), orig)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(show, cnts, -1, (40, 40, 255), 3)
    text = ("Edit image 1. Change ONLY the area that is highlighted in red in image 2; everything outside it must stay exactly the same "
            f"(same people, faces, clothes, background, lighting, camera angle). In the red area: {prompt}. "
            "Output the full edited image 1 at the same size, photorealistic, no text, no watermark.")
    if refs:
        text += (f" Images 3–{2 + len(refs)} are real photos of OUR phone: any phone in the red area must look exactly like them "
                 "(same shape, color, camera module), with no logo text. " + "The phone is one rigid object with the screen on the front and "
                 "the camera module on the back — the back cover never appears on both sides.")
    content = [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": _jpg_url(orig)}},
               {"type": "image_url", "image_url": {"url": _jpg_url(show)}}, *({"type": "image_url", "image_url": {"url": u}} for u in refs)]
    raw, _ = await llm.image(content, task="keyframe", aspect_ratio="9:16")
    return raw


def engines() -> dict:
    return {"flux": "FLUX Fill（按遮罩精确补画）", "gemini": "Gemini（可带商品图）"}


def pick(engine: str, with_product: bool) -> str:
    if engine in ("flux", "gemini"):
        return engine
    if with_product or not settings_store.get_secret("fal"):
        return "gemini"
    return "flux"


async def redraw(kf_url: str, mask_data_url: str, prompt: str, engine: str = "auto", product_id: str | None = None) -> tuple[bytes, str]:
    """返回 (新关键帧 PNG, 用的方式)。"""
    import cv2
    orig = _load(kf_url)
    h, w = orig.shape[:2]
    mask = mask_from(mask_data_url, (w, h))
    refs = [u for u in (assets.jpeg_data_url(v.get("cutout") or v["url"], max_w=768)
                        for v in (product.good_views(product_id, "hero", 2) if product_id else [])) if u]
    eng = pick(engine, bool(refs))
    raw = await (_gemini(orig, mask, prompt, refs) if eng == "gemini" else _flux(orig, mask, prompt))
    import numpy as np
    new = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if new is None:
        raise RuntimeError("重绘模型返回的不是图片")
    ok, buf = cv2.imencode(".png", composite(orig, new, mask))
    return buf.tobytes(), eng
