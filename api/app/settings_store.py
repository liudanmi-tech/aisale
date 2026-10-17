"""平台设置：在「设置」页填写的密钥（加密存储）与按任务选择的模型。

密钥优先读数据库（设置页填写），其次读环境变量（FAL_KEY / OPENROUTER_API_KEY / APIFY_TOKEN）。
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

SECRET_NAMES = {"fal": "FAL_KEY", "openrouter": "OPENROUTER_API_KEY", "apify": "APIFY_TOKEN"}

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
IMAGE_MODELS = [
    {"id": "google/gemini-3.1-flash-lite-image", "label": "Gemini 3.1 Flash Lite Image", "hint": "最像手绘分镜，约 3 秒、$0.034 / 张（默认）"},
    {"id": "google/gemini-2.5-flash-image", "label": "Gemini 2.5 Flash Image", "hint": "约 6 秒、$0.039 / 张"},
    {"id": "google/gemini-3.1-flash-image", "label": "Gemini 3.1 Flash Image", "hint": "更精细，约 10 秒、$0.067 / 张"},
    {"id": "google/gemini-3-pro-image", "label": "Gemini 3 Pro Image", "hint": "最精细、最贵"},
]
VIDEO_I2V_MODELS = [
    {"id": "bytedance/seedance-2.5/image-to-video", "label": "Seedance 2.5 图生视频", "hint": "按关键帧生成，最高 1080p，4–30 秒（默认）"},
    {"id": "bytedance/seedance-2.0/image-to-video", "label": "Seedance 2.0 图生视频", "hint": "2.5 拒收（如含真人脸）时自动退回用它"},
    {"id": "fal-ai/bytedance/seedance/v1/pro/image-to-video", "label": "Seedance 1.0 Pro 图生视频", "hint": "按关键帧生成，最高 1080p，更便宜"},
    {"id": "fal-ai/bytedance/seedance/v1/lite/image-to-video", "label": "Seedance 1.0 Lite 图生视频", "hint": "更快更便宜"},
]
VIDEO_REF_MODELS = [
    {"id": "bytedance/seedance-2.5/reference-to-video", "label": "Seedance 2.5 全能参考", "hint": "最多 30 张参考图，商品镜头全程看着商品图生成（默认）"},
    {"id": "bytedance/seedance-2.0/reference-to-video", "label": "Seedance 2.0 全能参考", "hint": "最多 9 张参考图"},
]
DEFAULT_MODELS = {
    "agent": "google/gemini-2.5-flash",  # 理解指令 → 画布工具调用，要快
    "script": "anthropic/claude-sonnet-5.5",  # 剧本与皮钦语 / 乌尔都语口播，要自然
    "eval": "google/gemini-2.5-flash",  # 40 个独立评测 Agent，每人一次调用、看关键帧，要便宜且能看图
    "video": "bytedance/seedance-2.5/text-to-video",
    "video_resolution": "720p",
    "analysis": "google/gemini-2.5-flash",  # 竞品视频逐条拆解（看封面 + 文案 + 字幕），量大要便宜、能看图
    "report": "anthropic/claude-sonnet-5.5",  # 汇总成分析报告，要会写洞察
    "storyboard": "google/gemini-3.1-flash-lite-image",  # 剧本分镜图（电影学院简笔分镜风格）
    "keyframe": "google/gemini-3.1-flash-image",  # 演员定妆照、场景图、每镜关键帧（真实质感，要能参考多张图）
    "qc": "google/gemini-2.5-flash",  # 质检：看关键帧和成片抽帧，对照定妆照和商品实拍图逐项检查
    "video_i2v": "bytedance/seedance-2.5/image-to-video",  # 关键帧 → 视频（图生视频，没有商品的镜头）
    "video_ref": "bytedance/seedance-2.5/reference-to-video",  # 商品镜头：关键帧 + 商品多视角图一起作参考，全程保持商品外观
    "tiktok_actor": "clockworks~tiktok-scraper",  # Apify 上抓 TikTok 账号视频的 Actor
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
        return {**DEFAULT_MODELS, **{k: v for k, v in ((s.value if s else {}) or {}).items() if not k.startswith("_")}}


def migrate_models() -> None:
    """一次性迁移：图生视频默认改成 Seedance 2.5。设置页「保存」会把当时的默认值写进库，所以旧的 1.0 设置要在这里改掉。"""
    with SessionLocal() as db:
        s = db.get(Setting, "models")
        if not s or (s.value or {}).get("_seedance25"):
            return
        v = dict(s.value or {})
        if "seedance/v1" in (v.get("video_i2v") or ""):
            v["video_i2v"] = DEFAULT_MODELS["video_i2v"]
        v["_seedance25"] = True
        s.value = v
        db.commit()


def set_models(values: dict) -> dict:
    allowed = {k: v for k, v in values.items() if k in DEFAULT_MODELS and isinstance(v, str) and v.strip()}
    with SessionLocal() as db:
        s = db.get(Setting, "models") or Setting(key="models", value={})
        s.value = {**(s.value or {}), **allowed}
        db.merge(s)
        db.commit()
    return get_models()


# 质检不合格时自动重做的次数。视频按条计费，默认不自动重做视频，只标红交给人决定
# kf_candidates：每轮同时画几张关键帧候选（挑最好的，其余留着可换）；kf_gate：整条生成先停在关键帧，人确认后再生成视频
RETRY_DEFAULTS = {"keyframe": 2, "clip": 0, "kf_candidates": 2, "kf_gate": 1}
RETRY_LIMITS = {"keyframe": 2, "clip": 1, "kf_candidates": 3, "kf_gate": 1}
RETRY_MIN = {"kf_candidates": 1}


def get_retries() -> dict:
    with SessionLocal() as db:
        s = db.get(Setting, "retries")
        return {**RETRY_DEFAULTS, **((s.value if s else {}) or {})}


def set_retries(values: dict) -> dict:
    ok = {k: max(RETRY_MIN.get(k, 0), min(RETRY_LIMITS[k], int(v))) for k, v in values.items() if k in RETRY_LIMITS and str(v).lstrip("-").isdigit()}
    with SessionLocal() as db:
        s = db.get(Setting, "retries") or Setting(key="retries", value={})
        s.value = {**(s.value or {}), **ok}
        db.merge(s)
        db.commit()
    return get_retries()


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
