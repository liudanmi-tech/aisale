"""模块工作流：每个模块执行完产出结论 → 创建审核单 → 节点停在「待审核」。

演示版用进程内异步任务 + 数据库状态机实现审核门；生产版替换为 Temporal：
每个 run_* 对应一个子工作流，审核决定通过 Signal 唤醒（技术方案第 4 节）。
"""
import asyncio
import hashlib
import json
import logging
import random
from datetime import date, timedelta

from app import agent, canvas, compose, config, panel, production, settings_store, storyboard, wash, wash_plan
from app.adapters import llm, tiktok
from app.db import SessionLocal
from app.events import emit, spawn
from app.models import Asset, MetricDaily, Node, Project, RefAd
from app.seed import SHOTS

log = logging.getLogger(__name__)


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
        proj = db.get(Project, n.project_id)
        market = proj.market if proj else "尼日利亚"
        lang = d.get("language") or ("尼日利亚皮钦英语" if market == "尼日利亚" else f"{market}当地常用语言")
        extra = (f"；人群标签：{'、'.join(d['audience_tags'])}" if d.get("audience_tags") else "") + (f"；机型：{d['model_sku']}" if d.get("model_sku") else "")
        current = [list(s) for s in d.get("shots") or []]
        shots = [s[:] for s in SHOTS.get(sp, SHOTS["续航"])]
        wn = next((u for u in canvas.upstream(db, node_id) if u.type == "wash" and u.status == "pass"), None)
        ref_no = (wn.data or {}).get("ref_ad_no") if wn else d.get("ref_ad_no")
        ad = db.query(RefAd).filter(RefAd.no == ref_no).first() if ref_no else None
        bd = ((ad.dna or {}).get("breakdown") if ad else None) or None
        if wn and ad and not bd:
            bd = wash_plan.ref_breakdown(ad)  # 没做视频拆解：用文案推断的分镜凑（洗稿方案上已标出）
        washed, wash_err = None, ""
        if settings_store.llm_enabled() and bd:
            # 有确认过的洗稿方案：按方案的六行表写；否则先出洗稿清单（用户改过就用改过的），再按清单写。镜头数和节奏跟着参考走
            brand = proj.brand if proj else "TECNO"
            ours = (f"品牌机型：{brand} {(d.get('model_sku') or (proj.model_sku if proj else '') or '').strip()}；主卖点：{sp}；"
                    f"目标市场：{market}；目标人群：{aud}{extra}；口播语言：{lang}")
            old = d.get("wash") or {}
            tier = (wn.data or {}).get("tier") if wn else None
            try:
                if wn:
                    plan = wash_plan.to_plan(wn.data or {})
                else:
                    plan = old["plan"] if old.get("plan_edited") and old.get("plan") and old.get("ref_no") == ad.no else await wash.make_plan(bd, ours, comment)
                washed = await wash.write(bd, plan, ours, brand, lang, comment, current, tier=tier)
                d["wash"] = {"ref_no": ad.no, "plan": plan, "plan_edited": bool(old.get("plan_edited") and old.get("plan") is plan),
                             "tier": tier, "from_node": wn.id if wn else None,
                             "map": washed["map"], "similarity": washed["similarity"], "check": washed.get("check"), "ref_shots": len(bd.get("shots") or []),
                             "ref": [{k: x.get(k) for k in ("t", "frame", "scene", "action", "line", "beat", "camera", "people", "product", "framing", "phone_facing")} for x in bd.get("shots") or [] if isinstance(x, dict)]}
                shots = washed["shots"]
                d["product_shots"] = washed["product_shots"]
            except Exception as e:  # noqa: BLE001
                log.warning("按拆解洗剧本失败，改用普通写法：%s", e)
                wash_err = str(e)[:200]
        if settings_store.llm_enabled() and not washed:
            # 改稿：在现有剧本上按意见改，没提到的镜头原样保留
            revise = (f"\n当前剧本（JSON）：{json.dumps(current, ensure_ascii=False)}\n请在当前剧本上按修改意见修改，"
                      "意见没涉及的镜头、画面和口播保持原样；时长写成秒数。") if comment and current else ""
            try:
                out = await llm.chat_json(
                    "你是 TECNO 手机的海外短视频广告编剧。只输出 JSON：{\"shots\": [[时长, 画面描述(中文), 口播(" + lang + "), 中文对照], ...]}，4 镜共 15 秒，第 3 镜为产品特写。"
                    "画面描述只写人物动作、手机的角度和姿态、场景，不写屏幕上显示什么、不写画面里的文字（AI 画不准文字）；"
                    "电池容量、价格、门店这类卖点数字放进口播，后期做成字幕贴片。",
                    f"参考爆款结构：{ad.dna if ad else '对比实测钩子'}；主卖点：{sp}；目标人群：{market} {aud}{extra}；修改意见：{comment or '无'}{revise}")
                if isinstance(out.get("shots"), list) and len(out["shots"]) >= 3:
                    shots = _normalize_shots(out["shots"])
            except Exception:
                pass
        elif comment:
            shots = current or shots
            shots[0][3] = f"{shots[0][3]}（已按意见修改：{comment}）"
        if not washed:
            d.pop("wash", None)
            d.pop("product_shots", None)
        sim = washed["similarity"] if washed else wash.similarity(shots, None, ad.dna if ad else None)
        total = sum(compose.secs(s[0]) for s in shots)
        d.update(shots=shots, version=d.get("version", 1) + (1 if comment else 0), similarity=sim)
        if wash_err:
            d["wash_error"] = wash_err
        else:
            d.pop("wash_error", None)
        n.data = d
        n.sub = f"{sp} · {aud} · {total:g}s" + (f" · v{d['version']}" if d["version"] > 1 else "")
        ref = f"按爆款 #{ad.no} 的逐镜拆解洗稿（参考 {d['wash']['ref_shots']} 镜 → 新剧本 {len(shots)} 镜）" if washed else \
            (f"参考爆款 #{ad.no} 的文案和钩子（这条还没做视频拆解）" if ad else "按卖点模板写")
        sim_text = ((sim.get("note") or f"台词和参考原话最高相似度 {sim['line_max']:.0%}（阈值 {sim['threshold']:.0%}，逐镜按词比对）")
                    if ad else "没有参考爆款，未做相似度比对")
        _done(db, n, f"{sp}卖点 · {aud}，{len(shots)} 镜 {total:g} 秒" + ("，台词和参考太像，建议修改" if sim["line_max"] > sim["threshold"] else ""),
              f"{ref}；{sim_text}" + (f"；洗稿失败原因：{wash_err}" if wash_err else ""))
    if settings_store.llm_enabled():  # 剧本好了接着画手绘分镜（不阻塞审核；改过的镜头才重画）
        spawn(storyboard.run(node_id))


BREAKDOWN_POLL = 3.0
BREAKDOWN_WAIT = 900  # 下载 + 抽帧 + 模型看，最多等 15 分钟


async def _wait_breakdown(node_id: str, no: int) -> str:
    """确保爆款 #no 有视频拆解：没在拆就开始拆，然后等。成功返回空字符串，失败返回原因。"""
    from app import breakdown
    with SessionLocal() as db:
        a = db.query(RefAd).filter(RefAd.no == no).first()
        dna = dict(a.dna or {}) if a else {}
        n = db.get(Node, node_id)
        if n:
            n.data = {**(n.data or {}), "stage": "breakdown", "need_video": False}
            n.sub = "正在看视频：下载 → 每秒抽帧 + 听音轨 → 模型逐镜拆解…"
            db.commit()
            emit(n.project_id, "canvas")
    if not breakdown.running(no):
        if not dna.get("url") and not breakdown.upload_path(no).exists():
            return "这条爆款没有 TikTok 链接，需要上传视频文件"
        breakdown.start(no)
    waited = 0.0
    while waited < BREAKDOWN_WAIT:
        await asyncio.sleep(BREAKDOWN_POLL)
        waited += BREAKDOWN_POLL
        with SessionLocal() as db:
            a = db.query(RefAd).filter(RefAd.no == no).first()
            dna = dict(a.dna or {}) if a else {}
        if dna.get("breakdown") and dna.get("breakdown_status") == "done":
            return ""
        if dna.get("breakdown_status") == "failed" and not breakdown.running(no):
            return dna.get("breakdown_error") or "拆解失败"
    return "拆解超时（超过 15 分钟）"


async def plan_wash(node_id: str, comment: str = "") -> None:
    """洗稿方案：要素拆分 → 相似度评估定档位 → 按档位写每行我方怎么做 → 提交人工确认。"""
    await _sleep()
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        d = dict(n.data or {})
        proj = db.get(Project, n.project_id)
        ad_row = db.query(RefAd).filter(RefAd.no == d.get("ref_ad_no")).first() if d.get("ref_ad_no") else None
        if not ad_row:
            n.status, n.sub = "failed", "没有参考爆款"
            db.commit()
            emit(n.project_id, "canvas")
            return
        market, brand = (proj.market if proj else "尼日利亚"), (proj.brand if proj else "TECNO")
        sp, aud = d.get("selling_point", "续航"), d.get("audience", "小商贩")
        lang = d.get("language") or ("尼日利亚皮钦英语" if market == "尼日利亚" else f"{market}当地常用语言")
        sku = (d.get("model_sku") or (proj.model_sku if proj else "") or "").strip()
        ours = (f"品牌机型：{brand} {sku}；主卖点：{sp}；目标市场：{market}；目标人群：{aud}"
                + (f"；人群标签：{'、'.join(d['audience_tags'])}" if d.get("audience_tags") else "") + f"；口播语言：{lang}")
        pid, no = n.project_id, ad_row.no
        has_bd = bool((ad_row.dna or {}).get("breakdown"))
    if settings_store.llm_enabled() and not has_bd:
        # 洗稿要看过视频：没拆解就先多模态拆解（下载视频 → 每秒抽帧 + 音轨 → 模型逐镜看），等它拆完再出方案
        why = await _wait_breakdown(node_id, no)
        if why:
            with SessionLocal() as db:
                n = db.get(Node, node_id)
                if n:
                    n.data = {**(n.data or {}), "need_video": True, "breakdown_error": why, "stage": None}
                    n.status, n.sub = "input", "需要看视频：拆解没成功"
                    db.commit()
                    agent.say(db, pid, f"{agent.ref(n)} 停下了：洗稿要先看视频，但爆款 #{no} 的视频拆解没成功（{why[:120]}）。"
                                       "在节点上点「上传视频」把 mp4 传上来，拆完会自动接着出方案。")
                    db.commit()
            emit(pid, "canvas")
            emit(pid, "chat")
            return
    with SessionLocal() as db:
        ad_row = db.query(RefAd).filter(RefAd.no == no).first()
        ad = {"market": ad_row.market, "selling_point": ad_row.selling_point, "breakdown": (ad_row.dna or {}).get("breakdown")}
        bd = wash_plan.ref_breakdown(ad_row)
        title = ad_row.title
    raw: dict = {}
    err = ""
    if settings_store.llm_enabled():
        try:
            pre = wash_plan.fit(ad, {"market": market, "selling_point": sp})
            tier0 = d.get("tier") if d.get("tier_source") in ("agent", "user") else pre["recommended"]
            raw = await wash_plan.draft(bd, ours, tier0, comment)
        except Exception as e:  # noqa: BLE001
            log.warning("洗稿方案生成失败：%s", e)
            err = str(e)[:200] or type(e).__name__
    f = wash_plan.fit(ad, {"market": market, "selling_point": sp}, {"audience": raw.get("audience_fit"), "product": raw.get("product_fit")})
    tier = d.get("tier") if d.get("tier_source") in ("agent", "user") and d.get("tier") in wash_plan.TIERS else f["recommended"]
    rows = wash_plan.rows_for(tier, raw.get("rows"), d.get("rows"))
    if not raw:  # 没有模型：原片一列按拆解填上，我方一列留给人写
        refs = {"hook": (bd.get("core") or {}).get("device") or "", "scene": "；".join(s.get("scene", "") for s in bd["shots"]),
                "rhythm": f"{len(bd['shots'])} 镜 · {bd.get('video_duration') or '—'} 秒", "lines": "；".join(s.get("line", "") for s in bd["shots"] if s.get("line")),
                "camera": "；".join(s.get("camera", "") for s in bd["shots"] if s.get("camera")),
                "cast": "；".join(f"{c.get('role')}：{c.get('look')}" for c in bd.get("cast") or [])}
        rows = [{**r, "ref": r["ref"] or refs.get(r["key"], "")} for r in rows]
    a = raw.get("analysis") if isinstance(raw.get("analysis"), dict) else {}
    opts = [{k: str(o.get(k) or "") for k in ("idea", "intensity", "fit", "risk")} for o in raw.get("options") or [] if isinstance(o, dict) and o.get("idea")][:4]
    chosen = int(raw["chosen"]) - 1 if str(raw.get("chosen", "")).isdigit() else None
    if opts and (chosen is None or not 0 <= chosen < len(opts) or "弱" in opts[chosen]["intensity"]):
        chosen = next((k for k, o in enumerate(opts) if "强" in o["intensity"]), next((k for k, o in enumerate(opts) if "弱" not in o["intensity"]), 0))
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        d = dict(n.data or {})
        d.update(tier=tier, tier_source=d.get("tier_source") or "recommended", fit=f, rows=rows, error=err, need_video=False, breakdown_error="", stage=None,
                 analysis={k: str(a.get(k) or "") for k in ("core", "why", "intensity", "must_not_lose")} if a else d.get("analysis"),
                 options=opts or d.get("options") or [], chosen=chosen if opts else d.get("chosen"),
                 inferred=bool(bd.get("inferred")), ref_title=title, version=d.get("version", 0) + 1)
        n.data = d
        n.sub = f"{wash_plan.TIERS[tier]['label']} · 参考爆款 #{no}"
        _done(db, n, wash_plan.summary(d) + ("（模型没生成成功，「我方」一列请手动填写）" if err or not raw else ""),
              f.get("reason", "") + ("；这条爆款没做视频拆解，要素按文案推断" if bd.get("inferred") else "") + (f"；出错：{err}" if err else ""))
    emit(pid, "canvas")


async def generate_video(node_id: str, comment: str = "") -> None:
    """分镜 → 选角置景 → 关键帧 → 每镜视频，见 app/production.py。"""
    await production.run(node_id, comment)


NAMES = {"尼日利亚": ["Ada", "Musa", "Chidi", "Bola", "Femi", "Ngozi", "Tunde", "Zainab"],
         "巴基斯坦": ["Ayesha", "Bilal", "Hira", "Usman", "Sana", "Imran", "Fatima", "Hamza"]}
CITIES = {"尼日利亚": ["Lagos", "Kano", "Abuja", "Ibadan"], "巴基斯坦": ["Karachi", "Lahore", "Islamabad", "Faisalabad"]}


JOBS = {"小商贩": ["菜市场摊主", "手机配件店老板", "摩托车司机（okada）", "裁缝铺老板"]}
JOBS_ANY = ["上班族", "小店店员", "网约车司机", "美发师"]
JOBS_YOUNG = ["大学生", "高中生", "实习生", "刚毕业找工作"]
LIKES = ["足球和球星集锦", "搞笑短剧", "Afrobeats 音乐", "赚钱副业教程", "美妆穿搭", "手机评测和开箱"]
HABITS = ["刷得很快，1 秒不吸引就划走", "会看完有剧情的视频", "只看熟人和关注的博主", "喜欢看评论区再决定", "对广告很反感"]
LANGS = {"尼日利亚": ["尼日利亚皮钦英语", "英语", "约鲁巴语和英语混说", "豪萨语和英语混说"], "巴基斯坦": ["乌尔都语", "乌尔都语和英语混说", "旁遮普语"]}


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
                    "income": "低" if i % 3 == 0 else "中",
                    "job": (JOBS_YOUNG if young else JOBS.get(seg, JOBS_ANY))[i % 4], "likes": LIKES[i % 6], "habit": HABITS[i % 5],
                    "lang": LANGS.get(market, ["英语"])[i % len(LANGS.get(market, ["英语"]))]})
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


async def evaluate(node_id: str, comment: str = "") -> None:
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        project = db.get(Project, n.project_id)
        videos = canvas.upstream(db, n.id)
        # 评测对象是成片节点（旧项目直接接视频）：剧本和每镜片段从对应的视频节点取
        src = {v.id: (db.get(Node, (v.data or {}).get("video_id")) if v.type == "cut" else v) or v for v in videos}
        scripts = {v.id: db.get(Node, (src[v.id].data or {}).get("script_id")) for v in videos}
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
                sc = scripts.get(v.id)
                sv = src[v.id]
                shots = (sc.data or {}).get("shots", []) if sc else (sv.data or {}).get("shots", [])
                r = await panel.run(personas, shots, (sv.data or {}).get("tasks") or [], _simulated(v, personas)["reactions"], seed=v.id)
            except Exception as e:  # noqa: BLE001
                log.warning("40 人评测退回模拟：%s", e)
                r = None
        r = r or _simulated(v, personas)
        done = sum(x["completed"] for x in r["reactions"]) / 40
        clicks = sum(x["clicked"] for x in r["reactions"])
        # 模型扮演用户打的分系统性偏高，总分一半看五维评分、一半看抽样出来的完播率（完播 50% 及以上算满分）
        score = round(sum(r["scores"].values()) / 5 * 10 * 0.5 + min(100, done * 200) * 0.5)
        # ctr 是 40 个模拟用户的点击意向换算的，没有用真实投放数据校准，页面上标「未校准」
        return {"id": v.id, "title": v.title, "score": score, "ctr": round(0.5 + clicks / 40 * 5, 1), "calibrated": False, "vtr": round(done * 100),
                "clicks": clicks, "reactions": r["reactions"], "dims": r["scores"], "issue": r["issue"], "engine": r["engine"],
                "retention": r.get("retention"), "agents": r.get("agents", 0), "shot_rel": r.get("shot_rel"),
                "video_url": (v.data or {}).get("video_url") if v.type == "cut" else None}

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


def _compliance(db, pid: str) -> dict:
    """用了真人照片的演员都要有肖像授权记录。"""
    ids = [(x.data or {}).get("asset_id") for x in canvas.nodes_of(db, pid, "actor")]
    actors = [a for a in (db.get(Asset, i) for i in ids if i) if a]
    return {"演员肖像授权": all(a.source != "upload" or (a.data or {}).get("consent") for a in actors)}


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
                "creatives": picks, "creative_urls": {r["id"]: r.get("video_url") for r in (ev.data or {}).get("results", []) if ev and r["id"] in picks and r.get("video_url")},
                "daily_budget": 30, "test_days": 3, "cpa_cap": 2.5,
                "guardrails": {"market_daily_cap": 500, "creative_spend_cap": 60},
                # TikTok 要求 AI 生成内容打上 AIGC 标识；下发时在广告上开启（具体 API 字段以 TikTok Marketing API 文档为准）
                "aigc_label": True,
                "checks": {"政策预审": True, "落地页": True, "追踪参数": True, **_compliance(db, n.project_id)}}
        n.data = {**(n.data or {}), "plan": plan, "log": []}
        _done(db, n, "TikTok · 2 个广告组 · $30/天 × 3 天 · CPA 上限 $2.5",
              "政策预审通过 · 落地页可访问 · 追踪参数完整 · 预算在市场日上限内 · 开启 AIGC 标识"
              + "".join(f" · ⚠ {k}未通过" for k, ok in plan["checks"].items() if not ok))


async def compose_cut(node_id: str, comment: str = "") -> None:
    """视频片段 → 成片，见 app/compose.py。"""
    from app import compose
    await compose.run(node_id, comment)


ACTIONS = {"plan_wash": plan_wash, "generate_script": generate_script, "generate_video": generate_video, "compose": compose_cut, "evaluate": evaluate, "plan_delivery": plan_delivery}
TYPE_ACTION = {"wash": "plan_wash", "script": "generate_script", "video": "generate_video", "cut": "compose", "eval": "evaluate", "deliver": "plan_delivery"}


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
            aid = await tiktok.create_ad(gid, f"{g['name']}-{c}", plan.get("creative_urls", {}).get(c) or f"mock://composed/{c}.mp4")
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
