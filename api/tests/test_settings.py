"""设置页密钥与模型：加密存储、免费校验、管理员口令；fal 视频生成与大模型 40 人评测走真实调用路径（用模拟 HTTP 响应）。"""
import json
import os
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import settings_store  # noqa: E402
from app.adapters import fal, llm  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Secret  # noqa: E402

FAL_KEY = "fal-test-key-1234abcd"
OR_KEY = "sk-or-test-5678wxyz"
calls = {"fal_submit": [], "llm": []}


def fal_handler(req: httpx.Request) -> httpx.Response:
    assert req.headers["authorization"] in (f"Key {FAL_KEY}", "Key wrong-key-0000")
    if req.headers["authorization"] == "Key wrong-key-0000":
        return httpx.Response(401, json={"detail": "invalid key credentials"})
    if req.method == "POST":
        body = json.loads(req.content)
        calls["fal_submit"].append((req.url.path, body))
        rid = f"r{len(calls['fal_submit'])}"
        return httpx.Response(200, json={"request_id": rid, "status_url": f"https://queue.fal.run/x/requests/{rid}/status",
                                         "response_url": f"https://queue.fal.run/x/requests/{rid}"})
    if req.url.path.endswith("/status"):
        return httpx.Response(404 if "0000-0000" in req.url.path else 200, json={"status": "COMPLETED"})
    rid = req.url.path.rsplit("/", 1)[1]
    return httpx.Response(200, json={"video": {"url": f"https://v3.fal.media/files/{rid}.mp4"}, "seed": 7})


def llm_handler(req: httpx.Request) -> httpx.Response:
    if req.url.path.endswith("/key"):
        return httpx.Response(200, json={"data": {"limit_remaining": 12.5}})
    body = json.loads(req.content)
    calls["llm"].append(body["model"])
    if body.get("tools"):
        text = body["messages"][-1]["content"]
        name, args = ("write_scripts", {"count": 1, "selling_point": "续航", "audience": "小商贩"}) if "剧本" in text else \
            ("generate_videos", {}) if "视频" in text else ("run_evaluation", {})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None,
                              "tool_calls": [{"id": "t1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]})
    system = body["messages"][0]["content"]
    if "TikTok 信息流" in system:
        reactions = [{"persona": i, "drop_at": 15 if i % 2 else 3, "clicked": i % 5 == 1, "comment": f"第{i}个人的反应"} for i in range(40)]
        content = json.dumps({"reactions": reactions, "scores": {"hook": 8, "clarity": 7, "trust": 7, "local": 9, "intent": 6}, "issue": "第 3 秒卖点太快"})
    else:
        content = json.dumps({"shots": [["0–3s", "停电夜", "Light don cut!", "停电了"], ["3–7s", "收款", "No charger.", "不用充电"],
                                        ["7–11s", "产品特写", "6000mAh.", "大电池"], ["11–15s", "CTA", "Buy am!", "快买"]]})
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


def wait_until(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_settings_and_real_call_paths():
    fal.transport, llm.transport, fal.POLL_SECONDS = httpx.MockTransport(fal_handler), httpx.MockTransport(llm_handler), 0.01
    try:
        with TestClient(app) as c:
            s = c.get("/api/v1/settings").json()
            assert s["secrets"]["fal"]["configured"] is False and s["integrations"][0]["mode"] == "模拟"
            assert c.put("/api/v1/settings/secrets/fal", json={"value": "short"}).status_code == 400

            # 保存后只回显末 4 位，数据库里是密文
            r = c.put("/api/v1/settings/secrets/fal", json={"value": FAL_KEY}).json()
            assert r["masked"] == "••••abcd" and FAL_KEY not in json.dumps(c.get("/api/v1/settings").json())
            c.put("/api/v1/settings/secrets/openrouter", json={"value": OR_KEY})
            with SessionLocal() as db:
                assert FAL_KEY not in db.get(Secret, "fal").ciphertext
            assert settings_store.get_secret("fal") == FAL_KEY

            # 免费校验
            assert c.post("/api/v1/settings/secrets/fal/test", json={}).json()["ok"] is True
            assert c.post("/api/v1/settings/secrets/fal/test", json={"value": "wrong-key-0000"}).json()["ok"] is False
            assert "12.50" in c.post("/api/v1/settings/secrets/openrouter/test", json={}).json()["message"]

            # 按任务选模型
            m = c.put("/api/v1/settings/models", json={"eval": "google/gemini-2.5-pro", "video": "fal-ai/bytedance/seedance/v1/pro/text-to-video", "bogus": "x"}).json()
            assert m["eval"] == "google/gemini-2.5-pro" and "bogus" not in m

            # 新项目跑通：剧本（大模型）→ 视频（fal）→ 评测（大模型 40 人）
            pid = c.post("/api/v1/projects", json={"name": "真实调用路径", "market": "尼日利亚"}).json()["id"]
            P = f"/api/v1/projects/{pid}"
            c.post(f"{P}/wash", json={"ref_ad_no": 13})
            c.post(f"{P}/agent/chat", json={"text": "给小商贩写 1 个续航剧本"})
            p = c.get(f"{P}/canvas").json()["pending_patch"]
            c.post(f"{P}/patches/{p['id']}/apply")
            nodes = lambda t: [n for n in c.get(f"{P}/canvas").json()["nodes"] if n["type"] == t]  # noqa: E731
            wait_until(lambda: nodes("script") and nodes("script")[0]["status"] == "wait")
            assert nodes("script")[0]["data"]["shots"][0][2] == "Light don cut!"
            approve = lambda: [c.post(f"/api/v1/reviews/{r['id']}/decide", json={"decision": "pass"}) for r in c.get("/api/v1/reviews", params={"status": "wait"}).json() if r["project_id"] == pid]  # noqa: E731
            approve()  # 剧本通过后自动生成视频

            wait_until(lambda: nodes("video") and nodes("video")[0]["status"] == "wait")
            v = nodes("video")[0]
            assert v["data"]["engine"] == "fal-ai/bytedance/seedance/v1/pro/text-to-video"
            assert v["data"]["video_url"].startswith("https://v3.fal.media/") and len(v["data"]["shot_urls"]) == 3
            path, body = calls["fal_submit"][0]
            assert path == "/fal-ai/bytedance/seedance/v1/pro/text-to-video" and body["aspect_ratio"] == "9:16" and body["duration"] == "5"
            approve()  # 视频通过后自动评测

            wait_until(lambda: nodes("eval") and nodes("eval")[0]["status"] == "wait")
            ev = nodes("eval")[0]["data"]
            r0 = ev["results"][0]
            assert ev["engine"] == "google/gemini-2.5-pro" and r0["vtr"] == 50 and r0["reactions"][1]["comment"] == "第1个人的反应"
            assert "google/gemini-2.5-pro" in calls["llm"] and "anthropic/claude-sonnet-5.5" in calls["llm"]

            # 管理员口令
            os.environ["ADMIN_TOKEN"] = "admin-secret"
            assert c.put("/api/v1/settings/models", json={"eval": "x/y"}).status_code == 401
            assert c.put("/api/v1/settings/models", json={"eval": "google/gemini-2.5-flash"}, headers={"X-Admin-Token": "admin-secret"}).status_code == 200
            del os.environ["ADMIN_TOKEN"]

            c.delete("/api/v1/settings/secrets/fal")
            c.delete("/api/v1/settings/secrets/openrouter")
            c.put("/api/v1/settings/models", json=settings_store.DEFAULT_MODELS)
            assert c.get("/api/v1/settings").json()["secrets"]["fal"]["configured"] is False
    finally:
        fal.transport = llm.transport = None
