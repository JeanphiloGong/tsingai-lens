from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from application.core.objectives.analysis import evidence_materialization
from application.core.objectives.analysis_service import ObjectiveAnalysisService
from application.core.objectives.analysis.evidence_routing import (
    EvidenceCandidate,
    StructuredEvidenceSelections,
)
from application.core.objectives.analysis.source_extraction import (
    ExtractedEvidenceDraft,
)
from application.core.objectives.analysis.source_screening import (
    PaperAnalysisFrame,
    StructuredPaperFrameBatch,
)
from application.core.objectives.research_objective_service import (
    ObjectiveDocumentEvidenceArtifacts,
)
from domain.core import (
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperResearchMap,
    PaperStudyDisposition,
    PaperStudyDispositionStatus,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.pipeline import ExecutionStats, ModelUsage, TokenUsage
from domain.source import source_documents_from_records
from tests.support.collection_service import build_test_collection_service
from tests.support.objective_extractor import (
    FakeObjectiveExtractor as _ObjectiveExtractor,
)
from infra.persistence.memory.objective_repository import MemoryObjectiveRepository
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

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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


def _ready_objective_facts(
    paper_map: PaperResearchMap,
    objective: ResearchObjective,
) -> ObjectiveFactSet:
    return ObjectiveFactSet(
        research_objectives_ready=True,
        document_inputs=(
            PreparedDocumentInput(
                document_id=paper_map.document_id,
                preparation_fingerprint=f"fingerprint-{paper_map.document_id}",
            ),
        ),
        research_objectives=(objective,),
        study_dispositions=tuple(
            PaperStudyDisposition(
                document_id=paper_map.document_id,
                study_id=study.study_id,
                relationship_id=relationship.relationship_id,
                status=PaperStudyDispositionStatus.PROMOTED,
                objective_id=objective.objective_id,
            )
            for study in paper_map.studies
            for relationship in study.relationships
        ),
    )


def _ready_objective_facts_for_papers(
    paper_maps: tuple[PaperResearchMap, ...],
    objective: ResearchObjective,
) -> ObjectiveFactSet:
    return ObjectiveFactSet(
        research_objectives_ready=True,
        document_inputs=tuple(
            PreparedDocumentInput(
                document_id=paper_map.document_id,
                preparation_fingerprint=f"fingerprint-{paper_map.document_id}",
            )
            for paper_map in paper_maps
        ),
        research_objectives=(objective,),
        study_dispositions=tuple(
            PaperStudyDisposition(
                document_id=paper_map.document_id,
                study_id=study.study_id,
                relationship_id=relationship.relationship_id,
                status=PaperStudyDispositionStatus.PROMOTED,
                objective_id=objective.objective_id,
            )
            for paper_map in paper_maps
            for study in paper_map.studies
            for relationship in study.relationships
        ),
    )


def _relationship_id(document_id: str, outcome: str) -> str:
    return f"relationship-{document_id}-{'-'.join(outcome.casefold().split())}"


def _paper_map(
    *,
    document_id: str,
    varied_factors: tuple[str, ...],
    outcomes: tuple[str, ...],
    material_scope: tuple[str, ...],
    process_context: tuple[str, ...],
    source_ref: str,
) -> PaperResearchMap:
    return PaperResearchMap.from_mapping(
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


async def test_memory_objective_repository_records_analysis_execution_stats():
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
    _, analysis = await repository.queue_analysis(
        "col-1",
        objective.objective_id,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-1",
                preparation_fingerprint="fingerprint-paper-1",
            ),
        ),
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
    )
    await repository.claim_analysis("col-1", objective.objective_id, 1)
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

    updated = await repository.update_analysis_execution_stats(
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


async def test_objective_analysis_preserves_claims_and_deduplicates_replayed_ids():
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
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
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
        paper_maps=(),
        frames=(frame,),
        routes=(),
        evidence_records=evidence_records,
    )

    assert contributions[0].routed_source_count == 2
    assert contributions[0].extracted_source_count == 1
    assert contributions[0].failed_source_count == 1


async def test_objective_contribution_reports_only_final_degraded_source_outcomes():
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
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    paper_map = PaperResearchMap.from_mapping(
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
        paper_maps=(paper_map,),
        frames=(frame,),
        routes=(
            EvidenceCandidate.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "source_kind": "block",
                    "source_ref": "block-4",
                    "role": "current_experimental_evidence",
                    "extractable": True,
                    "reason": (
                        "Deterministic route built after model routing failed."
                    ),
                    "used_fallback": True,
                    "confidence": 0.62,
                }
            ),
        ),
        evidence_records=(failed_evidence,),
    )

    assert contributions[0].warnings == (
        "1 Source unit(s) used conservative paper framing fallback.",
        "1 Source unit(s) used deterministic evidence routing fallback.",
        "1 PaperResearchMap Source unit(s) failed extraction before Objective analysis.",
        "1 selected source(s) failed extraction.",
    )


async def test_objective_analysis_uses_conservative_frame_batch_when_model_fails(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = await collection_service.create_collection("Objective frame fallback")
    collection_id = collection["collection_id"]
    extractor = _FailingFrameExtractor()
    service = _build_research_objective_service(
        collection_service=collection_service,
        response_client=extractor,
    )
    service.finding_synthesis_service.assertion_judge = extractor
    await service.source_artifact_repository.replace_document(
        collection_id,
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
        )[0],
    )
    await _seed_document_profiles(service, collection_id)
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
    paper_map = _paper_map(
        document_id="paper-1",
        varied_factors=("scan strategy rotation angle",),
        outcomes=("crystallographic texture", "yield strength"),
        material_scope=("316L stainless steel",),
        process_context=("LPBF",),
        source_ref="b1",
    )
    await service.paper_map_repository.replace(collection_id, paper_map)
    await service.objective_repository.replace(
        collection_id,
        _ready_objective_facts(paper_map, objective),
    )
    analysis = await _queue_running_analysis(
        service,
        collection_id,
        objective.objective_id,
    )

    artifacts = await service.generate_objective_analysis_artifacts(
        collection_id, analysis
    )

    assert extractor.frame_payloads
    assert artifacts.contributions[0].document_id == "paper-1"
    assert artifacts.contributions[0].analysis_version == analysis.analysis_version
    assert all(
        evidence.analysis_version == analysis.analysis_version
        for evidence in artifacts.evidence_records
    )


async def test_objective_analysis_uses_deterministic_route_when_route_model_fails(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = await collection_service.create_collection("Objective stage retry")
    collection_id = collection["collection_id"]
    extractor = _ObjectiveExtractor()
    extractor.model = "test-model"
    service = _build_research_objective_service(
        collection_service=collection_service,
        response_client=extractor,
    )
    service.finding_synthesis_service.assertion_judge = service._response_client
    await service.source_artifact_repository.replace_document(
        collection_id,
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
        )[0],
    )
    await _seed_document_profiles(service, collection_id)
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
    paper_map = _paper_map(
        document_id="paper-1",
        varied_factors=("heat treatment",),
        outcomes=("corrosion current",),
        material_scope=("316L stainless steel",),
        process_context=("LPBF", "heat treatment"),
        source_ref="b1",
    )
    await service.paper_map_repository.replace(collection_id, paper_map)
    await service.objective_repository.replace(
        collection_id,
        _ready_objective_facts(paper_map, objective),
    )
    analysis = await _queue_running_analysis(
        service,
        collection_id,
        objective.objective_id,
    )

    failing_extractor = _FailingRouteExtractor()
    service._response_client = failing_extractor
    service._objective_evidence_router = failing_extractor
    service.finding_synthesis_service.assertion_judge = failing_extractor
    artifacts = await service.generate_objective_analysis_artifacts(
        collection_id, analysis
    )

    assert failing_extractor.route_payloads
    assert artifacts.contributions[0].document_id == "paper-1"
    assert artifacts.contributions[0].warnings == (
        "1 Source unit(s) used deterministic evidence routing fallback.",
    )
    assert all(
        evidence.analysis_version == analysis.analysis_version
        for evidence in artifacts.evidence_records
    )


async def test_objective_analysis_does_not_mutate_active_objective_facts(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = await collection_service.create_collection("Objective force rebuild")
    collection_id = collection["collection_id"]
    extractor = _ObjectiveExtractor()
    service = _build_research_objective_service(
        collection_service=collection_service,
        response_client=extractor,
    )
    service.finding_synthesis_service.assertion_judge = extractor
    await service.source_artifact_repository.replace_document(
        collection_id,
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
        )[0],
    )
    await _seed_document_profiles(service, collection_id)
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
    paper_map = _paper_map(
        document_id="paper-1",
        varied_factors=("heat treatment",),
        outcomes=("corrosion current",),
        material_scope=("316L stainless steel",),
        process_context=("LPBF", "heat treatment"),
        source_ref="b1",
    )
    await service.paper_map_repository.replace(collection_id, paper_map)
    await service.objective_repository.replace(
        collection_id,
        _ready_objective_facts(paper_map, objective),
    )
    analysis = await _queue_running_analysis(
        service,
        collection_id,
        objective.objective_id,
    )
    active_facts = await service.objective_repository.read(collection_id)

    artifacts = await service.generate_objective_analysis_artifacts(
        collection_id, analysis
    )

    facts = await service.objective_repository.read(collection_id)
    assert extractor.frame_payloads
    assert extractor.route_payloads
    assert facts == active_facts
    assert artifacts.contributions


async def test_document_evidence_retry_reuses_success_and_reruns_only_failure(
    tmp_path,
    monkeypatch,
) -> None:
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = await collection_service.create_collection("Two paper retry")
    collection_id = collection["collection_id"]
    extractor = _ObjectiveExtractor()
    extractor.model = "test-model"
    service = _build_research_objective_service(
        collection_service=collection_service,
        response_client=extractor,
    )
    documents = source_documents_from_records(
        documents=[
            {
                "id": document_id,
                "title": f"Evidence paper {document_id}",
                "text": "Laser power and relative density were studied.",
                "metadata": {"source_filename": f"{document_id}.pdf"},
            }
            for document_id in ("paper-1", "paper-2")
        ],
        blocks=[
            {
                "block_id": f"block-{document_id}",
                "document_id": document_id,
                "block_type": "paragraph",
                "text": "Laser power and relative density were studied.",
                "block_order": 1,
                "heading_path": "Results",
            }
            for document_id in ("paper-1", "paper-2")
        ],
        tables=[],
    )
    for document in documents:
        await service.source_artifact_repository.replace_document(
            collection_id, document
        )
    await _seed_document_profiles(service, collection_id)
    objective = _research_objective(
        {
            "collection_id": collection_id,
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
            "seed_document_ids": ["paper-1", "paper-2"],
            "source_relationship_ids": [
                _relationship_id("paper-1", "relative density"),
                _relationship_id("paper-2", "relative density"),
            ],
            "rank": 1,
            "confidence": 0.9,
        }
    )
    paper_maps = tuple(
        _paper_map(
            document_id=document_id,
            varied_factors=("laser power",),
            outcomes=("relative density",),
            material_scope=("Ti-6Al-4V",),
            process_context=("LPBF",),
            source_ref=f"block-{document_id}",
        )
        for document_id in ("paper-1", "paper-2")
    )
    for paper_map in paper_maps:
        await service.paper_map_repository.replace(collection_id, paper_map)
    await service.objective_repository.replace(
        collection_id,
        _ready_objective_facts_for_papers(paper_maps, objective),
    )

    synthesis_calls: list[tuple[PaperContribution, ...]] = []

    class _FindingSynthesisRecorder:
        def synthesize(self, **payload):
            synthesis_calls.append(payload["contributions"])
            return ()

    service.finding_synthesis_service = _FindingSynthesisRecorder()
    extraction_calls: list[str] = []
    paper_2_failures_remaining = 1

    def extract_document(**payload):
        nonlocal paper_2_failures_remaining
        document_id = payload["objective_inputs"]["documents"][0].document_id
        extraction_calls.append(document_id)
        if document_id == "paper-2" and paper_2_failures_remaining:
            paper_2_failures_remaining -= 1
            raise RuntimeError("provider unavailable")
        return ObjectiveDocumentEvidenceArtifacts(
            contribution=PaperContribution.from_mapping(
                {
                    "collection_id": collection_id,
                    "objective_id": objective.objective_id,
                    "analysis_version": payload["analysis"].analysis_version,
                    "document_id": document_id,
                    "analysis_status": "analyzed",
                    "relevance": "high",
                    "paper_role": "primary_experiment",
                    "confidence": 0.9,
                    "evidence_disposition": "no_routable_evidence",
                    "routed_source_count": 0,
                    "extracted_source_count": 0,
                    "comparable_evidence_count": 0,
                    "failed_source_count": 0,
                    "evidence_disposition_reason": (
                        "No source in this paper was selected for extraction."
                    ),
                }
            ),
            evidence_records=(),
        )

    monkeypatch.setattr(
        service,
        "_generate_document_evidence",
        extract_document,
        raising=False,
    )
    analysis_service = ObjectiveAnalysisService(
        objective_repository=service.objective_repository,
        research_objective_service=service,
    )
    first_queued = await analysis_service.queue_analysis(
        collection_id,
        objective.objective_id,
        ("paper-1", "paper-2"),
    )

    first = await analysis_service.execute_queued_analysis(
        collection_id,
        objective.objective_id,
        first_queued["analysis"].analysis_version,
    )

    assert first["analysis"].status == "succeeded"
    assert first["objective"].published_analysis_version == 1
    assert extraction_calls == ["paper-1", "paper-2"]
    assert [item.analysis_status for item in first["paper_contributions"]] == [
        "analyzed",
        "failed",
    ]
    assert len(service.objective_repository._document_evidence) == 2
    assert sorted(
        checkpoint.status
        for checkpoint in service.objective_repository._document_evidence.values()
    ) == ["failed", "succeeded"]
    assert len(synthesis_calls) == 1

    second_queued = await analysis_service.queue_analysis(
        collection_id,
        objective.objective_id,
        ("paper-1", "paper-2"),
    )

    second = await analysis_service.execute_queued_analysis(
        collection_id,
        objective.objective_id,
        second_queued["analysis"].analysis_version,
    )

    assert second["analysis"].status == "succeeded"
    assert second["objective"].published_analysis_version == 2
    assert extraction_calls == ["paper-1", "paper-2", "paper-2"]
    assert all(
        item.analysis_status == "analyzed"
        for item in second["paper_contributions"]
    )
    assert all(
        item.analysis_version == second["analysis"].analysis_version
        for item in second["paper_contributions"]
    )
    assert len(synthesis_calls) == 2


def test_document_evidence_fingerprint_covers_every_reuse_input(tmp_path) -> None:
    collection_service = build_test_collection_service(tmp_path / "collections")
    service = _build_research_objective_service(
        collection_service=collection_service,
        response_client=_ObjectiveExtractor(),
    )
    objective = _research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    document_input = PreparedDocumentInput("paper-1", "preparation-1")

    def fingerprint(
        *,
        current_objective=objective,
        current_document_input=document_input,
        model_name="model-a",
        extraction_version="objective-document-evidence.v1",
    ) -> str:
        return service._document_evidence_input_fingerprint(
            objective=current_objective,
            document_input=current_document_input,
            model_name=model_name,
            extraction_version=extraction_version,
        )

    fingerprints = {
        fingerprint(),
        fingerprint(
            current_objective=replace(
                objective,
                question="How does laser energy affect relative density?",
            )
        ),
        fingerprint(
            current_objective=replace(
                objective,
                excluded_document_ids=("paper-1",),
            )
        ),
        fingerprint(
            current_objective=replace(
                objective,
                source_relationship_ids=("relationship-paper-1-density",),
            )
        ),
        fingerprint(
            current_document_input=PreparedDocumentInput(
                "paper-1", "preparation-2"
            )
        ),
        fingerprint(model_name="model-b"),
        fingerprint(extraction_version="objective-document-evidence.v2"),
    }

    assert len(fingerprints) == 7
