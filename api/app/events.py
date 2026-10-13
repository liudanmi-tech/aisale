"""项目级实时事件：节点状态、画布变化、审核、对话，经 WebSocket 推给前端。"""
import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

log = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self.clients: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, project_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self.clients[project_id].add(ws)

    def disconnect(self, project_id: str, ws: WebSocket) -> None:
        self.clients[project_id].discard(ws)

    async def publish(self, project_id: str, event: dict) -> None:
        dead = []
        for ws in list(self.clients[project_id]):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(project_id, ws)


hub = Hub()
_tasks: set = set()
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def spawn(coro) -> None:
    """后台执行（演示版用进程内任务，生产版替换为 Temporal 工作流）。同步接口在线程池里调用时投递到主事件循环。"""
    try:
        t = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        if _loop is None:
            coro.close()
            return
        t = asyncio.run_coroutine_threadsafe(coro, _loop)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    t.add_done_callback(_log_error)


def _log_error(t) -> None:
    if not t.cancelled() and t.exception() is not None:
        log.error("后台任务出错", exc_info=t.exception())


def emit(project_id: str, kind: str, **payload) -> None:
    spawn(hub.publish(project_id, {"type": kind, **payload}))
