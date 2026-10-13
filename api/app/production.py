"""视频制作：分镜 → 选角置景 → 每镜关键帧 → 每镜视频。

1. 分镜：剧本还没画分镜的先补画（关键帧以分镜构图为参考）。
2. 选角置景（cast）：大模型拆剧本，得到剧情类型、角色、场景、哪几镜出商品，以及每镜的景别 / 运镜 / 出场角色 / 场景 / 话术；
   角色和场景优先复用本项目已有的素材，否则在素材库新建并 AI 生成定妆照 / 场景图；商品用素材库里同机型的实拍图。
   每个素材在画布上是一个节点（演员 / 场景 / 商品），连到视频节点；用户可以换素材、重新生成、上传图片。
3. 商品镜头需要商品实拍图：没有图时视频停在「待上传」，上传后自动继续。
4. 关键帧：每镜用 Gemini 图像模型生成一张真实质感的 9:16 画面，参考图依次是分镜草图、出场演员定妆照、场景图、商品图。
5. 视频：有 fal.ai Key 时每镜关键帧走 Seedance 图生视频；没有关键帧时退回文生视频；都没有 Key 时模拟。
"""
import asyncio
import hashlib
import json
import logging

from app import agent, assets, canvas, config, qc, settings_store, storyboard
from app.adapters import fal, llm, seedance
from app.db import SessionLocal
from app.events import emit
from app.models import Asset, Edge, Node, Project

log = logging.getLogger(__name__)
SIZES = ["WS", "MS", "CU", "ECU"]  # 全景 / 中景 / 特写 / 大特写
SIZE_ZH = {"WS": "全景", "MS": "中景", "CU": "特写", "ECU": "大特写"}
MOVES = ["固定", "推", "拉", "摇", "跟拍", "手持"]
GENRES = ["情景剧", "真人测评", "痛点对比", "开箱", "搞笑段子", "达人口播", "产品展示"]
PRODUCT_SHOT = 2
KF_RETRIES, CLIP_RETRIES = 2, 1  # 质检不合格时自动重做的次数
VIDEO_STYLE = "vertical 9:16 smartphone ad shot, photorealistic, natural light, no on-screen text, no watermark"
_slots = asyncio.Semaphore(2)

CAST_PROMPT = f"""你是短视频广告的制片和选角导演。根据剧本分镜拆出拍摄需要的角色、场景和每镜的拍法，只输出 JSON：
{{
  "genre": "从这些里选 1 个：{'、'.join(GENRES)}",
  "roles": [{{"key": "r1", "name": "角色名，如 女摊主", "description": "外观：性别、年龄、肤色、发型、服装、气质（用于生成定妆照，具体、可视化）", "reuse": "可复用的已有演员 id，没有写 null"}}],
  "scenes": [{{"key": "s1", "name": "场景名，如 雨夜的街头市场", "description": "环境、时间、天气、光线、道具", "reuse": "可复用的已有场景 id，没有写 null"}}],
  "specs": [{{"shot": 0, "size": "WS/MS/CU/ECU 之一", "move": "{'/'.join(MOVES)} 之一", "roles": ["r1"], "scene": "s1", "product": false, "line": "这一镜的话术（口播原文）"}}]
}}
规则：specs 每镜一条、顺序与分镜一致；人物都是目标市场的当地人；第 {PRODUCT_SHOT + 1} 镜是产品特写，product 为 true；
同一个人物在不同镜头用同一个 key；已有素材合适就复用（reuse 填它的 id），不要重复造人。"""


def _fallback_cast(shots: list) -> dict:
    return {"genre": "情景剧", "roles": [{"key": "r1", "name": "主角", "description": "25 岁左右的当地年轻人，生活化穿着", "reuse": None}],
            "scenes": [{"key": "s1", "name": "主场景", "description": shots[0][1] if shots else "", "reuse": None}],
            "specs": [{"shot": i, "size": ["WS", "MS", "CU", "MS"][i % 4], "move": "固定", "roles": [] if i == PRODUCT_SHOT else ["r1"],
                       "scene": "s1", "product": i == PRODUCT_SHOT, "line": s[2] if len(s) > 2 else ""} for i, s in enumerate(shots)]}


def _norm_specs(specs: list, shots: list, roles: set[str], scenes: set[str]) -> list[dict]:
    by = {int(s.get("shot", i)): s for i, s in enumerate(specs or []) if isinstance(s, dict)}
    out = []
    for i, sh in enumerate(shots):
        s = by.get(i, {})
        out.append({"shot": i, "size": s.get("size") if s.get("size") in SIZES else "MS",
                    "move": s.get("move") if s.get("move") in MOVES else "固定",
                    "roles": [r for r in (s.get("roles") or []) if r in roles], "scene": s.get("scene") if s.get("scene") in scenes else next(iter(scenes), None),
                    "product": bool(s.get("product", i == PRODUCT_SHOT)), "line": s.get("line") or (sh[2] if len(sh) > 2 else "")})
    return out


async def cast_script(script_id: str) -> dict:
    """拆剧本 → 角色 / 场景 / 商品与每镜拍法，写到剧本节点 data.cast。返回 cast。"""
    with SessionLocal() as db:
        s = db.get(Node, script_id)
        project = db.get(Project, s.project_id)
        shots = [list(x) for x in (s.data or {}).get("shots", [])]
        used = _project_assets(db, project.id)
        brand, sku, market = project.brand, project.model_sku, project.market
    existing = "\n".join(f"- {a['id']} | {a['kind']} | {a['name']} | {a['description'][:80]}" for a in used if a["kind"] in ("actor", "scene")) or "（无）"
    raw = None
    if settings_store.llm_enabled():
        try:
            raw = await llm.chat_json(CAST_PROMPT, f"目标市场：{market}；品牌机型：{brand} {sku}\n分镜（时长, 画面, 口播, 中文）：{json.dumps(shots, ensure_ascii=False)}\n"
                                                   f"本项目已有素材（id | 类型 | 名称 | 描述）：\n{existing}", task="script", timeout=120)
        except Exception as e:  # noqa: BLE001
            log.warning("选角拆解失败，用默认方案：%s", e)
    raw = raw if isinstance(raw, dict) and raw.get("roles") is not None else _fallback_cast(shots)
    valid = {a["id"]: a for a in used}
    roles, scenes, to_draw = {}, {}, []
    for kind, items, target in (("actor", raw.get("roles") or [], roles), ("scene", raw.get("scenes") or [], scenes)):
        for it in items[:4]:
            key = str(it.get("key") or f"{kind[0]}{len(target) + 1}")
            reuse = it.get("reuse")
            if reuse in valid and valid[reuse]["kind"] == kind:
                target[key] = reuse
                continue
            a = assets.create(kind, it.get("name") or assets.KINDS[kind], it.get("description") or "", data={"market": market})
            target[key] = a.id
            to_draw.append(a.id)
    product = _find_product(brand, sku)
    specs = _norm_specs(raw.get("specs"), shots, set(roles), set(scenes))
    cast = {"genre": raw.get("genre") if raw.get("genre") in GENRES else "情景剧", "roles": roles, "scenes": scenes,
            "product": product if any(x["product"] for x in specs) else None, "specs": specs,
            "names": {k: _name(v) for k, v in {**roles, **scenes}.items()}}
    with SessionLocal() as db:
        s = db.get(Node, script_id)
        s.data = {**(s.data or {}), "cast": cast}
        db.commit()
        emit(s.project_id, "canvas")
    await asyncio.gather(*(assets.generate_image(i) for i in to_draw))
    return cast


def _name(asset_id: str) -> str:
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        return a.name if a else ""


def _find_product(brand: str, sku: str) -> str:
    """素材库里同品牌同机型的商品；没有就建一个空的（等用户上传实拍图）。"""
    with SessionLocal() as db:
        for a in db.query(Asset).filter(Asset.kind == "product"):
            d = a.data or {}
            if (d.get("brand") or "").lower() == (brand or "").lower() and (d.get("model_sku") or "").lower() == (sku or "").lower():
                return a.id
    return assets.create("product", f"{brand} {sku}", f"{brand} {sku} 手机实拍", data={"brand": brand, "model_sku": sku}).id


def _project_assets(db, pid: str) -> list[dict]:
    ids = [(n.data or {}).get("asset_id") for n in canvas.nodes_of(db, pid) if n.type in ("actor", "scene", "product")]
    return [assets.asset_dict(a) for a in db.query(Asset).filter(Asset.id.in_([i for i in ids if i]))] if ids else []


def place_asset_nodes(video_id: str, cast: dict) -> None:
    """把用到的素材放到画布上（同一项目同一素材只放一个节点），连到视频节点。"""
    with SessionLocal() as db:
        v = db.get(Node, video_id)
        project = db.get(Project, v.project_id)
        on_canvas = {(n.data or {}).get("asset_id"): n for n in canvas.nodes_of(db, project.id) if n.type in ("actor", "scene", "product")}
        linked = {e.source for e in db.query(Edge).filter(Edge.target == video_id)}
        want = [("actor", a, k) for k, a in cast["roles"].items()] + [("scene", a, k) for k, a in cast["scenes"].items()]
        if cast.get("product"):
            want.append(("product", cast["product"], "product"))
        for kind, aid, key in want:
            n = on_canvas.get(aid)
            if not n:
                a = db.get(Asset, aid)
                x, y = canvas.next_pos(db, project.id, kind)
                n = canvas.create_node(db, project, kind, sub=assets.KINDS[kind], status="pass", data={"asset_id": aid}, x=x, y=y,
                                       title=f"{assets.KINDS[kind]} · {a.name if a else key}")
                on_canvas[aid] = n
            if n.id not in linked:
                canvas.connect(db, project.id, n.id, video_id)
                linked.add(n.id)
        canvas.bump(project)
        db.commit()
        emit(project.id, "canvas")


def _img(asset_id: str | None) -> str | None:
    if not asset_id:
        return None
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        return assets.media_data_url((a.images or [None])[0]) if a and a.images else None


def _turnaround(asset_id: str | None) -> str | None:
    if not asset_id:
        return None
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        url = (a.data or {}).get("turnaround") if a else None
    return assets.media_data_url(url) if url else None


def inputs(sh: list, spec: dict, cast: dict) -> dict:
    """一镜用到的输入（画面、拍法、演员 / 场景 / 商品及其图片）。改了任何一项，这一镜就需要重新生成。"""
    keys = [("role", k, cast["roles"].get(k)) for k in spec.get("roles") or []] + [("scene", spec.get("scene"), cast["scenes"].get(spec.get("scene")))]
    if spec.get("product"):
        keys.append(("product", "product", cast.get("product")))
    with SessionLocal() as db:
        refs = []
        for kind, key, aid in keys:
            a = db.get(Asset, aid) if aid else None
            refs.append([kind, key, aid, (a.images or [None])[0] if a else None])
    return {"visual": sh[1] if len(sh) > 1 else "", "spec": {k: spec.get(k) for k in ("size", "move", "roles", "scene", "product")}, "refs": refs}


def _shot(video_id: str, i: int, **fields) -> None:
    """实时写一镜的进度，画布上能看到每一镜走到哪一步。"""
    with SessionLocal() as db:
        n = db.get(Node, video_id)
        if not n:
            return
        tasks = list((n.data or {}).get("tasks") or [])
        while len(tasks) <= i:
            tasks.append({"shot": len(tasks) + 1})
        tasks[i] = {**tasks[i], **fields}
        n.data = {**(n.data or {}), "tasks": tasks}
        db.commit()
        emit(n.project_id, "canvas")


def _save_keyframe(video_id: str, i: int, raw: bytes, mime: str) -> str:
    ext = {"image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
    d = config.MEDIA_DIR / "keyframes"
    d.mkdir(parents=True, exist_ok=True)
    name = f"{video_id}-{i}-{hashlib.sha1(raw).hexdigest()[:8]}.{ext}"
    (d / name).write_bytes(raw)
    return f"/api/v1/media/keyframes/{name}"


async def keyframe(video_id: str, i: int, shot: list, spec: dict, cast: dict, frame_url: str | None, market: str, comment: str) -> str | None:
    """一镜的关键帧。参考图：分镜草图（构图）→ 演员定妆照（长相服装）→ 场景图 → 商品图。"""
    refs, notes = [], []
    sb = assets.media_data_url(frame_url) if frame_url else None
    if sb:
        refs.append(sb)
        notes.append(f"第 {len(refs)} 张参考图是这一镜的分镜草图：只参考构图、机位和人物位置，不要沿用它的铅笔线稿画风")
    for key in spec.get("roles", []):
        img = _img(cast["roles"].get(key))
        if img:
            refs.append(img)
            notes.append(f"第 {len(refs)} 张参考图是角色「{cast['names'].get(key, key)}」：长相、发型、服装必须和它一致")
        turn = _turnaround(cast["roles"].get(key))
        if turn:
            refs.append(turn)
            notes.append(f"第 {len(refs)} 张参考图是「{cast['names'].get(key, key)}」的三视图：不同角度下都必须是这同一个人")
    sc = _img(cast["scenes"].get(spec.get("scene")))
    if sc:
        refs.append(sc)
        notes.append(f"第 {len(refs)} 张参考图是场景「{cast['names'].get(spec.get('scene'), '')}」：环境与光线和它一致")
    if spec.get("product"):
        pimg = _img(cast.get("product"))
        if pimg:
            refs.append(pimg)
            notes.append(f"第 {len(refs)} 张参考图是商品实拍：手机外观、颜色、摄像头模组必须和它完全一致，不要改造型")
    text = (f"ONE photorealistic photograph of a single moment (never a collage, grid, split screen or before/after panels) — "
            f"a keyframe for a TikTok smartphone ad in {market}. Vertical 9:16. {VIDEO_STYLE}.\n"
            "如果画面描述里包含一段时间（如「从早到晚」「一边…一边…」），只挑其中最有代表性的一个瞬间来拍。\n"
            f"镜头：{SIZE_ZH.get(spec.get('size'), '中景')}，运镜：{spec.get('move', '固定')}。画面：{shot[1]}\n"
            + ("\n".join(notes) + "\n" if notes else "") + (f"修改意见：{comment}\n" if comment else "")
            + "画面中不要出现任何文字、字幕、品牌标志。\n"
            f"Rules: the setting is {market}; people, streets and shops look local to {market}, never East Asian. "
            "The whole frame must be one consistent photorealistic photograph — no pencil-sketch or drawn areas. "
            "No readable text anywhere: shop signs, labels and screens are blank or blurred; never render Chinese characters."
            + (" The phone must copy the product photo exactly: same color, same camera module shape, same number and layout of lenses."
               if spec.get("product") else ""))
    content: list[dict] | str = [{"type": "text", "text": text}, *({"type": "image_url", "image_url": {"url": r}} for r in refs)] if refs else text
    raw, mime = await llm.image(content, task="keyframe", aspect_ratio="9:16")
    return _save_keyframe(video_id, i, raw, mime)


async def clip(prompt: str, image: str | None) -> dict:
    provider = settings_store.video_provider()
    async with _slots:
        if provider == "fal":
            try:
                job = await (fal.submit_i2v(prompt, image, duration=5) if image else fal.submit(prompt, duration=5))
                return {"provider": "fal", "model": job["model"], "task_id": job["request_id"], **await fal.wait(job)}
            except Exception as e:  # noqa: BLE001
                return {"provider": "fal", "status": "failed", "error": str(e)[:300]}
        tid = await seedance.create_task(prompt)
        return {"provider": "byteplus" if provider == "byteplus" else "mock", "task_id": tid, **await seedance.wait_task(tid)}


def _set(video_id: str, **fields) -> None:
    with SessionLocal() as db:
        n = db.get(Node, video_id)
        if not n:
            return
        for k, v in fields.items():
            if k == "data":
                n.data = {**(n.data or {}), **v}
            else:
                setattr(n, k, v)
        db.commit()
        emit(n.project_id, "canvas")


async def run(video_id: str, comment: str = "", recast: bool = False, only: list[int] | None = None) -> None:
    try:
        await _run(video_id, comment, recast, only)
    except Exception as e:  # noqa: BLE001  后台任务出错不能让节点一直停在「生成中」
        log.exception("视频生成出错 %s", video_id)
        _set(video_id, status="failed", sub=f"生成出错：{str(e)[:60]}，可重新生成")


async def _run(video_id: str, comment: str, recast: bool, only: list[int] | None) -> None:
    with SessionLocal() as db:
        v = db.get(Node, video_id)
        if not v:
            return
        script_id = (v.data or {}).get("script_id") or next((n.id for n in canvas.upstream(db, v.id) if n.type == "script"), None)
        project = db.get(Project, v.project_id)
        market = project.market
    if not script_id:
        _set(video_id, status="failed", sub="没有找到来源剧本")
        return
    _set(video_id, status="run", sub="生成中…", data={"stage": "分镜"})
    if recast:
        _set(video_id, data={"cast_confirmed": False})
    await storyboard.run(script_id)  # 已经画过的镜头不会重画
    with SessionLocal() as db:
        s = db.get(Node, script_id)
        cast = None if recast else (s.data or {}).get("cast")
    if not cast:
        _set(video_id, data={"stage": "选角置景"})
        cast = await cast_script(script_id)
    place_asset_nodes(video_id, cast)

    with SessionLocal() as db:
        s = db.get(Node, script_id)
        shots = [list(x) for x in (s.data or {}).get("shots", [])]
        frames = (s.data or {}).get("frames") or []
        cast = (s.data or {}).get("cast") or cast
        prod = db.get(Asset, cast["product"]) if cast.get("product") else None
        need_product = prod is not None and not prod.images and settings_store.llm_enabled()  # 演示模式没有关键帧，不必等商品图
        v = db.get(Node, video_id)
        old = list((v.data or {}).get("tasks") or [])
        confirmed = (v.data or {}).get("cast_confirmed") or not settings_store.llm_enabled()  # 演示模式不停
    if not confirmed:
        # 选角确认：花钱画关键帧之前先停下，让人看演员（定妆照 + 三视图）、场景、每镜拍法和口播，可以换、可以改
        with SessionLocal() as db:
            v = db.get(Node, video_id)
            v.status, v.sub = "input", "选角完成，等你确认后开始画关键帧" + ("（还需要上传商品图）" if need_product else "")
            v.data = {**(v.data or {}), "shots": shots, "stage": "确认选角", "need_product": prod.id if need_product else None}
            if need_product:
                for n in canvas.nodes_of(db, v.project_id, "product"):
                    if (n.data or {}).get("asset_id") == prod.id:
                        n.status = "input"
            agent.say(db, v.project_id, f"{agent.ref(v)} 选好了 {len(cast['roles'])} 个演员、{len(cast['scenes'])} 个场景。"
                      "在视频节点里检查定妆照和三视图、每镜的拍法和口播，不合适可以从素材库换、AI 重画或上传；"
                      + (f"还需要上传「{prod.name}」的实拍图；" if need_product else "") + "确认后点「确认选角，开始生成」。")
            db.commit()
            emit(v.project_id, "canvas")
            emit(v.project_id, "chat")
        return
    if need_product:
        with SessionLocal() as db:
            v = db.get(Node, video_id)
            v.status, v.sub = "input", "等待上传商品实拍图"
            v.data = {**(v.data or {}), "shots": shots, "stage": "等待商品图", "waiting_asset": prod.id}
            for n in canvas.nodes_of(db, v.project_id, "product"):
                if (n.data or {}).get("asset_id") == prod.id:
                    n.status = "input"
            agent.say(db, v.project_id, f"{agent.ref(v)} 有商品镜头，需要「{prod.name}」的实拍图。在画布上的商品节点里点「上传商品图」，上传后自动继续生成。")
            db.commit()
            emit(v.project_id, "canvas")
            emit(v.project_id, "chat")
        return

    _set(video_id, data={"stage": "关键帧", "shots": shots, "need_product": None})
    specs = cast.get("specs") or []
    for i in range(len(shots)):
        if only is None or i in only:
            _shot(video_id, i, phase="排队中", status=None)
    use_kf = settings_store.llm_enabled()
    sem = asyncio.Semaphore(3)

    async def one(i: int, sh: list) -> dict:
        prev = old[i] if i < len(old) and only is not None and i not in only else None
        if prev:
            return prev
        spec = specs[i] if i < len(specs) else {"size": "MS", "move": "固定", "roles": [], "scene": None, "product": i == PRODUCT_SHOT}
        kf, err, kf_qc, fix, tries = None, "", None, "", 0
        frame = (frames[i] or {}).get("url") if i < len(frames) and frames[i] else None
        last = old[i] if i < len(old) else {}
        if use_kf and last.get("keyframe") and last.get("status") == "failed" and last.get("inputs") == inputs(sh, spec, cast):
            # 上次关键帧画好了、只是视频没生成出来，输入也没改：沿用关键帧，只重做视频，不重复花钱
            kf, kf_qc = last["keyframe"], last.get("qc")
        elif use_kf:
            async with sem:
                # 关键帧质检：不合格带着问题重画，最多重画 KF_RETRIES 次；仍不合格就用最后一张并标红
                for tries in range(1, KF_RETRIES + 2):
                    _shot(video_id, i, phase="画关键帧" if tries == 1 else f"重画关键帧（第 {tries} 次）")
                    try:
                        kf = await keyframe(video_id, i, sh, spec, cast, frame, market, "；".join(x for x in (comment, fix) if x))
                    except Exception as e:  # noqa: BLE001
                        err = str(e)[:200]
                        log.warning("关键帧失败 %s #%d: %s", video_id, i, e)
                        break
                    _shot(video_id, i, keyframe=kf, phase="关键帧质检")
                    kf_qc = await qc.check_keyframe(kf, sh, spec, cast)
                    if kf_qc["status"] != "fail":
                        break
                    fix = "上一张没通过质检，必须改正：" + "；".join(kf_qc["issues"])[:400]
        if spec.get("product") and not kf and not cast.get("product"):
            return {"shot": i + 1, "source": "official", "status": "completed", "url": "asset://official/product.mp4", "spec": spec,
                    "phase": "完成", "inputs": inputs(sh, spec, cast)}
        move = {"固定": "static camera", "推": "slow push-in", "拉": "slow pull-out", "摇": "pan", "跟拍": "tracking shot", "手持": "handheld"}.get(spec.get("move"), "static camera")
        prompt = f"{sh[1]}. Camera: {move}. {VIDEO_STYLE}" + (f". 修改意见：{comment}" if comment else "")
        # 成片质检：不合格重生成 CLIP_RETRIES 次；重做失败时保留上一条已生成的视频，不能把它扔掉
        best, retry_error, clip_qc = None, "", None
        for clip_tries in range(1, CLIP_RETRIES + 2):
            _shot(video_id, i, phase="生成视频" if clip_tries == 1 else "质检不合格，重新生成视频", qc=qc.merge(kf_qc, None, spec, {"keyframe": tries}))
            res = await clip(prompt, assets.jpeg_data_url(kf) if kf else None)
            if res.get("status") == "failed":
                if best:
                    retry_error = res.get("error") or "重新生成失败"
                    log.warning("镜头 %s #%d 质检后重做失败，保留上一条视频：%s", video_id, i, retry_error)
                break
            _shot(video_id, i, phase="视频质检", url=res.get("video_url"))
            clip_qc = await qc.check_clip(res.get("video_url") or "", sh, spec, cast)
            best = (res, clip_qc, clip_tries)
            if clip_qc["status"] != "fail":
                break
        if best:
            res, clip_qc, clip_tries = best
        return {"shot": i + 1, "source": "seedance", "prompt": prompt, "keyframe": kf, "keyframe_error": err, "spec": spec,
                "url": res.get("video_url"), **res, "phase": "失败" if res.get("status") == "failed" else "完成", "inputs": inputs(sh, spec, cast),
                **({"retry_error": f"质检不合格后自动重做失败，保留了第一条视频：{retry_error[:200]}"} if retry_error else {}),
                "qc": qc.merge(kf_qc, clip_qc, spec, {"keyframe": tries if use_kf else 0, "clip": clip_tries})}

    tasks = list(await asyncio.gather(*(one(i, sh) for i, sh in enumerate(shots))))
    with SessionLocal() as db:
        v = db.get(Node, video_id)
        if not v:
            return
        failed = [t for t in tasks if t.get("status") == "failed"]
        real = [t for t in tasks if t.get("provider") in ("fal", "byteplus")]
        urls = [t["url"] for t in tasks if (t.get("url") or "").startswith("http")]
        kfs = sum(1 for t in tasks if t.get("keyframe"))
        report = qc.video_summary(tasks)
        v.data = {**(v.data or {}), "shots": shots, "tasks": tasks, "stage": "完成", "waiting_asset": None, "names": cast.get("names", {}),
                  "video_url": urls[0] if urls else f"mock://composed/{video_id}.mp4", "shot_urls": urls,
                  "engine": real[0].get("model", real[0]["provider"]) if real else "mock",
                  "qc": report}
        if failed:
            v.status, v.sub = "failed", f"{len(failed)} 个镜头生成失败，可重试"
            agent.say(db, v.project_id, f"{agent.ref(v)} 有 {len(failed)} 个镜头的视频生成失败（关键帧已画好；点「重新生成」会沿用关键帧，只重做视频）：{failed[0].get('error', '')[:300]}")
            db.commit()
            emit(v.project_id, "canvas")
            emit(v.project_id, "chat")
            return
        v.sub = f"{cast.get('genre', '')} · {len(shots)} 镜 · 质检 {report['text']}"
        canvas.add_review(db, v, f"{'Seedance（' + v.data['engine'] + '）' if real else '模拟'}生成 {len(shots)} 镜；关键帧 {kfs} 张（参考分镜、演员、场景、商品）",
                          f"剧情：{cast.get('genre')} · 角色 {len(cast['roles'])} · 场景 {len(cast['scenes'])} · 商品{'已用实拍图' if cast.get('product') else '未用'}"
                          f" · 质检 {report['text']}" + (f"；请重点看：{'；'.join(report['issues'][:3])}" if report["issues"] else "")
                          + (f"；商品镜头（第 {'、'.join(map(str, report['manual']))} 镜）需要你人工确认外观" if report["manual"] else ""))
        db.commit()
        emit(v.project_id, "canvas")
        emit(v.project_id, "reviews")


def resume_waiting(asset_id: str) -> list[str]:
    """商品图上传后：把等这张图的视频继续跑下去。返回恢复的视频 id。"""
    with SessionLocal() as db:
        vids = [n.id for n in db.query(Node).filter(Node.type == "video", Node.status == "input")
                if (n.data or {}).get("waiting_asset") == asset_id and (n.data or {}).get("stage") == "等待商品图"]
        for n in db.query(Node).filter(Node.type == "product", Node.status == "input"):
            if (n.data or {}).get("asset_id") == asset_id:
                n.status = "pass"
                emit(n.project_id, "canvas")
        db.commit()
    return vids


def confirm_cast(video_id: str, db=None) -> None:
    """人确认选角后继续：画关键帧 → 质检 → 图生视频。db 传入时在调用方的会话里改（调用方负责提交）。"""
    own = db is None
    db = db or SessionLocal()
    try:
        v = db.get(Node, video_id)
        s = db.get(Node, (v.data or {}).get("script_id")) if v and (v.data or {}).get("script_id") else None
        cast = (s.data or {}).get("cast") if s else None
        prod = db.get(Asset, cast["product"]) if cast and cast.get("product") else None
        if prod and not prod.images and settings_store.llm_enabled():
            raise ValueError(f"还需要先上传「{prod.name}」的实拍图")
        v.data = {**(v.data or {}), "cast_confirmed": True}
        if own:
            db.commit()
        else:
            db.flush()
    finally:
        if own:
            db.close()


def set_cast(video_id: str, key: str, asset_id: str) -> dict:
    """这条视频的剧本里，把某个角色 / 场景 / 商品换成素材库里的另一个；画布上的素材节点跟着换。返回新的 cast。"""
    with SessionLocal() as db:
        v = db.get(Node, video_id)
        s = db.get(Node, (v.data or {}).get("script_id")) if v and (v.data or {}).get("script_id") else None
        cast = dict((s.data or {}).get("cast") or {}) if s else {}
        a = db.get(Asset, asset_id)
        if not cast or not a:
            raise KeyError(key)
        slot = "product" if key == "product" else "roles" if key in cast.get("roles", {}) else "scenes" if key in cast.get("scenes", {}) else None
        want = {"product": "product", "roles": "actor", "scenes": "scene"}.get(slot or "")
        if not slot or a.kind != want:
            raise ValueError("只能换成同类型的素材")
        old = cast["product"] if slot == "product" else cast[slot][key]
        if slot == "product":
            cast["product"] = a.id
        else:
            cast[slot] = {**cast[slot], key: a.id}
            cast["names"] = {**cast.get("names", {}), key: a.name}
        s.data = {**s.data, "cast": cast}
        still = set(cast["roles"].values()) | set(cast["scenes"].values()) | {cast.get("product")}
        if old not in still:  # 旧素材这条视频不再用：断开连线
            for e in db.query(Edge).filter(Edge.target == video_id):
                src = db.get(Node, e.source)
                if src and (src.data or {}).get("asset_id") == old:
                    db.delete(e)
        canvas.bump(db.get(Project, v.project_id))
        canvas.audit(db, v.project_id, "user", "set_cast", {"video_id": video_id, "key": key, "from": old, "to": a.id})
        db.commit()
    place_asset_nodes(video_id, cast)
    return cast
