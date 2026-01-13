from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from controllers import chat, file, retrieval
from utils.logger import setup_logger
from config import DATA_DIR

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

    # 将data目录挂载为静态资源
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=DATA_DIR), name="static")
    app.include_router(file.router)
    app.include_router(chat.router)
    app.include_router(retrieval.router)
    return app


app = create_app()
