"""关键帧照草图：A 构图锁 + 景别跟原片；B 换真机只改手机那块；C 构图比对进质检、候选按它排。"""
import asyncio
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app import config, production, qc, settings_store  # noqa: E402
from app.adapters import llm  # noqa: E402


def test_prompt_locks_composition_and_size_follows_original():
    p = production.keyframe_prompt(["0–2s", "两人站在铲车前", "hi", ""], {"size": "CU", "roles": ["r1"]}, "尼日利亚", sketch=True)
    assert "照第 1 张参考图（分镜草图）" in p and "镜头：特写" not in p
    assert "镜头：特写" in production.keyframe_prompt(["0–2s", "x", "", ""], {"size": "CU"}, "尼日利亚")
    data = {"wash": {"tier": "high", "map": [{"ref": 1}], "ref": [{"camera": "中景、正面平视、固定"}]}}
    assert production._size_from_ref(data, 0, {"size": "CU"}) == {"size": "MS", "size_from": "原片"}
    low = {"wash": {**data["wash"], "tier": "low"}}
    assert production._size_from_ref(low, 0, {"size": "CU"}) == {"size": "CU"}  # 低档：构图可以改，不跟原片


def test_composition_check_and_ranking(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    (tmp_path / "x").mkdir()
    for n in ("a.png", "b.png"):
        cv2.imwrite(str(tmp_path / "x" / n), np.zeros((64, 36, 3), np.uint8))

    async def fake_chat(messages, **kw):
        return {"content": json.dumps({"score": 3, "diffs": ["草图是两人全身中景，关键帧是手机特写"]}, ensure_ascii=False)}
    monkeypatch.setattr(llm, "chat", fake_chat)
    r = asyncio.run(qc.composition_check("/api/v1/media/x/a.png", "/api/v1/media/x/b.png"))
    assert r["status"] == "fail" and r["score"] == 3 and "手机特写" in r["reason"]
    assert production.fail_kind("关键帧质检：构图与草图一致：3/10：草图是中景，关键帧是手机特写") == "构图不一致"
    cands = [{"qc": {"status": "warn", "issues": ["x"], "checks": {"composition": {"score": 5}}}, "url": "a"},
             {"qc": {"status": "warn", "issues": ["x"], "checks": {"composition": {"score": 8}}}, "url": "b"}]
    assert production._best(cands)["url"] == "b"  # 同级时选更像草图的


def test_place_product_only_changes_phone_area(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    (tmp_path / "keyframes").mkdir()
    base = np.full((400, 225, 3), (30, 120, 200), np.uint8)
    edited = np.full((400, 225, 3), (0, 0, 255), np.uint8)  # 编辑模型把整张图都改了（包括人物姿势）
    cv2.imwrite(str(tmp_path / "keyframes" / "base.png"), base)
    cv2.imwrite(str(tmp_path / "keyframes" / "edit.png"), edited)

    async def fake_box(path, ref=None):
        return [450, 400, 550, 600]  # 手机在画面中间一小块
    monkeypatch.setattr(qc, "phone_box", fake_box)
    out = asyncio.run(production._keep_outside_phone("v", 0, "/api/v1/media/keyframes/base.png", "/api/v1/media/keyframes/edit.png"))
    img = cv2.imread(str(tmp_path / "keyframes" / out.rsplit("/", 1)[1]))
    assert (img[:100] == base[:100]).all() and (img[330:] == base[330:]).all()  # 手机以外原样
    assert img[200, 112, 2] > 230  # 手机那块换成了编辑后的

    async def no_box(path, ref=None):
        return None
    monkeypatch.setattr(qc, "phone_box", no_box)
    assert asyncio.run(production._keep_outside_phone("v", 0, "/api/v1/media/keyframes/base.png", "/api/v1/media/keyframes/edit.png")) is None
