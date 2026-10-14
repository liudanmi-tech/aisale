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
import re
import time

from app import agent, assets, canvas, config, product, qc, settings_store, storyboard
from app.adapters import fal, llm, seedance
from app.db import SessionLocal
from app.events import emit, spawn
from app.models import Asset, Edge, Node, Project, ReviewTask

log = logging.getLogger(__name__)
SIZES = ["WS", "MS", "CU", "ECU"]  # 全景 / 中景 / 特写 / 大特写
SIZE_ZH = {"WS": "全景", "MS": "中景", "CU": "特写", "ECU": "大特写"}
MOVES = ["固定", "推", "拉", "摇", "跟拍", "手持"]
GENRES = ["情景剧", "真人测评", "痛点对比", "开箱", "搞笑段子", "达人口播", "产品展示"]
PRODUCT_SHOT = 2
TEXTY = r"参数|标识|字样|数字|文字|界面|显示|mAh|价格|￥|\$|%|logo|Logo|LOGO"  # 画面描述里出现这些，说明在要求画文字
VIDEO_STYLE = "vertical 9:16 smartphone ad shot, photorealistic, natural light, no on-screen text, no watermark"
_slots = asyncio.Semaphore(2)

CAST_PROMPT = f"""你是短视频广告的制片和选角导演。根据剧本分镜拆出拍摄需要的角色、场景和每镜的拍法，只输出 JSON：
{{
  "genre": "从这些里选 1 个：{'、'.join(GENRES)}",
  "roles": [{{"key": "r1", "name": "角色名，如 女摊主", "description": "外观：性别、年龄、肤色、发型、服装、气质（用于生成定妆照，具体、可视化）", "reuse": "可复用的已有演员 id，没有写 null"}}],
  "scenes": [{{"key": "s1", "name": "场景名，如 雨夜的街头市场", "description": "环境、时间、天气、光线、道具", "reuse": "可复用的已有场景 id，没有写 null"}}],
  "specs": [{{"shot": 0, "size": "WS/MS/CU/ECU 之一", "move": "{'/'.join(MOVES)} 之一", "roles": ["r1"], "scene": "s1", "product": false,
             "product_tier": "商品镜头填 hero（纯商品特写，没有人）或 hand（人物拿着 / 使用这台手机）；不是商品镜头填 null",
             "line": "这一镜的话术（口播原文）", "overlay": "后期叠在画面上的卖点文字，用和口播相同的语言、越短越好（如 6000mAh Big Battery），没有写空字符串"}}]
}}
规则：specs 每镜一条、顺序与分镜一致；人物都是目标市场的当地人；第 {PRODUCT_SHOT + 1} 镜是产品特写，product 为 true；
同一个人物在不同镜头用同一个 key；已有素材合适就复用（reuse 填它的 id），不要重复造人。
场景是空的布景：description 只写环境、陈设和光线，不写人物，也不写手机或任何电子设备（人物用演员，手机用商品实拍，画关键帧时再放进去）；
商品特写用的展示台 / 桌面要写成「空的台面」。
画面里不出现任何文字：屏幕上显示的参数、价格、卖点数字一律写进 overlay（后期做成字幕贴片），不要让画面去画。"""


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
                    "product": bool(s.get("product", i == PRODUCT_SHOT)), "line": s.get("line") or (sh[2] if len(sh) > 2 else ""),
                    "product_tier": s.get("product_tier") if s.get("product_tier") in ("hero", "hand") else None,
                    "overlay": str(s.get("overlay") or "")[:60]})
    out = [phone_spec(x, sh[1] if len(sh) > 1 else "") for x, sh in zip(out, shots)]
    for x in out:  # 没写级别的商品镜头：没有人物就是纯商品特写，有人物就是手持
        if x["product"] and not x["product_tier"]:
            x["product_tier"] = "hand" if x["roles"] else "hero"
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


def _norm_sku(brand: str, sku: str) -> str:
    """「Infinix Hot 60」「hot60」→「hot 60」：去掉品牌前缀、统一大小写和空格。"""
    s = re.sub(rf"^\s*{re.escape(brand or '')}\s*", "", sku or "", flags=re.I) if brand else (sku or "")
    s = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _find_product(brand: str, sku: str) -> str:
    """素材库里同品牌同机型的商品（有图的优先）；素材库没有、传音机型库里有就自动导入官方图；都没有才建空的等上传。"""
    want = _norm_sku(brand, sku)
    with SessionLocal() as db:
        hits = []
        for a in db.query(Asset).filter(Asset.kind == "product"):
            d = a.data or {}
            same_brand = not d.get("brand") or (d.get("brand") or "").lower() == (brand or "").lower()
            if same_brand and want and want in (_norm_sku(brand, d.get("model_sku") or ""), _norm_sku(brand, a.name)):
                hits.append(a)
        if hits:
            return max(hits, key=lambda a: len(a.images or [])).id
    from app import catalog  # 避免循环导入
    m = next((m for m in catalog.load() if m["brand"].lower() == (brand or "").lower() and _norm_sku(brand, m["model_sku"]) == want), None)
    if m:
        made = catalog.start([m["id"]])
        if made:
            spawn(catalog.run_import(made[0]["asset_id"], m["id"]))
            return made[0]["asset_id"]
    sku = re.sub(rf"^\s*{re.escape(brand or '')}\s*", "", sku or "", flags=re.I) if brand else sku
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
    return {"visual": sh[1] if len(sh) > 1 else "", "spec": {k: spec.get(k) for k in ("size", "move", "roles", "scene", "product", "kf_source", "product_tier")}, "refs": refs}


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


def _first_image(asset_id: str | None) -> str | None:
    if not asset_id:
        return None
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        return (a.images or [None])[0] if a else None


def _turnaround_url(asset_id: str | None) -> str | None:
    if not asset_id:
        return None
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        return (a.data or {}).get("turnaround") if a else None


# 手机广告里，画面或口播提到这些，画面里基本就有手机
PHONE_WORDS = (r"手机|屏幕|拍|合影|照片|相片|录像|录视频|直播|视频通话|刷|扫码|收款|付款|转账|导航|打电话|来电|发消息|回消息|"
               r"WhatsApp|TikTok|phone|selfie|photo|picture|camera|video call|scroll|screen")


def shows_phone(spec: dict, visual: str = "") -> bool:
    """这一镜画面里有没有手机：商品镜头，或者画面描述 / 口播里有人在用手机。画面里出现的手机都必须是我们的商品。"""
    return bool(spec.get("product") or re.search(PHONE_WORDS, f"{visual or ''} {spec.get('line') or ''}", re.I))


def phone_spec(spec: dict, visual: str) -> dict:
    """画面里有人拿着 / 用着手机（自拍、刷手机、视频通话……）但没标成商品镜头：升级成手持商品镜头，
    走「先画占位手机、再换成真实商品」和多图参考，保证画面里的手机就是我们的商品。"""
    if spec.get("product") or not spec.get("roles") or not shows_phone(spec, visual):
        return spec
    return {**spec, "product": True, "product_tier": "hand", "auto_product": True}


def keyframe_refs(spec: dict, cast: dict, frame_url: str | None, visual: str = "") -> list[dict]:
    """这一镜关键帧用的参考图（本地地址 + 用途说明），顺序：分镜草图 → 演员定妆照 / 三视图 → 场景 → 商品。"""
    refs = []
    if frame_url:
        refs.append({"kind": "storyboard", "label": "分镜草图", "url": frame_url,
                     "note": "这一镜的分镜草图：只参考构图、机位和人物位置，不要沿用它的铅笔线稿画风；草图里的人物和手机都只是占位，"
                             "人物的长相、服装以演员定妆照为准，手机以商品实拍为准"})
    for key in spec.get("roles", []):
        name = cast["names"].get(key, key)
        aid = cast["roles"].get(key)
        if _first_image(aid):
            refs.append({"kind": "actor", "label": f"{name} 定妆照", "url": _first_image(aid), "note": f"角色「{name}」：长相、发型、服装必须和它一致"})
        if _turnaround_url(aid):
            refs.append({"kind": "turnaround", "label": f"{name} 三视图", "url": _turnaround_url(aid), "note": f"「{name}」的三视图：不同角度下都必须是这同一个人"})
    sid = cast["scenes"].get(spec.get("scene"))
    if _first_image(sid):
        name = cast["names"].get(spec.get("scene"), "")
        refs.append({"kind": "scene", "label": f"场景：{name}", "url": _first_image(sid),
                     "note": f"场景「{name}」：只参考环境、布置和光线；场景图里如果有人物、手或手机，一律去掉、不要画进来——"
                             "人物只用上面的演员，手机只用商品实拍"})
    if spec.get("product") or shows_phone(spec, visual):
        tier = spec.get("product_tier") or ("hero" if spec.get("product") and not spec.get("roles") else "hand")
        for v in product.good_views(cast.get("product"), tier, 2 if spec.get("product") else 1):
            label = f"商品{product.VIEWS.get(v.get('view'), '')}图"
            refs.append({"kind": "product", "label": label, "url": v["url"],
                         "note": f"商品实拍（{product.VIEWS.get(v.get('view'), '实拍')}）：手机外观、颜色、摄像头模组必须和它完全一致，不要改造型"})
    return refs


def keyframe_prompt(shot: list, spec: dict, market: str, placeholder: bool = False) -> str:
    """关键帧提示词的主体（不含参考图说明和修改意见），重画时可以在画布上直接改。placeholder：两步走第一步，手机先画占位。"""
    phone = shows_phone(spec, shot[1] if len(shot) > 1 else "") and not placeholder
    return (f"ONE photorealistic photograph of a single moment (never a collage, grid, split screen or before/after panels) — "
            f"a keyframe for a TikTok smartphone ad in {market}. Vertical 9:16. {VIDEO_STYLE}.\n"
            "如果画面描述里包含一段时间（如「从早到晚」「一边…一边…」），只挑其中最有代表性的一个瞬间来拍。\n"
            f"镜头：{SIZE_ZH.get(spec.get('size'), '中景')}，运镜：{spec.get('move', '固定')}。画面：{shot[1]}\n"
            + ("画面描述里提到的参数、数字、标识和文字都不要画出来（后期做成字幕贴片），只画手机和人物本身。\n"
               if re.search(TEXTY, shot[1] if len(shot) > 1 else "") else "")
            + "画面中不要出现任何文字、字幕、品牌标志。\n"
            + (f"画面里的人物只有本镜的 {len(spec.get('roles') or [])} 个角色（长相照演员参考图），不要多画别人的正脸；背景路人只能是虚化的远景。\n"
               if spec.get("roles") else "这一镜没有出场角色：不要画人物的正脸（商品镜头最多出现一只手）。\n")
            + ("画面里出现的手机都必须是商品实拍里的这台手机，不要画别的手机。\n" if phone else "")
            + f"Rules: the setting is {market}; people, streets and shops look local to {market}, never East Asian. "
            "The whole frame must be one consistent photorealistic photograph — no pencil-sketch or drawn areas. "
            "No readable text anywhere: shop signs, labels and screens are blank or blurred; never render Chinese characters."
            + (" The phone must copy the product photo exactly: same color, same camera module shape, same number and layout of lenses."
               " If the screen is visible it is off or shows a plain dark wallpaper — never draw UI, numbers or text on the screen."
               if phone else ""))


async def keyframe(video_id: str, i: int, shot: list, spec: dict, cast: dict, frame_url: str | None, market: str, comment: str,
                   prompt: str | None = None, drop: set[str] | None = None, placeholder: bool = False) -> tuple[str, dict]:
    """画一镜的关键帧。prompt 传入时代替自动生成的提示词主体；drop 里的参考图不用。返回 (关键帧地址, 本次用的提示词和参考图)。"""
    refs = [r for r in keyframe_refs(spec, cast, frame_url, shot[1] if len(shot) > 1 else "") if r["url"] not in (drop or set())]
    if placeholder:  # 两步走第一步：先画占位手机，商品图不参与，第二步再换成真实商品
        refs = [r for r in refs if r["kind"] != "product"]
    sent = [(r, assets.jpeg_data_url(r["url"], max_w=1280)) for r in refs]
    sent = [(r, d) for r, d in sent if d]
    core = (prompt or "").strip() or keyframe_prompt(shot, spec, market, placeholder)
    if placeholder:
        core += ("\nThe person holds a plain generic black smartphone with no logo and a dark screen (a placeholder that will be replaced "
                 "by the real product later). Show the phone clearly and large enough, not hidden by fingers.")
    elif spec.get("product") and product.spec_text(cast.get("product")):
        core += f"\n商品说明卡（照着画）：{product.spec_text(cast.get('product'))}"
    notes = "\n".join(f"第 {k + 1} 张参考图是{r['note']}" for k, (r, _) in enumerate(sent))
    text = core + ("\n" + notes if notes else "") + (f"\n修改意见：{comment}" if comment else "")
    content: list[dict] | str = [{"type": "text", "text": text}, *({"type": "image_url", "image_url": {"url": d}} for _, d in sent)] if sent else text
    raw, mime = await llm.image(content, task="keyframe", aspect_ratio="9:16")
    meta = {"prompt": core, "custom_prompt": bool((prompt or "").strip()), "refs": [r for r, _ in sent], "dropped": sorted(drop or []),
            "comment": comment, "model": settings_store.get_models()["keyframe"]}
    return _save_keyframe(video_id, i, raw, mime), meta


PLACE_PROMPT = ("Edit image 1. Replace the placeholder phone in the person's hand with the exact phone shown in the product photos "
                "(images 2{last}). {spec}Keep everything else in image 1 exactly unchanged: people, faces, hands, pose, clothes, background, "
                "lighting and framing. Match the perspective, scale, lighting and reflections of the scene; the side of the phone facing the camera "
                "must match how it is held. The screen, if visible, is off or a plain dark wallpaper. No text, no logos other than the phone's own, "
                "no extra phones. Vertical 9:16 photorealistic photo.")


async def place_product(video_id: str, i: int, base_url: str, spec: dict, cast: dict, comment: str = "") -> tuple[str, dict]:
    """两步走第二步：用图像编辑把占位手机换成真实商品（参考商品多视角图），画面其余部分不动。"""
    views = product.good_views(cast.get("product"), "hand", 2)
    imgs = [assets.jpeg_data_url(base_url, max_w=1280)] + [assets.jpeg_data_url(v.get("cutout") or v["url"], max_w=1024) for v in views]
    imgs = [x for x in imgs if x]
    spec_line = product.spec_text(cast.get("product"))
    text = PLACE_PROMPT.format(last=f"–{len(imgs)}" if len(imgs) > 2 else "", spec=f"The phone: {spec_line}. " if spec_line else "")
    text += f"\n修改意见：{comment}" if comment else ""
    raw, mime = await llm.image([{"type": "text", "text": text}, *({"type": "image_url", "image_url": {"url": d}} for d in imgs)],
                                task="keyframe", aspect_ratio="9:16")
    return _save_keyframe(video_id, i, raw, mime), {"place_prompt": text, "place_refs": [{"kind": "product", "label": f"商品{product.VIEWS.get(v.get('view'), '')}图",
                                                                                         "url": v.get("cutout") or v["url"], "note": "换入画面的真实商品"} for v in views]}


async def clip(prompt: str, image: str | None, refs: list[str] | None = None) -> dict:
    provider = settings_store.video_provider()
    async with _slots:
        if provider == "fal":
            res: dict
            try:
                if refs:  # 商品镜头：全能参考，关键帧 + 商品图一起给，生成全程看着商品
                    job = await fal.submit_ref(prompt, refs, duration=5)
                else:
                    job = await (fal.submit_i2v(prompt, image, duration=5) if image else fal.submit(prompt, duration=5))
                res = {"provider": "fal", "model": job["model"], "task_id": job["request_id"], **await fal.wait(job)}
            except fal.InputRejected as e:
                res = {"provider": "fal", "status": "failed", "error": str(e)[:400], "rejected": True}
            except Exception as e:  # noqa: BLE001
                return {"provider": "fal", "status": "failed", "error": str(e)[:400]}
            if res.get("status") == "failed" and res.get("rejected") and image:
                # Seedance 2.x 拒收（常见：画面里有真人脸）：用关键帧走 Seedance 1 Pro 图生视频再做一次。
                # 关键帧里已经换好了真实商品，外观靠关键帧保持
                try:
                    plain = re.sub(r"@Image\d+(\s+and\s+@Image\d+)*", "the phone in the first frame", prompt.replace("@Image1", "the first frame"))
                    job = await fal.submit_i2v(plain, image, duration=5, model=fal.FALLBACK_I2V)
                    res2 = {"provider": "fal", "model": job["model"], "task_id": job["request_id"], **await fal.wait(job)}
                except Exception as e:  # noqa: BLE001
                    res2 = {"status": "failed", "error": str(e)[:300]}
                if res2.get("status") != "failed":
                    return {**res2, "fallback": f"Seedance 2.5 不接受这一镜的输入（{res['error'][:120]}），自动改用 Seedance 1 Pro 图生视频"}
                res["error"] += f"；改用 Seedance 1 Pro 也失败：{res2.get('error', '')[:200]}"
            return res
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


_active: dict[str, set] = {}  # 正在跑的后台任务（整条生成、单镜重画 / 重做），「停止生成」时取消


class _track:
    """登记当前任务，停止时能取消它。"""
    def __init__(self, video_id: str):
        self.vid = video_id

    def __enter__(self):
        t = asyncio.current_task()
        if t:
            _active.setdefault(self.vid, set()).add(t)
        return self

    def __exit__(self, *exc):
        t = asyncio.current_task()
        _active.get(self.vid, set()).discard(t)
        return False


def stop(video_id: str) -> int:
    """停止这条视频正在进行的生成：取消后台任务；已经画好的关键帧和视频保留，正在做的镜头标为「已停止」。"""
    tasks = list(_active.pop(video_id, set()))
    for t in tasks:
        t.cancel()
    _mark_stopped(video_id)
    return len(tasks)


def _mark_stopped(video_id: str) -> None:
    with SessionLocal() as db:
        v = db.get(Node, video_id)
        if not v:
            return
        tasks = []
        for t in (v.data or {}).get("tasks") or []:
            if t and t.get("phase") not in IDLE and t.get("phase") != "已停止":
                t = {**t, "phase": "已停止", "status": "failed", "error": "你手动停止了生成"}
            tasks.append(t)
        v.data = {**(v.data or {}), "tasks": tasks}
        if v.status == "run":
            v.status, v.sub = "failed", "已停止：可以改选角 / 提示词后重新生成，已做好的镜头保留"
        db.commit()
        emit(v.project_id, "canvas")


async def run(video_id: str, comment: str = "", recast: bool = False, only: list[int] | None = None) -> None:
    try:
        with _track(video_id):
            await _run(video_id, comment, recast, only)
    except asyncio.CancelledError:
        _mark_stopped(video_id)
        raise
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
    if cast.get("product"):
        up = [phone_spec(sp, shots[k][1] if k < len(shots) and len(shots[k]) > 1 else "") for k, sp in enumerate(specs)]
        if up != specs:  # 旧剧本：有人用手机的镜头补成手持商品镜头，存回剧本（画布上能看到「商品 · 手持」）
            specs = up
            cast = {**cast, "specs": specs}
            with SessionLocal() as db:
                s = db.get(Node, script_id)
                s.data = {**(s.data or {}), "cast": cast}
                db.commit()
    for i in range(len(shots)):
        if only is None or i in only:
            _shot(video_id, i, phase="排队中", status=None)
    use_kf = settings_store.llm_enabled()
    retries = settings_store.get_retries()  # 设置页可调；视频默认不自动重做
    kf_retries, clip_retries = retries["keyframe"], retries["clip"]
    sem = asyncio.Semaphore(3)

    async def one(i: int, sh: list) -> dict:
        prev = old[i] if i < len(old) and only is not None and i not in only else None
        if prev:
            return prev
        spec = _spec(specs, i)
        frame = (frames[i] or {}).get("url") if i < len(frames) and frames[i] else None
        last = old[i] if i < len(old) else {}
        kf, kf_qc, tries, err = None, None, 0, ""
        if use_kf and last.get("keyframe") and last.get("status") == "failed" and last.get("inputs") == inputs(sh, spec, cast):
            # 上次关键帧画好了、只是视频没生成出来，输入也没改：沿用关键帧，只重做视频，不重复花钱
            kf, kf_qc = last["keyframe"], last.get("qc")
        elif use_kf:
            async with sem:
                kf, kf_qc, tries, err = await make_keyframe(video_id, i, sh, spec, cast, frame, market, comment, kf_retries)
        if spec.get("product") and not kf and not cast.get("product"):
            return {"shot": i + 1, "source": "official", "status": "completed", "url": "asset://official/product.mp4", "spec": spec,
                    "phase": "完成", "inputs": inputs(sh, spec, cast)}
        return await make_clip(video_id, i, sh, spec, cast, kf, kf_qc, tries if use_kf else 0, err, comment, clip_retries)

    tasks = list(await asyncio.gather(*(one(i, sh) for i, sh in enumerate(shots))))
    _finalize(video_id, cast, shots, tasks)


def _spec(specs: list, i: int) -> dict:
    return specs[i] if i < len(specs) else {"size": "MS", "move": "固定", "roles": [], "scene": None, "product": i == PRODUCT_SHOT}


def kf_source(spec: dict, cast: dict) -> str:
    """商品镜头关键帧怎么做：
    photo     纯商品特写：直接用实拍（抠图）合成，外观 100% 一致；
    placement 人物手持：先画占位手机，再用图像编辑换成真实商品；
    ai        AI 直接画（参考商品图），外观可能走样。
    默认按级别：hero → photo，hand → placement。没有商品图时只能 ai。"""
    if not spec.get("product"):
        return "ai"
    want = spec.get("kf_source") or "auto"
    want = {"product": "photo"}.get(want, want)  # 旧值兼容
    if want == "ai" or not product.good_views(cast.get("product"), "hero", 1):
        return "ai"
    if want in ("photo", "placement"):
        return want
    return "placement" if spec.get("product_tier") == "hand" or (spec.get("roles") and spec.get("product_tier") != "hero") else "photo"


def product_keyframe(video_id: str, i: int, cast: dict) -> str:
    """用商品实拍合成 9:16 关键帧。有抠图：放在柔和的棚拍渐变背景上，加一点投影；没有抠图：背景取实拍图边缘的底色。外观和实拍完全一致。"""
    import cv2
    import numpy as np
    v = (product.good_views(cast.get("product"), "hero", 1) or [{}])[0]
    W, H = 1080, 1920
    cut = v.get("cutout")
    if cut:
        rgba = cv2.imread(str(config.MEDIA_DIR / cut.split("/api/v1/media/", 1)[1]), cv2.IMREAD_UNCHANGED)
        if rgba is not None and rgba.shape[2] == 4:
            ys, xs = np.where(rgba[:, :, 3] > 10)
            rgba = rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            h, w = rgba.shape[:2]
            scale = min(W * 0.78 / w, H * 0.66 / h)
            rgba = cv2.resize(rgba, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
            h, w = rgba.shape[:2]
            yy = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
            bg = (np.array([236, 236, 238], np.float32) * (1 - yy) + np.array([196, 197, 202], np.float32) * yy) * np.ones((H, W, 3), np.float32)
            x, y = (W - w) // 2, (H - h) // 2 - 40
            shadow = np.zeros((H, W), np.float32)
            cv2.ellipse(shadow, (W // 2, y + h + 18), (int(w * 0.42), 26), 0, 0, 360, 1.0, -1)
            shadow = cv2.GaussianBlur(shadow, (0, 0), 18) * 0.35
            bg *= (1 - shadow)[:, :, None]
            alpha = rgba[:, :, 3:4].astype(np.float32) / 255
            roi = bg[y:y + h, x:x + w]
            bg[y:y + h, x:x + w] = roi * (1 - alpha) + rgba[:, :, :3].astype(np.float32) * alpha
            ok, buf = cv2.imencode(".jpg", bg.clip(0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 92])
            return _save_keyframe(video_id, i, buf.tobytes(), "image/jpeg")
    url = v.get("url") or _first_image(cast.get("product"))
    img = cv2.imread(str(config.MEDIA_DIR / url.split("/api/v1/media/", 1)[1]), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("商品实拍图读不出来")
    h, w = img.shape[:2]
    edge = np.concatenate([img[:4].reshape(-1, 3), img[-4:].reshape(-1, 3), img[:, :4].reshape(-1, 3), img[:, -4:].reshape(-1, 3)])
    canvas_ = np.empty((H, W, 3), np.uint8)
    canvas_[:] = np.median(edge, axis=0).astype(np.uint8)
    scale = min(W * 0.9 / w, H * 0.72 / h)
    nw, nh = int(w * scale), int(h * scale)
    small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    x, y = (W - nw) // 2, (H - nh) // 2
    canvas_[y:y + nh, x:x + nw] = small
    ok, buf = cv2.imencode(".jpg", canvas_, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return _save_keyframe(video_id, i, buf.tobytes(), "image/jpeg")


async def make_keyframe(video_id: str, i: int, sh: list, spec: dict, cast: dict, frame: str | None, market: str,
                        comment: str, retries: int, prompt: str | None = None, drop: set[str] | None = None) -> tuple[str | None, dict | None, int, str]:
    """画一镜的关键帧并质检；不合格带着问题重画，最多重画 retries 次。返回 (关键帧, 质检, 画了几次, 错误)。"""
    mode = kf_source(spec, cast)
    if mode == "photo":
        _shot(video_id, i, phase="用商品实拍图合成关键帧")
        try:
            kf = await asyncio.to_thread(product_keyframe, video_id, i, cast)
        except Exception as e:  # noqa: BLE001  合成失败就退回 AI 画
            log.warning("实拍图合成关键帧失败 %s #%d：%s", video_id, i, e)
        else:
            v = (product.good_views(cast.get("product"), "hero", 1) or [{}])[0]
            _shot(video_id, i, keyframe=kf, kf_meta={"prompt": "", "refs": [{"kind": "product", "label": "商品实拍图", "url": v.get("cutout") or v.get("url") or "",
                                                               "note": "直接用实拍图合成关键帧（没有调用生图模型）"}], "composite": True, "mode": "photo"})
            res = qc.summarize({"product": {"status": "pass", "reason": "关键帧直接用商品实拍图，外观与实拍一致"}}, spec)
            return kf, {**res, "manual_confirm": False, "source": "product"}, 1, ""
    kf, kf_qc, err, fix, tries = None, None, "", "", 0
    for tries in range(1, retries + 2):
        _shot(video_id, i, phase=("画关键帧" if tries == 1 else f"重画关键帧（第 {tries} 次）") + ("：先画占位手机" if mode == "placement" else ""))
        try:
            note = "；".join(x for x in (comment, fix) if x)
            kf, meta = await keyframe(video_id, i, sh, spec, cast, frame, market, note, prompt, drop, placeholder=mode == "placement")
            if mode == "placement":
                _shot(video_id, i, keyframe=kf, phase="换入真实商品")
                base = kf
                kf, extra = await place_product(video_id, i, base, spec, cast, note)
                meta = {**meta, **extra, "placeholder": base, "mode": "placement"}
            else:
                meta = {**meta, "mode": "ai"}
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
            log.warning("关键帧失败 %s #%d: %s", video_id, i, e)
            break
        _shot(video_id, i, keyframe=kf, kf_meta=meta, phase="关键帧质检")
        kf_qc = await qc.check_keyframe(kf, sh, spec, cast)
        if kf_qc["status"] != "fail":
            break
        fix = "上一张没通过质检，必须改正：" + "；".join(kf_qc["issues"])[:400]
    return kf, kf_qc, tries, err


async def make_clip(video_id: str, i: int, sh: list, spec: dict, cast: dict, kf: str | None, kf_qc: dict | None, tries: int,
                    err: str, comment: str, retries: int) -> dict:
    """关键帧 → 视频并质检；不合格重做 retries 次，重做失败时保留上一条已生成的视频。返回这一镜的结果。"""
    move = {"固定": "static camera", "推": "slow push-in", "拉": "slow pull-out", "摇": "pan", "跟拍": "tracking shot", "手持": "handheld"}.get(spec.get("move"), "static camera")
    prompt = f"{sh[1]}. Camera: {move}. {VIDEO_STYLE}" + (f". 修改意见：{comment}" if comment else "")
    refs, ref_labels = None, []
    if spec.get("product") and kf and cast.get("product") and settings_store.video_provider() == "fal":
        # 商品镜头：全能参考。@Image1 = 关键帧（开场画面），@Image2/3 = 商品多视角实拍，生成全程看着商品图
        views = product.good_views(cast.get("product"), spec.get("product_tier") or "hero", 2)
        refs = [assets.jpeg_data_url(kf)] + [assets.jpeg_data_url(v["url"], max_w=1280) for v in views]
        refs = [x for x in refs if x]
        ref_labels = ["关键帧"] + [f"商品{product.VIEWS.get(v.get('view'), '')}图" for v in views]
        phone = " and ".join(f"@Image{k + 2}" for k in range(len(refs) - 1))
        spec_line = product.spec_text(cast.get("product"))
        hero = (kf_qc or {}).get("source") == "product" or spec.get("product_tier") == "hero"
        prompt = (f"@Image1 is the opening frame: start exactly from it and keep its composition, people and setting. "
                  f"The phone is the one in {phone}{(' (' + spec_line + ')') if spec_line else ''}: keep its shape, colour, camera module and logo "
                  "exactly unchanged in every frame — no morphing, no melting logo, no extra phones, no on-screen text. "
                  + (f"Product hero shot: slow, subtle {move}; soft moving studio light; no hands. " if hero else f"{sh[1]}. Camera: gentle {move}. ")
                  + VIDEO_STYLE)
    best, retry_error, clip_qc, res, clip_tries = None, "", None, {}, 0
    for clip_tries in range(1, retries + 2):
        _shot(video_id, i, phase="生成视频" if clip_tries == 1 else "质检不合格，重新生成视频", qc=qc.merge(kf_qc, None, spec, {"keyframe": tries}))
        res = await clip(prompt, assets.jpeg_data_url(kf) if kf else None, refs)
        if res.get("status") == "failed":
            if best:
                retry_error = res.get("error") or "重新生成失败"
                log.warning("镜头 %s #%d 质检后重做失败，保留上一条视频：%s", video_id, i, retry_error)
            break
        _shot(video_id, i, phase="视频质检", url=res.get("video_url"))
        try:
            clip_qc = await asyncio.wait_for(qc.check_clip(res.get("video_url") or "", sh, spec, cast), QC_TIMEOUT)
        except Exception as e:  # noqa: BLE001  质检超时或出错：保留视频，标「未执行」交给人看
            log.warning("视频质检没做完 %s #%d：%s", video_id, i, e)
            clip_qc = qc.summarize({"tech": {"status": "skip", "reason": f"未执行：视频质检{'超时' if isinstance(e, TimeoutError) else '出错'}，请自己看一下"}}, spec)
        best = (res, clip_qc, clip_tries)
        if clip_qc["status"] != "fail":
            break
    if best:
        res, clip_qc, clip_tries = best
    return {"shot": i + 1, "source": "seedance", "prompt": prompt, "keyframe": kf, "keyframe_error": err, "spec": spec,
            "url": res.get("video_url"), "video_url": res.get("video_url"), "error": None, "retry_error": None, **res,
            "phase": "失败" if res.get("status") == "failed" else "完成", "inputs": inputs(sh, spec, cast),
            "kf_from": "product" if (kf_qc or {}).get("source") == "product" else "ai",
            "video_mode": "reference" if refs else "image", "video_refs": ref_labels,
            **({"retry_error": f"质检不合格后自动重做失败，保留了第一条视频：{retry_error[:200]}"} if retry_error else {}),
            "qc": qc.merge(kf_qc, clip_qc, spec, {"keyframe": tries, "clip": clip_tries})}


IDLE = ("完成", "失败", "已停止", "关键帧待确认", None)
QC_TIMEOUT = 300  # 视频质检最长 5 分钟（下载视频 + 抽帧 + 模型看图）


def _finalize(video_id: str, cast: dict, shots: list, tasks: list) -> None:
    """所有镜头做完后：有失败 → 标失败；有关键帧待确认 → 等人；否则提交审核。"""
    with SessionLocal() as db:
        v = db.get(Node, video_id)
        if not v:
            return
        # 整条生成期间，用户可能单独重做了已经失败 / 做完的镜头：那几镜以数据库里的为准
        cur = list((v.data or {}).get("tasks") or [])
        tasks = [cur[k] if k < len(cur) and (cur[k] or {}).get("redo_seq", 0) > ((t or {}).get("redo_seq") or 0) else t for k, t in enumerate(tasks)]
        if any((t or {}).get("phase") not in IDLE for t in tasks):
            # 还有镜头在单独重做：先把其他镜头的结果写进去，等它做完由 _settle 收尾
            v.data = {**(v.data or {}), "shots": shots, "tasks": tasks, "stage": "单镜修改"}
            db.commit()
            emit(v.project_id, "canvas")
            return
        failed = [t for t in tasks if t.get("status") == "failed"]
        pending = [k + 1 for k, t in enumerate(tasks) if t.get("phase") == "关键帧待确认"]
        real = [t for t in tasks if t.get("provider") in ("fal", "byteplus")]
        urls = [t["url"] for t in tasks if (t.get("url") or "").startswith("http")]
        kfs = sum(1 for t in tasks if t.get("keyframe"))
        report = qc.video_summary(tasks)
        v.data = {**(v.data or {}), "shots": shots, "tasks": tasks, "stage": "关键帧待确认" if pending else "完成", "waiting_asset": None,
                  "names": cast.get("names", {}), "video_url": urls[0] if urls else f"mock://composed/{video_id}.mp4", "shot_urls": urls,
                  "engine": real[0].get("model", real[0]["provider"]) if real else (v.data or {}).get("engine", "mock"), "qc": report}
        if pending:
            v.status, v.sub = "input", f"第 {'、'.join(map(str, pending))} 镜关键帧已更新，确认后生成视频"
            db.commit()
            emit(v.project_id, "canvas")
            return
        if failed:
            v.status, v.sub = "failed", f"{len(failed)} 个镜头生成失败，可重试"
            agent.say(db, v.project_id, f"{agent.ref(v)} 有 {len(failed)} 个镜头的视频生成失败（关键帧已画好；点「重做视频」会沿用关键帧，只重做视频）：{failed[0].get('error', '')[:300]}")
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


def _context(video_id: str) -> dict:
    with SessionLocal() as db:
        v = db.get(Node, video_id)
        s = db.get(Node, (v.data or {}).get("script_id"))
        project = db.get(Project, v.project_id)
        return {"shots": [list(x) for x in (s.data or {}).get("shots", [])], "frames": (s.data or {}).get("frames") or [],
                "cast": (s.data or {}).get("cast") or {}, "market": project.market, "script_id": s.id}


def _upgrade_spec(video_id: str, cast: dict, i: int, sh: list) -> dict:
    """单镜重做时：画面里有人用手机的镜头补成手持商品镜头，并存回剧本（画布上显示「商品 · 手持」，质检也按商品镜头查）。"""
    spec = _spec(cast.get("specs") or [], i)
    if not cast.get("product"):
        return spec
    up = phone_spec(spec, sh[1] if len(sh) > 1 else "")
    if up is not spec and i < len(cast.get("specs") or []):
        with SessionLocal() as db:
            v = db.get(Node, video_id)
            s = db.get(Node, (v.data or {}).get("script_id")) if v else None
            if s and (s.data or {}).get("cast"):
                c = dict(s.data["cast"])
                c["specs"] = [up if k == i else x for k, x in enumerate(c.get("specs") or [])]
                s.data = {**s.data, "cast": c}
                db.commit()
                emit(s.project_id, "canvas")
    return up


def _begin_shot(video_id: str, i: int, what: str) -> None:
    """单镜修改开始：视频节点进入「生成中」，旧审核单作废（改完重新提交）。"""
    with SessionLocal() as db:
        v = db.get(Node, video_id)
        for r in db.query(ReviewTask).filter(ReviewTask.node_id == video_id, ReviewTask.status == "wait"):
            r.status, r.comment = "cancel", f"第 {i + 1} 镜{what}"
        v.status, v.sub = "run", f"第 {i + 1} 镜{what}中…"
        tasks = list((v.data or {}).get("tasks") or [])
        while len(tasks) <= i:
            tasks.append({"shot": len(tasks) + 1})
        tasks[i] = {**tasks[i], "redo_seq": time.time()}  # 整条生成收尾时认出这一镜被单独改过，不覆盖
        v.data = {**(v.data or {}), "stage": "单镜修改", "tasks": tasks}
        db.commit()
        emit(v.project_id, "canvas")
        emit(v.project_id, "reviews")


def _settle(video_id: str) -> None:
    """单镜修改结束：其他镜头都空闲了才收尾。"""
    with SessionLocal() as db:
        v = db.get(Node, video_id)
        tasks = list((v.data or {}).get("tasks") or [])
    if any(t.get("phase") not in IDLE for t in tasks):
        return
    ctx = _context(video_id)
    _finalize(video_id, ctx["cast"], ctx["shots"], tasks)


async def _redo_keyframe(video_id: str, i: int, comment: str = "", prompt: str | None = None, drop: list[str] | None = None) -> None:
    """只重画第 i 镜的关键帧（可带修改意见），画完停下等人看；满意了再 redo_clip 生成视频。"""
    _begin_shot(video_id, i, "重画关键帧")
    try:
        ctx = _context(video_id)
        sh, cast = ctx["shots"][i], ctx["cast"]
        spec = _upgrade_spec(video_id, cast, i, sh)
        frame = (ctx["frames"][i] or {}).get("url") if i < len(ctx["frames"]) and ctx["frames"][i] else None
        kf, kf_qc, tries, err = await make_keyframe(video_id, i, sh, spec, cast, frame, ctx["market"], comment,
                                                    settings_store.get_retries()["keyframe"], prompt, set(drop or []))
        if kf:
            kq = qc.merge(kf_qc, None, spec, {"keyframe": tries})
            if (kf_qc or {}).get("source") == "product":
                kq["manual_confirm"] = False  # 实拍图合成的关键帧外观就是实拍；视频生成后再由视频质检和人确认
            _shot(video_id, i, keyframe=kf, keyframe_error="", qc=kq, phase="关键帧待确认",
                  status="keyframe_ready", url=None, video_url=None, error=None, retry_error=None, spec=spec, inputs=inputs(sh, spec, cast),
                  kf_from="product" if (kf_qc or {}).get("source") == "product" else "ai")
        else:
            _shot(video_id, i, phase="失败", status="failed", error=f"关键帧没画出来：{err}")
    except Exception as e:  # noqa: BLE001
        log.exception("重画关键帧出错 %s #%d", video_id, i)
        _shot(video_id, i, phase="失败", status="failed", error=f"重画关键帧出错：{str(e)[:200]}")
    _settle(video_id)


async def _redo_clip(video_id: str, i: int) -> None:
    """用第 i 镜现在的关键帧生成视频（关键帧确认后、或只有视频失败时）。"""
    _begin_shot(video_id, i, "生成视频")
    try:
        ctx = _context(video_id)
        with SessionLocal() as db:
            t = ((db.get(Node, video_id).data or {}).get("tasks") or [{}] * (i + 1))[i]
        sh, cast = ctx["shots"][i], ctx["cast"]
        spec = _upgrade_spec(video_id, cast, i, sh)
        kf_qc = t.get("qc")
        if t.get("kf_from") == "product":  # 实拍图合成的关键帧，视频提示词要求商品保持不变
            kf_qc = {**(kf_qc or {}), "source": "product"}
        res = await make_clip(video_id, i, sh, spec, cast, t.get("keyframe"), kf_qc, ((t.get("qc") or {}).get("attempts") or {}).get("keyframe", 1),
                              "", "", settings_store.get_retries()["clip"])
        _shot(video_id, i, **res)
    except Exception as e:  # noqa: BLE001
        log.exception("生成视频出错 %s #%d", video_id, i)
        _shot(video_id, i, phase="失败", status="failed", error=f"生成视频出错：{str(e)[:200]}")
    _settle(video_id)


async def redo_keyframe(video_id: str, i: int, comment: str = "", prompt: str | None = None, drop: list[str] | None = None) -> None:
    try:
        with _track(video_id):
            await _redo_keyframe(video_id, i, comment, prompt, drop)
    except asyncio.CancelledError:
        _mark_stopped(video_id)
        _settle(video_id)
        raise


async def redo_clip(video_id: str, i: int) -> None:
    try:
        with _track(video_id):
            await _redo_clip(video_id, i)
    except asyncio.CancelledError:
        _mark_stopped(video_id)
        _settle(video_id)
        raise


def has_images(asset_id: str) -> bool:
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        return bool(a and a.images)


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
