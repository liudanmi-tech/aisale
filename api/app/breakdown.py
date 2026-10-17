"""爆款视频多模态拆解：真的看一遍视频，再拿去洗剧本。

1. 拿到视频文件：人工上传的 > TikTok 原始播放地址 > 让 Apify 把这条视频下载下来。
2. ffmpeg 每秒抽 1 帧（长视频均匀抽，最多 MAX_FRAMES 帧），音轨转成 16k 单声道 wav。
3. 帧（带秒数）+ 音轨 + 文案 / 字幕 一起交给多模态模型（设置里的 analysis 模型，默认 Gemini 2.5 Flash），
   逐镜输出场景、人物、动作、运镜、口播、屏幕文字、情绪和作用，再总结结构、爆款精髓和可替换元素。
   模型不收音频时退回只看帧 + 字幕，并在结果里注明。
结果写到 RefAd.dna["breakdown"]，状态在 dna["breakdown_status"]（running / done / failed）。
"""
import asyncio
import base64
import logging
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import httpx

from app import compose, config
from app.adapters import apify, llm
from app.db import SessionLocal
from app.events import spawn
from app.models import RefAd, SourceVideo

log = logging.getLogger(__name__)
transport: httpx.AsyncBaseTransport | None = None  # 测试时注入（下载视频）
MAX_FRAMES = 40
MAX_BYTES = 80_000_000
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Referer": "https://www.tiktok.com/"}
BEATS = ["钩子", "铺垫", "痛点", "冲突", "转折", "产品展示", "卖点证明", "情绪高潮", "行动号召"]

PROMPT = f"""你是短视频广告的拆片导演，在逐帧拆解一条竞品手机的爆款 TikTok 视频，拆完要交给编剧「洗剧本」：
保留它火的结构和手法，替换品牌、人物、场景和台词。
给你的是按时间顺序的画面帧（每帧前标了秒数）、音轨（如果有）、文案和字幕。只输出 JSON：
{{
  "summary": "一句话讲这条视频讲了什么故事",
  "duration": 视频总秒数,
  "people_count": 出镜总人数（不同的人算几个）,
  "cast": [{{"role": "角色名，如 主角 / 朋友 / 店员 / 路人", "count": 这个角色几个人, "gender": "性别", "age": "年龄段",
            "look": "外形：肤色、发型、身材", "wear": "穿着打扮", "acting": "表演：表情、情绪、动作习惯", "job": "在片中干什么、和其他人什么关系",
            "shots": [出现在第几镜，从 1 开始]}}],
  "scenes": [{{"name": "场景名", "detail": "环境、陈设、光线、时间、天气", "props": "关键道具（如 铲车、水桶）", "shots": [第几镜]}}],
  "hook_detail": {{"t": "钩子在第几秒", "visual": "那几秒画面里发生了什么", "line": "那几秒的口播 / 字幕", "why": "为什么能让人停下来"}},
  "shots": [{{
    "t": "起止秒，如 0–2.5s（按画面切换分镜，不要按固定间隔切）",
    "scene": "场景：在哪、环境和光线",
    "people": "画面里有谁（用 cast 的角色名），没人写「无」",
    "action": "人物做了什么、手机怎么出现",
    "camera": "景别 + 运镜，如 近景手持跟拍",
    "line": "这一镜的口播 / 对白原话（听不到写空字符串）",
    "text_on_screen": "屏幕上的字（没有写空字符串）",
    "emotion": "这一镜的情绪",
    "beat": "这一镜的作用，从这些里选 1 个：{'、'.join(BEATS)}",
    "product": 这一镜手机是否是画面主体（true / false）
  }}],
  "structure": {{
    "hook": "开头怎么抓人（具体写手法）",
    "hook_type": "痛点 / 悬念 / 对比 / 反差 / 提问 / 数字冲击 / 名人达人 / 福利促销 / 情绪共鸣 选 1",
    "conflict": "冲突或痛点是什么",
    "turn": "转折在哪一秒、怎么转",
    "product_reveal": "产品第几秒出现、怎么出现",
    "proof": "怎么证明卖点",
    "cta": "结尾的行动号召，没有写「无」",
    "emotion_curve": "情绪怎么起伏",
    "rhythm": "节奏：几个镜头、平均每镜几秒、怎么剪"
  }},
  "core": {{"device": "这条视频最大的看点，具体到画面（如「用铲车往手机上倒一整斗水」）", "why": "为什么抓人：反差、荒诞、规模、悬念……",
            "intensity": "强度：规模多大、多夸张、和日常差多远"}},
  "selling_point": "主打卖点",
  "why_viral": "为什么火：结合内容和数据 1–2 句",
  "essence": ["洗剧本必须保留的爆款精髓 3–5 条，第 1 条写核心看点和它的强度要求，每条写成能照着执行的规则，如「前 2 秒用反问句直击停电没电的痛点」"],
  "replaceable": ["可以替换的元素 3–6 条，如「小米机型 → 我方机型」「拉各斯街头 → 目标市场的同类场景」"],
  "confidence": "高 / 中 / 低"
}}
规则：只写画面和音轨里真有的东西，看不清的写「未知」；不要编造数字；分镜按真实画面切换来分。"""


def _set(no: int, **fields) -> None:
    with SessionLocal() as db:
        a = db.query(RefAd).filter(RefAd.no == no).first()
        if a:
            a.dna = {**(a.dna or {}), **fields}
            db.commit()


def upload_path(no: int) -> Path:
    return config.MEDIA_DIR / "refvideos" / f"{no}.mp4"


async def _download(url: str, dest: Path, headers: dict | None = None) -> None:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True, transport=transport) as c:
        async with c.stream("GET", url, headers=headers or {}) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"下载视频失败（HTTP {r.status_code}）")
            size = 0
            with dest.open("wb") as f:
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise RuntimeError("视频太大（超过 80MB）")
                    f.write(chunk)
    if dest.stat().st_size < 10_000:
        raise RuntimeError("下载到的不是视频文件")


def ytdlp_download(url: str, dest: Path) -> None:
    """用 yt-dlp 直接从 TikTok 下载（免费，不经 Apify）。没装 yt-dlp 时报错，换下一条路。"""
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("没装 yt-dlp（在 api 目录运行 pip install -r requirements.txt）") from None
    class _Quiet:  # 报错由下面整理后抛出，不往终端打
        def debug(self, msg): pass
        def info(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg): pass

    opts = {"outtmpl": str(dest), "format": "mp4/best", "quiet": True, "no_warnings": True, "noplaylist": True, "logger": _Quiet(),
            "max_filesize": MAX_BYTES, "socket_timeout": 30, "retries": 2, "overwrites": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:  # noqa: BLE001  yt-dlp 的报错带颜色码和前缀，整理一下
        msg = re.sub(r"^ERROR:\s*", "", re.sub(r"\x1b\[[0-9;]*m", "", str(e)).strip()).split("; please report")[0]
        if "Unexpected response" in msg:
            try:
                import curl_cffi  # noqa: F401
            except ImportError:
                msg += "（没装 curl_cffi，TikTok 会挡回：在 api 目录运行 pip install -r requirements.txt）"
        raise RuntimeError(msg[:240] or type(e).__name__) from None
    if not dest.exists() or dest.stat().st_size < 10_000:
        raise RuntimeError("下载到的不是视频文件")


async def fetch_video(ad: dict, dest: Path) -> str:
    """拿到视频文件，返回来源说明。依次试：人工上传 → 同步时存下的 TikTok 地址 → yt-dlp（免费）→ Apify（要额度）。"""
    up = upload_path(ad["no"])
    if up.exists():
        dest.write_bytes(up.read_bytes())
        return "人工上传的视频"
    dna = ad["dna"]
    errs = []
    raw = ad.get("raw") or {}
    for u in [*(raw.get("mediaUrls") or []), (raw.get("videoMeta") or {}).get("downloadAddr"), (raw.get("videoMeta") or {}).get("playAddr")]:
        if not u:
            continue
        try:
            await _download(u, dest, UA)
            return "TikTok 原视频"
        except Exception as e:  # noqa: BLE001
            errs.append(f"TikTok 存下的地址：{str(e) or type(e).__name__}")
            break  # 这几个地址是同一批、一起过期，试一个就够
    if dna.get("url"):
        try:
            await asyncio.to_thread(ytdlp_download, dna["url"], dest)
            return "TikTok 原视频（yt-dlp 下载）"
        except Exception as e:  # noqa: BLE001
            errs.append(f"yt-dlp：{str(e) or type(e).__name__}")
        try:
            await _download(await apify.post_media(dna["url"]), dest)
            return "TikTok 原视频（经 Apify 下载）"
        except Exception as e:  # noqa: BLE001
            errs.append(f"Apify：{str(e) or type(e).__name__}")
    raise RuntimeError("拿不到视频文件：" + ("；".join(errs) if errs else "这条爆款没有 TikTok 链接") + "。可以手动上传视频再拆解")


def _ffmpeg(*args: str) -> subprocess.CompletedProcess:
    exe = compose.ffmpeg_exe()
    if not exe:
        raise RuntimeError("没有 ffmpeg，无法抽帧")
    return subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True, timeout=300)


def duration(path: Path) -> float:
    p = subprocess.run([compose.ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def extract(video: Path, out: Path, no: int) -> tuple[float, list[dict], bytes | None]:
    """抽帧（存到 media/breakdown，详情页每镜配图用）+ 音轨。返回 (时长, [{t, url, data}], wav)。"""
    dur = duration(video)
    if dur <= 0:
        raise RuntimeError("读不出视频时长，文件可能损坏")
    step = max(1.0, dur / MAX_FRAMES)
    r = _ffmpeg("-i", str(video), "-vf", f"fps=1/{step:.3f},scale=360:-2", "-q:v", "5", str(out / "f%03d.jpg"))
    files = sorted(out.glob("f*.jpg"))
    if not files:
        raise RuntimeError(f"抽帧失败：{r.stderr[-200:]}")
    keep = config.MEDIA_DIR / "breakdown"
    keep.mkdir(parents=True, exist_ok=True)
    for old in keep.glob(f"{no}-*.jpg"):
        old.unlink()
    frames = []
    for k, f in enumerate(files):
        t = round(k * step, 1)
        name = f"{no}-{k:03d}.jpg"
        (keep / name).write_bytes(f.read_bytes())
        frames.append({"t": t, "url": f"/api/v1/media/breakdown/{name}", "data": "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode()})
    wav = out / "a.wav"
    _ffmpeg("-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-t", "120", str(wav))
    audio = wav.read_bytes() if wav.exists() and wav.stat().st_size > 2000 else None
    return dur, frames, audio


def _content(intro: str, frames: list[dict], audio: bytes | None) -> list[dict]:
    parts: list[dict] = [{"type": "text", "text": intro}]
    for f in frames:
        parts += [{"type": "text", "text": f"第 {f['t']} 秒"}, {"type": "image_url", "image_url": {"url": f["data"]}}]
    if audio:
        parts += [{"type": "text", "text": "下面是这条视频的音轨："},
                  {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio).decode(), "format": "wav"}}]
    return parts


async def analyze(intro: str, frames: list[dict], audio: bytes | None) -> tuple[dict, list[str]]:
    used = [f"画面 {len(frames)} 帧"]
    try:
        msg = await llm.chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": _content(intro, frames, audio)}],
                             json_mode=True, task="analysis", timeout=240)
        used += ["音轨"] if audio else []
    except Exception as e:  # noqa: BLE001  有的模型不收音频：只看帧 + 字幕再来一次
        if not audio:
            raise
        log.warning("带音轨拆解失败，改为只看画面：%s", e)
        msg = await llm.chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": _content(intro, frames, None)}],
                             json_mode=True, task="analysis", timeout=240)
        used.append("没听音轨（模型不收音频）")
    out = llm.parse_json(msg.get("content") or "")
    if not isinstance(out.get("shots"), list) or not out["shots"]:
        raise RuntimeError("模型没有给出分镜，请重试")
    return out, used


def _secs(t: str) -> float:
    m = re.match(r"\s*([\d.]+)", str(t or ""))
    return float(m[1]) if m else 0.0


_running: set[int] = set()  # 同一条爆款同时只拆一次（三个洗稿方案会同时要它）


def running(no: int) -> bool:
    return no in _running


async def run(no: int) -> None:
    if no in _running:
        return
    _running.add(no)
    _set(no, breakdown_status="running", breakdown_error="", breakdown_started=datetime.utcnow().isoformat())
    try:
        with SessionLocal() as db:
            a = db.query(RefAd).filter(RefAd.no == no).first()
            dna = dict(a.dna or {})
            sv = db.get(SourceVideo, dna.get("source_video_id")) if dna.get("source_video_id") else None
            ad = {"no": no, "dna": dna, "raw": (sv.raw if sv else None), "brand": a.brand, "market": a.market, "title": a.title}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            video = tmp_p / "v.mp4"
            source = await fetch_video(ad, video)
            dur, frames, audio = await asyncio.to_thread(extract, video, tmp_p, no)
        intro = (f"品牌：{ad['brand']}；市场：{ad['market']}；时长 {dur:.1f} 秒\n文案：{dna.get('text') or ad['title']}\n"
                 f"数据：播放 {dna.get('plays', '未知')}，点赞 {dna.get('likes', '未知')}，分享 {dna.get('shares', '未知')}，爆款倍数 {dna.get('multiple', '未知')}×")
        out, used = await analyze(intro, frames, audio)
        thumbs = [{"t": f["t"], "url": f["url"]} for f in frames]
        for s in out["shots"]:  # 每镜配一张它开头那一秒的画面
            if isinstance(s, dict):
                t0 = _secs(s.get("t"))
                s["frame"] = min(thumbs, key=lambda f: abs(f["t"] - t0 - 0.5))["url"]
        out.update(frames=thumbs, inputs=[source, *used], at=datetime.utcnow().isoformat(), video_duration=round(dur, 1))
        _set(no, breakdown=out, breakdown_status="done", breakdown_error="")
    except Exception as e:  # noqa: BLE001
        log.exception("拆解爆款 #%s 失败", no)
        _set(no, breakdown_status="failed", breakdown_error=(str(e) or type(e).__name__)[:400])
    finally:
        _running.discard(no)
    _resume_washes(no)


def _resume_washes(no: int) -> None:
    """拆解有结果了（成功或失败）：画布上因为缺视频停住的洗稿方案接着走（失败的会再停下、显示原因）。"""
    from app import workflows  # workflows 依赖本模块，延迟导入
    from app.events import emit
    from app.models import Node
    with SessionLocal() as db:
        ns = [n for n in db.query(Node).filter(Node.type == "wash", Node.status == "input") if (n.data or {}).get("ref_ad_no") == no]
        a = db.query(RefAd).filter(RefAd.no == no).first()
        if not ns or not a or (a.dna or {}).get("breakdown_status") != "done":
            return
        for n in ns:
            n.status, n.sub = "run", "视频拆解好了，正在出方案…"
        db.commit()
        for pid in {n.project_id for n in ns}:
            emit(pid, "canvas")
        ids = [n.id for n in ns]
    for nid in ids:
        spawn(workflows.plan_wash(nid))


def start(no: int) -> None:
    if no in _running:
        return
    _set(no, breakdown_status="running", breakdown_error="")
    spawn(run(no))
