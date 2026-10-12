"""设置：第三方密钥（加密存储，只回显末 4 位）与按任务选择的模型。

公网部署时设置环境变量 ADMIN_TOKEN，修改密钥 / 模型需在请求头 X-Admin-Token 带上它。
"""
import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import canvas, config, settings_store
from app.adapters import fal, llm
from app.db import get_db

router = APIRouter(prefix="/api/v1/settings")
NAMES = {"fal": "fal.ai（视频生成）", "openrouter": "OpenRouter（大模型）"}


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("ADMIN_TOKEN")
    if expected and not (x_admin_token and hmac.compare_digest(x_admin_token, expected)):
        raise HTTPException(401, "需要管理员口令")


@router.get("")
def get_settings():
    vp = settings_store.video_provider()
    return {
        "admin_required": bool(os.getenv("ADMIN_TOKEN")),
        "secrets": {k: {"label": v, **settings_store.secret_status(k)} for k, v in NAMES.items()},
        "models": settings_store.get_models(),
        "catalog": {"llm": settings_store.LLM_MODELS, "video": settings_store.VIDEO_MODELS, "resolutions": ["480p", "720p", "1080p"]},
        "integrations": [
            {"name": "视频生成", "mode": {"fal": "fal.ai 真实调用", "byteplus": "BytePlus 直连", "mock": "模拟"}[vp], "ready": vp != "mock"},
            {"name": "大模型（Agent / 剧本 / 评测）", "mode": "OpenRouter 真实调用" if settings_store.llm_enabled() else "规则与模板", "ready": settings_store.llm_enabled()},
            {"name": "TikTok Marketing API", "mode": "真实调用" if config.TIKTOK_MODE == "real" else "模拟", "ready": bool(config.TIKTOK_ACCESS_TOKEN)},
            {"name": "第三方广告情报", "mode": "样例数据", "ready": False},
            {"name": "Meta / X", "mode": "二期", "ready": False},
        ],
    }


class SecretIn(BaseModel):
    value: str


def _check_name(name: str) -> None:
    if name not in NAMES:
        raise HTTPException(404, "unknown secret")


@router.put("/secrets/{name}", dependencies=[Depends(require_admin)])
def put_secret(name: str, body: SecretIn, db: Session = Depends(get_db)):
    _check_name(name)
    v = body.value.strip()
    if len(v) < 8 or any(c.isspace() for c in v):
        raise HTTPException(400, "Key 格式不正确")
    settings_store.set_secret(name, v)
    canvas.audit(db, "-", "user", "set_secret", {"name": name, "last4": v[-4:]})
    db.commit()
    return settings_store.secret_status(name)


@router.delete("/secrets/{name}", dependencies=[Depends(require_admin)])
def delete_secret(name: str, db: Session = Depends(get_db)):
    _check_name(name)
    settings_store.delete_secret(name)
    canvas.audit(db, "-", "user", "delete_secret", {"name": name})
    db.commit()
    return settings_store.secret_status(name)


class TestIn(BaseModel):
    value: str | None = None


@router.post("/secrets/{name}/test", dependencies=[Depends(require_admin)])
async def test_secret(name: str, body: TestIn):
    """校验 Key 是否可用，不产生调用费用；不传 value 时校验已保存的 Key。"""
    _check_name(name)
    key = (body.value or "").strip() or settings_store.get_secret(name)
    if not key:
        return {"ok": False, "message": "还没有填写 Key"}
    try:
        ok, msg = await (fal.check_key(key) if name == "fal" else llm.check_key(key))
    except Exception as e:
        ok, msg = False, f"连接失败：{type(e).__name__}"
    return {"ok": ok, "message": msg}


@router.put("/models", dependencies=[Depends(require_admin)])
def put_models(body: dict, db: Session = Depends(get_db)):
    res = settings_store.set_models(body)
    canvas.audit(db, "-", "user", "set_models", body)
    db.commit()
    return res
