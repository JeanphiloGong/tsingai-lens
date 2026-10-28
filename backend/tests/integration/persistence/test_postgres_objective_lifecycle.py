from infra.persistence import database
"""Moved execution records preserve publication and failure history in PostgreSQL."""


import pytest
from domain.core import (
    ObjectiveFactSet,
    PaperContribution,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.core.finding import (
    PAPER_CONTRIBUTION_STATUSES,
)
from domain.core.finding import _choice as finding_choice
from domain.core.finding import _text as finding_text
from domain.core.research_objective import (
    PaperContribution,
    ResearchObjective,
)
from domain.core.research_objective import (
    _positive_int_or_none as objective_positive_int_or_none,
)
from domain.core.research_objective import (
    _text,
    build_research_objective_id,
    normalize_objective_terms,
)
from repositories.objective_repository import ObjectiveAnalysis, ObjectiveRepository
from repositories.pipeline_run_repository import (
    ExecutionStats,
    ModelUsage,
    TokenUsage,
)
from tests.integration.persistence.test_postgres_source_artifacts import (
    COLLECTION_ID,
    _source,
)

pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio

OBJECTIVE_ID = "objective-laser-power-strength"


@pytest.fixture
async def objective_repository(source_repository):
    for document_id in ("doc_a", "doc_b"):
        await source_repository.replace_document(
            COLLECTION_ID, _source(document_id, title=document_id),
        )
    repository = ObjectiveRepository()
    objective = ResearchObjective(
        collection_id=_text(COLLECTION_ID) or "",
        objective_id=_text(OBJECTIVE_ID)
        or build_research_objective_id(
            question="How does laser power affect tensile strength?",
            material_scope=("Ti-6Al-4V",),
            variables=("laser power",),
            outcomes=("tensile strength",),
            mechanisms=(),
            constraints=(),
            requested_comparator=None,
            parent_objective_id=None,
            parent_analysis_version=None,
        ),
        question="How does laser power affect tensile strength?",
        material_scope=("Ti-6Al-4V",),
        variables=("laser power",),
        outcomes=("tensile strength",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=("doc_a", "doc_b"),
        excluded_document_ids=(),
        confidence=0.0,
        reason=None,
    )
    await repository.replace(COLLECTION_ID, ObjectiveFactSet(research_objectives=(objective,)))
    return repository


async def _queue_and_claim(repository):
    objective, queued = await repository.queue_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        document_inputs=(
            PreparedDocumentInput(
                document_id="doc_a", preparation_fingerprint="fingerprint-doc-a"
            ),
            PreparedDocumentInput(
                document_id="doc_b", preparation_fingerprint="fingerprint-doc-b"
            ),
        ),
        pipeline_version="objective-analysis.v1",
        model_name="test-model",
        prompt_versions={"finding": "v1"},
    )
    claimed = await repository.claim_analysis(COLLECTION_ID, OBJECTIVE_ID, queued.analysis_version)
    assert claimed is not None
    return objective, claimed


def _contribution(version: int, document_id: str) -> PaperContribution:
    return PaperContribution(
        collection_id=finding_text(COLLECTION_ID) or "",
        objective_id=finding_text(OBJECTIVE_ID) or "",
        analysis_version=objective_positive_int_or_none(version) or 0,
        document_id=finding_text(document_id) or "",
        analysis_status="analyzed",
        relevance="high",
        paper_role="primary_experiment",
        contribution_summary="Reports a controlled laser-power comparison.",
        material_match=("Ti-6Al-4V",),
        changed_variables=("laser power",),
        measured_property_scope=("tensile strength",),
        test_environment_scope=("room temperature",),
        exclusion_reason=None,
        warnings=(),
        confidence=0.9,
        evidence_disposition="comparable_evidence",
        routed_source_count=1,
        extracted_source_count=1,
        comparable_evidence_count=1,
        failed_source_count=0,
    )


async def test_finding_http_revision_and_abstention_are_persisted(source_repository, tmp_path):
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
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from infra.persistence.file.collection_workspace import FileCollectionWorkspace
    from repositories.collection_repository import (
        CollectionRepository,
    )
    from repositories.comparison_group_repository import (
        ComparisonGroupRepository,
    )
    from repositories.experiment_analysis_repository import (
        ExperimentAnalysisRepository,
    )
    from repositories.experiment_finding_repository import (
        ExperimentFindingRepository,
    )
    from repositories.objective_experiment_selection_repository import (
        ObjectiveExperimentSelectionRepository,
    )
    from repositories.paper_experiment_repository import (
        PaperExperimentRepository,
    )
    from tests.unit.application.test_experiment_analysis_writer import (
        _comparison_experiment,
    )

    sessions = database.AsyncSessionLocal
    repository = ObjectiveRepository()
    objective = ResearchObjective(
        collection_id=_text(COLLECTION_ID) or "",
        objective_id="preheat-elongation",
        question="Does preheat change elongation in 316L?",
        material_scope=("316L",),
        variables=("preheat",),
        outcomes=("elongation",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=(),
        excluded_document_ids=(),
        confidence=0.0,
        reason=None,
        confirmation_status="confirmed",
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
    experiments = PaperExperimentRepository()
    writer = ExperimentAnalysisWriter(
        paper_experiment_repository=experiments,
        experiment_analysis_repository=ExperimentAnalysisRepository(),
    )
    async with database.AsyncSessionLocal() as db, db.begin():
        source = await writer.write_experiment_analysis(db=db,
            collection_id=COLLECTION_ID,
            objective=objective,
            analysis=analysis,
            experiment_outputs=(_comparison_experiment("doc_a"),),
        )
    coverage = tuple(
        PaperContribution(
            collection_id=finding_text(COLLECTION_ID) or "",
            objective_id=finding_text(objective.objective_id) or "",
            analysis_version=1,
            document_id=finding_text(doc) or "",
            analysis_status=finding_choice(
                "analyzed" if doc == "doc_a" else "excluded",
                PAPER_CONTRIBUTION_STATUSES,
                "pending",
            ),
            relevance="uncertain",
            paper_role="uncertain",
            contribution_summary=None,
            material_match=(),
            changed_variables=(),
            measured_property_scope=(),
            test_environment_scope=(),
            exclusion_reason=None,
            warnings=normalize_objective_terms(
                [] if doc == "doc_a" else ["No comparable elongation measurement."]
            ),
            confidence=0.0,
        )
        for doc in ("doc_a", "doc_b")
    )
    async with database.AsyncSessionLocal() as db, db.begin():
        await repository.publish_experiment_analysis(db, COLLECTION_ID, objective.objective_id, 1, contributions=coverage)
    query = ExperimentQueryService(
        experiments,
        ObjectiveExperimentSelectionRepository(),
        ComparisonGroupRepository(),
        ExperimentFindingRepository(),
        objective_repository=repository,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.finding_authoring_service = FindingAuthoringService(collection_service=CollectionService(CollectionRepository(), FileCollectionWorkspace(tmp_path)), objective_repository=repository, experiment_query_service=query, experiment_analysis_writer=writer)

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
    repository = ObjectiveRepository()
    objective = ResearchObjective(
        collection_id=_text(COLLECTION_ID) or "",
        objective_id="laser-power-porosity",
        question="How does laser power affect porosity in Ti-6Al-4V?",
        material_scope=("Ti-6Al-4V",),
        variables=("laser power",),
        outcomes=("porosity",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=("doc_a", "doc_b"),
        excluded_document_ids=(),
        confidence=0.0,
        reason=None,
    )
    inputs = (
        PreparedDocumentInput(
            document_id="doc_a", preparation_fingerprint="prepared-a"
        ),
        PreparedDocumentInput(
            document_id="doc_b", preparation_fingerprint="prepared-b"
        ),
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
        async with database.AsyncSessionLocal() as db, db.begin():
            await repository.publish_experiment_analysis(db, *queued.key)

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
    async with database.AsyncSessionLocal() as db, db.begin():
        published_objective, published = await repository.publish_experiment_analysis(db, *queued.key, abstention_reason='no_comparable_evidence', abstention_note='The selected papers report power settings but no comparable porosity measurements.')
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
