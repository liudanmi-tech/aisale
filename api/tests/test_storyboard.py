"""剧本分镜图：剧本生成后自动画（第 1 镜作参考图）、画面改了标过期、单镜重画。"""
import base64
import json
import os
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.adapters import llm  # noqa: E402
from app.main import app  # noqa: E402
from tests._watched import watch_all_ads  # noqa: E402

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n fake").decode()
calls: list[dict] = []


def handler(req: httpx.Request) -> httpx.Response:
    body = json.loads(req.content)
    if body.get("modalities"):
        calls.append(body)
        assert body["model"] == "google/gemini-3.1-flash-lite-image" and body["image_config"]["aspect_ratio"] == "9:16"
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "images": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG}"}}]}}]})
    if body.get("tools"):  # Agent 理解指令：交给规则解析
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": []}}]})
    shots = [["3", "停电的夜市，摊主手机黑屏", "NEPA don take light!", "又停电了"], ["4", "换上新手机，接单不停", "E no dey die", "不会没电"],
             ["4", "产品特写：电池参数", "6000mAh!", "大电池"], ["4", "顾客围过来问价", "Go TECNO shop!", "去门店"]]
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"shots": shots}, ensure_ascii=False)}}]})


def wait_until(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_storyboard(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    llm.transport = httpx.MockTransport(handler)
    with TestClient(app) as c:
        watch_all_ads()  # 爆款都已经看过视频（多模态拆解），洗稿方案直接出
        pid = c.post("/api/v1/projects", json={"name": "分镜", "market": "尼日利亚", "selling_point": "续航"}).json()["id"]
        P = f"/api/v1/projects/{pid}"
        c.post(P + "/agent/chat", json={"text": "给小商贩写 1 个续航剧本"})
        c.post(f"{P}/patches/{c.get(P + '/canvas').json()['pending_patch']['id']}/apply")
        script = lambda: next(n for n in c.get(P + "/canvas").json()["nodes"] if n["type"] == "script")  # noqa: E731
        assert c.post(f"/api/v1/nodes/{script()['id']}/storyboard", json={}).status_code == 400  # 没有 OpenRouter Key：不画

        c.put("/api/v1/settings/secrets/openrouter", json={"value": "sk-or-test-5678wxyz"})
        wash = lambda: next(n for n in c.get(P + "/canvas").json()["nodes"] if n["type"] == "wash")  # noqa: E731
        wait_until(lambda: wash()["status"] == "wait")
        c.post("/api/v1/reviews/pass-nodes", json={"node_ids": [wash()["id"]]})  # 确认洗稿方案 → 写剧本
        wait_until(lambda: script()["status"] == "wait")
        wait_until(lambda: (script()["data"].get("storyboard") or {}).get("status") == "done")  # 剧本写好自动画手绘分镜
        nid = script()["id"]
        c.post(f"/api/v1/nodes/{nid}/storyboard", json={})
        wait_until(lambda: (script()["data"].get("storyboard") or {}).get("status") == "done")
        d = script()["data"]
        assert len(d["frames"]) == 4 and all(f["url"].startswith("/api/v1/media/storyboards/") for f in d["frames"])
        assert (tmp_path / "storyboards" / d["frames"][0]["url"].rsplit("/", 1)[1]).read_bytes().startswith(b"\x89PNG")
        assert len(calls) == 4 and isinstance(calls[0]["messages"][0]["content"], str)  # 第 1 镜不带参考图
        later = [b["messages"][0]["content"] for b in calls[1:]]
        assert all(isinstance(x, list) and x[1]["type"] == "image_url" for x in later)  # 其余镜头带第 1 镜作参考
        assert any("产品特写" in x[0]["text"] for x in later) and f"画面：{d['shots'][0][1]}" in calls[0]["messages"][0]["content"]

        shots = d["shots"]
        shots[1][1] = "主角在雨里送货"
        c.patch(f"{P}/nodes/{nid}", json={"data": {"shots": shots}})
        n0 = len(calls)
        c.post(f"/api/v1/nodes/{nid}/storyboard", json={})  # 只重画画面改过的镜头
        wait_until(lambda: script()["data"]["frames"][1]["visual"] == "主角在雨里送货")
        assert len(calls) == n0 + 1 and "主角在雨里送货" in calls[-1]["messages"][0]["content"][0]["text"]
        c.post(f"/api/v1/nodes/{nid}/storyboard", json={"indices": [3]})  # 强制重画指定镜头
        wait_until(lambda: len(calls) == n0 + 2 and (script()["data"].get("storyboard") or {}).get("status") == "done")
        c.delete("/api/v1/settings/secrets/openrouter")
    llm.transport = None
