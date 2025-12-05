from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from controllers.documents import router
from utils.logger import setup_logger

# 初始化全局日志，确保 controllers/services 的日志能输出
setup_logger("lens")


def create_app() -> FastAPI:
    app = FastAPI(title="TsingAI-Lens API", version="0.3.0-graphrag")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
