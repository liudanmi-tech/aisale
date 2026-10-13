"""质检：汇总规则 + 成片技术检查（规格、黑帧、冻帧）。"""
import shutil
import subprocess

import pytest

from app import qc


def test_summary_rules():
    spec = {"product": True}
    kf = qc.summarize({"face": {"status": "skip", "reason": "未执行"}, "product": {"status": "fail", "reason": "摄像头模组是三摄，实拍是双摄"}}, spec)
    assert kf["status"] == "fail" and kf["manual_confirm"] and kf["issues"] == ["商品一致：摄像头模组是三摄，实拍是双摄"]
    assert qc.summarize({"face": {"status": "skip", "reason": "x"}}, {})["status"] == "skip"  # 一项没查成不算通过
    clip = qc.summarize({"product": {"status": "pass", "reason": "无"}, "tech": {"status": "warn", "reason": "有黑帧"}}, spec)
    m = qc.merge(kf, clip, spec, {"keyframe": 3, "clip": 1})
    assert m["status"] == "warn" and m["stages"] == {"keyframe": "fail", "clip": "warn"}  # 成片检过的项以成片为准
    rep = qc.video_summary([{"shot": 1, "qc": m}, {"shot": 2, "qc": qc.merge(None, None, {}, {})}])
    assert rep["status"] == "warn" and rep["text"] == "0/1 镜通过 · 1 镜待看" and rep["retried"] == 2 and rep["manual"] == [1]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="没装 ffmpeg")
def test_tech_check(tmp_path):
    good, bad = tmp_path / "good.mp4", tmp_path / "bad.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:d=4:r=24", "-pix_fmt", "yuv420p", str(good)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=640x360:d=3:r=24", "-pix_fmt", "yuv420p", str(bad)], check=True)
    g = qc.tech_check(good)
    assert g["status"] == "pass" and g["width"] == 360 and g["duration"] == 4.0, g
    b = qc.tech_check(bad)
    assert b["status"] == "fail" and "不是 9:16" in b["reason"] and "黑帧" in b["reason"] and "冻结" in b["reason"], b
    assert len(qc.sample_frames(good)) == 3
