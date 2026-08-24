"""Backend paths and legacy LLM configuration."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Project root
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = DATA_DIR / "logs"

# Environment file
ENV_FILE_PATH = ROOT_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE_PATH)

# Storage paths
DOCUMENTS_DIR = DATA_DIR / "documents"
IMAGES_DIR = DATA_DIR / "images"
INDEX_FILE = DOCUMENTS_DIR / "index.json"
GRAPH_STORE_FILE = DATA_DIR / "graph_store.json"

# LLM configuration (may be adjusted manually when needed)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
LLM_API_KEY = os.environ.get("LLM_API_KEY")
LLM_MAX_TOKENS = 512
