"""画布模型与 Agent 画布工具：节点、连线、补丁（预览 → 应用 → 撤销）、布局、审核单。"""
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import AuditLog, Edge, Node, Patch, Project, ReviewTask, new_id

TYPES = {
    "ad": {"label": "爆款", "col": 0, "module": "爆款挖掘"},
    "sp": {"label": "卖点", "col": 0, "module": "资产"},
    "aud": {"label": "人群包", "col": 0, "module": "资产"},
    "script": {"label": "剧本", "col": 1, "module": "剧本工厂"},
    "video": {"label": "视频", "col": 2, "module": "视频生成"},
    "eval": {"label": "评测", "col": 3, "module": "Agent 评测"},
    "deliver": {"label": "投放", "col": 4, "module": "自动投放"},
    "data": {"label": "数据", "col": 5, "module": "数据回收"},
    "opt": {"label": "优化", "col": 6, "module": "自动优化"},
}
STATUS_ZH = {"none": "未开始", "run": "生成中", "wait": "待审核", "pass": "已通过", "reject": "已驳回", "live": "投放中", "failed": "失败"}
COL_W, ROW_H, X0, Y0 = 260, 120, 40, 40


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
    col = TYPES[type_]["col"]
    ys = [n.y for n in nodes_of(db, pid) if TYPES[n.type]["col"] == col]
    y = (max(ys) + ROW_H) if ys else Y0
    return X0 + col * COL_W, y + k * ROW_H


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
            status = "run" if op["temp_id"] in run_targets else "none"
            n = create_node(db, project, op["type"], sub=op.get("sub", ""), status=status, data=op.get("data") or {},
                            x=op["x"], y=op["y"])
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


def layout(db: Session, project: Project) -> Patch:
    """按节点类型分列排布；作为一次已应用的补丁记录，便于撤销。"""
    prev = []
    rows: dict[int, int] = {}
    for n in nodes_of(db, project.id):
        prev.append([n.id, n.x, n.y])
        col = TYPES[n.type]["col"]
        i = rows.get(col, 0)
        n.x, n.y = X0 + col * COL_W, Y0 + i * ROW_H
        rows[col] = i + 1
    p = Patch(id=new_id("pt"), project_id=project.id, base_version=project.version, intent={"name": "layout"},
              summary="整理画布", steps=["按类型分列排布"], ops=[{"op": "layout", "strategy": "by_type"}],
              status="applied", needs_review=False, undo={"positions": prev})
    db.add(p)
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
    p.status = "undone"
    bump(project)
    audit(db, project.id, "user", "undo", {"patch_id": p.id})
    return p


def now() -> datetime:
    return datetime.utcnow()
