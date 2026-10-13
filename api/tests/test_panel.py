"""40 个独立评测 Agent：模型只给逐镜相对评分，按基准概率抽样；同一条视频结果可复现。"""
import asyncio
import json

import httpx

from app import panel
from app.adapters import llm
from app.workflows import _personas

SHOTS = [["0–3s", "停电夜市", "Light don cut!", ""], ["3–7s", "收款", "No charger.", ""], ["7–11s", "产品特写", "6000mAh", ""], ["11–15s", "CTA", "Buy am", ""]]


def run(rel: int, seed: str = "v1") -> dict:
    def handler(req: httpx.Request) -> httpx.Response:
        out = {"watch": [{"shot": k + 1, "vs_usual": rel, "thought": f"镜{k + 1}"} for k in range(4)], "click_vs_usual": rel,
               "comment": "ok", "scores": {d: 5 + rel for d in panel.DIMS}}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}]})
    llm.transport = httpx.MockTransport(handler)
    try:
        personas = _personas("尼日利亚", ["小商贩", "学生"])
        return asyncio.run(panel.run(personas, SHOTS, [], [{}] * 40, seed=seed))
    finally:
        llm.transport = None


def test_panel_uses_base_rates():
    bad, usual, good = run(-2), run(0), run(2)
    done = lambda r: sum(x["completed"] for x in r["reactions"])  # noqa: E731
    clicks = lambda r: sum(x["clicked"] for x in r["reactions"])  # noqa: E731
    assert done(bad) <= 2 and done(bad) < done(usual) < done(good)  # 都说「差不多」时只有少数人看完
    assert done(usual) <= 15 and clicks(usual) <= 3 and clicks(good) >= clicks(usual)
    assert usual["retention"][0] == 100 and usual["retention"][1] < 60  # 前 3 秒流失一半以上
    assert usual["scores"]["hook"] == 5 and good["shot_rel"] == [2, 2, 2, 2] and usual["agents"] == 40
    assert run(0)["reactions"] == usual["reactions"] and run(0, seed="v2")["reactions"] != usual["reactions"]  # 同一视频可复现
