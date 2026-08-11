from __future__ import annotations

from types import SimpleNamespace

from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from domain.core import PaperSkim
from domain.source import SourceArtifactSet
from tests.support.collection_service import build_test_collection_service
from tests.support.objective_candidate_extractors import (
    AxisQuestionMismatchExtractor as _AxisQuestionMismatchExtractor,
    BroadObjectiveExtractor as _BroadObjectiveExtractor,
    CanonicalizingAxisExtractor as _CanonicalizingAxisExtractor,
    CrossCandidateAxisExtractor as _CrossCandidateAxisExtractor,
    CrossObjectiveAxisMergeExtractor as _CrossObjectiveAxisMergeExtractor,
    DisjointPropertyMergeExtractor as _DisjointPropertyMergeExtractor,
    DroppedObjectiveMergeExtractor as _DroppedObjectiveMergeExtractor,
    DuplicateMechanicalObjectiveExtractor as _DuplicateMechanicalObjectiveExtractor,
    DuplicateObjectiveIdExtractor as _DuplicateObjectiveIdExtractor,
    InvalidAxisCanonicalizationExtractor as _InvalidAxisCanonicalizationExtractor,
    InventedAxisMergeExtractor as _InventedAxisMergeExtractor,
    MissingSeedObjectiveExtractor as _MissingSeedObjectiveExtractor,
    OmittedMaterialScopeExtractor as _OmittedMaterialScopeExtractor,
    OppositeDirectionMergeExtractor as _OppositeDirectionMergeExtractor,
    OverbroadAxisCanonicalizationExtractor as _OverbroadAxisCanonicalizationExtractor,
    OverbroadPersistedObjectiveExtractor as _OverbroadPersistedObjectiveExtractor,
    SingleMixedObjectiveExtractor as _SingleMixedObjectiveExtractor,
    UnderSpecifiedMergeQuestionExtractor as _UnderSpecifiedMergeQuestionExtractor,
    UnmatchedSeedObjectiveExtractor as _UnmatchedSeedObjectiveExtractor,
)
from tests.support.objective_extractor import (
    FakeObjectiveExtractor as _ObjectiveExtractor,
)
from tests.support.research_objective_service import (
    build_research_objective_service as _build_research_objective_service,
    research_objective as _research_objective,
    seed_document_profiles as _seed_document_profiles,
)


def test_objective_candidate_service_canonicalizes_model_document_references(
):
    service = ObjectiveCandidateService()
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "seed_document_ids": ["stored/P003.pdf", "canonical-1", "unknown"],
            "excluded_document_ids": ["paper-2.pdf"],
        }
    )
    documents = [
        SimpleNamespace(
            document_id="canonical-1",
            metadata={"source_path": "stored/P003.pdf"},
        ),
        SimpleNamespace(
            document_id="canonical-2",
            metadata={"source_filename": "paper-2.pdf"},
        ),
    ]

    normalized = service._canonicalize_objective_document_ids(
        objective,
        documents=documents,
    )

    assert normalized.seed_document_ids == ("canonical-1",)
    assert normalized.excluded_document_ids == ("canonical-2",)


def test_objective_candidate_service_repairs_one_character_truncated_document_id(
):
    service = ObjectiveCandidateService()
    canonical_id = "a" * 127 + "0"
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "seed_document_ids": [canonical_id[:-1]],
        }
    )

    normalized = service._canonicalize_objective_document_ids(
        objective,
        documents=[SimpleNamespace(document_id=canonical_id, metadata={})],
    )

    assert normalized.seed_document_ids == (canonical_id,)


def test_objective_candidate_service_rejects_ambiguous_or_overtruncated_document_id(
):
    service = ObjectiveCandidateService()
    common_prefix = "a" * 127
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "seed_document_ids": [common_prefix, common_prefix[:-1]],
        }
    )

    normalized = service._canonicalize_objective_document_ids(
        objective,
        documents=[
            SimpleNamespace(document_id=common_prefix + "0", metadata={}),
            SimpleNamespace(document_id=common_prefix + "1", metadata={}),
        ],
    )

    assert normalized.seed_document_ids == ()


def test_objective_discovery_skim_keeps_three_complete_candidate_questions():
    candidates = (
        "How does " + "very long processing condition " * 8 + "affect porosity?",
        "How does laser power affect porosity?",
        "How does heat treatment affect corrosion resistance?",
        "How does aging affect yield strength?",
        "How does scanning speed affect density?",
    )
    skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "possible_objectives": candidates,
        }
    )

    discovery_skim = ObjectiveCandidateService._build_objective_discovery_skim(skim)

    assert discovery_skim["possible_objectives"] == list(candidates[1:4])
    assert all(
        candidate.endswith("?")
        for candidate in discovery_skim["possible_objectives"]
    )


def test_objective_discovery_skim_preserves_structured_research_map():
    skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "doc_role": "experimental",
            "candidate_materials": ["316L stainless steel"],
            "candidate_processes": ["laser powder bed fusion"],
            "candidate_properties": ["relative density", "porosity"],
            "changed_variables": ["laser power", "scan speed"],
            "possible_objectives": [
                "How do laser power and scan speed affect relative density?"
            ],
            "evidence_density": "high",
            "confidence": 0.91,
            "warnings": ["one table caption is truncated"],
        }
    )

    discovery_skim = ObjectiveCandidateService._build_objective_discovery_skim(skim)

    assert discovery_skim == {
        "document_id": "paper-1",
        "doc_role": "experimental",
        "candidate_materials": ["316L stainless steel"],
        "candidate_processes": ["laser powder bed fusion"],
        "candidate_properties": ["relative density", "porosity"],
        "changed_variables": ["laser power", "scan speed"],
        "possible_objectives": [
            "How do laser power and scan speed affect relative density?"
        ],
        "evidence_density": "high",
        "confidence": 0.91,
        "warnings": ["one table caption is truncated"],
    }


def test_structured_skim_axes_can_support_objective_without_question_hint():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How do laser power and scan speed affect relative density?",
            "variables": ["laser power", "scan speed"],
            "outcomes": ["relative density"],
        }
    )
    discovery_skim = {
        "changed_variables": ["laser power", "scan speed"],
        "candidate_properties": ["relative density"],
        "possible_objectives": [],
    }

    assert ObjectiveCandidateService._discovery_skim_supports_objective(
        discovery_skim,
        objective,
    )


def test_question_hint_cannot_override_conflicting_structured_skim_axes():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    discovery_skim = {
        "changed_variables": ["heat treatment"],
        "candidate_properties": ["yield strength"],
        "possible_objectives": ["How does laser power affect relative density?"],
    }

    assert not ObjectiveCandidateService._discovery_skim_supports_objective(
        discovery_skim,
        objective,
    )


def test_objective_candidate_service_recovers_material_shared_by_every_seed():
    service = ObjectiveCandidateService()
    paper_skims = (
        _paper_skim("paper-1", materials=["316L stainless steel"]),
        _paper_skim("paper-2", materials=["316L stainless steel (316L)"]),
    )

    objectives = service.discover_candidates(
        "collection-test",
        paper_skims=paper_skims,
        documents=_documents_for_skims(paper_skims),
        extractor=_OmittedMaterialScopeExtractor(),
    )

    assert len(objectives) == 1
    assert objectives[0].material_scope == ("316L stainless steel",)


def test_objective_candidate_service_does_not_guess_unshared_material():
    service = ObjectiveCandidateService()

    for materials in (
        (["316L stainless steel"], ["Ti-6Al-4V"]),
        (["316L stainless steel"], []),
    ):
        paper_skims = (
            _paper_skim("paper-1", materials=materials[0]),
            _paper_skim("paper-2", materials=materials[1]),
        )

        objectives = service.discover_candidates(
            "collection-test",
            paper_skims=paper_skims,
            documents=_documents_for_skims(paper_skims),
            extractor=_OmittedMaterialScopeExtractor(),
        )

        assert len(objectives) == 1
        assert objectives[0].material_scope == ()


def test_research_objective_service_builds_and_persists_objective_records(
    tmp_path,
    caplog,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Collection")
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
                },
                {
                    "id": "paper-2",
                    "title": "Review of Stainless Steel Corrosion",
                    "text": "This review summarizes stainless steel corrosion literature.",
                    "metadata": {"source_filename": "review.pdf"},
                },
            ],
            blocks=[
                {
                    "block_id": "b1",
                    "document_id": "paper-1",
                    "block_type": "heading",
                    "text": "Abstract",
                    "block_order": 1,
                },
                {
                    "block_id": "b2",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": "LPBF 316L was compared before and after heat treatment.",
                    "block_order": 2,
                    "heading_path": "Abstract",
                },
                {
                    "block_id": "b2b",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": "Additional abstract context stayed in the same section.",
                    "block_order": 3,
                    "heading_path": "Abstract",
                },
                {
                    "block_id": "b-ref-heading",
                    "document_id": "paper-1",
                    "block_type": "heading",
                    "text": "References",
                    "block_order": 90,
                    "heading_path": "References",
                    "heading_level": 1,
                },
                {
                    "block_id": "b-ref-body",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": "Reference text should not be skimmed as paper evidence.",
                    "block_order": 91,
                    "heading_path": "References",
                },
                {
                    "block_id": "b3",
                    "document_id": "paper-2",
                    "block_type": "paragraph",
                    "text": "This review summarizes prior corrosion studies.",
                    "block_order": 1,
                    "heading_path": "Abstract",
                },
            ],
            tables=[
                {
                    "table_id": "table-1",
                    "document_id": "paper-1",
                    "table_order": 1,
                    "caption_text": "Corrosion comparison of as-built and heat-treated LPBF 316L",
                    "heading_path": "Results",
                    "column_headers": ["sample", "corrosion current"],
                    "table_matrix": [
                        ["sample", "corrosion current"],
                        ["as-built", "1.2 uA/cm2"],
                        ["heat-treated", "0.4 uA/cm2"],
                    ],
                },
                {
                    "table_id": "table-2",
                    "document_id": "paper-1",
                    "table_order": 2,
                    "caption_text": "Nominal chemical composition of 316L powder",
                    "heading_path": "Experimental",
                    "column_headers": ["Fe", "Cr", "Ni", "Mo"],
                    "table_matrix": [
                        ["Fe", "Cr", "Ni", "Mo"],
                        ["balance", "17", "12", "2.5"],
                    ],
                }
            ],
        ),
    )
    _seed_document_profiles(service, collection_id)

    with caplog.at_level("INFO"):
        objectives = service.discover_and_replace_objective_candidates(
            collection_id,
            build_id="build_test",
        )

    assert len(objectives) == 1
    assert objectives[0].question.startswith("How does heat treatment")
    facts = service.objective_repository.read(collection_id)
    assert facts.research_objectives_ready is True
    assert len(facts.paper_skims) == 2
    assert facts.paper_skims[0].document_id == "paper-1"
    source_artifacts = service.source_artifact_repository.read_collection_artifacts(
        collection_id,
        build_id="build_test",
    )
    assert source_artifacts.documents[0].metadata["source_filename"] == "paper-1.pdf"
    assert facts.research_objectives[0].excluded_document_ids == ("paper-2",)
    assert facts.research_objectives == objectives
    assert service.objective_repository.list_objectives(collection_id) == objectives
    assert objectives[0].confirmation_status == "candidate"
    assert objectives[0].active_analysis_version is None
    assert objectives[0].published_analysis_version is None
    assert extractor.frame_payloads == []
    assert extractor.route_payloads == []
    assert extractor.unit_payloads == []
    assert extractor.skim_payloads[0]["headings"] == ["Abstract", "References"]
    assert "Additional abstract context" in extractor.skim_payloads[0]["text_preview"]
    assert "Reference text should not" not in extractor.skim_payloads[0]["text_preview"]
    assert extractor.skim_payloads[0]["table_captions"][0]["table_id"] == "table-1"
    assert extractor.discovery_payloads[0]["paper_skims"][0]["document_id"] == "paper-1"
    discovery_skim = extractor.discovery_payloads[0]["paper_skims"][0]
    assert set(discovery_skim) == {
        "document_id",
        "doc_role",
        "candidate_materials",
        "candidate_processes",
        "candidate_properties",
        "changed_variables",
        "possible_objectives",
        "evidence_density",
        "confidence",
        "warnings",
    }
    assert discovery_skim["changed_variables"] == ["heat treatment temperature"]
    assert discovery_skim["candidate_properties"] == ["corrosion"]
    assert discovery_skim["possible_objectives"] == [
        "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?"
    ]
    assert "text_preview" not in discovery_skim
    assert "document_profile" not in discovery_skim
    assert any(
        "Research objective paper skim document started" in record.message
        and "document_position=1" in record.message
        for record in caplog.records
    )
    assert any(
        "Research objective discovery finished" in record.message
        and "accepted_objective_count=1" in record.message
        for record in caplog.records
    )
    output_dir = collection_service.get_paths(collection_id).output_dir
    assert not list(output_dir.glob("*objective*"))


def test_research_objective_service_preserves_discovered_scientific_intent(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Strengthening")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        objective_extractor=_BroadObjectiveExtractor(),
    )
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        "build_test",
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "SLM 316L Mechanical Properties",
                    "text": (
                        "Energy density and scanning strategy changed "
                        "mechanical properties."
                    ),
                    "metadata": {"source_filename": "paper-1.pdf"},
                }
            ],
            blocks=[
                {
                    "block_id": "b1",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": (
                        "Energy density and scanning strategy changed "
                        "mechanical properties."
                    ),
                    "block_order": 1,
                }
            ],
        ),
    )
    _seed_document_profiles(service, collection_id)

    objectives = service.discover_and_replace_objective_candidates(
        collection_id,
        build_id="build_test",
    )

    assert len(objectives) == 1
    objective = objectives[0]
    assert objective.variables == (
        "energy density",
        "scanning strategy",
        "scanning speed",
    )
    assert objective.outcomes == ("mechanical properties",)
    assert objective.constraints == ("Selective Laser Melting",)
    assert objective.mechanisms == ()
    assert objective.requested_comparator is None


def test_research_objective_service_merges_overlapping_mechanical_objectives(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Merge")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        objective_extractor=_DuplicateMechanicalObjectiveExtractor(),
    )
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        "build_test",
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "SLM 316L Mechanical Properties",
                    "text": (
                        "Energy density, scanning speed, and scanning strategy "
                        "changed densification and mechanical properties."
                    ),
                    "metadata": {"source_filename": "paper-1.pdf"},
                }
            ],
            blocks=[
                {
                    "block_id": "b1",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": (
                        "Energy density, scanning speed, and scanning strategy "
                        "changed densification and mechanical properties."
                    ),
                    "block_order": 1,
                }
            ],
        ),
    )
    _seed_document_profiles(service, collection_id)

    objectives = service.discover_and_replace_objective_candidates(
        collection_id,
        build_id="build_test",
    )

    assert len(objectives) == 2
    structure_objective = next(
        objective
        for objective in objectives
        if "densification" in objective.outcomes
    )
    mechanical_objective = next(
        objective
        for objective in objectives
        if "yield strength" in objective.outcomes
    )
    assert structure_objective.outcomes == ("densification", "microstructure")
    assert "energy density" in mechanical_objective.variables
    assert "scanning speed" in mechanical_objective.variables
    assert "scanning strategy" in mechanical_objective.variables
    assert mechanical_objective.outcomes == (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    )
    assert mechanical_objective.question.startswith("How do")


def test_research_objective_service_persists_definitions_without_analysis_artifacts(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Contexts")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        objective_extractor=_DuplicateMechanicalObjectiveExtractor(),
    )
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        "build_test",
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "SLM 316L Mechanical Properties",
                    "text": (
                        "Energy density, scanning speed, and scanning strategy "
                        "changed densification and mechanical properties."
                    ),
                    "metadata": {"source_filename": "paper-1.pdf"},
                }
            ],
            blocks=[
                {
                    "block_id": "b1",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": (
                        "Energy density, scanning speed, and scanning strategy "
                        "changed densification and mechanical properties."
                    ),
                    "block_order": 1,
                }
            ],
            tables=[
                {
                    "table_id": "table-1",
                    "document_id": "paper-1",
                    "table_order": 1,
                    "caption_text": "Table 1 SLM processing parameters along with relative densities.",
                    "column_headers": [
                        "Sample number",
                        "Scan strategy",
                        "Scanning speed (mm/s)",
                        "Energy density (J/mm3)",
                        "Relative density",
                    ],
                    "table_matrix": [
                        [
                            "Sample number",
                            "Scan strategy",
                            "Scanning speed (mm/s)",
                            "Energy density (J/mm3)",
                            "Relative density",
                        ],
                        ["1", "A", "0.25", "70", "95.4"],
                    ],
                },
                {
                    "table_id": "table-2",
                    "document_id": "paper-1",
                    "table_order": 2,
                    "caption_text": (
                        "Table 2 Mechanical properties (yield strength, ultimate "
                        "tensile strength, and elongation) of SLM processed samples "
                        "along with microhardness values."
                    ),
                    "column_headers": [
                        "Sample number",
                        "Yield Strength (MPa)",
                        "Ultimate Tensile Strength (MPa)",
                        "Elongation (%)",
                        "Microhadness (HV)",
                    ],
                    "table_matrix": [
                        [
                            "Sample number",
                            "Yield Strength (MPa)",
                            "Ultimate Tensile Strength (MPa)",
                            "Elongation (%)",
                            "Microhadness (HV)",
                        ],
                        ["1", "236.65", "375.13", "7.21", "215.65"],
                    ],
                },
            ],
        ),
    )
    _seed_document_profiles(service, collection_id)

    objectives = service.discover_and_replace_objective_candidates(
        collection_id,
        build_id="build_test",
    )
    facts = service.objective_repository.read(collection_id)
    structure_objective = next(
        objective for objective in objectives if "densification" in objective.outcomes
    )
    mechanical_objective = next(
        objective for objective in objectives if "yield strength" in objective.outcomes
    )
    assert structure_objective.variables == (
        "energy density",
        "scanning strategy",
        "scanning speed",
    )
    assert structure_objective.constraints == ("Selective Laser Melting",)
    assert mechanical_objective.outcomes == (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    )
    assert facts.research_objectives == objectives
    assert service._objective_extractor.frame_payloads == []
    assert service._objective_extractor.route_payloads == []
    assert service._objective_extractor.unit_payloads == []


def test_research_objective_service_canonicalizes_axis_aliases_with_llm(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _CanonicalizingAxisExtractor(),
    )

    assert len(objectives) == 2
    all_variables = [
        process_axis
        for objective in objectives
        for process_axis in objective.variables
    ]
    assert "scanning strategy" in all_variables
    assert "scan strategy" not in all_variables


def test_research_objective_service_rejects_axis_canonicalization_that_breaks_question(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _AxisQuestionMismatchExtractor(),
    )

    assert len(objectives) == 1
    assert objectives[0].variables == ("scan strategy",)
    assert objectives[0].question == "How does scan strategy affect porosity?"


def test_research_objective_service_falls_back_when_axis_plan_drops_axes(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _InvalidAxisCanonicalizationExtractor(),
    )

    all_variables = [
        process_axis
        for objective in objectives
        for process_axis in objective.variables
    ]
    assert "scanning strategy" in all_variables
    assert "scan strategy" not in all_variables


def test_research_objective_service_rejects_overbroad_axis_canonicalization(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _OverbroadAxisCanonicalizationExtractor(),
    )

    assert len(objectives) == 2
    all_variables = [
        process_axis
        for objective in objectives
        for process_axis in objective.variables
    ]
    assert "energy density" in all_variables
    assert "scanning speed" in all_variables
    assert "scanning strategy" in all_variables
    assert all(
        objective.constraints == ("Selective Laser Melting",)
        for objective in objectives
    )


def test_research_objective_service_keeps_candidates_after_rejected_merge_plan(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _DroppedObjectiveMergeExtractor(),
    )

    assert len(objectives) == 3
    assert {objective.outcomes for objective in objectives} == {
        ("densification", "microstructure"),
        ("yield strength", "ultimate tensile strength", "elongation", "microhardness"),
        ("yield strength", "microhardness"),
    }


def test_research_objective_service_falls_back_when_merge_plan_invents_axis(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _InventedAxisMergeExtractor(),
    )

    assert len(objectives) == 3
    assert all("laser power" not in objective.variables for objective in objectives)


def test_research_objective_service_rejects_merge_plan_with_cross_objective_axis(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _CrossObjectiveAxisMergeExtractor(),
    )

    assert len(objectives) == 2
    mechanical_objective = next(
        objective
        for objective in objectives
        if "yield strength" in objective.outcomes
    )
    corrosion_objective = next(
        objective
        for objective in objectives
        if "corrosion potential" in objective.outcomes
    )
    assert "porosity" not in mechanical_objective.variables
    assert "porosity" in corrosion_objective.variables


def test_research_objective_service_rejects_completed_opposite_direction_merge(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _OppositeDirectionMergeExtractor(),
    )

    assert len(objectives) == 2
    assert {objective.variables for objective in objectives} == {
        ("porosity",),
        ("density",),
    }
    assert {objective.outcomes for objective in objectives} == {
        ("density", "roughness"),
        ("porosity", "roughness"),
    }


def test_research_objective_service_rejects_axes_combined_across_skim_candidates(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _CrossCandidateAxisExtractor(),
    )

    assert objectives == ()


def test_research_objective_service_does_not_global_fill_unmatched_seed_axes(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _UnmatchedSeedObjectiveExtractor(),
    )

    assert objectives == ()


def test_research_objective_service_recovers_unique_missing_seed_document_id(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _MissingSeedObjectiveExtractor(),
    )

    assert len(objectives) == 1
    assert objectives[0].seed_document_ids == ("paper-1",)


def test_research_objective_service_rejects_ambiguous_missing_seed_document_id(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection_id = collection_service.create_collection("Ambiguous seeds")[
        "collection_id"
    ]
    service = _build_research_objective_service(
        collection_service=collection_service,
        objective_extractor=_MissingSeedObjectiveExtractor(),
    )
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        "build_test",
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": document_id,
                    "title": "LPBF 316L corrosion experiment",
                    "text": "Heat treatment changed corrosion resistance.",
                }
                for document_id in ("paper-1", "paper-2")
            ],
            blocks=[
                {
                    "block_id": f"{document_id}-abstract",
                    "document_id": document_id,
                    "block_type": "paragraph",
                    "text": "Heat treatment changed corrosion resistance.",
                    "block_order": 1,
                }
                for document_id in ("paper-1", "paper-2")
            ],
        ),
    )
    _seed_document_profiles(service, collection_id)

    objectives = service.discover_and_replace_objective_candidates(
        collection_id,
        build_id="build_test",
    )

    assert objectives == ()


def test_research_objective_service_rejects_overbroad_candidate_definition(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Display")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        objective_extractor=_OverbroadPersistedObjectiveExtractor(),
    )
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        "build_test",
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "SLM 316L Mechanical Properties",
                    "text": (
                        "Energy density and scanning speed changed yield strength."
                    ),
                    "metadata": {"source_filename": "paper-1.pdf"},
                }
            ],
            blocks=[
                {
                    "block_id": "b1",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": (
                        "Energy density and scanning speed changed yield strength."
                    ),
                    "block_order": 1,
                }
            ],
        ),
    )
    _seed_document_profiles(service, collection_id)

    objectives = service.discover_and_replace_objective_candidates(
        collection_id,
        build_id="build_test",
    )

    assert service.objective_repository.list_objectives(collection_id) == objectives
    assert objectives == ()


def test_research_objective_service_rejects_merge_with_disjoint_outcomes(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _DisjointPropertyMergeExtractor(),
    )

    assert len(objectives) == 3
    assert {objective.outcomes for objective in objectives} == {
        ("densification", "microstructure"),
        ("yield strength", "ultimate tensile strength", "elongation", "microhardness"),
        ("yield strength", "microhardness"),
    }


def test_research_objective_service_rejects_merge_that_drops_variable_intent(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _UnderSpecifiedMergeQuestionExtractor(),
    )

    assert len(objectives) == 3
    assert all(
        objective.question
        != "What is the relationship between scanning speed and the mechanical properties of 316L stainless steel?"
        for objective in objectives
    )


def test_research_objective_service_rejects_single_cross_candidate_objective(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _SingleMixedObjectiveExtractor(),
    )

    assert objectives == ()


def test_research_objective_service_dedupes_repeated_objective_ids_before_persist(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Duplicate Objectives")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        objective_extractor=_DuplicateObjectiveIdExtractor(),
    )
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
        ),
    )
    _seed_document_profiles(service, collection_id)

    objectives = service.discover_and_replace_objective_candidates(
        collection_id,
        build_id="build_test",
    )

    assert len(objectives) == 1
    facts = service.objective_repository.read(collection_id)
    assert len(facts.research_objectives) == 1


def _build_duplicate_paper_objectives(
    tmp_path,
    extractor: _ObjectiveExtractor,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Merge")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        objective_extractor=extractor,
    )
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        "build_test",
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "SLM 316L Mechanical Properties",
                    "text": (
                        "Energy density, scanning speed, and scanning strategy "
                        "changed densification and mechanical properties."
                    ),
                    "metadata": {"source_filename": "paper-1.pdf"},
                }
            ],
            blocks=[
                {
                    "block_id": "b1",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": (
                        "Energy density, scanning speed, and scanning strategy "
                        "changed densification and mechanical properties."
                    ),
                    "block_order": 1,
                }
            ],
        ),
    )
    _seed_document_profiles(service, collection_id)
    return service.discover_and_replace_objective_candidates(
        collection_id,
        build_id="build_test",
    )


def _paper_skim(document_id: str, *, materials: list[str]) -> PaperSkim:
    return PaperSkim.from_mapping(
        {
            "document_id": document_id,
            "doc_role": "experimental",
            "candidate_materials": materials,
            "candidate_properties": ["relative density"],
            "changed_variables": ["laser power"],
            "possible_objectives": [
                "How does laser power affect relative density?"
            ],
            "evidence_density": "high",
            "confidence": 0.9,
        }
    )


def _documents_for_skims(
    paper_skims: tuple[PaperSkim, ...],
) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(document_id=skim.document_id, metadata={})
        for skim in paper_skims
    ]
