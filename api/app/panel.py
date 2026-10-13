"""40 人评测：每个虚拟用户是一个独立的 Agent（一次独立的模型调用），按自己的画像逐镜「看」广告。

每个 Agent 看到：自己的画像 + 每一镜的关键帧图片、时长、口播。40 个 Agent 并发调用、互相看不到对方的回答。

为什么不让 Agent 直接说「看完 / 划走 / 点击」：实测让模型直接回答时，40 个人 40 个看完、39 个点击（连「对广告很反感」的人也点了），
模型扮演用户时系统性偏乐观。所以只让模型做它擅长的「相对判断」——每一镜比你平时刷到的广告更吸引还是更差（-2 到 +2），
再用「基准流失率」换算成概率，按固定种子抽样决定在哪一镜划走、是否点击（同一条视频重复评测结果一致）：
- 基准（未校准的行业经验值）：第 1 镜（前 3 秒）继续看的概率按刷视频习惯 0.2–0.55；之后每镜 0.8；看完的人点击 6%。
- 相对评分的倍数：-2 → ×0.3，-1 → ×0.6，0 → ×1，+1 → ×1.3，+2 → ×1.6（概率上限 0.95）。
点击率说明：这是模拟用户的点击意向，不是真实 CTR，没有用传音历史投放数据校准过（calibrated=False）；
接入真实投放数据后，用真实的分镜留存和 CTR 回归校准上面的基准值和倍数。
"""
import asyncio
import base64
import hashlib
import logging
import random
import re
from collections import Counter

from app import assets, settings_store
from app.adapters import llm

log = logging.getLogger(__name__)
CONCURRENCY = 8
MIN_ANSWERS = 30  # 少于这么多 Agent 回答就整体退回模拟
DIMS = ("hook", "clarity", "trust", "local", "intent")
_sem = asyncio.Semaphore(CONCURRENCY)
FIRST_KEEP = {"刷得很快，1 秒不吸引就划走": 0.3, "会看完有剧情的视频": 0.55, "只看熟人和关注的博主": 0.3, "喜欢看评论区再决定": 0.45, "对广告很反感": 0.2}
LATER_KEEP, CLICK_BASE = 0.8, 0.06
FACTOR = {-2: 0.3, -1: 0.6, 0: 1.0, 1: 1.3, 2: 1.6}

SYSTEM = """你是一个真实的 TikTok 用户，正在刷 For You 信息流，刷到了一条手机广告。你的画像（编号 {id}）：
{name}，{age} 岁，{segment}，住在 {city}，职业：{job}；现在用 {phone}，收入{income}；平时爱看：{likes}；刷视频习惯：{habit}；
日常语言：{lang}。
你每天会刷到几十条手机广告，绝大多数你一两秒就划走了。请拿这条和你平时刷到的手机广告比，按你自己的性格和需求挑剔地判断，
不需要配合广告主；和你没关系、看不懂、太假、太像广告的地方都要说出来。
广告按镜头顺序给你（每镜一张画面 + 时长 + 口播），每一镜都要评：
vs_usual = 这一镜比你平时刷到的手机广告更能让你看下去吗：-2 明显更差 / -1 差一点 / 0 差不多 / 1 好一点 / 2 明显更好。
只输出 JSON：
{{"watch": [{{"shot": 1, "vs_usual": -2..2, "thought": "看到这一镜时你心里的真实想法，一句口语中文；想划走就说为什么"}}, ...每一镜一条],
 "click_vs_usual": -2..2 看到最后，比起平时的手机广告你多想点进去了解或买,
 "comment": "如果在评论区留言你会说什么，一句口语（可以用你的日常语言）；觉得假也可以吐槽",
 "scores": {{"hook": 1-10, "clarity": 1-10, "trust": 1-10, "local": 1-10, "intent": 1-10}}（5 分 = 和你平时刷到的手机广告差不多；hook 开头抓不抓人，clarity 卖点清不清楚，trust 信不信，local 像不像你身边的人和事，intent 想不想买）}}"""


def _rel(v) -> int:
    try:
        return max(-2, min(2, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def _score(v) -> int:
    try:
        return max(1, min(10, int(round(float(v)))))
    except (TypeError, ValueError):
        return 5


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


async def watch(persona: dict, content: list[dict], durs: list[int], seed: str) -> dict | None:
    """一个 Agent 看一遍广告：模型给逐镜相对评分，按基准概率抽样决定在哪一镜划走、是否点击。失败返回 None。"""
    async with _sem:
        try:
            msg = await llm.chat([{"role": "system", "content": SYSTEM.format(**persona)}, {"role": "user", "content": content}],
                                 json_mode=True, task="eval", timeout=90)
            out = llm.parse_json(msg.get("content") or "")
        except Exception as e:  # noqa: BLE001
            log.info("评测 Agent %s 失败：%s", persona["id"], e)
            return None
    rows = [w for w in (out.get("watch") or []) if isinstance(w, dict)][: len(durs)]
    if len(rows) < len(durs):
        return None
    rng = random.Random(int(hashlib.sha1(f"{seed}-{persona['id']}".encode()).hexdigest()[:8], 16))
    last, completed = len(durs) - 1, True
    for k, w in enumerate(rows):
        base = FIRST_KEEP.get(persona.get("habit"), 0.4) if k == 0 else LATER_KEEP
        if rng.random() >= min(0.95, base * FACTOR[_rel(w.get("vs_usual"))]):
            last, completed = k, False
            break
    clicked = completed and rng.random() < CLICK_BASE * FACTOR[_rel(out.get("click_vs_usual"))]
    total = sum(durs)
    drop = total if completed else sum(durs[:last]) + min(2, durs[last])  # 在这一镜开头一两秒划走
    scores = out.get("scores") or {}
    return {"persona": persona["id"], "drop_at": round(drop * 15 / total), "completed": completed, "clicked": clicked,
            "drop_shot": None if completed else last + 1, "thought": str(rows[last].get("thought", ""))[:80],
            "vs_usual": [_rel(w.get("vs_usual")) for w in rows], "comment": str(out.get("comment") or "")[:80],
            "scores": {k: _score(scores.get(k)) for k in DIMS}}


async def run(personas: list[dict], shots: list, tasks: list, fallback: list[dict], seed: str = "") -> dict:
    content, durs = ad_content(shots, tasks)
    answers = await asyncio.gather(*(watch(p, content, durs, seed) for p in personas))
    got = [a for a in answers if a]
    if len(got) < MIN_ANSWERS:
        raise ValueError(f"只有 {len(got)} 个 Agent 回答")
    reactions = [a or fallback[p["id"]] for p, a in zip(personas, answers)]
    scores = {k: max(1, min(10, round(sum(a["scores"][k] for a in got) / len(got)))) for k in DIMS}
    # 逐镜留存：每一镜开始时还在看的人数占比
    retention = [round(100 * sum(1 for a in got if a["completed"] or (a["drop_shot"] or 99) >= i + 1) / len(got)) for i in range(len(durs))]
    shot_rel = [round(sum(a["vs_usual"][i] for a in got) / len(got), 1) for i in range(len(durs))]
    # 主要问题：评价最低的那一镜 + 给它差评的人怎么说（只引用差评；被基准流失率抽中划走的人不一定不满意）
    w = min(range(len(durs)), key=lambda i: shot_rel[i])
    neg = list(dict.fromkeys(a["thought"] for a in got if a["vs_usual"][w] < 0 and a["thought"]))
    drops = Counter(a["drop_shot"] for a in got if a["drop_shot"])
    lead = f"第 {drops.most_common(1)[0][0]} 镜流失最多（{drops.most_common(1)[0][1]} 人划走）；" if drops else "没有人中途划走；"
    issue = lead + (f"评价最低的是第 {w + 1} 镜（比平时的广告 {shot_rel[w]:+}）：{'；'.join(neg)[:90]}" if neg
                    else f"没有哪一镜被多数人评得比平时的广告差（最低第 {w + 1} 镜 {shot_rel[w]:+}）")
    return {"reactions": reactions, "scores": scores, "issue": issue, "retention": retention, "agents": len(got), "shot_rel": shot_rel,
            "engine": f"{len(got)} 个独立 Agent · {settings_store.get_models()['eval']}"}
