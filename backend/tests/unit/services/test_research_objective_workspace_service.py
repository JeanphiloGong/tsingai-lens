from __future__ import annotations

import pytest

from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveNotFoundError,
    ResearchObjectiveService,
)
from application.source.collection_service import CollectionService
from domain.core import (
    CoreFactSet,
    DocumentProfile,
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectivePaperFrame,
    PaperSkim,
    ResearchObjective,
)
from infra.persistence.sqlite.core_fact_repository import SqliteCoreFactRepository


def _seed_objective_collection(tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Workspace")
    collection_id = collection["collection_id"]
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    objective = ResearchObjective.from_mapping(
        {
            "question": "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["LPBF", "heat treatment"],
            "property_axes": ["corrosion resistance"],
            "comparison_intent": "Compare as-built and heat-treated samples.",
            "seed_document_ids": ["paper-1"],
            "confidence": 0.88,
        }
    )
    repository.replace_collection_research_objectives(
        collection_id,
        (
            PaperSkim.from_mapping(
                {
                    "document_id": "paper-1",
                    "title": "LPBF 316L Corrosion",
                    "source_filename": "paper-1.pdf",
                    "doc_role": "experimental",
                    "candidate_materials": ["316L stainless steel"],
                }
            ),
        ),
        (objective,),
        (
            ObjectiveContext.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "question": objective.question,
                    "material_scope": ["316L stainless steel"],
                    "variable_process_axes": ["heat treatment"],
                    "process_context_axes": ["LPBF"],
                    "target_property_axes": ["corrosion resistance"],
                    "confidence": 0.88,
                }
            ),
        ),
        (
            ObjectivePaperFrame.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "relevance": "high",
                    "paper_role": "primary_experiment",
                    "background": "Studies LPBF 316L corrosion after heat treatment.",
                    "material_match": ["316L stainless steel"],
                    "changed_variables": ["heat treatment"],
                    "measured_property_scope": ["corrosion resistance"],
                    "test_environment_scope": ["NaCl"],
                    "relevant_sections": ["Results"],
                    "relevant_tables": ["table-1"],
                }
            ),
        ),
        (
            ObjectiveEvidenceRoute.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "role": "current_experimental_evidence",
                    "extractable": True,
                    "reason": "Contains corrosion results.",
                    "table_schema": {"column_headers": ["sample", "icorr"]},
                    "confidence": 0.81,
                }
            ),
        ),
        (),
        (),
    )
    repository.replace_collection_facts(
        collection_id,
        CoreFactSet(
            document_profiles=(
                DocumentProfile(
                    document_id="paper-1",
                    collection_id=collection_id,
                    title="Profile Title",
                    source_filename="profile-paper.pdf",
                    doc_type="experimental",
                    parsing_warnings=(),
                    confidence=0.9,
                ),
            ),
        ),
    )
    return collection_id, objective.objective_id, ResearchObjectiveService(
        collection_service=collection_service,
        core_fact_repository=repository,
    )


def test_objective_workspace_lists_persisted_objectives(tmp_path):
    collection_id, objective_id, service = _seed_objective_collection(tmp_path)

    payload = service.list_objective_workspaces(collection_id)

    assert payload["collection_id"] == collection_id
    assert payload["state"] == "partial"
    assert payload["readiness"] == {
        "objectives_ready": True,
        "frames_ready": True,
        "routes_ready": True,
        "evidence_units_ready": False,
        "logic_chain_ready": False,
    }
    assert payload["objectives"][0]["objective_id"] == objective_id
    assert payload["objectives"][0]["paper_frame_count"] == 1
    assert payload["objectives"][0]["evidence_route_count"] == 1


def test_objective_workspace_detail_returns_frames_and_reserved_fields(tmp_path):
    collection_id, objective_id, service = _seed_objective_collection(tmp_path)

    payload = service.get_objective_research_view(collection_id, objective_id)

    assert payload["collection_id"] == collection_id
    assert payload["objective"]["objective_id"] == objective_id
    assert payload["objective_context"]["variable_process_axes"] == ["heat treatment"]
    assert payload["paper_frames"][0]["title"] == "Profile Title"
    assert payload["paper_frames"][0]["source_filename"] == "profile-paper.pdf"
    assert payload["paper_frames"][0]["relevant_tables"] == ["table-1"]
    assert payload["evidence_routes"][0]["source_ref"] == "table-1"
    assert payload["evidence_units"] == []
    assert payload["logic_chain"] is None
    assert payload["existing_comparison_rows"] == []


def test_objective_workspace_detail_raises_for_missing_objective(tmp_path):
    collection_id, _, service = _seed_objective_collection(tmp_path)

    with pytest.raises(ResearchObjectiveNotFoundError) as exc_info:
        service.get_objective_research_view(collection_id, "obj_missing")

    assert exc_info.value.collection_id == collection_id
    assert exc_info.value.objective_id == "obj_missing"
