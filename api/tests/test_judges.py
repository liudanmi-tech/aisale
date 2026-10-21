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


def test_improve_round_accept_reject_stall_adopt(monkeypatch):
    """自动改进一轮：A/B/C 三个版本和原版同轮打分；高 3 分以上才采用；连续 2 轮没进步提示换创意；可以手动采用任一版。"""
    from app import improve
    monkeypatch.setattr(settings_store, "llm_enabled", lambda: True)
    boost = {"v": 3}

    async def fake_chat(messages, model=None, **kw):
        text = messages[1]["content"]
        base = 6 + (boost["v"] if "BOOM" in text else 0) + (1 if "TWEAK" in text else 0)
        return {"content": json.dumps({"scores": {k: min(10, base) for k in judges.DIM_KEYS}, "reasons": {"hook": "x"},
                                       "issues": [{"shot": 1, "dim": "hook", "problem": "钩子弱", "fix": "加异常画面", "severity": "high"}]})}
    seen = []

    async def fake_json(system, user, **kw):
        seen.append(user)
        tag = "BOOM" if "重写结构" in user else "TWEAK"
        return {"shots": [[2, f"特写：{tag} 手机", "Go", "走"], [3, "中景：两人", "Win", "赢"], [2, "特写：手机", "TECNO", "TECNO"]]}
    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(llm, "chat_json", fake_json)
    with TestClient(app) as c:
        with SessionLocal() as db:
            s = LibScript(id=new_id("ls"), market="尼日利亚", product="TECNO Pova", selling_point="打游戏不卡", audience="学生", title="t",
                          concept={"logline": "停电打游戏", "trend": "NEPA"}, shots=[["0–2s", "特写：手机", "a", "a"], ["2–5s", "中景：两人", "b", "b"]], status="ok")
            db.add(s)
            db.commit()
            sid = s.id

        def go():
            assert c.post(f"/api/v1/scripts/{sid}/improve").status_code == 200
            for _ in range(300):
                d = c.get(f"/api/v1/scripts/{sid}").json()
                if d["status"] == "ok":
                    return d
                time.sleep(0.03)
        d = go()
        r = d["evaluation"]["rounds"][-1]
        assert [x["label"] for x in r["candidates"]] == ["原版", "攻短板", "改共识问题", "重写结构"]
        assert any("攻短板" in u for u in seen) and any("重写结构" in u and "停电打游戏" in u for u in seen)  # C 版保留创意核心
        assert r["accepted"] and r["winner"] == "重写结构" and r["gain"] == 30 and d["version"] == 2 and "BOOM" in d["shots"][0][1]
        assert r["candidates"][3]["prefer"] == 5 and r["candidates"][3]["paired"] == 5  # 5 个评委都给新版打了更高分
        assert [h["how"] for h in d["evaluation"]["history"]][-1] == "自动改进：重写结构"
        # 现在的剧本已经是 BOOM 版：新版本都不比它高 3 分 → 不采用、保留原版
        d = go()
        assert not d["evaluation"]["rounds"][-1]["accepted"] and d["version"] == 2 and "保留原版" in d["error"]
        d = go()
        assert d["evaluation"]["rounds"][-1]["stall"] == 2 and "换一个备选创意" in d["error"]
        # 手动采用上一轮的「攻短板」
        assert c.post(f"/api/v1/scripts/{sid}/adopt", json={"round": len(d["evaluation"]["rounds"]) - 1, "candidate": 1}).status_code == 200
        d = c.get(f"/api/v1/scripts/{sid}").json()
        assert d["version"] == 3 and "TWEAK" in d["shots"][0][1] and d["evaluation"]["judges"]["total"] > 0


def test_paired_rule_rejects_one_judge_swing():
    """总分高了但只有 1 个评委更喜欢（其他人没变）：算波动，不采用。"""
    from app import improve
    base = {"results": [_r(m, 7, 7, 7, 7, 7) for m in "abcde"]}
    new = {"results": [_r("a", 10, 10, 10, 10, 10)] + [_r(m, 7, 7, 7, 7, 7) for m in "bcde"]}
    assert improve._paired(base, new, W) == (1, 5)
