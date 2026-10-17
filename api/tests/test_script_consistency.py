"""剧本和分镜、关键帧不打架：一镜一个景别；特写不拼两张脸；草图里的手机只是占位。"""
from app import production, wash


def test_split_cuts():
    shots = [["0–2s", "中景：两人站在铲车前", "Watch!", "看"],
             ["2–6s", "特写：两部 Camon 并排举在水流里，随后切中景固定：两人并肩站定，睡衣湿透", "No wahala", "没问题"],
             ["6–8s", "特写：手机", "", ""]]
    out, m, prod = wash.split_cuts(shots, [{"ref": 1}, {"ref": 2, "changed": "换"}, {"ref": 3}], [1, 2])
    assert [s[0] for s in out] == ["0–2s", "2–4s", "4–6s", "6–8s"]
    assert out[1][1] == "特写：两部 Camon 并排举在水流里" and out[1][2] == "No wahala"
    assert out[2][1].startswith("中景固定") and out[2][2] == ""
    assert [x.get("ref") for x in m] == [1, 2, 2, 3] and "拆成两镜" in m[2]["changed"]
    assert prod == [1, 3]
    assert wash.split_cuts(shots[:1])[0] == shots[:1]  # 没有「随后切」的不动


def test_closeup_prompt_and_refs():
    spec = {"size": "CU", "roles": ["a", "b"], "move": "固定"}
    p = production.keyframe_prompt(["0–2s", "特写：两人举着手机"], spec, "Nigeria")
    assert "画中画" in p and "最多拍清一个人的脸" in p
    p = production.keyframe_prompt(["0–2s", "中景：两人"], {**spec, "size": "MS"}, "Nigeria")
    assert "画中画" not in p
    assert "placeholders" in production.COMPOSITION_LOCK and "follow the sketch" in production.COMPOSITION_LOCK
