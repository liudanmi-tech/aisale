"""模块工作流：每个模块执行完产出结论 → 创建审核单 → 节点停在「待审核」。

演示版用进程内异步任务 + 数据库状态机实现审核门；生产版替换为 Temporal：
每个 run_* 对应一个子工作流，审核决定通过 Signal 唤醒（技术方案第 4 节）。
"""
import asyncio
import hashlib
import random
from datetime import date, timedelta

from app import agent, canvas, config
from app.adapters import llm, seedance, tiktok
from app.db import SessionLocal
from app.events import emit, spawn
from app.models import MetricDaily, Node, Project, RefAd
from app.seed import SHOTS


def _h(s: str, mod: int) -> int:
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % mod


def _done(db, node: Node, conclusion: str, evidence: str) -> None:
    canvas.add_review(db, node, conclusion, evidence)
    db.commit()
    emit(node.project_id, "canvas")
    emit(node.project_id, "reviews")


async def _sleep(k: float = 1.0) -> None:
    await asyncio.sleep(config.STEP_DELAY * k)


async def generate_script(node_id: str, comment: str = "") -> None:
    await _sleep()
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        d = dict(n.data or {})
        sp, aud = d.get("selling_point", "续航"), d.get("audience", "小商贩")
        shots = [s[:] for s in SHOTS.get(sp, SHOTS["续航"])]
        if config.LLM_ENABLED:
            ad = db.query(RefAd).filter(RefAd.no == d.get("ref_ad_no")).first()
            try:
                out = await llm.chat_json(
                    "你是 TECNO 手机的海外短视频广告编剧。只输出 JSON：{\"shots\": [[时长, 画面描述(中文), 口播(尼日利亚皮钦英语), 中文对照], ...]}，4 镜共 15 秒，第 3 镜为产品特写（官方素材）。",
                    f"参考爆款结构：{ad.dna if ad else '对比实测钩子'}；主卖点：{sp}；目标人群：尼日利亚 {aud}；修改意见：{comment or '无'}")
                if isinstance(out.get("shots"), list) and len(out["shots"]) >= 3:
                    shots = [[str(c) for c in row][:4] for row in out["shots"]]
            except Exception:
                pass
        elif comment:
            shots[0][3] = f"{shots[0][3]}（已按意见修改：{comment}）"
        d.update(shots=shots, version=d.get("version", 1) + (1 if comment else 0))
        n.data = d
        n.sub = f"{sp} · {aud} · 15s" + (f" · v{d['version']}" if d["version"] > 1 else "")
        _done(db, n, f"{sp}卖点 · {aud}，{len(shots)} 镜 15 秒，合规自检通过",
              "参考爆款的创意结构；卖点表述取自卖点库；与参考素材相似度 18%（阈值 40%）；禁用词 0 处")


async def generate_video(node_id: str, comment: str = "") -> None:
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        src = db.get(Node, (n.data or {}).get("script_id")) or next(iter(canvas.upstream(db, n.id)), None)
        shots = (src.data or {}).get("shots", []) if src else []
    tasks = []
    for i, s in enumerate(shots):
        if i == 2:  # 产品镜头只用官方素材，不让模型生成
            tasks.append({"shot": i + 1, "source": "official", "url": "asset://official/camon-product.mp4"})
            continue
        tid = await seedance.create_task(f"{s[1]}，9:16 竖屏，非洲城市夜景，真实质感")
        res = await seedance.wait_task(tid)
        tasks.append({"shot": i + 1, "source": "seedance", "task_id": tid, "url": res.get("video_url"), "status": res["status"]})
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        failed = [t for t in tasks if t.get("status") == "failed"]
        n.data = {**(n.data or {}), "shots": shots, "tasks": tasks, "video_url": f"mock://composed/{node_id}.mp4",
                  "qc": {"画面崩坏": not failed, "产品形态": True, "字幕错字": True, "时长与规格": True}}
        if failed:
            n.status = "failed"
            db.commit()
            emit(n.project_id, "canvas")
            return
        _done(db, n, f"Seedance 生成 {len(tasks) - 1} 镜 + 官方产品镜头 1 镜，质检 4/4 通过",
              "画面崩坏 0 · 产品形态与官方素材一致 · 字幕错字 0 · 时长 15.0s · 9:16 1080p")


def _personas(market: str) -> list[dict]:
    names = ["Ada", "Musa", "Chi", "Bola", "Femi", "Ngozi", "Tunde", "Zara"]
    return [{"id": i, "name": names[i % 8], "segment": "小商贩" if i < 24 else "学生", "age": 25 + i % 10 if i < 24 else 18 + i % 6}
            for i in range(40)]


async def evaluate(node_id: str, comment: str = "") -> None:
    await _sleep(1.5)
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        project = db.get(Project, n.project_id)
        personas = _personas(project.market)
        results = []
        for v in canvas.upstream(db, n.id):
            reactions = []
            for p in personas:
                drop = [3, 5, 8, 15, 15, 15, 2, 15, 11, 15][_h(v.id + str(p["id"]), 10)]
                reactions.append({"persona": p["id"], "drop_at": drop, "completed": drop >= 15, "clicked": drop >= 15 and _h(v.id + p["name"] + str(p["id"]), 7) == 0})
            done = sum(r["completed"] for r in reactions) / 40
            clicks = sum(r["clicked"] for r in reactions)
            score = 70 + _h(v.id, 22)
            results.append({"id": v.id, "title": v.title, "score": score, "ctr": round(1.2 + (score - 70) * 0.07, 1),
                            "vtr": round(done * 100), "clicks": clicks, "reactions": reactions})
        results.sort(key=lambda r: -r["score"])
        picks = [r["id"] for r in results if r["score"] >= 80] or ([results[0]["id"]] if results else [])
        top = results[0] if results else None
        n.data = {**(n.data or {}), "personas": personas, "results": results, "picks": picks, "score": top["score"] if top else 0,
                  "suggest_audience": "小商贩", "issue": "前 3 秒流失偏高，建议换停电场景钩子"}
        n.sub = f"最高 {top['title']} · 预测 CTR {top['ctr']}%" if top else "无视频"
        _done(db, n, f"入选 {len(picks)} 条；最高分 {n.data['score']}，建议人群：小商贩",
              "；".join(f"{r['title']}：{r['score']} 分 / CTR {r['ctr']}% / 完播 {r['vtr']}%" for r in results))


async def plan_delivery(node_id: str, comment: str = "") -> None:
    await _sleep(0.5)
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        ev = db.get(Node, (n.data or {}).get("eval_id"))
        picks = (ev.data or {}).get("picks", []) if ev else []
        plan = {"platform": "TikTok", "account": "TECNO Nigeria Ads", "campaign": "Camon · 测试",
                "adgroups": [{"name": "小商贩", "targeting": {"location": "尼日利亚", "age": "25–34", "interests": ["小生意", "手机"]}},
                             {"name": "学生", "targeting": {"location": "尼日利亚", "age": "18–24", "interests": ["拍照", "足球"]}}],
                "creatives": picks, "daily_budget": 30, "test_days": 3, "cpa_cap": 2.5,
                "guardrails": {"market_daily_cap": 500, "creative_spend_cap": 60}, "checks": {"政策预审": True, "落地页": True, "追踪参数": True}}
        n.data = {**(n.data or {}), "plan": plan, "log": []}
        _done(db, n, "TikTok · 2 个广告组 · $30/天 × 3 天 · CPA 上限 $2.5",
              "政策预审通过 · 落地页可访问 · 追踪参数完整 · 预算在市场日上限内")


ACTIONS = {"generate_script": generate_script, "generate_video": generate_video, "evaluate": evaluate, "plan_delivery": plan_delivery}
TYPE_ACTION = {"script": "generate_script", "video": "generate_video", "eval": "evaluate", "deliver": "plan_delivery"}


def run(runs: list[tuple[str, str]]) -> None:
    for node_id, action in runs:
        spawn(ACTIONS[action](node_id))


def rework(node: Node, comment: str) -> None:
    action = TYPE_ACTION.get(node.type)
    if action:
        spawn(ACTIONS[action](node.id, comment))


async def launch(node_id: str) -> None:
    """下发投放：TikTok 建广告系列 / 广告组 / 广告，上线后回收数据并生成优化建议。"""
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        plan = (n.data or {})["plan"]
        pid = n.project_id

    async def log(line: str) -> None:
        with SessionLocal() as db:
            m = db.get(Node, node_id)
            m.data = {**m.data, "log": [*m.data.get("log", []), line]}
            db.commit()
        emit(pid, "delivery")

    cid = await tiktok.create_campaign(plan["campaign"], plan["daily_budget"])
    await log(f"创建广告系列「{plan['campaign']}」✓ {cid}")
    for g in plan["adgroups"]:
        gid = await tiktok.create_adgroup(cid, g["name"], g["targeting"], plan["daily_budget"])
        await log(f"创建广告组：{g['name']} ✓ {gid}")
        for c in plan["creatives"]:
            aid = await tiktok.create_ad(gid, f"{g['name']}-{c}", f"mock://composed/{c}.mp4")
            await log(f"创建广告并提交平台审核 ✓ {aid}")
    await log("平台审核通过，开始投放 ✓")
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        project = db.get(Project, pid)
        n.status = "live"
        _collect_metrics(db, project, plan["creatives"])
        x, y = canvas.next_pos(db, pid, "data")
        dn = canvas.create_node(db, project, "data", sub="TikTok 报表 · 每小时回收", status="pass", x=x, y=y)
        canvas.connect(db, pid, n.id, dn.id)
        x, y = canvas.next_pos(db, pid, "opt")
        on = canvas.create_node(db, project, "opt", sub="3 条建议", status="run", x=x, y=y)
        canvas.connect(db, pid, dn.id, on.id)
        canvas.bump(project)
        flags = dict(project.flags or {})
        flags["launched"] = True
        project.flags = flags
        agent.say(db, pid, f"投放已上线：{{{{{dn.id}}}}} 开始回收数据，{{{{{on.id}}}}} 正在生成优化建议。")
        db.commit()
        emit(pid, "canvas")
        emit(pid, "chat")
        opt_id = on.id
    await _sleep()
    with SessionLocal() as db:
        on = db.get(Node, opt_id)
        on.data = {"suggestions": _suggestions(db, pid)}
        _done(db, on, "；".join(s["text"] for s in on.data["suggestions"]),
              "规则：淘汰（CTR < 均值 60%）· 扩量（CPA ≤ 目标 80%）· 疲劳（CTR 3 天降 30%）")


def _collect_metrics(db, project: Project, creatives: list[str]) -> None:
    rnd = random.Random(project.id)
    start = date.today() - timedelta(days=6)
    for c in creatives:
        quality = 0.6 + rnd.random() * 0.8
        for d in range(7):
            imp = int(20000 + rnd.random() * 15000)
            clicks = int(imp * 0.02 * quality)
            db.add(MetricDaily(project_id=project.id, creative_node_id=c, day=(start + timedelta(days=d)).isoformat(),
                               spend=round(imp / 1000 * 4.2, 2), impressions=imp, clicks=clicks,
                               completes=int(imp * 0.31 * quality), conversions=int(clicks * 0.1)))
    db.flush()


def _suggestions(db, pid: str) -> list[dict]:
    rows = db.query(MetricDaily).filter(MetricDaily.project_id == pid).all()
    by: dict[str, dict] = {}
    for r in rows:
        a = by.setdefault(r.creative_node_id, {"spend": 0, "imp": 0, "clicks": 0, "conv": 0})
        a["spend"] += r.spend; a["imp"] += r.impressions; a["clicks"] += r.clicks; a["conv"] += r.conversions
    title = {n.id: n.title for n in canvas.nodes_of(db, pid)}
    ranked = sorted(by.items(), key=lambda kv: -kv[1]["clicks"] / max(1, kv[1]["imp"]))
    out = []
    if ranked:
        best = ranked[0]
        out.append({"action": "scale", "target": best[0], "text": f"{title.get(best[0], best[0])} 扩量：预算 +20%，复制到类似人群"})
    if len(ranked) > 1:
        worst = ranked[-1]
        out.append({"action": "pause", "target": worst[0], "text": f"暂停 {title.get(worst[0], worst[0])}（CTR 低于均值）"})
    out.append({"action": "iterate", "target": None, "text": "基于跑赢剧本生成 2 个变体：保留对比实测钩子，替换第 4–6 秒"})
    return out
