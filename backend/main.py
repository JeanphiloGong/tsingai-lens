from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config import DATA_DIR
from controllers import chat, collections, file, retrieval, tasks, workspace
from utils.logger import setup_logger

# 初始化全局日志，确保 controllers/services 的日志能输出
setup_logger("lens")


def create_app() -> FastAPI:
    app = FastAPI(title="TsingAI-Lens API", version="0.4.0-app-layer")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=DATA_DIR), name="static")
    app.include_router(file.router)
    app.include_router(chat.router)
    app.include_router(retrieval.router)
    app.include_router(collections.router)
    app.include_router(tasks.router)
    app.include_router(workspace.router)
    return app


app = create_app()
