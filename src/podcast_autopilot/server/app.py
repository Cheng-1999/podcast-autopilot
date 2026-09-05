from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from ..config import PROJECT_ROOT
from .jobs import JobManager
from .routes import router


def create_app(project_root: Optional[Path] = None) -> FastAPI:
    project_root = Path(project_root) if project_root is not None else PROJECT_ROOT
    app = FastAPI(title="podcast-autopilot dashboard")
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
