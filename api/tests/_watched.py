"""测试用：把爆款库里的爆款都标成「已经看过视频」（多模态拆解好了），洗稿方案就不会停下来要视频。"""
from app.db import SessionLocal
from app.models import RefAd

BREAKDOWN = {"shots": [{"t": "0–3s", "scene": "夜市", "action": "停电", "line": "Light don cut!"}, {"t": "3–7s", "scene": "摊位", "action": "收款"},
                       {"t": "7–11s", "scene": "台面", "action": "手机特写", "product": True}, {"t": "11–15s", "scene": "门店", "action": "号召"}],
             "video_duration": 15, "selling_point": "续航"}


def watch_all_ads() -> None:
    with SessionLocal() as db:
        for a in db.query(RefAd):
            if not (a.dna or {}).get("breakdown"):
                a.dna = {**(a.dna or {}), "breakdown": BREAKDOWN, "breakdown_status": "done"}
        db.commit()
