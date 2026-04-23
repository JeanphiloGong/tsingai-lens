from __future__ import annotations

import json

from application.core.semantic_build.core_semantic_version import (
    CURRENT_CORE_SEMANTIC_VERSION,
    core_semantic_rebuild_required,
    write_core_semantic_manifest,
)


def test_core_semantic_version_requires_rebuild_when_structural_inputs_exist_without_manifest(
    tmp_path,
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "documents.parquet").write_text("placeholder", encoding="utf-8")
    (output_dir / "blocks.parquet").write_text("placeholder", encoding="utf-8")

    assert core_semantic_rebuild_required(output_dir) is True


def test_core_semantic_version_is_current_after_manifest_write(tmp_path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "documents.parquet").write_text("placeholder", encoding="utf-8")

    write_core_semantic_manifest(output_dir)

    manifest = json.loads((output_dir / "core_semantic_manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == CURRENT_CORE_SEMANTIC_VERSION
    assert core_semantic_rebuild_required(output_dir) is False
