from __future__ import annotations

import json
from pathlib import Path


CURRENT_CORE_SEMANTIC_VERSION = "paper_facts_v1"
CORE_SEMANTIC_MANIFEST_FILE = "core_semantic_manifest.json"
CORE_SEMANTIC_ARTIFACT_FILES = (
    "document_profiles.parquet",
    "evidence_anchors.parquet",
    "method_facts.parquet",
    "evidence_cards.parquet",
    "characterization_observations.parquet",
    "structure_features.parquet",
    "test_conditions.parquet",
    "baseline_references.parquet",
    "sample_variants.parquet",
    "measurement_results.parquet",
    "comparison_rows.parquet",
)
_STRUCTURAL_INPUT_FILES = (
    "documents.parquet",
    "blocks.parquet",
    "table_rows.parquet",
    "table_cells.parquet",
)


def core_semantic_manifest_path(base_dir: str | Path) -> Path:
    return Path(base_dir).expanduser().resolve() / CORE_SEMANTIC_MANIFEST_FILE


def structural_inputs_available(base_dir: str | Path) -> bool:
    resolved = Path(base_dir).expanduser().resolve()
    return any((resolved / filename).is_file() for filename in _STRUCTURAL_INPUT_FILES)


def core_semantic_version_is_current(base_dir: str | Path) -> bool:
    manifest_path = core_semantic_manifest_path(base_dir)
    if not manifest_path.is_file():
        return not structural_inputs_available(base_dir)

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return payload.get("version") == CURRENT_CORE_SEMANTIC_VERSION


def core_semantic_rebuild_required(base_dir: str | Path) -> bool:
    return structural_inputs_available(base_dir) and not core_semantic_version_is_current(base_dir)


def write_core_semantic_manifest(base_dir: str | Path) -> None:
    manifest_path = core_semantic_manifest_path(base_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"version": CURRENT_CORE_SEMANTIC_VERSION}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def purge_stale_core_semantic_artifacts(base_dir: str | Path) -> None:
    resolved = Path(base_dir).expanduser().resolve()
    if not core_semantic_rebuild_required(resolved):
        return
    for filename in (*CORE_SEMANTIC_ARTIFACT_FILES, CORE_SEMANTIC_MANIFEST_FILE):
        path = resolved / filename
        if path.is_file():
            path.unlink()
