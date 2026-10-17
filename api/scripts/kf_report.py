"""打印最近一条视频每一镜关键帧的质检原因（排查「为什么都没过」用）。
用法：python3 scripts/kf_report.py [视频编号]
"""
import json
import sqlite3
import sys
from pathlib import Path

db = sqlite3.connect(Path(__file__).resolve().parent.parent / "aigc.db")
no = sys.argv[1] if len(sys.argv) > 1 else None
q = "select no, data from node where type='video'" + (" and no=?" if no else "") + " order by created_at desc limit 1"
row = db.execute(q, (int(no),) if no else ()).fetchone()
if not row:
    sys.exit("没找到视频节点")
print(f"视频 #{row[0]}")
for i, t in enumerate(json.loads(row[1]).get("tasks") or []):
    t = t or {}
    meta = t.get("kf_meta") or {}
    print(f"\n=== 镜 {i + 1}  {t.get('phase') or ''}  方式={meta.get('mode') or '-'}")
    for k, c in ((t.get("qc") or {}).get("checks") or {}).items():
        if c.get("status") != "pass":
            print(f"  [当前图] {k} {c.get('status')}: {str(c.get('reason') or '')[:150]}")
    for n, c in enumerate(t.get("kf_candidates") or []):
        print(f"  候选{n + 1} {c.get('status')}: {' | '.join(c.get('issues') or [])[:300]}")
    for f in ((t.get("stats") or {}).get("fails") or [])[-8:]:
        print(f"  失败记录 [{f.get('kind')}] {f.get('reason')}")
    if t.get("keyframe_error"):
        print(f"  关键帧错误: {t['keyframe_error']}")
