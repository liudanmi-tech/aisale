"""洗剧本：拿多模态拆解（breakdown.py）当参考，两步写剧本。

1. 先分析：这条爆款最大的看点是什么、为什么有效、强度多大；给 3–4 个替换方案（标更强 / 相当 / 更弱），不能选更弱的。
   再出洗稿清单：爆款精髓里哪些要保留（钩子手法、节奏、情绪起伏、产品出现的位置），哪些要替换
   （竞品机型 → 我方机型、卖点、人物、场景、俚语、台词）。清单存在剧本节点 data.wash.plan，用户可以改了再重写。
2. 按清单写剧本：镜头数和每镜时长跟着参考视频走（3–8 镜），每镜写明对应参考第几镜、保留了什么、换了什么。
3. 复查：另一次调用检查核心看点有没有被洗弱，弱了就带着问题重写一版。
4. 相似度：新台词 / 画面和参考逐镜做文本比对（difflib），台词最高相似度超过阈值就让模型把那几镜再改一遍。
"""
import difflib
import json
import re

from app.adapters import llm

THRESHOLD = 0.4
MIN_SHOTS, MAX_SHOTS = 3, 8

PLAN_PROMPT = """你是短视频广告的创意总监，要把一条竞品爆款「洗」成我方品牌的新剧本。洗稿最容易犯的错，是把爆款最大的看点洗没了：
比如原片用铲车往手机上倒一整斗水，洗成用桶浇水，反差和荒诞感就没了，这条片子也就不会火。
所以先分析，再出清单。只输出 JSON：
{"analysis": {
   "core": "这条爆款最大的看点，一句话，具体到画面（如「用铲车往手机上倒一整斗水」）",
   "why": "它为什么有效：反差、荒诞、规模、悬念、情绪……具体说",
   "intensity": "这个看点的强度：规模多大、多夸张、和日常差多远",
   "must_not_lose": "洗稿时绝对不能丢的东西（如「考验的规模必须远超日常，荒诞到让人停下来」）"},
 "options": [{"idea": "替换这个看点的方案，具体到画面（如「农用无人机从空中对着手机喷洒」）",
              "intensity": "和原片比：更强 / 相当 / 更弱", "fit": "怎么服务我方卖点和目标市场", "risk": "实拍或 AI 生成的难度、风险"}],
 "chosen": 选第几个方案（从 1 开始）, "chosen_why": "为什么选它",
 "keep": ["必须保留的精髓 3–6 条，每条写成能照着执行的规则；第 1 条写核心看点的强度要求"],
 "replace": ["要替换的元素 4–8 条，统一写成「原来的 → 换成的」；第 1 条写「原看点 → 选中的方案」"]}
规则：
- options 给 3–4 个，至少 2 个是「更强」或「相当」；「更弱」的方案不能选。原看点本身跟品牌无关、也能证明我方卖点时，可以把「保留原看点、只换场景和道具」当成一个方案。
- 看点要服务我方主卖点：把同样强度的手法用在我方卖点上（例如原片用极端考验证明防水，我方主卖点是续航，就用同样夸张的考验证明续航）。
- 替换后的人物、场景、语言都要符合目标市场和人群；不要保留竞品的品牌、机型和原台词。"""

CRITIC_PROMPT = """你是短视频广告的创意总监，检查一版洗稿剧本有没有保住参考爆款的核心看点。只输出 JSON：
{"kept_core": true/false, "intensity": "和原片比：更强 / 相当 / 更弱", "score": 1–5 的整数（5 = 看点完整保住甚至更强）,
 "problems": "哪里把看点洗弱了、洗没了，具体到第几镜；没问题写空字符串", "fix": "怎么改能把强度拉回来，具体到画面"}"""

WRITE_PROMPT = """你是 {brand} 手机的海外短视频广告编剧，正在按洗稿清单把一条竞品爆款改写成我方剧本。只输出 JSON：
{{"shots": [[时长秒数, 画面描述(中文), 口播({lang}), 中文对照], ...],
  "map": [{{"ref": 对应参考第几镜(数字), "kept": "这一镜保留了参考的什么手法", "changed": "这一镜换了什么"}}, ...],
  "product_shots": [手机是画面主体的镜号, 从 1 开始]}}
规则：
- 写 {n} 镜，总时长约 {total} 秒，每镜时长尽量和对应的参考镜头一致；map 和 shots 一一对应。
- 严格执行清单：「保留」的手法要在对应镜头里体现，「替换」的元素一个都不能留原样。
- 台词重新写，不要翻译或照抄参考的原话，用 {lang} 的地道说法。
- 画面描述只写人物动作、手机的角度和姿态、场景，不写屏幕上显示什么、不写画面里的文字（AI 画不准文字）；电池容量、价格这类数字放进口播。
- 至少有一镜是产品特写或手持展示，放在参考里产品出现的位置。
- 核心看点（清单「替换」第 1 条的新方案）必须在画面里拍足，规模和夸张程度不能比原片弱。"""


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
    keys = ("summary", "core", "people_count", "cast", "structure", "selling_point", "why_viral", "essence", "replaceable")
    shots = [{k: s.get(k) for k in ("t", "scene", "people", "action", "camera", "line", "text_on_screen", "emotion", "beat", "product")}
             for s in bd.get("shots") or [] if isinstance(s, dict)]
    return json.dumps({**{k: bd.get(k) for k in keys if bd.get(k)}, "shots": [{"镜": i + 1, **s} for i, s in enumerate(shots)]}, ensure_ascii=False)


async def make_plan(bd: dict, ours: str, comment: str = "") -> dict:
    out = await llm.chat_json(PLAN_PROMPT, f"爆款逐镜拆解：{_ref_text(bd)}\n我方：{ours}\n修改意见：{comment or '无'}", task="script", timeout=120)
    keep = [str(x).strip() for x in out.get("keep") or [] if str(x).strip()]
    replace = [str(x).strip() for x in out.get("replace") or [] if str(x).strip()]
    if not keep or not replace:
        raise RuntimeError("模型没有给出洗稿清单")
    a = out.get("analysis") if isinstance(out.get("analysis"), dict) else {}
    options = [{k: str(o.get(k) or "") for k in ("idea", "intensity", "fit", "risk")} for o in out.get("options") or [] if isinstance(o, dict) and o.get("idea")][:4]
    chosen = int(out["chosen"]) - 1 if str(out.get("chosen", "")).isdigit() else 0
    if options and (not 0 <= chosen < len(options) or "弱" in options[chosen]["intensity"]):  # 模型选了更弱的：换成最强的那个
        chosen = next((k for k, o in enumerate(options) if "强" in o["intensity"]), next((k for k, o in enumerate(options) if "弱" not in o["intensity"]), 0))
    return {"keep": keep[:8], "replace": replace[:10], "analysis": {k: str(a.get(k) or "") for k in ("core", "why", "intensity", "must_not_lose")},
            "options": options, "chosen": chosen if options else None, "chosen_why": str(out.get("chosen_why") or "")}


def choose(plan: dict, idea: str) -> dict:
    """换核心看点的方案（选候选里的另一个，或者自己写一个）：替换清单第 1 条跟着改。"""
    core = (plan.get("analysis") or {}).get("core") or "原看点"
    opts = list(plan.get("options") or [])
    k = next((i for i, o in enumerate(opts) if o["idea"] == idea), None)
    if k is None:
        opts.append({"idea": idea, "intensity": "自定义", "fit": "", "risk": ""})
        k = len(opts) - 1
    line = f"{core} → {idea}"
    rest = [x for x in plan.get("replace") or [] if not x.startswith(core)]
    return {**plan, "options": opts, "chosen": k, "chosen_why": "你选的", "replace": [line, *rest]}


async def critique(plan: dict, shots: list) -> dict | None:
    a = plan.get("analysis") or {}
    if not a.get("core"):
        return None
    opts, k = plan.get("options") or [], plan.get("chosen")
    target = opts[k]["idea"] if isinstance(k, int) and k < len(opts) else ""
    out = await llm.chat_json(CRITIC_PROMPT, f"原片核心看点：{a['core']}\n为什么有效：{a.get('why')}\n强度：{a.get('intensity')}\n不能丢：{a.get('must_not_lose')}\n"
                                             f"这次选的新看点：{target or '见清单'}\n剧本（时长, 画面, 口播, 中文）：{json.dumps(shots, ensure_ascii=False)}", task="script", timeout=90)
    score = int(out["score"]) if str(out.get("score", "")).isdigit() else None
    return {"kept_core": bool(out.get("kept_core")), "intensity": str(out.get("intensity") or ""), "score": score,
            "problems": str(out.get("problems") or ""), "fix": str(out.get("fix") or "")}


def _weak(c: dict | None) -> bool:
    return bool(c) and (not c["kept_core"] or "弱" in c["intensity"] or (c["score"] or 5) <= 2)


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


def competitor_hits(shots: list, brand: str) -> list[int]:
    """台词或画面里出现竞品品牌 / 机型的镜头（镜号从 1 开始）。"""
    from app.wash_plan import COMPETITORS
    own = (brand or "").lower()
    words = [w for w in COMPETITORS if w not in own]
    return [i + 1 for i, s in enumerate(shots) if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", " ".join(map(str, s)).lower()) for w in words)]


async def write(bd: dict, plan: dict, ours: str, brand: str, lang: str, comment: str = "", current: list | None = None, tier: str | None = None) -> dict:
    """tier 是洗稿方案的档位：「high」几乎照拍，台词本来就会像，不按相似度阈值重写，只查有没有竞品品牌。"""
    n, total = target_shots(bd)
    system = WRITE_PROMPT.format(brand=brand, lang=lang, n=n, total=total)
    a = plan.get("analysis") or {}
    plan_text = (f"核心看点分析：原片最大的看点是「{a.get('core')}」，{a.get('why')}；强度：{a.get('intensity')}；绝对不能丢：{a.get('must_not_lose')}\n" if a.get("core") else "") + \
        "保留：\n" + "\n".join(f"- {x}" for x in plan["keep"]) + "\n替换：\n" + "\n".join(f"- {x}" for x in plan["replace"])
    revise = (f"\n当前剧本（JSON）：{json.dumps(current, ensure_ascii=False)}\n请在当前剧本上按修改意见改，意见没涉及的镜头保持原样。"
              if comment and current else "")
    user = f"爆款逐镜拆解：{_ref_text(bd)}\n洗稿清单：\n{plan_text}\n我方：{ours}\n修改意见：{comment or '无'}{revise}"
    shots, mapping, prod = _clean(await llm.chat_json(system, user, task="script", timeout=120), n)
    sim = similarity(shots, bd)
    too_close = [] if tier == "high" else [i + 1 for i, p in enumerate(sim["per_shot"]) if p["line"] > THRESHOLD]
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
    hits = competitor_hits(shots, brand)
    if hits:  # 剧本里还留着竞品品牌：只改这几镜
        try:
            shots2, mapping2, prod2 = _clean(await llm.chat_json(system, user + f"\n上一版：{json.dumps(shots, ensure_ascii=False)}\n第 {'、'.join(map(str, hits))} 镜"
                                                                  f"还出现了竞品品牌或机型，换成 {brand} 的说法，其他镜头不动。", task="script", timeout=120), n)
            if len(competitor_hits(shots2, brand)) < len(hits):
                shots, mapping, prod = shots2, mapping2, prod2
                sim = similarity(shots, bd)
        except Exception:  # noqa: BLE001
            pass
    if tier == "high":
        sim = {**sim, "threshold": 1.0, "note": f"高相似档（几乎照拍）：台词按原片句式重说，不按相似度拦截（最高 {sim['line_max']:.0%}），只检查竞品品牌"}
    left = competitor_hits(shots, brand)
    if left:
        sim = {**sim, "competitor_shots": left}
    check, fixed = None, False
    try:
        check = await critique(plan, shots)
        if _weak(check):  # 看点洗弱了：带着问题再写一版，复查后更好才用
            user2 = (f"{user}\n上一版：{json.dumps(shots, ensure_ascii=False)}\n复查发现核心看点被洗弱了：{check['problems']}\n"
                     f"改法：{check['fix']}\n重写这一版，核心看点的规模和夸张程度不能比原片弱。")
            shots2, mapping2, prod2 = _clean(await llm.chat_json(system, user2, task="script", timeout=120), n)
            check2 = await critique(plan, shots2)
            if check2 and (check2["score"] or 0) > (check["score"] or 0):
                shots, mapping, prod, check, fixed = shots2, mapping2, prod2, check2, True
                sim = similarity(shots, bd)
    except Exception:  # noqa: BLE001  复查失败不影响出剧本
        pass
    if not prod:  # 模型没标产品镜头：用参考里产品出现的那一镜对应的新镜头，再不行用第 3 镜
        ref_prod = {i + 1 for i, s in enumerate(bd.get("shots") or []) if isinstance(s, dict) and (s.get("product") or s.get("beat") == "产品展示")}
        prod = [i for i, m in enumerate(mapping) if m["ref"] in ref_prod][:1] or [min(2, len(shots) - 1)]
    return {"shots": shots, "map": mapping, "product_shots": prod, "similarity": sim, "check": {**check, "rewrote": fixed} if check else None}
