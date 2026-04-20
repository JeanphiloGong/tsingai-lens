from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from application.source.artifact_input_service import load_blocks_artifact
from application.derived.protocol.block_service import build_procedure_blocks
from application.derived.protocol.extract_service import ProtocolExtractService
from application.derived.protocol.artifact_service import (
    persist_procedure_blocks,
)


@dataclass(frozen=True)
class ProtocolPipelineResult:
    output_dir: Path
    procedure_blocks_path: Path
    protocol_steps_path: Path
    source_block_count: int
    procedure_block_count: int
    protocol_step_count: int


def build_protocol_artifacts(
    base_dir: str | Path,
    extractor: ProtocolExtractService | None = None,
) -> ProtocolPipelineResult:
    output_dir = Path(base_dir).expanduser().resolve()
    extractor = extractor or ProtocolExtractService()
    blocks = load_blocks_artifact(output_dir)

    procedure_blocks = build_procedure_blocks(blocks)
    procedure_blocks_path = persist_procedure_blocks(output_dir, procedure_blocks)

    protocol_steps_path = output_dir / "protocol_steps.parquet"
    protocol_steps_table = extractor.build_protocol_steps_table(procedure_blocks)
    protocol_steps_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_steps_table.to_parquet(protocol_steps_path, index=False)

    return ProtocolPipelineResult(
        output_dir=output_dir,
        procedure_blocks_path=procedure_blocks_path,
        protocol_steps_path=protocol_steps_path,
        source_block_count=len(blocks),
        procedure_block_count=len(procedure_blocks),
        protocol_step_count=len(protocol_steps_table),
    )
