import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config, monitor
from app.db import Base, SessionLocal, engine
from app.events import set_loop
from app.routers import monitor as monitor_router
from app.routers import ops, projects, settings
from app.seed import seed


@asynccontextmanager
async def lifespan(_: FastAPI):
    set_loop(asyncio.get_running_loop())
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    task = asyncio.create_task(monitor.scheduler())
    yield
    task.cancel()


app = FastAPI(title="AIGC 投放平台 API", version="0.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(projects.router)
app.include_router(ops.router)
app.include_router(settings.router)
app.include_router(monitor_router.router)


@app.get("/api/health")
def health():
    return {"ok": True}


config.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/v1/media", StaticFiles(directory=config.MEDIA_DIR), name="media")

# 生产部署时由 API 直接托管前端构建产物（web/dist），单容器即可运行
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
if WEB_DIST.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIST / "static"), name="static")

    @app.get("/{path:path}")
    def spa(path: str):
        f = WEB_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        # index.html 不缓存，发版后浏览器总能拿到新的文件清单
        return FileResponse(WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"})
