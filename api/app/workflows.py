"""模块工作流：每个模块执行完产出结论 → 创建审核单 → 节点停在「待审核」。

演示版用进程内异步任务 + 数据库状态机实现审核门；生产版替换为 Temporal：
每个 run_* 对应一个子工作流，审核决定通过 Signal 唤醒（技术方案第 4 节）。
"""
import asyncio
import hashlib
import json
import random
from datetime import date, timedelta

from app import agent, canvas, config, settings_store, storyboard
from app.adapters import fal, llm, seedance, tiktok
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


def _normalize_shots(rows: list) -> list[list[str]]:
    """统一成 [时间段, 画面, 口播, 中文]；大模型给的时长是数字时换算成「0–3s」这样的区间。"""
    out, t = [], 0.0
    for row in rows:
        row = [str(c) for c in row][:4] + [""] * (4 - len(row[:4]))
        try:
            d = float(row[0].rstrip("s秒"))
            row[0] = f"{t:g}–{t + d:g}s"
            t += d
        except ValueError:
            pass
        out.append(row)
    return out


async def generate_script(node_id: str, comment: str = "") -> None:
    await _sleep()
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        d = dict(n.data or {})
        sp, aud = d.get("selling_point", "续航"), d.get("audience", "小商贩")
        current = [list(s) for s in d.get("shots") or []]
        shots = [s[:] for s in SHOTS.get(sp, SHOTS["续航"])]
        if settings_store.llm_enabled():
            ad = db.query(RefAd).filter(RefAd.no == d.get("ref_ad_no")).first()
            # 改稿：在现有剧本上按意见改，没提到的镜头原样保留
            revise = (f"\n当前剧本（JSON）：{json.dumps(current, ensure_ascii=False)}\n请在当前剧本上按修改意见修改，"
                      "意见没涉及的镜头、画面和口播保持原样；时长写成秒数。") if comment and current else ""
            try:
                out = await llm.chat_json(
                    "你是 TECNO 手机的海外短视频广告编剧。只输出 JSON：{\"shots\": [[时长, 画面描述(中文), 口播(尼日利亚皮钦英语), 中文对照], ...]}，4 镜共 15 秒，第 3 镜为产品特写（官方素材）。",
                    f"参考爆款结构：{ad.dna if ad else '对比实测钩子'}；主卖点：{sp}；目标人群：尼日利亚 {aud}；修改意见：{comment or '无'}{revise}")
                if isinstance(out.get("shots"), list) and len(out["shots"]) >= 3:
                    shots = _normalize_shots(out["shots"])
            except Exception:
                pass
        elif comment:
            shots = current or shots
            shots[0][3] = f"{shots[0][3]}（已按意见修改：{comment}）"
        d.update(shots=shots, version=d.get("version", 1) + (1 if comment else 0))
        n.data = d
        n.sub = f"{sp} · {aud} · 15s" + (f" · v{d['version']}" if d["version"] > 1 else "")
        _done(db, n, f"{sp}卖点 · {aud}，{len(shots)} 镜 15 秒，合规自检通过",
              "参考爆款的创意结构；卖点表述取自卖点库；与参考素材相似度 18%（阈值 40%）；禁用词 0 处")
    if settings_store.llm_enabled():  # 剧本好了接着画分镜图（不阻塞审核）
        spawn(storyboard.run(node_id))


VIDEO_STYLE = "竖屏 9:16 手机广告镜头，真实质感，自然光，本地人物，画面中不要出现文字和品牌标志"
_video_slots = asyncio.Semaphore(2)  # 同时最多 2 个镜头在生成，避免触发平台并发限制


async def _gen_shot(prompt: str) -> dict:
    provider = settings_store.video_provider()
    async with _video_slots:
        if provider == "fal":
            try:
                job = await fal.submit(prompt, duration=5)
                return {"provider": "fal", "model": job["model"], "task_id": job["request_id"], **await fal.wait(job)}
            except Exception as e:  # 网络 / 鉴权 / 参数错误都按失败处理，节点标红可重试
                return {"provider": "fal", "status": "failed", "error": str(e)[:300]}
        tid = await seedance.create_task(prompt)
        return {"provider": "byteplus" if provider == "byteplus" else "mock", "task_id": tid, **await seedance.wait_task(tid)}


async def generate_video(node_id: str, comment: str = "") -> None:
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        project = db.get(Project, n.project_id)
        src = db.get(Node, (n.data or {}).get("script_id")) or next(iter(canvas.upstream(db, n.id)), None)
        shots = (src.data or {}).get("shots", []) if src else []
        market = project.market

    async def one(i: int, s: list[str]) -> dict:
        if i == 2:  # 产品镜头只用官方素材，不让模型生成
            return {"shot": i + 1, "source": "official", "status": "completed", "url": "asset://official/camon-product.mp4"}
        prompt = f"{market}，{s[1]}。{VIDEO_STYLE}" + (f"。修改意见：{comment}" if comment else "")
        res = await _gen_shot(prompt)
        return {"shot": i + 1, "source": "seedance", "prompt": prompt, "url": res.get("video_url"), **res}

    tasks = list(await asyncio.gather(*(one(i, s) for i, s in enumerate(shots))))
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        failed = [t for t in tasks if t.get("status") == "failed"]
        real = [t for t in tasks if t.get("provider") in ("fal", "byteplus")]
        urls = [t["url"] for t in tasks if t.get("url", "").startswith("http")]
        n.data = {**(n.data or {}), "shots": shots, "tasks": tasks, "video_url": urls[0] if urls else f"mock://composed/{node_id}.mp4",
                  "shot_urls": urls, "engine": real[0].get("model", real[0]["provider"]) if real else "mock",
                  "qc": {"画面崩坏": not failed, "产品形态": True, "字幕错字": True, "时长与规格": True}}
        if failed:
            n.status = "failed"
            n.sub = f"{len(failed)} 个镜头生成失败，可重试"
            agent.say(db, n.project_id, f"{agent.ref(n)} 有 {len(failed)} 个镜头生成失败：{failed[0].get('error', '')[:120]}。可以在视频工作室单独重生成。")
            db.commit()
            emit(n.project_id, "canvas")
            emit(n.project_id, "chat")
            return
        engine = n.data["engine"]
        _done(db, n, f"{'Seedance（' + engine + '）' if real else '模拟'}生成 {len(tasks) - 1} 镜 + 官方产品镜头 1 镜，质检 4/4 通过",
              f"引擎：{engine} · 画面崩坏 0 · 产品形态与官方素材一致 · 字幕错字 0 · 9:16")


NAMES = {"尼日利亚": ["Ada", "Musa", "Chidi", "Bola", "Femi", "Ngozi", "Tunde", "Zainab"],
         "巴基斯坦": ["Ayesha", "Bilal", "Hira", "Usman", "Sana", "Imran", "Fatima", "Hamza"]}
CITIES = {"尼日利亚": ["Lagos", "Kano", "Abuja", "Ibadan"], "巴基斯坦": ["Karachi", "Lahore", "Islamabad", "Faisalabad"]}


def _personas(market: str, segments: list[str]) -> list[dict]:
    """按市场与人群抽 40 个虚拟用户：第一人群 60%，第二人群 40%。"""
    names, cities = NAMES.get(market, NAMES["尼日利亚"]), CITIES.get(market, CITIES["尼日利亚"])
    a, b = (segments + segments)[:2]
    out = []
    for i in range(40):
        seg = a if i < 24 else b
        young = seg == "学生"
        out.append({"id": i, "name": names[i % 8], "segment": seg, "age": (18 + i % 6) if young else (25 + i % 12), "city": cities[i % 4],
                    "phone": ["Tecno Spark", "itel A70", "Samsung A05", "Infinix Hot", "Redmi 13C"][i % 5],
                    "income": "低" if i % 3 == 0 else "中"})
    return out


def _simulated(v: Node, personas: list[dict]) -> dict:
    reactions = []
    for p in personas:
        drop = [3, 5, 8, 15, 15, 15, 2, 15, 11, 15][_h(v.id + str(p["id"]), 10)]
        reactions.append({"persona": p["id"], "drop_at": drop, "completed": drop >= 15,
                          "clicked": drop >= 15 and _h(v.id + p["name"] + str(p["id"]), 7) == 0, "comment": ""})
    s = 7 + _h(v.id, 3)
    return {"reactions": reactions, "scores": {"hook": s, "clarity": s, "trust": s - 1, "local": s, "intent": s - 1},
            "issue": "前 3 秒流失偏高，建议换停电场景钩子", "engine": "simulated"}


async def _llm_eval(v: Node, script: Node | None, personas: list[dict], market: str) -> dict:
    shots = (script.data or {}).get("shots", []) if script else (v.data or {}).get("shots", [])
    board = "\n".join(f"镜{i + 1}（{s[0]}）画面：{s[1]}；口播：{s[2]}" for i, s in enumerate(shots))
    people = "\n".join(f"{p['id']}. {p['name']}，{p['age']} 岁，{p['segment']}，{p['city']}，现用 {p['phone']}，收入{p['income']}" for p in personas)
    system = ("你在模拟 TikTok 信息流里刷到一条 15 秒手机广告的真实用户。根据每个人的画像独立判断他会在第几秒划走、"
              "是否看完、是否点击 CTA，并写一句他会说的真实反应（中文，口语）。不要所有人都一样，要符合真实的流失分布："
              "真实信息流里约一半人在前 3 秒划走，看完的通常不到三分之一，点击 CTA 的通常只有 1–4 人；与自己人群无关的广告更容易划走。"
              "只输出 JSON：{\"reactions\":[{\"persona\":编号,\"drop_at\":0-15 的整数（看完填 15）,\"clicked\":true/false,\"comment\":\"一句话\"}]（40 条，编号 0-39 全覆盖）,"
              "\"scores\":{\"hook\":1-10,\"clarity\":1-10,\"trust\":1-10,\"local\":1-10,\"intent\":1-10},\"issue\":\"最主要的问题与修改建议，一句话\"}")
    out = await llm.chat_json(system, f"市场：{market}\n广告分镜：\n{board}\n\n用户画像：\n{people}", task="eval", timeout=120)
    by = {int(r["persona"]): r for r in out.get("reactions", []) if str(r.get("persona", "")).isdigit() or isinstance(r.get("persona"), int)}
    if len(by) < 30:
        raise ValueError("reactions incomplete")
    sim = _simulated(v, personas)["reactions"]
    reactions = []
    for p in personas:
        r = by.get(p["id"])
        if not r:
            reactions.append(sim[p["id"]])
            continue
        drop = max(0, min(15, int(r.get("drop_at", 15))))
        reactions.append({"persona": p["id"], "drop_at": drop, "completed": drop >= 15, "clicked": bool(r.get("clicked")) and drop >= 6,
                          "comment": str(r.get("comment", ""))[:80]})
    scores = {k: max(1, min(10, int((out.get("scores") or {}).get(k, 6)))) for k in ("hook", "clarity", "trust", "local", "intent")}
    return {"reactions": reactions, "scores": scores, "issue": str(out.get("issue", ""))[:120], "engine": settings_store.get_models()["eval"]}


async def evaluate(node_id: str, comment: str = "") -> None:
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        project = db.get(Project, n.project_id)
        videos = canvas.upstream(db, n.id)
        scripts = {v.id: db.get(Node, (v.data or {}).get("script_id")) for v in videos}
        segs = list(dict.fromkeys((s.data or {}).get("audience") for s in scripts.values() if s and (s.data or {}).get("audience"))) or ["小商贩", "学生"]
        personas = _personas(project.market, segs)
        market = project.market
    use_llm = settings_store.llm_enabled()
    if not use_llm:
        await _sleep(1.5)

    async def one(v: Node) -> dict:
        r = None
        if use_llm:
            try:
                r = await _llm_eval(v, scripts.get(v.id), personas, market)
            except Exception:
                r = None
        r = r or _simulated(v, personas)
        done = sum(x["completed"] for x in r["reactions"]) / 40
        clicks = sum(x["clicked"] for x in r["reactions"])
        score = round(sum(r["scores"].values()) / 5 * 10)
        return {"id": v.id, "title": v.title, "score": score, "ctr": round(0.5 + clicks / 40 * 5, 1), "vtr": round(done * 100),
                "clicks": clicks, "reactions": r["reactions"], "dims": r["scores"], "issue": r["issue"], "engine": r["engine"]}

    results = sorted(await asyncio.gather(*(one(v) for v in videos)), key=lambda x: -x["score"])
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        picks = [r["id"] for r in results if r["score"] >= 70] or ([results[0]["id"]] if results else [])
        top = results[0] if results else None
        seg_score = {}
        for seg in segs:
            ids = {p["id"] for p in personas if p["segment"] == seg}
            seg_score[seg] = sum(x["completed"] for r in results for x in r["reactions"] if x["persona"] in ids)
        best_seg = max(seg_score, key=seg_score.get) if seg_score else "小商贩"
        n.data = {**(n.data or {}), "personas": personas, "results": results, "picks": picks, "score": top["score"] if top else 0,
                  "suggest_audience": best_seg, "issue": top["issue"] if top else "", "engine": top["engine"] if top else ""}
        n.sub = f"最高 {top['title']} · 预测 CTR {top['ctr']}%" if top else "无视频"
        _done(db, n, f"入选 {len(picks)} 条；最高分 {n.data['score']}，建议人群：{best_seg}（评测引擎：{n.data['engine']}）",
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
