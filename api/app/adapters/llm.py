"""大模型网关（OpenAI 兼容协议，走 OpenRouter）。按任务读取设置页里选的模型与 Key。"""
import asyncio
import base64
import json

import httpx

from app import config, settings_store

transport: httpx.AsyncBaseTransport | None = None  # 测试时注入


async def chat(messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False, timeout: float = 60, task: str = "agent") -> dict:
    headers = {"Content-Type": "application/json", "X-Title": "AIGC Ads Platform"}
    key = settings_store.get_secret("openrouter") or config.LLM_API_KEY
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body: dict = {"model": settings_store.get_models()[task], "messages": messages, "temperature": 0.4 if task == "script" else 0.2}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "required"
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        # httpx 的 timeout 只管单次读写；OpenRouter 处理中会发保活空白，模型卡住时永远不超时，所以再加一个总时限
        r = await asyncio.wait_for(client.post(f"{config.LLM_BASE_URL}/chat/completions", headers=headers, json=body), timeout + 30)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]


async def image(content: list[dict] | str, task: str = "storyboard", aspect_ratio: str = "9:16", timeout: float = 180) -> tuple[bytes, str]:
    """生成一张图（OpenRouter 图像输出：modalities 带 image，结果在 message.images[].image_url.url，是 data URL）。"""
    headers = {"Content-Type": "application/json", "X-Title": "AIGC Ads Platform"}
    key = settings_store.get_secret("openrouter") or config.LLM_API_KEY
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": settings_store.get_models()[task], "modalities": ["image", "text"], "image_config": {"aspect_ratio": aspect_ratio},
            "messages": [{"role": "user", "content": content}]}
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        r = await asyncio.wait_for(client.post(f"{config.LLM_BASE_URL}/chat/completions", headers=headers, json=body), timeout + 30)
        r.raise_for_status()
        imgs = r.json()["choices"][0]["message"].get("images") or []
        if not imgs:
            raise RuntimeError("模型没有返回图片")
        url = imgs[0]["image_url"]["url"]
        if url.startswith("data:"):
            head, b64 = url.split(",", 1)
            return base64.b64decode(b64), head[5:].split(";")[0] or "image/png"
        r = await client.get(url)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "image/png")


def parse_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = t.find("{"), t.rfind("}")
    return json.loads(t[start:end + 1])


async def chat_json(system: str, user: str, task: str = "script", timeout: float = 90) -> dict:
    msg = await chat([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True, task=task, timeout=timeout)
    return parse_json(msg.get("content") or "")


async def check_key(key: str) -> tuple[bool, str]:
    """免费校验 OpenRouter Key：查询 Key 信息接口，不产生调用费用。"""
    async with httpx.AsyncClient(timeout=15, transport=transport) as c:
        r = await c.get(f"{config.LLM_BASE_URL}/key", headers={"Authorization": f"Bearer {key}"})
    if r.status_code == 200:
        d = r.json().get("data", {})
        rem = d.get("limit_remaining")
        return True, "连接成功" + (f"，剩余额度 ${rem:.2f}" if isinstance(rem, (int, float)) else "")
    return False, f"校验失败（HTTP {r.status_code}）"
