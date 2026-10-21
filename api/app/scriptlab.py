"""剧本库：结合本地热点，原创「整活」型爆款剧本，最后落到产品卖点（打游戏不卡、省电、防水……）。

流程（后台任务，一批大约 1–2 分钟）：
1. 找热点：竞品雷达 + 达人雷达最近 30 天抓到的本地视频，按播放加权统计话题标签和背景音乐（真实数据，不花钱）；
   再加上你手填的热点、预置的本地常青话题（停电、堵车、足球……，标明是预置）
2. 创意锦标赛：8 路创意引擎（荒诞升级、POV、假新闻、恶作剧反转……）× 3 个不同的编剧模型，想约 40 个创意，
   参照爆款库里真实爆款的钩子结构；5 个评委按同样 5 个维度给创意打分，取前几名（同一路引擎最多 2 个）
3. 写分镜：一镜一个景别，口播用当地语言；编剧提示词里写明生成流程的能力边界，写完按 LINT 自检，超出范围的镜头自动改
4. 5 个评委给写好的剧本正式打分
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
from app.models import Creator, LibScript, Project, Setting, SourceVideo, WatchAccount, new_id
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
- 能用我们的 AI 流程拍出来（在这个范围里把钩子放开写）：
{production}
- 安全：不教人做危险动作，不嘲笑宗教 / 民族 / 残障，不点名贬低竞品
- 这次的创意引擎：{engine}——{engine_desc}。按这个套路想 {n} 个彼此差异大的创意；至少一半用上面的本地热点；用梗要用对意思和语气（照「当地说法」和「可以这样用」），不要硬套，也不要解释梗
- 真实爆款的钩子参照（只学结构，不要照抄）：
{hooks}
只输出 JSON：{{"ideas": [{{"title": "8 字以内的标题", "format": "形式", "logline": "一句话讲完这个故事", "hook": "前 2 秒画面",
"twist": "反转 / 笑点", "product_moment": "卖点怎么被证明（画面）", "trend": "用了哪个热点，没用写空", "why_viral": "为什么本地人会转发", "risk": "拍摄或合规风险"}}]}}"""

WRITE_PROMPT = """你是短视频广告编剧，把这个创意写成可以直接拍的分镜剧本（{market}，{product}，卖点：{selling_point}，人群：{audience}）。
只输出 JSON：{{"shots": [[时长秒数, "画面描述（中文）", "口播（{lang}）", "口播的中文对照"], ...]}}
规则：
- 6–8 镜，总时长 15–22 秒；第 1 镜 1.5–2 秒，就是创意里的钩子画面
- 一镜只有一个景别、一个机位：画面描述以景别开头（如「特写：」「中景：」），不许写「随后切…」，要切就拆成两镜
- 画面只写人物动作、表情、手机的角度和姿态、场景；不写屏幕上显示什么、不写画面里的文字（AI 画不准文字）；参数数字放进口播
- 卖点的证明镜头要清楚：手机是画面主体、哪一面朝镜头写清楚
- 参数只能用这些（没写的一个数字都不许编，口播里也不行）：{specs}；{water_rule}
- 主要人物不超过 3 个，每镜写清楚是谁
- 口播短、口语、像当地人说话；最后一镜一句带产品名的口号
- 我们的生成流程只能拍这些（写出范围外的镜头，可拍性会被扣分、成片也会崩）：
{production}"""


def _water_rule(specs: str) -> str:
    if re.search(r"IP6[78]|IP68|IP69", specs or "", re.I):
        return "防水可以拍短时间泡水（按给出的 IP 等级），不拍长时间浸泡、热水、海水"
    if re.search(r"IP6[0-6]|IP5\d", specs or "", re.I):
        return "按给出的 IP 等级只能拍溅水、淋雨、泼一杯水，不能掉进水里、泡水、冲水龙头"
    return "没给防水等级：只能拍溅几滴水、淋小雨，不能掉进水里、泡水、高压冲；也不说任何 IP 等级"


# 我们的生成流程（关键帧 + 图生视频）能稳定拍出来的范围：写进编剧提示词，写完再按 LINT 自检一遍
PRODUCTION = """  · 每镜最多 2 个主要人物露脸（第 3 个人只能是背影、手或虚化远景）；不要人群、观众、围观、全场
  · 动作要简单、慢、幅度小：转头、拿起、递过去、跳起来欢呼、瘫倒都行；不要打斗、追逐、空翻、翻滚、爆炸、高速运动
  · 手机屏幕不出现任何界面、游戏画面、文字：用手指动作、表情、音效、旁人反应来表现「游戏很流畅 / 很卡」；
    真要给屏幕内容，就在画面描述末尾写「〔后期贴屏〕」，后期再把真实录屏贴上去
  · 画面里不出现任何字幕、招牌字、标语、logo 文字
  · 每镜 1.5–4 秒，一镜一个景别、一个机位；同一个人前后服装发型不变
  · 场景尽量 1–2 个（换场景就是换一套背景，成本高）"""
LINT = [  # (规则说明, 正则, 例外)
    ("人群 / 群戏：每镜最多 2 个主要人物露脸", r"人群|一群|围观|观众|全场|众人|所有人|大家都|满屋|一屋子|三个人|三人|四个人|几个人", r"背影|虚化"),
    ("复杂 / 高速动作", r"打斗|追逐|追车|空翻|翻滚|爆炸|飞起|飞出|跳水|狂奔|飞扑|摔出", ""),
    ("屏幕内容：AI 画不准界面和游戏画面", r"屏幕(上|里)[^。；，]{0,12}(显示|游戏|画面|角色|界面|聊天|视频|文字|数字|血条)|游戏画面|游戏角色|界面", r"后期贴屏|看不到屏幕|屏幕背对"),
    ("画面里的文字", r"字幕|弹幕|标语|招牌上|写着|logo 文字|文字显示", ""),
]


def lint(shots: list) -> list[dict]:
    """可拍性自检：按生成流程的边界逐镜检查。返回 [{shot, rule, text}]。"""
    from app.compose import secs
    out = []
    if not 5 <= len(shots) <= 9:
        out.append({"shot": 0, "rule": f"镜头数 {len(shots)}：要 6–8 镜", "text": ""})
    for i, sh in enumerate(shots):
        v = str(sh[1]) if len(sh) > 1 else ""
        if secs(sh[0]) > 4.5:
            out.append({"shot": i + 1, "rule": f"这一镜 {secs(sh[0]):g} 秒：每镜不超过 4 秒", "text": v[:40]})
        if not re.match(r"\s*(大特写|特写|近景|中景|全景|远景|大全景|俯拍|仰拍|手部特写)", v):
            out.append({"shot": i + 1, "rule": "画面描述要以景别开头", "text": v[:40]})
        for rule, pat, exc in LINT:
            m = re.search(pat, v)
            if m and not (exc and re.search(exc, v)):
                out.append({"shot": i + 1, "rule": rule, "text": m.group(0)})
    return out


FIX_PROMPT = """下面这个分镜剧本有几处超出了我们 AI 生成流程的能力，只改有问题的镜头，其他镜头一个字都不动；改的时候保住这一镜原来的作用（钩子 / 反转 / 卖点证明）。
生成流程的范围：
{production}
只输出 JSON：{{"shots": [[时长秒数, "画面描述（中文）", "口播", "中文对照"], ...]}}（完整剧本，镜头数可以微调）"""


async def lint_fix(shots: list, model: str | None = None) -> tuple[list, list[dict]]:
    """自检不过的镜头让模型按生成流程的范围改一遍；改完还剩的问题一并返回（不阻塞）。"""
    from app.wash import split_cuts
    from app.workflows import _normalize_shots
    issues = lint(shots)
    if not issues:
        return shots, []
    try:
        out = await llm.chat_json(FIX_PROMPT.format(production=PRODUCTION),
                                  f"剧本：{json.dumps(shots, ensure_ascii=False)}\n要改的地方：\n" +
                                  "\n".join(f"- 镜 {x['shot']}：{x['rule']}（「{x['text']}」）" if x["shot"] else f"- 整体：{x['rule']}" for x in issues),
                                  task="script", timeout=120)
        rows = [r for r in out.get("shots") or [] if isinstance(r, list) and len(r) >= 2]
        if len(rows) >= 3:
            fixed = split_cuts(_normalize_shots(rows))[0]
            left = lint(fixed)
            if len(left) < len(issues):
                return fixed, left
    except Exception as e:  # noqa: BLE001  修不成就用原来的，问题照实标出来
        log.info("可拍性自检修改失败：%s", e)
    return shots, issues


def _brand(product: str) -> str:
    return (product or "TECNO").split()[0]


def _product_desc(product: str) -> str:
    from app.creators import PRODUCT_LINES
    return PRODUCT_LINES.get(product, "")


# 创意引擎：每一路用不同的套路想点子，逼出风格差异（同一个模型一次想 8 个，往往是同一种中庸的点子）
ENGINES = [
    ("荒诞升级", "一件小事越闹越大、越来越离谱，最后靠这台手机收场"),
    ("POV 第一视角", "「POV：你是……」，观众代入一个本地人都经历过的尴尬 / 倒霉瞬间，手机让局面反转"),
    ("假纪录片 / 新闻播报", "一本正经地播报或采访一件荒诞的小事，卖点是新闻里的「突发事件」"),
    ("恶作剧反转", "有人想整蛊主角，结果因为这台手机反被整"),
    ("预期 vs 现实", "先演观众以为会发生的惨剧，再给出因为这台手机而完全相反的现实"),
    ("梗模板改编", "直接套用当地正在火的梗 / 句式 / BGM 玩法，把卖点塞进梗的笑点位置"),
    ("对决挑战", "两个人（或两台手机）比赛，卖点决定胜负，输的人有好笑的惩罚"),
    ("身份错位", "妈妈 / 老板 / 保安 / 老师出现在意外的场合，用这台手机做出完全不符合身份的事"),
]
IDEAS_PER_CALL = 5


def writer_models() -> list[str]:
    """想创意用的编剧模型：设置里的剧本模型 + 另外两家，风格才会真的不一样。"""
    with SessionLocal() as db:
        st = db.get(Setting, "scriptlab")
        v = (st.value if st else {}) or {}
    main = settings_store.get_models()["script"]
    return list(dict.fromkeys(v.get("writers") or [main, "openai/gpt-6.1-sol", "google/gemini-3.8-flash"]))[:4]


def hook_bank(market: str, n: int = 8) -> list[str]:
    """真实爆款的钩子：爆款库里做过视频拆解的（前 2 秒发生了什么、为什么能让人停下），不够再用雷达里高播放本地视频的开头文案。"""
    from app.models import RefAd
    out = []
    with SessionLocal() as db:
        for a in db.query(RefAd).filter(RefAd.market == market).order_by(RefAd.hot_score.desc()).limit(40):
            bd = (a.dna or {}).get("breakdown") or {}
            h = bd.get("hook_detail") or {}
            if h.get("visual"):
                core = (bd.get("core") or {}).get("device") or ""
                out.append(f"{h['visual']}（为什么停下：{h.get('why', '')}）" + (f"；全片看点：{core}" if core else ""))
            if len(out) >= n:
                return out
        accs = [x.id for x in db.query(WatchAccount).filter(WatchAccount.market == market)]
        for v in db.query(SourceVideo).filter(SourceVideo.account_id.in_(accs)).order_by(SourceVideo.plays.desc()).limit(30):
            if v.text and len(out) < n:
                out.append(f"「{v.text[:70]}」（{v.plays:,} 播放，只有文案，没做拆解）")
    return out


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
                                                  lang=LANG.get(s.market, "当地常用语言"), specs=specs or "（没给）", water_rule=_water_rule(specs),
                                                  production=PRODUCTION), user, task="script", timeout=120)
    rows = [r for r in out.get("shots") or [] if isinstance(r, list) and len(r) >= 2]
    if len(rows) < 3:
        raise RuntimeError("模型写的分镜太少")
    shots, _left = await lint_fix(split_cuts(_normalize_shots(rows))[0])
    return shots


async def _ideas(p: dict, model: str, engine: tuple[str, str], hooks: list[str]) -> list[dict]:
    tr = list(p.get("trends") or [])
    out = await llm.chat_json(IDEA_PROMPT.format(
        brand=_brand(p["product"]), market=p["market"], product=p["product"], product_desc=_product_desc(p["product"]),
        selling_point=p["selling_point"], audience=p["audience"], formats="、".join(p.get("formats") or FORMATS[:3]),
        specs=p.get("specs") or "（没给）", water_rule=_water_rule(p.get("specs") or ""), production=PRODUCTION,
        trends="；".join(tr) or "（没有指定，自己挑本地人熟悉的日常场景）", engine=engine[0], engine_desc=engine[1], n=IDEAS_PER_CALL,
        hooks="\n".join(f"  · {h}" for h in hooks) or "  · （爆款库里还没有做过拆解的本地爆款）"),
        f"补充要求：{p.get('brief') or '无'}", task="script", timeout=150, model=model)
    return [{**i, "engine": engine[0], "writer": model} for i in out.get("ideas") or [] if isinstance(i, dict) and i.get("title")][:IDEAS_PER_CALL + 2]


async def generate(jid: str) -> None:
    """创意锦标赛：8 路创意引擎 × 3 个编剧模型想约 40 个创意 → 5 个评委给创意打分 → 前 k 名写成分镜（过可拍性自检）→ 5 评委正式打分。"""
    from app import judges
    job = _jobs[jid]
    p = job["params"]
    try:
        if not settings_store.llm_enabled():
            raise RuntimeError("剧本库需要大模型：到「设置」里填 OpenRouter Key")
        k = max(1, min(5, int(p.get("count") or 3)))
        hooks = hook_bank(p["market"])
        writers = writer_models()
        plan = [(writers[i % len(writers)], e) for i, e in enumerate(ENGINES)]
        job["stage"] = f"{len(ENGINES)} 路创意引擎 × {len(writers)} 个编剧模型，想约 {len(plan) * IDEAS_PER_CALL} 个创意"
        # 200 秒时有 6 路以上回来了就不等最慢的
        got = await judges.gather_quorum([_ideas(p, m, e, hooks) for m, e in plan], 200, max(1, len(plan) - 2))
        ideas = [i for g in got if isinstance(g, list) for i in g]
        bad = [f"{m.split('/')[-1]}·{e[0]}：{str(g)[:60] or type(g).__name__}" for (m, e), g in zip(plan, got) if isinstance(g, BaseException)]
        if not ideas:
            raise RuntimeError("创意都没想出来：" + "；".join(bad))
        job["stage"] = f"5 个评委给 {len(ideas)} 个创意打分（锦标赛初筛）"
        ctx = {"market": p["market"], "product": p["product"], "selling_point": p["selling_point"], "audience": p["audience"]}
        cs = await judges.score_concepts(ideas, ctx)
        order = sorted(range(len(ideas)), key=lambda i: -cs[i]["total"])
        picked, per_engine = [], {}
        for i in order:  # 前 k 名，同一路引擎最多 2 个，保证风格不同
            e = ideas[i]["engine"]
            if cs[i]["total"] and per_engine.get(e, 0) < 2:
                picked.append(i)
                per_engine[e] = per_engine.get(e, 0) + 1
            if len(picked) >= k:
                break
        rank = {i: n + 1 for n, i in enumerate(order)}
        rows: list[LibScript] = []
        with SessionLocal() as db:
            for i, idea in enumerate(ideas):
                c = cs[i]
                s = LibScript(id=new_id("ls"), batch=jid, market=p["market"], product=p["product"], selling_point=p["selling_point"],
                              audience=p["audience"], format=str(idea.get("format") or idea["engine"]), title=str(idea.get("title"))[:40],
                              concept={**{kk: str(idea.get(kk) or "") for kk in ("logline", "hook", "twist", "product_moment", "trend", "why_viral", "risk", "title")},
                                       "specs": p.get("specs") or "", "engine": idea["engine"], "writer": idea["writer"]},
                              critic={"scores": c["dims"], "total": c["total"], "judges": c["judges"], "spread": c.get("spread"), "rank": rank[i],
                                      "of": len(ideas), "picked": i in picked, "by": f"{c['judges']} 个评委（创意阶段）", "stage": "concept"},
                              status="writing" if i in picked else "concept")
                db.add(s)
                rows.append(s)
            db.commit()
            ids = [s.id for s in rows if s.status == "writing"]
        job["stage"] = f"写前 {len(ids)} 名的分镜，并做可拍性自检"
        await asyncio.gather(*(_write_one(sid) for sid in ids))
        job["stage"] = f"5 个评委给 {len(ids)} 个剧本正式打分"
        await asyncio.gather(*(judges.run(sid) for sid in ids))
        job.update(status="done", stage=f"完成：{len(ideas)} 个创意里挑出 {len(ids)} 个写成剧本并打分" + (f"（{len(bad)} 路创意没出来）" if bad else ""),
                   scripts=ids, warnings=bad)
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
