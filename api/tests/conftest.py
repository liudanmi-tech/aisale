import pytest


@pytest.fixture(autouse=True)
def _gate_follows_setting(monkeypatch):
    """老流程的测试用设置项 kf_gate=0 走「画完直接生成视频」；产品里关键帧确认始终开着（FORCE_GATE）。"""
    from app import production
    monkeypatch.setattr(production, "FORCE_GATE", False)
