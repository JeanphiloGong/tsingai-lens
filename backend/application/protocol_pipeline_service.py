from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from application.protocol_block_service import build_procedure_blocks
from application.protocol_extract_service import ProtocolExtractService
from application.protocol_section_service import build_sections
from application.protocol_source_service import (
    load_protocol_inputs,
    persist_procedure_blocks,
    persist_sections,
)


@dataclass(frozen=True)
class ProtocolPipelineResult:
    output_dir: Path
    sections_path: Path
    procedure_blocks_path: Path
    protocol_steps_path: Path
    section_count: int
    procedure_block_count: int
    protocol_step_count: int


def build_protocol_artifacts(
    base_dir: str | Path,
    extractor: ProtocolExtractService | None = None,
) -> ProtocolPipelineResult:
    output_dir = Path(base_dir).expanduser().resolve()
    extractor = extractor or ProtocolExtractService()
    documents, text_units = load_protocol_inputs(output_dir)

    sections = build_sections(documents, text_units)
    sections_path = persist_sections(output_dir, sections)

    procedure_blocks = build_procedure_blocks(sections)
    procedure_blocks_path = persist_procedure_blocks(output_dir, procedure_blocks)

    protocol_steps_path = output_dir / "protocol_steps.parquet"
    protocol_steps_table = extractor.build_protocol_steps_table(procedure_blocks)
    protocol_steps_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_steps_table.to_parquet(protocol_steps_path, index=False)

    return ProtocolPipelineResult(
        output_dir=output_dir,
        sections_path=sections_path,
        procedure_blocks_path=procedure_blocks_path,
        protocol_steps_path=protocol_steps_path,
        section_count=len(sections),
        procedure_block_count=len(procedure_blocks),
        protocol_step_count=len(protocol_steps_table),
    )
