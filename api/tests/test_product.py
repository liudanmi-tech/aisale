"""商品主体：多视角检查、抠图、说明卡；商品镜头的关键帧来源（实拍合成 / 占位换真机 / AI）；商品相似度判定。"""
import asyncio
import base64
import json
import os
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

import cv2  # noqa: E402
import httpx  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config, product, production, qc  # noqa: E402
from app.adapters import llm  # noqa: E402
from app import settings_store  # noqa: E402
from app.main import app  # noqa: E402


def phone_png(collage: bool = False) -> str:
    """白底上的一台灰色手机（两台就是拼图）。"""
    img = np.full((1400, 1100, 3), 255, np.uint8)
    for x0 in ((150, 600) if collage else (330,)):
        cv2.rectangle(img, (x0, 200), (x0 + 400, 1200), (110, 110, 115), -1)
        cv2.circle(img, (x0 + 120, 330), 70, (20, 20, 20), -1)
        cv2.circle(img, (x0 + 100, 310), 18, (200, 200, 200), -1)
    return "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", img)[1].tobytes()).decode()


calls: list[dict] = []


def llm_handler(req: httpx.Request) -> httpx.Response:
    body = json.loads(req.content)
    calls.append(body)
    if body.get("modalities"):  # 生图：返回一张白底小图
        png = base64.b64encode(cv2.imencode(".png", np.full((64, 36, 3), 200, np.uint8))[1].tobytes()).decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "images": [{"image_url": {"url": f"data:image/png;base64,{png}"}}]}}]})
    text = body["messages"][0]["content"][0]["text"] if isinstance(body["messages"][0]["content"], list) else body["messages"][0]["content"]
    if "审核一张手机商品图" in text:
        n_imgs = len(body["messages"][0]["content"]) - 1
        assert n_imgs == 1
        # 第一张上传的是拼图，第二张是干净的背面
        collage = sum(1 for c in calls if "审核一张手机商品图" in str(c)) == 1
        out = {"view": "front", "phones": 2 if collage else 1, "is_collage": collage, "background": "plain", "sharp": True, "occluded": False}
    elif "商品说明卡" in text and "只写看得见的外观事实" in text:
        out = {"color": "雾面钛灰", "camera_module": "左上角竖排三摄", "logo": "背面左下 TECNO", "screen": "直屏挖孔", "body": "窄长", "notes": "无"}
    else:
        out = {}
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}]})


def wait_until(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_product_subject(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    llm.transport = httpx.MockTransport(llm_handler)
    try:
        with TestClient(app) as c:
            settings_store.set_retries({"kf_candidates": 1, "kf_gate": 0})  # 老流程：每镜 1 张关键帧，画完直接生成视频
            c.put("/api/v1/settings/secrets/openrouter", json={"value": "sk-or-test-5678wxyz"})
            a = c.post("/api/v1/library", json={"kind": "product", "name": "TECNO Camon 40", "image": phone_png(collage=True),
                                               "data": {"brand": "TECNO", "model_sku": "Camon 40"}}).json()
            get = lambda: next(x for x in c.get("/api/v1/library", params={"kind": "product"}).json() if x["id"] == a["id"])  # noqa: E731
            wait_until(lambda: all(v.get("status") not in (None, "checking") for v in get()["data"].get("views", {}).values()) and get()["data"].get("views"))
            v0 = get()["data"]["views"][get()["images"][0]]
            assert v0["status"] == "bad" and "拼图" in v0["issues"][0] and not v0.get("cutout")  # 拼图不当参考，也不抠图
            assert product.good_views(a["id"]) == []  # 只有拼图时没有能用的图
            assert get()["product"]["missing"] == ["背面", "正面", "侧面"] and get()["product"]["bad"] == 1

            # 再传一张干净的背面（手动标视角）：检查通过、自动抠图、提取说明卡
            c.post(f"/api/v1/library/{a['id']}/upload", json={"image": phone_png(), "view": "back"})
            wait_until(lambda: get()["data"].get("spec_card"))
            back = get()["images"][0]
            vb = get()["data"]["views"][back]
            assert vb["view"] == "back" and vb["status"] == "ok" and vb["cutout"].endswith(".png") and vb["cutout_by"] == "本地"
            cut = cv2.imread(str(tmp_path / vb["cutout"].split("/api/v1/media/", 1)[1]), cv2.IMREAD_UNCHANGED)
            assert cut.shape[2] == 4 and cut[50, 50, 3] == 0 and cut[700, 500, 3] == 255  # 背景透明、机身不透明（含高光的洞也填上了）
            assert [v["url"] for v in product.good_views(a["id"])] == [back]
            assert product.spec_text(a["id"]).startswith("颜色：雾面钛灰；摄像头模组：左上角竖排三摄")
            assert get()["product"]["missing"] == ["正面", "侧面"]

            # 改视角、删掉拼图、手动改说明卡（之后不再被自动覆盖）
            assert c.post(f"/api/v1/library/{a['id']}/view", json={"url": back, "view": "angle"}).json()["data"]["views"][back]["view"] == "angle"
            bad = [u for u in get()["images"] if u != back][0]
            assert bad not in c.post(f"/api/v1/library/{a['id']}/remove-image", json={"url": bad}).json()["images"]
            card = c.patch(f"/api/v1/library/{a['id']}", json={"data": {"spec_card": {"color": "星空黑", "camera_module": "圆形四摄", "junk": "x"}}}).json()["data"]
            assert card["spec_card"] == {"color": "星空黑", "camera_module": "圆形四摄"} and card["spec_card_edited"]
            asyncio.run(product.extract_spec(a["id"]))
            assert get()["data"]["spec_card"]["color"] == "星空黑"

            # 关键帧来源：纯商品特写 → 实拍合成；手持 → 占位换真机；指定 AI → AI；没有能用的图 → AI
            cast = {"product": a["id"], "roles": {"r1": None}, "scenes": {}, "names": {}}
            assert production.kf_source({"product": True, "product_tier": "hero", "roles": []}, cast) == "photo"
            assert production.kf_source({"product": True, "product_tier": "hand", "roles": ["r1"]}, cast) == "placement"
            assert production.kf_source({"product": True, "product_tier": "hand", "kf_source": "ai"}, cast) == "ai"
            assert production.kf_source({"product": True, "kf_source": "product"}, cast) == "photo"  # 旧值兼容
            assert production.kf_source({"product": True}, {"product": None}) == "ai"

            # 实拍合成：用抠图放在棚拍背景上
            kf = production.product_keyframe("vid", 2, cast)
            img = cv2.imread(str(tmp_path / kf.split("/api/v1/media/", 1)[1]))
            assert img.shape[:2] == (1920, 1080) and img[60, 60].tolist() != [255, 255, 255]  # 背景是渐变，不是白底

            # 手持两步走：先画占位手机（不给商品图），再编辑换成真实商品（给关键帧 + 商品图）
            calls.clear()
            monkeypatch.setattr(production, "_shot", lambda *a, **k: None)
            spec = {"product": True, "product_tier": "hand", "roles": [], "scene": None, "size": "MS", "move": "固定"}
            out = asyncio.run(production.make_keyframe("vid", 1, ["4", "摊主拿着手机给顾客看", "", ""], spec, {**cast, "roles": {}, "scenes": {}},
                                                       None, "尼日利亚", "", 0))
            kf2, kf_qc, tries, err = out
            imgs = [x for x in calls if x.get("modalities")]
            assert len(imgs) == 2 and not err
            step1, step2 = imgs[0]["messages"][0]["content"], imgs[1]["messages"][0]["content"]
            assert isinstance(step1, str) and "placeholder" in step1 and "商品实拍" not in step1  # 第一步没有参考图（不给商品图）
            assert step2[0]["text"].startswith("Edit image 1. Replace the placeholder phone") and "星空黑" in step2[0]["text"] and len(step2) == 3
    finally:
        llm.transport = None
        with TestClient(app) as c:
            settings_store.set_retries({"kf_candidates": 1, "kf_gate": 0})  # 老流程：每镜 1 张关键帧，画完直接生成视频
            c.delete("/api/v1/settings/secrets/openrouter")


def test_similarity_rules(tmp_path, monkeypatch):
    """结构吻合度高（画面里就是实拍像素）直接通过；否则看特写比对：不是同一款判不合格。"""
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(qc.settings_store, "llm_enabled", lambda: True)
    ref = tmp_path / "ref.png"
    rng = np.random.default_rng(1)
    phone = rng.integers(0, 255, (600, 300, 3), dtype=np.uint8)  # 纹理丰富，SIFT 能对上
    cv2.imwrite(str(ref), np.dstack([phone, np.full((600, 300), 255, np.uint8)]))
    frame = tmp_path / "f.jpg"
    canvas = np.full((1920, 1080, 3), 230, np.uint8)
    canvas[600:1200, 400:700] = phone
    cv2.imwrite(str(frame), canvas, [cv2.IMWRITE_JPEG_QUALITY, 95])
    other = tmp_path / "o.jpg"
    cv2.imwrite(str(other), np.full((1920, 1080, 3), 120, np.uint8))
    monkeypatch.setattr(product, "good_views", lambda *a, **k: [{"url": "/api/v1/media/ref.png"}])
    monkeypatch.setattr(product, "spec_text", lambda *a: "")

    async def box(f, r=None):
        return [300, 350, 640, 670]
    monkeypatch.setattr(qc, "phone_box", box)
    verdict = {"same": False, "mismatches": ["镜头是三颗，实拍是四颗"]}

    async def pair(crop, refs, card):
        return verdict
    monkeypatch.setattr(qc, "pair_check", pair)
    spec, cast = {"product": True, "product_tier": "hero"}, {"product": "p"}
    r = asyncio.run(qc.product_similarity([frame], spec, cast))
    assert r["status"] == "pass" and "实拍商品" in r["reason"]
    r = asyncio.run(qc.product_similarity([other], spec, cast))
    assert r["status"] == "fail" and "三颗" in r["reason"]
    verdict.update(same=True, mismatches=[])
    assert asyncio.run(qc.product_similarity([other], spec, cast))["status"] == "pass"
    assert qc.summarize({"similarity": {"status": "fail", "reason": "x"}}, spec)["issues"] == ["商品相似度：x"]


def test_catalog_import(tmp_path, monkeypatch):
    """传音机型库：官方渲染图（一张里两台：背面 + 正面）按框裁成单台，带视角导入，走检查和抠图；重复导入跳过。"""
    from app import catalog
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    render = np.full((800, 1000, 3), 255, np.uint8)
    cv2.rectangle(render, (100, 100), (400, 700), (40, 120, 60), -1)  # 背面（绿）
    cv2.circle(render, (180, 200), 50, (10, 10, 10), -1)
    cv2.rectangle(render, (600, 100), (900, 700), (30, 30, 30), -1)  # 正面（黑屏）
    raw = cv2.imencode(".jpg", render)[1].tobytes()
    fake = [{"id": "tecno-pova-9", "brand": "TECNO", "name": "TECNO Pova 9", "model_sku": "Pova 9", "series": "Pova", "announced": "2026, May 1",
             "year": 2026, "color": "green", "source": "https://www.gsmarena.com/x.php",
             "images": [{"src": "https://fdn2.gsmarena.com/vv/pics/tecno/tecno-pova-9-1.jpg", "box": [100, 600, 900, 920], "view": "front"},
                        {"src": "https://fdn2.gsmarena.com/vv/pics/tecno/tecno-pova-9-1.jpg", "box": [100, 80, 900, 420], "view": "back"}]}]
    monkeypatch.setattr(catalog, "load", lambda: fake)
    got = []
    catalog.transport = httpx.MockTransport(lambda r: (got.append(str(r.url)), httpx.Response(200, content=raw))[1])
    try:
        with TestClient(app) as c:
            settings_store.set_retries({"kf_candidates": 1, "kf_gate": 0})  # 老流程：每镜 1 张关键帧，画完直接生成视频
            assert [m["imported"] for m in c.get("/api/v1/library/catalog").json()] == [None]
            r = c.post("/api/v1/library/catalog/import", json={"ids": ["tecno-pova-9", "nope"]}).json()
            assert r["created"] == 1
            aid = r["items"][0]["asset_id"]
            get = lambda: next(x for x in c.get("/api/v1/library", params={"kind": "product"}).json() if x["id"] == aid)  # noqa: E731
            wait_until(lambda: get()["data"].get("import_step") == "完成" and get()["status"] == "ready")
            a = get()
            assert a["name"] == "TECNO Pova 9" and a["data"]["brand"] == "TECNO" and a["data"]["model_sku"] == "Pova 9" and len(a["images"]) == 2
            assert len(got) == 1  # 同一张渲染图只下载一次
            views = a["data"]["views"]
            assert views[a["images"][0]]["view"] == "back" and views[a["images"][1]]["view"] == "front"  # 背面排第一（商品主图）
            back = cv2.imread(str(tmp_path / a["images"][0].split("/api/v1/media/", 1)[1]))
            assert np.abs(back[back.shape[0] // 2, back.shape[1] // 2].astype(int) - [40, 120, 60]).max() <= 3  # 裁出来的是绿色背面那台
            assert all(views[u].get("cutout") for u in a["images"])
            assert c.get("/api/v1/library/catalog").json()[0]["imported"]["id"] == aid
            assert c.post("/api/v1/library/catalog/import", json={"ids": ["tecno-pova-9"]}).json()["created"] == 0
    finally:
        catalog.transport = None
