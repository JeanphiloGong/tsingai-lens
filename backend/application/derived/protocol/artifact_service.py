from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from application.source.artifact_input_service import (
    build_document_records,
    load_collection_inputs,
)


@dataclass(frozen=True)
class ProtocolArtifactPaths:
    base_dir: Path
    procedure_blocks: Path
    protocol_steps: Path

__all__ = [
    "ProtocolArtifactPaths",
    "resolve_protocol_artifact_paths",
    "load_protocol_inputs",
    "build_document_records",
    "persist_procedure_blocks",
]


def resolve_protocol_artifact_paths(base_dir: str | Path) -> ProtocolArtifactPaths:
    base_path = Path(base_dir).expanduser().resolve()
    return ProtocolArtifactPaths(
        base_dir=base_path,
        procedure_blocks=base_path / "procedure_blocks.parquet",
        protocol_steps=base_path / "protocol_steps.parquet",
    )


def load_protocol_inputs(base_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    return load_collection_inputs(base_dir)


def persist_procedure_blocks(base_dir: str | Path, procedure_blocks: pd.DataFrame) -> Path:
    paths = resolve_protocol_artifact_paths(base_dir)
    paths.base_dir.mkdir(parents=True, exist_ok=True)
    procedure_blocks.to_parquet(paths.procedure_blocks, index=False)
    return paths.procedure_blocks
