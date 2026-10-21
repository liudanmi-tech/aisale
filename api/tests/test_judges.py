"""剧本评审：5 个不同模型 × 5 个维度，中位数 → 加权总分；分歧、合规否决、可拍性封顶、问题合并、失败换备用。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")

import json
import time

from fastapi.testclient import TestClient

from app import judges, settings_store
from app.adapters import llm
from app.db import SessionLocal
from app.main import app
from app.models import LibScript, new_id

W = {"hook": 0.3, "local": 0.25, "selling": 0.2, "feasible": 0.15, "safe": 0.1}


def _r(model, hook, local, selling, feasible, safe, issues=()):
    keys = judges.DIM_KEYS
    return {"model": model, "scores": dict(zip(keys, (hook, local, selling, feasible, safe))), "reasons": {k: f"{model} 的理由" for k in keys},
            "evidence": {}, "issues": list(issues), "highlights": ["钩子好"], "confidence": "high"}


def test_aggregate_median_weights_split_veto():
    rs = [_r("a", 9, 8, 7, 8, 9, [{"shot": 3, "dim": "selling", "problem": "卖点太晚", "fix": "提前到镜 2", "severity": "high"}]),
          _r("b", 8, 8, 7, 8, 9, [{"shot": 3, "dim": "selling", "problem": "卖点出现晚", "fix": "", "severity": "mid"}]),
          _r("c", 8, 2, 7, 8, 9), _r("d", 7, 8, 6, 8, 9), _r("e", 8, 9, 8, 8, 9), {"model": "f", "error": "超时"}]
    a = judges.aggregate(rs, W)
    assert a["dims"]["hook"]["median"] == 8 and a["dims"]["local"]["median"] == 8  # 中位数：一个评委打 2 分带不偏
    assert a["dims"]["local"]["split"] and a["dims"]["local"]["low"]["model"] == "c"  # 分歧大，并给出最低分评委
    assert a["total"] == round((8 * .3 + 8 * .25 + 7 * .2 + 8 * .15 + 9 * .1) * 10) and a["verdict"] == "可以投"
    assert a["issues"][0]["shot"] == 3 and a["issues"][0]["count"] == 2 and a["issues"][0]["severity"] == "high"
    unsafe = [_r(m, 9, 9, 9, 9, 2 if m in "ab" else 9) for m in "abcde"]
    assert judges.aggregate(unsafe, W)["verdict"] == "不能投"  # 2 个评委合规 ≤ 3：一票否决
    hard = [_r(m, 9, 9, 9, 4, 9) for m in "abcde"]
    assert judges.aggregate(hard, W)["verdict"] == "改了再用"  # 可拍性 ≤ 4：封顶
    assert judges.kripp_alpha([[8, 8, 8], [3, 3, 3], [6, 6, 6]]) == 1.0
    assert "镜 3（2 个评委提到）：卖点太晚" in judges.rewrite_comment(a)


def test_run_five_models_with_fallback(monkeypatch):
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    calls = []

    async def fake_chat(messages, model=None, **kw):
        calls.append(model)
        assert "镜 1" in messages[1]["content"] and "哪个模型写的" not in messages[0]["content"]
        if model == "x-ai/grok-4.7":
            raise RuntimeError("模型不可用")
        if model == "qwen/qwen3.8-max-0902":
            return {"content": json.dumps({"scores": {"hook": 7}})}  # 缺维度：不算
        base = {"openai/gpt-6.1-sol": 8, "google/gemini-3.8-flash": 7, "deepseek/deepseek-v4-pro-0813": 8}.get(model, 6)
        return {"content": json.dumps({"scores": {k: base for k in judges.DIM_KEYS}, "reasons": {"hook": "开头好"},
                                       "issues": [{"shot": 1, "dim": "hook", "problem": "再快一点", "fix": "删掉第一句", "severity": "mid"}]})}
    monkeypatch.setattr(llm, "chat", fake_chat)
    with TestClient(app) as c:
        with SessionLocal() as db:
            s = LibScript(id=new_id("ls"), market="尼日利亚", product="TECNO Pova", selling_point="打游戏不卡", audience="学生", title="t",
                          concept={"logline": "x"}, shots=[["0–2s", "特写：手机", "Wahala", "麻烦"], ["2–5s", "中景：两人", "Win am", "赢了"]], status="ok",
                          evaluation={"score": 70})
            db.add(s)
            db.commit()
            sid = s.id
        assert c.post(f"/api/v1/scripts/{sid}/judge").status_code == 200
        for _ in range(200):
            d = c.get(f"/api/v1/scripts/{sid}").json()
            if d["status"] == "ok":
                break
            time.sleep(0.03)
        jd = d["evaluation"]["judges"]
        assert d["evaluation"]["audience"] == {"score": 70}  # 老的 40 人评测挪到 audience 下
        models = [r["model"] for r in jd["results"] if "scores" in r]
        assert len(models) == 5 and sum(1 for r in jd["results"] if r.get("fallback")) == 2  # grok、qwen 失败两次后换备用模型
        assert calls.count("x-ai/grok-4.7") == 2
        assert jd["issues"][0]["shot"] == 1 and jd["issues"][0]["count"] == 5
        # 按评委意见改写：改完自动重评
        seen = {}

        async def fake_json(system, user, **kw):
            seen["user"] = user
            return {"shots": [[2, "特写：手机", "Go!", "走"], [3, "中景：两人", "Win", "赢"], [2, "特写：手机", "TECNO", "TECNO"]]}
        monkeypatch.setattr(llm, "chat_json", fake_json)
        assert c.post(f"/api/v1/scripts/{sid}/rewrite-by-judges").status_code == 200
        for _ in range(200):
            d = c.get(f"/api/v1/scripts/{sid}").json()
            if d["status"] == "ok" and d["evaluation"].get("judges"):
                break
            time.sleep(0.03)
        assert "5 个评委提到" in seen["user"] and d["version"] == 2 and len(d["shots"]) == 3
        assert d["evaluation"]["previous"]["total"] == jd["total"]
