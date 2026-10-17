"""洗稿方案节点（爆款 → 洗稿方案 → 剧本）：写剧本之前的拆分、评估和人工确认。

① 要素拆分：把参考爆款拆成 钩子 / 人物 / 场景 / 节奏 / 台词 / 镜头 六行。
② 相似度评估：参考和我方需求有多像（卖点、市场、人群、产品四项），推荐档位：
   高（几乎照拍）/ 中（保钩子）/ 低（只保结构）。Agent 一次写 3 个时三档各一个，人可以改档位。
③ 按档位定每行「保留 / 保留手法换内容 / 替换」，④ 由模型写出每行我方怎么做。
人确认（审核通过）后，下游剧本才按这张表写分镜。
"""
import logging

from app.adapters import llm

log = logging.getLogger(__name__)

ROWS = [("hook", "钩子 / 核心看点"), ("cast", "人物"), ("scene", "场景"), ("rhythm", "节奏"), ("lines", "台词"), ("camera", "镜头")]
ROW_ZH = dict(ROWS)
ACTION_ZH = {"keep": "保留", "adapt": "保留手法、换内容", "replace": "替换"}
TIERS = {
    "high": {"label": "高 · 几乎照拍", "desc": "人物换成目标市场的当地人，钩子、场景、节奏、镜头都照原片；台词保留句式重新说，只换品牌和卖点",
             "actions": {"hook": "keep", "cast": "replace", "scene": "keep", "rhythm": "keep", "lines": "adapt", "camera": "keep"}},
    "mid": {"label": "中 · 保钩子", "desc": "保留钩子手法、节奏和镜头语言，人物、场景、台词全部替换",
            "actions": {"hook": "adapt", "cast": "replace", "scene": "replace", "rhythm": "keep", "lines": "replace", "camera": "keep"}},
    "low": {"label": "低 · 只保结构", "desc": "只保留节奏和情绪起伏，钩子换成同等或更强的新看点，人物、场景、台词、镜头都换",
            "actions": {"hook": "replace", "cast": "replace", "scene": "replace", "rhythm": "keep", "lines": "replace", "camera": "replace"}},
}
REGIONS = {"非洲": ["尼日利亚", "肯尼亚", "南非", "埃及", "加纳"], "南亚": ["巴基斯坦", "孟加拉", "印度"],
           "东南亚": ["印尼", "菲律宾", "越南", "泰国", "马来西亚"]}
SP_GROUPS = [{"续航", "电池", "快充", "充电", "battery"}, {"拍照", "夜拍", "自拍", "美颜", "相机", "camera"},
             {"防水", "耐用", "耐摔", "三防", "durable"}, {"存储", "内存", "storage"}, {"性能", "游戏", "流畅"}, {"价格", "性价比", "优惠"}]
FIT_WEIGHTS = {"selling_point": 0.35, "market": 0.25, "audience": 0.2, "product": 0.2}
FIT_ZH = {"selling_point": "卖点", "market": "市场", "audience": "人群", "product": "产品"}
MATCH_SCORE = {"match": 1.0, "partial": 0.5, "no": 0.0}
COMPETITORS = ["xiaomi", "redmi", "小米", "红米", "samsung", "三星", "galaxy", "realme", "oppo", "vivo", "honor", "荣耀", "apple", "iphone", "苹果", "huawei", "华为", "poco"]

PROMPT = """你是短视频广告的创意总监，在给一条竞品爆款做「洗稿方案」：先把原片拆成六个要素，再按给定档位写出每个要素我方怎么做。
洗稿最容易犯的错，是把原片最大的看点洗没了：比如原片用铲车往手机上倒一整斗水，洗成用桶浇水，反差感就没了。只输出 JSON：
{"rows": {
   "hook":   {"ref": "原片的钩子 / 核心看点，具体到画面和第几秒", "ours": "我方怎么做", "why": "为什么这样做"},
   "cast":   {"ref": "原片几个人、各是什么角色和外形", "ours": "...", "why": "..."},
   "scene":  {"ref": "原片的场景（逐镜简述）", "ours": "...", "why": "..."},
   "rhythm": {"ref": "镜头数、每镜时长、情绪起伏、产品第几秒出现", "ours": "...", "why": "..."},
   "lines":  {"ref": "原片台词的句式和要点（不要整段照抄）", "ours": "...", "why": "..."},
   "camera": {"ref": "景别和运镜（逐镜简述）", "ours": "...", "why": "..."}},
 "audience_fit": {"match": "match / partial / no", "note": "原片的人群和我方人群像不像"},
 "product_fit": {"match": "match / partial / no", "note": "原片的产品（品类、价位）和我方像不像"},
 "analysis": {"core": "原片最大的看点", "why": "为什么有效", "intensity": "强度：规模多大、多夸张", "must_not_lose": "不能丢的东西"},
 "options": [{"idea": "钩子 / 核心看点的替换方案，具体到画面", "intensity": "和原片比：更强 / 相当 / 更弱", "fit": "怎么服务我方卖点", "risk": "实拍或 AI 生成难点"}],
 "chosen": 选第几个方案（从 1 开始）}
每行怎么做由档位定（用户消息里给出每行是 保留 / 保留手法换内容 / 替换）：
- 保留：ours 照原片写，只去掉竞品品牌、换成我方机型，必要时把地名换成目标市场的；
- 保留手法换内容：同样的手法，换成服务我方卖点、符合目标市场的内容；
- 替换：写新的内容，但钩子替换时强度不能比原片弱。
人物一律换成目标市场的当地人；台词永远不照抄原话，「保留手法」时保留句式重新说，用目标语言的地道说法。
options 给 3–4 个，「更弱」的不能选；钩子是「保留」时 options 可以为空。"""


def _region(m: str) -> str | None:
    return next((r for r, ms in REGIONS.items() if m in ms), None)


def _sp_match(a: str, b: str) -> str:
    a, b = (a or "").lower(), (b or "").lower()
    if not a or not b or a == "未知":
        return "partial"
    if a == b or a in b or b in a:
        return "match"
    ga = next((g for g in SP_GROUPS if any(w in a for w in g)), None)
    return "match" if ga and any(w in b for w in ga) else "no"


def fit(ad: dict, ours: dict, llm_fit: dict | None = None) -> dict:
    """参考和我方需求像不像：卖点、市场按规则判，人群、产品让模型判。返回分数、各项和推荐档位。"""
    ref_sp = (ad.get("breakdown") or {}).get("selling_point") or ad.get("selling_point") or ""
    m_ref, m_ours = ad.get("market") or "", ours.get("market") or ""
    market = "match" if m_ref == m_ours else "partial" if _region(m_ref) and _region(m_ref) == _region(m_ours) else "no"
    items = {"selling_point": {"match": _sp_match(ref_sp, ours.get("selling_point", "")), "ref": ref_sp or "未知", "ours": ours.get("selling_point", "")},
             "market": {"match": market, "ref": m_ref or "未知", "ours": m_ours}}
    for k in ("audience", "product"):
        got = (llm_fit or {}).get(k) or {}
        items[k] = {"match": got.get("match") if got.get("match") in MATCH_SCORE else "partial", "note": str(got.get("note") or "")}
    score = round(sum(FIT_WEIGHTS[k] * MATCH_SCORE[v["match"]] for k, v in items.items()), 2)
    tier = "high" if score >= 0.75 else "mid" if score >= 0.45 else "low"
    why = "；".join(f"{FIT_ZH[k]}{ {'match': '一致', 'partial': '相近', 'no': '不同'}[v['match']] }" for k, v in items.items())
    return {"score": score, "items": items, "recommended": tier, "reason": f"{why}，综合 {score:.0%} → 推荐「{TIERS[tier]['label']}」"}


def ref_breakdown(ad_row) -> dict | None:
    """有视频拆解用拆解；没有就用入库时按文案推断的分镜凑一个（会标出来）。"""
    dna = ad_row.dna or {}
    if dna.get("breakdown"):
        return dna["breakdown"]
    shots = []
    for s in dna.get("shots") or []:
        if isinstance(s, (list, tuple)) and s:
            shots.append({"t": str(s[0]), "scene": str(s[1]) if len(s) > 1 else "", "action": "", "line": ""})
    return {"shots": shots or [{"t": "0–15s", "scene": dna.get("scene") or "", "action": "", "line": dna.get("text") or ""}],
            "summary": dna.get("text") or ad_row.title, "selling_point": ad_row.selling_point, "video_duration": dna.get("duration") or 15,
            "core": {"device": dna.get("hook") or ad_row.hook}, "inferred": True}


def rows_for(tier: str, raw_rows: dict | None, old: list | None = None) -> list[dict]:
    """按档位排出六行；模型给的 ref / ours 填进去；人改过的行（edited）保留。"""
    kept = {r["key"]: r for r in old or [] if r.get("edited")}
    out = []
    for key, label in ROWS:
        if key in kept:
            out.append(kept[key])
            continue
        r = (raw_rows or {}).get(key) or {}
        out.append({"key": key, "label": label, "action": TIERS[tier]["actions"][key], "ref": str(r.get("ref") or ""),
                    "ours": str(r.get("ours") or ""), "why": str(r.get("why") or ""), "edited": False})
    return out


async def draft(bd: dict, ours_text: str, tier: str, comment: str = "") -> dict:
    from app import wash
    actions = "；".join(f"{ROW_ZH[k]}：{ACTION_ZH[a]}" for k, a in TIERS[tier]["actions"].items())
    out = await llm.chat_json(PROMPT, f"参考爆款拆解：{wash._ref_text(bd)}\n我方：{ours_text}\n档位：{TIERS[tier]['label']}（{TIERS[tier]['desc']}）\n"
                                      f"每行怎么做：{actions}\n修改意见：{comment or '无'}", task="script", timeout=150)
    if not isinstance(out.get("rows"), dict):
        raise RuntimeError("模型没有给出要素表")
    return out


def to_plan(d: dict) -> dict:
    """确认后的六行表 → 写剧本用的清单（保留 / 替换 + 核心看点分析）。"""
    keep, replace = [], []
    for r in d.get("rows") or []:
        label, ref, ours = r.get("label") or ROW_ZH.get(r.get("key"), ""), r.get("ref") or "", r.get("ours") or ""
        if r.get("action") == "keep":
            keep.append(f"{label}照原片：{ours or ref}")
        elif r.get("action") == "adapt":
            keep.append(f"{label}保留原片的手法：{ref}")
            replace.append(f"{label}：{ref} → {ours}")
        else:
            replace.append(f"{label}：{ref} → {ours}")
    keep += [f"人工意见（必须执行）：{x}" for x in d.get("notes") or []]
    plan = {"keep": keep or ["节奏和镜头数照原片"], "replace": replace or ["竞品品牌 → 我方机型"]}
    for k in ("analysis", "options", "chosen", "chosen_why"):
        if d.get(k) is not None:
            plan[k] = d[k]
    hook = next((r for r in d.get("rows") or [] if r.get("key") == "hook"), None)
    if hook and plan.get("options") is not None and hook.get("ours"):  # 钩子以表里（人可能改过）的为准
        opts = list(plan["options"])
        k = next((i for i, o in enumerate(opts) if o.get("idea") == hook["ours"]), None)
        if k is None and hook.get("action") != "keep":
            opts.append({"idea": hook["ours"], "intensity": "自定义", "fit": "", "risk": ""})
            k = len(opts) - 1
        plan["options"], plan["chosen"] = opts, k
    return plan


def summary(d: dict) -> str:
    t = TIERS.get(d.get("tier") or "", TIERS["mid"])
    rows = d.get("rows") or []
    keep = [r["label"] for r in rows if r.get("action") == "keep"]
    change = [r["label"] for r in rows if r.get("action") != "keep"]
    return f"{t['label']}：保留 {'、'.join(keep) or '无'}；替换 {'、'.join(change) or '无'}"
