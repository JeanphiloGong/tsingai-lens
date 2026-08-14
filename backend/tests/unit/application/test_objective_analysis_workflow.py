from __future__ import annotations

from dataclasses import replace
from typing import Any

from application.core.objectives.schemas import (
    StructuredEvidenceSelections,
    StructuredPaperFrameBatch,
)
from domain.core import (
    ObjectiveFactSet,
    PaperSkim,
    PaperStudyDisposition,
    PaperStudyDispositionStatus,
    ResearchObjective,
)
from domain.source import source_documents_from_records
from tests.support.collection_service import build_test_collection_service
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.objective_extractor import (
    FakeObjectiveExtractor as _ObjectiveExtractor,
)
from tests.support.research_objective_service import (
    build_research_objective_service as _build_research_objective_service,
    queue_running_analysis as _queue_running_analysis,
    research_objective as _research_objective,
    seed_document_profiles as _seed_document_profiles,
)


class _FailingRouteExtractor(_ObjectiveExtractor):
    def select_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredEvidenceSelections:
        self.route_payloads.append(payload)
        raise RuntimeError("route model failed")


class _FailingFrameExtractor(_ObjectiveExtractor):
    def assess_objective_paper(
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


def test_objective_analysis_uses_conservative_frame_batch_when_model_fails(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective frame fallback")
    collection_id = collection["collection_id"]
    extractor = _FailingFrameExtractor()
    service = _build_research_objective_service(
        collection_service=collection_service,
        objective_extractor=extractor,
    )
    service.finding_synthesis_service.finding_extractor = extractor
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
        objective_extractor=_ObjectiveExtractor(),
    )
    service.finding_synthesis_service.finding_extractor = service._objective_extractor
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
    service._objective_extractor = failing_extractor
    service.finding_synthesis_service.finding_extractor = failing_extractor
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
        objective_extractor=extractor,
    )
    service.finding_synthesis_service.finding_extractor = extractor
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
        objective_extractor=extractor,
        objective_repository=repository,
    )
    service.finding_synthesis_service.finding_extractor = extractor
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
