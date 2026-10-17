"""洗剧本：拿多模态拆解（breakdown.py）当参考，两步写剧本。

1. 洗稿清单：爆款精髓里哪些要保留（钩子手法、节奏、情绪起伏、产品出现的位置），哪些要替换
   （竞品机型 → 我方机型、卖点、人物、场景、俚语、台词）。清单存在剧本节点 data.wash.plan，用户可以改了再重写。
2. 按清单写剧本：镜头数和每镜时长跟着参考视频走（3–8 镜），每镜写明对应参考第几镜、保留了什么、换了什么。
3. 相似度：新台词 / 画面和参考逐镜做文本比对（difflib），台词最高相似度超过阈值就让模型把那几镜再改一遍。
"""
import difflib
import json
import re

from app.adapters import llm

THRESHOLD = 0.4
MIN_SHOTS, MAX_SHOTS = 3, 8

PLAN_PROMPT = """你是短视频广告的创意总监，要把一条竞品爆款「洗」成我方品牌的新剧本：保留它火的结构和手法，换掉品牌、人物、场景和台词。
根据爆款的逐镜拆解和我方信息，列出洗稿清单，只输出 JSON：
{"keep": ["必须保留的精髓 3–6 条，每条写成能照着执行的规则：钩子手法、节奏和镜头数、情绪起伏、冲突 / 转折、产品出现的时间点和方式、证明卖点的方法"],
 "replace": ["要替换的元素 4–8 条，统一写成「原来的 → 换成的」，如「小米 Redmi 13C → TECNO POVA 6」「拉各斯雨夜街头 → 内罗毕马塔图车站」"]}
规则：替换后的人物、场景、语言都要符合目标市场和人群；卖点换成我方的主卖点；不要保留竞品的品牌、机型和原台词。"""

WRITE_PROMPT = """你是 {brand} 手机的海外短视频广告编剧，正在按洗稿清单把一条竞品爆款改写成我方剧本。只输出 JSON：
{{"shots": [[时长秒数, 画面描述(中文), 口播({lang}), 中文对照], ...],
  "map": [{{"ref": 对应参考第几镜(数字), "kept": "这一镜保留了参考的什么手法", "changed": "这一镜换了什么"}}, ...],
  "product_shots": [手机是画面主体的镜号, 从 1 开始]}}
规则：
- 写 {n} 镜，总时长约 {total} 秒，每镜时长尽量和对应的参考镜头一致；map 和 shots 一一对应。
- 严格执行清单：「保留」的手法要在对应镜头里体现，「替换」的元素一个都不能留原样。
- 台词重新写，不要翻译或照抄参考的原话，用 {lang} 的地道说法。
- 画面描述只写人物动作、手机的角度和姿态、场景，不写屏幕上显示什么、不写画面里的文字（AI 画不准文字）；电池容量、价格这类数字放进口播。
- 至少有一镜是产品特写或手持展示，放在参考里产品出现的位置。"""


def _tokens(s: str) -> list[str]:
    """按词比（中文按字）：按字母比的话，两句毫不相干的短英文也能有 40% 相似度。"""
    return re.findall(r"[a-z0-9']+|[\u4e00-\u9fff]", str(s or "").lower())


def _ratio(a: str, b: str) -> float:
    a, b = _tokens(a), _tokens(b)
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0


def similarity(shots: list, bd: dict | None, dna: dict | None = None) -> dict:
    """新剧本每镜的台词 / 画面，和参考里最像的那一镜比，取相似度。没有拆解时只和参考文案比台词。"""
    ref = [s for s in (bd or {}).get("shots") or [] if isinstance(s, dict)]
    ref_lines = [s.get("line") or "" for s in ref] or [(dna or {}).get("text") or "", (dna or {}).get("hook") or ""]
    ref_visuals = [f"{s.get('scene', '')}{s.get('action', '')}" for s in ref]
    per = []
    for s in shots:
        line = s[2] if len(s) > 2 else ""
        per.append({"line": round(max((_ratio(line, r) for r in ref_lines), default=0.0), 2),
                    "visual": round(max((_ratio(s[1], r) for r in ref_visuals), default=0.0), 2)})
    return {"per_shot": per, "line_max": max((p["line"] for p in per), default=0.0),
            "visual_max": max((p["visual"] for p in per), default=0.0), "threshold": THRESHOLD, "has_breakdown": bool(ref)}


def target_shots(bd: dict) -> tuple[int, float]:
    n = len([s for s in bd.get("shots") or [] if isinstance(s, dict)])
    total = float(bd.get("video_duration") or bd.get("duration") or 15)
    return max(MIN_SHOTS, min(MAX_SHOTS, n or 4)), round(max(8.0, min(30.0, total)), 1)


def _ref_text(bd: dict) -> str:
    keys = ("summary", "people_count", "cast", "structure", "selling_point", "why_viral", "essence", "replaceable")
    shots = [{k: s.get(k) for k in ("t", "scene", "people", "action", "camera", "line", "text_on_screen", "emotion", "beat", "product")}
             for s in bd.get("shots") or [] if isinstance(s, dict)]
    return json.dumps({**{k: bd.get(k) for k in keys if bd.get(k)}, "shots": [{"镜": i + 1, **s} for i, s in enumerate(shots)]}, ensure_ascii=False)


async def make_plan(bd: dict, ours: str, comment: str = "") -> dict:
    out = await llm.chat_json(PLAN_PROMPT, f"爆款逐镜拆解：{_ref_text(bd)}\n我方：{ours}\n修改意见：{comment or '无'}", task="script", timeout=120)
    keep = [str(x).strip() for x in out.get("keep") or [] if str(x).strip()]
    replace = [str(x).strip() for x in out.get("replace") or [] if str(x).strip()]
    if not keep or not replace:
        raise RuntimeError("模型没有给出洗稿清单")
    return {"keep": keep[:8], "replace": replace[:10]}


def _clean(out: dict, n: int) -> tuple[list, list, list[int]]:
    from app.workflows import _normalize_shots
    shots = _normalize_shots([r for r in out.get("shots") or [] if isinstance(r, list) and len(r) >= 2])
    if len(shots) < MIN_SHOTS:
        raise RuntimeError("模型写的剧本镜头太少")
    m = [x if isinstance(x, dict) else {} for x in out.get("map") or []]
    m = (m + [{}] * len(shots))[: len(shots)]
    mapping = [{"ref": int(x["ref"]) if str(x.get("ref", "")).isdigit() else None, "kept": str(x.get("kept") or ""),
                "changed": str(x.get("changed") or "")} for x in m]
    prod = sorted({int(k) - 1 for k in out.get("product_shots") or [] if str(k).isdigit() and 1 <= int(k) <= len(shots)})
    return shots, mapping, prod


async def write(bd: dict, plan: dict, ours: str, brand: str, lang: str, comment: str = "", current: list | None = None) -> dict:
    n, total = target_shots(bd)
    system = WRITE_PROMPT.format(brand=brand, lang=lang, n=n, total=total)
    plan_text = "保留：\n" + "\n".join(f"- {x}" for x in plan["keep"]) + "\n替换：\n" + "\n".join(f"- {x}" for x in plan["replace"])
    revise = (f"\n当前剧本（JSON）：{json.dumps(current, ensure_ascii=False)}\n请在当前剧本上按修改意见改，意见没涉及的镜头保持原样。"
              if comment and current else "")
    user = f"爆款逐镜拆解：{_ref_text(bd)}\n洗稿清单：\n{plan_text}\n我方：{ours}\n修改意见：{comment or '无'}{revise}"
    shots, mapping, prod = _clean(await llm.chat_json(system, user, task="script", timeout=120), n)
    sim = similarity(shots, bd)
    too_close = [i + 1 for i, p in enumerate(sim["per_shot"]) if p["line"] > THRESHOLD]
    if too_close:  # 台词太像参考：只把这几镜重写一遍
        user += (f"\n上一版：{json.dumps(shots, ensure_ascii=False)}\n第 {'、'.join(map(str, too_close))} 镜的台词和参考原话太像"
                 f"（超过 {int(THRESHOLD * 100)}%），把这几镜的台词换一种说法重写，其他镜头不动。")
        try:
            shots2, mapping2, prod2 = _clean(await llm.chat_json(system, user, task="script", timeout=120), n)
            sim2 = similarity(shots2, bd)
            if sim2["line_max"] < sim["line_max"]:
                shots, mapping, prod, sim = shots2, mapping2, prod2, {**sim2, "rewrote": too_close}
        except Exception:  # noqa: BLE001  重写失败就用第一版，相似度照实标出来
            pass
    if not prod:  # 模型没标产品镜头：用参考里产品出现的那一镜对应的新镜头，再不行用第 3 镜
        ref_prod = {i + 1 for i, s in enumerate(bd.get("shots") or []) if isinstance(s, dict) and (s.get("product") or s.get("beat") == "产品展示")}
        prod = [i for i, m in enumerate(mapping) if m["ref"] in ref_prod][:1] or [min(2, len(shots) - 1)]
    return {"shots": shots, "map": mapping, "product_shots": prod, "similarity": sim}
