"""Moved execution records preserve publication and failure history in PostgreSQL."""

import pytest

from application.repositories.objective_repository import ObjectiveAnalysis
from application.repositories.pipeline_run_repository import (
    ExecutionStats,
    ModelUsage,
    TokenUsage,
)
from domain.core import ObjectiveFactSet, PaperContribution, PreparedDocumentInput, ResearchObjective
from infra.persistence.postgres.objective_repository import PostgresObjectiveRepository
from tests.integration.persistence.test_postgres_source_artifacts import COLLECTION_ID, _source

pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio

OBJECTIVE_ID = "objective-laser-power-strength"


@pytest.fixture
async def objective_repository(source_repository):
    for document_id in ("doc_a", "doc_b"):
        await source_repository.replace_document(
            COLLECTION_ID, _source(document_id, title=document_id),
        )
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    objective = ResearchObjective.from_mapping({
        "collection_id": COLLECTION_ID, "objective_id": OBJECTIVE_ID,
        "question": "How does laser power affect tensile strength?",
        "material_scope": ["Ti-6Al-4V"], "variables": ["laser power"],
        "outcomes": ["tensile strength"], "seed_document_ids": ["doc_a", "doc_b"],
    })
    await repository.replace(COLLECTION_ID, ObjectiveFactSet(research_objectives=(objective,)))
    return repository


async def _queue_and_claim(repository):
    objective, queued = await repository.queue_analysis(
        COLLECTION_ID, OBJECTIVE_ID,
        document_inputs=(
            PreparedDocumentInput("doc_a", "fingerprint-doc-a"),
            PreparedDocumentInput("doc_b", "fingerprint-doc-b"),
        ),
        pipeline_version="objective-analysis.v1", model_name="test-model",
        prompt_versions={"finding": "v1"},
    )
    claimed = await repository.claim_analysis(COLLECTION_ID, OBJECTIVE_ID, queued.analysis_version)
    assert claimed is not None
    return objective, claimed


def _contribution(version: int, document_id: str) -> PaperContribution:
    return PaperContribution.from_mapping({
        "collection_id": COLLECTION_ID, "objective_id": OBJECTIVE_ID,
        "analysis_version": version, "document_id": document_id,
        "analysis_status": "analyzed", "relevance": "high",
        "paper_role": "primary_experiment",
        "contribution_summary": "Reports a controlled laser-power comparison.",
        "material_match": ["Ti-6Al-4V"], "changed_variables": ["laser power"],
        "measured_property_scope": ["tensile strength"],
        "test_environment_scope": ["room temperature"], "confidence": 0.9,
        "evidence_disposition": "comparable_evidence",
        "routed_source_count": 1, "extracted_source_count": 1,
        "comparable_evidence_count": 1, "failed_source_count": 0,
    })


async def test_finding_http_revision_and_abstention_are_persisted(source_repository, tmp_path):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from application.core.objectives.analysis.experiment_analysis_writer import (
        ExperimentAnalysisWriter,
    )
    from application.core.objectives.analysis.experiment_query_service import (
        ExperimentQueryService,
    )
    from application.core.objectives.finding_authoring_service import (
        FindingAuthoringService,
    )
    from application.source.collection_service import CollectionService
    from controllers.core.finding_review import router
    from domain.core import PaperContribution
    from infra.persistence.file.collection_workspace import FileCollectionWorkspace
    from infra.persistence.postgres.collection_repository import (
        PostgresCollectionRepository,
    )
    from infra.persistence.postgres.comparison_group_repository import (
        PostgresComparisonGroupRepository,
    )
    from infra.persistence.postgres.experiment_analysis_repository import (
        PostgresExperimentAnalysisRepository,
    )
    from infra.persistence.postgres.experiment_analysis_transaction import (
        PostgresExperimentAnalysisTransactionFactory,
    )
    from infra.persistence.postgres.experiment_finding_repository import (
        PostgresExperimentFindingRepository,
    )
    from infra.persistence.postgres.objective_experiment_selection_repository import (
        PostgresObjectiveExperimentSelectionRepository,
    )
    from infra.persistence.postgres.paper_experiment_repository import (
        PostgresPaperExperimentRepository,
    )
    from tests.unit.application.test_experiment_analysis_writer import (
        _comparison_experiment,
    )

    sessions = source_repository.session_factory
    repository = PostgresObjectiveRepository(sessions)
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": COLLECTION_ID,
            "objective_id": "preheat-elongation",
            "question": "Does preheat change elongation in 316L?",
            "material_scope": ["316L"],
            "variables": ["preheat"],
            "outcomes": ["elongation"],
            "confirmation_status": "confirmed",
        }
    )
    await repository.replace(
        COLLECTION_ID, ObjectiveFactSet(research_objectives=(objective,))
    )
    await repository.queue_analysis(
        COLLECTION_ID,
        objective.objective_id,
        document_inputs=tuple(
            PreparedDocumentInput(doc, f"prepared-{doc}") for doc in ("doc_a", "doc_b")
        ),
        pipeline_version="test",
        model_name=None,
        prompt_versions={},
    )
    analysis = await repository.claim_analysis(COLLECTION_ID, objective.objective_id, 1)
    experiments = PostgresPaperExperimentRepository(sessions)
    writer = ExperimentAnalysisWriter(
        paper_experiment_repository=experiments,
        experiment_analysis_repository=PostgresExperimentAnalysisRepository(sessions),
    )
    source = await writer.write_experiment_analysis(
        collection_id=COLLECTION_ID,
        objective=objective,
        analysis=analysis,
        experiment_outputs=(_comparison_experiment("doc_a"),),
    )
    coverage = tuple(
        PaperContribution.from_mapping(
            {
                "collection_id": COLLECTION_ID,
                "objective_id": objective.objective_id,
                "analysis_version": 1,
                "document_id": doc,
                "analysis_status": "analyzed" if doc == "doc_a" else "excluded",
                "warnings": (
                    [] if doc == "doc_a" else ["No comparable elongation measurement."]
                ),
            }
        )
        for doc in ("doc_a", "doc_b")
    )
    await repository.publish_experiment_analysis(
        COLLECTION_ID,
        objective.objective_id,
        1,
        contributions=coverage,
    )
    query = ExperimentQueryService(
        experiments,
        PostgresObjectiveExperimentSelectionRepository(sessions),
        PostgresComparisonGroupRepository(sessions),
        PostgresExperimentFindingRepository(sessions),
        objective_repository=repository,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.finding_authoring_service = FindingAuthoringService(
        collection_service=CollectionService(
            PostgresCollectionRepository(sessions), FileCollectionWorkspace(tmp_path)
        ),
        objective_repository=repository,
        experiment_query_service=query,
        experiment_analysis_writer=writer,
        experiment_analysis_transaction_factory=PostgresExperimentAnalysisTransactionFactory(
            sessions
        ),
    )

    @app.middleware("http")
    async def authenticate(request, call_next):
        request.state.current_user = {"user_id": "user_source"}
        return await call_next(request)

    path = f"/api/v1/collections/{COLLECTION_ID}/objectives/{objective.objective_id}/findings"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        revised = await client.post(
            path,
            json={
                "source_analysis_version": 1,
                "selection_ids": [item.selection_id for item in source.selections],
                "parent_finding_id": source.findings[0].finding_id,
                "limitations": [
                    " Supported only within the tested preheat conditions. "
                ],
            },
        )
        assert revised.status_code == 201, revised.text
        current = await query.read_analysis_bundle(
            COLLECTION_ID, objective.objective_id, 2
        )
        assert current.findings[0].parent_finding_id == source.findings[0].finding_id
        assert current.findings[0].origin == "hybrid"
        assert current.findings[0].created_by_user_id == "user_source"
        assert current.findings[0].source_analysis_version == 1
        assert "Supported only within the tested preheat conditions." in current.findings[0].limitations
        assert current.findings[0].created_at is not None
        abstained = await client.post(path, json={
            "source_analysis_version": 2, "abstention_reason": "insufficient_evidence",
            "limitations": ["The second paper lacks a comparable elongation measurement."],
        })
        assert abstained.status_code == 201, abstained.text
        assert abstained.json()["finding"] is None
        assert abstained.json()["abstention_reason"] == "insufficient_evidence"
    stored = await repository.read_analysis(COLLECTION_ID, objective.objective_id, 3)
    assert stored.abstention_reason == "insufficient_evidence"
    assert stored.abstention_note == "The second paper lacks a comparable elongation measurement."
    assert (await query.read_analysis_bundle(COLLECTION_ID, objective.objective_id, 3)).findings == ()
    assert (await query.read_analysis_bundle(COLLECTION_ID, objective.objective_id, 1)).findings == source.findings
    assert {item.document_id for item in await repository.list_contributions(COLLECTION_ID, objective.objective_id, 3)} == {"doc_a", "doc_b"}


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
