from __future__ import annotations

from pathlib import Path

import pandas as pd

from application.documents.input_service import (
    CollectionArtifactPaths,
    build_document_records,
    load_collection_inputs,
    resolve_collection_artifact_paths,
)


ProtocolArtifactPaths = CollectionArtifactPaths

__all__ = [
    "ProtocolArtifactPaths",
    "resolve_protocol_artifact_paths",
    "load_protocol_inputs",
    "build_document_records",
    "persist_sections",
    "persist_procedure_blocks",
]


def resolve_protocol_artifact_paths(base_dir: str | Path) -> ProtocolArtifactPaths:
    return resolve_collection_artifact_paths(base_dir)


def load_protocol_inputs(base_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    return load_collection_inputs(base_dir)


def persist_sections(base_dir: str | Path, sections: pd.DataFrame) -> Path:
    paths = resolve_protocol_artifact_paths(base_dir)
    paths.base_dir.mkdir(parents=True, exist_ok=True)
    sections.to_parquet(paths.sections, index=False)
    return paths.sections


def persist_procedure_blocks(base_dir: str | Path, procedure_blocks: pd.DataFrame) -> Path:
    paths = resolve_protocol_artifact_paths(base_dir)
    paths.base_dir.mkdir(parents=True, exist_ok=True)
    procedure_blocks.to_parquet(paths.procedure_blocks, index=False)
    return paths.procedure_blocks
