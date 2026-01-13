"""Static configuration (hard-coded defaults)."""
import os
from pathlib import Path
from dotenv import load_dotenv

# 根目录
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = DATA_DIR / "logs"

# 环境变量文件
ENV_FILE_PATH = ROOT_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE_PATH)

ENV_EXIST = os.getenv("ENV_FILE")

if ENV_EXIST:
    print("环境变量加载成功")
else:
    print("环境变量加载失败")


# 存储路径
DOCUMENTS_DIR = DATA_DIR / "documents"
IMAGES_DIR = DATA_DIR / "images"
INDEX_FILE = DOCUMENTS_DIR / "index.json"
GRAPH_STORE_FILE = DATA_DIR / "graph_store.json"
CONFIG_DIR = DATA_DIR / "configs"

STATIC_IMAGE_URL = "/statc/images"

# LLM 配置（可根据需要手工修改）
LLM_BASE_URL = os.environ.get("LLM_BASE_URL","http://localhost:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
LLM_API_KEY = os.environ.get("LLM_API_KEY")
LLM_MAX_TOKENS = 512

#################
# DATABASE
#################

DATABASE_USER = os.environ.get("DATABASE_USER", "webai_user")
DATABASE_PASSWORD = os.environ.get("DATABASE_PASSWORD", "Jeanphilo..")
DATABASE_PORT = os.environ.get("DATABASE_PORT", "5432")
DATABASE_HOST = os.environ.get("DATABASE_HOST", "localhost")
