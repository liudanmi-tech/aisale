"""剧本分镜图：按剧本每一镜的画面描述，调用 Gemini 画电影学院风格的简笔分镜（铅笔草图、黑白、标景别和运镜箭头）。

- 先画第 1 镜，再把它作为参考图画其余镜头，保持主角外形和画风一致。
- 图片存到 MEDIA_DIR/storyboards，节点 data.frames[i] = {url, visual, model}；某一镜的画面描述改了，那一镜标为「需重画」。
- 剧本生成或重做完成后自动画（需要 OpenRouter Key）；详情页也可以整组重画或单镜重画。
"""
import asyncio
import base64
import hashlib
import logging
from datetime import datetime

from app import config, settings_store
from app.adapters import llm
from app.db import SessionLocal
from app.events import emit
from app.models import Node, Project

log = logging.getLogger(__name__)
CONCURRENCY = 3
_running: set[str] = set()

STYLE = (
    "Film-school storyboard panel. A quick, simple pencil sketch on white paper: loose confident black outlines, minimal detail, "
    "simple shapes for the background, light hatching only for shadows, no color, no gradients. Vertical 9:16 panel with a thin "
    "hand-drawn border. The only text allowed is a tiny handwritten shot size (WS / MS / CU / ECU) in the top-left corner; use simple "
    "arrows to show camera or subject movement. Do not write dialogue, captions, brand names or any other words."
)
PRODUCT_SHOT = 2  # 第 3 镜是产品特写（成片用官方素材），分镜里画手机特写示意


def _prompt(project: Project, aud: str, shots: list, i: int, has_ref: bool) -> str:
    s = shots[i]
    parts = [
        STYLE,
        f"\n这是 {project.brand} 手机在{project.market}投放的 TikTok 竖屏广告分镜，目标人群：{project.market}的{aud}，人物都是{project.market}当地人。",
        f"全片 {len(shots)} 镜，现在画第 {i + 1} 镜（{s[0]}）。",
        f"画面：{s[1]}",
    ]
    if i == PRODUCT_SHOT:
        parts.append("这一镜是产品特写：画手机本身的特写（可以有手持），突出电池 / 屏幕等卖点的示意，不要画品牌字样。")
    if len(s) > 2 and s[2]:
        parts.append(f"这一镜的口播（只用来理解人物情绪，不要写进画面）：{s[2]}")
    if has_ref:
        parts.append("参考图是同一支广告的第 1 镜：保持同一主角的外形、发型、服装和完全相同的简笔画风。")
    return "\n".join(parts)


def _file(node_id: str, i: int, visual: str, model: str, ext: str):
    h = hashlib.sha1(f"{visual}|{model}".encode()).hexdigest()[:8]
    return config.MEDIA_DIR / "storyboards" / f"{node_id}-{i}-{h}.{ext}"


def _data_url(path) -> str | None:
    try:
        b = path.read_bytes()
    except OSError:
        return None
    ext = path.suffix.lstrip(".") or "png"
    return f"data:image/{'jpeg' if ext == 'jpg' else ext};base64,{base64.b64encode(b).decode()}"


def _update(node_id: str, **fields) -> None:
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            return
        n.data = {**(n.data or {}), **fields}
        db.commit()
        emit(n.project_id, "canvas")


def frame_path(url: str):
    return config.MEDIA_DIR / url.split("/api/v1/media/", 1)[1] if url and "/api/v1/media/" in url else None


async def run(node_id: str, indices: list[int] | None = None) -> None:
    """画分镜。indices 为空时画全部缺失或过期的镜头；指定时强制重画这些镜头。"""
    if node_id in _running or not settings_store.llm_enabled():
        return
    _running.add(node_id)
    try:
        await _run(node_id, indices)
    except Exception as e:  # noqa: BLE001
        log.exception("分镜图生成失败")
        _update(node_id, storyboard={"status": "error", "error": (str(e) or type(e).__name__)[:200]})
    finally:
        _running.discard(node_id)


async def _run(node_id: str, indices: list[int] | None) -> None:
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n or n.type != "script":
            return
        project = db.get(Project, n.project_id)
        shots = [list(s) for s in (n.data or {}).get("shots", [])]
        frames = list((n.data or {}).get("frames") or [])
        aud = (n.data or {}).get("audience", "用户")
    frames += [None] * (len(shots) - len(frames))
    frames = frames[: len(shots)]
    if indices is None:
        todo = [i for i, s in enumerate(shots) if not frames[i] or frames[i].get("visual") != s[1]]
    else:
        todo = [i for i in indices if 0 <= i < len(shots)]
    if not todo:
        return
    model = settings_store.get_models()["storyboard"]
    (config.MEDIA_DIR / "storyboards").mkdir(parents=True, exist_ok=True)
    total, done = len(todo), {"n": 0}
    _update(node_id, storyboard={"status": "running", "done": 0, "total": total, "error": ""})

    async def draw(i: int, ref: str | None) -> None:
        content: list[dict] | str = _prompt(project, aud, shots, i, bool(ref))
        if ref:
            content = [{"type": "text", "text": content}, {"type": "image_url", "image_url": {"url": ref}}]
        img, mime = await llm.image(content, task="storyboard")
        ext = {"image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
        path = _file(node_id, i, shots[i][1], model, ext)
        path.write_bytes(img)
        with SessionLocal() as db:
            n = db.get(Node, node_id)
            if not n:
                return
            cur = [list(s) for s in (n.data or {}).get("shots", [])]
            fr = list((n.data or {}).get("frames") or [])
            fr += [None] * (len(cur) - len(fr))
            if i < len(cur) and cur[i][1] == shots[i][1]:  # 画的过程中这一镜被改了就作废，下次再画
                fr[i] = {"url": f"/api/v1/media/storyboards/{path.name}", "visual": shots[i][1], "model": model,
                         "at": datetime.utcnow().isoformat()}
            done["n"] += 1
            n.data = {**(n.data or {}), "frames": fr[: len(cur)],
                      "storyboard": {"status": "running", "done": done["n"], "total": total, "error": ""}}
            db.commit()
            emit(n.project_id, "canvas")

    # 先定下第 1 镜的人物和画风，其余镜头以它为参考并行画
    first = frames[0] if frames and frames[0] and 0 not in todo else None
    ref = _data_url(frame_path(first["url"])) if first else None
    errors: list[str] = []
    if 0 in todo:
        try:
            await draw(0, None)
        except Exception as e:  # noqa: BLE001
            log.warning("分镜 %s 第 1 镜失败：%s", node_id, e)
            errors.append(f"第 1 镜：{str(e)[:80] or type(e).__name__}")
        with SessionLocal() as db:
            f0 = ((db.get(Node, node_id).data or {}).get("frames") or [None])[0]
        ref = _data_url(frame_path(f0["url"])) if f0 else None
    sem = asyncio.Semaphore(CONCURRENCY)

    async def guarded(i: int) -> None:
        async with sem:
            try:
                await draw(i, ref)
            except Exception as e:  # noqa: BLE001  单镜失败不影响其他镜
                log.warning("分镜 %s 第 %d 镜失败：%s", node_id, i + 1, e)
                errors.append(f"第 {i + 1} 镜：{str(e)[:80] or type(e).__name__}")

    await asyncio.gather(*(guarded(i) for i in todo if i != 0))
    _update(node_id, storyboard={"status": "error" if errors else "done", "done": total - len(errors), "total": total,
                                 "error": "；".join(errors)})
