"""视频质检：关键帧质检（图生视频前）+ 成片质检（图生视频后），不通过的镜头自动重做。

检查项（每项 pass / warn / fail，附原因）：
- 商品一致性（从严，任何一项不对就 fail）：多模态模型对照商品实拍图逐项检查颜色、摄像头模组、屏幕形态、机身比例、
  多余手机 / 竞品 logo；有商品的镜头一律要求人工确认。
- 人物一致性：人脸相似度（OpenCV YuNet 检测 + SFace 特征，余弦相似度，同一人阈值 0.363 为 OpenCV 推荐值），
  要求每个出场角色都能在画面里找到；同一角色匹配到多张脸提示「分身」；再由多模态模型看服装发型和人数。
- 画面质量：多模态模型按清单检查手部 / 面部畸形、肢体穿模、乱码文字、残留线稿、物理不合理；
  成片另用 ffmpeg 查规格（9:16、时长）、黑帧、冻帧，用 OpenCV 查模糊和闪烁。
- 剧本符合度：画面是否符合这一镜的描述和景别。
人脸模型首次使用时从 Hugging Face 下载（约 39MB）；拿不到时人脸检查标为「未执行」，不影响其他检查。
"""
import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import httpx

from app import assets, config, settings_store
from app.adapters import llm
from app.db import SessionLocal
from app.models import Asset

log = logging.getLogger(__name__)
FACE_PASS, FACE_WARN = 0.363, 0.30
MODELS = {
    "det": ("face_detection_yunet_2023mar.onnx", "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx"),
    "rec": ("face_recognition_sface_2021dec.onnx", "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx"),
}
media_transport: httpx.AsyncBaseTransport | None = None  # 测试时注入（下载成片）
LABELS = {"product": "商品一致", "people": "人物一致", "artifacts": "画面质量", "text": "无乱码文字", "script": "符合剧本", "face": "人脸相似度", "tech": "规格与画质"}
RANK = {"pass": 0, "skip": 0, "warn": 1, "fail": 2}

RUBRIC = """你是短视频广告的质检员，检查一张 AI 生成的广告画面（第 1 张图）。后面的参考图依次是：{refs}
只输出 JSON，每项 status 只能是 pass / warn / fail，reason 用中文一句话说明看到的问题（没问题写「无」）：
{{
  "product": {{"present": true/false 画面里有没有手机, "status": "...", "items": {{"颜色": "pass/warn/fail", "摄像头模组": "...", "屏幕形态": "...", "机身比例": "...", "无多余手机或竞品标志": "..."}}, "reason": "..."}},
  "people": {{"count": 画面里主要人物数量, "status": "...", "reason": "和参考定妆照比，服装、发型、配饰是否一致；人数是否符合要求"}},
  "artifacts": {{"status": "...", "items": ["发现的问题，如 手指畸形 / 面部扭曲 / 肢体穿模 / 物体悬空 / 残留线稿 / 画面割裂"], "reason": "..."}},
  "text": {{"status": "...", "reason": "画面里有没有可读文字、乱码、中文字符（应该一个都没有）"}},
  "script": {{"status": "...", "reason": "画面是否符合这一镜的描述和景别"}}
}}
规则：这一镜{product_rule}；要求出场的主要角色 {roles}（共 {n_roles} 个角色）；景别 {size}；画面描述：{visual}
- 商品检查从严：颜色、摄像头模组的形状 / 数量 / 排列、屏幕形态任何一项和实拍图不一致都判 fail。
- 不是商品特写的镜头：人物拿着手机很正常，不算问题；只在出现竞品标志或明显不是一个牌子的多部手机时提出来。
- 人物：背景里的路人、群演不算多出来的人；只看主要角色有没有出现、服装发型和定妆照是否一致；背对镜头的角色看服装体型。
- 文字：手机自身的品牌 logo 可以有。判 fail 的只有：任何中文字符、乱码或拼错的假文字、大块清晰可读的店招；
  手机屏幕界面、本子、小标签上的零星小字判 warn。
- 字幕、口播、价格贴片、门店 CTA 和品牌 logo 都在后期加，不要因为画面里没有它们扣分。
- 画面必须是一个连续的单镜头：拼图、分屏、多格画面算「画面割裂」，判 fail。"""


# ---------- 人脸 ----------

_face = {"loaded": False, "det": None, "rec": None, "error": ""}
_face_lock = threading.Lock()  # OpenCV 的检测器 / 识别器不是线程安全的（setInputSize 会改共享状态），几镜并发质检时要排队


def _model_path(name: str) -> Path:
    return config.MEDIA_DIR / "models" / name


def _ensure_face_models() -> bool:
    if _face["loaded"]:
        return _face["det"] is not None
    _face["loaded"] = True
    try:
        import cv2  # noqa: F401
    except ImportError:
        _face["error"] = "未安装 opencv-python-headless"
        return False
    try:
        for name, url in MODELS.values():
            p = _model_path(name)
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                with httpx.Client(timeout=120, follow_redirects=True) as c:
                    r = c.get(url)
                    r.raise_for_status()
                    p.write_bytes(r.content)
        import cv2
        _face["det"] = cv2.FaceDetectorYN.create(str(_model_path(MODELS["det"][0])), "", (320, 320), 0.7)
        _face["rec"] = cv2.FaceRecognizerSF.create(str(_model_path(MODELS["rec"][0])), "")
        return True
    except Exception as e:  # noqa: BLE001
        _face["error"] = f"人脸模型加载失败：{str(e)[:80]}"
        log.warning(_face["error"])
        return False


def _features(path: Path) -> list:
    import cv2
    img = cv2.imread(str(path))
    if img is None:
        return []
    h, w = img.shape[:2]
    det, rec = _face["det"], _face["rec"]
    det.setInputSize((w, h))
    _, found = det.detect(img)
    return [rec.feature(rec.alignCrop(img, f)) for f in (found if found is not None else [])]


def _local(url: str | None) -> Path | None:
    if not url or "/api/v1/media/" not in url:
        return None
    p = config.MEDIA_DIR / url.split("/api/v1/media/", 1)[1]
    return p if p.exists() else None


def face_check(frame: Path, spec: dict, cast: dict) -> dict:
    """每个出场角色在画面里能不能找到同一张脸；同一角色匹配到多张脸提示分身。"""
    try:
        with _face_lock:
            return _face_check(frame, spec, cast)
    except Exception as e:  # noqa: BLE001  人脸检查出错不影响其他检查
        log.warning("人脸检查出错：%s", e)
        return {"status": "skip", "reason": f"未执行：人脸检查出错（{str(e)[:60]}）", "scores": {}}


def _face_check(frame: Path, spec: dict, cast: dict) -> dict:
    roles = spec.get("roles") or []
    if not roles:
        return {"status": "skip", "reason": "这一镜没有出场演员", "scores": {}}
    if not _ensure_face_models():
        return {"status": "skip", "reason": f"未执行：{_face['error']}", "scores": {}}
    import cv2
    faces = _features(frame)
    rec = _face["rec"]
    scores, problems, worst = {}, [], "pass"
    with SessionLocal() as db:
        refs = {k: db.get(Asset, cast["roles"].get(k)) for k in roles}
    for k in roles:
        a = refs.get(k)
        ref_path = _local((a.images or [None])[0]) if a and a.images else None
        ref = _features(ref_path) if ref_path else []
        name = cast.get("names", {}).get(k, k)
        if not ref:
            problems.append(f"{name} 的定妆照里没检测到人脸")
            worst = max(worst, "warn", key=RANK.get)
            continue
        sims = sorted((float(rec.match(f, ref[0], cv2.FaceRecognizerSF_FR_COSINE)) for f in faces), reverse=True)
        best = sims[0] if sims else 0.0
        scores[name] = round(best, 2)
        if best < FACE_WARN:
            # 侧脸、背影、远景都检测不到正脸，这里只提示；人到底在不在交给多模态模型看服装体型
            problems.append(f"没找到 {name} 的正脸（最高相似度 {best:.2f}）")
            worst = max(worst, "warn", key=RANK.get)
        elif best < FACE_PASS:
            problems.append(f"{name} 不太像（相似度 {best:.2f}）")
            worst = max(worst, "warn", key=RANK.get)
        if len([s for s in sims if s >= FACE_PASS]) > 1:
            problems.append(f"画面里有不止一个人像 {name}（疑似分身）")
            worst = max(worst, "warn", key=RANK.get)
    return {"status": worst, "reason": "；".join(problems) or f"{len(roles)} 个出场角色都能对上定妆照", "scores": scores, "faces": len(faces)}


# ---------- 多模态模型按清单检查 ----------

def _asset_images(asset_id: str | None, limit: int = 3) -> list[str]:
    if not asset_id:
        return []
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        urls = list(a.images or [])[:limit] if a else []
    return [d for d in (assets.media_data_url(u) for u in urls) if d]


async def vlm_check(frames: list[str], shot: list, spec: dict, cast: dict) -> dict:
    """frames：待查画面（data URI，成片时是抽出来的几帧）；对照演员定妆照和商品实拍图。"""
    refs, desc = [], []
    for k in spec.get("roles") or []:
        imgs = _asset_images(cast["roles"].get(k), 1)
        refs += imgs
        desc += [f"角色「{cast.get('names', {}).get(k, k)}」定妆照"] * len(imgs)
    if spec.get("product"):
        imgs = _asset_images(cast.get("product"), 3)
        refs += imgs
        desc += ["商品实拍图"] * len(imgs)
    extra = f"（第 1–{len(frames)} 张是同一镜头按时间顺序抽出的帧，还要检查前后帧人物和商品有没有变化）" if len(frames) > 1 else ""
    names = [cast.get("names", {}).get(k, k) for k in spec.get("roles") or []]
    names = [f"{n}（群体角色，可以是多人）" if n.endswith("们") or "群" in n else n for n in names]
    text = RUBRIC.format(refs=("、".join(desc) or "无") + extra, product_rule="必须出现商品手机" if spec.get("product") else "不需要出现商品",
                         roles="、".join(names) or "无", n_roles=len(names), size=spec.get("size", "MS"), visual=shot[1] if len(shot) > 1 else "")
    content = [{"type": "text", "text": text}, *({"type": "image_url", "image_url": {"url": u}} for u in [*frames, *refs])]
    msg = await llm.chat([{"role": "user", "content": content}], json_mode=True, task="qc", timeout=120)
    out = llm.parse_json(msg.get("content") or "")
    res = {}
    for k in ("product", "people", "artifacts", "text", "script"):
        v = out.get(k) or {}
        st = v.get("status") if v.get("status") in RANK else "warn"
        if k == "product" and spec.get("product"):
            bad = [n for n, s in (v.get("items") or {}).items() if s != "pass"]
            if not v.get("present"):
                st, v["reason"] = "fail", "这一镜要求出现商品，但画面里没有手机"
            elif any((v.get("items") or {}).get(n) == "fail" for n in bad):
                st = "fail"  # 从严：任何一项不一致就不合格
            elif bad:
                st = max(st, "warn", key=RANK.get)
        elif k == "product":
            st = {"fail": "warn"}.get(st, st)  # 不是商品镜头：出现手机不算错，只提示
        elif k == "script":
            st = {"fail": "warn"}.get(st, st)  # 剧本符合度只提示，交给人判断，不触发重画
        res[k] = {"status": st, "reason": str(v.get("reason") or "")[:160], **({"items": v["items"]} if isinstance(v.get("items"), (dict, list)) else {})}
    return res


# ---------- 成片：ffmpeg / OpenCV ----------

def _ffmpeg_ok() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def tech_check(path: Path) -> dict:
    """规格、黑帧、冻帧、模糊、闪烁。"""
    problems, worst = [], "pass"
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    info = json.loads(p.stdout or "{}")
    st = (info.get("streams") or [{}])[0]
    w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    dur = float((info.get("format") or {}).get("duration") or 0)
    if not w or not h:
        return {"status": "fail", "reason": "视频文件无法解析"}
    if abs(w / h - 9 / 16) > 0.02:
        problems.append(f"画幅 {w}×{h} 不是 9:16")
        worst = "fail"
    if dur < 2.5:
        problems.append(f"时长只有 {dur:.1f} 秒")
        worst = "fail"
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "blackdetect=d=0.3:pix_th=0.10,freezedetect=n=0.003:d=1.0",
                        "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    if "black_start" in p.stderr:
        problems.append("有黑帧")
        worst = max(worst, "warn", key=RANK.get)
    if "freeze_start" in p.stderr:
        problems.append("有画面冻结（超过 1 秒不动）")
        worst = max(worst, "warn", key=RANK.get)
    try:
        import cv2
        cap = cv2.VideoCapture(str(path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 24
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        lum, sharp = [], []
        for idx in range(0, max(total, 1), max(1, int(fps / 2))):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, fr = cap.read()
            if not ok:
                break
            g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            lum.append(float(g.mean()))
            sharp.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
        cap.release()
        if sharp and sorted(sharp)[len(sharp) // 2] < 25:
            problems.append("画面偏模糊")
            worst = max(worst, "warn", key=RANK.get)
        if len(lum) > 2 and max(abs(a - b) for a, b in zip(lum, lum[1:])) > 45:
            problems.append("亮度突变（疑似闪烁或跳帧）")
            worst = max(worst, "warn", key=RANK.get)
    except ImportError:
        pass
    return {"status": worst, "reason": "；".join(problems) or f"{w}×{h} · {dur:.1f} 秒 · 无黑帧冻帧", "width": w, "height": h, "duration": round(dur, 1)}


def sample_frames(path: Path, n: int = 3) -> list[Path]:
    """均匀抽 n 帧（首、中、尾）存成 jpg。"""
    out = []
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=30)
    dur = float((p.stdout or "0").strip() or 0)
    for k in range(n):
        t = max(0.0, min(dur - 0.1, dur * (k + 0.5) / n)) if dur else 0
        f = path.with_name(f"{path.stem}-f{k}.jpg")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", str(f)], timeout=60)
        if f.exists():
            out.append(f)
    return out


def _data_url(path: Path) -> str:
    import base64
    return f"data:image/jpeg;base64,{base64.b64encode(path.read_bytes()).decode()}"


# ---------- 汇总 ----------

def summarize(checks: dict, spec: dict) -> dict:
    done = [c.get("status") for c in checks.values() if c.get("status") != "skip"]
    status = max(done, key=lambda s: RANK.get(s, 0)) if done else "skip"  # 一项都没查成就是「未执行」，不算通过
    issues = [f"{LABELS.get(k, k)}：{c['reason']}" for k, c in checks.items() if c.get("status") in ("warn", "fail") and c.get("reason")]
    return {"status": status, "checks": checks, "issues": issues, "manual_confirm": bool(spec.get("product"))}


async def check_keyframe(keyframe_url: str, shot: list, spec: dict, cast: dict) -> dict:
    """关键帧质检：人脸（本地）+ 清单（多模态模型）。"""
    path = _local(keyframe_url)
    checks: dict = {}
    if path:
        checks["face"] = await asyncio.to_thread(face_check, path, spec, cast)
    if settings_store.llm_enabled():
        frame = assets.media_data_url(keyframe_url)
        try:
            checks.update(await vlm_check([frame] if frame else [], shot, spec, cast))
        except Exception as e:  # noqa: BLE001
            checks["artifacts"] = {"status": "warn", "reason": f"模型质检没完成：{str(e)[:80]}"}
    return summarize(checks, spec)


async def check_clip(url: str, shot: list, spec: dict, cast: dict) -> dict:
    """成片质检：下载片段 → 规格画质（ffmpeg / OpenCV）→ 抽 3 帧看人脸和清单（检查前后帧是否变脸、商品是否变形）。"""
    if not (url or "").startswith("http"):
        return summarize({"tech": {"status": "skip", "reason": "模拟视频，未做成片质检"}}, spec)
    if not _ffmpeg_ok():
        return summarize({"tech": {"status": "skip", "reason": "未执行：服务器没装 ffmpeg，跳过成片检查（macOS：brew install ffmpeg）"}}, spec)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "clip.mp4"
        try:
            async with httpx.AsyncClient(timeout=120, transport=media_transport, follow_redirects=True) as c:
                r = await c.get(url)
                r.raise_for_status()
                path.write_bytes(r.content)
        except Exception as e:  # noqa: BLE001
            return summarize({"tech": {"status": "warn", "reason": f"下载视频失败：{str(e)[:80]}"}}, spec)
        checks = {"tech": await asyncio.to_thread(tech_check, path)}
        frames = await asyncio.to_thread(sample_frames, path)
        face = [await asyncio.to_thread(face_check, f, spec, cast) for f in frames]
        if face and any(f["status"] != "skip" for f in face):
            worst = max((f["status"] for f in face), key=lambda s: RANK.get(s, 0))
            checks["face"] = {"status": worst, "reason": "；".join(dict.fromkeys(f["reason"] for f in face if f["status"] in ("warn", "fail"))) or "首、中、尾帧人物都对得上",
                              "scores": [f.get("scores", {}) for f in face]}
        if settings_store.llm_enabled() and frames:
            try:
                checks.update(await vlm_check([_data_url(f) for f in frames], shot, spec, cast))
            except Exception as e:  # noqa: BLE001
                checks["artifacts"] = {"status": "warn", "reason": f"模型质检没完成：{str(e)[:80]}"}
    return summarize(checks, spec)


def merge(kf: dict | None, clip: dict | None, spec: dict, attempts: dict) -> dict:
    """一镜的质检结果：关键帧和成片两段，取更差的那个。"""
    parts = {k: v for k, v in (("keyframe", kf), ("clip", clip)) if v}
    if not parts:
        return {"status": "skip", "issues": [], "manual_confirm": bool(spec.get("product")), "attempts": attempts}
    # 成片检过的项以成片为准（关键帧的问题可能已经在重画时修好）
    checks = {**(kf or {}).get("checks", {}), **{k: v for k, v in (clip or {}).get("checks", {}).items() if v.get("status") != "skip"}}
    out = summarize(checks, spec)
    return {**out, "stages": {k: v["status"] for k, v in parts.items()}, "attempts": attempts}


def video_summary(tasks: list[dict]) -> dict:
    """视频节点头部的质检汇总。"""
    qs = [(t.get("shot"), t.get("qc") or {}) for t in tasks]
    count = {s: sum(1 for _, q in qs if q.get("status") == s) for s in ("pass", "warn", "fail")}
    checked = sum(count.values())
    status = "fail" if count["fail"] else "warn" if count["warn"] else "pass" if checked else "skip"
    text = "未执行" if not checked else (f"{count['pass']}/{checked} 镜通过" + (f" · {count['warn']} 镜待看" if count["warn"] else "")
                                         + (f" · {count['fail']} 镜不合格" if count["fail"] else ""))
    issues = [f"第 {n} 镜 {x}" for n, q in qs for x in q.get("issues", [])]
    retried = sum(max(0, (q.get("attempts") or {}).get("keyframe", 0) - 1) + max(0, (q.get("attempts") or {}).get("clip", 0) - 1) for _, q in qs)
    return {"status": status, "text": text, **count, "issues": issues, "retried": retried,
            "manual": [n for n, q in qs if q.get("manual_confirm")]}
