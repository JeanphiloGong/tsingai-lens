"""Moved execution records preserve publication and failure history in PostgreSQL."""

import pytest

from application.repositories.objective_repository import ObjectiveAnalysis
from application.repositories.pipeline_run_repository import (
    ExecutionStats,
    ModelUsage,
    TokenUsage,
)
from domain.core import ObjectiveFactSet, PreparedDocumentInput, ResearchObjective
from infra.persistence.postgres.objective_repository import PostgresObjectiveRepository
from tests.integration.persistence.test_postgres_source_artifacts import COLLECTION_ID

pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio


async def test_published_evidence_gap_survives_a_failed_followup(
    source_repository,
) -> None:
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": COLLECTION_ID,
            "objective_id": "laser-power-porosity",
            "question": "How does laser power affect porosity in Ti-6Al-4V?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
            "seed_document_ids": ["doc_a", "doc_b"],
        }
    )
    inputs = (
        PreparedDocumentInput("doc_a", "prepared-a"),
        PreparedDocumentInput("doc_b", "prepared-b"),
    )
    await repository.replace(
        COLLECTION_ID, ObjectiveFactSet(research_objectives=(objective,))
    )
    stored = await repository.read_objective_record(
        COLLECTION_ID, objective.objective_id
    )
    assert stored.objective == objective
    assert stored.created_at is not None
    assert not hasattr(stored.objective, "created_at")

    confirmed = await repository.confirm_objective(
        COLLECTION_ID, objective.objective_id
    )
    queued_objective, queued = await repository.queue_analysis(
        COLLECTION_ID,
        objective.objective_id,
        document_inputs=inputs,
        pipeline_version="research-analysis.v1",
        model_name="analysis-model",
        prompt_versions={},
    )
    assert confirmed.confirmation_status == "confirmed"
    assert isinstance(queued, ObjectiveAnalysis)
    assert queued_objective.active_analysis_version == queued.analysis_version
    assert await repository.read_analysis(*queued.key) == queued
    with pytest.raises(ValueError, match="only running"):
        await repository.publish_experiment_analysis(*queued.key)

    running = await repository.claim_analysis(*queued.key)
    assert running.status == "running"
    stats = ExecutionStats(
        duration_ms=100,
        model_usage=(ModelUsage("analysis-model", 1, TokenUsage(32, 16, 48)),),
    )
    await repository.update_analysis_execution_stats(
        *queued.key,
        stats=stats,
        model_name="analysis-model",
        prompt_versions={},
        diagnostics=(),
    )
    published_objective, published = await repository.publish_experiment_analysis(
        *queued.key,
        abstention_reason="no_comparable_evidence",
        abstention_note="The selected papers report power settings but no comparable porosity measurements.",
    )
    assert published_objective.published_analysis_version == queued.analysis_version
    assert published.status == "succeeded"
    assert published.stats.token_usage == TokenUsage(32, 16, 48)
    assert (
        await repository.read_published_analysis(COLLECTION_ID, objective.objective_id)
        == published
    )

    _, retry = await repository.queue_analysis(
        COLLECTION_ID,
        objective.objective_id,
        document_inputs=inputs,
        pipeline_version="research-analysis.v1",
        model_name="analysis-model",
        prompt_versions={},
    )
    await repository.claim_analysis(*retry.key)
    failed = await repository.fail_analysis(
        *retry.key,
        error_code="provider_timeout",
        error_message="The source analysis timed out.",
    )
    assert failed.status == "failed"
    assert failed.abstention_reason is None
    assert await repository.read_analysis(*failed.key) == failed
    assert (
        await repository.read_published_analysis(COLLECTION_ID, objective.objective_id)
        == published
    )
