from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock

import pytest


from domain.core import PreparedDocumentInput, ResearchObjective
from domain.core.research_objective import ResearchObjective
from infra.persistence.postgres.models.objective import ObjectiveAnalysisRecord, ObjectiveResearchRecord
from repositories.objective_repository import ObjectiveAnalysis, ObjectiveRepository


def _objective() -> ResearchObjective:
    return ResearchObjective(
        collection_id="collection-1",
        objective_id="objective-1",
        question="How does temperature affect strength?",
        material_scope=("Alloy A",),
        variables=("temperature",),
        outcomes=("strength",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=("paper-1", "paper-2"),
        excluded_document_ids=(),
        confidence=0.9,
        reason=None,
        rank=1,
    )


def test_research_objective_does_not_expose_persistence_timestamps() -> None:
    objective = _objective()

    assert not hasattr(objective, "created_at")
    assert not hasattr(objective, "updated_at")


@pytest.mark.anyio
async def test_objective_record_keeps_timestamps_out_of_scientific_payload() -> None:
    created_at = datetime(2026, 9, 2, 1, 2, 3, tzinfo=UTC)
    updated_at = datetime(2026, 9, 2, 4, 5, 6, tzinfo=UTC)
    objective = _objective()
    row = ObjectiveResearchRecord(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        rank=objective.rank,
        origin=objective.origin,
        payload={key: list(value) if isinstance(value, tuple) else value for key, value in asdict(objective).items()},
        created_at=created_at,
    )
    row.updated_at = updated_at

    assert "created_at" not in row.payload
    assert "updated_at" not in row.payload
    assert row.created_at == created_at
    assert row.updated_at == updated_at

    restored = await _repository(row).read_objective_record("collection-1", "objective-1")
    assert restored.objective == objective
    assert restored.created_at == created_at
    assert restored.updated_at == updated_at


@pytest.mark.anyio
async def test_objective_record_columns_override_legacy_payload_timestamps() -> None:
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
            **asdict(_objective()),
            "created_at": legacy_created_at.isoformat(),
            "updated_at": legacy_updated_at.isoformat(),
        },
        created_at=column_created_at,
        updated_at=column_updated_at,
    )

    restored = await _repository(row).read_objective_record("collection-1", "objective-1")

    assert restored.created_at == column_created_at
    assert restored.updated_at == column_updated_at


@pytest.mark.anyio
async def test_analysis_row_persists_private_diagnostics_without_public_exposure() -> None:
    analysis = ObjectiveAnalysis(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-1", preparation_fingerprint="preparation-1"
            ),
        ),
        pipeline_version="objective-analysis.v2",
        model_name="model-a",
        prompt_versions={},
        total_document_count=1,
        diagnostics=(
            {
                "trace_type": "table_matrix_repair",
                "table_id": "table-1",
                "status": "verified",
            },
        ),
    )

    row = ObjectiveAnalysisRecord(
        collection_id=analysis.collection_id,
        objective_id=analysis.objective_id,
        analysis_version=analysis.analysis_version,
        status=analysis.status,
        payload={
            **{
                "collection_id": analysis.collection_id,
                "objective_id": analysis.objective_id,
                "analysis_version": analysis.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in analysis.document_inputs
                ],
                "pipeline_version": analysis.pipeline_version,
                "model_name": analysis.model_name,
                "prompt_versions": dict(analysis.prompt_versions),
                "stats": {
                    "duration_ms": analysis.stats.duration_ms,
                    "token_usage": (
                        asdict(analysis.stats.token_usage)
                        if analysis.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [
                        asdict(item) for item in analysis.stats.model_usage
                    ],
                    "unreported_request_count": analysis.stats.unreported_request_count,
                    "prompt_versions": dict(analysis.stats.prompt_versions),
                },
                "status": analysis.status,
                "phase": analysis.phase,
                "processed_document_count": analysis.processed_document_count,
                "total_document_count": analysis.total_document_count,
                "current_document_id": analysis.current_document_id,
                "progress_message": analysis.progress_message,
                "error_code": analysis.error_code,
                "error_message": analysis.error_message,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at is not None
                    else None
                ),
                "started_at": (
                    analysis.started_at.isoformat()
                    if analysis.started_at is not None
                    else None
                ),
                "completed_at": (
                    analysis.completed_at.isoformat()
                    if analysis.completed_at is not None
                    else None
                ),
                "origin": analysis.origin,
                "scientific_record_source": analysis.scientific_record_source,
                "source_analysis_version": analysis.source_analysis_version,
                "created_by_user_id": analysis.created_by_user_id,
                "created_by_tool_call_id": analysis.created_by_tool_call_id,
                "abstention_reason": analysis.abstention_reason,
                "abstention_note": analysis.abstention_note,
            },
            "diagnostics": list(analysis.diagnostics),
        },
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert row.payload["diagnostics"] == [
        {
            "trace_type": "table_matrix_repair",
            "table_id": "table-1",
            "status": "verified",
        }
    ]
    restored = await _repository(row).read_analysis("collection-1", "objective-1", 1)
    assert restored.diagnostics == (
        {
            "trace_type": "table_matrix_repair",
            "table_id": "table-1",
            "status": "verified",
        },
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _repository(row):
    session = AsyncMock()
    session.get.return_value = row
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    return ObjectiveRepository(factory)
