"""项目、画布、Agent 对话、补丁（计划卡）与实时事件。"""
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import agent, canvas, workflows
from app.db import get_db
from app.events import emit, hub
from app.models import ChatMessage, Node, Patch, Project, RefAd, ReviewTask
from app.seed import new_project

router = APIRouter(prefix="/api/v1")


def get_project(db: Session, pid: str) -> Project:
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404, "project not found")
    return p


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    out = []
    for p in db.query(Project).order_by(Project.created_at.desc()):
        nodes = canvas.nodes_of(db, p.id)
        waiting = db.query(ReviewTask).filter(ReviewTask.project_id == p.id, ReviewTask.status == "wait").count()
        out.append({"id": p.id, "name": p.name, "market": p.market, "brand": p.brand, "model_sku": p.model_sku,
                    "created_at": p.created_at.isoformat(), "waiting": waiting, "live": bool((p.flags or {}).get("launched")),
                    "nodes": len(nodes), "thumb": [{"type": n.type, "x": n.x, "y": n.y} for n in nodes]})
    return out


class ProjectIn(BaseModel):
    model_config = {"protected_namespaces": ()}
    name: str
    market: str = "尼日利亚"
    brand: str = "TECNO"
    model_sku: str = "Camon"
    selling_point: str = "续航"


@router.post("/projects")
def create_project(body: ProjectIn, db: Session = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(400, "项目名不能为空")
    p = new_project(db, body.name.strip(), body.market, body.brand, body.model_sku, body.selling_point)
    return {"id": p.id}


@router.get("/projects/{pid}")
def get_project_info(pid: str, db: Session = Depends(get_db)):
    p = get_project(db, pid)
    return {"id": p.id, "name": p.name, "market": p.market, "brand": p.brand, "model_sku": p.model_sku}


@router.get("/projects/{pid}/canvas")
def get_canvas(pid: str, db: Session = Depends(get_db)):
    return canvas.snapshot(db, get_project(db, pid))


class NodeUpdate(BaseModel):
    x: float | None = None
    y: float | None = None
    data: dict | None = None


@router.patch("/projects/{pid}/nodes/{nid}")
def update_node(pid: str, nid: str, body: NodeUpdate, db: Session = Depends(get_db)):
    project, n = get_project(db, pid), db.get(Node, nid)
    if not n or n.project_id != pid:
        raise HTTPException(404, "node not found")
    if body.x is not None and body.y is not None:
        n.x, n.y = body.x, body.y  # 仅移动位置不改变画布版本，避免让 Agent 的计划失效
    if body.data is not None:
        n.data = {**(n.data or {}), **body.data}
        canvas.bump(project)
        canvas.audit(db, pid, "user", "update_node", {"node_id": nid})
    db.commit()
    return canvas.node_dict(n)


@router.get("/projects/{pid}/chat")
def get_chat(pid: str, db: Session = Depends(get_db)):
    ms = db.query(ChatMessage).filter(ChatMessage.project_id == pid).order_by(ChatMessage.id).all()
    return [{"id": m.id, "role": m.role, **m.content} for m in ms]


class ChatIn(BaseModel):
    text: str
    selection: list[str] = []


@router.post("/projects/{pid}/agent/chat")
async def agent_chat(pid: str, body: ChatIn, db: Session = Depends(get_db)):
    project = get_project(db, pid)
    if not body.text.strip():
        raise HTTPException(400, "empty")
    res = await agent.handle(db, project, body.text.strip(), body.selection)
    emit(pid, "canvas")
    emit(pid, "chat")
    last = db.query(ChatMessage).filter(ChatMessage.project_id == pid, ChatMessage.role == "agent").order_by(ChatMessage.id.desc()).first()
    pending = db.query(Patch).filter(Patch.project_id == pid, Patch.status == "proposed").first()
    # 画布上的按钮发的指令：前端用 reply 弹提示（左侧对话收起时也能看到结果）
    return {**res, "reply": (last.content or {}).get("text", "") if last else "", "pending_patch": pending.summary if pending else None}


class DeleteIn(BaseModel):
    ids: list[str]


@router.post("/projects/{pid}/nodes/delete")
def delete_nodes(pid: str, body: DeleteIn, db: Session = Depends(get_db)):
    """删除画布节点，可撤销（⌘Z 或「撤销上一步」）。"""
    project = get_project(db, pid)
    p = canvas.delete_nodes(db, project, body.ids)
    if not p:
        raise HTTPException(404, "没有可删除的节点")
    agent.say(db, pid, f"已{p.summary}。需要恢复就点「撤销上一步」或按 ⌘Z。")
    db.commit()
    emit(pid, "canvas")
    emit(pid, "chat")
    emit(pid, "reviews")
    return {"ok": True, "deleted": p.ops[0]["ids"]}


@router.post("/projects/{pid}/patches/{patch_id}/apply")
def apply_patch(pid: str, patch_id: str, db: Session = Depends(get_db)):
    project, p = get_project(db, pid), db.get(Patch, patch_id)
    if not p or p.project_id != pid or p.status != "proposed":
        raise HTTPException(409, "patch is not pending")
    try:
        runs = canvas.apply_patch(db, project, p)
    except canvas.StaleVersion:
        p.status = "superseded"
        agent.set_card_state(db, p, "stale")
        agent.say(db, pid, "画布在计划生成后被修改过，这个计划已失效。请重新下达指令，我会基于最新画布规划。")
        db.commit()
        emit(pid, "chat")
        raise HTTPException(409, "canvas changed, please re-plan")
    flag = {"write_scripts": "scripts_generated", "iterate": "iterated"}.get((p.intent or {}).get("name"))
    if flag:
        project.flags = {**(project.flags or {}), flag: True}
    agent.set_card_state(db, p, "applied")
    created = [db.get(Node, i) for i in p.undo.get("nodes", [])]
    agent.say(db, pid, f"开始执行「{p.summary}」：" + " ".join(agent.ref(n) for n in created if n) + "。完成后会逐个提交审核。")
    db.commit()
    workflows.run(runs)
    emit(pid, "canvas")
    emit(pid, "chat")
    return {"ok": True, "created": p.undo.get("nodes", [])}


@router.post("/projects/{pid}/patches/{patch_id}/cancel")
def cancel_patch(pid: str, patch_id: str, db: Session = Depends(get_db)):
    p = db.get(Patch, patch_id)
    if not p or p.status != "proposed":
        raise HTTPException(409, "patch is not pending")
    p.status = "cancelled"
    agent.set_card_state(db, p, "cancelled")
    agent.say(db, pid, "好的，已取消，画布没有改动。")
    db.commit()
    emit(pid, "canvas")
    emit(pid, "chat")
    return {"ok": True}


class AdjustIn(BaseModel):
    count: int


@router.post("/projects/{pid}/patches/{patch_id}/adjust")
def adjust_patch(pid: str, patch_id: str, body: AdjustIn, db: Session = Depends(get_db)):
    project, p = get_project(db, pid), db.get(Patch, patch_id)
    if not p or p.status != "proposed" or (p.intent or {}).get("name") != "write_scripts":
        raise HTTPException(409, "patch cannot be adjusted")
    res = agent.adjust(db, project, p, body.count)
    db.commit()
    emit(pid, "canvas")
    emit(pid, "chat")
    return {"ok": not isinstance(res, str)}


@router.post("/projects/{pid}/undo")
def undo(pid: str, db: Session = Depends(get_db)):
    project = get_project(db, pid)
    p = canvas.undo_last(db, project)
    agent.say(db, pid, f"已撤销「{p.summary}」。" if p else "没有可撤销的 Agent 操作。")
    if p:
        agent.set_card_state(db, p, "undone")
    db.commit()
    emit(pid, "canvas")
    emit(pid, "chat")
    return {"ok": bool(p)}


class WashIn(BaseModel):
    ref_ad_no: int


@router.post("/projects/{pid}/wash")
def wash(pid: str, body: WashIn, db: Session = Depends(get_db)):
    """一键洗剧本：把爆款放到画布（已存在则选中），返回给 Agent 的指令。"""
    project = get_project(db, pid)
    ad = db.query(RefAd).filter(RefAd.no == body.ref_ad_no).first()
    if not ad:
        raise HTTPException(404, "ref ad not found")
    n = next((x for x in canvas.nodes_of(db, pid, "ad") if (x.data or {}).get("ref_ad_no") == ad.no), None)
    if not n:
        x, y = canvas.next_pos(db, pid, "ad")
        n = canvas.create_node(db, project, "ad", sub=f"{ad.hook} · {ad.market}", status="pass",
                               data={"ref_ad_no": ad.no}, x=x, y=y, title=f"爆款 #{ad.no}")
        canvas.bump(project)
    project.flags = {**(project.flags or {}), "washed": True}
    sp = ad.selling_point if ad.selling_point in ("续航", "拍照", "存储") else "续航"
    db.commit()
    emit(pid, "canvas")
    return {"node_id": n.id, "prompt": f"用 @爆款 #{ad.no} 给小商贩写 3 个{sp}剧本"}


@router.get("/projects/{pid}/flow")
def flow(pid: str, db: Session = Depends(get_db)):
    project = get_project(db, pid)
    f = project.flags or {}
    has = lambda t, st=None: any(st is None or n.status == st for n in canvas.nodes_of(db, pid, t))  # noqa: E731
    steps = [
        ("在爆款库选爆款并「一键洗剧本」", bool(f.get("washed")), "/ads"),
        ("Agent 在画布上生成剧本（先计划后执行）", bool(f.get("scripts_generated")), f"/p/{pid}"),
        ("审核中心通过剧本", bool(f.get("script_passed")), "/review"),
        ("Agent 生成视频（Seedance）", has("video"), f"/p/{pid}"),
        ("审核通过视频", has("video", "pass"), "/review"),
        ("40 Agent 评测并通过", has("eval", "pass"), f"/p/{pid}"),
        ("投放方案审核后下发 TikTok", bool(f.get("launched")), "/delivery"),
        ("数据回收 + 优化建议", has("opt"), "/data"),
        ("采纳建议，迭代再生成剧本", bool(f.get("iterated")), "/data"),
    ]
    return [{"title": t, "done": d, "path": p} for t, d, p in steps]


@router.websocket("/projects/{pid}/live")
async def live(ws: WebSocket, pid: str):
    await hub.connect(pid, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(pid, ws)
