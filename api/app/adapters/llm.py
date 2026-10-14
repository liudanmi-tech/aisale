"""大模型网关（OpenAI 兼容协议，走 OpenRouter）。按任务读取设置页里选的模型与 Key。"""
import asyncio
import base64
import json
import re

import httpx

from app import config, settings_store

transport: httpx.AsyncBaseTransport | None = None  # 测试时注入


async def chat(messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False, timeout: float = 60, task: str = "agent",
               model: str | None = None) -> dict:
    headers = {"Content-Type": "application/json", "X-Title": "AIGC Ads Platform"}
    key = settings_store.get_secret("openrouter") or config.LLM_API_KEY
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body: dict = {"model": model or settings_store.get_models()[task], "messages": messages, "temperature": 0.4 if task == "script" else 0.2}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "required"
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        # httpx 的 timeout 只管单次读写；OpenRouter 处理中会发保活空白，模型卡住时永远不超时，所以再加一个总时限
        r = await asyncio.wait_for(client.post(f"{config.LLM_BASE_URL}/chat/completions", headers=headers, json=body), timeout + 30)
        _check(r)
        return r.json()["choices"][0]["message"]


def _check(r: httpx.Response) -> None:
    """OpenRouter 出错时把原因翻成人话（原始的 httpx 报错只有状态码，看不出为什么）。"""
    if r.status_code < 400:
        return
    try:
        msg = (r.json().get("error") or {}).get("message") or r.text
    except Exception:  # noqa: BLE001
        msg = r.text
    msg = str(msg)[:200]
    if r.status_code == 402 and re.search(r"image|video", msg, re.I):
        raise RuntimeError("OpenRouter 余额不足：生成图片要求账户余额至少 $1（写剧本等文字调用不受影响）。"
                           "到 openrouter.ai 充值，或在 Keys 设置里调高这个 Key 的额度，然后点「重画失败的分镜」")
    if r.status_code == 402:
        raise RuntimeError("OpenRouter 余额不足或这个 Key 的额度用完了：到 openrouter.ai 充值或调高 Key 额度后重试")
    if r.status_code in (401, 403):
        raise RuntimeError(f"OpenRouter Key 无效或没有权限（{msg}）：在设置页重新填写 Key")
    if r.status_code == 429:
        raise RuntimeError("OpenRouter 请求太频繁，稍等一会儿再试")
    if r.status_code == 404 or "not a valid model" in msg:
        raise RuntimeError(f"模型不可用（{msg}）：在设置页换一个模型")
    raise RuntimeError(f"OpenRouter {r.status_code}：{msg}")


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
        _check(r)
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
