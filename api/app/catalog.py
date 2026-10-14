"""传音机型库：TECNO / Infinix / itel 近两年发布的手机，一键导入素材库的商品库。

清单在 app/data/transsion_catalog.json（脚本整理，见 scripts/build_transsion_catalog.py）：
每款机型记录官方渲染图的来源地址和每台手机在图里的位置（框）、视角、颜色。
官方渲染图通常一张里排着好几台手机（不同配色的背面 + 正面），导入时按框裁成单台，
再走商品主体的检查、抠图和说明卡提取（app/product.py）。图片版权归传音，仅用于本平台为传音制作广告。
"""
import asyncio
import json
import logging
from functools import lru_cache
from pathlib import Path

import httpx

from app import assets, product
from app.db import SessionLocal
from app.events import emit
from app.models import Asset

log = logging.getLogger(__name__)
CATALOG = Path(__file__).parent / "data" / "transsion_catalog.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
transport: httpx.AsyncBaseTransport | None = None  # 测试时注入
_sem = asyncio.Semaphore(2)


@lru_cache(maxsize=1)
def load() -> list[dict]:
    return json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() else []


def _imported() -> dict[str, dict]:
    with SessionLocal() as db:
        return {(a.data or {}).get("catalog_id"): {"id": a.id, "status": a.status, "images": len(a.images or [])}
                for a in db.query(Asset).filter(Asset.kind == "product") if (a.data or {}).get("catalog_id")}


def listing() -> list[dict]:
    done = _imported()
    return [{k: m[k] for k in ("id", "brand", "name", "series", "announced", "year", "color", "source")} |
            {"views": [x["view"] for x in m["images"]], "imported": done.get(m["id"])} for m in load()]


def _crop(raw: bytes, box: list[int], mask: list[list[int]] | None = None) -> bytes:
    """按框裁出一台手机；mask 是挡在它前面的其他手机的框，先涂白再裁。"""
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    for my0, mx0, my1, mx1 in mask or []:
        img[int(my0 / 1000 * h):int(my1 / 1000 * h), int(mx0 / 1000 * w):int(mx1 / 1000 * w)] = 255
    y0, x0, y1, x1 = box
    pad = 0.0  # 不外扩：官方图里手机常常贴在一起，外扩会带进邻居
    y0, y1 = max(0, int((y0 / 1000 - pad) * h)), min(h, int((y1 / 1000 + pad) * h))
    x0, x1 = max(0, int((x0 / 1000 - pad) * w)), min(w, int((x1 / 1000 + pad) * w))
    crop = _keep_main(img[y0:y1, x0:x1].copy())
    ch, cw = crop.shape[:2]
    m = int(max(ch, cw) * 0.06)  # 四周留白，抠图和参考都更稳
    crop = cv2.copyMakeBorder(crop, m, m, m, m, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    ok, buf = cv2.imencode(".png", crop)
    if not ok:
        raise ValueError("裁剪失败")
    return buf.tobytes()


def _keep_main(crop):
    """官方渲染图是白底：只留框里最大的一块前景（这台手机），相邻手机伸进框里的边涂白。"""
    import cv2
    import numpy as np
    dist = (255 - crop.astype(np.int16)).max(axis=2)
    fg = (dist > 18).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg)
    if n <= 2:
        return _trim_sides(crop)
    big = max(range(1, n), key=lambda i: stats[i, cv2.CC_STAT_AREA])
    keep = np.zeros_like(fg)
    contours, _ = cv2.findContours((labels == big).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(keep, contours, -1, 1, thickness=cv2.FILLED)
    keep = cv2.dilate(keep, np.ones((5, 5), np.uint8))
    crop[keep == 0] = 255
    return _trim_sides(crop)


def _trim_sides(crop):
    """贴在一起的相邻手机会在左右边缘留下一条：在两侧 18% 宽度内找前景最少的那一列（两台之间的缝），缝外涂白。"""
    import numpy as np
    h, w = crop.shape[:2]
    fg = ((255 - crop.astype(np.int16)).max(axis=2) > 18).mean(axis=0)
    band = max(3, int(w * 0.18))
    core = float(np.median(fg[band:w - band])) if w > 2 * band else 1.0
    for side in ("left", "right"):
        cols = range(1, band) if side == "left" else range(w - band, w - 1)
        k = min(cols, key=lambda c: fg[c])
        outer = fg[:k] if side == "left" else fg[k + 1:]
        # 缝要明显比机身「空」，而且缝外确实有东西（别把自己的圆角边裁掉）
        if fg[k] < 0.5 * core and outer.size and outer.max() > 0.3:
            if side == "left":
                crop[:, :k] = 255
            else:
                crop[:, k + 1:] = 255
    return crop


async def _download(c: httpx.AsyncClient, url: str, cache: dict) -> bytes:
    if url not in cache:
        r = await c.get(url)
        r.raise_for_status()
        cache[url] = r.content
    return cache[url]


def _set(asset_id: str, **data) -> None:
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        if a:
            a.data = {**(a.data or {}), **data}
            if "import_step" in data:
                a.status = "ready" if data["import_step"] in ("完成", "失败") else "generating"
            db.commit()


def _resume(asset_id: str) -> None:
    """第一张官方图到了：等这款商品图的视频继续生成。"""
    from app import production  # 避免循环导入
    from app.events import spawn
    for vid in production.resume_waiting(asset_id):
        spawn(production.run(vid))


def start(ids: list[str]) -> list[dict]:
    """建好商品（同一款已导入过就跳过），返回 [{catalog_id, asset_id, created}]；图片在后台下载处理。"""
    by = {m["id"]: m for m in load()}
    done = _imported()
    out = []
    for cid in ids:
        m = by.get(cid)
        if not m:
            continue
        if cid in done:
            out.append({"catalog_id": cid, "asset_id": done[cid]["id"], "created": False})
            continue
        a = assets.create("product", m["name"], f"{m['announced']} 发布 · {m['color']} · 官方渲染图",
                          data={"brand": m["brand"], "model_sku": m["model_sku"], "catalog_id": cid, "source_page": m["source"],
                                "color": m["color"], "import_step": "排队中"})
        with SessionLocal() as db:
            db.get(Asset, a.id).status = "generating"
            db.commit()
        out.append({"catalog_id": cid, "asset_id": a.id, "created": True})
    return out


async def run_import(asset_id: str, catalog_id: str) -> None:
    """下载官方渲染图 → 按框裁成单台手机 → 逐张上传（带视角）→ 检查、抠图、说明卡。"""
    m = next((x for x in load() if x["id"] == catalog_id), None)
    if not m:
        return
    async with _sem:
        cache: dict = {}
        n = 0
        try:
            async with httpx.AsyncClient(timeout=60, headers=UA, transport=transport, follow_redirects=True) as c:
                # 背面放最前：商品主图（列表封面、实拍合成）优先用背面
                for k, img in enumerate(sorted(m["images"], key=lambda x: {"back": 9, "angle": 8, "side": 7}.get(x["view"], 0))):
                    _set(asset_id, import_step=f"下载并裁剪第 {k + 1}/{len(m['images'])} 张")
                    raw = _crop(await _download(c, img["src"], cache), img["box"], img.get("mask"))
                    url = assets.save_image(raw, "image/png")
                    with SessionLocal() as db:
                        a = db.get(Asset, asset_id)
                        a.images = [url, *[u for u in (a.images or []) if u != url]][:10]
                        a.source = "upload"
                        db.commit()
                    _set(asset_id, import_step=f"检查和抠图第 {k + 1}/{len(m['images'])} 张")
                    await product.process_upload(asset_id, url, img["view"])
                    n += 1
                    if n == 1:
                        _resume(asset_id)
            _set(asset_id, import_step="完成", import_error=None)
        except Exception as e:  # noqa: BLE001
            log.warning("导入 %s 失败：%s", catalog_id, e)
            _set(asset_id, import_step="完成" if n else "失败",
                 import_error=f"下载官方图失败（{str(e)[:120]}）。可能是网络连不上 gsmarena.com，开代理后在商品详情里手动上传" if not n else None)
        emit("-", "library")
