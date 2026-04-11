from __future__ import annotations

from pathlib import Path
from typing import Any

from retrieval.config.embeddings import create_index_name

INCREMENTAL_BASELINE_FILENAME = "documents.parquet"
INCREMENTAL_DOWNGRADE_WARNING = (
    "未找到上一轮索引产物 documents.parquet，已自动降级为全量重建。"
)
INCREMENTAL_VECTOR_STORE_DOWNGRADE_WARNING = (
    "未找到完整的向量索引基线，已自动降级为全量重建。"
)


def has_incremental_baseline(output_dir: str | Path) -> bool:
    """Return whether an output directory has the minimum baseline for update runs."""
    base_dir = Path(output_dir).expanduser().resolve()
    return (base_dir / INCREMENTAL_BASELINE_FILENAME).is_file()


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _to_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    try:
        return dict(vars(value))
    except TypeError:
        return None


def _resolve_root_dir(config: Any) -> Path:
    root_dir = _get_attr(config, "root_dir", ".")
    return Path(str(root_dir)).expanduser().resolve()


def _resolve_vector_store_config(config: Any) -> dict[str, Any] | None:
    embed_text = _get_attr(config, "embed_text")
    vector_store_id = _get_attr(embed_text, "vector_store_id", "default_vector_store")

    if hasattr(config, "get_vector_store_config"):
        store = config.get_vector_store_config(vector_store_id)
        return _to_mapping(store)

    vector_store = _get_attr(config, "vector_store")
    if isinstance(vector_store, dict):
        store = vector_store.get(vector_store_id) or vector_store.get(
            "default_vector_store"
        )
        return _to_mapping(store)

    store = _get_attr(vector_store, vector_store_id) or _get_attr(
        vector_store, "default_vector_store"
    )
    return _to_mapping(store)


def _resolve_vector_store_path(
    config: Any,
    vector_store_config: dict[str, Any],
) -> Path | None:
    db_uri = vector_store_config.get("db_uri")
    if not db_uri:
        return None
    db_path = Path(str(db_uri)).expanduser()
    if not db_path.is_absolute():
        db_path = (_resolve_root_dir(config) / db_path).resolve()
    return db_path


def _required_vector_store_tables(
    config: Any,
    vector_store_config: dict[str, Any],
) -> list[str]:
    embed_text = _get_attr(config, "embed_text")
    embed_names = _get_attr(embed_text, "names", []) or []
    container_name = str(vector_store_config.get("container_name") or "default")
    return [create_index_name(container_name, str(name)) for name in embed_names]


def _probe_lancedb_tables(
    db_uri: Path,
    required_tables: list[str],
) -> tuple[list[str], str | None]:
    if not required_tables:
        return [], None

    try:
        import lancedb
    except Exception as exc:  # noqa: BLE001
        return required_tables, str(exc)

    try:
        db = lancedb.connect(str(db_uri))
    except Exception as exc:  # noqa: BLE001
        return required_tables, str(exc)

    missing: list[str] = []
    errors: list[str] = []
    for table_name in required_tables:
        try:
            db.open_table(table_name)
        except Exception as exc:  # noqa: BLE001
            missing.append(table_name)
            errors.append(f"{table_name}: {exc}")
    return missing, "; ".join(errors) if errors else None


def _check_vector_store_baseline(config: Any) -> str | None:
    if config is None:
        return None

    vector_store_config = _resolve_vector_store_config(config)
    if not vector_store_config:
        return None
    if str(vector_store_config.get("type") or "").lower() != "lancedb":
        return None

    db_uri = _resolve_vector_store_path(config, vector_store_config)
    if db_uri is None or not db_uri.exists():
        return INCREMENTAL_VECTOR_STORE_DOWNGRADE_WARNING

    required_tables = _required_vector_store_tables(config, vector_store_config)
    missing_tables, detail = _probe_lancedb_tables(db_uri, required_tables)
    if not missing_tables:
        return None

    message = (
        f"{INCREMENTAL_VECTOR_STORE_DOWNGRADE_WARNING} "
        f"缺失或不可用的表: {', '.join(missing_tables)}。"
    )
    if detail:
        message = f"{message} 详情: {detail}"
    return message


def resolve_update_run(
    output_dir: str | Path,
    is_update_run: bool,
    config: Any | None = None,
) -> tuple[bool, str | None]:
    """Normalize requested update mode against available baseline artifacts."""
    if not is_update_run:
        return False, None
    if not has_incremental_baseline(output_dir):
        return False, INCREMENTAL_DOWNGRADE_WARNING

    vector_warning = _check_vector_store_baseline(config)
    if vector_warning:
        return False, vector_warning

    return True, None
