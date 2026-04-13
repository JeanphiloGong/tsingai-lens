import os

from controllers import (
    collections,
    comparisons,
    documents,
    evidence,
    goals,
    graph,
    protocol,
    query,
    reports,
    tasks,
    workspace,
)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config import DATA_DIR
from utils.logger import setup_logger

# 初始化全局日志，确保 controllers/services 的日志能输出
setup_logger("lens")

PUBLIC_API_PREFIX = "/api"
PUBLIC_API_V1_PREFIX = f"{PUBLIC_API_PREFIX}/v1"


def _parse_cors_allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    app = FastAPI(
        title="TsingAI-Lens API",
        version="0.2.2",
        docs_url=f"{PUBLIC_API_PREFIX}/docs",
        redoc_url=f"{PUBLIC_API_PREFIX}/redoc",
        openapi_url=f"{PUBLIC_API_PREFIX}/openapi.json",
    )
    cors_allowed_origins = _parse_cors_allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        # Same-origin deployment does not require wildcard cross-origin access.
        # Configure explicit origins via `CORS_ALLOWED_ORIGINS` when needed.
        allow_origins=cors_allowed_origins,
        allow_credentials=bool(cors_allowed_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.mount(f"{PUBLIC_API_PREFIX}/static", StaticFiles(directory=DATA_DIR), name="static")
    app.include_router(query.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(reports.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(collections.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(goals.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(graph.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(protocol.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(tasks.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(workspace.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(documents.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(evidence.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(comparisons.router, prefix=PUBLIC_API_V1_PREFIX)
    return app


app = create_app()
