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

import httpx

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
PRODUCT_SHOT = 2  # 默认第 3 镜是产品特写；洗剧本时按参考爆款的产品位置写在剧本 data.product_shots


def product_shots(data: dict, n: int) -> set[int]:
    """剧本里手机是画面主体的镜头（从 0 开始）。"""
    ps = {int(i) for i in (data or {}).get("product_shots") or [] if isinstance(i, int) and 0 <= i < n}
    return ps or ({PRODUCT_SHOT} if n > PRODUCT_SHOT else {max(0, n - 1)})


def ref_shot(data: dict, i: int) -> dict | None:
    """洗稿剧本第 i 镜对应的原片镜头：原片这一帧（构图参考）+ 拆解出的景别、站位、手机朝向。没有对应就返回 None。"""
    w = (data or {}).get("wash") or {}
    m = (w.get("map") or [])[i] if i < len(w.get("map") or []) else None
    k = (m or {}).get("ref")
    if not isinstance(k, int) or k < 1:
        return None
    refs = w.get("ref") or []
    r = dict(refs[k - 1]) if k - 1 < len(refs) else {}
    if w.get("ref_no") and not r.get("camera"):  # 老剧本存的少：从爆款的拆解里补上景别、站位
        from app.models import RefAd
        with SessionLocal() as db:
            a = db.query(RefAd).filter(RefAd.no == w["ref_no"]).first()
            bs = [x for x in ((a.dna or {}).get("breakdown") or {}).get("shots") or [] if isinstance(x, dict)] if a else []
        if k - 1 < len(bs):
            r = {**bs[k - 1], **{x: y for x, y in r.items() if y}}
    if not r:
        return None
    return {**r, "no": k, "tier": w.get("tier")}


SIZE_EN = [(r"大特写|极特写|ECU", "EXTREME CLOSE-UP: only the detail fills the frame"),
           (r"特写|CU", "CLOSE-UP: the object or face fills most of the frame"),
           (r"近景", "MEDIUM CLOSE-UP: people from the chest up"),
           (r"中景|MS", "MEDIUM SHOT: people from the knees or waist up, with the surroundings visible"),
           (r"全景|远景|WS|大全景", "WIDE SHOT: full bodies of everyone and the whole environment")]


def _composition(rs: dict) -> str:
    """原片这一镜的构图，写成画图模型最听得懂的英文硬要求，放在提示词最前面。"""
    import re
    cam = str(rs.get("camera") or "")
    size = next((en for pat, en in SIZE_EN if re.search(pat, cam)), "")
    bits = [f"COMPOSITION FIRST — copy the framing of reference image 1 (shot {rs['no']} of the original ad):" if rs.get("frame")
            else f"COMPOSITION FIRST — shot {rs['no']} of the original ad:"]
    if size:
        bits.append(f"shot size {size};")
    if rs.get("people") and rs["people"] not in ("无", "无人", "没有"):
        bits.append(f"people in frame: {rs['people']} (draw them, do not crop to hands only);")
    if rs.get("framing"):
        bits.append(f"layout: {rs['framing']};")
    if rs.get("phone_facing"):
        bits.append(f"phone side facing camera: {rs['phone_facing']};")
    bits.append("same camera angle and same direction of every person and prop (e.g. a vehicle seen from the front stays seen from the front).")
    return " ".join(bits)


def _prompt(project: Project, aud: str, shots: list, i: int, has_ref: bool, prod: set[int] | None = None, rs: dict | None = None) -> str:
    """rs：原片对应镜头（ref_shot）。有原片画面时，它是第 1 张参考图，照它的构图画；has_ref 时本片第 1 镜是后一张参考图。"""
    s = shots[i]
    lead = _composition(rs) if rs and rs.get("tier") != "low" else ""
    parts = [
        *([lead] if lead else []),
        STYLE,
        f"\n这是 {project.brand} 手机在{project.market}投放的 TikTok 竖屏广告分镜，目标人群：{project.market}的{aud}，人物都是{project.market}当地人。",
        f"全片 {len(shots)} 镜，现在画第 {i + 1} 镜（{s[0]}）。",
        f"画面：{s[1]}",
    ]
    with_frame = bool(rs and rs.get("frame"))
    if rs:
        loose = rs.get("tier") == "low"
        facts = "；".join(f"{k}：{rs[f]}" for k, f in (("景别 / 机位", "camera"), ("构图", "framing"), ("人物", "people"), ("动作", "action"),
                                                        ("手机朝向", "phone_facing")) if rs.get(f))
        parts.append(
            (f"第 1 张参考图是原片第 {rs['no']} 镜的画面，只用来参考构图。" if with_frame else f"原片第 {rs['no']} 镜：") +
            (f"构图可以按上面的画面描述调整，原片只作参考（{facts}）。" if loose else
             f"照原片的景别、机位角度、人物数量和站位、道具的位置大小和朝向、手机哪一面朝镜头来画（{facts}）；"
             "画面描述和原片冲突时，人物、服装、手机型号按画面描述，构图按原片。") +
            "人物换成画面描述里的当地人，不要照着原片人物的长相画；手机画成通用占位手机：简单的圆角长方形机身，背面只用一个小方块代表摄像头，不要画 iPhone、三星这类具体机型的镜头排列和造型，也不要任何标识；不要画原片里的品牌、logo、字幕和任何文字。")
    people_in_shot = bool(rs and rs.get("people") and rs["people"] not in ("无", "无人", "没有"))
    if i in (prod if prod is not None else {PRODUCT_SHOT}) and not people_in_shot:
        parts.append("这一镜是产品特写：画手机本身的特写（可以有手持），画手机的角度和姿态即可。不要画屏幕上的界面、参数、数字或任何文字，不要画品牌字样。")
    elif i in (prod if prod is not None else {PRODUCT_SHOT}):
        parts.append("手机要清楚可见，但按原片的景别画（有人就画人，不要改成手机特写）。屏幕上不画界面和文字。")
    if not (rs and rs.get("phone_facing")) and not with_frame:
        from app import production  # production 依赖本模块，延迟导入
        if production.shows_phone({"line": s[2] if len(s) > 2 else ""}, s[1]):
            parts.append("手机朝向：" + ("屏幕朝镜头（人把屏幕给别人看）。" if production.phone_facing({}, s[1]) == "screen"
                                         else "背面（摄像头）朝镜头，屏幕朝着拿手机的人。") + "手机只有一面是屏幕，背面不会两面都画。")
    if len(s) > 2 and s[2]:
        parts.append(f"这一镜的口播（只用来理解人物情绪，不要写进画面）：{s[2]}")
    if has_ref:
        parts.append(f"{'第 2 张' if with_frame else ''}参考图是同一支广告的第 1 镜：只用来保持同一主角的外形、发型、服装和完全相同的简笔画风"
                     + ("，不要照它的构图和景别（构图照第 1 张原片）。" if with_frame else "。"))
    return "\n".join(parts)


def _file(node_id: str, i: int, visual: str, model: str, ext: str):
    h = hashlib.sha1(f"{visual}|{model}".encode()).hexdigest()[:8]
    return config.MEDIA_DIR / "storyboards" / f"{node_id}-{i}-{h}.{ext}"


def _data_url(path) -> str | None:
    if path is None:
        return None
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


def preview(node_id: str, i: int) -> dict:
    """「重画」浮窗：这一镜上一轮用的提示词（改过的就是改过的）和默认提示词。"""
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n or n.type != "script":
            raise KeyError(node_id)
        project = db.get(Project, n.project_id)
        d = n.data or {}
    shots = [list(x) for x in d.get("shots", [])]
    if not 0 <= i < len(shots):
        raise IndexError(i)
    frames = list(d.get("frames") or []) + [None] * len(shots)
    has_ref = i != 0 and bool(frames[0])
    rs = ref_shot(d, i)
    default = _prompt(project, d.get("audience", "用户"), shots, i, has_ref, product_shots(d, len(shots)), rs)
    f = frames[i] or {}
    custom = bool(f.get("custom")) and f.get("visual") == shots[i][1]
    return {"prompt": f.get("prompt") if custom else default, "default": default, "custom": custom, "has_ref": has_ref,
            "ref_frame": (rs or {}).get("frame"), "ref_no": (rs or {}).get("no"),
            "frame": f.get("url"), "stale": bool(f) and f.get("visual") != shots[i][1]}


async def run(node_id: str, indices: list[int] | None = None, prompts: dict[int, str] | None = None) -> None:
    """画分镜。indices 为空时画全部缺失或过期的镜头；指定时强制重画这些镜头。prompts：人改过的提示词（按镜号）。"""
    if node_id in _running or not settings_store.llm_enabled():
        return
    _running.add(node_id)
    try:
        await _run(node_id, indices, prompts or {})
    except Exception as e:  # noqa: BLE001
        log.exception("分镜图生成失败")
        _update(node_id, storyboard={"status": "error", "error": (str(e) or type(e).__name__)[:200]})
    finally:
        _running.discard(node_id)


async def _run(node_id: str, indices: list[int] | None, prompts: dict[int, str]) -> None:
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n or n.type != "script":
            return
        project = db.get(Project, n.project_id)
        shots = [list(s) for s in (n.data or {}).get("shots", [])]
        frames = list((n.data or {}).get("frames") or [])
        aud = (n.data or {}).get("audience", "用户")
        prod = product_shots(n.data or {}, len(shots))
        refs = [ref_shot(n.data or {}, k) for k in range(len(shots))]
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
        old = frames[i] or {}
        # 人改过的提示词：这次传进来的优先；没传但上一轮是改过的、画面描述也没变，就沿用
        mine = prompts.get(i) or (old.get("prompt") if old.get("custom") and old.get("visual") == shots[i][1] else None)
        rs = refs[i]
        orig = _data_url(frame_path(rs["frame"])) if rs and rs.get("frame") else None  # 原片这一帧：照它的构图画
        text = mine or _prompt(project, aud, shots, i, bool(ref), prod, rs if orig else ({**rs, "frame": None} if rs else None))
        imgs = [u for u in (orig, ref) if u]
        content: list[dict] | str = [{"type": "text", "text": text}, *({"type": "image_url", "image_url": {"url": u}} for u in imgs)] if imgs else text
        try:
            img, mime = await llm.image(content, task="storyboard")
        except (httpx.TransportError, httpx.TimeoutException):  # 网络抖一下：再试一次
            try:
                img, mime = await llm.image(content, task="storyboard")
            except (httpx.TransportError, httpx.TimeoutException) as e:
                raise RuntimeError(f"连不上 OpenRouter（{type(e).__name__}）：网络或代理不稳，点「重画失败的分镜」再试") from None
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
                         "at": datetime.utcnow().isoformat(), "prompt": text, "custom": bool(mine)}
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
            errors.append(f"第 1 镜：{str(e)[:220] or type(e).__name__}")
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
                errors.append(f"第 {i + 1} 镜：{str(e)[:220] or type(e).__name__}")

    await asyncio.gather(*(guarded(i) for i in todo if i != 0))
    # 同一个原因（如余额不足）只说一次：「第 1、2、3、4 镜：……」
    by: dict[str, list[str]] = {}
    for e in errors:
        shot, _, why = e.partition("：")
        by.setdefault(why, []).append(shot.removeprefix("第 ").removesuffix(" 镜"))
    msg = "；".join(f"第 {'、'.join(sorted(v, key=int))} 镜：{why}" for why, v in by.items())
    _update(node_id, storyboard={"status": "error" if errors else "done", "done": total - len(errors), "total": total, "error": msg})
