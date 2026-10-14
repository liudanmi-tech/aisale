"""左侧 Agent：滑动窗口记忆（「继续」接上之前的指令）、任意人群 / 标签 / 语言 / 机型写剧本。"""
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app import agent, settings_store  # noqa: E402
from app.adapters import llm  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ChatMessage  # noqa: E402

ASK = "给埃塞俄比亚的「大学生、自拍美颜、短视频创作、基督教」人群写 3 个 Infinix Hot 60 的剧本，用阿姆哈拉语口播"


def test_free_audience_and_follow_up():
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "记忆", "market": "埃塞俄比亚"}).json()["id"]
        P = f"/api/v1/projects/{pid}"
        c.post(P + "/agent/chat", json={"text": ASK, "selection": []})
        patch = c.get(P + "/canvas").json()["pending_patch"]
        assert patch and patch["summary"] == "写剧本"
        aud = next(o for o in patch["ops"] if o["op"] == "create_node" and o["type"] == "aud")
        assert aud["data"]["audience"] == "大学生" and "基督教" in aud["data"]["tags"]
        script = next(o for o in patch["ops"] if o["op"] == "create_node" and o["type"] == "script")
        assert script["data"]["language"] == "阿姆哈拉语" and script["data"]["model_sku"] == "Infinix Hot 60"
        assert any("新建人群包「大学生」" in s for s in patch["steps"])
        # 「继续」：接上一条指令，不再反问
        c.post(P + "/agent/chat", json={"text": "继续", "selection": []})
        again = c.get(P + "/canvas").json()["pending_patch"]
        assert again and again["id"] != patch["id"] and again["summary"] == "写剧本"
        assert next(o for o in again["ops"] if o["type"] == "aud")["data"]["audience"] == "大学生"
        # 确认执行：新人群包和剧本都上了画布
        assert c.post(f"{P}/patches/{again['id']}/apply").status_code == 200
        nodes = c.get(P + "/canvas").json()["nodes"]
        assert any(n["type"] == "aud" and n["title"] == "人群包 · 大学生" for n in nodes)
        assert sum(n["type"] == "script" for n in nodes) == 3


def test_history_window(monkeypatch):
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "窗口"}).json()["id"]
        with SessionLocal() as db:
            for k in range(30):
                db.add(ChatMessage(project_id=pid, role="user" if k % 2 == 0 else "agent", content={"text": f"第{k}条 " + "长" * (1500 if k == 27 else 10)}))
            db.add(ChatMessage(project_id=pid, role="user", content={"text": "当前这条"}))
            db.commit()
            h = agent.history(db, pid)
        assert len(h) <= agent.HISTORY_MESSAGES and h[-1]["content"].startswith("第29条") and "当前这条" not in json.dumps(h, ensure_ascii=False)
        assert all(len(x["content"]) <= agent.HISTORY_EACH for x in h) and sum(len(x["content"]) for x in h) <= agent.HISTORY_CHARS
        assert h[-1]["role"] == "assistant" and h[-2]["role"] == "user"

        # 模型路径：历史对话放在当前消息前面一起发给模型
        seen = {}

        async def fake_chat(messages, **kw):
            seen["messages"] = messages
            return {"tool_calls": [{"function": {"name": "summary", "arguments": "{}"}}]}

        monkeypatch.setattr(llm, "chat", fake_chat)
        monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
        c.post(f"/api/v1/projects/{pid}/agent/chat", json={"text": "继续", "selection": []})
        msgs = seen["messages"]
        assert msgs[0]["role"] == "system" and "记忆" in msgs[0]["content"] and msgs[-1] == {"role": "user", "content": "继续"}
        assert any(m["content"].startswith("当前这条") for m in msgs[1:-1])


def test_openrouter_errors_are_readable():
    """OpenRouter 出错时给出原因：余额不够画图（文字调用照常）这种情况最常见。"""
    import httpx
    import pytest
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    body = {"error": {"message": "This request requires at least $1.00 in balance for image or video output", "code": 402}}
    with pytest.raises(RuntimeError, match="生成图片要求账户余额至少 \\$1"):
        llm._check(httpx.Response(402, json=body, request=req))
    with pytest.raises(RuntimeError, match="Key 无效"):
        llm._check(httpx.Response(401, json={"error": {"message": "No auth"}}, request=req))
    llm._check(httpx.Response(200, json={}, request=req))
