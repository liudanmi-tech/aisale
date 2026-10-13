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

from app import config, qc  # noqa: E402
from app.adapters import fal, llm  # noqa: E402
from app.main import app  # noqa: E402

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


def fal_handler(req: httpx.Request) -> httpx.Response:
    if req.method == "POST" and FAL_DOWN["after"] is not None:
        FAL_DOWN["after"] -= 1
        FAL_DOWN["on"] = FAL_DOWN["after"] < 0
    if req.method == "POST" and FAL_DOWN["on"]:
        return httpx.Response(403, json={"detail": "User is locked. Reason: Exhausted balance."})
    if req.method == "POST":
        body = json.loads(req.content)
        i2v.append({"path": req.url.path, **body})
        rid = f"r{len(i2v)}"
        return httpx.Response(200, json={"request_id": rid, "status_url": f"https://queue.fal.run/x/requests/{rid}/status", "response_url": f"https://queue.fal.run/x/requests/{rid}"})
    if req.url.path.endswith("/status"):
        return httpx.Response(200, json={"status": "COMPLETED"})
    return httpx.Response(200, json={"video": {"url": f"https://v3.fal.media/files/{req.url.path.rsplit('/', 1)[1]}.mp4"}})


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
    with TestClient(app) as c:
        c.put("/api/v1/settings/secrets/openrouter", json={"value": "sk-or-test-5678wxyz"})
        c.put("/api/v1/settings/secrets/fal", json={"value": "fal-test-key-1234abcd"})
        pid = c.post("/api/v1/projects", json={"name": "制作", "market": "尼日利亚", "brand": "TECNO", "model_sku": "Spark 40", "selling_point": "续航"}).json()["id"]
        P = f"/api/v1/projects/{pid}"
        canvas = lambda: c.get(P + "/canvas").json()  # noqa: E731
        of = lambda t: [n for n in canvas()["nodes"] if n["type"] == t]  # noqa: E731
        c.post(P + "/agent/chat", json={"text": "给小商贩写 1 个续航剧本"})
        c.post(f"{P}/patches/{canvas()['pending_patch']['id']}/apply")
        wait_until(lambda: of("script") and of("script")[0]["status"] == "wait")
        c.post("/api/v1/reviews/pass-nodes", json={"node_ids": [of("script")[0]["id"]]})

        # 选角置景 → 素材节点上画布；有商品镜头、没有商品图 → 停在「待上传」
        wait_until(lambda: of("video") and of("video")[0]["status"] == "input")
        v, s = of("video")[0], of("script")[0]
        cast = s["data"]["cast"]
        assert cast["genre"] == "情景剧" and set(cast["roles"]) == {"r1", "r2"} and cast["names"]["r1"] == "女摊主"
        assert cast["specs"][3] == {"shot": 3, "size": "MS", "move": "固定", "roles": [], "scene": "s1", "product": False, "line": "Go TECNO"}
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
        assert len(kf_calls) == 5 and all(t["keyframe"].startswith("/api/v1/media/keyframes/") for t in v["data"]["tasks"])
        refs = lambda b: len(b["messages"][0]["content"]) - 1 if isinstance(b["messages"][0]["content"], list) else 0  # noqa: E731
        texts = [b["messages"][0]["content"][0]["text"] for b in kf_calls]
        shot0 = next(b for b, t in zip(kf_calls, texts) if "停电的夜市" in t)
        assert refs(shot0) == 6 and "三视图" in shot0["messages"][0]["content"][0]["text"]  # 分镜 + 2 个演员各定妆照和三视图 + 场景
        t0 = v["data"]["tasks"][0]
        assert t0["phase"] == "完成" and t0["inputs"]["visual"] == "停电的夜市" and ["scene", "s1", alt["id"], alt["images"][0]] in t0["inputs"]["refs"]
        prod = next(b for b, t in zip(kf_calls, texts) if "产品特写" in t)
        assert "商品实拍" in prod["messages"][0]["content"][0]["text"]
        assert len(i2v) == 4 and all(x["path"].endswith("/image-to-video") and x["image_url"].startswith("data:image/") for x in i2v)
        assert v["data"]["engine"].endswith("image-to-video")
        # 质检：第 1 镜关键帧不合格 → 带着问题重画一次后通过；商品镜头要人工确认
        retry = [b for b, t in zip(kf_calls, texts) if "停电的夜市" in t]
        assert len(retry) == 2 and "六根手指" in retry[1]["messages"][0]["content"][0]["text"]
        t0 = v["data"]["tasks"][0]["qc"]
        assert t0["status"] == "pass" and t0["attempts"]["keyframe"] == 2 and t0["checks"]["face"]["status"] == "skip"
        rep = v["data"]["qc"]
        assert rep["retried"] == 1 and rep["manual"] == [3] and rep["pass"] + rep["warn"] == 4
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
        FAL_DOWN["after"] = 1  # 第一次提交成功，第二次（重做）失败
        assert c.post(f"/api/v1/nodes/{v['id']}/shots/2/regenerate").json()["ok"]
        wait_until(lambda: of("video")[0]["status"] in ("wait", "failed") and of("video")[0]["data"]["tasks"][2].get("phase") == "完成")
        t2 = of("video")[0]["data"]["tasks"][2]
        assert of("video")[0]["status"] == "wait" and t2["status"] == "completed" and t2["url"].startswith("https://")
        assert "Exhausted balance" in t2["retry_error"] and t2["qc"]["status"] == "fail"
        FAL_DOWN.update(on=False, after=None)

        for name in ("openrouter", "fal"):
            c.delete(f"/api/v1/settings/secrets/{name}")
    llm.transport = fal.transport = None
