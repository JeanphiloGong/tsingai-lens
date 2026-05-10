from __future__ import annotations

from domain.protocol import ProtocolArtifactSet
from infra.persistence.sqlite import SqliteProtocolArtifactRepository


def test_sqlite_protocol_artifact_repository_round_trips_collection_artifacts(tmp_path):
    repository = SqliteProtocolArtifactRepository(tmp_path / "lens.sqlite")

    repository.replace_collection_artifacts(
        "col-1",
        ProtocolArtifactSet(
            procedure_blocks=(
                {
                    "block_id": "pb-1",
                    "paper_id": "paper-1",
                    "text": "Powders were mixed.",
                    "order": 2,
                },
            ),
            protocol_steps=(
                {
                    "step_id": "step-1",
                    "paper_id": "paper-1",
                    "action": "mix",
                    "conditions_json": {"duration": {"value": 7200}},
                    "order": 1,
                },
            ),
        ),
    )

    restored = repository.read_collection_artifacts("col-1")
    status = repository.get_collection_status("col-1")

    assert restored.procedure_blocks[0]["block_id"] == "pb-1"
    assert restored.protocol_steps[0]["conditions_json"]["duration"]["value"] == 7200
    assert status.procedure_blocks_ready is True
    assert status.protocol_steps_ready is True
