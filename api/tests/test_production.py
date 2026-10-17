"""视频制作流程：剧本通过 → 分镜 → 选角置景（演员 / 场景 / 商品节点）→ 等商品图 → 关键帧（带参考图）→ 图生视频。"""
import base64
import json
import os
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config, product, qc  # noqa: E402
from app.adapters import fal, llm  # noqa: E402
from app import settings_store  # noqa: E402
from app.main import app  # noqa: E402
from tests._watched import watch_all_ads  # noqa: E402

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n img").decode()
images: list[dict] = []
i2v: list[dict] = []
qc_calls: list[dict] = []
OK = {"status": "pass", "reason": "无"}
QC_GOOD = {"product": {"present": True, "status": "pass", "items": {"颜色": "pass", "摄像头模组": "pass"}, "reason": "无"},
           "people": OK, "artifacts": {**OK, "items": []}, "text": OK, "script": OK}
QC_BAD = {**QC_GOOD, "artifacts": {"status": "fail", "items": ["手指畸形"], "reason": "女摊主左手六根手指"}}
CAST = {"genre": "情景剧",
        "roles": [{"key": "r1", "name": "女摊主", "description": "25 岁尼日利亚女性，编发，印花上衣", "reuse": None},
                  {"key": "r2", "name": "顾客", "description": "30 岁男性，衬衫", "reuse": None}],
        "scenes": [{"key": "s1", "name": "雨夜市场", "description": "下雨的夜晚，摊位挂着灯泡", "reuse": None}],
        "specs": [{"shot": 0, "size": "WS", "move": "推", "roles": ["r1", "r2"], "scene": "s1", "product": False, "line": "Light don go!"},
                  {"shot": 1, "size": "MS", "move": "跟拍", "roles": ["r1"], "scene": "s1", "product": False, "line": "Phone still dey"},
                  {"shot": 2, "size": "CU", "move": "固定", "roles": [], "scene": "s1", "product": True, "line": "6000mAh"},
                  {"shot": 3, "size": "XX", "move": "乱写", "roles": ["r9"], "scene": "s9", "product": False, "line": "Go TECNO"}]}


def llm_handler(req: httpx.Request) -> httpx.Response:
    body = json.loads(req.content)
    if body.get("modalities"):
        images.append(body)
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "images": [{"type": "image_url", "image_url": {"url": PNG}}]}}]})
    if body.get("tools"):
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": []}}]})
    sys_prompt = body["messages"][0]["content"]
    if isinstance(sys_prompt, list) and "质检员" in sys_prompt[0]["text"]:
        qc_calls.append(body)
        # 第 1 镜（停电的夜市）的第一张关键帧不合格，其余都合格
        bad = "停电的夜市" in sys_prompt[0]["text"] and sum("停电的夜市" in b["messages"][0]["content"][0]["text"] for b in qc_calls) == 1
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(QC_BAD if bad else QC_GOOD, ensure_ascii=False)}}]})
    out = CAST if "选角导演" in sys_prompt else {"shots": [["3", "停电的夜市", "NEPA!", "停电"], ["4", "接单不停", "E no die", "不会没电"],
                                                         ["4", "产品特写", "6000mAh", "大电池"], ["4", "顾客问价", "Go shop", "去门店"]]}
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}]})


FAL_DOWN = {"on": False, "after": None}


cuts: list[dict] = []
kinds: dict[str, str] = {}


def fal_handler(req: httpx.Request) -> httpx.Response:
    if req.method == "POST" and FAL_DOWN["after"] is not None and "birefnet" not in req.url.path:
        FAL_DOWN["after"] -= 1
        FAL_DOWN["on"] = FAL_DOWN["after"] < 0
    if req.method == "POST" and FAL_DOWN["on"] and "birefnet" not in req.url.path:
        return httpx.Response(403, json={"detail": "User is locked. Reason: Exhausted balance."})
    if req.method == "POST":
        body = json.loads(req.content)
        if "birefnet" in req.url.path:  # 抠图
            cuts.append(body)
            rid = f"c{len(cuts)}"
            kinds[rid] = "cut"
        else:
            i2v.append({"path": req.url.path, **body})
            rid = f"r{len(i2v)}"
        return httpx.Response(200, json={"request_id": rid, "status_url": f"https://queue.fal.run/x/requests/{rid}/status", "response_url": f"https://queue.fal.run/x/requests/{rid}"})
    if req.url.path.endswith("/status"):
        return httpx.Response(200, json={"status": "COMPLETED"})
    rid = req.url.path.rsplit("/", 1)[1]
    if kinds.get(rid) == "cut":
        return httpx.Response(200, json={"image": {"url": f"https://v3.fal.media/files/{rid}.png"}})
    return httpx.Response(200, json={"video": {"url": f"https://v3.fal.media/files/{rid}.mp4"}})


def wait_until(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_production(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(qc, "_face", {"loaded": True, "det": None, "rec": None, "error": "测试环境不下载人脸模型"})
    monkeypatch.setattr(qc, "_ffmpeg_ok", lambda: False)
    llm.transport, fal.transport, fal.POLL_SECONDS = httpx.MockTransport(llm_handler), httpx.MockTransport(fal_handler), 0.01
    product.media_transport = httpx.MockTransport(lambda r: httpx.Response(200, content=base64.b64decode(PNG.split(",", 1)[1])))
    with TestClient(app) as c:
        settings_store.set_retries({"kf_candidates": 1, "kf_gate": 0})  # 老流程：每镜 1 张关键帧，画完直接生成视频
        watch_all_ads()  # 爆款都已经看过视频（多模态拆解），洗稿方案直接出
        c.put("/api/v1/settings/secrets/openrouter", json={"value": "sk-or-test-5678wxyz"})
        c.put("/api/v1/settings/secrets/fal", json={"value": "fal-test-key-1234abcd"})
        pid = c.post("/api/v1/projects", json={"name": "制作", "market": "尼日利亚", "brand": "TECNO", "model_sku": "Spark 40", "selling_point": "续航"}).json()["id"]
        P = f"/api/v1/projects/{pid}"
        canvas = lambda: c.get(P + "/canvas").json()  # noqa: E731
        of = lambda t: [n for n in canvas()["nodes"] if n["type"] == t]  # noqa: E731
        c.post(P + "/agent/chat", json={"text": "给小商贩写 1 个续航剧本"})
        c.post(f"{P}/patches/{canvas()['pending_patch']['id']}/apply")
        wait_until(lambda: of("wash") and of("wash")[0]["status"] == "wait")  # 先确认洗稿方案，剧本才写
        c.post("/api/v1/reviews/pass-nodes", json={"node_ids": [of("wash")[0]["id"]]})
        wait_until(lambda: of("script") and of("script")[0]["status"] == "wait")
        c.post("/api/v1/reviews/pass-nodes", json={"node_ids": [of("script")[0]["id"]]})

        # 选角置景 → 素材节点上画布；有商品镜头、没有商品图 → 停在「待上传」
        wait_until(lambda: of("video") and of("video")[0]["status"] == "input")
        v, s = of("video")[0], of("script")[0]
        cast = s["data"]["cast"]
        assert cast["genre"] == "情景剧" and set(cast["roles"]) == {"r1", "r2"} and cast["names"]["r1"] == "女摊主"
        assert cast["specs"][3] == {"shot": 3, "size": "MS", "move": "固定", "roles": [], "scene": "s1", "product": False, "line": "Go TECNO",
                                    "product_tier": None, "overlay": ""}
        assert cast["specs"][2]["product_tier"] == "hero"  # 没写级别、没有人物的商品镜头 → 纯商品特写
        assert len(of("actor")) == 2 and len(of("scene")) == 1 and of("product")[0]["status"] == "input"
        lib = {a["name"]: a for a in c.get("/api/v1/library").json()}
        assert lib["女摊主"]["images"] and lib["雨夜市场"]["images"] and not lib["TECNO Spark 40"]["images"]
        assert "实拍图" in c.get(P + "/chat").json()[-1]["text"] and "确认选角" in c.get(P + "/chat").json()[-1]["text"]

        # 选角确认：花钱画关键帧之前停下；演员有定妆照 + 三视图
        assert v["data"]["stage"] == "确认选角" and v["data"]["need_product"] == lib["TECNO Spark 40"]["id"]
        assert lib["女摊主"]["data"]["turnaround"].startswith("/api/v1/media/") and lib["女摊主"]["status"] == "ready"
        assert c.post(f"/api/v1/nodes/{v['id']}/confirm-cast").status_code == 400  # 还没上传商品图
        # 确认前在视频节点里换场景：只改这条视频的剧本选角
        alt = c.post("/api/v1/library", json={"kind": "scene", "name": "白天的路边摊", "description": "晴天", "image": PNG}).json()
        assert c.post(f"/api/v1/nodes/{v['id']}/cast", json={"key": "s1", "asset_id": alt["id"]}).json()["cast"]["scenes"]["s1"] == alt["id"]
        assert c.post(f"/api/v1/nodes/{v['id']}/cast", json={"key": "s1", "asset_id": lib["女摊主"]["id"]}).status_code == 400
        assert not any(n["data"]["asset_id"] == lib["雨夜市场"]["id"] for n in of("scene") if any(e["source"] == n["id"] and e["target"] == v["id"] for e in canvas()["edges"]))

        # 上传商品图后不自动继续（还在等确认）；确认 → 每镜关键帧（参考分镜、演员、三视图、场景、商品）→ 质检 → 图生视频
        n_img = len(images)
        r = c.post(f"/api/v1/library/{lib['TECNO Spark 40']['id']}/upload", json={"image": PNG}).json()
        assert r["resumed"] == []
        c.post(P + "/agent/chat", json={"text": "选角没问题，开始生成"})  # 在左侧对话里确认，和点按钮一样
        assert "选角已确认" in c.get(P + "/chat").json()[-1]["text"]
        wait_until(lambda: of("video")[0]["status"] == "wait")
        v = of("video")[0]
        kf_calls = images[n_img:]
        # 4 镜 + 1：第 2 镜口播「Phone still dey」里有手机，自动升级成手持商品镜头，先画占位手机再换真机（多一次调用）
        assert len(kf_calls) == 6 and all(t["keyframe"].startswith("/api/v1/media/keyframes/") for t in v["data"]["tasks"])
        refs = lambda b: len(b["messages"][0]["content"]) - 1 if isinstance(b["messages"][0]["content"], list) else 0  # noqa: E731
        texts = [b["messages"][0]["content"][0]["text"] for b in kf_calls]
        shot0 = next(b for b, t in zip(kf_calls, texts) if "停电的夜市" in t)
        assert refs(shot0) == 6 and "三视图" in shot0["messages"][0]["content"][0]["text"]  # 分镜 + 2 个演员各定妆照和三视图 + 场景
        t0 = v["data"]["tasks"][0]
        assert t0["phase"] == "完成" and t0["inputs"]["visual"] == "停电的夜市" and ["scene", "s1", alt["id"], alt["images"][0]] in t0["inputs"]["refs"]
        prod = next(b for b, t in zip(kf_calls, texts) if "产品特写" in t)
        assert "商品实拍" in prod["messages"][0]["content"][0]["text"]
        # 没有手机的 2 镜走 Seedance 2.5 图生视频；商品镜头（第 3 镜特写 + 第 2 镜手持）走全能参考：@Image1 关键帧 + 商品实拍，关掉模型自带声音
        plain = [x for x in i2v if x["path"].endswith("/image-to-video")]
        ref = [x for x in i2v if x["path"].endswith("/reference-to-video")]
        assert len(plain) == 2 and all(x["path"] == "/bytedance/seedance-2.5/image-to-video" and x["image_url"].startswith("data:image/") for x in plain)
        assert "aspect_ratio" not in plain[0] and plain[0]["generate_audio"] is False
        assert len(ref) == 2 and all(x["path"] == "/bytedance/seedance-2.5/reference-to-video" and len(x["image_urls"]) >= 2 for x in ref)
        assert ref[0]["prompt"].startswith("@Image1 is the opening frame") and "@Image2" in ref[0]["prompt"] and ref[0]["generate_audio"] is False
        assert v["data"]["engine"].endswith("image-to-video")
        # 质检：第 1 镜关键帧不合格 → 带着问题重画一次后通过；商品镜头要人工确认
        retry = [b for b, t in zip(kf_calls, texts) if "停电的夜市" in t]
        assert len(retry) == 2 and "六根手指" in retry[1]["messages"][0]["content"][0]["text"]
        t0 = v["data"]["tasks"][0]["qc"]
        assert t0["status"] == "pass" and t0["attempts"]["keyframe"] == 2 and t0["checks"]["face"]["status"] == "skip"
        rep = v["data"]["qc"]
        assert rep["retried"] == 1 and 3 in rep["manual"] and rep["pass"] + rep["warn"] == 4
        assert "质检" in v["sub"]

        # 换演员：画布上的演员节点换成素材库里另一个，剧本选角同步
        actor_in = {"kind": "actor", "name": "年轻男摊主", "description": "20 岁男性", "image": PNG}
        assert c.post("/api/v1/library", json=actor_in).status_code == 400  # 真人照片没确认肖像授权
        new = c.post("/api/v1/library", json={**actor_in, "consent": True}).json()
        assert new["data"]["consent"]["text"].startswith("我确认已取得")
        actor = next(n for n in of("actor") if "女摊主" in n["title"])
        assert c.post(f"/api/v1/nodes/{actor['id']}/asset", json={"asset_id": new["id"]}).json()["title"] == "演员 · 年轻男摊主"
        assert of("script")[0]["data"]["cast"]["roles"]["r1"] == new["id"]
        assert c.post(f"/api/v1/nodes/{actor['id']}/asset", json={"asset_id": lib["雨夜市场"]["id"]}).status_code == 400  # 类型不符
        assert c.delete(f"/api/v1/library/{new['id']}").status_code == 409  # 画布上在用

        # 单镜重生成：只重做第 2 镜
        n_i2v = len(i2v)
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/1/regenerate").json()["ok"]
        wait_until(lambda: len(i2v) == n_i2v + 1 and of("video")[0]["status"] == "wait")
        assert len([r for r in c.get("/api/v1/reviews", params={"status": "wait"}).json() if r["node_id"] == v["id"]]) == 1  # 旧审核单作废

        # 只重做改过的几镜
        n_i2v = len(i2v)
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/regenerate", json={"indices": [0, 3, 9]}).json()["indices"] == [0, 3]
        wait_until(lambda: len(i2v) == n_i2v + 2 and of("video")[0]["status"] == "wait")
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/regenerate", json={"indices": []}).status_code == 400

        # fal 拒绝（余额不足）：镜头标失败并带上 fal 的原因；恢复后重做只重做视频，沿用已画好的关键帧
        FAL_DOWN["on"] = True
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/1/regenerate").json()["ok"]
        wait_until(lambda: of("video")[0]["status"] == "failed")
        t1 = of("video")[0]["data"]["tasks"][1]
        assert t1["status"] == "failed" and "余额" in t1["error"] and "Exhausted balance" in t1["error"] and t1["keyframe"]
        FAL_DOWN["on"] = False
        n_img, n_i2v = len(images), len(i2v)
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/1/regenerate").json()["ok"]
        wait_until(lambda: of("video")[0]["status"] == "wait")
        assert len(images) == n_img and len(i2v) == n_i2v + 1 and of("video")[0]["data"]["tasks"][1]["keyframe"] == t1["keyframe"]

        # 视频质检不合格 → 自动重做；重做那次 fal 失败 → 保留第一条视频，不判失败
        async def bad_clip(url, shot, spec, cast_):
            return qc.summarize({"tech": {"status": "fail", "reason": "画幅不是 9:16"}}, spec)
        monkeypatch.setattr(qc, "check_clip", bad_clip)
        # 默认不自动重做视频：只生成 1 条，标红交给人
        assert {k: v for k, v in c.get("/api/v1/settings").json()["retries"].items() if k in ("keyframe", "clip")} == {"keyframe": 2, "clip": 0}
        n_i2v = len(i2v)
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/2/regenerate").json()["ok"]
        wait_until(lambda: of("video")[0]["status"] == "wait" and of("video")[0]["data"]["tasks"][2].get("phase") == "完成")
        assert len(i2v) == n_i2v + 1 and of("video")[0]["data"]["tasks"][2]["qc"]["status"] == "fail"
        # 打开 1 次自动重做
        assert c.put("/api/v1/settings/retries", json={"clip": 5, "keyframe": "x", "kf_candidates": 0}).json() == {"keyframe": 2, "clip": 1, "kf_candidates": 1, "kf_gate": 0}  # 超出上下限按上下限
        FAL_DOWN["after"] = 1  # 第一次提交成功，第二次（重做）失败
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/2/regenerate").json()["ok"]
        wait_until(lambda: of("video")[0]["status"] in ("wait", "failed") and of("video")[0]["data"]["tasks"][2].get("phase") == "完成")
        t2 = of("video")[0]["data"]["tasks"][2]
        assert of("video")[0]["status"] == "wait" and t2["status"] == "completed" and t2["url"].startswith("https://")
        assert "Exhausted balance" in t2["retry_error"] and t2["qc"]["status"] == "fail"
        FAL_DOWN.update(on=False, after=None)
        c.put("/api/v1/settings/retries", json={"keyframe": 2, "clip": 0})
        monkeypatch.undo()
        monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
        monkeypatch.setattr(qc, "_face", {"loaded": True, "det": None, "rec": None, "error": "测试环境不下载人脸模型"})
        monkeypatch.setattr(qc, "_ffmpeg_ok", lambda: False)

        # 回到关键帧：只重画第 1 镜关键帧（带修改意见），画完停下等确认，不生成视频
        n_img, n_i2v = len(images), len(i2v)
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/0/keyframe", json={"comment": "摊主要拿着手机照亮摊位"}).json()["ok"]
        wait_until(lambda: of("video")[0]["status"] == "input")
        vv = of("video")[0]
        t0 = vv["data"]["tasks"][0]
        assert vv["data"]["stage"] == "关键帧待确认" and t0["phase"] == "关键帧待确认" and t0["url"] is None and t0["keyframe"]
        assert len(images) == n_img + 1 and len(i2v) == n_i2v and "摊主要拿着手机照亮摊位" in images[-1]["messages"][0]["content"][0]["text"]
        assert not [r for r in c.get("/api/v1/reviews", params={"status": "wait"}).json() if r["node_id"] == v["id"]]  # 旧审核单作废
        assert c.post(f"/api/v1/nodes/{v['id']}/confirm-cast").status_code == 409
        # 每张关键帧都记下用了什么提示词和哪些参考图；重画时可以去掉某张参考图、直接改提示词
        meta = t0["kf_meta"]
        labels = [r["label"] for r in meta["refs"]]
        assert labels[0] == "分镜草图" and "年轻男摊主 定妆照" in labels and "年轻男摊主 三视图" in labels and any(x.startswith("场景：") for x in labels)
        assert "停电的夜市" in meta["prompt"] and meta["comment"] == "摊主要拿着手机照亮摊位"
        drop = next(r["url"] for r in meta["refs"] if r["kind"] == "storyboard")
        n_img = len(images)
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/0/keyframe", json={"prompt": "夜市摊位，摊主举着手机当手电筒，竖屏真实照片", "drop_refs": [drop]}).json()["ok"]
        wait_until(lambda: len(images) == n_img + 1 and of("video")[0]["status"] == "input")
        body = images[-1]["messages"][0]["content"]
        assert body[0]["text"].startswith("夜市摊位，摊主举着手机当手电筒") and "分镜草图" not in body[0]["text"] and len(body) - 1 == len(meta["refs"]) - 1
        m2 = of("video")[0]["data"]["tasks"][0]["kf_meta"]
        assert m2["custom_prompt"] and m2["dropped"] == [drop] and len(m2["refs"]) == len(meta["refs"]) - 1
        # 确认这张 → 生成视频 → 重新提交审核
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/0/clip").json()["ok"]
        wait_until(lambda: of("video")[0]["status"] == "wait")
        assert len(i2v) == n_i2v + 1 and of("video")[0]["data"]["tasks"][0]["keyframe"] == t0["keyframe"]
        assert len([r for r in c.get("/api/v1/reviews", params={"status": "wait"}).json() if r["node_id"] == v["id"]]) == 1

        # 商品特写：有真实的商品实拍图时，关键帧直接用实拍图合成（不调用生图），视频提示词要求商品不变
        import cv2
        import numpy as np
        photo = np.full((400, 300, 3), 255, np.uint8)
        cv2.rectangle(photo, (80, 40), (220, 360), (90, 90, 90), -1)
        real = "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", photo)[1].tobytes()).decode()
        c.post(f"/api/v1/library/{lib['TECNO Spark 40']['id']}/upload", json={"image": real})
        n_img, n_i2v = len(images), len(i2v)
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/2/keyframe", json={}).json()["ok"]
        wait_until(lambda: of("video")[0]["status"] == "input")
        t2 = of("video")[0]["data"]["tasks"][2]
        assert len(images) == n_img and t2["kf_from"] == "product" and t2["qc"]["checks"]["product"]["status"] == "pass"
        kf = cv2.imread(str(tmp_path / t2["keyframe"].split("/api/v1/media/", 1)[1]))
        assert kf.shape[:2] == (1920, 1080) and tuple(int(x) for x in kf[10, 10]) == (255, 255, 255)  # 背景取实拍图的底色
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/2/clip").json()["ok"]
        wait_until(lambda: of("video")[0]["status"] == "wait")
        assert i2v[-1]["path"].endswith("/reference-to-video") and "Product hero shot" in i2v[-1]["prompt"] and of("video")[0]["data"]["tasks"][2]["kf_from"] == "product"

        for name in ("openrouter", "fal"):
            c.delete(f"/api/v1/settings/secrets/{name}")
    llm.transport = fal.transport = product.media_transport = None
