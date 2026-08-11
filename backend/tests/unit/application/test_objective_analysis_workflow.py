from __future__ import annotations

from typing import Any

from application.core.objectives.schemas import (
    StructuredEvidenceSelections,
    StructuredPaperContributionDraft,
)
from domain.core import ObjectiveFactSet, PaperSkim
from domain.source import SourceArtifactSet
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
    ) -> StructuredPaperContributionDraft:
        self.frame_payloads.append(payload)
        raise RuntimeError("frame model failed")


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


def test_objective_analysis_uses_deterministic_frame_when_frame_model_fails(
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
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        "build_test",
        SourceArtifactSet.from_records(
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
            "confidence": 0.9,
        }
    )
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "collection_id": collection_id,
            "doc_role": "experimental",
            "candidate_materials": ["316L stainless steel"],
            "candidate_processes": ["LPBF"],
            "candidate_properties": ["crystallographic texture", "yield strength"],
            "changed_variables": ["scan strategy rotation angle"],
            "possible_objectives": [objective.question],
            "evidence_density": "high",
            "confidence": 0.9,
        }
    )
    service.objective_repository.replace(
        collection_id,
        "build_test",
        ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=(paper_skim,),
            research_objectives=(objective,),
        ),
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
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        "build_test",
        SourceArtifactSet.from_records(
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
            "confidence": 0.9,
        }
    )
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "collection_id": collection_id,
            "doc_role": "experimental",
            "candidate_materials": ["316L stainless steel"],
            "candidate_processes": ["LPBF", "heat treatment"],
            "candidate_properties": ["corrosion current"],
            "changed_variables": ["heat treatment"],
            "possible_objectives": [objective.question],
            "evidence_density": "high",
            "confidence": 0.9,
        }
    )
    service.objective_repository.replace(
        collection_id,
        "build_test",
        ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=(paper_skim,),
            research_objectives=(objective,),
        ),
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
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        "build_test",
        SourceArtifactSet.from_records(
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
            "confidence": 0.9,
        }
    )
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "collection_id": collection_id,
            "doc_role": "experimental",
            "candidate_materials": ["316L stainless steel"],
            "candidate_processes": ["LPBF", "heat treatment"],
            "candidate_properties": ["corrosion current"],
            "changed_variables": ["heat treatment"],
            "possible_objectives": [objective.question],
            "evidence_density": "high",
            "confidence": 0.9,
        }
    )
    service.objective_repository.replace(
        collection_id,
        "build_test",
        ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=(paper_skim,),
            research_objectives=(objective,),
        ),
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
