"""画布模型与 Agent 画布工具：节点、连线、补丁（预览 → 应用 → 撤销）、布局、审核单。"""
from datetime import datetime

from sqlalchemy import DateTime, or_
from sqlalchemy.orm import Session

from app.models import AuditLog, Edge, Node, Patch, Project, ReviewTask, new_id

TYPES = {
    "ad": {"label": "爆款", "col": 0, "module": "爆款挖掘"},
    "sp": {"label": "卖点", "col": 0, "module": "资产"},
    "aud": {"label": "人群包", "col": 0, "module": "资产"},
    "script": {"label": "剧本", "col": 1, "module": "剧本工厂"},
    "actor": {"label": "演员", "col": 2, "module": "选角置景"},
    "scene": {"label": "场景", "col": 2, "module": "选角置景"},
    "product": {"label": "商品", "col": 2, "module": "选角置景"},
    "video": {"label": "视频", "col": 3, "module": "视频生成"},
    "cut": {"label": "成片", "col": 4, "module": "成片合成"},
    "eval": {"label": "评测", "col": 5, "module": "Agent 评测"},
    "deliver": {"label": "投放", "col": 6, "module": "自动投放"},
    "data": {"label": "数据", "col": 7, "module": "数据回收"},
    "opt": {"label": "优化", "col": 8, "module": "自动优化"},
}
STATUS_ZH = {"none": "未开始", "run": "生成中", "input": "待上传", "wait": "待审核", "pass": "已通过", "reject": "已驳回", "live": "投放中", "failed": "失败"}
X0, Y0, GAP_X, GAP_Y = 40, 40, 80, 40
# 节点在画布上默认展开显示内容，布局按展开后的大致尺寸排（宽度和前端 NODE_WIDTH 一致，高度是估计值）
NODE_SIZE = {"ad": (220, 84), "sp": (220, 84), "aud": (220, 84), "script": (660, 620), "video": (660, 560),
             "actor": (260, 470), "scene": (260, 470), "product": (260, 470),
             "cut": (380, 820), "eval": (760, 900), "deliver": (400, 300), "data": (400, 260), "opt": (400, 300)}
COL_X: dict[int, float] = {}
_x = X0
for _col in range(max(t["col"] for t in TYPES.values()) + 1):
    COL_X[_col] = _x
    _x += max(w for t, (w, _) in NODE_SIZE.items() if TYPES[t]["col"] == _col) + GAP_X


def _bottom(n: Node) -> float:
    return n.y + NODE_SIZE[n.type][1] + GAP_Y


class StaleVersion(Exception):
    pass


def node_dict(n: Node) -> dict:
    return {"id": n.id, "type": n.type, "no": n.no, "title": n.title, "sub": n.sub, "status": n.status,
            "x": n.x, "y": n.y, "data": n.data or {}}


def patch_dict(p: Patch) -> dict:
    return {"id": p.id, "base_version": p.base_version, "summary": p.summary, "steps": p.steps, "cost": p.cost,
            "needs_review": p.needs_review, "ops": p.ops, "status": p.status, "intent": p.intent}


def nodes_of(db: Session, pid: str, type_: str | None = None) -> list[Node]:
    q = db.query(Node).filter(Node.project_id == pid)
    if type_:
        q = q.filter(Node.type == type_)
    return q.order_by(Node.created_at, Node.no).all()


def pending_patch(db: Session, pid: str) -> Patch | None:
    return db.query(Patch).filter(Patch.project_id == pid, Patch.status == "proposed").order_by(Patch.created_at.desc()).first()


def snapshot(db: Session, project: Project) -> dict:
    p = pending_patch(db, project.id)
    return {
        "project": {"id": project.id, "name": project.name, "market": project.market, "brand": project.brand},
        "version": project.version,
        "nodes": [node_dict(n) for n in nodes_of(db, project.id)],
        "edges": [{"id": e.id, "source": e.source, "target": e.target} for e in db.query(Edge).filter(Edge.project_id == project.id)],
        "pending_patch": patch_dict(p) if p else None,
    }


def next_pos(db: Session, pid: str, type_: str, k: int = 0) -> tuple[float, float]:
    """新节点放在同一列最下面；k 表示同一批里的第几个。"""
    col = TYPES[type_]["col"]
    ys = [_bottom(n) for n in nodes_of(db, pid) if TYPES[n.type]["col"] == col]
    y = max(ys) if ys else Y0
    return COL_X[col], y + k * (NODE_SIZE[type_][1] + GAP_Y)


def bump(project: Project) -> None:
    project.version = (project.version or 0) + 1


def create_node(db: Session, project: Project, type_: str, sub: str = "", status: str = "none",
                data: dict | None = None, x: float | None = None, y: float | None = None, title: str | None = None) -> Node:
    counters = dict(project.counters or {})
    counters[type_] = counters.get(type_, 0) + 1
    project.counters = counters
    no = counters[type_]
    if x is None or y is None:
        x, y = next_pos(db, project.id, type_)
    n = Node(id=new_id("n"), project_id=project.id, type=type_, no=no, title=title or f"{TYPES[type_]['label']} #{no}",
             sub=sub, status=status, x=x, y=y, data=data or {})
    db.add(n)
    db.flush()
    return n


def connect(db: Session, pid: str, source: str, target: str) -> Edge:
    e = Edge(id=new_id("e"), project_id=pid, source=source, target=target)
    db.add(e)
    db.flush()
    return e


def upstream(db: Session, node_id: str) -> list[Node]:
    ids = [e.source for e in db.query(Edge).filter(Edge.target == node_id)]
    return db.query(Node).filter(Node.id.in_(ids)).all() if ids else []


def downstream(db: Session, node_id: str) -> list[Node]:
    ids = [e.target for e in db.query(Edge).filter(Edge.source == node_id)]
    return db.query(Node).filter(Node.id.in_(ids)).all() if ids else []


def audit(db: Session, pid: str, actor: str, action: str, payload: dict | None = None) -> None:
    db.add(AuditLog(project_id=pid, actor=actor, action=action, payload=payload or {}))


def add_review(db: Session, node: Node, conclusion: str, evidence: str = "") -> ReviewTask:
    """提交审核；同一节点之前没处理的审核单作废（以最新结果为准）。"""
    for old in db.query(ReviewTask).filter(ReviewTask.node_id == node.id, ReviewTask.status == "wait"):
        old.status = "cancel"
    r = ReviewTask(id=new_id("r"), project_id=node.project_id, node_id=node.id, module=TYPES[node.type]["module"],
                   title=node.title, conclusion=conclusion, evidence=evidence, status="wait")
    db.add(r)
    node.status = "wait"
    return r


def apply_patch(db: Session, project: Project, patch: Patch) -> list[tuple[str, str]]:
    """应用补丁，返回需要启动的 (node_id, action) 列表。"""
    if patch.base_version != project.version:
        raise StaleVersion()
    idmap: dict[str, str] = {}
    created_nodes, created_edges, runs = [], [], []
    run_targets = {op["node_id"] for op in patch.ops if op["op"] == "run_node"}
    for op in patch.ops:
        if op["op"] == "create_node":
            status = "run" if op["temp_id"] in run_targets else op.get("status", "none")
            n = create_node(db, project, op["type"], sub=op.get("sub", ""), status=status, data=op.get("data") or {},
                            x=op["x"], y=op["y"], title=op.get("title"))
            if op["type"] == "ad":
                project.flags = {**(project.flags or {}), "washed": True}
            idmap[op["temp_id"]] = n.id
            created_nodes.append(n.id)
        elif op["op"] == "connect":
            e = connect(db, project.id, idmap.get(op["from"], op["from"]), idmap.get(op["to"], op["to"]))
            created_edges.append(e.id)
        elif op["op"] == "run_node":
            runs.append((idmap.get(op["node_id"], op["node_id"]), op["action"]))
    patch.status = "applied"
    patch.undo = {"nodes": created_nodes, "edges": created_edges, "idmap": idmap}
    bump(project)
    audit(db, project.id, "agent", "apply_patch", {"patch_id": patch.id, "summary": patch.summary})
    return runs


LAYOUT_VERSION = 5  # v5：评测节点放大成三个子节点； v2：节点默认展开；v3：剧本与视频之间加了演员 / 场景 / 商品一列；v4：视频和评测之间加了成片一列。老项目启动时整理一次


def migrate_layouts(db: Session) -> int:
    """老项目的节点是按小卡片排的，展开后会重叠：整理一次（记录为可撤销的操作）。"""
    n = 0
    for p in db.query(Project):
        if (p.flags or {}).get("layout_v") == LAYOUT_VERSION:
            continue
        if nodes_of(db, p.id):
            layout(db, p)
            bump(p)
            n += 1
        p.flags = {**(p.flags or {}), "layout_v": LAYOUT_VERSION}
    db.commit()
    return n


def layout(db: Session, project: Project) -> Patch:
    """按节点类型分列排布；作为一次已应用的补丁记录，便于撤销。"""
    prev = []
    tops: dict[int, float] = {}
    for n in nodes_of(db, project.id):
        prev.append([n.id, n.x, n.y])
        col = TYPES[n.type]["col"]
        n.x, n.y = COL_X[col], tops.get(col, Y0)
        tops[col] = _bottom(n)
    p = Patch(id=new_id("pt"), project_id=project.id, base_version=project.version, intent={"name": "layout"},
              summary="整理画布", steps=["按类型分列排布"], ops=[{"op": "layout", "strategy": "by_type"}],
              status="applied", needs_review=False, undo={"positions": prev})
    db.add(p)
    return p


def _row(obj) -> dict:
    out = {}
    for c in obj.__table__.columns:
        v = getattr(obj, c.name)
        out[c.name] = v.isoformat() if isinstance(v, datetime) else v
    return out


def _unrow(cls, d: dict):
    vals = {}
    for c in cls.__table__.columns:
        v = d.get(c.name)
        if isinstance(v, str) and isinstance(c.type, DateTime):
            v = datetime.fromisoformat(v)
        vals[c.name] = v
    return cls(**vals)


def delete_nodes(db: Session, project: Project, ids: list[str]) -> Patch | None:
    """删除节点（连同它们的连线和待审核任务）；整行存进补丁，撤销时原样恢复。"""
    nodes = [n for n in (db.get(Node, i) for i in ids) if n and n.project_id == project.id]
    if not nodes:
        return None
    nid = [n.id for n in nodes]
    edges = db.query(Edge).filter(or_(Edge.source.in_(nid), Edge.target.in_(nid))).all()
    reviews = db.query(ReviewTask).filter(ReviewTask.node_id.in_(nid)).all()
    snap = {"nodes": [_row(n) for n in nodes], "edges": [_row(e) for e in edges], "reviews": [_row(r) for r in reviews]}
    for obj in [*reviews, *edges, *nodes]:
        db.delete(obj)
    names = "、".join(n.title for n in nodes[:3]) + (f" 等 {len(nodes)} 个" if len(nodes) > 3 else "")
    p = Patch(id=new_id("pt"), project_id=project.id, base_version=project.version, intent={"name": "delete"},
              summary=f"删除 {names}", steps=[f"删除 {len(nodes)} 个节点和 {len(edges)} 条连线"], ops=[{"op": "delete", "ids": nid}],
              status="applied", needs_review=False, undo={"deleted": snap})
    db.add(p)
    bump(project)
    audit(db, project.id, "user", "delete_nodes", {"ids": nid})
    return p


def undo_last(db: Session, project: Project) -> Patch | None:
    p = db.query(Patch).filter(Patch.project_id == project.id, Patch.status == "applied").order_by(Patch.created_at.desc()).first()
    if not p:
        return None
    u = p.undo or {}
    for nid, x, y in u.get("positions", []):
        n = db.get(Node, nid)
        if n:
            n.x, n.y = x, y
    node_ids = u.get("nodes", [])
    if node_ids:
        db.query(ReviewTask).filter(ReviewTask.node_id.in_(node_ids)).delete(synchronize_session=False)
        db.query(Edge).filter(or_(Edge.source.in_(node_ids), Edge.target.in_(node_ids))).delete(synchronize_session=False)
        db.query(Node).filter(Node.id.in_(node_ids)).delete(synchronize_session=False)
    if u.get("edges"):
        db.query(Edge).filter(Edge.id.in_(u["edges"])).delete(synchronize_session=False)
    gone = u.get("deleted") or {}
    for cls, key in ((Node, "nodes"), (Edge, "edges"), (ReviewTask, "reviews")):
        for d in gone.get(key, []):
            if not db.get(cls, d["id"]):
                db.add(_unrow(cls, d))
        db.flush()
    p.status = "undone"
    bump(project)
    audit(db, project.id, "user", "undo", {"patch_id": p.id})
    return p


def now() -> datetime:
    return datetime.utcnow()


def recover_interrupted(db: Session) -> int:
    """服务重启时进程内的后台任务都没了：停在「生成中」的节点改成失败，让用户可以重新生成。"""
    n = 0
    idle = ("完成", "失败", "已停止", "关键帧待确认", None)
    for node in db.query(Node).filter(Node.status == "run"):
        node.status, node.sub = "failed", "服务重启，生成中断，可重新生成"
        n += 1
    for node in db.query(Node).filter(Node.type == "video"):
        tasks = list((node.data or {}).get("tasks") or [])
        if not any(t.get("phase") not in idle for t in tasks):
            continue
        # 镜头停在半路（画关键帧 / 生成视频 / 质检中）：视频已出来就算完成（质检没做完），否则标失败，按钮才能再点
        for k, t in enumerate(tasks):
            if t.get("phase") in idle:
                continue
            if (t.get("url") or "").startswith("http"):
                tasks[k] = {**t, "phase": "完成", "status": "completed", "retry_error": "服务重启，这一镜的视频质检没做完，请自己看一下"}
            else:
                tasks[k] = {**t, "phase": "失败", "status": "failed",
                            "error": "服务重启，生成中断" + ("，可点「重做视频」（沿用关键帧）" if t.get("keyframe") else "，可点「重新生成」")}
        node.data = {**node.data, "tasks": tasks}
    for node in db.query(Node).filter(Node.type == "script"):
        sb = (node.data or {}).get("storyboard") or {}
        if sb.get("status") == "running":
            node.data = {**node.data, "storyboard": {**sb, "status": "error", "error": "服务重启，分镜中断"}}
    db.commit()
    return n
