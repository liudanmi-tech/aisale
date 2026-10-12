"""投放 Agent：理解指令 → 生成画布补丁（计划卡 + 预览）→ 用户确认后应用。

Agent 只能通过画布工具改画布：查询、创建节点、连线、布局、运行节点、撤销。
上游未通过审核时拒绝执行下游指令，并指出卡在哪个节点。
"""
import json
import re

from sqlalchemy.orm import Session

from app import canvas, config, settings_store
from app.adapters import llm
from app.models import ChatMessage, Node, Patch, Project, new_id

INTENT_TOOLS = [
    {"type": "function", "function": {"name": "write_scripts", "description": "基于爆款结构给某个人群写剧本",
        "parameters": {"type": "object", "properties": {
            "count": {"type": "integer", "minimum": 1, "maximum": 6},
            "selling_point": {"type": "string", "enum": ["续航", "拍照", "存储"]},
            "audience": {"type": "string", "enum": ["小商贩", "学生", "年轻家庭"]},
            "ref_ad_node_id": {"type": "string", "description": "参考的爆款节点 id，不确定时省略"}},
            "required": ["count", "selling_point", "audience"]}}},
    {"type": "function", "function": {"name": "generate_videos", "description": "为已通过审核的剧本生成视频",
        "parameters": {"type": "object", "properties": {"script_node_ids": {"type": "array", "items": {"type": "string"}}}}}},
    {"type": "function", "function": {"name": "run_evaluation", "description": "对已通过审核的视频跑 40 Agent 评测",
        "parameters": {"type": "object", "properties": {"video_node_ids": {"type": "array", "items": {"type": "string"}}}}}},
    {"type": "function", "function": {"name": "plan_delivery", "description": "根据已通过的评测结论生成 TikTok 投放方案",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "layout", "description": "整理画布布局", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "undo", "description": "撤销上一次 Agent 操作", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "query_best", "description": "回答哪个视频预测 CTR 最高之类的查询",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "summary", "description": "总结项目进度", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "clarify", "description": "指令有歧义或无法完成时反问用户",
        "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}},
]

HELP = ("我可以：写剧本（如「给学生写 2 个拍照剧本」）、生成视频、跑评测、生成投放方案、整理画布、"
        "查询（如「哪个视频预测 CTR 最高」）、撤销。\n选中节点后再下指令，只会作用于选中的节点。")


def ref(n: Node) -> str:
    return "{{" + n.id + "}}"


def say(db: Session, pid: str, text: str, role: str = "agent") -> ChatMessage:
    m = ChatMessage(project_id=pid, role=role, content={"text": text})
    db.add(m)
    db.flush()
    return m


def set_card_state(db: Session, patch: Patch, state: str, **extra) -> None:
    if patch.chat_message_id:
        m = db.get(ChatMessage, patch.chat_message_id)
        if m:
            m.content = {**m.content, "state": state, **extra}


def rule_intent(text: str, selection: list[str]) -> dict:
    t = re.sub(r"\s", "", text)
    if "撤销" in t:
        return {"name": "undo"}
    if re.search("整理|排列", t):
        return {"name": "layout"}
    if re.search("最高|哪个|最好|最佳", t):
        return {"name": "query_best"}
    if re.search("总结|进度", t):
        return {"name": "summary"}
    if re.search("剧本|写|变体", t):
        m = re.search(r"(\d+)个", t)
        ad = re.search(r"爆款#?(\d+)", t)
        return {"name": "write_scripts", "count": min(6, int(m.group(1))) if m else 3,
                "selling_point": "拍照" if re.search("拍照|夜拍", t) else ("存储" if "存储" in t else "续航"),
                "audience": "学生" if "学生" in t else ("年轻家庭" if re.search("家庭|婚礼|斋月", t) else "小商贩"), "ref_ad_no": int(ad.group(1)) if ad else None}
    if re.search("视频|成片", t):
        return {"name": "generate_videos"}
    if re.search("评测|打分", t):
        return {"name": "run_evaluation"}
    if re.search("投放|下发|方案", t):
        return {"name": "plan_delivery"}
    return {"name": "help"}


async def llm_intent(db: Session, project: Project, text: str, selection: list[str]) -> dict:
    nodes = canvas.nodes_of(db, project.id)
    snap = "\n".join(f"- {n.id} | {n.title} | {n.type} | {canvas.STATUS_ZH.get(n.status, n.status)}" for n in nodes)
    system = ("你是 TECNO 手机海外投放平台的画布 Agent，只能通过给定工具操作画布。"
              "根据用户指令选择且只选择一个工具。节点引用一律使用节点 id。\n"
              "卖点同义词：夜拍/拍照/相机/自拍 → 拍照；电池/续航/停电/充电 → 续航；内存/存储/装照片 → 存储。"
              "人群同义词：学生/年轻人/大学生 → 学生；摊主/商贩/小生意/做生意 → 小商贩；家庭/婚礼/斋月团聚 → 年轻家庭。数量用阿拉伯数字（两个 → 2）。\n"
              "用户没有点名具体节点（如「都」「全部」「通过的」）时，不要传节点 id 参数，系统会作用于全部符合条件的节点；"
              "只有当前选中了节点或用户点名时才传 id。与画布无关的问题用 clarify 简短说明你能做什么。\n"
              f"当前画布节点（id | 标题 | 类型 | 状态）：\n{snap}\n当前选中：{selection or '无'}")
    msg = await llm.chat([{"role": "system", "content": system}, {"role": "user", "content": text}], tools=INTENT_TOOLS, task="agent")
    call = (msg.get("tool_calls") or [None])[0]
    if not call:
        raise ValueError("no tool call")  # 交给规则解析兜底
    args = json.loads(call["function"].get("arguments") or "{}")
    return {"name": call["function"]["name"], **args}


async def parse_intent(db: Session, project: Project, text: str, selection: list[str]) -> dict:
    if settings_store.llm_enabled():
        try:
            return await llm_intent(db, project, text, selection)
        except Exception:
            pass
    return rule_intent(text, selection)


def _propose(db: Session, project: Project, intent: dict, summary: str, steps: list[str], cost: str, ops: list[dict]) -> Patch:
    p = Patch(id=new_id("pt"), project_id=project.id, base_version=project.version, intent=intent, summary=summary,
              steps=steps, cost=cost, needs_review=True, ops=ops, status="proposed")
    db.add(p)
    m = ChatMessage(project_id=project.id, role="plan", content={"patch_id": p.id, "summary": summary, "steps": steps,
                                                                 "cost": cost, "needs_review": True, "count": intent.get("count"),
                                                                 "state": "proposed"})
    db.add(m)
    db.flush()
    p.chat_message_id = m.id
    return p


def _ghost_create(db: Session, pid: str, temp_id: str, type_: str, k: int, sub: str, data: dict) -> dict:
    x, y = canvas.next_pos(db, pid, type_, k)
    return {"op": "create_node", "temp_id": temp_id, "type": type_, "x": x, "y": y, "sub": sub, "data": data}


def compile_scripts(db: Session, project: Project, intent: dict, selection: list[str]) -> Patch | str:
    count = max(1, min(6, int(intent.get("count") or 3)))
    sp, aud = intent.get("selling_point") or "续航", intent.get("audience") or "小商贩"
    ads = canvas.nodes_of(db, project.id, "ad")
    src = None
    if intent.get("ref_ad_node_id"):
        src = next((n for n in ads if n.id == intent["ref_ad_node_id"]), None)
    if not src and intent.get("ref_ad_no"):
        src = next((n for n in ads if (n.data or {}).get("ref_ad_no") == intent["ref_ad_no"]), None)
    if not src:
        src = next((n for n in ads if n.id in selection), None) or (ads[-1] if ads else None)
    if not src:
        return "画布上还没有爆款节点，先去爆款库选一条，点「一键洗剧本」。"
    aud_node = next((n for n in canvas.nodes_of(db, project.id, "aud") if (n.data or {}).get("audience") == aud), None)
    if not aud_node:
        return f"资产库里还没有「{aud}」人群包。"
    ops, k0 = [], (project.counters or {}).get("script", 0)
    for k in range(count):
        tid = f"g{k}"
        ops.append(_ghost_create(db, project.id, tid, "script", k, f"{sp} · {aud} · 15s",
                                 {"selling_point": sp, "audience": aud, "version": 1, "ref_ad_no": (src.data or {}).get("ref_ad_no")}))
        ops += [{"op": "connect", "from": src.id, "to": tid}, {"op": "connect", "from": aud_node.id, "to": tid},
                {"op": "run_node", "node_id": tid, "action": "generate_script"}]
    intent = {**intent, "name": "write_scripts", "count": count, "selling_point": sp, "audience": aud, "ref_ad_node_id": src.id}
    steps = [f"新增 {count} 个剧本节点（{sp} · {aud}），编号 #{k0 + 1}–#{k0 + count}",
             f"新增 {count * 2} 条连线：{src.title}、{aud_node.title} → 新剧本",
             "生成分镜与本地语言口播（英语 / 皮钦语）", "完成后逐个提交审核"]
    return _propose(db, project, intent, "写剧本", steps, "约 0.2 积分（文本生成）", ops)


def _has_child(db: Session, node_id: str, type_: str) -> bool:
    return any(n.type == type_ for n in canvas.downstream(db, node_id))


def compile_videos(db: Session, project: Project, intent: dict, selection: list[str]) -> Patch | str:
    scripts = canvas.nodes_of(db, project.id, "script")
    ids = intent.get("script_node_ids") or [i for i in selection if any(s.id == i for s in scripts)]
    pool = [s for s in scripts if not ids or s.id in ids]
    ok = [s for s in pool if s.status == "pass" and not _has_child(db, s.id, "video")]
    if not ok:
        waiting = [s for s in pool if s.status in ("wait", "run", "reject")]
        if waiting:
            return "还没有可生成视频的剧本：需要先审核通过。待处理：" + " ".join(ref(s) for s in waiting)
        return "没有已通过且未生成视频的剧本，先写剧本吧。"
    ops = []
    for k, s in enumerate(ok):
        tid = f"v{k}"
        ops += [_ghost_create(db, project.id, tid, "video", k, f"来自 {s.title} · 15s", {"script_id": s.id}),
                {"op": "connect", "from": s.id, "to": tid}, {"op": "run_node", "node_id": tid, "action": "generate_video"}]
    seconds = len(ok) * 15
    steps = [f"为 {len(ok)} 个已通过的剧本各新增 1 个视频节点", "按镜调用 Seedance（9:16 · 1080p），产品镜头使用官方素材",
             "TTS 配音 + 字幕 + BGM 合成，自动质检", "完成后逐个提交审核"]
    return _propose(db, project, {"name": "generate_videos", "script_node_ids": [s.id for s in ok]}, "生成视频", steps,
                    f"约 {seconds} 秒 Seedance 生成（按实际单价计费，确认后才会调用）", ops)


def compile_eval(db: Session, project: Project, intent: dict, selection: list[str]) -> Patch | str:
    videos = canvas.nodes_of(db, project.id, "video")
    ids = intent.get("video_node_ids") or [i for i in selection if any(v.id == i for v in videos)]
    pool = [v for v in videos if not ids or v.id in ids]
    ok = [v for v in pool if v.status == "pass" and not _has_child(db, v.id, "eval")]
    if not ok:
        if pool:
            return "评测需要已通过审核的视频。当前：" + "，".join(f"{ref(v)} {canvas.STATUS_ZH.get(v.status, v.status)}" for v in pool)
        return "还没有视频，先说「生成视频」。"
    ops = [_ghost_create(db, project.id, "e0", "eval", 0, f"40 Agent · {len(ok)} 个视频", {"video_ids": [v.id for v in ok]})]
    ops += [{"op": "connect", "from": v.id, "to": "e0"} for v in ok] + [{"op": "run_node", "node_id": "e0", "action": "evaluate"}]
    steps = [f"新增 1 个评测节点，覆盖 {len(ok)} 个视频", f"按「{project.market}」目标人群抽取 40 个虚拟用户画像",
             "逐秒记录划走 / 看完 / 点击，预测 CTR 与完播率", "输出入选名单与建议人群，提交审核"]
    return _propose(db, project, {"name": "run_evaluation", "video_node_ids": [v.id for v in ok]}, "40 Agent 评测", steps,
                    "约 1.5 积分（多模态模型）", ops)


def compile_delivery(db: Session, project: Project, intent: dict, selection: list[str]) -> Patch | str:
    evals = canvas.nodes_of(db, project.id, "eval")
    ev = next((e for e in reversed(evals) if e.status == "pass" and not _has_child(db, e.id, "deliver")), None)
    if not ev:
        if evals:
            return f"投放方案需要评测结论先通过审核：{ref(evals[-1])} {canvas.STATUS_ZH.get(evals[-1].status, evals[-1].status)}。"
        return "还没有评测结果，先说「跑评测」。"
    picks = (ev.data or {}).get("picks", [])
    ops = [_ghost_create(db, project.id, "d0", "deliver", 0, "TikTok · 测试期", {"eval_id": ev.id}),
           {"op": "connect", "from": ev.id, "to": "d0"}, {"op": "run_node", "node_id": "d0", "action": "plan_delivery"}]
    steps = [f"新增 1 个投放节点（TikTok · {project.market}）", f"入选素材 {len(picks)} 条，按建议人群建广告组",
             "测试期预算 $30/天 × 3 天，CPA 上限 $2.5", "生成投放方案卡并提交审核；通过后在投放中心由你点击下发"]
    return _propose(db, project, {"name": "plan_delivery", "eval_id": ev.id}, "生成投放方案", steps,
                    "方案生成免费；下发后测试期预算约 $180", ops)


def compile_iterate(db: Session, project: Project, opt: Node) -> Patch:
    scripts = [s for s in canvas.nodes_of(db, project.id, "script") if s.status == "pass"]
    best = scripts[0] if scripts else None
    sp = (best.data or {}).get("selling_point", "续航") if best else "续航"
    aud = (best.data or {}).get("audience", "小商贩") if best else "小商贩"
    ops = []
    for k in range(2):
        tid = f"i{k}"
        ops += [_ghost_create(db, project.id, tid, "script", k, f"迭代 · {sp} · v2",
                              {"selling_point": sp, "audience": aud, "version": 1, "iterate_from": best.id if best else None}),
                {"op": "connect", "from": opt.id, "to": tid}, {"op": "run_node", "node_id": tid, "action": "generate_script"}]
    steps = [f"基于 {best.title if best else '跑赢剧本'} 的跑赢元素新增 2 个剧本变体", "保留「对比实测」钩子，替换第 4–6 秒流失镜头",
             f"连线：{opt.title} → 新剧本", "完成后提交审核，进入下一轮"]
    return _propose(db, project, {"name": "iterate", "opt_id": opt.id}, "迭代再生成", steps, "约 0.1 积分", ops)


def query_best(db: Session, project: Project) -> str:
    results = [r for e in canvas.nodes_of(db, project.id, "eval") for r in (e.data or {}).get("results", [])]
    if not results:
        return "还没有评测结果，跑完评测后我可以告诉你哪个视频预测 CTR 最高。"
    b = max(results, key=lambda r: r["ctr"])
    return f"预测 CTR 最高的是 {{{{{b['id']}}}}}：{b['ctr']}%，预测完播率 {b['vtr']}%，评测得分 {b['score']}。已在画布上高亮。"


def summary(db: Session, project: Project) -> str:
    from app.models import ReviewTask
    c = {t: len(canvas.nodes_of(db, project.id, t)) for t in ("script", "video", "eval", "deliver")}
    w = db.query(ReviewTask).filter(ReviewTask.project_id == project.id, ReviewTask.status == "wait").all()
    tail = ("：" + " ".join("{{" + r.node_id + "}}" for r in w)) if w else ""
    return f"当前画布：剧本 {c['script']}、视频 {c['video']}、评测 {c['eval']}、投放 {c['deliver']}。待审核 {len(w)} 条{tail}。"


async def handle(db: Session, project: Project, text: str, selection: list[str]) -> dict:
    """处理一条用户指令，返回 {effects}；消息与补丁写入数据库。"""
    say(db, project.id, text, role="user")
    old = canvas.pending_patch(db, project.id)
    if old:
        old.status = "superseded"
        set_card_state(db, old, "superseded")
    intent = await parse_intent(db, project, text, selection)
    name, effects = intent.get("name"), []
    if name == "undo":
        p = canvas.undo_last(db, project)
        say(db, project.id, "没有可撤销的 Agent 操作。" if not p else f"已撤销「{p.summary}」。")
        if p:
            set_card_state(db, p, "undone")
    elif name == "layout":
        canvas.layout(db, project)
        canvas.bump(project)
        say(db, project.id, "已按「爆款/资产 → 剧本 → 视频 → 评测 → 投放 → 数据 → 优化」从左到右整理画布（布局类操作免确认，可撤销）。")
    elif name == "query_best":
        txt = query_best(db, project)
        say(db, project.id, txt)
        effects = [{"type": "highlight", "node_ids": re.findall(r"\{\{(\w+)\}\}", txt)}]
    elif name == "summary":
        say(db, project.id, summary(db, project))
    elif name == "clarify":
        say(db, project.id, intent.get("question") or HELP)
    elif name in ("write_scripts", "generate_videos", "run_evaluation", "plan_delivery"):
        fn = {"write_scripts": compile_scripts, "generate_videos": compile_videos,
              "run_evaluation": compile_eval, "plan_delivery": compile_delivery}[name]
        res = fn(db, project, intent, selection)
        if isinstance(res, str):
            say(db, project.id, res)
        else:
            say(db, project.id, "画布上紫色虚线框是预览，确认后执行；可以先调整数量或取消。")
    else:
        say(db, project.id, HELP)
    db.commit()
    return {"effects": effects}


def adjust(db: Session, project: Project, patch: Patch, count: int) -> Patch | str:
    """调整计划卡的数量：作废旧补丁，按新参数重新编译。"""
    patch.status = "superseded"
    set_card_state(db, patch, "superseded")
    db.flush()
    intent = {**patch.intent, "count": max(1, min(6, count))}
    return compile_scripts(db, project, intent, [])
