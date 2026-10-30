from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from ..config import PROJECT_ROOT
from .jobs import JobManager
from .routes import router


def _is_benign_proactor_reset(exc: BaseException) -> bool:
    """True for the harmless `ConnectionResetError: [WinError 10054]` that
    Windows' ProactorEventLoop raises from `_call_connection_lost` when a
    client (e.g. a browser dropping an SSE connection) resets the TCP
    connection before the server's own `sock.shutdown()` runs. The stdlib
    does not guard that call, so left alone it reaches the loop's default
    exception handler and prints a traceback to stderr -- which, during a
    job, is exactly the stream tee'd into that job's log/SSE feed, making an
    unrelated client disconnect look like the job crashed."""
    return isinstance(exc, ConnectionResetError) and getattr(exc, "winerror", None) == 10054


def _loop_exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    exc = context.get("exception")
    if exc is not None and _is_benign_proactor_reset(exc):
        return
    loop.default_exception_handler(context)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if sys.platform == "win32":
        asyncio.get_running_loop().set_exception_handler(_loop_exception_handler)
    yield


def create_app(project_root: Optional[Path] = None) -> FastAPI:
    project_root = Path(project_root) if project_root is not None else PROJECT_ROOT
    app = FastAPI(title="podcast-autopilot dashboard", lifespan=_lifespan)
    app.state.project_root = project_root
    app.state.job_manager = JobManager()
    app.include_router(router)

    web_dist = (project_root / "web" / "dist").resolve()
    if web_dist.is_dir():
        index_path = web_dist / "index.html"

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str):
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(404, "not found")
            candidate = (web_dist / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(web_dist):
                return FileResponse(candidate)
            if index_path.is_file():
                return FileResponse(index_path)
            raise HTTPException(404, "not found")

    return app
