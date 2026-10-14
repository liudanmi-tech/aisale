"""fal.ai 视频生成适配器（队列接口），默认模型 Seedance。

提交：POST https://queue.fal.run/{model}，头 Authorization: Key <FAL_KEY>
返回 request_id、status_url、response_url；轮询 status_url 到 COMPLETED 后读 response_url，视频地址在 video.url。
"""
import asyncio
import logging
import re

import httpx

from app import settings_store

log = logging.getLogger(__name__)
BASE = "https://queue.fal.run"
transport: httpx.AsyncBaseTransport | None = None  # 测试时注入
POLL_SECONDS = 4.0


HINTS = {401: "fal Key 无效", 403: "fal 拒绝请求（常见原因：账户余额不足或 Key 没有权限，去 fal.ai 控制台查看 Billing）",
         404: "模型不存在（检查设置页里的图生视频模型 ID）", 413: "上传的图片太大", 422: "模型不接受这些参数", 429: "请求太频繁，被限流"}


class InputRejected(RuntimeError):
    """模型拒收输入（HTTP 422）：参数不对，或者图片内容不被接受（例如 Seedance 2.x 不收含真人脸的图）。"""


def _reason(r: httpx.Response) -> str:
    """把 fal 的报错（{"detail": [{"loc": [...], "msg": "..."}]}）整理成一句话。"""
    try:
        d = r.json().get("detail")
    except Exception:  # noqa: BLE001
        return r.text[:300]
    if isinstance(d, list):
        return "；".join(f"{'.'.join(str(x) for x in (e.get('loc') or [])[1:]) or '请求'}：{e.get('msg')}" for e in d if isinstance(e, dict))[:400]
    return str(d or r.text)[:300]


def _message(r: httpx.Response) -> str:
    why = _reason(r)
    if r.status_code == 422 and re.search(r"face|person|people|human|portrait|real", why, re.I):
        return f"模型不接受含真人脸的图片（{why}）"
    return f"{HINTS.get(r.status_code, 'fal 返回错误')}（HTTP {r.status_code}：{why}）"


def _check(r: httpx.Response) -> None:
    """失败时带上 fal 返回的原因（raise_for_status 只有状态码，看不出为什么）。"""
    if r.status_code < 400:
        return
    raise (InputRejected if r.status_code == 422 else RuntimeError)(_message(r))


def _headers(key: str | None = None) -> dict:
    return {"Authorization": f"Key {key or settings_store.get_secret('fal')}", "Content-Type": "application/json"}


async def _submit(model: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=60, transport=transport) as c:
        r = await c.post(f"{BASE}/{model}", headers=_headers(), json=body)
        _check(r)
        d = r.json()
    return {"model": model, "request_id": d["request_id"], "status_url": d.get("status_url") or f"{BASE}/{model}/requests/{d['request_id']}/status",
            "response_url": d.get("response_url") or f"{BASE}/{model}/requests/{d['request_id']}"}


def _is_v1(model: str) -> bool:
    return "seedance/v1" in model


def _video_body(prompt: str, duration: int, models: dict, model: str) -> dict:
    res = models.get("video_resolution", "720p")
    body = {"prompt": prompt, "resolution": res, "duration": str(duration)}
    if not _is_v1(model):
        body["generate_audio"] = False  # 配音、字幕后期统一做；模型自带的声音会和口播打架
    return body


async def submit(prompt: str, duration: int = 5, aspect_ratio: str = "9:16") -> dict:
    """文生视频。"""
    models = settings_store.get_models()
    model = models["video"]
    return await _submit(model, {**_video_body(prompt, duration, models, model), "aspect_ratio": aspect_ratio})


# Seedance 2.5 拒收（如含真人脸）时退回 Seedance 2.0
FALLBACK_REF = "bytedance/seedance-2.0/reference-to-video"  # 全能参考，最多 9 张图
FALLBACK_I2V = "bytedance/seedance-2.0/image-to-video"


async def submit_i2v(prompt: str, image_url: str, duration: int = 5, model: str | None = None, end_image: str | None = None) -> dict:
    """图生视频：image_url 是首帧，可以是公网地址或 data URI。Seedance 2.5 的画幅跟随首帧（只能 auto）。"""
    models = settings_store.get_models()
    model = model or models["video_i2v"]
    body = {**_video_body(prompt, duration, models, model), "image_url": image_url, **({"end_image_url": end_image} if end_image else {})}
    if _is_v1(model):
        body["aspect_ratio"] = "9:16"
    return await _submit(model, body)


# 含真人脸、Seedance 2.x 一律拒收的镜头：改用可灵 O3 Pro（全能参考：首帧 + 商品作为 @Element1）
FACE_REF = "fal-ai/kling-video/o3/pro/reference-to-video"
FACE_I2V = "fal-ai/kling-video/o3/pro/image-to-video"


def describe(e: BaseException) -> str:
    """异常写成人话。httpx 的超时 / 连接错误 str() 是空的，直接存会变成「没有返回原因」。"""
    msg = str(e).strip()
    if isinstance(e, httpx.TimeoutException):
        return f"连接 fal 超时（{type(e).__name__}）：网络或代理太慢，稍后点「重做视频」再试" + (f"：{msg}" if msg else "")
    if isinstance(e, httpx.TransportError):
        return f"连不上 fal（{type(e).__name__}）：检查网络 / 代理" + (f"：{msg}" if msg else "")
    return msg or f"{type(e).__name__}（没有更多信息）"


def face_rejected(err: str) -> bool:
    return bool(re.search(r"真人脸|likeness|real people|face|person|portrait", err or "", re.I))


async def submit_kling_ref(prompt: str, start_image: str, product_images: list[str], duration: int = 5, end_image: str | None = None) -> dict:
    """可灵 O3 Pro 全能参考：start_image 是开场画面（关键帧），product_images 是商品各角度实拍，提示词里用 @Element1 指代商品。"""
    body = {"prompt": prompt[:2500], "start_image_url": start_image, "aspect_ratio": "9:16", "duration": str(duration), "generate_audio": False}
    if end_image:
        body["end_image_url"] = end_image
    if product_images:
        body["elements"] = [{"frontal_image_url": product_images[0], "reference_image_urls": product_images[1:4] or [product_images[0]]}]
    return await _submit(FACE_REF, body)


async def submit_kling_i2v(prompt: str, image: str, duration: int = 5, end_image: str | None = None) -> dict:
    return await _submit(FACE_I2V, {"prompt": prompt[:2500], "image_url": image, "duration": str(duration), "generate_audio": False,
                                    **({"end_image_url": end_image} if end_image else {})})


async def submit_ref(prompt: str, image_urls: list[str], duration: int = 5, model: str | None = None) -> dict:
    """全能参考生视频（Seedance 2.x reference-to-video）：提示词里用 @Image1、@Image2 引用 image_urls 里的图。"""
    models = settings_store.get_models()
    model = model or models["video_ref"]
    if "seedance-2.0" in model:
        image_urls = image_urls[:9]
    return await _submit(model, {**_video_body(prompt, duration, models, model), "image_urls": image_urls, "aspect_ratio": "9:16"})


async def _result(job: dict, timeout_seconds: float = 900) -> dict:
    """轮询队列任务，返回 {"status": "completed", "data": 原始结果} 或 {"status": "failed", "error": ...}。"""
    waited = 0.0
    async with httpx.AsyncClient(timeout=30, transport=transport) as c:
        while waited < timeout_seconds:
            r = await c.get(job["status_url"], headers=_headers())
            _check(r)
            st = r.json().get("status")
            if st == "COMPLETED":
                out = await c.get(job["response_url"], headers=_headers())
                if out.status_code >= 400:
                    return {"status": "failed", "error": _message(out), "rejected": out.status_code == 422}
                return {"status": "completed", "data": out.json()}
            if st in ("FAILED", "CANCELLED", "ERROR"):
                body = r.json()
                why = body.get("error") or body.get("detail") or body.get("logs") or body
                return {"status": "failed", "error": f"fal 任务失败（{st}）：{str(why)[:300]}"}
            await asyncio.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
    return {"status": "failed", "error": "timeout"}


async def wait(job: dict, timeout_seconds: float = 900) -> dict:
    res = await _result(job, timeout_seconds)
    if res["status"] != "completed":
        return res
    d = res["data"]
    url = (d.get("video") or {}).get("url", "") if isinstance(d, dict) else ""
    if not url:  # 任务「完成」了但没给视频：多半是模型内部失败，把原始返回带上，别当成功
        log.warning("fal %s 完成但没有视频：%s", job.get("model"), str(d)[:500])
        why = (d.get("error") or d.get("detail") or d) if isinstance(d, dict) else d
        return {"status": "failed", "error": f"{job.get('model', 'fal')} 任务结束了但没有返回视频：{str(why)[:300]}"}
    return {"status": "completed", "video_url": url, "seed": d.get("seed")}


CUTOUT_MODEL = "fal-ai/birefnet/v2"


async def remove_background(image_url: str) -> str:
    """抠图（BiRefNet），返回透明背景 PNG 的地址。"""
    job = await _submit(CUTOUT_MODEL, {"image_url": image_url, "output_format": "png", "refine_foreground": True})
    res = await _result(job, 180)
    if res["status"] != "completed":
        raise RuntimeError(res.get("error") or "抠图失败")
    return (res["data"].get("image") or {}).get("url", "")


async def check_key(key: str) -> tuple[bool, str]:
    """免费校验：查询一个不存在的任务，Key 无效返回 401/403，有效返回 404。"""
    async with httpx.AsyncClient(timeout=15, transport=transport) as c:
        r = await c.get(f"{BASE}/fal-ai/fast-sdxl/requests/00000000-0000-0000-0000-000000000000/status", headers=_headers(key))
    if r.status_code in (401, 403):
        return False, "Key 无效或无权限"
    if r.status_code in (200, 404):
        return True, "连接成功"
    return False, f"校验失败（HTTP {r.status_code}）"
