from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from application.derived.protocol.block_service import build_procedure_blocks
from application.derived.protocol.extract_service import ProtocolExtractService
from domain.protocol import ProtocolArtifactSet
from infra.persistence.factory import (
    build_protocol_artifact_repository,
    build_source_artifact_repository,
)


@dataclass(frozen=True)
class ProtocolPipelineResult:
    output_dir: Path
    source_block_count: int
    procedure_block_count: int
    protocol_step_count: int


source_artifact_repository = build_source_artifact_repository()
protocol_artifact_repository = build_protocol_artifact_repository()


def build_protocol_artifacts(
    collection_id: str,
    base_dir: str | Path,
    extractor: ProtocolExtractService | None = None,
) -> ProtocolPipelineResult:
    output_dir = Path(base_dir).expanduser().resolve()
    extractor = extractor or ProtocolExtractService()
    blocks = pd.DataFrame(
        [block.to_record() for block in source_artifact_repository.list_blocks(collection_id)]
    )

    procedure_blocks = build_procedure_blocks(blocks)
    protocol_steps_table = extractor.build_protocol_steps_table(procedure_blocks)
    protocol_artifact_repository.replace_collection_artifacts(
        collection_id,
        ProtocolArtifactSet(
            procedure_blocks=tuple(procedure_blocks.to_dict(orient="records")),
            protocol_steps=tuple(protocol_steps_table.to_dict(orient="records")),
        ),
    )

    return ProtocolPipelineResult(
        output_dir=output_dir,
        source_block_count=len(blocks),
        procedure_block_count=len(procedure_blocks),
        protocol_step_count=len(protocol_steps_table),
    )
