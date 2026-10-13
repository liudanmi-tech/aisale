"""fal.ai 视频生成适配器（队列接口），默认模型 Seedance。

提交：POST https://queue.fal.run/{model}，头 Authorization: Key <FAL_KEY>
返回 request_id、status_url、response_url；轮询 status_url 到 COMPLETED 后读 response_url，视频地址在 video.url。
"""
import asyncio

import httpx

from app import settings_store

BASE = "https://queue.fal.run"
transport: httpx.AsyncBaseTransport | None = None  # 测试时注入
POLL_SECONDS = 4.0


def _headers(key: str | None = None) -> dict:
    return {"Authorization": f"Key {key or settings_store.get_secret('fal')}", "Content-Type": "application/json"}


async def submit(prompt: str, duration: int = 5, aspect_ratio: str = "9:16") -> dict:
    models = settings_store.get_models()
    model = models["video"]
    body = {"prompt": prompt, "aspect_ratio": aspect_ratio, "resolution": models.get("video_resolution", "720p"), "duration": str(duration)}
    async with httpx.AsyncClient(timeout=30, transport=transport) as c:
        r = await c.post(f"{BASE}/{model}", headers=_headers(), json=body)
        r.raise_for_status()
        d = r.json()
    return {"model": model, "request_id": d["request_id"], "status_url": d.get("status_url") or f"{BASE}/{model}/requests/{d['request_id']}/status",
            "response_url": d.get("response_url") or f"{BASE}/{model}/requests/{d['request_id']}"}


async def submit_i2v(prompt: str, image_url: str, duration: int = 5) -> dict:
    """图生视频：image_url 可以是公网地址或 data URI（fal 支持 base64 data URI 作为文件输入）。"""
    models = settings_store.get_models()
    model = models["video_i2v"]
    body = {"prompt": prompt, "image_url": image_url, "resolution": models.get("video_resolution", "720p"), "duration": str(duration)}
    async with httpx.AsyncClient(timeout=60, transport=transport) as c:
        r = await c.post(f"{BASE}/{model}", headers=_headers(), json=body)
        r.raise_for_status()
        d = r.json()
    return {"model": model, "request_id": d["request_id"], "status_url": d.get("status_url") or f"{BASE}/{model}/requests/{d['request_id']}/status",
            "response_url": d.get("response_url") or f"{BASE}/{model}/requests/{d['request_id']}"}


async def wait(job: dict, timeout_seconds: float = 900) -> dict:
    waited = 0.0
    async with httpx.AsyncClient(timeout=30, transport=transport) as c:
        while waited < timeout_seconds:
            r = await c.get(job["status_url"], headers=_headers())
            r.raise_for_status()
            st = r.json().get("status")
            if st == "COMPLETED":
                out = await c.get(job["response_url"], headers=_headers())
                if out.status_code >= 400:
                    return {"status": "failed", "error": out.text[:300]}
                d = out.json()
                return {"status": "completed", "video_url": (d.get("video") or {}).get("url", ""), "seed": d.get("seed")}
            if st in ("FAILED", "CANCELLED", "ERROR"):
                return {"status": "failed", "error": st}
            await asyncio.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
    return {"status": "failed", "error": "timeout"}


async def check_key(key: str) -> tuple[bool, str]:
    """免费校验：查询一个不存在的任务，Key 无效返回 401/403，有效返回 404。"""
    async with httpx.AsyncClient(timeout=15, transport=transport) as c:
        r = await c.get(f"{BASE}/fal-ai/fast-sdxl/requests/00000000-0000-0000-0000-000000000000/status", headers=_headers(key))
    if r.status_code in (401, 403):
        return False, "Key 无效或无权限"
    if r.status_code in (200, 404):
        return True, "连接成功"
    return False, f"校验失败（HTTP {r.status_code}）"
