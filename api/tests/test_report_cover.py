"""竞品报告：封面以本地缓存为准（报告里存的 TikTok 链接会过期）。"""
from fastapi.testclient import TestClient

from app import config, monitor
from app.db import SessionLocal
from app.main import app
from app.models import Report, SourceVideo, WatchAccount, new_id


def test_report_uses_cached_cover(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path)
    spawned = []
    monkeypatch.setattr("app.routers.monitor.spawn", lambda co: (spawned.append(co), co.close()))
    with TestClient(app) as c:
        with SessionLocal() as db:
            a = WatchAccount(id=new_id("wa"), handle="rc_" + new_id("x"), market="尼日利亚")
            v1 = SourceVideo(id=new_id("sv"), external_id="e1_" + new_id("x"), account_id=a.id, cover="https://cdn/expired1.jpg")
            v2 = SourceVideo(id=new_id("sv"), external_id="e2_" + new_id("x"), account_id=a.id, cover="https://cdn/expired2.jpg")
            r = Report(id=new_id("rp"), status="done", data={"videos": [{"id": v1.id, "cover": v1.cover}, {"id": v2.id, "cover": v2.cover}]})
            db.add_all([a, v1, v2, r])
            db.commit()
            f = monitor._cover_file(v1.external_id)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"\xff\xd8jpg")
            rid, e1 = r.id, v1.external_id
        vs = c.get(f"/api/v1/watch/reports/{rid}").json()["data"]["videos"]
        assert vs[0]["cover"] == f"/api/v1/media/covers/{e1}.jpg" and vs[1]["cover"] == "https://cdn/expired2.jpg"
        assert len(spawned) == 1  # 没缓存的那张后台补下载
