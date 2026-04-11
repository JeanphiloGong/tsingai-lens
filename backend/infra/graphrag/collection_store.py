"""Collection storage and configuration helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from fastapi import HTTPException

from config import CONFIG_DIR
from retrieval.config.load_config import load_config

logger = logging.getLogger(__name__)

COLLECTIONS_DIR = CONFIG_DIR.parent / "collections"
DEFAULT_COLLECTION_ID = "default"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "default.yaml"
LEGACY_DATA_DIR = CONFIG_DIR.parent
LEGACY_DEFAULT_PATHS = {
    "input_base_dir": "../../documents",
    "output_base_dir": "../../output",
    "update_output_base_dir": "../../update_output",
    "cache_base_dir": "../../cache",
    "reporting_base_dir": "../../logs",
    "vector_store_uri": "../../vector_store/lancedb",
}


def collection_dir(collection_id: str) -> Path:
    return COLLECTIONS_DIR / collection_id


def collection_config_path(collection_id: str) -> Path:
    return collection_dir(collection_id) / "config.yaml"


def collection_meta_path(collection_id: str) -> Path:
    return collection_dir(collection_id) / "meta.json"


def write_collection_meta(collection_id: str, name: str | None) -> None:
    meta = {
        "id": collection_id,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    collection_meta_path(collection_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _resolve_collection_path(base_dir: Path, value: str | None, default: str) -> Path:
    path = Path(value or default)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _sync_default_collection_legacy_config(default_dir: Path) -> None:
    config_path = default_dir / "config.yaml"
    if not config_path.is_file():
        return
    legacy_output_dir = LEGACY_DATA_DIR / "output"
    if not legacy_output_dir.is_dir():
        return

    try:
        config_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning("Failed to read default collection config: %s", config_path)
        return

    if not isinstance(config_data, dict):
        logger.warning("Default collection config is not a mapping: %s", config_path)
        return

    output_cfg = config_data.get("output", {})
    current_output = output_cfg.get("base_dir") if isinstance(output_cfg, dict) else None
    current_output_dir = _resolve_collection_path(default_dir, current_output, "output")
    if current_output_dir.is_dir():
        return

    changed = False

    if config_data.get("root_dir") != ".":
        config_data["root_dir"] = "."
        changed = True

    input_cfg = config_data.setdefault("input", {})
    if isinstance(input_cfg, dict):
        storage_cfg = input_cfg.setdefault("storage", {})
        if isinstance(storage_cfg, dict):
            expected = LEGACY_DEFAULT_PATHS["input_base_dir"]
            if storage_cfg.get("base_dir") != expected:
                storage_cfg["base_dir"] = expected
                changed = True

    for section, key_name in [
        ("output", "output_base_dir"),
        ("update_index_output", "update_output_base_dir"),
        ("cache", "cache_base_dir"),
        ("reporting", "reporting_base_dir"),
    ]:
        section_cfg = config_data.setdefault(section, {})
        if isinstance(section_cfg, dict):
            expected = LEGACY_DEFAULT_PATHS[key_name]
            if section_cfg.get("base_dir") != expected:
                section_cfg["base_dir"] = expected
                changed = True

    vector_store_cfg = config_data.setdefault("vector_store", {})
    if isinstance(vector_store_cfg, dict):
        default_store = vector_store_cfg.setdefault("default_vector_store", {})
        if isinstance(default_store, dict):
            expected = LEGACY_DEFAULT_PATHS["vector_store_uri"]
            if default_store.get("db_uri") != expected:
                default_store["db_uri"] = expected
                changed = True

    if not changed:
        return

    config_path.write_text(
        yaml.safe_dump(config_data, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    logger.info("Synced default collection config to legacy data layout")


def create_collection_dirs(target_dir: Path) -> None:
    for subdir in ["input", "output", "update_output", "cache", "logs", "vector_store"]:
        (target_dir / subdir).mkdir(parents=True, exist_ok=True)


def create_collection_config(collection_dir_path: Path, template_path: Path) -> None:
    if not template_path.is_file():
        raise HTTPException(status_code=500, detail=f"配置模板不存在: {template_path}")
    config_data = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
    config_data["root_dir"] = str(collection_dir_path.resolve())
    config_data.setdefault("input", {}).setdefault("storage", {})[
        "base_dir"
    ] = "input"
    config_data.setdefault("output", {})["base_dir"] = "output"
    config_data.setdefault("update_index_output", {})["base_dir"] = "update_output"
    config_data.setdefault("cache", {})["base_dir"] = "cache"
    config_data.setdefault("reporting", {})["base_dir"] = "logs"
    vector_store = config_data.setdefault("vector_store", {})
    default_store = vector_store.setdefault("default_vector_store", {})
    default_store.setdefault("type", "lancedb")
    default_store["db_uri"] = "vector_store/lancedb"
    config_path = collection_dir_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config_data, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def read_collection_meta(collection_dir_path: Path) -> dict[str, Any]:
    meta_path = collection_dir_path / "meta.json"
    if meta_path.is_file():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Collection meta invalid: %s", meta_path)
    stat = collection_dir_path.stat()
    created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return {
        "id": collection_dir_path.name,
        "name": None,
        "created_at": created_at,
    }


def ensure_default_collection() -> None:
    if not collection_dir(DEFAULT_COLLECTION_ID).is_dir():
        COLLECTIONS_DIR.mkdir(parents=True, exist_ok=True)
        default_dir = collection_dir(DEFAULT_COLLECTION_ID)
        default_dir.mkdir(parents=True, exist_ok=True)
        create_collection_dirs(default_dir)
        create_collection_config(default_dir, DEFAULT_CONFIG_PATH)
        write_collection_meta(DEFAULT_COLLECTION_ID, "default")
    _sync_default_collection_legacy_config(collection_dir(DEFAULT_COLLECTION_ID))


def ensure_collection_exists(collection_id: str) -> Path:
    target_dir = collection_dir(collection_id)
    if not target_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"集合不存在: {collection_id}")
    if not collection_config_path(collection_id).is_file():
        raise HTTPException(status_code=404, detail=f"集合配置缺失: {collection_id}")
    return target_dir


def load_collection_config(collection_id: str | None) -> tuple[Any, str]:
    resolved_id = collection_id or DEFAULT_COLLECTION_ID
    if resolved_id == DEFAULT_COLLECTION_ID:
        ensure_default_collection()
    else:
        ensure_collection_exists(resolved_id)
    config_path = collection_config_path(resolved_id)
    try:
        config = load_config(config_path.parent, config_filepath=config_path)
    except Exception as exc:
        logger.exception("Failed to load GraphRAG config for collection")
        raise HTTPException(status_code=400, detail=f"配置加载失败: {exc}") from exc
    return config, resolved_id


def collection_output_dir(collection_dir_path: Path) -> Path:
    config_path = collection_dir_path / "config.yaml"
    if config_path.is_file():
        try:
            config_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.warning("Failed to read collection config: %s", config_path)
        else:
            if isinstance(config_data, dict):
                output_cfg = config_data.get("output", {})
                if isinstance(output_cfg, dict):
                    base_dir = output_cfg.get("base_dir")
                    if base_dir:
                        output_path = Path(base_dir)
                        if not output_path.is_absolute():
                            output_path = collection_dir_path / output_path
                        return output_path
    return collection_dir_path / "output"


def read_parquet_row_count(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        try:
            import pyarrow.parquet as pq

            return int(pq.ParquetFile(path).metadata.num_rows)
        except Exception:
            df = pd.read_parquet(path)
            return int(len(df))
    except Exception:
        logger.exception("Failed to read parquet row count: %s", path)
        return None


def read_stats_num_documents(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read stats: %s", path)
        return None
    if isinstance(payload, dict):
        num_documents = payload.get("num_documents")
        if num_documents is not None:
            return int(num_documents)
        update_documents = payload.get("update_documents")
        if update_documents is not None:
            return int(update_documents)
    return None


def latest_output_time(output_dir: Path) -> str | None:
    if not output_dir.is_dir():
        return None
    candidates = [
        "stats.json",
        "context.json",
        "documents.parquet",
        "entities.parquet",
        "relationships.parquet",
        "communities.parquet",
    ]
    mtimes: list[float] = []
    for name in candidates:
        path = output_dir / name
        if path.is_file():
            mtimes.append(path.stat().st_mtime)
    if not mtimes:
        return None
    return datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat()


def collection_metrics(collection_dir_path: Path) -> dict[str, Any]:
    output_dir = collection_output_dir(collection_dir_path)
    document_count = read_parquet_row_count(output_dir / "documents.parquet")
    if document_count is None:
        document_count = read_stats_num_documents(output_dir / "stats.json")
    if document_count is None:
        document_count = 0
    entity_count = read_parquet_row_count(output_dir / "entities.parquet")
    if entity_count is None:
        entity_count = 0
    updated_at = latest_output_time(output_dir)
    status = "ready" if entity_count > 0 else "empty"
    return {
        "status": status,
        "document_count": document_count,
        "entity_count": entity_count,
        "updated_at": updated_at,
    }
