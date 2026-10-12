"""大模型网关（OpenAI 兼容协议，走 OpenRouter）。按任务读取设置页里选的模型与 Key。"""
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
        r = await client.post(f"{config.LLM_BASE_URL}/chat/completions", headers=headers, json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]


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
