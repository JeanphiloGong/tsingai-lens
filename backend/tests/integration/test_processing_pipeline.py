from __future__ import annotations

import pandas as pd

from application.derived.protocol import pipeline_service as protocol_pipeline_service
from domain.protocol import ProtocolArtifactSet
from domain.source import SourceArtifactSet
from infra.persistence.sqlite import (
    SqliteProtocolArtifactRepository,
    SqliteSourceArtifactRepository,
)
from infra.source.runtime.source_evidence import build_blocks


def _source_artifacts() -> SourceArtifactSet:
    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Composite Paper",
                "text": "\n".join(
                    [
                        "Introduction",
                        "Composite performance was evaluated.",
                        "Experimental Section",
                        "The precursor powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C for 2 h under Ar.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The precursor powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "The slurry was dried at 80 C and annealed at 600 C for 2 h under Ar.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-3",
                "text": "XRD and SEM were used to characterize the powders.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    blocks = build_blocks(documents, text_units)
    return SourceArtifactSet.from_records(
        documents=documents.to_dict(orient="records"),
        text_units=text_units.to_dict(orient="records"),
        blocks=blocks.to_dict(orient="records"),
    )


def _assert_protocol_artifacts(artifacts: ProtocolArtifactSet) -> None:
    blocks = pd.DataFrame([dict(record) for record in artifacts.procedure_blocks])
    steps = pd.DataFrame([dict(record) for record in artifacts.protocol_steps])

    assert not blocks.empty
    assert not steps.empty
    assert set(blocks["section_type"]) >= {"methods", "characterization"}
    assert "synthesis" in set(blocks["block_type"])
    assert "anneal" in set(steps["action"])


def test_build_protocol_artifacts_persists_artifacts(monkeypatch, tmp_path):
    collection_id = "col-protocol"
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    source_repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    protocol_repository = SqliteProtocolArtifactRepository(tmp_path / "lens.sqlite")
    source_repository.replace_collection_artifacts(collection_id, _source_artifacts())
    monkeypatch.setattr(
        protocol_pipeline_service,
        "source_artifact_repository",
        source_repository,
    )
    monkeypatch.setattr(
        protocol_pipeline_service,
        "protocol_artifact_repository",
        protocol_repository,
    )

    result = protocol_pipeline_service.build_protocol_artifacts(collection_id, output_dir)

    assert result.output_dir == output_dir.resolve()
    assert result.source_block_count >= 5
    assert result.procedure_block_count >= 3
    assert result.protocol_step_count >= 3
    _assert_protocol_artifacts(protocol_repository.read_collection_artifacts(collection_id))
