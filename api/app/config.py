import os
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.lower() in ("1", "true", "yes")


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./aigc.db")

# 外部服务模式：mock 为模拟适配器，real 为真实调用（需配置对应 Key）
SEEDANCE_MODE = os.getenv("SEEDANCE_MODE", "mock")
SEEDANCE_BASE_URL = os.getenv("SEEDANCE_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3")
SEEDANCE_API_KEY = os.getenv("SEEDANCE_API_KEY", "")
SEEDANCE_MODEL = os.getenv("SEEDANCE_MODEL", "")

TIKTOK_MODE = os.getenv("TIKTOK_MODE", "mock")
TIKTOK_BASE_URL = os.getenv("TIKTOK_BASE_URL", "https://business-api.tiktok.com/open_api/v1.3")
TIKTOK_ACCESS_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN", "")
TIKTOK_ADVERTISER_ID = os.getenv("TIKTOK_ADVERTISER_ID", "")

INTEL_MODE = os.getenv("INTEL_MODE", "mock")

# 大模型：用于 Agent 意图理解与剧本生成；关闭时使用规则解析与模板
LLM_ENABLED = _bool("LLM_ENABLED", False)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-2.5-flash")

# 演示节奏：每个生成步骤的模拟耗时（秒），测试时设为 0
STEP_DELAY = float(os.getenv("STEP_DELAY", "1.0"))

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# 本地媒体（竞品视频封面等）：TikTok 封面链接几天后失效，同步时存一份
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", Path(__file__).resolve().parents[1] / "media"))
