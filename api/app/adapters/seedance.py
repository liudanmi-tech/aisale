"""Seedance 视频生成适配器（BytePlus ModelArk 国际版）。

真实模式的字段以 BytePlus 官方 API 文档为准，拿到文档后需逐项核对：
- 创建任务：POST {base}/contents/generations/tasks
- 查询任务：GET  {base}/contents/generations/tasks/{id}
- 视频 URL 24 小时失效，完成后需转存对象存储。
"""
import asyncio
import uuid

import httpx

from app import config


async def create_task(prompt: str, ratio: str = "9:16", duration: int = 5, resolution: str = "1080p") -> str:
    if config.SEEDANCE_MODE != "real":
        return f"mock-task-{uuid.uuid4().hex[:8]}"
    body = {
        "model": config.SEEDANCE_MODEL,
        "content": [{"type": "text", "text": prompt}],
        "ratio": ratio,
        "duration": duration,
        "resolution": resolution,
    }
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{config.SEEDANCE_BASE_URL}/contents/generations/tasks",
                         headers={"Authorization": f"Bearer {config.SEEDANCE_API_KEY}"}, json=body)
        r.raise_for_status()
        return r.json()["id"]


async def wait_task(task_id: str, poll_seconds: float = 5, timeout_seconds: float = 600) -> dict:
    """返回 {status, video_url}。"""
    if config.SEEDANCE_MODE != "real":
        await asyncio.sleep(config.STEP_DELAY)
        return {"status": "completed", "video_url": f"mock://seedance/{task_id}.mp4"}
    waited = 0.0
    async with httpx.AsyncClient(timeout=30) as c:
        while waited < timeout_seconds:
            r = await c.get(f"{config.SEEDANCE_BASE_URL}/contents/generations/tasks/{task_id}",
                            headers={"Authorization": f"Bearer {config.SEEDANCE_API_KEY}"})
            r.raise_for_status()
            d = r.json()
            if d.get("status") in ("completed", "succeeded"):
                return {"status": "completed", "video_url": (d.get("content") or {}).get("video_url", "")}
            if d.get("status") in ("failed", "cancelled"):
                return {"status": "failed", "error": d.get("error")}
            await asyncio.sleep(poll_seconds)
            waited += poll_seconds
    return {"status": "failed", "error": "timeout"}
