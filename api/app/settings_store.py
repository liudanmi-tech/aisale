"""平台设置：在「设置」页填写的密钥（加密存储）与按任务选择的模型。

密钥优先读数据库（设置页填写），其次读环境变量（FAL_KEY / OPENROUTER_API_KEY）。
加密主密钥来自环境变量 APP_SECRET；未设置时在 api/.app_secret 自动生成（生产环境务必配置 APP_SECRET）。
"""
import base64
import hashlib
import os
import secrets as pysecrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.db import SessionLocal
from app.models import Secret, Setting

SECRET_NAMES = {"fal": "FAL_KEY", "openrouter": "OPENROUTER_API_KEY"}

LLM_MODELS = [
    {"id": "google/gemini-2.5-flash", "label": "Gemini 2.5 Flash", "hint": "快、便宜，支持工具调用与视频理解"},
    {"id": "google/gemini-2.5-pro", "label": "Gemini 2.5 Pro", "hint": "更强的推理与多模态理解"},
    {"id": "anthropic/claude-sonnet-5.5", "label": "Claude Sonnet 5.5", "hint": "写作与本地口语更自然"},
    {"id": "anthropic/claude-haiku-5.5", "label": "Claude Haiku 5.5", "hint": "快、便宜"},
    {"id": "openai/gpt-4.1-mini", "label": "GPT-4.1 mini", "hint": "通用、便宜"},
]
VIDEO_MODELS = [
    {"id": "bytedance/seedance-2.5/text-to-video", "label": "Seedance 2.5", "hint": "最新版，最高 720p，4–30 秒"},
    {"id": "fal-ai/bytedance/seedance/v1.5/pro/text-to-video", "label": "Seedance 1.5 Pro", "hint": "带同步音频，最高 720p"},
    {"id": "fal-ai/bytedance/seedance/v1/pro/text-to-video", "label": "Seedance 1.0 Pro", "hint": "最高 1080p，2–12 秒"},
    {"id": "fal-ai/bytedance/seedance/v1/pro/fast/text-to-video", "label": "Seedance 1.0 Pro Fast", "hint": "更快更便宜"},
]
DEFAULT_MODELS = {
    "agent": "google/gemini-2.5-flash",  # 理解指令 → 画布工具调用，要快
    "script": "anthropic/claude-sonnet-5.5",  # 剧本与皮钦语 / 乌尔都语口播，要自然
    "eval": "google/gemini-2.5-flash",  # 40 人评测输出大段 JSON，要便宜
    "video": "bytedance/seedance-2.5/text-to-video",
    "video_resolution": "720p",
}


def _fernet() -> Fernet:
    raw = os.getenv("APP_SECRET")
    if not raw:
        f = Path(__file__).resolve().parents[1] / ".app_secret"
        if not f.exists():
            f.write_text(pysecrets.token_urlsafe(32))
            f.chmod(0o600)
        raw = f.read_text().strip()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()))


def set_secret(name: str, value: str) -> None:
    with SessionLocal() as db:
        s = db.get(Secret, name) or Secret(name=name, ciphertext="", last4="")
        s.ciphertext = _fernet().encrypt(value.encode()).decode()
        s.last4 = value[-4:]
        db.merge(s)
        db.commit()


def delete_secret(name: str) -> None:
    with SessionLocal() as db:
        s = db.get(Secret, name)
        if s:
            db.delete(s)
            db.commit()


def get_secret(name: str) -> str:
    with SessionLocal() as db:
        s = db.get(Secret, name)
        if s:
            try:
                return _fernet().decrypt(s.ciphertext.encode()).decode()
            except InvalidToken:
                return ""
    return os.getenv(SECRET_NAMES[name], "")


def secret_status(name: str) -> dict:
    with SessionLocal() as db:
        s = db.get(Secret, name)
        if s:
            return {"configured": True, "source": "settings", "masked": f"••••{s.last4}", "updated_at": s.updated_at.isoformat()}
    env = os.getenv(SECRET_NAMES[name], "")
    return {"configured": bool(env), "source": "env" if env else None, "masked": f"••••{env[-4:]}" if env else None, "updated_at": None}


def get_models() -> dict:
    with SessionLocal() as db:
        s = db.get(Setting, "models")
        return {**DEFAULT_MODELS, **((s.value if s else {}) or {})}


def set_models(values: dict) -> dict:
    allowed = {k: v for k, v in values.items() if k in DEFAULT_MODELS and isinstance(v, str) and v.strip()}
    with SessionLocal() as db:
        s = db.get(Setting, "models") or Setting(key="models", value={})
        s.value = {**(s.value or {}), **allowed}
        db.merge(s)
        db.commit()
    return get_models()


def llm_enabled() -> bool:
    from app import config
    return config.LLM_ENABLED or bool(get_secret("openrouter"))


def video_provider() -> str:
    """fal：填了 fal Key；byteplus：环境变量指定直连 BytePlus；否则 mock。"""
    from app import config
    if get_secret("fal"):
        return "fal"
    if config.SEEDANCE_MODE == "real":
        return "byteplus"
    return "mock"
