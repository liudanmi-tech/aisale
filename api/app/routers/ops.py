"""爆款库、节点详情编辑、审核、投放、数据、资产与设置。"""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import agent, breakdown, canvas, config, monitor, production, settings_store, storyboard, wash, wash_plan, workflows
from app.adapters import llm
from app.db import SessionLocal, get_db
from app.events import emit, spawn
from app.models import Audience, MetricDaily, Node, Project, RefAd, ReviewTask, SellingPoint

router = APIRouter(prefix="/api/v1")


def _tiktok_id(dna: dict) -> str:
    """账号监控入库的爆款：TikTok 视频 ID（老数据从链接里取）。"""
    if dna.get("external_id"):
        return str(dna["external_id"])
    m = re.search(r"/video/(\d+)", dna.get("url") or "")
    return m.group(1) if m else ""


def ad_dict(a: RefAd) -> dict:
    tid = _tiktok_id(a.dna or {})
    return {"tiktok_id": tid or None, "cover": (monitor.cover_url(tid) or None) if tid else None,"id": a.id, "no": a.no, "source": a.source, "platform": a.platform, "brand": a.brand, "market": a.market,
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


class BreakdownIn(BaseModel):
    video: str | None = None  # data URL：没有 TikTok 链接或下载不到时，手动上传视频


@router.post("/ref-ads/{no}/breakdown")
def start_breakdown(no: int, body: BreakdownIn, db: Session = Depends(get_db)):
    """多模态拆解这条爆款（下载视频 → 抽帧 + 音轨 → 模型逐镜拆解），后台跑，结果写进 dna.breakdown。"""
    a = db.query(RefAd).filter(RefAd.no == no).first()
    if not a:
        raise HTTPException(404, "not found")
    if breakdown.running(no):
        raise HTTPException(409, "正在拆解，稍等")
    if body.video:
        m = re.match(r"data:video/[\w.+-]+;base64,(.+)", body.video, re.S)
        if not m:
            raise HTTPException(400, "请上传视频文件（mp4 / mov）")
        import base64
        raw = base64.b64decode(m.group(1))
        if len(raw) > breakdown.MAX_BYTES:
            raise HTTPException(400, "视频太大（超过 80MB）")
        p = breakdown.upload_path(no)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
    elif not (a.dna or {}).get("url") and not breakdown.upload_path(no).exists():
        raise HTTPException(400, "这条爆款没有 TikTok 链接：请上传视频文件再拆解")
    breakdown.start(no)
    db.refresh(a)
    return ad_dict(a)


@router.post("/nodes/{nid}/wash-confirm")
def wash_confirm(nid: str, db: Session = Depends(get_db)):
    """确认洗稿方案（待确认时等于审核通过；已确认后又改了表，就重新确认、按新表重写下游剧本）。"""
    n = db.get(Node, nid)
    if not n or n.type != "wash":
        raise HTTPException(404, "not found")
    if n.status in ("run", "none"):
        raise HTTPException(409, "方案还没生成好")
    if not any((r.get("ours") or "").strip() for r in (n.data or {}).get("rows") or []):
        raise HTTPException(400, "「我方」一列还是空的：先填好每一行怎么做")
    r = db.query(ReviewTask).filter(ReviewTask.node_id == nid, ReviewTask.status == "wait").first()
    if r:
        _decide(db, r, DecideIn(decision="pass"))
        return {"ok": True}
    project = db.get(Project, n.project_id)
    n.status = "pass"
    canvas.audit(db, n.project_id, "user", "wash_confirm", {"node_id": nid})
    runs = agent.auto_advance(db, project, n)
    db.commit()
    workflows.run(runs)
    for k in ("canvas", "chat", "reviews"):
        emit(n.project_id, k)
    return {"ok": True}


class WashTierIn(BaseModel):
    tier: str
    reset_edits: bool = False  # 换档时把人改过的行也按新档位重写


@router.post("/nodes/{nid}/wash-tier")
def wash_tier(nid: str, body: WashTierIn, db: Session = Depends(get_db)):
    """洗稿方案换档位：按新档位重新定每行保留 / 替换，重写「我方」一列，再提交确认。"""
    n = db.get(Node, nid)
    if not n or n.type != "wash":
        raise HTTPException(404, "not found")
    if body.tier not in wash_plan.TIERS:
        raise HTTPException(400, "档位只能是 high / mid / low")
    if n.status == "run":
        raise HTTPException(409, "方案正在生成，稍等")
    d = dict(n.data or {})
    rows = d.get("rows") or []
    if body.reset_edits:
        rows = [{**r, "edited": False} for r in rows]
    n.data = {**d, "tier": body.tier, "tier_source": "user", "rows": rows}
    n.status, n.sub = "run", f"按「{wash_plan.TIERS[body.tier]['label']}」重新出方案…"
    for r in db.query(ReviewTask).filter(ReviewTask.node_id == nid, ReviewTask.status == "wait"):
        r.status = "cancel"
    canvas.audit(db, n.project_id, "user", "wash_tier", {"node_id": nid, "tier": body.tier})
    db.commit()
    emit(n.project_id, "canvas")
    spawn(workflows.plan_wash(nid))
    return {"ok": True}


class WashPlanIn(BaseModel):
    keep: list[str] = []
    replace: list[str] = []
    idea: str | None = None  # 换核心看点的方案：候选里的另一个，或者自己写的


@router.post("/nodes/{nid}/wash-plan")
def rewrite_with_plan(nid: str, body: WashPlanIn, db: Session = Depends(get_db)):
    """改过的洗稿清单：保存后按清单重写剧本（不再重新出清单）。"""
    n = db.get(Node, nid)
    if not n or n.type != "script":
        raise HTTPException(404, "not found")
    d = dict(n.data or {})
    if not d.get("wash"):
        raise HTTPException(400, "这个剧本不是按爆款拆解洗的，没有洗稿清单")
    old = d["wash"].get("plan") or {}
    keep = [x.strip() for x in body.keep if x.strip()][:8] or old.get("keep") or []
    replace = [x.strip() for x in body.replace if x.strip()][:10] or old.get("replace") or []
    if not keep or not replace:
        raise HTTPException(400, "保留和替换至少各写一条")
    if n.status == "run":
        raise HTTPException(409, "剧本正在生成，稍等")
    plan = {**old, "keep": keep, "replace": replace}
    if body.idea and body.idea.strip():
        plan = wash.choose(plan, body.idea.strip()[:200])
    d["wash"] = {**d["wash"], "plan": plan, "plan_edited": True}
    n.data, n.status = d, "run"
    canvas.audit(db, n.project_id, "user", "wash_plan", {"node_id": nid})
    db.commit()
    emit(n.project_id, "canvas")
    spawn(workflows.generate_script(nid))
    return {"ok": True}


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


class StoryboardIn(BaseModel):
    indices: list[int] | None = None  # 不传：画缺失或过期的镜头；传：强制重画这些镜头
    prompt: str | None = None  # 只重画一镜时：人改过的提示词


@router.get("/nodes/{nid}/storyboard/{i}/prompt")
def storyboard_prompt(nid: str, i: int):
    try:
        return storyboard.preview(nid, i)
    except KeyError:
        raise HTTPException(404, "script not found") from None
    except IndexError:
        raise HTTPException(404, "没有这一镜") from None


@router.post("/nodes/{nid}/storyboard")
def draw_storyboard(nid: str, body: StoryboardIn, db: Session = Depends(get_db)):
    n = db.get(Node, nid)
    if not n or n.type != "script":
        raise HTTPException(404, "script not found")
    if not settings_store.llm_enabled():
        raise HTTPException(400, "画分镜需要 Gemini：请先在设置页填写 OpenRouter Key")
    if nid in storyboard._running:
        raise HTTPException(409, "正在画分镜，请稍候")
    canvas.audit(db, n.project_id, "user", "storyboard", {"node_id": nid, "indices": body.indices})
    db.commit()
    prompts = {}
    if body.prompt and body.prompt.strip():
        if not body.indices or len(body.indices) != 1:
            raise HTTPException(400, "改提示词只能一次重画一镜")
        prompts = {body.indices[0]: body.prompt.strip()[:4000]}
    spawn(storyboard.run(nid, body.indices, prompts))
    return {"ok": True}


@router.post("/nodes/{nid}/shots/{i}/regenerate")
def regenerate_shot(nid: str, i: int, db: Session = Depends(get_db)):
    """重新生成视频的某一镜（关键帧 + 视频），其余镜头保留。"""
    n = db.get(Node, nid)
    if not n or n.type != "video":
        raise HTTPException(404, "video not found")
    if not 0 <= i < len((n.data or {}).get("shots", [])):
        raise HTTPException(400, "bad shot index")
    if n.status == "run" or (n.data or {}).get("stage") in ("确认选角", "等待商品图"):
        raise HTTPException(409, "视频还在生成或等待确认，稍后再试")
    spawn(production.run(nid, only=[i]))
    return {"ok": True}


class RegenIn(BaseModel):
    comment: str = ""
    recast: bool = False  # 重新选角置景（换演员 / 场景后不需要，直接重生成即可）


@router.post("/nodes/{nid}/regenerate")
def regenerate_video(nid: str, body: RegenIn, db: Session = Depends(get_db)):
    """整条视频重新生成：换了演员 / 场景 / 商品图后用。"""
    n = db.get(Node, nid)
    if not n or n.type != "video":
        raise HTTPException(404, "video not found")
    if n.status in ("run",):
        raise HTTPException(409, "视频还在生成，稍后再试")
    canvas.audit(db, n.project_id, "user", "regenerate_video", {"node_id": nid, **body.model_dump()})
    db.commit()
    spawn(production.run(nid, body.comment, recast=body.recast))
    return {"ok": True}


@router.post("/nodes/{nid}/stop")
def stop_video(nid: str, db: Session = Depends(get_db)):
    """停止视频生成（整条或正在做的单镜）。已做好的关键帧和视频保留。"""
    n = db.get(Node, nid)
    if not n or n.type != "video":
        raise HTTPException(404, "video not found")
    k = production.stop(nid)
    canvas.audit(db, n.project_id, "user", "stop_video", {"node_id": nid, "tasks": k})
    agent.say(db, n.project_id, f"已停止 {agent.ref(n)} 的生成。已做好的镜头保留；改好选角、场景或提示词后，可以单镜重画，或点「全部重新生成」。")
    db.commit()
    emit(n.project_id, "canvas")
    emit(n.project_id, "chat")
    return {"ok": True, "cancelled": k}


@router.post("/nodes/{nid}/confirm-cast")
def confirm_cast(nid: str, db: Session = Depends(get_db)):
    """选角确认：人看过演员、场景、每镜拍法和口播后，继续画关键帧和生成视频。"""
    n = db.get(Node, nid)
    if not n or n.type != "video":
        raise HTTPException(404, "video not found")
    if n.status != "input" or (n.data or {}).get("stage") != "确认选角":
        raise HTTPException(409, "这条视频现在不在等选角确认")
    try:
        production.confirm_cast(nid)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    canvas.audit(db, n.project_id, "user", "confirm_cast", {"node_id": nid})
    agent.say(db, n.project_id, f"选角已确认，{agent.ref(n)} 开始画关键帧，每镜画完先质检再生成视频。")
    db.commit()
    emit(n.project_id, "chat")
    spawn(production.run(nid))
    return {"ok": True}


class CastIn(BaseModel):
    key: str  # 角色 / 场景的 key（如 r1、s1），商品写 product
    asset_id: str


@router.post("/nodes/{nid}/cast")
def set_cast(nid: str, body: CastIn, db: Session = Depends(get_db)):
    """在视频节点里换某个角色 / 场景 / 商品（从素材库选）。生成中不能换。"""
    n = db.get(Node, nid)
    if not n or n.type != "video":
        raise HTTPException(404, "video not found")
    if n.status == "run":
        raise HTTPException(409, "视频还在生成，等这一轮做完再换")
    try:
        cast = production.set_cast(nid, body.key, body.asset_id)
    except KeyError:
        raise HTTPException(404, "没有这个角色或素材") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    db.expire_all()
    n = db.get(Node, nid)
    if body.key == "product" and production.has_images(body.asset_id) and (n.data or {}).get("need_product"):
        n.sub = (n.sub or "").replace("（还需要上传商品图）", "")
        n.data = {**(n.data or {}), "need_product": False}
        db.commit()
    # 视频在等商品图、换成了一个已经有图的商品：直接继续
    if body.key == "product" and n.status == "input" and (n.data or {}).get("stage") == "等待商品图" and production.has_images(body.asset_id):
        n.data = {**(n.data or {}), "waiting_asset": body.asset_id}
        db.commit()
        for vid in production.resume_waiting(body.asset_id):
            spawn(production.run(vid))
    emit(n.project_id, "canvas")
    return {"cast": cast}


def _shot_guard(db: Session, nid: str, i: int) -> Node:
    """单镜修改的前置检查：整条视频在跑（分镜 / 选角 / 关键帧阶段）或在等选角确认时不行；这一镜正在做也不行。"""
    n = db.get(Node, nid)
    if not n or n.type != "video":
        raise HTTPException(404, "video not found")
    d = n.data or {}
    if not 0 <= i < len(d.get("shots", [])):
        raise HTTPException(400, "bad shot index")
    # 整条生成在画关键帧 / 生成视频时，已经做完或失败的镜头可以先单独重做；分镜、选角阶段和等确认时不行
    if (n.status == "run" and d.get("stage") not in ("关键帧", "单镜修改")) or d.get("stage") in ("确认选角", "等待商品图"):
        raise HTTPException(409, "视频还在拆分镜 / 选角或等待确认，稍后再试")
    t = (d.get("tasks") or [])[i] if i < len(d.get("tasks") or []) else {}
    if t.get("phase") not in production.IDLE:
        raise HTTPException(409, f"第 {i + 1} 镜正在{t.get('phase')}，稍后再试（等太久可以点视频节点上的「停止生成」再重做）")
    return n


class KeyframeIn(BaseModel):
    comment: str = ""
    prompt: str | None = None  # 改过的提示词主体；不传就按画面描述自动生成
    drop_refs: list[str] = []  # 这次不用的参考图（上一版 kf_meta.refs 里的 url）
    ref_shots: list[int] = []  # 拿哪几镜（从 0 开始）已经画好的关键帧当额外参考，保持人物 / 场景前后一致


@router.post("/nodes/{nid}/shots/{i}/keyframe")
def redo_keyframe(nid: str, i: int, body: KeyframeIn, db: Session = Depends(get_db)):
    """回到关键帧：只重画这一镜的关键帧（可写修改意见），画完停下等你确认，不自动生成视频。"""
    n = _shot_guard(db, nid, i)
    canvas.audit(db, n.project_id, "user", "redo_keyframe", {"node_id": nid, "shot": i, "comment": body.comment})
    db.commit()
    spawn(production.redo_keyframe(nid, i, body.comment.strip(), body.prompt, body.drop_refs, body.ref_shots))
    return {"ok": True}


class InpaintIn(BaseModel):
    mask: str  # data URL：涂过的地方不透明 / 白色
    prompt: str
    engine: str = "auto"  # auto / flux / gemini
    product: bool = False  # 带上商品实拍图（改手机时用）


@router.post("/nodes/{nid}/shots/{i}/inpaint")
def inpaint_keyframe(nid: str, i: int, body: InpaintIn, db: Session = Depends(get_db)):
    """关键帧局部重绘：只重画涂过的地方，画完停下等你确认。"""
    n = _shot_guard(db, nid, i)
    t = ((n.data or {}).get("tasks") or [{}] * (i + 1))[i] or {}
    if not t.get("keyframe"):
        raise HTTPException(400, "这一镜还没有关键帧")
    if not body.prompt.strip():
        raise HTTPException(400, "写一句要把涂的地方改成什么")
    if body.engine == "flux" and not settings_store.get_secret("fal"):
        raise HTTPException(400, "FLUX Fill 走 fal：先在设置页填 fal Key，或改用 Gemini")
    if body.engine in ("gemini", "auto") and not settings_store.llm_enabled() and not settings_store.get_secret("fal"):
        raise HTTPException(400, "局部重绘需要 OpenRouter 或 fal 的 Key")
    canvas.audit(db, n.project_id, "user", "inpaint_keyframe", {"node_id": nid, "shot": i, "prompt": body.prompt})
    db.commit()
    spawn(production.inpaint_keyframe(nid, i, body.mask, body.prompt.strip()[:600], body.engine, body.product))
    return {"ok": True}


@router.post("/nodes/{nid}/shots/{i}/keyframe-undo")
def undo_keyframe(nid: str, i: int, db: Session = Depends(get_db)):
    """撤回上一次局部重绘。"""
    _shot_guard(db, nid, i)
    kf = production.restore_keyframe(nid, i)
    if not kf:
        raise HTTPException(400, "没有可以撤回的版本")
    return {"keyframe": kf}


class PickIn(BaseModel):
    url: str


@router.post("/nodes/{nid}/shots/{i}/keyframe-pick")
def pick_keyframe(nid: str, i: int, body: PickIn, db: Session = Depends(get_db)):
    """从这一镜的关键帧候选里换一张（不花钱）。这一镜还在画关键帧时：选定这张，停下不再画。"""
    n = db.get(Node, nid)
    t = ((n.data or {}).get("tasks") or [])[i] if n and n.type == "video" and 0 <= i < len((n.data or {}).get("tasks") or []) else {}
    if str(t.get("phase") or "").startswith(("画关键帧", "重画关键帧", "上一张没过质检")):
        if not production.pin_candidate(nid, i, body.url):
            raise HTTPException(404, "没有这张候选")
        return {"ok": True, "pinned": True}
    _shot_guard(db, nid, i)
    if not production.pick_candidate(nid, i, body.url):
        raise HTTPException(404, "没有这张候选")
    return {"ok": True}


class ClipsIn(BaseModel):
    indices: list[int] | None = None  # 不传：所有「关键帧待确认」的镜头


@router.post("/nodes/{nid}/clips")
def generate_clips(nid: str, body: ClipsIn, db: Session = Depends(get_db)):
    """关键帧都调好了：一起生成视频（这时才开始花视频的钱）。"""
    n = db.get(Node, nid)
    if not n or n.type != "video":
        raise HTTPException(404, "video not found")
    d = n.data or {}
    if n.status == "run" and d.get("stage") not in ("单镜修改", "关键帧"):
        raise HTTPException(409, "视频还在拆分镜 / 选角，稍后再试")
    tasks = d.get("tasks") or []
    todo = [k for k, t in enumerate(tasks) if t and t.get("phase") == "关键帧待确认" and t.get("keyframe")
            and (body.indices is None or k in body.indices)]
    if not todo:
        raise HTTPException(400, "没有等着生成视频的关键帧")
    canvas.audit(db, n.project_id, "user", "generate_clips", {"node_id": nid, "shots": todo})
    db.commit()
    for k in todo:
        spawn(production.redo_clip(nid, k))
    return {"shots": todo}


class ClipIn(BaseModel):
    prompt: str | None = None  # 浮窗里确认过的提示词；不传就按模式自动生成
    mode: str | None = None  # ref 全能参考 / first 首帧 / first_last 首尾帧
    engine: str = "auto"  # auto / seedance-2.5 / seedance-2.0 / kling
    comment: str = ""


@router.post("/nodes/{nid}/shots/{i}/clip")
def redo_clip(nid: str, i: int, body: ClipIn | None = None, db: Session = Depends(get_db)):
    """用这一镜现在的关键帧生成视频（可带浮窗里改过的提示词、模式和模型）。"""
    body = body or ClipIn()
    n = _shot_guard(db, nid, i)
    t = ((n.data or {}).get("tasks") or [{}] * (i + 1))[i]
    if not t.get("keyframe"):
        raise HTTPException(400, "这一镜还没有关键帧，先画关键帧")
    if body.engine not in production.VIDEO_ENGINES:
        raise HTTPException(400, "不认识这个视频模型")
    canvas.audit(db, n.project_id, "user", "redo_clip", {"node_id": nid, "shot": i, **body.model_dump()})
    db.commit()
    spawn(production.redo_clip(nid, i, (body.prompt or "").strip() or None, body.mode, body.engine, body.comment.strip()))
    return {"ok": True}


class ClipPlanIn(BaseModel):
    mode: str | None = None
    prompt: str | None = None
    suggestion: str = ""


@router.post("/nodes/{nid}/shots/{i}/video-plan")
async def video_plan(nid: str, i: int, body: ClipPlanIn, db: Session = Depends(get_db)):
    """「重做视频」浮窗：上一轮用的模式 / 模型 / 提示词 / 质检问题，这一轮的提示词预览；带修改建议时让模型按建议改写提示词（不生成视频）。"""
    n = db.get(Node, nid)
    if not n or n.type != "video" or not 0 <= i < len((n.data or {}).get("shots", [])):
        raise HTTPException(404, "没有这一镜")
    plan = production.preview_clip(nid, i, body.mode)
    if body.suggestion.strip():
        try:
            plan["prompt"] = await production.rewrite_clip_prompt((body.prompt or "").strip() or plan["prompt"], body.suggestion.strip(), plan["mode"])
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"改写提示词失败：{str(e)[:200]}") from None
    return plan


class ComposeIn(BaseModel):
    captions: bool | None = None  # 不传就沿用节点上的设置
    trims: dict[str, dict] | None = None  # 每镜剪哪一段：{"镜号": {"start": 秒, "dur": 秒或 null=整段}}；{} 清空，全部按剧本时长


@router.post("/nodes/{nid}/compose")
def compose(nid: str, body: ComposeIn, db: Session = Depends(get_db)):
    """成片重新合成（视频改过镜头后，或切换字幕开关）。"""
    n = db.get(Node, nid)
    if not n or n.type != "cut":
        raise HTTPException(404, "cut not found")
    if n.status == "run":
        raise HTTPException(409, "正在合成，稍后再试")
    if body.captions is not None:
        n.data = {**(n.data or {}), "captions": body.captions}
    if body.trims is not None:
        ok = {str(k): {"start": max(0.0, float(v.get("start") or 0)), "dur": (max(0.5, float(v["dur"])) if v.get("dur") else None)}
              for k, v in body.trims.items() if str(k).isdigit() and isinstance(v, dict)}
        n.data = {**(n.data or {}), "trims": ok}
    n.status, n.sub = "run", "合成中…"
    canvas.audit(db, n.project_id, "user", "compose", {"node_id": nid, **body.model_dump()})
    db.commit()
    emit(n.project_id, "canvas")
    spawn(workflows.compose_cut(nid))
    return {"ok": True}


class ShotsIn(BaseModel):
    indices: list[int]


@router.post("/nodes/{nid}/shots/regenerate")
def regenerate_shots(nid: str, body: ShotsIn, db: Session = Depends(get_db)):
    """只重新生成指定的几镜（改过拍法、换过演员 / 场景的镜头），其余保留。"""
    n = db.get(Node, nid)
    if not n or n.type != "video":
        raise HTTPException(404, "video not found")
    total = len((n.data or {}).get("shots", []))
    idx = sorted({i for i in body.indices if 0 <= i < total})
    if not idx:
        raise HTTPException(400, "没有要重新生成的镜头")
    if n.status == "run" or (n.data or {}).get("stage") in ("确认选角", "等待商品图"):
        raise HTTPException(409, "视频还在生成或等待确认，稍后再试")
    canvas.audit(db, n.project_id, "user", "regenerate_shots", {"node_id": nid, "indices": idx})
    db.commit()
    spawn(production.run(nid, only=idx))
    return {"ok": True, "indices": idx}


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


NEXT_HINT = {"deliver": "在投放节点上点「下发到 TikTok」开始花钱投放。", "opt": ""}
AUTO_NEXT = ("wash", "script", "video", "eval")  # 这些节点通过后自动走下一步，见 agent.auto_advance


@router.post("/reviews/{rid}/decide")
def decide(rid: str, body: DecideIn, db: Session = Depends(get_db)):
    r = db.get(ReviewTask, rid)
    if not r or r.status != "wait":
        raise HTTPException(409, "review is not pending")
    if body.decision == "reject" and not body.comment.strip():
        raise HTTPException(400, "驳回需要填写理由")
    _decide(db, r, body)
    return {"ok": True}


class NodesDecideIn(BaseModel):
    node_ids: list[str]


@router.post("/reviews/pass-nodes")
def pass_nodes(body: NodesDecideIn, db: Session = Depends(get_db)):
    """在画布上直接通过一个或多个待审核节点（驳回需要理由，走详情页）。"""
    rs = db.query(ReviewTask).filter(ReviewTask.node_id.in_(body.node_ids), ReviewTask.status == "wait").all()
    for r in rs:
        _decide(db, r, DecideIn(decision="pass"))
    return {"passed": len(rs)}


class RejectNodeIn(BaseModel):
    node_id: str
    comment: str


@router.post("/reviews/reject-node")
def reject_node(body: RejectNodeIn, db: Session = Depends(get_db)):
    """在画布上驳回：理由作为改稿意见交给 Agent 重做。"""
    if not body.comment.strip():
        raise HTTPException(400, "驳回需要填写理由")
    r = db.query(ReviewTask).filter(ReviewTask.node_id == body.node_id, ReviewTask.status == "wait").first()
    if not r:
        raise HTTPException(409, "这个节点没有待审核的结果")
    _decide(db, r, DecideIn(decision="reject", comment=body.comment.strip()))
    return {"ok": True}


def _decide(db: Session, r: ReviewTask, body: "DecideIn") -> None:
    n, project = db.get(Node, r.node_id), db.get(Project, r.project_id)
    r.status = "reject" if body.decision == "reject" else "pass"
    r.comment, r.decided_at = body.comment or ("修改后通过" if body.decision == "edit_pass" else ""), datetime.utcnow()
    canvas.audit(db, r.project_id, "user", "review_" + r.status, {"review_id": r.id, "node_id": r.node_id, "comment": body.comment})
    rework, runs = False, []
    if n and r.status == "pass":
        n.status = "pass"
        if n.type == "script":
            project.flags = {**(project.flags or {}), "script_passed": True}
        if n.type in AUTO_NEXT:
            runs = agent.auto_advance(db, project, n)
        else:
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
    workflows.run(runs)
    for k in ("canvas", "chat", "reviews"):
        emit(r.project_id, k)


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
