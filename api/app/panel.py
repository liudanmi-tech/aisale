"""40 人评测：每个虚拟用户是一个独立的 Agent（一次独立的模型调用），按自己的画像逐镜「看」广告。

每个 Agent 看到：自己的画像 + 每一镜的关键帧图片、时长、口播。逐镜决定继续看还是划走，写下当时的想法，
看到最后一镜（CTA）才可能点击，最后按 5 个维度打分。40 个 Agent 并发调用、互相看不到对方的回答，
避免一次调用里 40 个人「商量好」给出整齐的分布。

点击率说明：这是 40 个模拟用户的点击意向，不是真实 CTR，没有用传音历史投放数据校准过（calibrated=False）；
接入真实投放数据后，用「模拟意向 → 真实 CTR」做回归校准。
"""
import asyncio
import base64
import logging
import re
from collections import Counter

from app import assets, settings_store
from app.adapters import llm

log = logging.getLogger(__name__)
CONCURRENCY = 8
MIN_ANSWERS = 30  # 少于这么多 Agent 回答就整体退回模拟
DIMS = ("hook", "clarity", "trust", "local", "intent")
_sem = asyncio.Semaphore(CONCURRENCY)

SYSTEM = """你是一个真实的 TikTok 用户，正在刷 For You 信息流，刷到了一条手机广告。你的画像（编号 {id}）：
{name}，{age} 岁，{segment}，住在 {city}，职业：{job}；现在用 {phone}，收入{income}；平时爱看：{likes}；刷视频习惯：{habit}；
日常语言：{lang}。
按你自己的性格和需求真实反应：大多数人刷到广告会很快划走，只有和自己有关、开头抓人的才会看下去；你不需要配合广告主。
广告按镜头顺序给你（每镜一张画面 + 时长 + 口播）。逐镜决定：继续看（keep=true）还是划走（keep=false，后面的镜头就看不到了）。
只输出 JSON：
{{"watch": [{{"shot": 1, "keep": true/false, "thought": "这一镜你心里的真实想法，一句口语中文"}}, ...一直到你划走的那一镜],
 "clicked": true/false 看到最后有没有想点进去（没看到最后一镜填 false）,
 "comment": "如果在评论区留言你会说什么，一句口语（可以用你的日常语言）",
 "scores": {{"hook": 1-10 开头抓不抓人, "clarity": 1-10 卖点清不清楚, "trust": 1-10 信不信, "local": 1-10 像不像你身边的人和事, "intent": 1-10 想不想买}}}}"""


def _small(url: str | None) -> str | None:
    """关键帧缩到 384px 宽的 JPEG 再发给 40 个 Agent，省流量和 token。"""
    data = assets.media_data_url(url) if url else None
    if not data:
        return None
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(base64.b64decode(data.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        if w > 384:
            img = cv2.resize(img, (384, int(h * 384 / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return f"data:image/jpeg;base64,{base64.b64encode(buf.tobytes()).decode()}" if ok else data
    except Exception:  # noqa: BLE001  没装 OpenCV 就发原图
        return data


def _secs(x) -> int:
    """「4」「4s」→ 4；「3–7s」→ 4。"""
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(x))]
    if len(nums) >= 2:
        return max(1, round(nums[1] - nums[0]))
    return max(1, round(nums[0])) if nums else 4


def ad_content(shots: list, tasks: list) -> tuple[list[dict], list[int]]:
    """所有 Agent 共用的广告内容（多模态消息）和每镜时长。"""
    durs = [_secs(s[0]) for s in shots]
    parts: list[dict] = []
    t = 0
    for i, s in enumerate(shots):
        kf = _small((tasks[i] if i < len(tasks) else {}).get("keyframe"))
        parts.append({"type": "text", "text": f"第 {i + 1} 镜（{t}–{t + durs[i]} 秒）画面：{s[1]}；口播：{s[2] if len(s) > 2 else ''}"})
        if kf:
            parts.append({"type": "image_url", "image_url": {"url": kf}})
        t += durs[i]
    return parts, durs


async def watch(persona: dict, content: list[dict], durs: list[int]) -> dict | None:
    """一个 Agent 看一遍广告。失败返回 None。"""
    async with _sem:
        try:
            msg = await llm.chat([{"role": "system", "content": SYSTEM.format(**persona)}, {"role": "user", "content": content}],
                                 json_mode=True, task="eval", timeout=90)
            out = llm.parse_json(msg.get("content") or "")
        except Exception as e:  # noqa: BLE001
            log.info("评测 Agent %s 失败：%s", persona["id"], e)
            return None
    seen = [w for w in (out.get("watch") or []) if isinstance(w, dict)][: len(durs)]
    if not seen:
        return None
    stop = next((k for k, w in enumerate(seen) if not w.get("keep", True)), None)
    completed = stop is None and len(seen) >= len(durs)
    last = stop if stop is not None else len(seen) - 1
    start = sum(durs[:last])
    total = sum(durs)
    drop = total if completed else start + min(2, durs[last])  # 在这一镜开头一两秒划走
    scores = out.get("scores") or {}
    return {"persona": persona["id"], "drop_at": round(drop * 15 / total), "completed": completed,
            "clicked": bool(out.get("clicked")) and last == len(durs) - 1,
            "drop_shot": None if completed else last + 1, "thought": str((seen[last] or {}).get("thought", ""))[:80],
            "comment": str(out.get("comment") or "")[:80],
            "scores": {k: max(1, min(10, int(scores.get(k, 5)) if str(scores.get(k, 5)).isdigit() else 5)) for k in DIMS}}


async def run(personas: list[dict], shots: list, tasks: list, fallback: list[dict]) -> dict:
    content, durs = ad_content(shots, tasks)
    answers = await asyncio.gather(*(watch(p, content, durs) for p in personas))
    got = [a for a in answers if a]
    if len(got) < MIN_ANSWERS:
        raise ValueError(f"只有 {len(got)} 个 Agent 回答")
    reactions = [a or fallback[p["id"]] for p, a in zip(personas, answers)]
    scores = {k: max(1, min(10, round(sum(a["scores"][k] for a in got) / len(got)))) for k in DIMS}
    # 逐镜留存：每一镜开始时还在看的人数占比
    retention = [round(100 * sum(1 for a in got if a["completed"] or (a["drop_shot"] or 99) >= i + 1) / len(got)) for i in range(len(durs))]
    # 主要问题：流失最多的那一镜 + 划走的人当时在想什么
    drops = Counter(a["drop_shot"] for a in got if a["drop_shot"])
    if drops:
        k, cnt = drops.most_common(1)[0]
        why = "；".join(dict.fromkeys(a["thought"] for a in got if a["drop_shot"] == k and a["thought"]))
        issue = f"第 {k} 镜流失最多（{cnt} 人划走）：{why[:90]}"
    else:
        issue = "没有人中途划走"
    return {"reactions": reactions, "scores": scores, "issue": issue, "retention": retention, "agents": len(got),
            "engine": f"{len(got)} 个独立 Agent · {settings_store.get_models()['eval']}"}
