import os
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    data_dir: Path = Field(default_factory=lambda: BASE_DIR / "data")
    vector_store_dir: Path = Field(default_factory=lambda: BASE_DIR / "data/vector_store")
    documents_dir: Path = Field(default_factory=lambda: BASE_DIR / "data/documents")
    index_file: Path = Field(default_factory=lambda: BASE_DIR / "data/documents/index.json")

    embedding_model: str = Field(default=os.getenv("EMBEDDING_MODEL", "text-embedding-3-large"))
    embedding_base_url: Optional[str] = Field(
        default=os.getenv("EMBEDDING_BASE_URL", os.getenv("LLM_BASE_URL", None))
    )  # OpenAI 兼容 embedding 端点
    embedding_api_key: Optional[str] = Field(
        default=os.getenv("EMBEDDING_API_KEY", os.getenv("LLM_API_KEY", "EMPTY"))
    )

    llm_model: str = Field(default=os.getenv("LLM_MODEL", "qwen1.5-8b-chat"))
    llm_base_url: Optional[str] = Field(
        default=os.getenv("LLM_BASE_URL", None)
    )  # e.g. http://localhost:11434/v1
    llm_api_key: Optional[str] = Field(default=os.getenv("LLM_API_KEY", "EMPTY"))
    llm_max_tokens: int = Field(default=512)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
