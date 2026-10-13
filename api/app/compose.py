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
import textwrap
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


def plan(video: Node, script: Node | None) -> list[dict]:
    """每镜：片段地址、剪多长、字幕（口播）、贴片（卖点文字）。"""
    shots = (script.data or {}).get("shots") if script else (video.data or {}).get("shots") or []
    specs = ((script.data or {}).get("cast") or {}).get("specs") or [] if script else []
    tasks = (video.data or {}).get("tasks") or []
    out = []
    for i, s in enumerate(shots or []):
        t = tasks[i] if i < len(tasks) else {}
        sp = specs[i] if i < len(specs) else {}
        out.append({"shot": i + 1, "src": t.get("url") or "", "dur": secs(s[0]), "line": (s[2] if len(s) > 2 else "").strip(),
                    "overlay": (sp.get("overlay") or "").strip(), "keyframe": t.get("keyframe")})
    return out


def _wrap(text: str, width: int = 26) -> str:
    return "\n".join(textwrap.wrap(text, width)[:3])


def _filters(parts: list[dict], tmp: Path, captions: bool, fonts: dict) -> str:
    chains = []
    for k, p in enumerate(parts):
        f = (f"[{k}:v]trim=0:{p['dur']:.2f},setpts=PTS-STARTPTS,scale={W}:{H}:force_original_aspect_ratio=increase,"
             f"crop={W}:{H},fps={FPS},format=yuv420p,setsar=1")
        if captions:
            # 文字放进文件再引用，避免 drawtext 的转义问题
            font = _font_for(p["line"], fonts)
            if p["line"] and font:
                tf = tmp / f"line{k}.txt"
                tf.write_text(_wrap(p["line"]), encoding="utf-8")
                f += (f",drawtext=fontfile='{font}':textfile='{tf}':fontsize=40:fontcolor=white:line_spacing=8:"
                      f"box=1:boxcolor=black@0.45:boxborderw=14:x=(w-text_w)/2:y=h-text_h-150")
            font = _font_for(p["overlay"], fonts)
            if p["overlay"] and font:
                of = tmp / f"ov{k}.txt"
                of.write_text(_wrap(p["overlay"], 18), encoding="utf-8")
                f += (f",drawtext=fontfile='{font}':textfile='{of}':fontsize=58:fontcolor=white:borderw=4:bordercolor=black@0.7:"
                      f"x=(w-text_w)/2:y=170")
        chains.append(f + f"[v{k}]")
    return ";".join(chains) + ";" + "".join(f"[v{k}]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[out]"


def render(parts: list[dict], files: list[Path], out: Path, tmp: Path, captions: bool) -> dict:
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("没有 ffmpeg：在 api 目录运行 pip install -r requirements.txt（会装上 imageio-ffmpeg），或 brew install ffmpeg")
    fonts = {"latin": font_file(), "cjk": font_file(cjk=True)}
    font = fonts["latin"] or fonts["cjk"]
    tried = []
    for use_caps in ([True, False] if captions and font else [False]):
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-y"]
        for f in files:
            cmd += ["-i", str(f)]
        cmd += ["-filter_complex", _filters(parts, tmp, use_caps, fonts), "-map", "[out]", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if p.returncode == 0 and out.exists():
            skipped = [p["shot"] for p in parts if use_caps and any(t and not _font_for(t, fonts) for t in (p["line"], p["overlay"]))]
            return {"captions": use_caps, "font": font if use_caps else None, "skipped_text": skipped}
        tried.append(p.stderr[-300:])
        log.warning("合成失败（字幕=%s）：%s", use_caps, p.stderr[-300:])
    raise RuntimeError("ffmpeg 合成失败：" + (tried[-1] if tried else ""))


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
        parts = plan(video, script) if video else []
        pid = cut.project_id
    if not parts:
        _set(cut_id, status="failed", sub="没有找到视频片段")
        return
    _set(cut_id, status="run", sub="合成中…", data={"video_id": vid, "parts": parts, "stage": "下载片段", "error": None})
    real = [p for p in parts if p["src"].startswith("http")]
    total = round(sum(p["dur"] for p in parts), 1)
    sig = hashlib.sha1("|".join(p["src"] for p in parts).encode()).hexdigest()[:10]
    try:
        if len(real) < len(parts):
            # 演示模式 / 有镜头没出视频：只记录拼接方案
            missing = [p["shot"] for p in parts if not p["src"].startswith("http")]
            if real:
                raise RuntimeError(f"第 {'、'.join(map(str, missing))} 镜还没有视频片段，先把这些镜头生成出来")
            _set(cut_id, data={"video_url": None, "mock": True, "duration": total, "source_sig": sig, "stage": "完成"},
                 sub=f"模拟成片 · {len(parts)} 镜 · {total:g} 秒")
        else:
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d)
                files = []
                async with httpx.AsyncClient(timeout=180, transport=transport, follow_redirects=True) as c:
                    for k, p in enumerate(parts):
                        r = await c.get(p["src"])
                        r.raise_for_status()
                        f = tmp / f"s{k}.mp4"
                        f.write_bytes(r.content)
                        files.append(f)
                _set(cut_id, data={"stage": "拼接与字幕"})
                outdir = config.MEDIA_DIR / "cuts"
                outdir.mkdir(parents=True, exist_ok=True)
                out = outdir / f"{cut_id}-{sig}.mp4"
                info = await asyncio.to_thread(render, parts, files, out, tmp, captions)
            url = f"/api/v1/media/cuts/{out.name}"
            _set(cut_id, data={"video_url": url, "mock": False, "duration": total, "source_sig": sig, "stage": "完成",
                               "burned": info["captions"], "font": info["font"], "skipped_text": info["skipped_text"]},
                 sub=f"{len(parts)} 镜 · {total:g} 秒 · 9:16" + (" · 已加字幕" if info["captions"] else ""))
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
