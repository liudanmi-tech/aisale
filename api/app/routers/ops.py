"""爆款库、节点详情编辑、审核、投放、数据、资产与设置。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import agent, canvas, config, settings_store, workflows
from app.adapters import llm
from app.db import SessionLocal, get_db
from app.events import emit, spawn
from app.models import Audience, MetricDaily, Node, Project, RefAd, ReviewTask, SellingPoint

router = APIRouter(prefix="/api/v1")


def ad_dict(a: RefAd) -> dict:
    return {"id": a.id, "no": a.no, "source": a.source, "platform": a.platform, "brand": a.brand, "market": a.market,
            "title": a.title, "hook": a.hook, "selling_point": a.selling_point, "days_running": a.days_running,
            "variants": a.variants, "ctr_range": a.ctr_range, "vtr": a.vtr, "is_estimated": a.is_estimated,
            "hot_score": a.hot_score, "dna": a.dna}


@router.get("/ref-ads")
def ref_ads(market: str | None = None, selling_point: str | None = None, db: Session = Depends(get_db)):
    q = db.query(RefAd)
    if market:
        q = q.filter(RefAd.market == market)
    if selling_point:
        q = q.filter(RefAd.selling_point == selling_point)
    return [ad_dict(a) for a in q.order_by(RefAd.hot_score.desc())]


@router.get("/ref-ads/{no}")
def ref_ad(no: int, db: Session = Depends(get_db)):
    a = db.query(RefAd).filter(RefAd.no == no).first()
    if not a:
        raise HTTPException(404, "not found")
    return ad_dict(a)


@router.get("/nodes/{nid}")
def get_node(nid: str, db: Session = Depends(get_db)):
    n = db.get(Node, nid)
    if not n:
        raise HTTPException(404, "node not found")
    r = db.query(ReviewTask).filter(ReviewTask.node_id == nid, ReviewTask.status == "wait").first()
    return {**canvas.node_dict(n), "project_id": n.project_id, "review_id": r.id if r else None,
            "upstream": [canvas.node_dict(u) for u in canvas.upstream(db, nid)]}


class RewriteIn(BaseModel):
    hint: str = ""


ALT_LINES = ["Light off for 2 days? This phone no dey die!", "Customer dey wait, phone still dey work!", "One charge, full market day."]


@router.post("/nodes/{nid}/shots/{i}/rewrite")
async def rewrite_shot(nid: str, i: int, body: RewriteIn, db: Session = Depends(get_db)):
    n = db.get(Node, nid)
    if not n or n.type != "script":
        raise HTTPException(404, "script not found")
    shots = [s[:] for s in n.data.get("shots", [])]
    if not 0 <= i < len(shots):
        raise HTTPException(400, "bad shot index")
    line, zh = ALT_LINES[(n.data.get("version", 1) + i) % 3], body.hint or "换了一个更口语的说法"
    if settings_store.llm_enabled():
        try:
            out = await llm.chat_json("你是尼日利亚市场的广告编剧，只输出 JSON：{\"line\": 皮钦英语口播, \"zh\": 中文对照}",
                                      f"原镜头：{shots[i]}；修改要求：{body.hint or '更口语、更抓人'}")
            line, zh = out.get("line", line), out.get("zh", zh)
        except Exception:
            pass
    shots[i][2], shots[i][3] = line, zh
    n.data = {**n.data, "shots": shots}
    canvas.bump(db.get(Project, n.project_id))
    canvas.audit(db, n.project_id, "agent", "rewrite_shot", {"node_id": nid, "shot": i})
    db.commit()
    emit(n.project_id, "canvas")
    return canvas.node_dict(n)


@router.post("/nodes/{nid}/shots/{i}/regenerate")
def regenerate_shot(nid: str, i: int, db: Session = Depends(get_db)):
    n = db.get(Node, nid)
    if not n or n.type != "video":
        raise HTTPException(404, "video not found")
    tasks = [t.copy() for t in (n.data or {}).get("tasks", [])]
    if not 0 <= i < len(tasks) or tasks[i].get("source") == "official":
        raise HTTPException(400, "该镜头不能重生成")
    tasks[i] = {**tasks[i], "status": "processing", "error": None}
    n.data = {**n.data, "tasks": tasks}
    db.commit()
    spawn(_regen(nid, i, tasks[i].get("prompt") or f"{n.data['shots'][i][1]}。{workflows.VIDEO_STYLE}"))
    return {"ok": True}


async def _regen(nid: str, i: int, prompt: str) -> None:
    res = await workflows._gen_shot(prompt)
    with SessionLocal() as db:
        n = db.get(Node, nid)
        if not n:
            return
        tasks = [t.copy() for t in n.data.get("tasks", [])]
        tasks[i] = {**tasks[i], **res, "url": res.get("video_url"), "prompt": prompt}
        urls = [t["url"] for t in tasks if (t.get("url") or "").startswith("http")]
        n.data = {**n.data, "tasks": tasks, "shot_urls": urls, "video_url": urls[0] if urls else n.data.get("video_url")}
        if n.status == "failed" and all(t.get("status") == "completed" for t in tasks):
            n.status = "wait"
        db.commit()
        emit(n.project_id, "canvas")


@router.get("/reviews")
def reviews(status: str | None = None, project_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(ReviewTask)
    if status:
        q = q.filter(ReviewTask.status == status)
    if project_id:
        q = q.filter(ReviewTask.project_id == project_id)
    return [{"id": r.id, "project_id": r.project_id, "node_id": r.node_id, "module": r.module, "title": r.title,
             "conclusion": r.conclusion, "evidence": r.evidence, "status": r.status, "comment": r.comment,
             "created_at": r.created_at.isoformat(), "decided_at": r.decided_at.isoformat() if r.decided_at else None}
            for r in q.order_by(ReviewTask.created_at.desc())]


class DecideIn(BaseModel):
    decision: str  # pass | reject | edit_pass
    comment: str = ""


NEXT_HINT = {"script": "下一步可以说「生成视频」。", "video": "下一步可以说「跑评测」。", "eval": "下一步可以说「生成投放方案」。",
             "deliver": "去投放中心点击「下发到 TikTok」。", "opt": ""}


@router.post("/reviews/{rid}/decide")
def decide(rid: str, body: DecideIn, db: Session = Depends(get_db)):
    r = db.get(ReviewTask, rid)
    if not r or r.status != "wait":
        raise HTTPException(409, "review is not pending")
    if body.decision == "reject" and not body.comment.strip():
        raise HTTPException(400, "驳回需要填写理由")
    n, project = db.get(Node, r.node_id), db.get(Project, r.project_id)
    r.status = "reject" if body.decision == "reject" else "pass"
    r.comment, r.decided_at = body.comment or ("修改后通过" if body.decision == "edit_pass" else ""), datetime.utcnow()
    canvas.audit(db, r.project_id, "user", "review_" + r.status, {"review_id": rid, "node_id": r.node_id, "comment": body.comment})
    rework = False
    if n and r.status == "pass":
        n.status = "pass"
        if n.type == "script":
            project.flags = {**(project.flags or {}), "script_passed": True}
        agent.say(db, project.id, f"{agent.ref(n)} 已通过审核。{NEXT_HINT.get(n.type, '')}")
        if n.type == "opt":
            agent.compile_iterate(db, project, n)
            agent.say(db, project.id, f"已采纳优化建议。闭环第二轮：基于跑赢元素生成 2 个剧本变体，连到 {agent.ref(n)}，确认后执行。")
    elif n:
        n.status = "run"
        rework = True
        agent.say(db, project.id, f"{agent.ref(n)} 被驳回：「{body.comment}」。我会把意见作为输入重做，完成后重新提交审核。")
    db.commit()
    if rework:
        workflows.rework(n, body.comment)
    for k in ("canvas", "chat", "reviews"):
        emit(r.project_id, k)
    return {"ok": True}


@router.get("/projects/{pid}/delivery")
def delivery(pid: str, db: Session = Depends(get_db)):
    out = []
    for n in canvas.nodes_of(db, pid, "deliver"):
        r = db.query(ReviewTask).filter(ReviewTask.node_id == n.id, ReviewTask.status == "wait").first()
        titles = {x.id: x.title for x in canvas.nodes_of(db, pid)}
        plan = (n.data or {}).get("plan")
        out.append({**canvas.node_dict(n), "review_id": r.id if r else None,
                    "creative_titles": [titles.get(c, c) for c in (plan or {}).get("creatives", [])]})
    return out


@router.post("/nodes/{nid}/launch")
def launch(nid: str, db: Session = Depends(get_db)):
    n = db.get(Node, nid)
    if not n or n.type != "deliver":
        raise HTTPException(404, "delivery not found")
    if n.status != "pass" or (n.data or {}).get("launching"):
        raise HTTPException(409, "投放方案需审核通过且未下发")
    n.data = {**n.data, "launching": True, "log": []}
    canvas.audit(db, n.project_id, "user", "launch", {"node_id": nid})
    db.commit()
    spawn(workflows.launch(nid))
    return {"ok": True}


SAMPLE_DAILY = [(320, 2.6), (410, 2.4), (480, 2.2), (560, 2.0), (610, 1.9), (590, 1.95), (650, 1.86)]


@router.get("/projects/{pid}/metrics")
def metrics(pid: str, db: Session = Depends(get_db)):
    rows = db.query(MetricDaily).filter(MetricDaily.project_id == pid).all()
    titles = {n.id: n.title for n in canvas.nodes_of(db, pid)}
    heat = [{"hook": "对比实测", "小商贩": 1.32, "学生": 1.05}, {"hook": "痛点提问", "小商贩": 1.18, "学生": 0.86},
            {"hook": "开箱", "小商贩": 0.92, "学生": 1.12}, {"hook": "故事剧情", "小商贩": 1.08, "学生": 1.21}]
    if not rows:
        return {"sample": True, "kpis": {"spend": 3620, "impressions": 1820000, "ctr": 2.03, "vtr": 31.8, "cpa": 1.86},
                "daily": [{"day": f"D{i + 1}", "spend": s, "cpa": c} for i, (s, c) in enumerate(SAMPLE_DAILY)],
                "ranking": [], "heatmap": heat, "calibration": None}
    days: dict[str, dict] = {}
    by: dict[str, dict] = {}
    for r in rows:
        d = days.setdefault(r.day, {"spend": 0, "conv": 0})
        d["spend"] += r.spend; d["conv"] += r.conversions
        a = by.setdefault(r.creative_node_id, {"spend": 0, "imp": 0, "clicks": 0, "completes": 0, "conv": 0})
        a["spend"] += r.spend; a["imp"] += r.impressions; a["clicks"] += r.clicks; a["completes"] += r.completes; a["conv"] += r.conversions
    tot = {k: sum(a[k] for a in by.values()) for k in ("spend", "imp", "clicks", "completes", "conv")}
    ranking = sorted(({"id": k, "title": titles.get(k, k), "spend": round(a["spend"], 2), "ctr": round(a["clicks"] / a["imp"] * 100, 2),
                       "vtr": round(a["completes"] / a["imp"] * 100, 1), "cpa": round(a["spend"] / max(1, a["conv"]), 2)}
                      for k, a in by.items()), key=lambda x: -x["ctr"])
    preds = {r["id"]: r["ctr"] for e in canvas.nodes_of(db, pid, "eval") for r in (e.data or {}).get("results", [])}
    pairs = [(preds[x["id"]], x["ctr"]) for x in ranking if x["id"] in preds]
    return {"sample": False,
            "kpis": {"spend": round(tot["spend"]), "impressions": tot["imp"], "ctr": round(tot["clicks"] / tot["imp"] * 100, 2),
                     "vtr": round(tot["completes"] / tot["imp"] * 100, 1), "cpa": round(tot["spend"] / max(1, tot["conv"]), 2)},
            "daily": [{"day": k[5:], "spend": round(v["spend"]), "cpa": round(v["spend"] / max(1, v["conv"]), 2)} for k, v in sorted(days.items())],
            "ranking": ranking, "heatmap": heat, "calibration": _spearman(pairs)}


def _spearman(pairs: list[tuple[float, float]]) -> dict | None:
    if len(pairs) < 2:
        return {"n": len(pairs), "rho": None}
    rank = lambda xs: {i: r for r, i in enumerate(sorted(range(len(xs)), key=lambda i: xs[i]))}  # noqa: E731
    a, b = rank([p[0] for p in pairs]), rank([p[1] for p in pairs])
    n = len(pairs)
    d2 = sum((a[i] - b[i]) ** 2 for i in range(n))
    return {"n": n, "rho": round(1 - 6 * d2 / (n * (n * n - 1)), 2)}


@router.get("/projects/{pid}/optimizations")
def optimizations(pid: str, db: Session = Depends(get_db)):
    out = []
    for n in canvas.nodes_of(db, pid, "opt"):
        r = db.query(ReviewTask).filter(ReviewTask.node_id == n.id, ReviewTask.status == "wait").first()
        out.append({**canvas.node_dict(n), "review_id": r.id if r else None})
    return out


@router.get("/creatives")
def creatives(status: str | None = None, q: str | None = None, db: Session = Depends(get_db)):
    """素材作品墙：所有项目里的视频素材，附投放实测或评测预测指标。"""
    projects = {p.id: p for p in db.query(Project)}
    preds = {}
    for e in db.query(Node).filter(Node.type == "eval"):
        for r in (e.data or {}).get("results", []):
            preds[r["id"]] = r
    actual: dict[str, dict] = {}
    for m in db.query(MetricDaily):
        a = actual.setdefault(m.creative_node_id, {"imp": 0, "clicks": 0, "completes": 0})
        a["imp"] += m.impressions; a["clicks"] += m.clicks; a["completes"] += m.completes
    out = []
    for v in db.query(Node).filter(Node.type == "video").order_by(Node.created_at.desc()):
        a, pr = actual.get(v.id), preds.get(v.id)
        live = bool(a)
        item = {"id": v.id, "project_id": v.project_id, "project": projects[v.project_id].name, "title": v.title, "sub": v.sub,
                "status": "live" if live else v.status, "measured": live,
                "ctr": round(a["clicks"] / a["imp"] * 100, 2) if a else (pr or {}).get("ctr"),
                "vtr": round(a["completes"] / a["imp"] * 100, 1) if a else (pr or {}).get("vtr"),
                "score": (pr or {}).get("score")}
        out.append(item)
    if status == "live":
        out = [x for x in out if x["status"] == "live"]
    elif status == "wait":
        out = [x for x in out if x["status"] == "wait"]
    elif status == "winning":
        out = [x for x in out if (x["ctr"] or 0) >= 2.0]
    if q:
        out = [x for x in out if q in x["title"] or q in x["project"] or q in x["sub"]]
    return out


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    waiting = db.query(ReviewTask).filter(ReviewTask.status == "wait").all()
    by: dict[str, int] = {}
    for r in waiting:
        by[r.module] = by.get(r.module, 0) + 1
    return {"kpis": [{"label": "本周花费", "value": "$4,820", "delta": "+12%", "good": True},
                     {"label": "CPA", "value": "$1.86", "delta": "-9%", "good": True},
                     {"label": "CTR", "value": "2.14%", "delta": "+0.3pt", "good": True},
                     {"label": "完播率", "value": "31.5%", "delta": "-1.2pt", "good": False}],
            "todo": [{"module": k, "count": v} for k, v in by.items()],
            "hot_ads": [ad_dict(a) for a in db.query(RefAd).order_by(RefAd.hot_score.desc()).limit(5)],
            "projects": [{"id": p.id, "name": p.name, "nodes": len(canvas.nodes_of(db, p.id))} for p in db.query(Project)]}


@router.get("/assets")
def assets(db: Session = Depends(get_db)):
    return {"selling_points": [{"id": s.id, "model_sku": s.model_sku, "title": s.title, "specs": s.specs,
                                "compliant_copy": s.compliant_copy, "priority": s.priority} for s in db.query(SellingPoint)],
            "audiences": [{"id": a.id, "market": a.market, "name": a.name, "tags": a.tags} for a in db.query(Audience)]}
