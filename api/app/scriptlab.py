"""剧本库：结合本地热点，原创「整活」型爆款剧本，最后落到产品卖点（打游戏不卡、省电、防水……）。

流程（后台任务，一批大约 1–2 分钟）：
1. 找热点：竞品雷达 + 达人雷达最近 30 天抓到的本地视频，按播放加权统计话题标签和背景音乐（真实数据，不花钱）；
   再加上你手填的热点、预置的本地常青话题（停电、堵车、足球……，标明是预置）
2. 头脑风暴：一次出 8 个创意（一句话 + 前 2 秒钩子 + 反转 + 卖点怎么当成笑点 / 反转落地）
3. 评审：另一个评审逐个打分（创意新奇、钩子、卖点融合、本地味、能不能用 AI 拍出来、安全合规），挑出最好的几个并给改进意见
4. 写分镜：按评审意见把挑中的写成完整分镜（一镜一个景别，口播用当地语言）
5. 评测（手动点）：复用 40 人评测，40 个本地虚拟用户各自读剧本逐镜打分，给出留存、得分和评论
落选的创意也存着，可以挑一个「写成剧本」。
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta

from app import canvas, settings_store
from app.adapters import llm
from app.db import SessionLocal
from app.events import emit
from app.models import Creator, LibScript, Project, SourceVideo, WatchAccount, new_id
from app.monitor import BRAND_KEYS

log = logging.getLogger(__name__)

SELLING_POINTS = ["打游戏不卡", "省电续航", "防水防尘", "拍照夜拍", "快充", "大存储", "耐摔", "大音量外放", "性价比"]
FORMATS = ["整活", "挑战赛", "反转短剧", "街头实测", "极限测试", "情侣 / 朋友段子", "家庭日常"]
AUDIENCES = ["学生", "小商贩", "年轻上班族", "游戏玩家", "宝妈", "摩托车司机"]
LANG = {"尼日利亚": "尼日利亚皮钦英语", "巴基斯坦": "乌尔都语（拉丁字母书写）", "肯尼亚": "英语和斯瓦希里语混说", "加纳": "英语",
        "孟加拉": "孟加拉语（拉丁字母书写）", "印尼": "印尼语", "菲律宾": "Taglish（他加禄语和英语混说）"}
# 预置的本地常青话题：不是实时热点，是当地人天天在聊的事；界面上标「预置」
EVERGREEN = {
    "尼日利亚": ["NEPA 又停电了（停电梗）", "Lagos 大堵车 go-slow", "Danfo 小巴上的众生相", "加纳 vs 尼日利亚 Jollof 饭之争", "Owambe 婚礼派对",
             "Super Eagles 看球", "雨季街道积水", "Okada 摩托车", "Detty December 年底狂欢", "Naija 妈妈的拖鞋"],
    "巴基斯坦": ["Load-shedding 停电", "板球比赛熬夜看", "Mehndi / 婚礼季", "斋月开斋 Iftar", "季风暴雨街道淹水", "夏天 45 度高温", "Rickshaw 三轮车",
             "Chai 茶摊闲聊", "PUBG 开黑", "亲戚问成绩"],
}
GENERIC_TAGS = {"fyp", "foryou", "foryoupage", "viral", "tiktok", "trending", "fypシ", "xyzbca", "explore", "explorepage", "capcut", "duet",
                "stitch", "foryourpage", "fy", "trend", "viralvideo", "tiktoknigeria", "nigeria", "naija", "pakistan", "lagos"}
_jobs: dict[str, dict] = {}


# ---------- 热点 ----------

def trends(market: str, days: int = 30, limit: int = 20) -> dict:
    """本地热点（真实数据）：竞品雷达 + 达人雷达最近抓到的视频里，按播放加权的话题标签和背景音乐。"""
    since = datetime.utcnow() - timedelta(days=days)
    tags: dict[str, dict] = {}
    music: dict[str, dict] = {}
    n = 0

    campaign: dict[str, dict] = {}

    def add(text: str, hashtags: list, plays: int, snd: str = "", official: bool = False) -> None:
        nonlocal n
        n += 1
        for h in hashtags or re.findall(r"#(\w+)", text or ""):
            k = str(h).lower().lstrip("#")
            if not k or k in GENERIC_TAGS or any(b in k for b in BRAND_KEYS) or len(k) < 3:
                continue
            # 竞品官方号的标签多半是它们自己的广告活动（#titanpower、#techupgrade），单列，不当本地热点
            t = (campaign if official else tags).setdefault(k, {"tag": k, "plays": 0, "videos": 0, "sample": ""})
            t["plays"] += plays or 0
            t["videos"] += 1
            if not t["sample"] and text:
                t["sample"] = text[:100]
        if snd and not official and "original sound" not in snd.lower() and "原声" not in snd:
            m = music.setdefault(snd, {"music": snd, "plays": 0, "videos": 0})
            m["plays"] += plays or 0
            m["videos"] += 1

    with SessionLocal() as db:
        accs = {a.id: a.kind for a in db.query(WatchAccount).filter(WatchAccount.market == market)}
        for v in db.query(SourceVideo).filter(SourceVideo.account_id.in_(list(accs))):
            if (v.posted_at or v.first_seen or since) >= since:
                add(v.text, v.hashtags, v.plays, v.music, official=accs[v.account_id] != "达人")
        for c in db.query(Creator).filter(Creator.market == market, Creator.demo.is_(False)):
            for v in c.videos or []:
                try:
                    ok = not v.get("posted_at") or datetime.fromisoformat(v["posted_at"]) >= since
                except ValueError:
                    ok = True
                if ok:
                    add(v.get("text", ""), [], v.get("plays") or 0)
    rank = lambda d: sorted(d.values(), key=lambda x: (-x["videos"] if x["videos"] >= 2 else 0, -x["plays"]))  # noqa: E731
    return {"tags": [t for t in rank(tags) if t["videos"] >= 2][:limit] or rank(tags)[:limit], "music": rank(music)[:8],
            "campaign_tags": [t for t in rank(campaign) if t["tag"] not in tags][:12],
            "evergreen": EVERGREEN.get(market, []), "videos": n, "days": days}


# ---------- 生成 ----------

IDEA_PROMPT = """你是 TikTok 上最会「整活」的短视频编剧，给 {brand} 在{market}写原创爆款广告。要的不是硬广，是本地人会主动转发的整活 / 段子 / 挑战，
产品卖点必须是笑点或反转本身（看完会说「这手机真能扛」），而不是结尾硬塞一句广告。
产品：{product}（{product_desc}）；这次要落地的卖点：{selling_point}；目标人群：{audience}；形式偏好：{formats}。
已知参数（只能用这些，没写的一个数字都不许编）：{specs}
可以借的本地热点 / 话题：{trends}
先想清楚这个卖点最常见的 3 个广告套路（比如防水就是「手机掉水里捞出来还能用」、续航就是「别人没电了我还有电」），然后全部避开或者反着用。
好创意的样子：卖点是剧情里的「意外解法」或「反转」，观众先以为要出事 / 要输，结果因为这台手机赢了，而且这个反转好笑、能拿去 @ 朋友。
规则：
- 前 2 秒必须有一个画面钩子（反常、危险感、冲突、悬念），不靠字幕、不靠口播也能看懂
- 卖点的「证明」要直观可见，夸张但真实，不能超出参数：{water_rule}
- 能用 AI 视频生成拍出来：6–8 镜、每镜 2–4 秒，主要人物不超过 3 个，不要大场面群戏和复杂特技
- 安全：不教人做危险动作，不嘲笑宗教 / 民族 / 残障，不点名贬低竞品
- 一次给 8 个风格差异大的创意，至少 3 个用上面的本地热点；用梗要用对意思和语气（照「当地说法」和「可以这样用」），不要硬套，也不要解释梗
只输出 JSON：{{"ideas": [{{"title": "8 字以内的标题", "format": "形式", "logline": "一句话讲完这个故事", "hook": "前 2 秒画面",
"twist": "反转 / 笑点", "product_moment": "卖点怎么被证明（画面）", "trend": "用了哪个热点，没用写空", "why_viral": "为什么本地人会转发", "risk": "拍摄或合规风险"}}]}}"""

CRITIC_PROMPT = """你是 TikTok 爆款评审，见过成千上万条手机广告，标准很严。逐个评这些创意（{market}，{product}，卖点：{selling_point}）。
每项 1–10 分：novelty 创意新奇（没见过才高分）、hook 前 2 秒能不能让人停下、integration 卖点是不是笑点 / 反转本身（硬塞广告 ≤4 分）、
local 本地人看了会不会觉得「这就是我们这儿」（用了热梗的看梗用得对不对、是不是硬套）、feasible 用 AI 视频生成能不能拍出来、safe 安全合规。
挑出最好的 {k} 个（总分高、彼此风格不同），给每个挑中的写一条具体改进意见。
只输出 JSON：{{"reviews": [{{"i": 创意序号从 1 开始, "scores": {{"novelty": n, "hook": n, "integration": n, "local": n, "feasible": n, "safe": n}}, "verdict": "一句话点评"}}],
"picked": [{{"i": 序号, "improve": "改进意见"}}]}}"""

WRITE_PROMPT = """你是短视频广告编剧，把这个创意写成可以直接拍的分镜剧本（{market}，{product}，卖点：{selling_point}，人群：{audience}）。
只输出 JSON：{{"shots": [[时长秒数, "画面描述（中文）", "口播（{lang}）", "口播的中文对照"], ...]}}
规则：
- 6–8 镜，总时长 15–22 秒；第 1 镜 1.5–2 秒，就是创意里的钩子画面
- 一镜只有一个景别、一个机位：画面描述以景别开头（如「特写：」「中景：」），不许写「随后切…」，要切就拆成两镜
- 画面只写人物动作、表情、手机的角度和姿态、场景；不写屏幕上显示什么、不写画面里的文字（AI 画不准文字）；参数数字放进口播
- 卖点的证明镜头要清楚：手机是画面主体、哪一面朝镜头写清楚
- 参数只能用这些（没写的一个数字都不许编，口播里也不行）：{specs}；{water_rule}
- 主要人物不超过 3 个，每镜写清楚是谁
- 口播短、口语、像当地人说话；最后一镜一句带产品名的口号"""


def _water_rule(specs: str) -> str:
    if re.search(r"IP6[78]|IP68|IP69", specs or "", re.I):
        return "防水可以拍短时间泡水（按给出的 IP 等级），不拍长时间浸泡、热水、海水"
    if re.search(r"IP6[0-6]|IP5\d", specs or "", re.I):
        return "按给出的 IP 等级只能拍溅水、淋雨、泼一杯水，不能掉进水里、泡水、冲水龙头"
    return "没给防水等级：只能拍溅几滴水、淋小雨，不能掉进水里、泡水、高压冲；也不说任何 IP 等级"


def _brand(product: str) -> str:
    return (product or "TECNO").split()[0]


def _product_desc(product: str) -> str:
    from app.creators import PRODUCT_LINES
    return PRODUCT_LINES.get(product, "")


def _scores_total(s: dict) -> float:
    keys = ("novelty", "hook", "integration", "local", "feasible", "safe")
    vals = [max(1, min(10, int(s.get(k) or 0))) for k in keys if s.get(k) is not None]
    # 卖点融合和钩子最重要
    w = {"novelty": 1.2, "hook": 1.3, "integration": 1.3, "local": 1.0, "feasible": 0.8, "safe": 0.4}
    return round(sum(max(1, min(10, int(s.get(k) or 0))) * w[k] for k in keys) / sum(w.values()) * 10) if vals else 0


def start_job(params: dict) -> str:
    jid = new_id("sj")
    _jobs[jid] = {"id": jid, "status": "running", "stage": "准备", "params": params, "batch": jid, "scripts": [], "error": ""}
    for old in list(_jobs)[:-20]:
        _jobs.pop(old, None)
    return jid


async def write_shots(s: LibScript, improve: str = "", comment: str = "") -> list:
    from app.wash import split_cuts
    from app.workflows import _normalize_shots
    c = s.concept or {}
    user = (f"创意：{c.get('title')}｜{c.get('logline')}\n钩子：{c.get('hook')}\n反转：{c.get('twist')}\n卖点证明：{c.get('product_moment')}\n"
            f"热点：{c.get('trend') or '无'}" + (f"\n评审改进意见：{improve}" if improve else "")
            + (f"\n当前剧本：{json.dumps(s.shots, ensure_ascii=False)}\n修改意见：{comment}（只按意见改，其他保持）" if comment else ""))
    specs = (s.concept or {}).get("specs") or ""
    out = await llm.chat_json(WRITE_PROMPT.format(market=s.market, product=s.product, selling_point=s.selling_point, audience=s.audience,
                                                  lang=LANG.get(s.market, "当地常用语言"), specs=specs or "（没给）", water_rule=_water_rule(specs)),
                              user, task="script", timeout=120)
    rows = [r for r in out.get("shots") or [] if isinstance(r, list) and len(r) >= 2]
    if len(rows) < 3:
        raise RuntimeError("模型写的分镜太少")
    return split_cuts(_normalize_shots(rows))[0]


async def generate(jid: str) -> None:
    job = _jobs[jid]
    p = job["params"]
    try:
        if not settings_store.llm_enabled():
            raise RuntimeError("剧本库需要大模型：到「设置」里填 OpenRouter Key")
        tr = list(p.get("trends") or [])
        k = max(1, min(5, int(p.get("count") or 3)))
        job["stage"] = "头脑风暴：一次想 8 个创意"
        ideas = (await llm.chat_json(IDEA_PROMPT.format(
            brand=_brand(p["product"]), market=p["market"], product=p["product"], product_desc=_product_desc(p["product"]),
            selling_point=p["selling_point"], audience=p["audience"], formats="、".join(p.get("formats") or FORMATS[:3]),
            specs=p.get("specs") or "（没给）", water_rule=_water_rule(p.get("specs") or ""),
            trends="；".join(tr) or "（没有指定，自己挑本地人熟悉的日常场景）"),
            f"补充要求：{p.get('brief') or '无'}", task="script", timeout=150)).get("ideas") or []
        ideas = [i for i in ideas if isinstance(i, dict) and i.get("title")][:10]
        if not ideas:
            raise RuntimeError("模型没有给出创意")
        job["stage"] = f"评审：给 {len(ideas)} 个创意打分，挑最好的 {k} 个"
        listing = "\n".join(f"{n + 1}. 【{i.get('format')}】{i.get('title')}：{i.get('logline')}｜钩子：{i.get('hook')}｜卖点：{i.get('product_moment')}"
                            for n, i in enumerate(ideas))
        crit = await llm.chat_json(CRITIC_PROMPT.format(market=p["market"], product=p["product"], selling_point=p["selling_point"], k=k),
                                   listing, task="analysis", timeout=120)
        reviews = {int(r["i"]) - 1: r for r in crit.get("reviews") or [] if isinstance(r, dict) and str(r.get("i", "")).isdigit()}
        picked = {int(x["i"]) - 1: str(x.get("improve") or "") for x in crit.get("picked") or [] if isinstance(x, dict) and str(x.get("i", "")).isdigit()}
        if not picked:  # 评审没挑：按总分取前 k 个
            order = sorted(range(len(ideas)), key=lambda n: -_scores_total((reviews.get(n) or {}).get("scores") or {}))
            picked = {n: "" for n in order[:k]}
        rows: list[LibScript] = []
        with SessionLocal() as db:
            for n, idea in enumerate(ideas):
                rv = reviews.get(n) or {}
                sc = {kk: max(1, min(10, int(v))) for kk, v in (rv.get("scores") or {}).items() if str(v).lstrip("-").isdigit()}
                s = LibScript(id=new_id("ls"), batch=jid, market=p["market"], product=p["product"], selling_point=p["selling_point"],
                              audience=p["audience"], format=str(idea.get("format") or ""), title=str(idea.get("title"))[:40],
                              concept={**{kk: str(idea.get(kk) or "") for kk in ("logline", "hook", "twist", "product_moment", "trend", "why_viral", "risk", "title")},
                                       "specs": p.get("specs") or ""},
                              critic={"scores": sc, "total": _scores_total(sc), "verdict": str(rv.get("verdict") or ""), "improve": picked.get(n, ""),
                                      "picked": n in picked, "by": settings_store.get_models()["analysis"]},
                              status="writing" if n in picked else "concept")
                db.add(s)
                rows.append(s)
            db.commit()
            ids = [(s.id, s.critic.get("improve", "")) for s in rows if s.status == "writing"]
        job["stage"] = f"写分镜：{len(ids)} 个入选创意"
        await asyncio.gather(*(_write_one(sid, imp) for sid, imp in ids))
        job.update(status="done", stage=f"完成：{len(ids)} 个剧本 + {len(rows) - len(ids)} 个备选创意", scripts=[sid for sid, _ in ids])
    except Exception as e:  # noqa: BLE001
        log.exception("剧本库生成失败")
        job.update(status="error", error=str(e)[:300] or type(e).__name__, stage="失败")


async def _write_one(sid: str, improve: str = "", comment: str = "", rejudge: bool = False) -> None:
    with SessionLocal() as db:
        s = db.get(LibScript, sid)
        s.status, s.error = "writing", ""
        db.commit()
        db.expunge(s)
    try:
        shots = await write_shots(s, improve, comment)
        with SessionLocal() as db:
            s = db.get(LibScript, sid)
            s.shots, s.status = shots, "ok"
            if comment:
                s.version += 1
                from app.judges import merge_eval
                old = (s.evaluation or {}).get("judges") or {}
                ev = {k: v for k, v in merge_eval(s.evaluation).items() if k in ("history", "rounds")}  # 改过了：旧评测作废，保留版本轨迹
                if old:
                    ev["previous"] = {"total": old.get("total"), "verdict": old.get("verdict"), "version": s.version - 1}
                s.evaluation = ev
            db.commit()
        if rejudge:
            from app import judges
            await judges.run(sid)
    except Exception as e:  # noqa: BLE001
        with SessionLocal() as db:
            s = db.get(LibScript, sid)
            s.status, s.error = ("ok" if s.shots else "error"), f"写分镜失败：{str(e)[:200]}"
            db.commit()


# ---------- 评测 ----------

async def evaluate(sid: str) -> None:
    from app import panel
    from app.workflows import _personas
    with SessionLocal() as db:
        s = db.get(LibScript, sid)
        s.status = "evaluating"
        db.commit()
        shots, market, aud = s.shots, s.market, s.audience
    try:
        segs = [aud or "学生", "年轻上班族" if aud != "年轻上班族" else "学生"]
        personas = _personas(market, segs)
        res = await panel.run(personas, shots, [], [{"persona": p["id"]} for p in personas], seed=sid)
        rs = res["reactions"]
        ev = {"scores": res["scores"], "retention": res["retention"], "shot_rel": res["shot_rel"], "issue": res["issue"], "agents": res["agents"],
              "engine": res["engine"], "completion": round(100 * sum(1 for r in rs if r.get("completed")) / max(1, len(rs))),
              "clicks": sum(1 for r in rs if r.get("clicked")), "comments": [r["comment"] for r in rs if r.get("comment")][:8],
              "score": round(sum(res["scores"].values()) / len(res["scores"]) * 10), "at": datetime.utcnow().isoformat(),
              "note": "40 个本地虚拟用户读剧本（没有画面），逐镜和平时刷到的手机广告比；是相对判断，不是真实投放数据"}
        with SessionLocal() as db:
            s = db.get(LibScript, sid)
            from app.judges import merge_eval
            cur = merge_eval(s.evaluation, (s.evaluation or {}).get("judges"))
            s.evaluation, s.status, s.error = {**cur, "audience": ev}, "ok", ""  # 观众模拟和评委打分分开存
            db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("剧本评测失败 %s：%s", sid, e)
        with SessionLocal() as db:
            s = db.get(LibScript, sid)
            s.status, s.error = "ok", f"评测失败：{str(e)[:200]}"
            db.commit()


# ---------- 用到画布 ----------

SP_MAP = {"省电续航": "续航", "快充": "续航", "拍照夜拍": "拍照", "大存储": "存储"}


def to_canvas(sid: str, pid: str) -> str:
    """剧本放到项目画布上，进入审核（审核通过后照常出分镜、选角、生成视频）。返回节点 ID。"""
    from app import storyboard
    from app.events import spawn
    from app.workflows import _done
    with SessionLocal() as db:
        s = db.get(LibScript, sid)
        project = db.get(Project, pid)
        if not s or not project or not s.shots:
            raise ValueError("剧本还没写好，或者项目不存在")
        from app.compose import secs
        total = sum(secs(x[0]) for x in s.shots)
        n = canvas.create_node(db, project, "script", sub=f"{s.selling_point} · {s.audience} · {total:g}s", status="run",
                               data={"shots": [list(x) for x in s.shots], "selling_point": SP_MAP.get(s.selling_point, s.selling_point),
                                     "audience": s.audience, "model_sku": s.product, "from_library": s.id, "lib_title": s.title,
                                     "language": LANG.get(s.market, "")}, title=f"剧本 · {s.title}")
        canvas.bump(project)
        s.used = [*(s.used or []), {"pid": pid, "node_id": n.id, "at": datetime.utcnow().isoformat()}]
        _done(db, n, f"剧本库「{s.title}」：{s.format} · {s.selling_point}，{len(s.shots)} 镜 {total:g} 秒",
              f"来自剧本库；创意评审 {s.critic.get('total', '—')} 分" + (f"，5 评委打分 {jd['total']} 分（{jd['verdict']}）" if (jd := (s.evaluation or {}).get("judges")) else "，还没做评委打分"))
        nid = n.id
    emit(pid, "canvas")
    if settings_store.llm_enabled():
        spawn(storyboard.run(nid))
    return nid


def script_dict(s: LibScript) -> dict:
    return {"id": s.id, "batch": s.batch, "market": s.market, "product": s.product, "selling_point": s.selling_point, "audience": s.audience,
            "format": s.format, "title": s.title, "concept": s.concept, "critic": s.critic, "shots": s.shots, "evaluation": s.evaluation,
            "status": s.status, "error": s.error, "used": s.used, "version": s.version, "created_at": s.created_at.isoformat()}
