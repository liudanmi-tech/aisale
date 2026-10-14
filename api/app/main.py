import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import agent, canvas, config, monitor, settings_store, workflows
from app.db import Base, SessionLocal, engine
from app.events import set_loop
from app.routers import monitor as monitor_router
from app.routers import library, ops, projects, settings
from app.seed import seed


@asynccontextmanager
async def lifespan(_: FastAPI):
    set_loop(asyncio.get_running_loop())
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        canvas.migrate_layouts(db)
        canvas.recover_interrupted(db)
        cuts = agent.backfill_cuts(db)
    settings_store.migrate_models()
    workflows.run([(c, "compose") for c in cuts])
    task = asyncio.create_task(monitor.scheduler())
    yield
    task.cancel()


app = FastAPI(title="AIGC 投放平台 API", version="0.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(projects.router)
app.include_router(ops.router)
app.include_router(settings.router)
app.include_router(library.router)
app.include_router(monitor_router.router)


@app.get("/api/health")
def health():
    return {"ok": True}


config.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/v1/media", StaticFiles(directory=config.MEDIA_DIR), name="media")

# 生产部署时由 API 直接托管前端构建产物（web/dist），单容器即可运行
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
WEB_SRC = Path(__file__).resolve().parents[2] / "web"


API_SRC = Path(__file__).resolve().parent


def _newest(root: Path, pattern: str) -> float:
    return max((p.stat().st_mtime for p in root.rglob(pattern) if p.is_file()), default=0)


STARTED_CODE = _newest(API_SRC, "*.py")  # 启动时后端代码的最新修改时间


@app.get("/api/v1/build-status")
def build_status():
    """前端打包产物是不是比前端源码旧（拉了新代码没重新 npm run build）；后端是不是还在跑旧代码（拉了新代码没重启）。"""
    backend = _newest(API_SRC, "*.py") > STARTED_CODE + 1
    index = WEB_DIST / "index.html"
    if not index.exists() or not (WEB_SRC / "src").exists():
        return {"stale": False, "backend_stale": backend}
    files = [p for p in (WEB_SRC / "src").rglob("*") if p.is_file()] + [WEB_SRC / "index.html", WEB_SRC / "package.json"]
    newest = max((p.stat().st_mtime for p in files if p.exists()), default=0)
    return {"stale": newest > index.stat().st_mtime + 1, "backend_stale": backend}

if WEB_DIST.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIST / "static"), name="static")

    @app.get("/{path:path}")
    def spa(path: str):
        f = WEB_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        # index.html 不缓存，发版后浏览器总能拿到新的文件清单
        return FileResponse(WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"})
