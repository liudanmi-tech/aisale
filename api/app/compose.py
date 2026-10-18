"""成片合成：把视频节点里每镜的片段按剧本时长剪好，顺序拼成一条 9:16 成片，烧上口播字幕和卖点贴片。

成片节点（cut）接在视频节点后面，合成完自动进入 40 人评测。
ffmpeg：优先用系统里的 ffmpeg；没有就用 pip 包 imageio-ffmpeg 自带的（requirements 里已加），不用另外安装。
没有真实片段（演示模式）时只记录拼接方案，不出文件。
"""
import asyncio
import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from app import canvas, config
from app.db import SessionLocal
from app.events import emit
from app.models import Node, Project

log = logging.getLogger(__name__)
W, H, FPS = 720, 1280, 30
transport: httpx.AsyncBaseTransport | None = None  # 测试时注入（下载片段）
FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
         "/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"]


def ffmpeg_exe() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


CJK_FONTS = ["/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/STHeiti Medium.ttc",
             "/System/Library/Fonts/Hiragino Sans GB.ttc", "/System/Library/Fonts/PingFang.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "C:/Windows/Fonts/msyh.ttc"]


def font_file(cjk: bool = False) -> str | None:
    """字幕里有中文时要用带中文字形的字体（Arial / DejaVu 没有中文，会显示成方块）。"""
    return next((f for f in (CJK_FONTS if cjk else FONTS) if Path(f).exists()), None)


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3000-\u9fff\uff00-\uffef]", text))


def _font_for(text: str, fonts: dict) -> str | None:
    """有中文用中文字体；没有中文字体时这一条不烧（不显示成方块）。"""
    return fonts["cjk"] if _has_cjk(text) else fonts["latin"] or fonts["cjk"]


def secs(x) -> float:
    """「3」「3s」→ 3；「3–7s」→ 4。"""
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(x))]
    if len(nums) >= 2:
        return max(1.0, nums[1] - nums[0])
    return max(1.0, nums[0]) if nums else 4.0


def plan(video: Node, script: Node | None, trims: dict | None = None) -> list[dict]:
    """每镜：片段地址、从第几秒开始剪、剪多长、字幕（口播）、贴片（卖点文字）。
    trims 是你在成片节点上调的：{"镜号": {"start": 秒, "dur": 秒}}，dur 为空 = 用到片段结尾（整段）。"""
    shots = (script.data or {}).get("shots") if script else (video.data or {}).get("shots") or []
    specs = ((script.data or {}).get("cast") or {}).get("specs") or [] if script else []
    tasks = (video.data or {}).get("tasks") or []
    out = []
    for i, s in enumerate(shots or []):
        t = tasks[i] if i < len(tasks) else {}
        sp = specs[i] if i < len(specs) else {}
        tr = (trims or {}).get(str(i + 1)) or {}
        start = max(0.0, float(tr.get("start") or 0))
        full = "dur" in tr and not tr.get("dur")
        dur = round(float(tr["dur"]), 2) if tr.get("dur") else round(secs(s[0]), 2)
        out.append({"shot": i + 1, "src": t.get("url") or "", "start": round(start, 2), "dur": dur, "full": full, "script_dur": round(secs(s[0]), 2),
                    "trimmed": bool(tr), "line": (s[2] if len(s) > 2 else "").strip(),
                    "overlay": (sp.get("overlay") or "").strip(), "keyframe": t.get("keyframe")})
    return out


def _wrap(text: str, font, width: int) -> list[str]:
    """按像素宽度换行：英文按词，中文按字；最多 3 行。"""
    tokens = re.findall(r"[\u3000-\u9fff\uff00-\uffef]|\S+\s*|\s+", text)
    lines, cur = [], ""
    for t in tokens:
        if cur and font.getlength((cur + t).rstrip()) > width:
            lines.append(cur.rstrip())
            cur = t.lstrip()
        else:
            cur += t
    if cur.strip():
        lines.append(cur.rstrip())
    return lines[:3]


def caption_png(p: dict, fonts: dict, out: Path) -> bool:
    """把这一镜的字幕（底部、半透明底）和贴片（顶部、描边大字）画成透明 PNG，合成时叠在画面上。
    用 Pillow 画而不用 ffmpeg 的 drawtext：很多 ffmpeg（包括 Homebrew 和 imageio-ffmpeg 的）没编进 drawtext。"""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    drew = False
    if p["overlay"] and (f := _font_for(p["overlay"], fonts)):
        font = ImageFont.truetype(f, 58)
        y = 170
        for ln in _wrap(p["overlay"], font, W - 100):
            w = font.getlength(ln)
            d.text(((W - w) / 2, y), ln, font=font, fill="white", stroke_width=4, stroke_fill=(0, 0, 0, 180))
            y += 72
        drew = True
    if p["line"] and (f := _font_for(p["line"], fonts)):
        font = ImageFont.truetype(f, 40)
        lines = _wrap(p["line"], font, W - 120)
        lh = 52
        top = H - 150 - lh * len(lines)
        bw = max(font.getlength(ln) for ln in lines) + 40
        d.rounded_rectangle(((W - bw) / 2, top - 14, (W + bw) / 2, top + lh * len(lines) + 6), radius=12, fill=(0, 0, 0, 115))
        for k, ln in enumerate(lines):
            d.text(((W - font.getlength(ln)) / 2, top + k * lh), ln, font=font, fill="white")
        drew = True
    if drew:
        img.save(out)
    return drew


def clip_len(path: Path) -> float | None:
    """片段时长（读 ffmpeg 的 Duration 输出）。"""
    exe = ffmpeg_exe()
    if not exe:
        return None
    r = subprocess.run([exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=30)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def render(parts: list[dict], files: list[Path], out: Path, tmp: Path, captions: bool) -> dict:
    """files[k] 是第 k 镜的视频片段，或者（这一镜还没出视频时）它的关键帧图片，按剧本时长停留。"""
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("没有 ffmpeg：在 api 目录运行 pip install -r requirements.txt（会装上 imageio-ffmpeg），或 brew install ffmpeg")
    fonts = {"latin": font_file(), "cjk": font_file(cjk=True)}
    font = fonts["latin"] or fonts["cjk"]
    note = None if font else "没找到可用字体"
    try:
        import PIL  # noqa: F401
    except ImportError:
        font, note = None, "没装 Pillow：在 api 目录运行 python3 -m pip install -r requirements.txt 后重新合成"
    tried = []
    for use_caps in ([True, False] if captions and font else [False]):
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-y"]
        for p, f in zip(parts, files):
            if p.get("still"):
                cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{p['dur']:.2f}"]
            cmd += ["-i", str(f)]
        chains, n_in = [], len(files)
        for k, p in enumerate(parts):
            a = 0 if p.get("still") else p.get("start", 0)
            c = (f"[{k}:v]trim={a:.2f}:{a + p['dur']:.2f},setpts=PTS-STARTPTS,scale={W}:{H}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{H},fps={FPS},format=yuv420p,setsar=1")
            png = tmp / f"cap{k}.png"
            if use_caps and caption_png(p, fonts, png):
                cmd += ["-i", str(png)]
                c += f"[b{k}];[b{k}][{n_in}:v]overlay=0:0,format=yuv420p"
                n_in += 1
            chains.append(c + f"[v{k}]")
        graph = ";".join(chains) + ";" + "".join(f"[v{k}]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[out]"
        cmd += ["-filter_complex", graph, "-map", "[out]", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode == 0 and out.exists():
            skipped = [p["shot"] for p in parts if use_caps and any(t and not _font_for(t, fonts) for t in (p["line"], p["overlay"]))]
            if captions and not use_caps and not note:
                note = "加字幕时 ffmpeg 出错，这版没烧字幕：" + tried[-1][-120:]
            return {"captions": use_caps, "font": font if use_caps else None, "skipped_text": skipped, "caption_note": note if captions else None}
        tried.append(r.stderr[-300:])
        log.warning("合成失败（字幕=%s）：%s", use_caps, r.stderr[-300:])
    raise RuntimeError("ffmpeg 合成失败：" + (tried[-1] if tried else ""))


async def _fetch(c: httpx.AsyncClient, url: str) -> bytes:
    """片段 / 关键帧：远程地址下载；本平台自己存的（/api/v1/media/...）直接读文件。"""
    if url.startswith("/api/v1/media/"):
        return (config.MEDIA_DIR / url.removeprefix("/api/v1/media/")).read_bytes()
    if url.startswith("data:"):
        import base64
        return base64.b64decode(url.split(",", 1)[1])
    r = await c.get(url)
    r.raise_for_status()
    return r.content


def _real(p: dict) -> bool:
    return p["src"].startswith(("http", "/api/v1/media/"))


def _set(cut_id: str, **fields) -> None:
    with SessionLocal() as db:
        n = db.get(Node, cut_id)
        if not n:
            return
        for k, v in fields.items():
            if k == "data":
                n.data = {**(n.data or {}), **v}
            else:
                setattr(n, k, v)
        db.commit()
        emit(n.project_id, "canvas")


async def run(cut_id: str, comment: str = "") -> None:
    """合成成片；完成后自动进入评测（所有视频的成片都好了才一起评）。"""
    with SessionLocal() as db:
        cut = db.get(Node, cut_id)
        if not cut:
            return
        vid = (cut.data or {}).get("video_id") or next((n.id for n in canvas.upstream(db, cut.id) if n.type == "video"), None)
        video = db.get(Node, vid) if vid else None
        script = db.get(Node, (video.data or {}).get("script_id")) if video and (video.data or {}).get("script_id") else None
        captions = (cut.data or {}).get("captions", True)
        parts = plan(video, script, (cut.data or {}).get("trims")) if video else []
        pid = cut.project_id
    if not parts:
        _set(cut_id, status="failed", sub="没有找到视频片段")
        return
    _set(cut_id, status="run", sub="合成中…", data={"video_id": vid, "parts": parts, "stage": "下载片段", "error": None})
    real = [p for p in parts if _real(p)]
    sig = hashlib.sha1("|".join(p["src"] for p in parts).encode()).hexdigest()[:10]
    total = round(sum(p["dur"] for p in parts), 1)
    try:
        if not real:
            # 演示模式：没有真实片段，只记录拼接方案
            _set(cut_id, data={"video_url": None, "mock": True, "duration": total, "source_sig": sig, "stage": "完成"},
                 sub=f"模拟成片 · {len(parts)} 镜 · {total:g} 秒")
        else:
            # 有镜头还没出视频（例如商品镜头等人工确认）：先用它的关键帧静帧占位，保证能看完整条
            for p in parts:
                p["still"] = not _real(p)
            missing = [p["shot"] for p in parts if p["still"] and not p.get("keyframe")]
            if missing:
                raise RuntimeError(f"第 {'、'.join(map(str, missing))} 镜既没有视频也没有关键帧，先把这些镜头生成出来")
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d)
                files = []
                async with httpx.AsyncClient(timeout=180, transport=transport, follow_redirects=True) as c:
                    for k, p in enumerate(parts):
                        f = tmp / (f"s{k}.png" if p["still"] else f"s{k}.mp4")
                        f.write_bytes(await _fetch(c, p["keyframe"] if p["still"] else p["src"]))
                        files.append(f)
                        if not p["still"]:  # 片段实际多长：整段 / 开始点超出片段时按实际长度算
                            n = await asyncio.to_thread(clip_len, f)
                            if n:
                                p["clip_len"] = round(n, 2)
                                p["start"] = min(p["start"], max(0.0, n - 0.5))
                                p["dur"] = round(n - p["start"] if p["full"] else min(p["dur"], n - p["start"]), 2)
                total = round(sum(p["dur"] for p in parts), 1)
                _set(cut_id, data={"stage": "拼接与字幕"})
                outdir = config.MEDIA_DIR / "cuts"
                outdir.mkdir(parents=True, exist_ok=True)
                out = outdir / f"{cut_id}-{sig}.mp4"
                info = await asyncio.to_thread(render, parts, files, out, tmp, captions)
            url = f"/api/v1/media/cuts/{out.name}"
            stills = [p["shot"] for p in parts if p["still"]]
            _set(cut_id, data={"video_url": url, "mock": False, "duration": total, "source_sig": sig, "stage": "完成", "parts": parts,
                               "stills": stills, "burned": info["captions"], "font": info["font"], "skipped_text": info["skipped_text"], "caption_note": info["caption_note"]},
                 sub=f"{len(parts)} 镜 · {total:g} 秒 · 9:16" + (" · 已加字幕" if info["captions"] else "")
                 + (f" · 镜 {'、'.join(map(str, stills))} 暂用关键帧" if stills else ""))
            if stills:
                # 还缺视频的成片不进评测：等这些镜头生成好、视频再次通过后会自动重新合成
                _set(cut_id, status="pass")
                from app import agent  # 避免循环导入
                with SessionLocal() as db:
                    agent.say(db, pid, f"成片已合成，镜 {'、'.join(map(str, stills))} 还没有视频，先用关键帧静帧占位；"
                                       "这些镜头生成好、视频再次通过后会自动重新合成，再进入评测。")
                    db.commit()
                emit(pid, "chat")
                return
    except Exception as e:  # noqa: BLE001
        log.exception("成片合成失败 %s", cut_id)
        _set(cut_id, status="failed", sub="合成失败，可重新合成", data={"stage": "失败", "error": str(e)[:300]})
        return
    # 合成完：成片节点直接通过（视频已经审核过），自动进入评测
    from app import agent, workflows  # 避免循环导入
    with SessionLocal() as db:
        cut = db.get(Node, cut_id)
        cut.status = "pass"
        project = db.get(Project, pid)
        runs = agent.auto_advance(db, project, cut)
        db.commit()
        for k in ("canvas", "chat"):
            emit(pid, k)
    workflows.run(runs)
