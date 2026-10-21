"""剧本评审：5 个不同的大模型当评委，每个评委都按同样 5 个维度给同一个剧本打分（LLM-as-a-judge 多评委）。

- 5 个维度（权重可改）：钩子与节奏 30% · 本地化 25% · 卖点表达 20% · 可拍性 15% · 合规安全 10%
- 所有评委用同一份提示词和评分细则，盲评（不知道谁写的、看不到别人的分）；评委里不放写剧本的模型家族（默认 Claude）
- 维度得分 = 5 个评委的中位数（不被单个极端分带偏）；总分 = Σ 维度中位数 × 权重 × 10，满分 100
- 一致性：每个维度的标准差 ≥ 2 标「评委分歧大」；整体用 Krippendorff's α（区间尺度）
- 合规兜底：≥ 2 个评委合规打 ≤ 3 分 → 不能投；可拍性中位数 ≤ 4 → 最多「改了再用」
- 问题清单按镜号合并，被多个评委同时提到的排前面
评委调用失败重试一次，还失败就换备用模型；少于 3 个评委成功则整次评审作废。
"""
import asyncio
import logging
import statistics
from datetime import datetime

from app import settings_store
from app.adapters import llm
from app.db import SessionLocal
from app.models import LibScript, Setting

log = logging.getLogger(__name__)

DIMS = [  # (key, 名字, 默认权重, 评什么, 评分锚点)
    ("hook", "钩子与节奏", 0.30, "前 2 秒能不能让人停下、反转有没有力、节奏会不会拖",
     "9–10 不看字幕也能让人停下，反转出乎意料；5 和普通手机广告开头差不多；1–3 开头就在介绍产品或者没事发生"),
    ("local", "本地化", 0.25, "像不像当地人的生活、梗和口语用得对不对、有没有文化冒犯",
     "9–10 当地人会说「这就是我们」，梗和口语地道；5 换个国家也能用；1–3 用错梗、口语别扭或冒犯"),
    ("selling", "卖点表达", 0.20, "卖点是不是剧情的反转 / 笑点本身、看完记不记得住、可不可信",
     "9–10 卖点就是笑点 / 反转，看完记得住；5 结尾硬塞一句卖点；1–3 看不出在卖什么或明显不可信"),
    ("feasible", "可拍性", 0.15, "能不能用 AI 视频生成拍出来：人物数、动作复杂度、一镜一景别、手机朝向清楚、角色前后一致",
     "9–10 每镜都能直接生成；5 有 1–2 镜要简化；1–3 大场面群戏、复杂特技或镜头描述含糊"),
    ("safe", "合规安全", 0.10, "有没有编参数 / 夸大宣传、危险动作可被模仿、宗教民族敏感、贬低竞品、未成年人问题",
     "9–10 没有风险；5 有小问题要改；1–3 不能投放"),
]
DIM_KEYS = [d[0] for d in DIMS]
DEFAULT_JUDGES = ["openai/gpt-6.1-sol", "google/gemini-3.8-flash", "x-ai/grok-4.7", "deepseek/deepseek-v4-pro-0813", "qwen/qwen3.8-max-0902"]
FALLBACKS = ["google/gemini-2.5-flash", "openai/gpt-6-luna", "deepseek/deepseek-v4.1-flash"]
SPREAD_WARN = 2.0
MIN_JUDGES = 3

PROMPT = """你是短视频广告评审，给一条 TikTok 手机广告剧本打分。只看剧本本身，按标准严格打分，不要客气，也不要配合任何人。
市场：{market}；产品：{product}；卖点：{selling_point}；目标人群：{audience}；已知参数：{specs}
按 5 个维度各打 1–10 的整数分，每个维度的标准：
{rubric}
参照尺子：普通的、千篇一律的手机广告各维度大约 5 分；本地爆款级别的才给 9 分以上。
只输出 JSON：
{{"scores": {{{keys}}},
 "reasons": {{每个维度一句理由，键同上}},
 "evidence": {{每个维度引用的镜号和原文片段，如 "镜 1：……"，键同上}},
 "issues": [{{"shot": 镜号（整体问题写 0）, "dim": "维度键", "problem": "问题", "fix": "具体改法", "severity": "high/mid/low"}}],
 "highlights": ["值得保留的地方"],
 "confidence": "high/mid/low"}}"""


# ---------- 并发：有截止时间，够数就不等最慢的 ----------

async def gather_quorum(coros: list, deadline: float, enough: int) -> list:
    """并发跑完 coros；到 deadline 秒时，只要已经有 enough 个成功就取消还没回来的（结果记为 TimeoutError），不够就再等到全部结束。
    返回值顺序和 coros 一致，失败的是异常对象。"""
    tasks = [asyncio.ensure_future(c) for c in coros]
    done, pending = await asyncio.wait(tasks, timeout=deadline)
    ok = sum(1 for t in done if not t.cancelled() and t.exception() is None and t.result() not in (None, {}) and "error" not in (t.result() if isinstance(t.result(), dict) else {}))
    if pending and ok >= enough:
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    elif pending:
        await asyncio.wait(pending)
    out = []
    for t in tasks:
        if t.cancelled():
            out.append(asyncio.TimeoutError(f"超过 {deadline:g} 秒没回来，已跳过"))
        elif t.exception() is not None:
            out.append(t.exception())
        else:
            out.append(t.result())
    return out


DEADLINE = 120  # 正式打分：120 秒时够 3 个评委就不等慢的
CONCEPT_DEADLINE = 150


# ---------- 设置 ----------

def get_settings() -> dict:
    with SessionLocal() as db:
        s = db.get(Setting, "judges")
        v = (s.value if s else {}) or {}
    weights = {k: float((v.get("weights") or {}).get(k, w)) for k, _, w, _, _ in DIMS}
    return {"models": list(v.get("models") or DEFAULT_JUDGES)[:7], "weights": weights, "double": bool(v.get("double", False)),
            "dims": [{"key": k, "name": n, "weight": weights[k], "what": what, "anchor": a} for k, n, _, what, a in DIMS]}


def set_settings(values: dict) -> dict:
    cur = get_settings()
    models = [m.strip() for m in values.get("models") or cur["models"] if isinstance(m, str) and m.strip()][:7]
    if len(models) < MIN_JUDGES:
        raise ValueError(f"至少要 {MIN_JUDGES} 个评委模型")
    w = {k: max(0.0, float((values.get("weights") or {}).get(k, cur["weights"][k]))) for k in DIM_KEYS}
    if sum(w.values()) <= 0:
        raise ValueError("权重不能全是 0")
    with SessionLocal() as db:
        s = db.get(Setting, "judges") or Setting(key="judges", value={})
        s.value = {"models": models, "weights": w, "double": bool(values.get("double", cur["double"]))}
        db.merge(s)
        db.commit()
    return get_settings()


# ---------- 单个评委 ----------

def _prompt(s: LibScript, shots: list | None = None) -> tuple[str, str]:
    rubric = "\n".join(f"- {k}（{n}）：{what}。{a}" for k, n, _, what, a in DIMS)
    system = PROMPT.format(market=s.market, product=s.product, selling_point=s.selling_point, audience=s.audience,
                           specs=(s.concept or {}).get("specs") or "（没给，剧本里出现的任何参数数字都算编造）", rubric=rubric,
                           keys=", ".join(f'"{k}": 1-10' for k in DIM_KEYS))
    c = s.concept or {}
    rows = s.shots if shots is None else shots
    text = "\n".join(f"镜 {i + 1}（{x[0]}）画面：{x[1]}｜口播：{x[2] if len(x) > 2 else ''}｜中文：{x[3] if len(x) > 3 else ''}" for i, x in enumerate(rows or []))
    user = (f"创意：{c.get('logline', '')}\n钩子：{c.get('hook', '')}\n反转：{c.get('twist', '')}\n卖点怎么落地：{c.get('product_moment', '')}\n"
            f"借的热点：{c.get('trend') or '无'}\n\n剧本（{len(rows or [])} 镜）：\n{text}")
    return system, user


def _clean(out: dict, n_shots: int) -> dict | None:
    sc = out.get("scores") or {}
    scores = {}
    for k in DIM_KEYS:
        try:
            scores[k] = max(1, min(10, int(round(float(sc.get(k))))))
        except (TypeError, ValueError):
            return None  # 少了维度：这次回答不算
    issues = []
    for it in out.get("issues") or []:
        if not isinstance(it, dict) or not it.get("problem"):
            continue
        try:
            shot = int(it.get("shot") or 0)
        except (TypeError, ValueError):
            shot = 0
        issues.append({"shot": shot if 0 <= shot <= n_shots else 0, "dim": it.get("dim") if it.get("dim") in DIM_KEYS else "",
                       "problem": str(it["problem"])[:200], "fix": str(it.get("fix") or "")[:200],
                       "severity": it.get("severity") if it.get("severity") in ("high", "mid", "low") else "mid"})
    txt = lambda d: {k: str((d or {}).get(k) or "")[:200] for k in DIM_KEYS}  # noqa: E731
    return {"scores": scores, "reasons": txt(out.get("reasons")), "evidence": txt(out.get("evidence")), "issues": issues[:12],
            "highlights": [str(h)[:150] for h in out.get("highlights") or []][:5],
            "confidence": out.get("confidence") if out.get("confidence") in ("high", "mid", "low") else "mid"}


async def _ask(model: str, system: str, user: str, n_shots: int) -> dict:
    msg = await llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True, task="eval", model=model, timeout=120)
    res = _clean(llm.parse_json(msg.get("content") or ""), n_shots)
    if not res:
        raise ValueError("回答里缺维度分数")
    return res


async def judge_one(model: str, system: str, user: str, n_shots: int, double: bool, used: set[str]) -> dict:
    """一个评委：失败重试一次，再失败换备用模型（不和已有评委重复）。返回结果或 {error}。"""
    t0 = datetime.utcnow()
    tried, last = [], ""
    for k in range(4):
        if k < 2:
            m = model
        else:  # 换备用模型：当场占住，免得两个失败的评委换成同一个备用模型（那就成了一个评委算两票）
            m = next((f for f in FALLBACKS if f not in used), None)
            if not m:
                break
            used.add(m)
        tried.append(m)
        try:
            runs = [await _ask(m, system, user, n_shots)]
            if double:
                try:
                    runs.append(await _ask(m, system, user, n_shots))
                except Exception:  # noqa: BLE001  第二次失败就只用一次的
                    pass
            r = runs[0]
            if len(runs) > 1:
                r = {**r, "scores": {k: round(sum(x["scores"][k] for x in runs) / len(runs), 1) for k in DIM_KEYS}, "samples": len(runs)}
            return {**r, "model": m, "requested": model, "fallback": m != model, "seconds": round((datetime.utcnow() - t0).total_seconds(), 1)}
        except Exception as e:  # noqa: BLE001
            last = str(e)[:160] or type(e).__name__
            log.info("评委 %s 失败：%s", m, last)
    return {"model": model, "error": last or "调用失败", "tried": tried}


# ---------- 汇总 ----------

def kripp_alpha(rows: list[list[float]]) -> float | None:
    """Krippendorff's α（区间尺度）。rows：每个维度一行，行里是各评委的分。"""
    units = [r for r in rows if len(r) >= 2]
    vals = [v for r in units for v in r]
    n = len(vals)
    if n < 4 or len(set(vals)) < 2:
        return None
    do = sum(sum((a - b) ** 2 for i, a in enumerate(r) for j, b in enumerate(r) if i != j) / (len(r) - 1) for r in units) / n
    de = sum((a - b) ** 2 for i, a in enumerate(vals) for j, b in enumerate(vals) if i != j) / (n * (n - 1))
    return round(1 - do / de, 2) if de else None


def _key(problem: str) -> str:
    return "".join(ch for ch in problem.lower() if ch.isalnum())[:12]


def aggregate(results: list[dict], weights: dict) -> dict:
    ok = [r for r in results if "scores" in r]
    dims = {}
    for k, name, _, _, _ in DIMS:
        vals = [r["scores"][k] for r in ok]
        med = statistics.median(vals)
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        hi = max(ok, key=lambda r: r["scores"][k])
        lo = min(ok, key=lambda r: r["scores"][k])
        dims[k] = {"name": name, "median": med, "mean": round(statistics.mean(vals), 1), "std": round(sd, 1), "scores": vals,
                   "split": sd >= SPREAD_WARN,
                   "high": {"model": hi["model"], "score": hi["scores"][k], "reason": hi["reasons"].get(k, "")},
                   "low": {"model": lo["model"], "score": lo["scores"][k], "reason": lo["reasons"].get(k, "")}}
    wsum = sum(weights.values()) or 1
    total = round(sum(dims[k]["median"] * weights[k] for k in DIM_KEYS) / wsum * 10)
    unsafe = sum(1 for r in ok if r["scores"]["safe"] <= 3)
    if unsafe >= 2:
        verdict, why = "不能投", f"{unsafe} 个评委认为有合规风险（合规 ≤ 3 分）"
    elif dims["feasible"]["median"] <= 4:
        verdict, why = "改了再用", "可拍性不够（中位数 ≤ 4）：拍不出来的剧本再好也没用"
    elif total >= 75:
        verdict, why = "可以投", ""
    elif total >= 60:
        verdict, why = "改了再用", ""
    else:
        verdict, why = "不能投", "总分低于 60"
    # 问题按镜号合并：同一镜、同一维度的算一类，被几个评委提到
    groups: dict[tuple, dict] = {}
    for r in ok:
        for it in r["issues"]:
            g = groups.setdefault((it["shot"], it["dim"] or _key(it["problem"])), {"shot": it["shot"], "dim": it["dim"], "items": [], "judges": set()})
            g["items"].append({**it, "model": r["model"]})
            g["judges"].add(r["model"])
    sev = {"high": 0, "mid": 1, "low": 2}
    issues = sorted(({"shot": g["shot"], "dim": g["dim"], "count": len(g["judges"]), "problem": g["items"][0]["problem"],
                      "fix": next((x["fix"] for x in g["items"] if x["fix"]), ""), "severity": min((x["severity"] for x in g["items"]), key=sev.get),
                      "details": [{"model": x["model"], "problem": x["problem"], "fix": x["fix"]} for x in g["items"]]} for g in groups.values()),
                    key=lambda x: (-x["count"], sev[x["severity"]], x["shot"]))
    alpha = kripp_alpha([[r["scores"][k] for r in ok] for k in DIM_KEYS])
    return {"total": total, "verdict": verdict, "verdict_why": why, "dims": dims, "alpha": alpha,
            "reliable": alpha is None or alpha >= 0.4, "issues": issues[:15],
            "highlights": list(dict.fromkeys(h for r in ok for h in r["highlights"]))[:6]}


async def score(s: LibScript, shots: list | None = None, cfg: dict | None = None) -> dict:
    """给一个剧本（或它的一个改写版本 shots）打一轮分，返回汇总结果。评委不够就抛错。不写库。"""
    cfg = cfg or get_settings()
    system, user = _prompt(s, shots)
    n_shots = len((s.shots if shots is None else shots) or [])
    used = set(cfg["models"])
    got = await gather_quorum([judge_one(m, system, user, n_shots, cfg["double"], used) for m in cfg["models"]], DEADLINE, MIN_JUDGES + 1)
    results = [g if isinstance(g, dict) else {"model": m, "error": str(g)[:160] or type(g).__name__} for m, g in zip(cfg["models"], got)]
    ok = [r for r in results if "scores" in r]
    if len(ok) < MIN_JUDGES:
        raise RuntimeError(f"只有 {len(ok)} 个评委打完分（至少要 {MIN_JUDGES} 个）：" + "；".join(f"{r['model']} {r.get('error')}" for r in results if "error" in r)[:300])
    return {**aggregate(results, cfg["weights"]), "results": results, "weights": cfg["weights"], "at": datetime.utcnow().isoformat(),
            "note": f"{len(ok)} 个不同的大模型各自按同样 5 个维度打分；维度取中位数，再按权重算总分"}


KEEP_KEYS = ("audience", "previous", "history", "rounds")


def merge_eval(cur: dict | None, judges: dict | None = None) -> dict:
    """更新评测：保留观众模拟、版本轨迹、改进记录，换上新的评委结果。"""
    cur = dict(cur or {})
    if cur and not ({"judges", *KEEP_KEYS} & set(cur)):  # 老数据：整份就是 40 人评测，挪到 audience 下
        cur = {"audience": cur}
    ev = {k: cur[k] for k in KEEP_KEYS if k in cur}
    if judges is not None:
        ev["judges"] = judges
    return ev


def history_point(version: int, jd: dict, how: str) -> dict:
    return {"version": version, "total": jd["total"], "verdict": jd["verdict"], "dims": {k: d["median"] for k, d in jd["dims"].items()},
            "how": how, "at": jd["at"]}


async def run(sid: str) -> None:
    with SessionLocal() as db:
        s = db.get(LibScript, sid)
        s.status = "judging"
        db.commit()
        db.expunge(s)
    try:
        jd = await score(s)
        with SessionLocal() as db:
            s = db.get(LibScript, sid)
            ev = merge_eval(s.evaluation, jd)
            hist = [h for h in ev.get("history") or [] if h["version"] != s.version]
            ev["history"] = [*hist, history_point(s.version, jd, "重新打分")][-20:]
            s.evaluation, s.status, s.error = ev, "ok", ""
            db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("剧本评审失败 %s：%s", sid, e)
        with SessionLocal() as db:
            s = db.get(LibScript, sid)
            s.status, s.error = "ok", f"评委打分失败：{str(e)[:300]}"
            db.commit()


def rewrite_comment(judges: dict, top: int = 6) -> str:
    """评委汇总的问题 → 给编剧模型的改写意见。"""
    lines = []
    for it in (judges.get("issues") or [])[:top]:
        where = f"镜 {it['shot']}" if it["shot"] else "整体"
        lines.append(f"{where}（{it['count']} 个评委提到）：{it['problem']}" + (f" → 改法：{it['fix']}" if it["fix"] else ""))
    low = sorted(judges.get("dims", {}).items(), key=lambda kv: kv[1]["median"])[:2]
    if low:
        lines.append("得分最低的维度：" + "、".join(f"{v['name']} {v['median']} 分（{v['low']['reason']}）" for _, v in low))
    return "按评委意见改：\n" + "\n".join(f"- {x}" for x in lines) + ("\n保留：" + "；".join(judges.get("highlights") or []) if judges.get("highlights") else "")


# ---------- 创意阶段：5 个评委批量给创意打分（锦标赛初筛） ----------

CONCEPT_PROMPT = """你是短视频广告评审，给一批 TikTok 手机广告的「创意」打分（还没写成分镜，只看创意本身能不能成爆款）。
市场：{market}；产品：{product}；卖点：{selling_point}；目标人群：{audience}
按 5 个维度各打 1–10 的整数分：
{rubric}
可拍性按「最多 2 个主要人物露脸、动作简单、屏幕不出现界面」的 AI 生成流程判断。
参照尺子：普通的手机广告创意各维度大约 5 分；只有本地爆款级别的才给 9 分以上。要拉开差距，不要都给 7 分。
只输出 JSON：{{"scores": [{{"i": 创意编号, {keys}}}, ...每个创意一条]}}"""
CONCEPT_BATCH = 20


async def score_concepts(ideas: list[dict], ctx: dict, cfg: dict | None = None) -> list[dict]:
    """ideas：[{title, logline, hook, twist, product_moment, trend}]。返回每个创意的 {dims 中位数, total, judges 数}。"""
    cfg = cfg or get_settings()
    rubric = "\n".join(f"- {k}（{n}）：{what}。{a}" for k, n, _, what, a in DIMS)
    system = CONCEPT_PROMPT.format(rubric=rubric, keys=", ".join(f'"{k}": 1-10' for k in DIM_KEYS), **ctx)
    batches = [list(range(i, min(len(ideas), i + CONCEPT_BATCH))) for i in range(0, len(ideas), CONCEPT_BATCH)]

    async def one(model: str, idx: list[int]) -> dict[int, dict]:
        listing = "\n".join(f"{i + 1}. {ideas[i].get('title')}：{ideas[i].get('logline')}｜前 2 秒：{ideas[i].get('hook')}｜反转：{ideas[i].get('twist')}"
                             f"｜卖点怎么落地：{ideas[i].get('product_moment')}" + (f"｜热点：{ideas[i]['trend']}" if ideas[i].get("trend") else "") for i in idx)
        for _ in range(2):
            try:
                msg = await llm.chat([{"role": "system", "content": system}, {"role": "user", "content": listing}], json_mode=True, task="eval",
                                     model=model, timeout=150)
                out = {}
                for r in llm.parse_json(msg.get("content") or "").get("scores") or []:
                    try:
                        i = int(r.get("i")) - 1
                        if i in idx:
                            out[i] = {k: max(1, min(10, int(round(float(r[k]))))) for k in DIM_KEYS}
                    except (TypeError, ValueError, KeyError):
                        continue
                if out:
                    return out
            except Exception as e:  # noqa: BLE001
                log.info("创意打分 %s 失败：%s", model, e)
        return {}

    got = await gather_quorum([one(m, b) for m in cfg["models"] for b in batches], CONCEPT_DEADLINE, (MIN_JUDGES + 1) * len(batches))
    per: dict[int, list[dict]] = {}
    for g in got:
        if not isinstance(g, dict):
            continue
        for i, sc in g.items():
            per.setdefault(i, []).append(sc)
    wsum = sum(cfg["weights"].values()) or 1
    res = []
    for i in range(len(ideas)):
        rows = per.get(i) or []
        if len(rows) < MIN_JUDGES:
            res.append({"dims": {}, "total": 0, "judges": len(rows)})
            continue
        dims = {k: statistics.median(r[k] for r in rows) for k in DIM_KEYS}
        res.append({"dims": dims, "total": round(sum(dims[k] * cfg["weights"][k] for k in DIM_KEYS) / wsum * 10), "judges": len(rows),
                    "spread": round(statistics.pstdev([sum(r[k] * cfg["weights"][k] for k in DIM_KEYS) / wsum * 10 for r in rows]), 1)})
    return res

