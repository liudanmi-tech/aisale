"""大模型网关（OpenAI 兼容协议，默认走 OpenRouter）。"""
import json

import httpx

from app import config


async def chat(messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False, timeout: float = 30) -> dict:
    headers = {"Content-Type": "application/json"}
    if config.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
    body: dict = {"model": config.LLM_MODEL, "messages": messages, "temperature": 0.3}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "required"
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{config.LLM_BASE_URL}/chat/completions", headers=headers, json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]


async def chat_json(system: str, user: str) -> dict:
    msg = await chat([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True)
    text = (msg.get("content") or "").strip().removeprefix("```json").removesuffix("```").strip()
    return json.loads(text)
