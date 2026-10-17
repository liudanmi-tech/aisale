"""投放 Agent：理解指令 → 生成画布补丁（计划卡 + 预览）→ 用户确认后应用。

Agent 只能通过画布工具改画布：查询、创建节点、连线、布局、运行节点、撤销。
上游未通过审核时拒绝执行下游指令，并指出卡在哪个节点。
"""
import json
import re

from sqlalchemy.orm import Session

from app import canvas, config, settings_store, wash_plan
from app.adapters import llm
from app.models import ChatMessage, Node, Patch, Project, RefAd, ReviewTask, new_id

INTENT_TOOLS = [
    {"type": "function", "function": {"name": "write_scripts", "description": "给某个人群写新剧本。人群和卖点可以是用户说的任意描述，不限于已有的人群包",
        "parameters": {"type": "object", "properties": {
            "count": {"type": "integer", "minimum": 1, "maximum": 6},
            "selling_point": {"type": "string", "description": "主卖点，简短。常见：续航 / 拍照 / 存储，也可以是用户说的其他卖点（如 快充、大屏、游戏）"},
            "audience": {"type": "string", "description": "人群名称，简短（如 小商贩、学生、大学生、宝妈）；能对上画布上已有人群包时用它的名字"},
            "audience_tags": {"type": "array", "items": {"type": "string"}, "description": "用户圈选或提到的人群标签原文（职业、兴趣、信仰、痛点、语言等），没有就省略"},
            "language": {"type": "string", "description": "口播语言（如 皮钦语、阿姆哈拉语、斯瓦希里语）；用户没说就省略"},
            "model_sku": {"type": "string", "description": "机型（如 Infinix Hot 60）；用户没说就省略"},
            "ref_ad_node_id": {"type": "string", "description": "参考的爆款节点 id，不确定时省略"}},
            "required": ["count", "selling_point", "audience"]}}},
    {"type": "function", "function": {"name": "revise_script", "description": "按用户的修改意见改已有的剧本（选中剧本节点后说怎么改）",
        "parameters": {"type": "object", "properties": {
            "instruction": {"type": "string", "description": "用户的修改意见原话"},
            "script_node_ids": {"type": "array", "items": {"type": "string"}, "description": "要改的剧本节点 id；用户选中或点名时才传"}},
            "required": ["instruction"]}}},
    {"type": "function", "function": {"name": "generate_videos", "description": "为已通过审核的剧本生成视频",
        "parameters": {"type": "object", "properties": {"script_node_ids": {"type": "array", "items": {"type": "string"}}}}}},
    {"type": "function", "function": {"name": "compose_videos", "description": "把已通过的视频的各镜片段拼接成完整成片（加字幕和贴片）；已有成片的重新合成",
        "parameters": {"type": "object", "properties": {"video_node_ids": {"type": "array", "items": {"type": "string"}}}}}},
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

HELP = ("我可以：写剧本（如「给学生写 2 个拍照剧本」）、改剧本（选中剧本后说怎么改）、生成视频、合成成片、跑评测、生成投放方案、整理画布、"
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


REVISE_WORDS = "改|优化|调整|换成|换掉|换个|加上|加一|删掉|去掉|重写|润色|更口语|更本地|缩短|加长|口播|第.镜"


def rule_intent(text: str, selection: list[str], selected_types: set[str] | None = None, has_scripts: bool = False) -> dict:
    t = re.sub(r"\s", "", text)
    can_revise = "script" in (selected_types or set()) or (has_scripts and not selection)
    if can_revise and re.search(REVISE_WORDS, t) and not re.search(r"写\d+个|写[一两三四五六]个", t):
        return {"name": "revise_script", "instruction": text.strip()}
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
        tags = [x for x in re.split(r"[、,，/]", (re.search(r"「([^」]+)」", text) or [None, ""])[1]) if x.strip()]
        lang = re.search(r"用(\S{1,8}?语)口播", t)
        model = re.search(r"(TECNO|Infinix|itel)\s?[A-Za-z]*\s?\d+\s?(Pro|Ultra|Plus)?", text, re.I)
        aud = ("学生" if "学生" in t else ("年轻家庭" if re.search("家庭|婚礼|斋月", t) else "小商贩")) if not tags else tags[0]
        return {"name": "write_scripts", "count": min(6, int(m.group(1))) if m else 3,
                "selling_point": "拍照" if re.search("拍照|夜拍|自拍|美颜", t) else ("存储" if re.search("存储|内存", t) else "续航"),
                "audience": aud, "audience_tags": tags or None, "language": lang.group(1) if lang else None,
                "model_sku": model.group(0).strip() if model else None, "ref_ad_no": int(ad.group(1)) if ad else None}
    if re.search("合成|成片|拼接", t):
        return {"name": "compose_videos"}
    if re.search("视频", t):
        return {"name": "generate_videos"}
    if re.search("评测|打分", t):
        return {"name": "run_evaluation"}
    if re.search("投放|下发|方案", t):
        return {"name": "plan_delivery"}
    return {"name": "help"}


HISTORY_MESSAGES, HISTORY_CHARS, HISTORY_EACH = 12, 6000, 800
FOLLOW_UP = r"^(继续|好的?|可以|行|嗯|对|是的?|就这样|就按(这个|刚才|之前|你说)的?|按(刚才|之前|上面)的?|开始吧?|写吧|执行|确定|没问题|编写剧本|写剧本|帮我写)[!！。.~]*$"


def history(db: Session, pid: str) -> list[dict]:
    """滑动窗口记忆：最近 12 条对话（不含刚收到的这条），总长不超过 6000 字，越旧的越先丢。"""
    rows = (db.query(ChatMessage).filter(ChatMessage.project_id == pid, ChatMessage.role.in_(("user", "agent")))
            .order_by(ChatMessage.id.desc()).limit(HISTORY_MESSAGES + 1).all())[1:]  # [0] 是刚写入的当前消息
    out, total = [], 0
    for m in rows:
        text = re.sub(r"\{\{(\w+)\}\}", r"[\1]", (m.content or {}).get("text") or "").strip()
        if not text:
            continue
        text = text[:HISTORY_EACH]
        if total + len(text) > HISTORY_CHARS:
            break
        total += len(text)
        out.append({"role": "user" if m.role == "user" else "assistant", "content": text})
    return out[::-1]


def _with_context(db: Session, pid: str, text: str) -> str:
    """规则解析兜底时的记忆：「继续」「编写剧本」这类短句，接上最近一条真正的指令。"""
    if not re.match(FOLLOW_UP, re.sub(r"\s", "", text)):
        return text
    for h in reversed(history(db, pid)):
        if h["role"] == "user" and not re.match(FOLLOW_UP, re.sub(r"\s", "", h["content"])):
            return f"{h['content']}（{text}）"
    return text


async def llm_intent(db: Session, project: Project, text: str, selection: list[str]) -> dict:
    nodes = canvas.nodes_of(db, project.id)
    snap = "\n".join(f"- {n.id} | {n.title} | {n.type} | {canvas.STATUS_ZH.get(n.status, n.status)}" for n in nodes)
    system = ("你是 TECNO 手机海外投放平台的画布 Agent，只能通过给定工具操作画布。"
              "根据用户指令选择且只选择一个工具。节点引用一律使用节点 id。\n"
              "卖点归一：夜拍/拍照/相机/自拍 → 拍照；电池/续航/停电/充电 → 续航；内存/存储/装照片 → 存储；其他卖点照用户原话。"
              "人群：能对上画布上已有人群包就用它的名字，对不上就用用户的说法（如 大学生），标签放进 audience_tags。数量用阿拉伯数字（两个 → 2）。\n"
              "用户没有点名具体节点（如「都」「全部」「通过的」）时，不要传节点 id 参数，系统会作用于全部符合条件的节点；"
              "只有当前选中了节点或用户点名时才传 id。选中了剧本、要求修改它（改口播、换场景、改第几镜、更口语等）时用 revise_script，"
              "instruction 填用户原话；要写新剧本才用 write_scripts。与画布无关的问题用 clarify 简短说明你能做什么。\n"
              "前面的对话是记忆：用户说「继续」「好的」「就按刚才的」「编写剧本」这类省略的话时，沿用之前说过的人群、标签、卖点、机型、语言和数量，直接执行，不要再反问。"
              "人群和卖点不限于已有的人群包和三个常用卖点，用户说什么就用什么（会自动新建人群包）。\n"
              f"项目：{project.brand} {project.model_sku} · 市场 {project.market}\n"
              f"当前画布节点（id | 标题 | 类型 | 状态）：\n{snap}\n当前选中：{selection or '无'}")
    msg = await llm.chat([{"role": "system", "content": system}, *history(db, project.id), {"role": "user", "content": text}], tools=INTENT_TOOLS, task="agent")
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
    nodes = canvas.nodes_of(db, project.id)
    types = {n.type for n in nodes if n.id in selection}
    return rule_intent(_with_context(db, project.id, text), selection, types, has_scripts=any(n.type == "script" for n in nodes))


def revise_scripts(db: Session, project: Project, intent: dict, selection: list[str]) -> str:
    """在原剧本节点上按意见修改：没提到的镜头保留，改完重新提交审核，改过的镜头自动重画分镜。"""
    from app import workflows  # workflows 依赖本模块，延迟导入
    scripts = canvas.nodes_of(db, project.id, "script")
    ids = intent.get("script_node_ids") or [i for i in selection if any(n.id == i for n in scripts)]
    if not ids and len(scripts) == 1:
        ids = [scripts[0].id]
    targets = [n for n in scripts if n.id in ids]
    if not targets:
        return "要改哪个剧本？先在画布上点选剧本节点（或点节点上的「优化剧本」），再告诉我怎么改。"
    instruction = (intent.get("instruction") or "").strip()
    busy = [n for n in targets if n.status == "run"]
    todo = [n for n in targets if n.status != "run"]
    for n in todo:
        for r in db.query(ReviewTask).filter(ReviewTask.node_id == n.id, ReviewTask.status == "wait"):
            r.status, r.comment = "cancel", f"改稿：{instruction}"
        n.status = "run"
        canvas.audit(db, project.id, "agent", "revise_script", {"node_id": n.id, "instruction": instruction})
    db.commit()
    for n in todo:
        wn = next((u for u in canvas.upstream(db, n.id) if u.type == "wash"), None)
        if wn and instruction:  # 有洗稿方案：意见记进方案，以后按方案重写也会执行
            wd = dict(wn.data or {})
            wn.data = {**wd, "notes": [*(wd.get("notes") or []), instruction][-8:]}
    db.commit()
    for n in todo:
        workflows.rework(n, instruction)
    parts = []
    if todo:
        washed = [n for n in todo if any(u.type == "wash" for u in canvas.upstream(db, n.id))]
        parts.append(f"好的，正在按「{instruction}」修改 {' '.join(ref(n) for n in todo)}：没提到的镜头保持不变，改完重新提交你审核，改过的镜头会自动重画手绘分镜。"
                     + ("这条意见也记进了它的洗稿方案，以后按方案重写也会照做。" if washed else ""))
    if busy:
        parts.append(f"{' '.join(ref(n) for n in busy)} 还在生成中，等它完成后再改。")
    return "\n".join(parts)


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
    tags = [t for t in (intent.get("audience_tags") or []) if t][:12]
    lang = intent.get("language") or ""
    model = intent.get("model_sku") or ""
    aud_node = next((n for n in canvas.nodes_of(db, project.id, "aud") if (n.data or {}).get("audience") == aud
                     and (not tags or set(tags) <= set((n.data or {}).get("tags") or tags))), None)
    ops, k0 = [], (project.counters or {}).get("script", 0)
    if aud_node:
        aud_id, aud_title = aud_node.id, aud_node.title
    else:
        # 画布上还没有这个人群：按用户说的人群和标签新建一个人群包
        aud_id, aud_title = "a0", f"人群包 · {aud}"
        ops.append({**_ghost_create(db, project.id, "a0", "aud", 0, f"{project.market} · " + ("、".join(tags[:4]) if tags else aud),
                                    {"audience": aud, "tags": tags, "market": project.market}), "status": "pass", "title": aud_title})
    if src:
        src_id, src_title, ref_no = src.id, src.title, (src.data or {}).get("ref_ad_no")
    else:
        # 画布上还没有爆款：从爆款库挑同市场、同卖点、爆款分最高的一条，随剧本一起放上画布
        lib = db.query(RefAd).order_by(RefAd.hot_score.desc()).all()
        ad = (next((a for a in lib if a.market == project.market and a.selling_point == sp), None)
              or next((a for a in lib if a.selling_point == sp), None) or (lib[0] if lib else None))
        if not ad:
            return "爆款库是空的，先导入爆款再写剧本。"
        src_id, src_title, ref_no = "ad0", f"爆款 #{ad.no}", ad.no
        ops.append({**_ghost_create(db, project.id, "ad0", "ad", 0, f"{ad.hook} · {ad.market}", {"ref_ad_no": ad.no}),
                    "status": "pass", "title": src_title})
    # 每个剧本前面先有一个洗稿方案：拆要素、评估相似度、定档位，人确认后剧本才写。写 3 个时高 / 中 / 低三档各一个
    tiers = ([None] if count == 1 else [["high", "mid", "low"][k % 3] for k in range(count)])
    brief = {"selling_point": sp, "audience": aud, "audience_tags": tags, "language": lang, "model_sku": model, "ref_ad_no": ref_no}
    for k in range(count):
        wid, tid = f"w{k}", f"g{k}"
        tier = tiers[k]
        label = wash_plan.TIERS[tier]["label"] if tier else "按相似度推荐档位"
        ops.append(_ghost_create(db, project.id, wid, "wash", k, f"{label} · 参考 {src_title}",
                                 {**brief, "tier": tier, "tier_source": "agent" if tier else None}))
        ops.append({**_ghost_create(db, project.id, tid, "script", k, f"{sp} · {aud} · 等洗稿方案确认", {**brief, "version": 1})})
        ops += [{"op": "connect", "from": src_id, "to": wid}, {"op": "connect", "from": aud_id, "to": wid},
                {"op": "connect", "from": wid, "to": tid}, {"op": "run_node", "node_id": wid, "action": "plan_wash"}]
    intent = {**intent, "name": "write_scripts", "count": count, "selling_point": sp, "audience": aud, "ref_ad_node_id": src.id if src else None}
    steps = ([] if src else [f"从爆款库选出最匹配的 {src_title}（{ad.title}，爆款分 {ad.hot_score}）放到画布"])
    if not aud_node:
        steps.append(f"新建人群包「{aud}」" + (f"：{'、'.join(tags)}" if tags else ""))
    steps += [f"新增 {count} 个洗稿方案（{'、'.join(wash_plan.TIERS[t]['label'] for t in tiers) if tiers[0] else '按相似度推荐档位'}）：拆分钩子、人物、场景、节奏、台词、镜头，评估相似度",
              f"每个方案后面接一个剧本节点（{sp} · {aud}{' · ' + model if model else ''}），编号 #{k0 + 1}–#{k0 + count}",
              "方案提交你确认（可以改档位、改每一行）→ 确认后按方案写分镜与" + (lang or "本地语言") + "口播，并画手绘分镜 → 提交你审核"]
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
    steps = [f"为 {len(ok)} 个已通过的剧本各新增 1 个视频节点", "选角置景：按剧本拆出演员、场景、商品，优先复用素材库，画布上可换",
             "每镜生成关键帧（参考分镜、演员定妆照、场景图、商品实拍图）", "关键帧走 Seedance 图生视频，完成后提交审核"]
    return _propose(db, project, {"name": "generate_videos", "script_node_ids": [s.id for s in ok]}, "生成视频", steps,
                    f"约 {seconds} 秒 Seedance 生成（按实际单价计费，确认后才会调用）", ops)


def compile_compose(db: Session, project: Project, videos: list[Node]) -> Patch | str:
    """视频通过后：每条视频接一个成片节点，把片段拼成完整成片。"""
    ok = [v for v in videos if v.status == "pass" and not _has_child(db, v.id, "cut")]
    if not ok:
        return "这些视频已经有成片了。"
    ops = []
    for k, v in enumerate(ok):
        tid = f"c{k}"
        ops += [_ghost_create(db, project.id, tid, "cut", k, "成片 · 拼接中", {"video_id": v.id, "captions": True}),
                {"op": "connect", "from": v.id, "to": tid}, {"op": "run_node", "node_id": tid, "action": "compose"}]
    steps = [f"为 {len(ok)} 条视频各新增 1 个成片节点", "按剧本时长剪好每镜片段，顺序拼成 9:16 成片", "烧上口播字幕和卖点贴片", "合成完自动进入 40 人评测"]
    return _propose(db, project, {"name": "compose", "video_node_ids": [v.id for v in ok]}, "合成成片", steps, "不额外收费（本地 ffmpeg）", ops)


def backfill_cuts(db: Session) -> list[str]:
    """成片节点上线前就通过的视频：每个项目补一次成片节点（之后删掉也不会再补）。返回要合成的成片节点。"""
    out = []
    for p in db.query(Project):
        if (p.flags or {}).get("cuts_backfilled"):
            continue
        made = []
        for v in canvas.nodes_of(db, p.id, "video"):
            if v.status == "pass" and not _has_child(db, v.id, "cut"):
                c = canvas.create_node(db, p, "cut", sub="合成中…", status="run",
                                       data={"video_id": v.id, "captions": True, "backfill": True})
                canvas.connect(db, p.id, v.id, c.id)
                made.append(c)
        p.flags = {**(p.flags or {}), "cuts_backfilled": True}
        if made:
            canvas.layout(db, p)
            canvas.bump(p)
            say(db, p.id, "新增了「成片」节点：已为通过的视频 " + " ".join(ref(c) for c in made) + " 补上成片，正在把片段拼成完整视频。")
            out += [c.id for c in made]
    db.commit()
    return out


def compose_videos(db: Session, project: Project, intent: dict, selection: list[str], runs: list) -> str:
    """聊天里说「合成成片」：没有成片的视频新建成片节点，已有的重新合成（本地 ffmpeg，免费，直接执行不用确认）。"""
    ids = set(intent.get("video_node_ids") or selection)
    vids = [v for v in canvas.nodes_of(db, project.id, "video") if v.status == "pass"]
    cuts = canvas.nodes_of(db, project.id, "cut")
    if ids:
        vids = [v for v in vids if v.id in ids or any(c.id in ids and (c.data or {}).get("video_id") == v.id for c in cuts)]
    if not vids:
        return "还没有通过审核的视频，视频通过后会自动拼成成片。"
    done = []
    for v in vids:
        c = next((c for c in cuts if (c.data or {}).get("video_id") == v.id), None)
        if c and c.status == "run":
            continue
        if not c:
            c = canvas.create_node(db, project, "cut", data={"video_id": v.id, "captions": True})
            canvas.connect(db, project.id, v.id, c.id)
        c.status, c.sub = "run", "合成中…"
        runs.append((c.id, "compose"))
        done.append(c)
    canvas.bump(project)
    if not done:
        return "成片正在合成中，稍等。"
    return "开始合成：" + " ".join(ref(c) for c in done) + "（按剧本时长剪好每镜、拼成 9:16，加字幕和贴片）。"


def _eval_sources(db: Session, project: Project) -> list[Node]:
    """评测的对象：成片节点（没有成片的老项目直接用视频节点）。"""
    cuts = canvas.nodes_of(db, project.id, "cut")
    if cuts:
        return cuts
    return canvas.nodes_of(db, project.id, "video")


def compile_eval(db: Session, project: Project, intent: dict, selection: list[str]) -> Patch | str:
    videos = _eval_sources(db, project)
    want = set(intent.get("video_node_ids") or selection)
    # 选中 / 点名的是视频节点时，换成它的成片
    ids = [v.id for v in videos if v.id in want or (v.data or {}).get("video_id") in want]
    pool = [v for v in videos if not ids or v.id in ids]
    ok = [v for v in pool if v.status == "pass" and not _has_child(db, v.id, "eval")]
    if not ok:
        if pool:
            return "评测需要已合成好的成片（或已通过审核的视频）。当前：" + "，".join(f"{ref(v)} {canvas.STATUS_ZH.get(v.status, v.status)}" for v in pool)
        return "还没有视频，先说「生成视频」。"
    ops = [_ghost_create(db, project.id, "e0", "eval", 0, f"40 Agent · {len(ok)} 条成片", {"video_ids": [v.id for v in ok]})]
    ops += [{"op": "connect", "from": v.id, "to": "e0"} for v in ok] + [{"op": "run_node", "node_id": "e0", "action": "evaluate"}]
    steps = [f"新增 1 个评测节点，覆盖 {len(ok)} 条成片", f"按「{project.market}」目标人群抽取 40 个虚拟用户画像",
             "40 个独立 Agent 逐镜看关键帧、对比平时的广告打分，按基准流失率换算留存、完播和点击意向（CTR 未校准）", "输出入选名单与建议人群，提交审核"]
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


def auto_advance(db: Session, project: Project, node: Node) -> list[tuple[str, str]]:
    """审核通过后自动走下一步（审核即同意）：剧本 → 视频；视频通过 → 合成成片；成片都好了 → 一起评测；评测 → 投放方案。
    下发投放要真花钱，仍由人点击。返回要启动的 (节点, 动作)。"""
    if node.type == "wash":
        # 洗稿方案确认了：下游剧本按这张表写分镜（已经写过的按新方案重写）
        scripts = [x for x in canvas.downstream(db, node.id) if x.type == "script" and x.status != "run"]
        for x in scripts:
            for r in db.query(ReviewTask).filter(ReviewTask.node_id == x.id, ReviewTask.status == "wait"):
                r.status, r.comment = "cancel", "洗稿方案重新确认"
            x.status, x.sub = "run", "按洗稿方案写分镜…"
        if not scripts:
            say(db, project.id, f"{ref(node)} 已确认，但后面没有连着剧本节点。")
            return []
        say(db, project.id, f"{ref(node)} 已确认，开始按方案写 " + " ".join(ref(x) for x in scripts) + "。写好后画手绘分镜，提交你审核。")
        return [(x.id, "generate_script") for x in scripts]
    if node.type == "script":
        res = compile_videos(db, project, {"script_node_ids": [node.id]}, [])
        label = f"{ref(node)} 已通过，自动开始生成视频（Seedance 按镜生成，产品镜头用官方素材）"
    elif node.type == "video":
        res = compile_compose(db, project, [node])
        if isinstance(res, str):
            # 已经有成片（例如重生成了几镜又通过）：成片跟着重新合成
            cuts = [c for c in canvas.nodes_of(db, project.id, "cut") if (c.data or {}).get("video_id") == node.id and c.status != "run"]
            for c in cuts:
                c.status, c.sub = "run", "视频已更新，重新合成中…"
            if cuts:
                say(db, project.id, f"{ref(node)} 已更新，自动重新合成 " + " ".join(ref(c) for c in cuts) + "。")
            return [(c.id, "compose") for c in cuts]
        label = f"{ref(node)} 已通过，自动把片段拼成成片（剪到剧本时长、加字幕和贴片）"
    elif node.type == "cut":
        vid = (node.data or {}).get("video_id")
        if (node.data or {}).get("backfill") and vid and _has_child(db, vid, "eval"):
            say(db, project.id, f"{ref(node)} 合成好了，可以在画布上播放。原来的评测是按视频跑的，要按成片重新评测就说「跑评测」。")
            return []
        if _has_child(db, node.id, "eval"):
            say(db, project.id, f"{ref(node)} 已重新合成。评测是按旧成片跑的，需要的话在评测节点上点「重新评测」。")
            return []
        pending = [v for v in canvas.nodes_of(db, project.id, "video") if v.status in ("none", "run", "wait", "input")]
        pending += [c for c in canvas.nodes_of(db, project.id, "cut") if c.id != node.id and c.status in ("none", "run")]
        if pending:
            say(db, project.id, f"{ref(node)} 合成好了。还有 {' '.join(ref(v) for v in pending)} 没完成，全部好了自动一起跑 40 人评测。")
            return []
        res = compile_eval(db, project, {}, [])
        label = f"{ref(node)} 合成好了，成片都齐了，自动开始 40 人评测"
    elif node.type == "eval":
        res = compile_delivery(db, project, {}, [])
        label = f"{ref(node)} 已通过，自动生成 TikTok 投放方案（下发前还会请你确认）"
    else:
        return []
    if isinstance(res, str):  # 没有可往下走的（例如已经生成过）：只提示
        say(db, project.id, f"{ref(node)} 已通过审核。{res}")
        return []
    runs = canvas.apply_patch(db, project, res)
    set_card_state(db, res, "applied")
    created = [db.get(Node, i) for i in res.undo.get("nodes", [])]
    say(db, project.id, f"{label}：" + " ".join(ref(n) for n in created if n) + "。完成后提交你审核，可撤销。")
    return runs


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


CONFIRM_WORDS = "确认选角|选角没问题|开始生成|继续生成|接着生成|确认.*继续|就这样生成"


def confirm_videos(db: Session, waiting: list[Node], selection: list[str]) -> str:
    """在对话里确认选角：选中了视频就只确认选中的，否则确认所有在等确认的视频。"""
    from app import production  # production 依赖本模块，这里延迟导入
    from app.events import spawn
    picked = [n for n in waiting if n.id in selection] or waiting
    ok, blocked = [], []
    for n in picked:
        try:
            production.confirm_cast(n.id, db)
        except ValueError as e:
            blocked.append(f"{ref(n)}：{e}")
            continue
        canvas.audit(db, n.project_id, "agent", "confirm_cast", {"node_id": n.id})
        ok.append(n)
    db.commit()  # 先提交确认，后台任务才读得到
    for n in ok:
        spawn(production.run(n.id))
    ok = [ref(n) for n in ok]
    parts = ([f"选角已确认，{'、'.join(ok)} 开始画关键帧，每镜画完先质检再生成视频。"] if ok else []) + blocked
    return "；".join(parts)


async def handle(db: Session, project: Project, text: str, selection: list[str]) -> dict:
    """处理一条用户指令，返回 {effects}；消息与补丁写入数据库。"""
    say(db, project.id, text, role="user")
    old = canvas.pending_patch(db, project.id)
    if old:
        old.status = "superseded"
        set_card_state(db, old, "superseded")
    waiting = [n for n in canvas.nodes_of(db, project.id, "video") if n.status == "input" and (n.data or {}).get("stage") == "确认选角"]
    if waiting and re.search(CONFIRM_WORDS, re.sub(r"\s", "", text)):
        say(db, project.id, confirm_videos(db, waiting, selection))
        db.commit()
        return {"effects": [{"type": "highlight", "node_ids": [n.id for n in waiting]}]}
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
    elif name == "revise_script":
        say(db, project.id, revise_scripts(db, project, intent, selection))
        effects = [{"type": "highlight", "node_ids": intent.get("script_node_ids") or selection}]
    elif name == "clarify":
        say(db, project.id, intent.get("question") or HELP)
    elif name == "compose_videos":
        runs: list = []
        say(db, project.id, compose_videos(db, project, intent, selection, runs))
        db.commit()
        from app import workflows  # 避免循环导入
        workflows.run(runs)
        return {"effects": effects}
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
