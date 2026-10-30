from __future__ import annotations

from dataclasses import replace
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.capabilities.finding_review import (
    CurateFindingCapability,
    CurateFindingToolRequest,
)
from application.evaluation import finding_feedback_service
from application.evaluation.core_evaluation_service import CoreEvaluationService
from application.evaluation.finding_feedback_service import parse_curated_finding
from application.evaluation.gold_service import EvaluationGoldService
from application.evaluation.prediction_snapshot_service import (
    CoreArtifactsNotReadyForEvaluationError,
    EvaluationPredictionSnapshotService,
)
from domain.core import (
    Finding,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperResearchMap,
    PaperStudyDisposition,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    Finding,
    FindingPaperContribution,
)
from domain.core.research_objective import (
    ObjectiveEvidence,
    PaperContribution,
    PaperResearchRelationship,
    PaperResearchScope,
    PaperResearchSourceRef,
    PaperStudyDisposition,
    PaperStudyDispositionStatus,
    ResearchObjective,
    normalize_objective_terms,
)
from domain.core.scientific_fact import (
    ScientificAttribute,
    ScientificComparison,
    ScientificContext,
    ScientificResult,
    ScientificVariable,
)
from domain.evaluation import EvaluationGoldItem, FindingCuration, FindingFeedback
from domain.source import SourceBlock, SourceDocument
from exceptions import RequestInvalidException, ResourceConflictException
from infra.persistence.postgres.models.objective import ObjectiveAnalysisRecord
from repositories.evaluation_repository import EvaluationRepository
from repositories.finding_review_repository import FindingReviewRepository
from repositories.objective_repository import ObjectiveRepository
from repositories.source_artifact_repository import SourceArtifactRepository
from sqlalchemy import select

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


_TEMPERATURE_STRENGTH_RELATIONSHIP_ID = "relationship-doc-1-temperature-strength"
_TEMPERATURE_STRENGTH_STUDY_ID = "study-doc-1-temperature-strength"
_DOC_1_INPUT = PreparedDocumentInput(
    document_id="doc-1",
    preparation_fingerprint="fingerprint-doc-1",
)


class FakeCollectionService:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or {"col-gold"}
        self.documents_by_collection = {
            "col-gold": [
                {
                    "document_id": "doc-1",
                    "original_filename": "paper-1.pdf",
                    "stored_filename": "paper-1.pdf",
                    "storage_key": "col-gold/input/paper-1.pdf",
                }
            ]
        }

    async def get_collection(self, collection_id: str) -> dict:
        if collection_id not in self.existing:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return {
            "collection_id": collection_id,
            "name": "Gold collection",
            "documents": list(self.documents_by_collection.get(collection_id, [])),
        }


class _RecordedExperimentProjection:
    def __init__(self, *, finding, evidence, contribution) -> None:
        self.finding_value = finding
        self.evidence_value = evidence
        self.contribution_value = contribution
        self.finding = {
            "collection_id": finding.collection_id,
            "objective_id": finding.objective_id,
            "analysis_version": finding.analysis_version,
            "finding_id": finding.finding_id,
            "statement": finding.statement,
            "factors": list(finding.factors),
            "outcome": finding.outcome,
            "direction": finding.direction,
            "assertion_strength": finding.assertion_strength,
            "attribution_scope": finding.attribution_scope,
            "synthesis_status": finding.synthesis_status,
            "certainty": finding.certainty,
            "display_rank": finding.display_rank,
            "mechanisms": [
                {
                    "source_term": mechanism.source_term,
                    "relation_type": mechanism.relation_type,
                    "target_term": mechanism.target_term,
                    "direction": mechanism.direction,
                    "assertion_strength": mechanism.assertion_strength,
                    "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
                }
                for mechanism in finding.mechanisms
            ],
            "scientific_context": {
                "material": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in finding.scientific_context.material
                ],
                "sample": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in finding.scientific_context.sample
                ],
                "process": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in finding.scientific_context.process
                ],
                "test": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in finding.scientific_context.test
                ],
            },
            "limitations": list(finding.limitations),
            "paper_contributions": [
                {
                    "document_id": contribution.document_id,
                    "analysis_status": contribution.analysis_status,
                    "supporting_evidence_ids": list(
                        contribution.supporting_evidence_ids
                    ),
                    "contradicting_evidence_ids": list(
                        contribution.contradicting_evidence_ids
                    ),
                    "context_evidence_ids": list(contribution.context_evidence_ids),
                    "condition_boundary_evidence_ids": list(
                        contribution.condition_boundary_evidence_ids
                    ),
                }
                for contribution in finding.paper_contributions
            ],
            "origin": finding.origin,
            "source_analysis_version": finding.source_analysis_version,
            "parent_finding_id": finding.parent_finding_id,
            "created_by_user_id": finding.created_by_user_id,
            "created_by_tool_call_id": finding.created_by_tool_call_id,
            "created_at": (
                finding.created_at.isoformat() if finding.created_at else None
            ),
            **(
                {"selection_ids": list(finding.selection_ids)}
                if finding.selection_ids
                else {}
            ),
            **(
                {"comparison_group_ids": list(finding.comparison_group_ids)}
                if finding.comparison_group_ids
                else {}
            ),
            **({"warnings": list(finding.warnings)} if finding.warnings else {}),
        }
        self.evidence = {
            "collection_id": evidence.collection_id,
            "objective_id": evidence.objective_id,
            "analysis_version": evidence.analysis_version,
            "evidence_id": evidence.evidence_id,
            "document_id": evidence.document_id,
            "source_kind": evidence.source_kind,
            "source_ref": evidence.source_ref,
            "source_excerpt": evidence.source_excerpt,
            "page_numbers": list(evidence.page_numbers),
            "evidence_role": evidence.evidence_role,
            "selection_status": evidence.selection_status,
            "selection_reason": evidence.selection_reason,
            "evidence_status": evidence.evidence_status,
            "evidence_status_reason": evidence.evidence_status_reason,
            "changed_variables": [
                {
                    "name": variable.name,
                    "baseline_value": variable.baseline_value,
                    "target_value": variable.target_value,
                    "unit": variable.unit,
                }
                for variable in evidence.changed_variables
            ],
            "comparison": (
                {
                    "baseline_label": evidence.comparison.baseline_label,
                    "target_label": evidence.comparison.target_label,
                    "axis_names": list(evidence.comparison.axis_names),
                    "comparable": evidence.comparison.comparable,
                    "incomparability_reasons": list(
                        evidence.comparison.incomparability_reasons
                    ),
                }
                if evidence.comparison
                else None
            ),
            "reported_result": (
                {
                    "outcome": evidence.reported_result.outcome,
                    "value": evidence.reported_result.value,
                    "baseline_value": evidence.reported_result.baseline_value,
                    "target_value": evidence.reported_result.target_value,
                    "unit": evidence.reported_result.unit,
                    "direction": evidence.reported_result.direction,
                    "result_text": evidence.reported_result.result_text,
                    "result_kind": evidence.reported_result.result_kind,
                }
                if evidence.reported_result
                else None
            ),
            "attribution_scope": evidence.attribution_scope,
            "scientific_context": {
                "material": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in evidence.scientific_context.material
                ],
                "sample": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in evidence.scientific_context.sample
                ],
                "process": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in evidence.scientific_context.process
                ],
                "test": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in evidence.scientific_context.test
                ],
            },
            "resolution_status": evidence.resolution_status,
            "failure_reason": evidence.failure_reason,
            "confidence": evidence.confidence,
            "origin": evidence.origin,
            "source_analysis_version": evidence.source_analysis_version,
            "supersedes_evidence_id": evidence.supersedes_evidence_id,
            "superseded_by_evidence_id": evidence.superseded_by_evidence_id,
            "created_by_user_id": evidence.created_by_user_id,
            "created_by_tool_call_id": evidence.created_by_tool_call_id,
            "created_at": (
                evidence.created_at.isoformat()
                if evidence.created_at is not None
                else None
            ),
            "authoring_note": evidence.authoring_note,
            **({"warnings": list(evidence.warnings)} if evidence.warnings else {}),
            **(
                {
                    "related_source_refs": [
                        dict(item) for item in evidence.related_source_refs
                    ]
                }
                if evidence.related_source_refs or evidence.related_source_refs_explicit
                else {}
            ),
        }
        self.contribution = {
            "collection_id": contribution.collection_id,
            "objective_id": contribution.objective_id,
            "analysis_version": contribution.analysis_version,
            "document_id": contribution.document_id,
            "analysis_status": contribution.analysis_status,
            "relevance": contribution.relevance,
            "paper_role": contribution.paper_role,
            "contribution_summary": contribution.contribution_summary,
            "material_match": list(contribution.material_match),
            "changed_variables": list(contribution.changed_variables),
            "measured_property_scope": list(contribution.measured_property_scope),
            "test_environment_scope": list(contribution.test_environment_scope),
            "exclusion_reason": contribution.exclusion_reason,
            "warnings": list(contribution.warnings),
            "confidence": contribution.confidence,
            "evidence_disposition": contribution.evidence_disposition,
            "routed_source_count": contribution.routed_source_count,
            "extracted_source_count": contribution.extracted_source_count,
            "comparable_evidence_count": contribution.comparable_evidence_count,
            "failed_source_count": contribution.failed_source_count,
            "uninspected_source_count": contribution.uninspected_source_count,
            "evidence_disposition_reason": contribution.evidence_disposition_reason,
            "evidence_status_counts": {
                status: count for status, count in contribution.evidence_status_counts
            },
            "inspected_source_refs": [
                {
                    "source_kind": source_ref.source_kind,
                    "source_ref": source_ref.source_ref,
                    "source_digest": source_ref.source_digest,
                }
                for source_ref in contribution.inspected_source_refs
            ],
        }

    async def read_analysis_records(
        self, collection_id, objective_id, analysis_version
    ):
        assert (collection_id, objective_id, analysis_version) == (
            "col-gold",
            "obj-1",
            1,
        )
        return (self.finding_value,), (self.evidence_value,), (self.contribution_value,)

    async def list_findings(
        self, collection_id, objective_id, analysis_version, *, offset=0, limit=50
    ):
        assert (collection_id, objective_id, analysis_version) == (
            "col-gold",
            "obj-1",
            1,
        )
        records = (self.finding,)
        return records[offset : offset + limit], len(records)

    async def read_finding(
        self, collection_id, objective_id, analysis_version, finding_id
    ):
        assert (collection_id, objective_id, analysis_version, finding_id) == (
            "col-gold",
            "obj-1",
            1,
            "finding-1",
        )
        return self.finding

    async def list_evidence(
        self,
        collection_id,
        objective_id,
        analysis_version,
        *,
        finding_id=None,
        offset=0,
        limit=100,
    ):
        assert (collection_id, objective_id, analysis_version) == (
            "col-gold",
            "obj-1",
            1,
        )
        assert finding_id in {None, "finding-1"}
        records = (self.evidence,)
        return records[offset : offset + limit], len(records)

    async def list_contributions(self, collection_id, objective_id, analysis_version):
        assert (collection_id, objective_id, analysis_version) == (
            "col-gold",
            "obj-1",
            1,
        )
        return (self.contribution,)


async def test_evaluation_gold_service_registers_gold_set_for_collection(
    *, postgres_session_factory
):
    repository = EvaluationRepository()
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=repository,
    )

    gold_set = await service.register_gold_set(
        collection_id="col-gold",
        gold_id="gold-v1",
        metadata={},
        items=[
            EvaluationGoldItem(
                gold_item_id="gold-1",
                gold_id="gold-v1",
                document_id="doc-1",
                family="measurement_results",
                item_key="doc-1:sample-a:yield_strength",
                payload={"metric": "yield_strength", "value": 520, "unit": "MPa"},
            )
        ],
    )

    assert await repository.read_gold_set("gold-v1") == gold_set
    assert (await repository.list_gold_items("gold-v1"))[0].gold_id == "gold-v1"
    assert (await repository.list_gold_items("gold-v1"))[0].payload["value"] == 520


async def test_evaluation_gold_service_accepts_collection_file_storage_key(
    *, postgres_session_factory
):
    repository = EvaluationRepository()
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=repository,
    )

    await service.register_gold_set(
        collection_id="col-gold",
        gold_id="gold-by-storage-key",
        items=[
            EvaluationGoldItem(
                gold_item_id="gold-storage-key-1",
                gold_id="gold-by-storage-key",
                document_id="col-gold/input/paper-1.pdf",
                family="measurement_results",
                item_key="paper-1:sample-a:yield_strength",
                payload={"metric": "yield_strength", "value": 520, "unit": "MPa"},
            )
        ],
    )

    assert (await repository.list_gold_items("gold-by-storage-key"))[
        0
    ].document_id == "col-gold/input/paper-1.pdf"


async def test_evaluation_gold_service_rejects_missing_collection(
    *, postgres_session_factory
):
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(existing=set()),
        evaluation_repository=EvaluationRepository(),
    )

    with pytest.raises(FileNotFoundError):
        await service.register_gold_set(
            collection_id="missing",
            gold_id="gold-v1",
            items=[],
        )


async def test_evaluation_gold_service_rejects_gold_item_outside_collection(
    *, postgres_session_factory
):
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=EvaluationRepository(),
    )

    with pytest.raises(ValueError, match="gold item document is not in collection"):
        await service.register_gold_set(
            collection_id="col-gold",
            gold_id="gold-v1",
            items=[
                EvaluationGoldItem(
                    gold_item_id="gold-1",
                    gold_id="gold-v1",
                    document_id="doc-outside",
                    family="measurement_results",
                    item_key="doc-outside:sample-a:yield_strength",
                    payload={"metric": "yield_strength", "value": 520, "unit": "MPa"},
                )
            ],
        )


async def _published_objective_repository(
    *, postgres_session_factory
) -> ObjectiveRepository:
    repository = ObjectiveRepository()
    objective = ResearchObjective(
        collection_id="col-gold",
        objective_id="obj-1",
        question="How does temperature affect strength?",
        material_scope=("Alloy A",),
        variables=("temperature",),
        outcomes=("strength",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=("doc-1",),
        excluded_document_ids=(),
        confidence=0.9,
        reason=None,
        source_relationship_ids=normalize_objective_terms(
            [_TEMPERATURE_STRENGTH_RELATIONSHIP_ID]
        ),
        rank=1,
    )
    skim = PaperResearchMap(
        document_id="doc-1",
        doc_role="experimental",
        studies=(
            PaperResearchScope(
                study_id=_TEMPERATURE_STRENGTH_STUDY_ID,
                document_id="doc-1",
                design_type="experimental",
                claim_scope="current_work",
                experiment_label=None,
                material_scope=objective.material_scope,
                process_context=(),
                relationships=(
                    PaperResearchRelationship(
                        relationship_id=_TEMPERATURE_STRENGTH_RELATIONSHIP_ID,
                        varied_factors=objective.variables,
                        outcome=objective.outcomes[0],
                        source_refs=(
                            PaperResearchSourceRef(
                                source_kind="block", source_ref="block-7"
                            ),
                        ),
                        confidence=0.9,
                    ),
                ),
                confidence=0.9,
            ),
        ),
        evidence_density="high",
        confidence=0.9,
        warnings=(),
    )
    await repository.replace(
        "col-gold",
        ObjectiveFactSet(
            research_objectives_ready=True,
            document_inputs=(_DOC_1_INPUT,),
            research_objectives=(objective,),
            study_dispositions=(
                PaperStudyDisposition(
                    document_id="doc-1",
                    study_id=_TEMPERATURE_STRENGTH_STUDY_ID or "",
                    relationship_id=_TEMPERATURE_STRENGTH_RELATIONSHIP_ID or "",
                    status=PaperStudyDispositionStatus("promoted"),
                    objective_id=objective.objective_id,
                ),
            ),
        ),
    )
    _, analysis = await repository.queue_analysis(
        "col-gold",
        "obj-1",
        document_inputs=(_DOC_1_INPUT,),
        pipeline_version="test.v1",
        model_name="model-1",
        prompt_versions={},
    )
    running = await repository.claim_analysis(
        "col-gold",
        "obj-1",
        analysis.analysis_version,
    )
    assert running is not None
    evidence = ObjectiveEvidence(
        collection_id="col-gold",
        objective_id="obj-1",
        analysis_version=1,
        evidence_id="evidence-1",
        document_id="doc-1",
        source_kind="text_window",
        source_ref="block-7",
        source_excerpt="At 500 C, tensile strength increased to 620 MPa.",
        page_numbers=(7,),
        related_source_refs=(),
        evidence_role="direct_result",
        selection_status="extracted",
        selection_reason=None,
        changed_variables=(
            ScientificVariable(
                name="temperature", baseline_value=400, target_value=500, unit="C"
            ),
        ),
        comparison=ScientificComparison(
            baseline_label="400 C",
            target_label="500 C",
            axis_names=("temperature",),
            comparable=True,
        ),
        reported_result=ScientificResult(
            outcome="strength",
            value=620,
            unit="MPa",
            direction="increase",
            result_text="At 500 C, tensile strength increased to 620 MPa.",
        ),
        attribution_scope="isolated_effect",
        scientific_context=ScientificContext(
            material=(ScientificAttribute(name="alloy", value="Alloy A"),),
            test=(ScientificAttribute(name="test", value="tensile"),),
        ),
        resolution_status="resolved",
        failure_reason=None,
        confidence=0.9,
    )
    finding = Finding(
        collection_id="col-gold",
        objective_id="obj-1",
        analysis_version=1,
        finding_id="finding-1",
        statement="Higher temperature was associated with greater strength.",
        factors=("temperature",),
        outcome="strength",
        direction="increase",
        assertion_strength="associative",
        attribution_scope="isolated_effect",
        synthesis_status="insufficient_confirmation",
        certainty=0.5,
        display_rank=0,
        mechanisms=(),
        scientific_context=ScientificContext(
            material=(ScientificAttribute(name="alloy", value="Alloy A"),),
            test=(ScientificAttribute(name="test", value="tensile"),),
        ),
        limitations=("Only one paper directly supports this Finding.",),
        paper_contributions=(
            FindingPaperContribution(
                document_id="doc-1",
                analysis_status="analyzed",
                supporting_evidence_ids=("evidence-1",),
            ),
        ),
    )
    await repository.publish_analysis(
        "col-gold",
        "obj-1",
        1,
        contributions=(
            PaperContribution(
                collection_id="col-gold",
                objective_id="obj-1",
                analysis_version=1,
                document_id="doc-1",
                analysis_status="analyzed",
                relevance="high",
                paper_role="primary_experiment",
                contribution_summary=None,
                material_match=(),
                changed_variables=(),
                measured_property_scope=(),
                test_environment_scope=(),
                exclusion_reason=None,
                warnings=(),
                confidence=0.9,
            ),
        ),
        evidence_records=(evidence,),
        findings=(finding,),
    )
    return repository


async def _finding_feedback_service(*, postgres_session_factory) -> ModuleType:
    finding_feedback_service.FindingReviewRepo = FindingReviewRepository()
    finding_feedback_service.ObjectiveRepo = await _published_objective_repository(
        postgres_session_factory=postgres_session_factory
    )
    return finding_feedback_service


def _prediction_snapshot_service(
    objective_repository: ObjectiveRepository,
) -> tuple[EvaluationPredictionSnapshotService, EvaluationRepository]:
    evaluation_repository = EvaluationRepository()
    return (
        EvaluationPredictionSnapshotService(
            collection_service=FakeCollectionService(),
            objective_repository=objective_repository,
            evaluation_repository=evaluation_repository,
        ),
        evaluation_repository,
    )


async def test_prediction_snapshot_exports_published_findings_with_exact_evidence(
    *, postgres_session_factory
) -> None:
    service, evaluation_repository = _prediction_snapshot_service(
        await _published_objective_repository(
            postgres_session_factory=postgres_session_factory
        )
    )

    snapshot = await service.create_core_snapshot(
        collection_id="col-gold",
        fact_source="objective_first",
        snapshot_id="snapshot-1",
    )

    assert (
        await evaluation_repository.read_prediction_snapshot(snapshot.snapshot_id)
        == snapshot
    )
    assert snapshot.artifact_counts["published_objective_analyses"] == 1
    assert snapshot.artifact_counts["objective_findings"] == 1
    assert snapshot.artifact_counts["objective_evidence"] == 1
    assert "objective_evidence_units" not in snapshot.artifact_counts
    assert "objective_logic_chains" not in snapshot.artifact_counts
    assert len(snapshot.items) == 1
    item = snapshot.items[0]
    assert item.family == "objective_findings"
    assert item.item_key == "obj-1:v1:finding-1"
    assert item.payload["analysis_version"] == 1
    assert item.payload["finding_id"] == "finding-1"
    assert item.payload["evidence"][0]["source_excerpt"] == (
        "At 500 C, tensile strength increased to 620 MPa."
    )
    assert item.source_refs == (
        {
            "evidence_id": "evidence-1",
            "document_id": "doc-1",
            "source_kind": "text_window",
            "source_ref": "block-7",
            "source_excerpt": "At 500 C, tensile strength increased to 620 MPa.",
            "page_numbers": [7],
            "related_source_refs": [],
        },
    )


async def test_experiment_projection_drives_snapshot_and_feedback_reads(
    *, postgres_session_factory
) -> None:
    repository = await _published_objective_repository(
        postgres_session_factory=postgres_session_factory
    )
    analysis = await repository.read_analysis("col-gold", "obj-1", 1)
    assert analysis is not None
    async with postgres_session_factory.begin() as session:
        row = await session.scalar(
            select(ObjectiveAnalysisRecord).where(
                ObjectiveAnalysisRecord.collection_id == "col-gold",
                ObjectiveAnalysisRecord.objective_id == "obj-1",
                ObjectiveAnalysisRecord.analysis_version == 1,
            )
        )
        row.payload = {
            **row.payload,
            **{"scientific_record_source": "experiment_graph"},
        }
    finding = await repository.read_finding("col-gold", "obj-1", 1, "finding-1")
    evidence, _ = await repository.list_evidence("col-gold", "obj-1", 1)
    contributions = await repository.list_contributions("col-gold", "obj-1", 1)
    assert finding is not None and len(evidence) == len(contributions) == 1
    projection = _RecordedExperimentProjection(
        finding=finding,
        evidence=evidence[0],
        contribution=contributions[0],
    )

    async def reject_legacy_read(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("legacy scientific-fact repository was read")

    repository.list_findings = reject_legacy_read
    repository.read_finding = reject_legacy_read
    repository.list_evidence = reject_legacy_read
    repository.list_contributions = reject_legacy_read

    evaluation_repository = EvaluationRepository()
    snapshot_service = EvaluationPredictionSnapshotService(
        collection_service=FakeCollectionService(),
        objective_repository=repository,
        evaluation_repository=evaluation_repository,
        experiment_projection=projection,
    )
    finding_feedback_service.FindingReviewRepo = FindingReviewRepository()
    finding_feedback_service.ObjectiveRepo = repository
    finding_feedback_service.experiment_compatibility_projection = projection
    feedback_service = finding_feedback_service

    snapshot = await snapshot_service.create_core_snapshot(
        collection_id="col-gold",
        snapshot_id="experiment-snapshot",
    )
    dataset = await feedback_service.export_dataset(
        collection_id="col-gold", objective_id="obj-1", user_id="user-1"
    )

    assert snapshot.items[0].payload["finding_id"] == "finding-1"
    assert dataset["items"][0]["evidence"][0]["evidence_id"] == "evidence-1"


async def test_authored_analysis_uses_its_snapshot_even_when_projection_is_available(
    *, postgres_session_factory
) -> None:
    repository = await _published_objective_repository(
        postgres_session_factory=postgres_session_factory
    )
    source = await repository.read_analysis("col-gold", "obj-1", 1)
    assert source is not None
    from tests.support.postgres import seed_user

    await seed_user(postgres_session_factory, "researcher-1")
    evidence, _ = await repository.list_evidence("col-gold", "obj-1", 1)
    findings, _ = await repository.list_findings("col-gold", "obj-1", 1)
    contributions = await repository.list_contributions("col-gold", "obj-1", 1)
    await repository.queue_analysis(
        "col-gold",
        "obj-1",
        document_inputs=source.document_inputs,
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
        origin="human_authored",
        source_analysis_version=1,
        created_by_user_id="researcher-1",
    )
    await repository.claim_analysis("col-gold", "obj-1", 2)
    await repository.publish_analysis(
        "col-gold",
        "obj-1",
        2,
        contributions=tuple(
            replace(item, analysis_version=2) for item in contributions
        ),
        evidence_records=tuple(replace(item, analysis_version=2) for item in evidence),
        findings=tuple(replace(item, analysis_version=2) for item in findings),
    )

    class RejectingProjection:
        async def list_findings(self, *args, **kwargs):  # noqa: ARG002
            pytest.fail("authored analysis must not read the experiment projection")

        async def list_evidence(self, *args, **kwargs):  # noqa: ARG002
            pytest.fail("authored analysis must not read the experiment projection")

        async def read_finding(self, *args, **kwargs):  # noqa: ARG002
            pytest.fail("authored analysis must not read the experiment projection")

        async def list_contributions(self, *args, **kwargs):  # noqa: ARG002
            pytest.fail("authored analysis must not read the experiment projection")

    snapshot_service, _ = _prediction_snapshot_service(repository)
    snapshot_service.experiment_projection = RejectingProjection()
    finding_feedback_service.FindingReviewRepo = FindingReviewRepository()
    finding_feedback_service.ObjectiveRepo = repository
    finding_feedback_service.experiment_compatibility_projection = RejectingProjection()
    feedback_service = finding_feedback_service

    snapshot = await snapshot_service.create_core_snapshot(
        collection_id="col-gold", snapshot_id="authored-snapshot"
    )
    dataset = await feedback_service.export_dataset(
        collection_id="col-gold", objective_id="obj-1", user_id="user-1"
    )

    assert snapshot.items[0].payload["finding_id"] == "finding-1"
    assert dataset["items"][0]["evidence"][0]["evidence_id"] == "evidence-1"


async def test_prediction_snapshot_rejects_unconfirmed_objective(
    *, postgres_session_factory
) -> None:
    objective = ResearchObjective(
        collection_id="col-gold",
        objective_id="obj-candidate",
        question="How does temperature affect strength?",
        material_scope=("Alloy A",),
        variables=("temperature",),
        outcomes=("strength",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=("doc-1",),
        excluded_document_ids=(),
        confidence=0.9,
        reason=None,
        source_relationship_ids=normalize_objective_terms(
            [_TEMPERATURE_STRENGTH_RELATIONSHIP_ID]
        ),
        rank=1,
    )
    skim = PaperResearchMap(
        document_id="doc-1",
        doc_role="experimental",
        studies=(
            PaperResearchScope(
                study_id=_TEMPERATURE_STRENGTH_STUDY_ID,
                document_id="doc-1",
                design_type="experimental",
                claim_scope="current_work",
                experiment_label=None,
                material_scope=objective.material_scope,
                process_context=(),
                relationships=(
                    PaperResearchRelationship(
                        relationship_id=_TEMPERATURE_STRENGTH_RELATIONSHIP_ID,
                        varied_factors=objective.variables,
                        outcome=objective.outcomes[0],
                        source_refs=(
                            PaperResearchSourceRef(
                                source_kind="block", source_ref="block-7"
                            ),
                        ),
                        confidence=0.9,
                    ),
                ),
                confidence=0.9,
            ),
        ),
        evidence_density="high",
        confidence=0.9,
        warnings=(),
    )
    repository = ObjectiveRepository()
    await repository.replace(
        "col-gold",
        ObjectiveFactSet(
            research_objectives_ready=True,
            document_inputs=(_DOC_1_INPUT,),
            research_objectives=(objective,),
            study_dispositions=(
                PaperStudyDisposition(
                    document_id="doc-1",
                    study_id=_TEMPERATURE_STRENGTH_STUDY_ID or "",
                    relationship_id=_TEMPERATURE_STRENGTH_RELATIONSHIP_ID or "",
                    status=PaperStudyDispositionStatus("promoted"),
                    objective_id=objective.objective_id,
                ),
            ),
        ),
    )
    service, _evaluation_repository = _prediction_snapshot_service(repository)

    with pytest.raises(CoreArtifactsNotReadyForEvaluationError):
        await service.create_core_snapshot(
            collection_id="col-gold",
            fact_source="objective_first",
        )


async def test_finding_feedback_rejects_stale_analysis_version(
    *, postgres_session_factory
) -> None:
    service = await _finding_feedback_service(
        postgres_session_factory=postgres_session_factory
    )

    with pytest.raises(ResourceConflictException, match="published analysis version"):
        await service.record_feedback(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=2,
            finding_id="finding-1",
            review_status="correct",
            issue_type="none",
            user_id="user-1",
        )


async def test_finding_feedback_rejects_inconsistent_review_decisions(
    *, postgres_session_factory
) -> None:
    service = await _finding_feedback_service(
        postgres_session_factory=postgres_session_factory
    )

    with pytest.raises(
        RequestInvalidException, match="correct finding feedback cannot report"
    ):
        await service.record_feedback(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=1,
            finding_id="finding-1",
            review_status="correct",
            issue_type="evidence_not_grounded",
            user_id="user-1",
        )
    with pytest.raises(
        RequestInvalidException, match="partial finding feedback requires an issue"
    ):
        await service.record_feedback(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=1,
            finding_id="finding-1",
            review_status="partial",
            issue_type="none",
            user_id="user-1",
        )


def test_review_input_rejects_unknown_status_values() -> None:
    from controllers.core.finding_review_routes import (
        FindingCurationCreateRequest,
        FindingFeedbackCreateRequest,
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="review_status"):
        FindingFeedbackCreateRequest(analysis_version=1, review_status="bogus")
    with pytest.raises(ValidationError, match="curated_status"):
        FindingCurationCreateRequest(
            analysis_version=1,
            curated_status="bogus",
            curated_finding={},
        )


async def test_finding_curation_rejects_evidence_outside_published_finding(
    *, postgres_session_factory
) -> None:
    service = await _finding_feedback_service(
        postgres_session_factory=postgres_session_factory
    )
    published = await service.ObjectiveRepo.read_finding(
        "col-gold", "obj-1", 1, "finding-1"
    )
    assert published is not None
    curated = {
        "collection_id": published.collection_id,
        "objective_id": published.objective_id,
        "analysis_version": published.analysis_version,
        "finding_id": published.finding_id,
        "statement": published.statement,
        "factors": list(published.factors),
        "outcome": published.outcome,
        "direction": published.direction,
        "assertion_strength": published.assertion_strength,
        "attribution_scope": published.attribution_scope,
        "synthesis_status": published.synthesis_status,
        "certainty": published.certainty,
        "display_rank": published.display_rank,
        "mechanisms": [
            {
                "source_term": mechanism.source_term,
                "relation_type": mechanism.relation_type,
                "target_term": mechanism.target_term,
                "direction": mechanism.direction,
                "assertion_strength": mechanism.assertion_strength,
                "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
            }
            for mechanism in published.mechanisms
        ],
        "scientific_context": {
            "material": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.material
            ],
            "sample": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.sample
            ],
            "process": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.process
            ],
            "test": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.test
            ],
        },
        "limitations": list(published.limitations),
        "paper_contributions": [
            {
                "document_id": contribution.document_id,
                "analysis_status": contribution.analysis_status,
                "supporting_evidence_ids": list(contribution.supporting_evidence_ids),
                "contradicting_evidence_ids": list(
                    contribution.contradicting_evidence_ids
                ),
                "context_evidence_ids": list(contribution.context_evidence_ids),
                "condition_boundary_evidence_ids": list(
                    contribution.condition_boundary_evidence_ids
                ),
            }
            for contribution in published.paper_contributions
        ],
        "origin": published.origin,
        "source_analysis_version": published.source_analysis_version,
        "parent_finding_id": published.parent_finding_id,
        "created_by_user_id": published.created_by_user_id,
        "created_by_tool_call_id": published.created_by_tool_call_id,
        "created_at": (
            published.created_at.isoformat() if published.created_at else None
        ),
        **(
            {"selection_ids": list(published.selection_ids)}
            if published.selection_ids
            else {}
        ),
        **(
            {"comparison_group_ids": list(published.comparison_group_ids)}
            if published.comparison_group_ids
            else {}
        ),
        **({"warnings": list(published.warnings)} if published.warnings else {}),
    }
    curated["paper_contributions"][0]["supporting_evidence_ids"] = ["evidence-outside"]

    with pytest.raises(RequestInvalidException, match="references missing evidence"):
        await service.record_curation(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=1,
            finding_id="finding-1",
            curated_status="limited",
            curated_finding=parse_curated_finding(curated),
            user_id="user-1",
        )


async def test_latest_feedback_or_curation_controls_dataset_status(
    *, postgres_session_factory
) -> None:
    service = await _finding_feedback_service(
        postgres_session_factory=postgres_session_factory
    )
    candidate = (
        await service.export_dataset(
            collection_id="col-gold", objective_id="obj-1", user_id="user-1"
        )
    )["items"][0]
    assert candidate["dataset_use_status"] == "review_candidate"
    assert candidate["training_messages"] == []

    published = await service.ObjectiveRepo.read_finding(
        "col-gold", "obj-1", 1, "finding-1"
    )
    assert published is not None
    identity = {
        "collection_id": "col-gold",
        "objective_id": "obj-1",
        "analysis_version": 1,
        "finding_id": "finding-1",
    }
    await service.FindingReviewRepo.upsert_curation(
        FindingCuration(
            curation_id="curation-1",
            **identity,
            curated_status="limited",
            curated_finding=published,
            updated_at="2026-08-02T10:00:00+00:00",
            note=None,
            reviewer=None,
        )
    )
    await service.FindingReviewRepo.upsert_feedback(
        FindingFeedback(
            feedback_id="feedback-1",
            **identity,
            review_status="incorrect",
            issue_type="overclaim",
            created_at="2026-08-02T11:00:00+00:00",
            note=None,
            reviewer=None,
        )
    )

    rejected = (
        await service.export_dataset(
            collection_id="col-gold", objective_id="obj-1", user_id="user-1"
        )
    )["items"][0]
    assert rejected["label_status"] == "rejected"
    assert rejected["dataset_use_status"] == "rejected"
    assert rejected["expert_target"] is None
    assert rejected["training_messages"] == []

    await service.FindingReviewRepo.upsert_curation(
        FindingCuration(
            curation_id="curation-1",
            **identity,
            curated_status="limited",
            curated_finding=published,
            updated_at="2026-08-02T12:00:00+00:00",
            note=None,
            reviewer=None,
        )
    )

    curated = (
        await service.export_dataset(
            collection_id="col-gold", objective_id="obj-1", user_id="user-1"
        )
    )["items"][0]
    assert curated["label_status"] == "gold"
    assert curated["dataset_use_status"] == "training_ready"
    assert curated["expert_target"] == {
        "collection_id": published.collection_id,
        "objective_id": published.objective_id,
        "analysis_version": published.analysis_version,
        "finding_id": published.finding_id,
        "statement": published.statement,
        "factors": list(published.factors),
        "outcome": published.outcome,
        "direction": published.direction,
        "assertion_strength": published.assertion_strength,
        "attribution_scope": published.attribution_scope,
        "synthesis_status": published.synthesis_status,
        "certainty": published.certainty,
        "display_rank": published.display_rank,
        "mechanisms": [
            {
                "source_term": mechanism.source_term,
                "relation_type": mechanism.relation_type,
                "target_term": mechanism.target_term,
                "direction": mechanism.direction,
                "assertion_strength": mechanism.assertion_strength,
                "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
            }
            for mechanism in published.mechanisms
        ],
        "scientific_context": {
            "material": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.material
            ],
            "sample": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.sample
            ],
            "process": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.process
            ],
            "test": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.test
            ],
        },
        "limitations": list(published.limitations),
        "paper_contributions": [
            {
                "document_id": contribution.document_id,
                "analysis_status": contribution.analysis_status,
                "supporting_evidence_ids": list(contribution.supporting_evidence_ids),
                "contradicting_evidence_ids": list(
                    contribution.contradicting_evidence_ids
                ),
                "context_evidence_ids": list(contribution.context_evidence_ids),
                "condition_boundary_evidence_ids": list(
                    contribution.condition_boundary_evidence_ids
                ),
            }
            for contribution in published.paper_contributions
        ],
        "origin": published.origin,
        "source_analysis_version": published.source_analysis_version,
        "parent_finding_id": published.parent_finding_id,
        "created_by_user_id": published.created_by_user_id,
        "created_by_tool_call_id": published.created_by_tool_call_id,
        "created_at": (
            published.created_at.isoformat() if published.created_at else None
        ),
        **(
            {"selection_ids": list(published.selection_ids)}
            if published.selection_ids
            else {}
        ),
        **(
            {"comparison_group_ids": list(published.comparison_group_ids)}
            if published.comparison_group_ids
            else {}
        ),
        **({"warnings": list(published.warnings)} if published.warnings else {}),
    }


async def test_finding_feedback_export_contains_exact_source_text(
    *, postgres_session_factory
) -> None:
    service = await _finding_feedback_service(
        postgres_session_factory=postgres_session_factory
    )
    await service.record_feedback(
        collection_id="col-gold",
        objective_id="obj-1",
        analysis_version=1,
        finding_id="finding-1",
        review_status="correct",
        issue_type="none",
        reviewer="expert-1",
        user_id="user-1",
    )

    dataset = await service.export_dataset(
        collection_id="col-gold", objective_id="obj-1", user_id="user-1"
    )

    assert len(dataset["items"]) == 1
    sample = dataset["items"][0]
    assert sample["label_status"] == "gold"
    assert sample["dataset_use_status"] == "training_ready"
    assert sample["system_prediction"]["factors"] == ["temperature"]
    assert sample["training_target"]["outcome"] == "strength"
    assert sample["finding_fingerprint"].startswith("finding.v2:")
    assert sample["evidence_fingerprint"].startswith("evidence.v2:")
    assert sample["evidence"][0]["source_excerpt"] == (
        "At 500 C, tensile strength increased to 620 MPa."
    )
    assert "At 500 C" in sample["training_messages"][0]["content"]
    assert sample["metadata"]["analysis_version"] == 1
    assert sample["metadata"]["finding_fingerprint"] == sample["finding_fingerprint"]
    assert "claim_id" not in str(sample)


@pytest.mark.parametrize(
    ("snapshot_change", "expected_reason"),
    [
        ({"analysis_version": 2}, "source_analysis_version_changed"),
        ({"finding_fingerprint": "finding.v2:changed"}, "source_finding_changed"),
        ({"evidence_fingerprint": "evidence.v2:changed"}, "source_evidence_changed"),
        ({"evidence_ids": ["evidence-replaced"]}, "source_evidence_ids_changed"),
    ],
)
async def test_finding_source_snapshot_detects_each_stale_dimension(
    snapshot_change: dict, expected_reason: str, *, postgres_session_factory
) -> None:
    service = await _finding_feedback_service(
        postgres_session_factory=postgres_session_factory
    )
    await service.record_feedback(
        collection_id="col-gold",
        objective_id="obj-1",
        analysis_version=1,
        finding_id="finding-1",
        review_status="correct",
        issue_type="none",
        user_id="user-1",
    )
    item = (
        await service.export_dataset(
            collection_id="col-gold", objective_id="obj-1", user_id="user-1"
        )
    )["items"][0]
    source_finding = {
        "finding_id": item["finding_id"],
        "analysis_version": item["analysis_version"],
        "finding_fingerprint": item["finding_fingerprint"],
        "evidence_fingerprint": item["evidence_fingerprint"],
        "evidence_ids": [entry["evidence_id"] for entry in item["evidence"]],
        **snapshot_change,
    }

    validity, reasons = await service.source_snapshot_validity(
        collection_id="col-gold",
        objective_id="obj-1",
        source_findings=[source_finding],
    )

    assert validity == "stale"
    assert reasons == [expected_reason]


async def test_finding_source_snapshot_is_stale_when_dataset_is_unavailable(
    *, postgres_session_factory
) -> None:
    service = await _finding_feedback_service(
        postgres_session_factory=postgres_session_factory
    )

    validity, reasons = await service.source_snapshot_validity(
        collection_id="missing-collection",
        objective_id="missing-objective",
        source_findings=[{"finding_id": "finding-1"}],
    )

    assert validity == "stale"
    assert reasons == ["source_dataset_unavailable"]


async def test_only_training_ready_samples_include_training_messages(
    *, postgres_session_factory
) -> None:
    candidate_service = await _finding_feedback_service(
        postgres_session_factory=postgres_session_factory
    )
    candidate = (
        await candidate_service.export_dataset(
            collection_id="col-gold", objective_id="obj-1", user_id="user-1"
        )
    )["items"][0]
    assert candidate["dataset_use_status"] == "review_candidate"
    assert candidate["training_messages"] == []

    rejected_service = candidate_service
    await rejected_service.record_feedback(
        collection_id="col-gold",
        objective_id="obj-1",
        analysis_version=1,
        finding_id="finding-1",
        review_status="incorrect",
        issue_type="overclaim",
        user_id="user-1",
    )
    rejected = (
        await rejected_service.export_dataset(
            collection_id="col-gold", objective_id="obj-1", user_id="user-1"
        )
    )["items"][0]
    assert rejected["dataset_use_status"] == "rejected"
    assert rejected["training_messages"] == []


@pytest.mark.parametrize("entry", ("service", "agent"))
async def test_typed_curation_preserves_published_finding_and_exports_expert_target(
    entry,
    *,
    postgres_session_factory,
) -> None:
    service = await _finding_feedback_service(
        postgres_session_factory=postgres_session_factory
    )
    published = await service.ObjectiveRepo.read_finding(
        "col-gold", "obj-1", 1, "finding-1"
    )
    assert published is not None
    candidate = replace(
        published,
        limitations=(
            *published.limitations,
            "Expert review retains the original experiment scope.",
        ),
    )

    if entry == "service":
        curation = await service.record_curation(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=1,
            finding_id="finding-1",
            curated_status="limited",
            curated_finding=candidate,
            reviewer="expert-1",
            user_id="user-1",
        )
        assert curation.curated_finding == candidate
    else:
        arguments = CurateFindingToolRequest(
            objective_id="obj-1",
            analysis_version=1,
            finding_id="finding-1",
            curated_status="limited",
            curated_finding={
                "collection_id": candidate.collection_id,
                "objective_id": candidate.objective_id,
                "analysis_version": candidate.analysis_version,
                "finding_id": candidate.finding_id,
                "statement": candidate.statement,
                "factors": list(candidate.factors),
                "outcome": candidate.outcome,
                "direction": candidate.direction,
                "assertion_strength": candidate.assertion_strength,
                "attribution_scope": candidate.attribution_scope,
                "synthesis_status": candidate.synthesis_status,
                "certainty": candidate.certainty,
                "display_rank": candidate.display_rank,
                "mechanisms": [
                    {
                        "source_term": mechanism.source_term,
                        "relation_type": mechanism.relation_type,
                        "target_term": mechanism.target_term,
                        "direction": mechanism.direction,
                        "assertion_strength": mechanism.assertion_strength,
                        "supporting_evidence_ids": list(
                            mechanism.supporting_evidence_ids
                        ),
                    }
                    for mechanism in candidate.mechanisms
                ],
                "scientific_context": {
                    "material": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in candidate.scientific_context.material
                    ],
                    "sample": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in candidate.scientific_context.sample
                    ],
                    "process": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in candidate.scientific_context.process
                    ],
                    "test": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in candidate.scientific_context.test
                    ],
                },
                "limitations": list(candidate.limitations),
                "paper_contributions": [
                    {
                        "document_id": contribution.document_id,
                        "analysis_status": contribution.analysis_status,
                        "supporting_evidence_ids": list(
                            contribution.supporting_evidence_ids
                        ),
                        "contradicting_evidence_ids": list(
                            contribution.contradicting_evidence_ids
                        ),
                        "context_evidence_ids": list(contribution.context_evidence_ids),
                        "condition_boundary_evidence_ids": list(
                            contribution.condition_boundary_evidence_ids
                        ),
                    }
                    for contribution in candidate.paper_contributions
                ],
                "origin": candidate.origin,
                "source_analysis_version": candidate.source_analysis_version,
                "parent_finding_id": candidate.parent_finding_id,
                "created_by_user_id": candidate.created_by_user_id,
                "created_by_tool_call_id": candidate.created_by_tool_call_id,
                "created_at": (
                    candidate.created_at.isoformat() if candidate.created_at else None
                ),
                **(
                    {"selection_ids": list(candidate.selection_ids)}
                    if candidate.selection_ids
                    else {}
                ),
                **(
                    {"comparison_group_ids": list(candidate.comparison_group_ids)}
                    if candidate.comparison_group_ids
                    else {}
                ),
                **(
                    {"warnings": list(candidate.warnings)} if candidate.warnings else {}
                ),
            },
        )
        collection_service = SimpleNamespace(get_collection_for_user=AsyncMock())
        result = await CurateFindingCapability(
            collection_service=collection_service,
            finding_feedback_service=service,
        ).execute(
            CapabilityExecutionContext(
                session_id="review-session",
                user_id="user-1",
                collection_id="col-gold",
                tool_call_id="curate-1",
            ),
            arguments,
        )
        collection_service.get_collection_for_user.assert_awaited_once_with(
            "col-gold", "user-1"
        )
        assert result.data["curated_finding"] == {
            "collection_id": candidate.collection_id,
            "objective_id": candidate.objective_id,
            "analysis_version": candidate.analysis_version,
            "finding_id": candidate.finding_id,
            "statement": candidate.statement,
            "factors": list(candidate.factors),
            "outcome": candidate.outcome,
            "direction": candidate.direction,
            "assertion_strength": candidate.assertion_strength,
            "attribution_scope": candidate.attribution_scope,
            "synthesis_status": candidate.synthesis_status,
            "certainty": candidate.certainty,
            "display_rank": candidate.display_rank,
            "mechanisms": [
                {
                    "source_term": mechanism.source_term,
                    "relation_type": mechanism.relation_type,
                    "target_term": mechanism.target_term,
                    "direction": mechanism.direction,
                    "assertion_strength": mechanism.assertion_strength,
                    "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
                }
                for mechanism in candidate.mechanisms
            ],
            "scientific_context": {
                "material": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in candidate.scientific_context.material
                ],
                "sample": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in candidate.scientific_context.sample
                ],
                "process": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in candidate.scientific_context.process
                ],
                "test": [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **(
                            {"context_scope": attribute.context_scope}
                            if attribute.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in candidate.scientific_context.test
                ],
            },
            "limitations": list(candidate.limitations),
            "paper_contributions": [
                {
                    "document_id": contribution.document_id,
                    "analysis_status": contribution.analysis_status,
                    "supporting_evidence_ids": list(
                        contribution.supporting_evidence_ids
                    ),
                    "contradicting_evidence_ids": list(
                        contribution.contradicting_evidence_ids
                    ),
                    "context_evidence_ids": list(contribution.context_evidence_ids),
                    "condition_boundary_evidence_ids": list(
                        contribution.condition_boundary_evidence_ids
                    ),
                }
                for contribution in candidate.paper_contributions
            ],
            "origin": candidate.origin,
            "source_analysis_version": candidate.source_analysis_version,
            "parent_finding_id": candidate.parent_finding_id,
            "created_by_user_id": candidate.created_by_user_id,
            "created_by_tool_call_id": candidate.created_by_tool_call_id,
            "created_at": (
                candidate.created_at.isoformat() if candidate.created_at else None
            ),
            **(
                {"selection_ids": list(candidate.selection_ids)}
                if candidate.selection_ids
                else {}
            ),
            **(
                {"comparison_group_ids": list(candidate.comparison_group_ids)}
                if candidate.comparison_group_ids
                else {}
            ),
            **({"warnings": list(candidate.warnings)} if candidate.warnings else {}),
        }
        (curation,) = await service.FindingReviewRepo.list_curations(
            "col-gold", "obj-1", 1, "finding-1"
        )
        assert curation.curated_finding == arguments._parsed_finding
    dataset = await service.export_dataset(
        collection_id="col-gold", objective_id="obj-1", user_id="user-1"
    )

    assert (
        await service.ObjectiveRepo.read_finding("col-gold", "obj-1", 1, "finding-1")
        == published
    )
    assert dataset["items"][0]["expert_target"] == {
        "collection_id": candidate.collection_id,
        "objective_id": candidate.objective_id,
        "analysis_version": candidate.analysis_version,
        "finding_id": candidate.finding_id,
        "statement": candidate.statement,
        "factors": list(candidate.factors),
        "outcome": candidate.outcome,
        "direction": candidate.direction,
        "assertion_strength": candidate.assertion_strength,
        "attribution_scope": candidate.attribution_scope,
        "synthesis_status": candidate.synthesis_status,
        "certainty": candidate.certainty,
        "display_rank": candidate.display_rank,
        "mechanisms": [
            {
                "source_term": mechanism.source_term,
                "relation_type": mechanism.relation_type,
                "target_term": mechanism.target_term,
                "direction": mechanism.direction,
                "assertion_strength": mechanism.assertion_strength,
                "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
            }
            for mechanism in candidate.mechanisms
        ],
        "scientific_context": {
            "material": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in candidate.scientific_context.material
            ],
            "sample": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in candidate.scientific_context.sample
            ],
            "process": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in candidate.scientific_context.process
            ],
            "test": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in candidate.scientific_context.test
            ],
        },
        "limitations": list(candidate.limitations),
        "paper_contributions": [
            {
                "document_id": contribution.document_id,
                "analysis_status": contribution.analysis_status,
                "supporting_evidence_ids": list(contribution.supporting_evidence_ids),
                "contradicting_evidence_ids": list(
                    contribution.contradicting_evidence_ids
                ),
                "context_evidence_ids": list(contribution.context_evidence_ids),
                "condition_boundary_evidence_ids": list(
                    contribution.condition_boundary_evidence_ids
                ),
            }
            for contribution in candidate.paper_contributions
        ],
        "origin": candidate.origin,
        "source_analysis_version": candidate.source_analysis_version,
        "parent_finding_id": candidate.parent_finding_id,
        "created_by_user_id": candidate.created_by_user_id,
        "created_by_tool_call_id": candidate.created_by_tool_call_id,
        "created_at": (
            candidate.created_at.isoformat() if candidate.created_at else None
        ),
        **(
            {"selection_ids": list(candidate.selection_ids)}
            if candidate.selection_ids
            else {}
        ),
        **(
            {"comparison_group_ids": list(candidate.comparison_group_ids)}
            if candidate.comparison_group_ids
            else {}
        ),
        **({"warnings": list(candidate.warnings)} if candidate.warnings else {}),
    }
    assert dataset["items"][0]["system_prediction"] == {
        "collection_id": published.collection_id,
        "objective_id": published.objective_id,
        "analysis_version": published.analysis_version,
        "finding_id": published.finding_id,
        "statement": published.statement,
        "factors": list(published.factors),
        "outcome": published.outcome,
        "direction": published.direction,
        "assertion_strength": published.assertion_strength,
        "attribution_scope": published.attribution_scope,
        "synthesis_status": published.synthesis_status,
        "certainty": published.certainty,
        "display_rank": published.display_rank,
        "mechanisms": [
            {
                "source_term": mechanism.source_term,
                "relation_type": mechanism.relation_type,
                "target_term": mechanism.target_term,
                "direction": mechanism.direction,
                "assertion_strength": mechanism.assertion_strength,
                "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
            }
            for mechanism in published.mechanisms
        ],
        "scientific_context": {
            "material": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.material
            ],
            "sample": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.sample
            ],
            "process": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.process
            ],
            "test": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in published.scientific_context.test
            ],
        },
        "limitations": list(published.limitations),
        "paper_contributions": [
            {
                "document_id": contribution.document_id,
                "analysis_status": contribution.analysis_status,
                "supporting_evidence_ids": list(contribution.supporting_evidence_ids),
                "contradicting_evidence_ids": list(
                    contribution.contradicting_evidence_ids
                ),
                "context_evidence_ids": list(contribution.context_evidence_ids),
                "condition_boundary_evidence_ids": list(
                    contribution.condition_boundary_evidence_ids
                ),
            }
            for contribution in published.paper_contributions
        ],
        "origin": published.origin,
        "source_analysis_version": published.source_analysis_version,
        "parent_finding_id": published.parent_finding_id,
        "created_by_user_id": published.created_by_user_id,
        "created_by_tool_call_id": published.created_by_tool_call_id,
        "created_at": (
            published.created_at.isoformat() if published.created_at else None
        ),
        **(
            {"selection_ids": list(published.selection_ids)}
            if published.selection_ids
            else {}
        ),
        **(
            {"comparison_group_ids": list(published.comparison_group_ids)}
            if published.comparison_group_ids
            else {}
        ),
        **({"warnings": list(published.warnings)} if published.warnings else {}),
    }


@pytest.fixture(autouse=True)
async def research_records(postgres_session_factory, anyio_backend):
    from tests.support.postgres import seed_collection

    await seed_collection(postgres_session_factory, "col-gold", document_ids=("doc-1",))
    text = "At 500 C, tensile strength increased to 620 MPa."
    await SourceArtifactRepository().replace_document(
        "col-gold",
        SourceDocument(
            document_id="doc-1",
            document_order=0,
            title="Temperature and strength",
            text=text,
            blocks=(
                SourceBlock(
                    block_id="block-7",
                    document_id="doc-1",
                    block_type="paragraph",
                    text=text,
                    block_order=0,
                    page=7,
                ),
            ),
        ),
    )
