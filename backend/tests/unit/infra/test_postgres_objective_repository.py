from __future__ import annotations

from datetime import UTC, datetime

from domain.core import ResearchObjective
from infra.persistence.postgres.models.objective import ObjectiveResearchRecord
from infra.persistence.postgres.objective_repository import PostgresObjectiveRepository


def _objective() -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "question": "How does temperature affect strength?",
            "material_scope": ["Alloy A"],
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "seed_document_ids": ["paper-1", "paper-2"],
            "confidence": 0.9,
            "rank": 1,
        }
    )


def test_research_objective_does_not_expose_persistence_timestamps() -> None:
    objective = _objective()

    assert not hasattr(objective, "created_at")
    assert not hasattr(objective, "updated_at")


def test_objective_record_keeps_timestamps_out_of_scientific_payload() -> None:
    created_at = datetime(2026, 9, 2, 1, 2, 3, tzinfo=UTC)
    updated_at = datetime(2026, 9, 2, 4, 5, 6, tzinfo=UTC)
    objective = _objective()
    row = PostgresObjectiveRepository._new_objective_row(
        objective,
        now=created_at,
    )
    row.updated_at = updated_at

    assert "created_at" not in row.payload
    assert "updated_at" not in row.payload
    assert row.created_at == created_at
    assert row.updated_at == updated_at

    restored = PostgresObjectiveRepository._objective_record_from_row(row)
    assert restored["created_at"] == created_at.isoformat()
    assert restored["updated_at"] == updated_at.isoformat()


def test_objective_record_columns_override_legacy_payload_timestamps() -> None:
    column_created_at = datetime(2026, 9, 2, 1, 2, 3, tzinfo=UTC)
    column_updated_at = datetime(2026, 9, 2, 4, 5, 6, tzinfo=UTC)
    legacy_created_at = datetime(2020, 1, 1, tzinfo=UTC)
    legacy_updated_at = datetime(2020, 1, 2, tzinfo=UTC)
    row = ObjectiveResearchRecord(
        collection_id="collection-1",
        objective_id="objective-1",
        rank=1,
        origin="system_discovered",
        created_by_tool_call_id=None,
        payload={
            **_objective().to_record(),
            "created_at": legacy_created_at.isoformat(),
            "updated_at": legacy_updated_at.isoformat(),
        },
        created_at=column_created_at,
        updated_at=column_updated_at,
    )

    restored = PostgresObjectiveRepository._objective_record_from_row(row)

    assert restored["created_at"] == column_created_at.isoformat()
    assert restored["updated_at"] == column_updated_at.isoformat()
