from __future__ import annotations

from datetime import datetime, timezone

import pytest

from application.core.objectives.finding_authoring_service import (
    FindingAuthoringService,
)
from domain.core import (
    Finding,
    ObjectiveDocumentEvidence,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperStudyDisposition,
    PreparedDocumentInput,
    ResearchObjective,
)
from infra.persistence.postgres.objective_repository import PostgresObjectiveRepository
from tests.integration.persistence.test_postgres_source_artifacts import (
    COLLECTION_ID,
    _source,
)


pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio

OBJECTIVE_ID = "objective-laser-power-strength"


def _document_inputs() -> tuple[PreparedDocumentInput, ...]:
    return (
        PreparedDocumentInput("doc_a", "fingerprint-doc-a"),
        PreparedDocumentInput("doc_b", "fingerprint-doc-b"),
    )


def _objective() -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": COLLECTION_ID,
            "objective_id": OBJECTIVE_ID,
            "question": "How does laser power affect tensile strength?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["tensile strength"],
            "requested_comparator": "compare reported laser-power conditions",
            "seed_document_ids": ["doc_a", "doc_b"],
            "confidence": 0.9,
            "reason": "Both papers report laser-power conditions and strength.",
            "source_relationship_ids": ["relationship-a", "relationship-b"],
            "rank": 1,
        }
    )


def _authored_objective() -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": COLLECTION_ID,
            "question": "How does scan strategy affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["scan strategy"],
            "outcomes": ["yield strength"],
            "seed_document_ids": ["doc_a"],
            "confidence": 0,
            "origin": "chat_assisted",
            "created_by_user_id": "user_source",
            "created_by_tool_call_id": "call-authored-no-discovery",
        }
    )


def _discovery() -> ObjectiveFactSet:
    return ObjectiveFactSet(
        research_objectives_ready=True,
        document_inputs=_document_inputs(),
        research_objectives=(_objective(),),
        study_dispositions=(
            PaperStudyDisposition.from_mapping(
                {
                    "document_id": "doc_a",
                    "study_id": "study-a",
                    "relationship_id": "relationship-a",
                    "status": "promoted",
                    "objective_id": OBJECTIVE_ID,
                }
            ),
            PaperStudyDisposition.from_mapping(
                {
                    "document_id": "doc_b",
                    "study_id": "study-b",
                    "relationship_id": "relationship-b",
                    "status": "promoted",
                    "objective_id": OBJECTIVE_ID,
                }
            ),
        ),
    )


def _contribution(version: int, document_id: str) -> PaperContribution:
    return PaperContribution.from_mapping(
        {
            "collection_id": COLLECTION_ID,
            "objective_id": OBJECTIVE_ID,
            "analysis_version": version,
            "document_id": document_id,
            "analysis_status": "analyzed",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "contribution_summary": "Reports a controlled laser-power comparison.",
            "material_match": ["Ti-6Al-4V"],
            "changed_variables": ["laser power"],
            "measured_property_scope": ["tensile strength"],
            "test_environment_scope": ["room temperature"],
            "confidence": 0.9,
            "evidence_disposition": "comparable_evidence",
            "routed_source_count": 1,
            "extracted_source_count": 1,
            "comparable_evidence_count": 1,
            "failed_source_count": 0,
        }
    )


def _evidence(version: int, document_id: str, confidence: float) -> ObjectiveEvidence:
    return ObjectiveEvidence.from_mapping(
        {
            "collection_id": COLLECTION_ID,
            "objective_id": OBJECTIVE_ID,
            "analysis_version": version,
            "evidence_id": f"evidence-{document_id}",
            "document_id": document_id,
            "source_kind": "text_window",
            "source_ref": f"block-{document_id}",
            "source_excerpt": "Laser power increased from 100 W to 150 W.",
            "page_numbers": [2],
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "selection_reason": "Reports the variable and measured result.",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": 100,
                    "target_value": 150,
                    "unit": "W",
                }
            ],
            "comparison": {
                "baseline_label": "100 W",
                "target_label": "150 W",
                "axis_names": ["laser power"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "tensile strength",
                "baseline_value": 900,
                "target_value": 950,
                "value": 950,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Tensile strength increased from 900 to 950 MPa.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": confidence,
        }
    )


def _analysis_contributions(version: int) -> tuple[PaperContribution, ...]:
    return tuple(_contribution(version, item.document_id) for item in _document_inputs())


def _analysis_evidence(version: int) -> tuple[ObjectiveEvidence, ...]:
    return (
        _evidence(version, "doc_a", 0.9),
        _evidence(version, "doc_b", 0.8),
    )


def _finding(version: int) -> Finding:
    return Finding.from_mapping(
        {
            "collection_id": COLLECTION_ID,
            "objective_id": OBJECTIVE_ID,
            "analysis_version": version,
            "finding_id": "finding-strength",
            "statement": (
                "Higher laser power was associated with higher tensile strength "
                "under the reported conditions."
            ),
            "factors": ["laser power"],
            "outcome": "tensile strength",
            "direction": "increase",
            "assertion_strength": "associative",
            "attribution_scope": "isolated_effect",
            "synthesis_status": "agreement",
            "certainty": 0.75,
            "display_rank": 0,
            "scientific_context": {},
            "limitations": ["Only the reported process windows are comparable."],
            "paper_contributions": [
                {
                    "document_id": item.document_id,
                    "analysis_status": "analyzed",
                    "supporting_evidence_ids": [f"evidence-{item.document_id}"],
                }
                for item in _document_inputs()
            ],
        }
    )


@pytest.fixture
async def objective_repository(source_repository):
    await source_repository.replace_document(
        COLLECTION_ID,
        _source("doc_a", title="Paper A"),
    )
    await source_repository.replace_document(
        COLLECTION_ID,
        _source("doc_b", title="Paper B"),
    )
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    await repository.replace(COLLECTION_ID, _discovery())
    return repository


async def _queue_and_claim(
    repository: PostgresObjectiveRepository,
):
    objective, queued = await repository.queue_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        document_inputs=_document_inputs(),
        pipeline_version="objective-analysis.v1",
        model_name="test-model",
        prompt_versions={"finding": "v1"},
    )
    claimed = await repository.claim_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        queued.analysis_version,
    )
    assert claimed is not None
    return objective, claimed


async def test_objective_discovery_round_trips_exact_prepared_document_inputs(
    objective_repository,
) -> None:
    restored = await objective_repository.read(COLLECTION_ID)

    assert restored.research_objectives_ready is True
    assert restored.document_inputs == _document_inputs()
    assert len(restored.research_objectives) == 1
    assert restored.research_objectives[0].question == _objective().question
    assert restored.research_objectives[0].seed_document_ids == ("doc_a", "doc_b")


async def test_authored_candidate_persists_without_an_objective_discovery_row(
    source_repository,
) -> None:
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    objective = _authored_objective()

    created = await repository.create_authored_candidate(
        objective,
        created_by_user_id="user_source",
        created_by_tool_call_id="call-authored-no-discovery",
    )

    assert created.rank == 1
    assert await repository.list_objectives(COLLECTION_ID) == (created,)
    assert (await repository.read(COLLECTION_ID)).research_objectives_ready is False


async def test_active_analysis_reuses_only_the_same_document_manifest(
    objective_repository,
) -> None:
    _, first = await objective_repository.queue_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        document_inputs=_document_inputs(),
        pipeline_version="objective-analysis.v1",
        model_name="test-model",
        prompt_versions={"finding": "v1"},
    )
    _, reused = await objective_repository.queue_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        document_inputs=_document_inputs(),
        pipeline_version="objective-analysis.v1",
        model_name="test-model",
        prompt_versions={"finding": "v1"},
    )

    assert reused == first
    with pytest.raises(
        ValueError,
        match="active analysis already uses a different document scope",
    ):
        await objective_repository.queue_analysis(
            COLLECTION_ID,
            OBJECTIVE_ID,
            document_inputs=(_document_inputs()[0],),
            pipeline_version="objective-analysis.v1",
            model_name="test-model",
            prompt_versions={"finding": "v1"},
        )


@pytest.mark.parametrize("claim_before_restart", [False, True])
async def test_restart_interrupts_active_analysis_and_allows_next_version(
    objective_repository,
    claim_before_restart: bool,
) -> None:
    _, active = await objective_repository.queue_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        document_inputs=_document_inputs(),
        pipeline_version="objective-analysis.v1",
        model_name="test-model",
        prompt_versions={"finding": "v1"},
    )
    if claim_before_restart:
        claimed = await objective_repository.claim_analysis(
            COLLECTION_ID,
            OBJECTIVE_ID,
            active.analysis_version,
        )
        assert claimed is not None
        assert claimed.status == "running"

    interrupted_count = await objective_repository.interrupt_active_analyses()
    interrupted = await objective_repository.read_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        active.analysis_version,
    )
    _, retry = await objective_repository.queue_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        document_inputs=_document_inputs(),
        pipeline_version="objective-analysis.v1",
        model_name="test-model",
        prompt_versions={"finding": "v1"},
    )

    assert interrupted_count == 1
    assert interrupted is not None
    assert interrupted.status == "failed"
    assert interrupted.error_code == "analysis_interrupted"
    assert retry.analysis_version == active.analysis_version + 1
    assert retry.status == "queued"


async def test_analysis_publish_preserves_manifest_and_source_backed_results(
    objective_repository,
) -> None:
    _, analysis = await _queue_and_claim(objective_repository)
    contributions = _analysis_contributions(analysis.analysis_version)
    evidence = _analysis_evidence(analysis.analysis_version)
    finding = _finding(analysis.analysis_version)

    objective, published = await objective_repository.publish_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
        contributions=contributions,
        evidence_records=evidence,
        findings=(finding,),
    )

    assert objective.published_analysis_version == analysis.analysis_version
    assert published.status == "succeeded"
    assert published.document_inputs == _document_inputs()
    assert await objective_repository.read_published_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
    ) == published
    assert await objective_repository.list_contributions(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    ) == contributions
    assert await objective_repository.list_evidence(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    ) == (evidence, len(evidence))
    assert await objective_repository.list_findings(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    ) == ((finding,), 1)


async def test_authored_finding_publishes_new_snapshot_without_mutating_source(
    objective_repository,
) -> None:
    _, analysis = await _queue_and_claim(objective_repository)
    await objective_repository.publish_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
        contributions=_analysis_contributions(analysis.analysis_version),
        evidence_records=_analysis_evidence(analysis.analysis_version),
        findings=(_finding(analysis.analysis_version),),
    )

    class _OwnedCollectionService:
        async def get_collection_for_user(self, collection_id, user_id):
            assert collection_id == COLLECTION_ID
            assert user_id == "user_source"
            return {"collection_id": collection_id}

    service = FindingAuthoringService(
        collection_service=_OwnedCollectionService(),
        objective_repository=objective_repository,
    )
    result = await service.create_version(
        collection_id=COLLECTION_ID,
        objective_id=OBJECTIVE_ID,
        source_analysis_version=1,
        statement=(
            "Across both papers, higher laser power was associated with "
            "higher tensile strength in the reported windows."
        ),
        assertion_strength="associative",
        supporting_evidence_ids=("evidence-doc_a", "evidence-doc_b"),
        contradicting_evidence_ids=(),
        context_evidence_ids=(),
        condition_boundary_evidence_ids=(),
        limitations=("Limited to the two reported process windows.",),
        parent_finding_id="finding-strength",
        abstention_reason=None,
        created_by_user_id="user_source",
    )

    assert result.finding is not None
    assert result.analysis.analysis_version == 2
    assert result.finding.origin == "hybrid"
    original = await objective_repository.read_finding(
        COLLECTION_ID, OBJECTIVE_ID, 1, "finding-strength"
    )
    assert original == _finding(1)
    version_two, total = await objective_repository.list_findings(
        COLLECTION_ID, OBJECTIVE_ID, 2
    )
    assert total == 2
    assert version_two[-1] == result.finding
    cloned_evidence, evidence_total = await objective_repository.list_evidence(
        COLLECTION_ID,
        OBJECTIVE_ID,
        2,
        finding_id=result.finding.finding_id,
    )
    assert evidence_total == 2
    assert {item.analysis_version for item in cloned_evidence} == {2}
    assert {item.source_ref for item in cloned_evidence} == {
        "block-doc_a",
        "block-doc_b",
    }


async def test_objective_document_evidence_round_trips_independent_status_and_payload(
    objective_repository,
) -> None:
    _, analysis = await _queue_and_claim(objective_repository)
    started_at = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)
    completed_at = datetime(2026, 8, 27, 8, 2, tzinfo=timezone.utc)
    running = ObjectiveDocumentEvidence.start(
        collection_id=COLLECTION_ID,
        objective_id=OBJECTIVE_ID,
        document_id="doc_a",
        input_fingerprint="objective-doc-a-input-v1",
        analysis_version=analysis.analysis_version,
        extraction_version="objective-document-evidence.v1",
        model_name="test-model",
        started_at=started_at,
    )

    await objective_repository.write_document_evidence(running)

    assert await objective_repository.read_document_evidence(
        COLLECTION_ID,
        OBJECTIVE_ID,
        "doc_a",
        "objective-doc-a-input-v1",
    ) == running
    assert await objective_repository.read_document_evidence(
        COLLECTION_ID,
        OBJECTIVE_ID,
        "doc_a",
        "another-input",
    ) is None

    succeeded = running.succeed(
        contribution=_contribution(analysis.analysis_version, "doc_a"),
        evidence_records=(
            _evidence(analysis.analysis_version, "doc_a", 0.9),
        ),
        completed_at=completed_at,
    )
    await objective_repository.write_document_evidence(succeeded)

    restored = await objective_repository.read_document_evidence(
        COLLECTION_ID,
        OBJECTIVE_ID,
        "doc_a",
        "objective-doc-a-input-v1",
    )
    assert restored == succeeded
    assert restored is not None
    assert restored.status == "succeeded"
    assert restored.contribution == _contribution(analysis.analysis_version, "doc_a")
    assert restored.evidence_records == (
        _evidence(analysis.analysis_version, "doc_a", 0.9),
    )

    failed_running = ObjectiveDocumentEvidence.start(
        collection_id=COLLECTION_ID,
        objective_id=OBJECTIVE_ID,
        document_id="doc_b",
        input_fingerprint="objective-doc-b-input-v1",
        analysis_version=analysis.analysis_version,
        extraction_version="objective-document-evidence.v1",
        model_name="test-model",
        started_at=started_at,
    )
    failed = failed_running.fail(
        contribution=PaperContribution.from_mapping(
            {
                "collection_id": COLLECTION_ID,
                "objective_id": OBJECTIVE_ID,
                "analysis_version": analysis.analysis_version,
                "document_id": "doc_b",
                "analysis_status": "failed",
                "relevance": "uncertain",
                "paper_role": "uncertain",
                "warnings": ["Evidence extraction failed for this paper."],
                "confidence": 0,
            }
        ),
        error_code="provider_error",
        error_message="provider unavailable",
        completed_at=completed_at,
    )
    await objective_repository.write_document_evidence(failed)

    assert await objective_repository.read_document_evidence(
        COLLECTION_ID,
        OBJECTIVE_ID,
        "doc_b",
        "objective-doc-b-input-v1",
    ) == failed
