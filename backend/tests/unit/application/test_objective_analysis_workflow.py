from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from application.core.objectives.analysis import evidence_materialization
from application.core.objectives.analysis.evidence_routing import (
    StructuredEvidenceSelections,
)
from application.core.objectives.analysis.source_extraction import (
    ExtractedEvidenceDraft,
)
from application.core.objectives.analysis.source_screening import (
    PaperAnalysisFrame,
    StructuredPaperFrameBatch,
)
from domain.core import (
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperSkim,
    PaperStudyDisposition,
    PaperStudyDispositionStatus,
    ResearchObjective,
)
from domain.pipeline import ExecutionStats, ModelUsage, TokenUsage
from domain.source import source_documents_from_records
from tests.support.collection_service import build_test_collection_service
from tests.support.objective_extractor import (
    FakeObjectiveExtractor as _ObjectiveExtractor,
)
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.research_objective_service import (
    build_research_objective_service as _build_research_objective_service,
)
from tests.support.research_objective_service import (
    queue_running_analysis as _queue_running_analysis,
)
from tests.support.research_objective_service import (
    research_objective as _research_objective,
)
from tests.support.research_objective_service import (
    seed_document_profiles as _seed_document_profiles,
)


class _FailingRouteExtractor(_ObjectiveExtractor):
    def route_source(
        self,
        payload: dict[str, Any],
    ) -> StructuredEvidenceSelections:
        self.route_payloads.append(payload)
        raise RuntimeError("route model failed")


class _FailingFrameExtractor(_ObjectiveExtractor):
    def screen_batch(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperFrameBatch:
        self.frame_payloads.append(payload)
        raise RuntimeError("frame model failed")


class _ActiveBuildScopeObjectiveRepository(MemoryObjectiveRepository):
    """Mirror production's global lifecycle plus active-build support scope."""

    def read_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        lifecycle = super().read_objective(collection_id, objective_id)
        if lifecycle is None:
            return None
        snapshot = next(
            (
                objective
                for objective in self.read(collection_id).research_objectives
                if objective.objective_id == objective_id
            ),
            None,
        )
        if snapshot is None:
            return lifecycle
        return replace(
            snapshot,
            confirmation_status=lifecycle.confirmation_status,
            active_analysis_version=lifecycle.active_analysis_version,
            published_analysis_version=lifecycle.published_analysis_version,
            created_at=lifecycle.created_at,
            updated_at=lifecycle.updated_at,
        )


def _ready_objective_facts(
    paper_skim: PaperSkim,
    objective: ResearchObjective,
) -> ObjectiveFactSet:
    return ObjectiveFactSet(
        research_objectives_ready=True,
        paper_skims=(paper_skim,),
        research_objectives=(objective,),
        study_dispositions=tuple(
            PaperStudyDisposition(
                document_id=paper_skim.document_id,
                study_id=study.study_id,
                relationship_id=relationship.relationship_id,
                status=PaperStudyDispositionStatus.PROMOTED,
                objective_id=objective.objective_id,
            )
            for study in paper_skim.studies
            for relationship in study.relationships
        ),
    )


def _relationship_id(document_id: str, outcome: str) -> str:
    return f"relationship-{document_id}-{'-'.join(outcome.casefold().split())}"


def _paper_skim(
    *,
    document_id: str,
    varied_factors: tuple[str, ...],
    outcomes: tuple[str, ...],
    material_scope: tuple[str, ...],
    process_context: tuple[str, ...],
    source_ref: str,
) -> PaperSkim:
    return PaperSkim.from_mapping(
        {
            "document_id": document_id,
            "doc_role": "experimental",
            "studies": [
                {
                    "study_id": f"study-{document_id}",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": list(material_scope),
                    "process_context": list(process_context),
                    "relationships": [
                        {
                            "relationship_id": _relationship_id(
                                document_id,
                                outcome,
                            ),
                            "varied_factors": list(varied_factors),
                            "outcome": outcome,
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": source_ref,
                                }
                            ],
                            "confidence": 0.9,
                        }
                        for outcome in outcomes
                    ],
                    "confidence": 0.9,
                }
            ],
            "evidence_density": "high",
            "confidence": 0.9,
            "warnings": [],
        }
    )


def test_memory_objective_repository_requires_explicit_activation():
    repository = MemoryObjectiveRepository()
    active = ObjectiveFactSet(research_objectives_ready=True)
    pending = ObjectiveFactSet()

    repository.replace("col-1", "build_test", active)
    repository.replace("col-1", "build_pending", pending)

    assert repository.read("col-1") == active
    assert repository.read("col-1", build_id="build_pending") == pending

    repository.activate("build_pending")

    assert repository.read("col-1") == pending


def test_memory_objective_repository_records_analysis_execution_stats():
    objective = _research_objective(
        {
            "collection_id": "col-1",
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
            "rank": 1,
            "confirmation_status": "confirmed",
        }
    )
    repository = MemoryObjectiveRepository.from_facts(
        "col-1",
        ObjectiveFactSet(
            research_objectives=(objective,),
        ),
    )
    _, analysis = repository.queue_analysis(
        "col-1",
        objective.objective_id,
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
    )
    repository.claim_analysis("col-1", objective.objective_id, 1)
    stats = ExecutionStats(
        model_usage=(
            ModelUsage(
                model_name="test-model",
                request_count=1,
                token_usage=TokenUsage(
                    input_tokens=10,
                    output_tokens=5,
                    total_tokens=15,
                ),
            ),
        ),
    )

    updated = repository.update_analysis_execution_stats(
        "col-1",
        objective.objective_id,
        analysis.analysis_version,
        stats=stats,
        model_name="test-model",
        prompt_versions={"source_extraction": "source_extraction.v1"},
        diagnostics=(),
    )

    assert updated.stats == stats
    assert updated.model_name == "test-model"
    assert updated.prompt_versions == {
        "source_extraction": "source_extraction.v1"
    }


def test_objective_analysis_preserves_claims_and_deduplicates_replayed_ids():
    objective = _research_objective(
        {
            "collection_id": "col-1",
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="col-1",
        objective_id=objective.objective_id,
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    source_refs = [
        {"source_kind": "text_window", "source_ref": "block-1"}
    ]
    drafts = (
        ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": "normal-context",
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "block-1",
                "evidence_role": "condition_context",
                "selection_status": "extracted",
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "process": [{"name": "process", "value": "LPBF"}]
                },
                "source_refs": source_refs,
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        ),
        ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": "repair-result",
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "block-1",
                "evidence_role": "direct_result",
                "selection_status": "extracted",
                "changed_variables": [
                    {
                        "name": "laser power",
                        "baseline_value": 100,
                        "target_value": 140,
                        "unit": "W",
                    }
                ],
                "comparison": {
                    "baseline_label": "100 W",
                    "target_label": "140 W",
                    "axis_names": ["laser power"],
                    "comparable": True,
                },
                "reported_result": {
                    "outcome": "relative density",
                    "value": 98.05,
                    "unit": "%",
                    "direction": "increase",
                    "result_text": "Relative density increased to 98.05%.",
                },
                "attribution_scope": "isolated_effect",
                "source_refs": source_refs,
                "resolution_status": "resolved",
                "confidence": 0.8,
            }
        ),
        ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": "repair-result",
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "block-1",
                "evidence_role": "direct_result",
                "selection_status": "extracted",
                "changed_variables": [
                    {
                        "name": "laser power",
                        "baseline_value": 100,
                        "target_value": 140,
                        "unit": "W",
                    }
                ],
                "comparison": {
                    "baseline_label": "100 W",
                    "target_label": "140 W",
                    "axis_names": ["laser power"],
                    "comparable": True,
                },
                "reported_result": {
                    "outcome": "relative density",
                    "value": 98.05,
                    "unit": "%",
                    "direction": "increase",
                    "result_text": "Relative density increased to 98.05%.",
                },
                "attribution_scope": "isolated_effect",
                "source_refs": source_refs,
                "resolution_status": "resolved",
                "confidence": 0.8,
            }
        ),
        ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": "failed-short",
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "block-2",
                "evidence_role": "irrelevant",
                "selection_status": "failed",
                "attribution_scope": "not_attributable",
                "source_refs": [
                    {"source_kind": "text_window", "source_ref": "block-2"}
                ],
                "resolution_status": "unknown",
                "failure_reason": "invalid",
                "confidence": 0.0,
            }
        ),
        ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": "failed-short",
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "block-2",
                "evidence_role": "irrelevant",
                "selection_status": "failed",
                "attribution_scope": "not_attributable",
                "source_refs": [
                    {"source_kind": "text_window", "source_ref": "block-2"}
                ],
                "resolution_status": "unknown",
                "failure_reason": "invalid",
                "confidence": 0.0,
            }
        ),
    )
    blocks = {
        "paper-1": [
            SimpleNamespace(
                block_id="block-1",
                text="Relative density increased to 98.05% at 140 W.",
                page=3,
            ),
            SimpleNamespace(
                block_id="block-2",
                text="A second selected Source failed extraction.",
                page=4,
            ),
        ]
    }

    evidence_records = evidence_materialization._analysis_evidence_records(
        collection_id="col-1",
        analysis=analysis,
        objective=objective,
        drafts=drafts,
        blocks_by_document_id=blocks,
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert [record.evidence_id for record in evidence_records] == [
        "normal-context",
        "repair-result",
        "failed-short",
    ]
    assert len(evidence_records) == len({record.evidence_id for record in evidence_records})
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
        }
    )
    contributions = evidence_materialization._analysis_contributions(
        collection_id="col-1",
        analysis=analysis,
        objective=objective,
        paper_skims=(),
        frames=(frame,),
        routes=(),
        evidence_records=evidence_records,
    )

    assert contributions[0].routed_source_count == 2
    assert contributions[0].extracted_source_count == 1
    assert contributions[0].failed_source_count == 1


def test_objective_contribution_reports_only_final_degraded_source_outcomes():
    objective = _research_objective(
        {
            "collection_id": "col-1",
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="col-1",
        objective_id=objective.objective_id,
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "doc_role": "experimental",
            "studies": [],
            "evidence_density": "low",
            "confidence": 0.6,
            "warnings": [],
            "source_unit_coverage": [
                {
                    "source_unit_id": "paper-1:source:1",
                    "window_id": "paper-1:window:1",
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "status": "extraction_failed",
                    "reason": "terminal singleton extraction failure",
                },
                {
                    "source_unit_id": "paper-1:source:2",
                    "window_id": "paper-1:window:2",
                    "source_kind": "block",
                    "source_ref": "block-2",
                    "status": "no_study_signal",
                    "reason": "no study signal",
                },
            ],
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "source_dispositions": [
                {
                    "source_unit_id": "frame-source-1",
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "disposition": "fallback_relevant",
                    "accounting_errors": ["provider unavailable"],
                },
                {
                    "source_unit_id": "frame-source-2",
                    "source_kind": "block",
                    "source_ref": "block-2",
                    "disposition": "repaired_relevant",
                    "accounting_errors": ["one missing Source decision was repaired"],
                },
            ],
        }
    )
    failed_evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": "failed-evidence",
            "document_id": "paper-1",
            "source_kind": "block",
            "source_ref": "block-3",
            "source_excerpt": "Source extraction failed.",
            "evidence_role": "irrelevant",
            "selection_status": "failed",
            "attribution_scope": "not_attributable",
            "resolution_status": "unknown",
            "failure_reason": "structured output remained invalid",
            "confidence": 0.0,
        }
    )

    contributions = evidence_materialization._analysis_contributions(
        collection_id="col-1",
        analysis=analysis,
        objective=objective,
        paper_skims=(paper_skim,),
        frames=(frame,),
        routes=(),
        evidence_records=(failed_evidence,),
    )

    assert contributions[0].warnings == (
        "1 Source unit(s) used conservative paper framing fallback.",
        "1 PaperSkim Source unit(s) failed extraction before Objective analysis.",
        "1 selected source(s) failed extraction.",
    )


def test_objective_analysis_uses_conservative_frame_batch_when_model_fails(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective frame fallback")
    collection_id = collection["collection_id"]
    extractor = _FailingFrameExtractor()
    service = _build_research_objective_service(
        collection_service=collection_service,
        response_client=extractor,
    )
    service.finding_synthesis_service.assertion_judge = extractor
    service.source_artifact_repository.replace_collection_documents(
        collection_id,
        "build_test",
        source_documents_from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "LPBF 316L Texture and Yield Study",
                    "text": "Scan strategy changed texture and yield strength.",
                    "metadata": {"source_filename": "paper-1.pdf"},
                }
            ],
            blocks=[
                {
                    "block_id": "b1",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": (
                        "Scan strategy rotation angle changed crystallographic "
                        "texture and yield strength of LPBF 316L."
                    ),
                    "block_order": 1,
                    "heading_path": "Results",
                }
            ],
            tables=[],
        ),
    )
    _seed_document_profiles(service, collection_id)
    objective = _research_objective(
        {
            "collection_id": collection_id,
            "objective_id": "obj_texture_yield",
            "question": "How does scan strategy affect texture and yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["scan strategy rotation angle"],
            "outcomes": ["crystallographic texture", "yield strength"],
            "requested_comparator": "Compare texture and yield strength across scan strategy.",
            "seed_document_ids": ["paper-1"],
            "source_relationship_ids": [
                _relationship_id("paper-1", "crystallographic texture"),
                _relationship_id("paper-1", "yield strength"),
            ],
            "rank": 1,
            "confidence": 0.9,
        }
    )
    paper_skim = _paper_skim(
        document_id="paper-1",
        varied_factors=("scan strategy rotation angle",),
        outcomes=("crystallographic texture", "yield strength"),
        material_scope=("316L stainless steel",),
        process_context=("LPBF",),
        source_ref="b1",
    )
    service.objective_repository.replace(
        collection_id,
        "build_test",
        _ready_objective_facts(paper_skim, objective),
    )
    analysis = _queue_running_analysis(service, collection_id, objective.objective_id)

    artifacts = service.generate_objective_analysis_artifacts(
        collection_id, analysis
    )

    assert extractor.frame_payloads
    assert artifacts.contributions[0].document_id == "paper-1"
    assert artifacts.contributions[0].analysis_version == analysis.analysis_version
    assert all(
        evidence.analysis_version == analysis.analysis_version
        for evidence in artifacts.evidence_records
    )


def test_objective_analysis_uses_deterministic_route_when_route_model_fails(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective stage retry")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        response_client=_ObjectiveExtractor(),
    )
    service.finding_synthesis_service.assertion_judge = service._response_client
    service.source_artifact_repository.replace_collection_documents(
        collection_id,
        "build_test",
        source_documents_from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "LPBF 316L Heat Treatment Corrosion Study",
                    "text": "LPBF 316L was heat treated and corrosion current was measured.",
                    "metadata": {"source_filename": "paper-1.pdf"},
                }
            ],
            blocks=[
                {
                    "block_id": "b1",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": "LPBF 316L was heat treated.",
                    "block_order": 1,
                }
            ],
            tables=[
                {
                    "table_id": "table-1",
                    "document_id": "paper-1",
                    "caption_text": "Corrosion current results",
                    "column_headers": ["sample", "corrosion current"],
                    "table_matrix": [
                        ["sample", "corrosion current"],
                        ["as-built", "1.2 uA/cm2"],
                    ],
                }
            ],
        ),
    )
    _seed_document_profiles(service, collection_id)
    objective = _research_objective(
        {
            "collection_id": collection_id,
            "objective_id": "obj_corrosion",
            "question": "How does heat treatment affect corrosion current?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["corrosion current"],
            "constraints": ["LPBF"],
            "requested_comparator": "Compare corrosion current before and after heat treatment.",
            "seed_document_ids": ["paper-1"],
            "source_relationship_ids": [
                _relationship_id("paper-1", "corrosion current")
            ],
            "rank": 1,
            "confidence": 0.9,
        }
    )
    paper_skim = _paper_skim(
        document_id="paper-1",
        varied_factors=("heat treatment",),
        outcomes=("corrosion current",),
        material_scope=("316L stainless steel",),
        process_context=("LPBF", "heat treatment"),
        source_ref="b1",
    )
    service.objective_repository.replace(
        collection_id,
        "build_test",
        _ready_objective_facts(paper_skim, objective),
    )
    analysis = _queue_running_analysis(service, collection_id, objective.objective_id)

    failing_extractor = _FailingRouteExtractor()
    service._response_client = failing_extractor
    service._objective_evidence_router = failing_extractor
    service.finding_synthesis_service.assertion_judge = failing_extractor
    artifacts = service.generate_objective_analysis_artifacts(
        collection_id, analysis
    )

    assert failing_extractor.route_payloads
    assert artifacts.contributions[0].document_id == "paper-1"
    assert all(
        evidence.analysis_version == analysis.analysis_version
        for evidence in artifacts.evidence_records
    )


def test_objective_analysis_does_not_mutate_active_objective_facts(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective force rebuild")
    collection_id = collection["collection_id"]
    extractor = _ObjectiveExtractor()
    service = _build_research_objective_service(
        collection_service=collection_service,
        response_client=extractor,
    )
    service.finding_synthesis_service.assertion_judge = extractor
    service.source_artifact_repository.replace_collection_documents(
        collection_id,
        "build_test",
        source_documents_from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "LPBF 316L Heat Treatment Corrosion Study",
                    "text": "LPBF 316L was heat treated and corrosion current was measured.",
                    "metadata": {"source_filename": "paper-1.pdf"},
                }
            ],
            blocks=[
                {
                    "block_id": "b1",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": "LPBF 316L was heat treated.",
                    "block_order": 1,
                }
            ],
            tables=[
                {
                    "table_id": "table-1",
                    "document_id": "paper-1",
                    "caption_text": "Corrosion current results",
                    "column_headers": ["sample", "corrosion current"],
                    "table_matrix": [
                        ["sample", "corrosion current"],
                        ["as-built", "1.2 uA/cm2"],
                        ["heat-treated", "0.4 uA/cm2"],
                    ],
                }
            ],
        ),
    )
    _seed_document_profiles(service, collection_id)
    objective = _research_objective(
        {
            "collection_id": collection_id,
            "objective_id": "obj_corrosion",
            "question": "How does heat treatment affect corrosion current?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["corrosion current"],
            "constraints": ["LPBF"],
            "requested_comparator": "Compare corrosion current before and after heat treatment.",
            "seed_document_ids": ["paper-1"],
            "source_relationship_ids": [
                _relationship_id("paper-1", "corrosion current")
            ],
            "rank": 1,
            "confidence": 0.9,
        }
    )
    paper_skim = _paper_skim(
        document_id="paper-1",
        varied_factors=("heat treatment",),
        outcomes=("corrosion current",),
        material_scope=("316L stainless steel",),
        process_context=("LPBF", "heat treatment"),
        source_ref="b1",
    )
    service.objective_repository.replace(
        collection_id,
        "build_test",
        _ready_objective_facts(paper_skim, objective),
    )
    active_facts = service.objective_repository.read(collection_id)
    analysis = _queue_running_analysis(service, collection_id, objective.objective_id)

    artifacts = service.generate_objective_analysis_artifacts(
        collection_id, analysis
    )

    facts = service.objective_repository.read(collection_id)
    assert extractor.frame_payloads
    assert extractor.route_payloads
    assert facts == active_facts
    assert artifacts.contributions


def test_queued_analysis_uses_its_source_build_objective_scope_after_rebuild(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection_id = collection_service.create_collection("Build snapshot analysis")[
        "collection_id"
    ]
    extractor = _ObjectiveExtractor()
    repository = _ActiveBuildScopeObjectiveRepository()
    service = _build_research_objective_service(
        collection_service=collection_service,
        response_client=extractor,
        objective_repository=repository,
    )
    service.finding_synthesis_service.assertion_judge = extractor
    service.source_artifact_repository.replace_collection_documents(
        collection_id,
        "build_test",
        source_documents_from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Queued source paper",
                    "text": "Heat treatment changed corrosion current.",
                }
            ],
            blocks=[
                {
                    "block_id": "paper-1-results",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": "Heat treatment changed corrosion current.",
                    "block_order": 1,
                    "heading_path": "Results",
                }
            ],
            tables=[],
        ),
    )
    _seed_document_profiles(service, collection_id)
    queued_objective = _research_objective(
        {
            "collection_id": collection_id,
            "objective_id": "obj_corrosion",
            "question": "How does heat treatment affect corrosion current?",
            "variables": ["heat treatment"],
            "outcomes": ["corrosion current"],
            "seed_document_ids": ["paper-1"],
            "source_relationship_ids": [
                _relationship_id("paper-1", "corrosion current")
            ],
            "rank": 1,
        }
    )
    queued_skim = _paper_skim(
        document_id="paper-1",
        varied_factors=("heat treatment",),
        outcomes=("corrosion current",),
        material_scope=("316L",),
        process_context=("LPBF",),
        source_ref="paper-1-results",
    )
    repository.replace(
        collection_id,
        "build_test",
        _ready_objective_facts(queued_skim, queued_objective),
    )
    analysis = _queue_running_analysis(
        service,
        collection_id,
        queued_objective.objective_id,
    )

    rebuilt_objective = _research_objective(
        {
            **queued_objective.to_record(),
            "seed_document_ids": ["paper-2"],
            "source_relationship_ids": [
                _relationship_id("paper-2", "corrosion current")
            ],
            "confirmation_status": "candidate",
            "active_analysis_version": None,
            "rank": 1,
        }
    )
    rebuilt_skim = _paper_skim(
        document_id="paper-2",
        varied_factors=("heat treatment",),
        outcomes=("corrosion current",),
        material_scope=("316L",),
        process_context=("LPBF",),
        source_ref="paper-2-results",
    )
    repository.replace(
        collection_id,
        "build_rebuilt",
        _ready_objective_facts(rebuilt_skim, rebuilt_objective),
    )
    repository.activate("build_rebuilt")

    service.generate_objective_analysis_artifacts(collection_id, analysis)

    frame_payload = extractor.frame_payloads[0]
    assert "seed_document_ids" not in frame_payload["objective"]
    assert "source_relationship_ids" not in frame_payload["objective"]
    assert frame_payload["paper_prior"]["studies"][0]["relationships"] == [
        {
            "varied_factors": ["heat treatment"],
            "outcome": "corrosion current",
        }
    ]
