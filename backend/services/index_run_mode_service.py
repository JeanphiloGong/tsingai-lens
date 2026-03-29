from __future__ import annotations

from pathlib import Path


INCREMENTAL_BASELINE_FILENAME = "documents.parquet"
INCREMENTAL_DOWNGRADE_WARNING = (
    "未找到上一轮索引产物 documents.parquet，已自动降级为全量重建。"
)


def has_incremental_baseline(output_dir: str | Path) -> bool:
    """Return whether an output directory has the minimum baseline for update runs."""
    base_dir = Path(output_dir).expanduser().resolve()
    return (base_dir / INCREMENTAL_BASELINE_FILENAME).is_file()


def resolve_update_run(output_dir: str | Path, is_update_run: bool) -> tuple[bool, str | None]:
    """Normalize requested update mode against available baseline artifacts."""
    if not is_update_run:
        return False, None
    if has_incremental_baseline(output_dir):
        return True, None
    return False, INCREMENTAL_DOWNGRADE_WARNING
