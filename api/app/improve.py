"""剧本自动改进一轮：同时出 3 个改法不同的版本，和原版放在同一轮里一起让 5 个评委打分，比原版高够多才采用。

- A 版「攻短板」：只改和得分最低的那个维度有关的镜头，其他镜头一字不改
- B 版「改共识问题」：只解决被 ≥2 个评委同时提到的前 2 个问题
- C 版「重写结构」：保留创意核心（梗、卖点怎么落地），重新设计钩子和整体结构，可以换镜头数
- 原版也重新打一次分（同一批评委、同一时间），版本之间才可比
- 最好的版本比原版高 ≥ MIN_GAIN 分、并且同一批评委里多数人各自都给它打了更高分（配对比较）才采用——评分本身有几分波动，
  实测同一个剧本两次评分能差 6 分；否则保留原版，记一次「没改出更好的」
- 连续 2 轮没进步：提示这个创意到顶了，回备选创意里换一个
每一轮的 4 个版本都存着，可以手动挑任意一版用。
"""
import asyncio
import json
import logging
from datetime import datetime

from app import judges
from app.adapters import llm
from app.db import SessionLocal
from app.models import LibScript

log = logging.getLogger(__name__)
MIN_GAIN = 3
STALL_ROUNDS = 2
_stage: dict[str, str] = {}

MODES = {
    "A": "攻短板：只改和「{dim}」有关的镜头，其他镜头一个字都不要动。\n这个维度的问题：\n{issues}",
    "B": "改共识问题：只解决下面这 {n} 个被多个评委同时提到的问题，其他保持不变。\n{issues}",
    "C": ("重写结构：保留创意核心（{core}），其他都可以推翻——重新设计前 2 秒的画面钩子、反转的位置和整体结构，镜头数可以变。"
          "评委对现在这版的主要意见（参考，不用逐条照改）：\n{issues}"),
}
LABELS = {"A": "攻短板", "B": "改共识问题", "C": "重写结构"}


def _issue_lines(items: list[dict]) -> str:
    return "\n".join(f"- {'镜 ' + str(i['shot']) if i['shot'] else '整体'}（{i['count']} 个评委）：{i['problem']}" + (f" → {i['fix']}" if i["fix"] else "")
                     for i in items) or "- （没有具体问题）"


def instructions(jd: dict, concept: dict) -> dict[str, str]:
    dims = jd.get("dims") or {}
    low_key = min(dims, key=lambda k: dims[k]["median"]) if dims else ""
    issues = jd.get("issues") or []
    low_issues = [i for i in issues if i.get("dim") == low_key][:4]
    if not low_issues and low_key:  # 评委没把问题归到这个维度：用最低分评委的理由
        d = dims[low_key]
        low_issues = [{"shot": 0, "count": 1, "problem": f"{d['low']['reason']}", "fix": ""}]
    shared = [i for i in issues if i["count"] >= 2][:2] or issues[:2]
    core = "；".join(x for x in (concept.get("logline"), concept.get("trend") and f"热点：{concept['trend']}",
                                 concept.get("product_moment") and f"卖点落地：{concept['product_moment']}") if x)
    return {"A": MODES["A"].format(dim=dims.get(low_key, {}).get("name", "最低分维度"), issues=_issue_lines(low_issues)),
            "B": MODES["B"].format(n=len(shared), issues=_issue_lines(shared)),
            "C": MODES["C"].format(core=core or "原创意", issues=_issue_lines(issues[:6]))}


async def _variant(s: LibScript, mode: str, text: str) -> list:
    from app.scriptlab import LANG, PRODUCTION, WRITE_PROMPT, _water_rule, lint_fix
    from app.wash import split_cuts
    from app.workflows import _normalize_shots
    c = s.concept or {}
    specs = c.get("specs") or ""
    user = (f"创意：{c.get('title')}｜{c.get('logline')}\n钩子：{c.get('hook')}\n反转：{c.get('twist')}\n卖点证明：{c.get('product_moment')}\n"
            f"热点：{c.get('trend') or '无'}\n\n当前剧本：{json.dumps(s.shots, ensure_ascii=False)}\n\n这次的改法：{text}")
    out = await llm.chat_json(WRITE_PROMPT.format(market=s.market, product=s.product, selling_point=s.selling_point, audience=s.audience,
                                                  lang=LANG.get(s.market, "当地常用语言"), specs=specs or "（没给）", water_rule=_water_rule(specs),
                                                  production=PRODUCTION), user, task="script", timeout=150)
    rows = [r for r in out.get("shots") or [] if isinstance(r, list) and len(r) >= 2]
    if len(rows) < 3:
        raise RuntimeError("模型写的分镜太少")
    shots, _left = await lint_fix(split_cuts(_normalize_shots(rows))[0])  # 改写出来的版本同样先过可拍性自检
    return shots


def _weighted(scores: dict, weights: dict) -> float:
    return sum(scores[k] * weights.get(k, 0) for k in judges.DIM_KEYS) / (sum(weights.values()) or 1)


def _paired(base: dict, new: dict, weights: dict) -> tuple[int, int]:
    """同一个评委（同一个模型）给新版和原版的加权分比较：返回 (给新版打分更高的评委数, 两版都打了分的评委数)。"""
    b = {r["model"]: r["scores"] for r in base.get("results") or [] if r.get("scores")}
    n = {r["model"]: r["scores"] for r in new.get("results") or [] if r.get("scores")}
    both = [m for m in n if m in b]
    return sum(1 for m in both if _weighted(n[m], weights) > _weighted(b[m], weights)), len(both)


def _brief(jd: dict) -> dict:
    return {"total": jd["total"], "verdict": jd["verdict"], "dims": {k: d["median"] for k, d in jd["dims"].items()},
            "alpha": jd.get("alpha"), "issues": jd["issues"][:5]}


async def run(sid: str) -> None:
    with SessionLocal() as db:
        s = db.get(LibScript, sid)
        jd0 = (s.evaluation or {}).get("judges")
        s.status, s.error = "improving", ""
        db.commit()
        db.expunge(s)
    try:
        if not jd0:
            _stage[sid] = "先给原版打一次分"
            jd0 = await judges.score(s)
        _stage[sid] = "写 3 个改法不同的版本"
        ins = instructions(jd0, s.concept or {})
        got = await asyncio.gather(*(_variant(s, m, ins[m]) for m in "ABC"), return_exceptions=True)
        variants = [(m, g) for m, g in zip("ABC", got) if not isinstance(g, BaseException)]
        errs = [f"{LABELS[m]}：{str(g)[:80]}" for m, g in zip("ABC", got) if isinstance(g, BaseException)]
        if not variants:
            raise RuntimeError("3 个版本都没写出来：" + "；".join(errs))
        _stage[sid] = f"原版和 {len(variants)} 个新版本一起让 5 个评委打分"
        cfg = judges.get_settings()
        scored = await asyncio.gather(judges.score(s, cfg=cfg), *(judges.score(s, shots, cfg) for _, shots in variants), return_exceptions=True)
        base = scored[0] if not isinstance(scored[0], BaseException) else jd0  # 原版这轮没打成：用上一次的分
        cands = [{"label": "原版", "mode": "", "shots": s.shots, "judges": base, **_brief(base)}]
        for (m, shots), r in zip(variants, scored[1:]):
            if isinstance(r, BaseException):
                errs.append(f"{LABELS[m]}没打成分：{str(r)[:80]}")
                continue
            cands.append({"label": LABELS[m], "mode": m, "instruction": ins[m], "shots": shots, "judges": r, **_brief(r)})
        for c in cands[1:]:
            c["prefer"], c["paired"] = _paired(base, c["judges"], cfg["weights"])
        best = max(cands[1:], key=lambda c: c["total"], default=None)
        gain = (best["total"] - base["total"]) if best else 0
        # 评分本身有几分波动：总分高 MIN_GAIN 以上，并且同一批评委里多数人各自都给新版打了更高分（配对比较），才算真的变好
        accepted = bool(best) and gain >= MIN_GAIN and best["prefer"] * 2 > best["paired"] and best["verdict"] != "不能投"
        with SessionLocal() as db:
            s = db.get(LibScript, sid)
            ev = judges.merge_eval(s.evaluation, base)
            rounds = list(ev.get("rounds") or [])
            hist = [h for h in ev.get("history") or [] if h["version"] != s.version]
            hist.append(judges.history_point(s.version, base, "改进前重新打分"))
            if accepted:
                s.version += 1
                s.shots = best["shots"]
                ev["judges"] = best["judges"]
                ev.pop("audience", None)  # 剧本换了：旧的观众模拟作废
                hist.append(judges.history_point(s.version, best["judges"], f"自动改进：{best['label']}"))
            # 连续几轮没进步：从最近一轮往前数，直到碰到采用过的那一轮
            stall = 0 if accepted else 1 + next((i for i, r in enumerate(reversed(rounds)) if r.get("accepted")), len(rounds))
            rounds.append({"at": datetime.utcnow().isoformat(), "base_version": s.version - (1 if accepted else 0), "base_total": base["total"],
                           "accepted": accepted, "gain": gain, "winner": best["label"] if accepted else "原版",
                           "candidates": cands,
                           "errors": errs, "stall": stall, "min_gain": MIN_GAIN})
            # 只有最近一轮保留每个版本的完整评委结果（手动采用时直接用），更早的只留摘要，免得越存越大
            ev["rounds"] = [{**r, "candidates": [{k: v for k, v in c.items() if k != "judges"} for c in r["candidates"]]} for r in rounds[:-1]][-9:] + rounds[-1:]
            ev["history"] = hist[-20:]
            s.evaluation, s.status = ev, "ok"
            s.error = "" if accepted else (f"这一轮没改出更好的（最好的「{best['label']}」{best['total']} 分，原版 {base['total']} 分；要总分高 {MIN_GAIN} 分以上、"
                                           f"并且多数评委都给新版打了更高分才采用，这次是 {best['prefer']}/{best['paired']} 个评委），保留原版"
                                           if best else "没有可用的新版本") + ("；已经连续 2 轮没进步，这个创意可能到顶了，建议换一个备选创意" if stall >= STALL_ROUNDS else "")
            db.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("剧本自动改进失败 %s", sid)
        with SessionLocal() as db:
            s = db.get(LibScript, sid)
            s.status, s.error = "ok", f"自动改进失败：{str(e)[:300]}"
            db.commit()
    finally:
        _stage.pop(sid, None)


def adopt(sid: str, round_idx: int, cand_idx: int) -> dict:
    """手动采用某一轮里的某个版本。"""
    with SessionLocal() as db:
        s = db.get(LibScript, sid)
        ev = judges.merge_eval(s.evaluation, (s.evaluation or {}).get("judges"))
        rounds = ev.get("rounds") or []
        try:
            c = rounds[round_idx]["candidates"][cand_idx]
        except (IndexError, TypeError):
            raise ValueError("没有这个版本") from None
        if c["shots"] == s.shots:
            return {"ok": True, "unchanged": True}
        s.version += 1
        s.shots = c["shots"]
        if c.get("judges"):
            ev["judges"] = c["judges"]
        else:  # 更早的轮次只存了摘要：详细评委结果要重新打分
            ev.pop("judges", None)
        ev.pop("audience", None)
        ev["history"] = [*(ev.get("history") or []), {"version": s.version, "total": c["total"], "verdict": c["verdict"], "dims": c["dims"],
                                                       "how": f"手动采用：{c['label']}", "at": datetime.utcnow().isoformat()}][-20:]
        s.evaluation, s.error = ev, ""
        db.commit()
    return {"ok": True}
