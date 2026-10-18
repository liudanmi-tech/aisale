"""成片：每镜可以调剪哪一段（开始点、时长、整段），默认按剧本时长从头剪。"""
from types import SimpleNamespace

from app import compose, production


def test_plan_trims():
    script = SimpleNamespace(data={"shots": [["0–1.5s", "a", "hi", ""], ["1.5–3.5s", "b", "", ""]], "cast": {"specs": []}})
    video = SimpleNamespace(data={"tasks": [{"url": "https://v/1.mp4"}, {"url": "https://v/2.mp4"}]})
    p = compose.plan(video, script)
    assert [(x["start"], x["dur"], x["full"]) for x in p] == [(0, 1.5, False), (0, 2.0, False)]
    p = compose.plan(video, script, {"1": {"start": 1.2, "dur": 2.5}, "2": {"start": 0, "dur": None}})
    assert (p[0]["start"], p[0]["dur"], p[0]["full"]) == (1.2, 2.5, False) and p[1]["full"] and p[0]["trimmed"]


def test_short_shot_prompt_asks_for_fast_action():
    plan = production.clip_plan(["0–1.5s", "铲斗倒水"], {"size": "MS"}, {"product": None}, "/k.png", None)
    assert "within the first 1.5 seconds" in plan["prompt"]
    assert "Timing" not in production.clip_plan(["0–5s", "x"], {}, {"product": None}, "/k.png", None)["prompt"]
