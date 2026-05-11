from __future__ import annotations

from typing import Any

from application.core.semantic_build.llm.schemas import (
    StructuredDocumentProfile,
    StructuredPaperSkim,
    StructuredResearchObjective,
    StructuredResearchObjectives,
)
from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveService,
)
from application.source.collection_service import CollectionService
from domain.source import SourceArtifactSet


class _ObjectiveExtractor:
    def __init__(self) -> None:
        self.skim_payloads: list[dict[str, Any]] = []
        self.discovery_payloads: list[dict[str, Any]] = []

    def extract_document_profile(
        self,
        payload: dict[str, Any],
    ) -> StructuredDocumentProfile:
        title = str(payload.get("title") or "")
        return StructuredDocumentProfile(
            doc_type="review" if "Review" in title else "experimental",
            parsing_warnings=[],
            confidence=0.9,
        )

    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        title = str(payload.get("title") or "")
        if "Review" in title:
            return StructuredPaperSkim(
                doc_role="review",
                candidate_materials=["316L stainless steel"],
                candidate_processes=[],
                candidate_properties=[],
                changed_variables=[],
                possible_objectives=[],
                evidence_density="low",
                confidence=0.72,
                warnings=[],
            )
        return StructuredPaperSkim(
            doc_role="experimental",
            candidate_materials=["316L stainless steel"],
            candidate_processes=["LPBF", "heat treatment"],
            candidate_properties=["corrosion"],
            changed_variables=["heat treatment temperature"],
            possible_objectives=[
                "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?"
            ],
            evidence_density="high",
            confidence=0.91,
            warnings=[],
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question="How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?",
                    material_scope=["316L stainless steel"],
                    process_axes=["LPBF", "heat treatment"],
                    property_axes=["corrosion"],
                    comparison_intent="compare as-built and heat-treated corrosion behavior",
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=["paper-2"],
                    confidence=0.88,
                    reason="paper skims share a clear material-process-property axis",
                ),
                StructuredResearchObjective(
                    question="316L stainless steel",
                    material_scope=["316L stainless steel"],
                    process_axes=[],
                    property_axes=[],
                    comparison_intent=None,
                    seed_document_ids=[],
                    excluded_document_ids=[],
                    confidence=0.4,
                    reason="plain material list should be filtered",
                ),
            ]
        )


class _BroadObjectiveExtractor(_ObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            candidate_materials=["316L stainless steel"],
            candidate_processes=["Selective Laser Melting"],
            candidate_properties=[
                "mechanical properties",
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "microhardness",
            ],
            changed_variables=[
                "energy density",
                "scanning strategy",
                "scanning speed",
            ],
            possible_objectives=[
                "What is the relationship between SLM processing parameters "
                "and mechanical properties of 316L stainless steel?"
            ],
            evidence_density="high",
            confidence=0.91,
            warnings=[],
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "What is the relationship between SLM processing parameters "
                        "and mechanical properties of 316L stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=["Selective Laser Melting"],
                    property_axes=["mechanical properties"],
                    comparison_intent=None,
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.88,
                    reason="paper skim points to mechanical-property comparison",
                )
            ]
        )


class _DuplicateMechanicalObjectiveExtractor(_BroadObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "How do energy density, scanning strategy, and scanning "
                        "speed affect the densification and microstructure of "
                        "316L stainless steel processed via Selective Laser "
                        "Melting?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=[
                        "Selective Laser Melting",
                        "energy density",
                        "scanning strategy",
                        "scanning speed",
                    ],
                    property_axes=["densification", "microstructure"],
                    comparison_intent=(
                        "Compare the effects of energy density, scanning strategy, "
                        "and scanning speed on densification and microstructure."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="processing parameters affect density and structure",
                ),
                StructuredResearchObjective(
                    question=(
                        "What are the effects of varying energy density and "
                        "scanning speed on yield strength, ultimate tensile "
                        "strength, elongation, and microhardness of 316L "
                        "stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=[
                        "Selective Laser Melting",
                        "energy density",
                        "scanning speed",
                    ],
                    property_axes=[
                        "yield strength",
                        "ultimate tensile strength",
                        "elongation",
                        "microhardness",
                    ],
                    comparison_intent=(
                        "Analyze how changes in energy density and scanning speed "
                        "influence mechanical properties."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="mechanical properties are reported together",
                ),
                StructuredResearchObjective(
                    question=(
                        "How does the scanning strategy influence the mechanical "
                        "properties, including yield strength and microhardness, "
                        "of 316L stainless steel in Selective Laser Melting?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=[
                        "Selective Laser Melting",
                        "scanning strategy",
                    ],
                    property_axes=["yield strength", "microhardness"],
                    comparison_intent=(
                        "Evaluate scanning strategy effects on yield strength "
                        "and microhardness."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="mechanical properties overlap with the prior objective",
                ),
            ]
        )


def test_research_objective_service_builds_and_persists_db_records(tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Collection")
    collection_id = collection["collection_id"]
    extractor = _ObjectiveExtractor()
    service = ResearchObjectiveService(
        collection_service=collection_service,
        structured_extractor=extractor,
    )
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
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
                }
            ],
        ),
    )

    objectives = service.build_research_objectives(collection_id)

    assert len(objectives) == 1
    assert objectives[0].question.startswith("How does heat treatment")
    facts = service.core_fact_repository.read_collection_facts(collection_id)
    assert facts.research_objectives_ready is True
    assert len(facts.paper_skims) == 2
    assert facts.paper_skims[0].source_filename == "paper-1.pdf"
    assert facts.research_objectives[0].excluded_document_ids == ("paper-2",)
    assert extractor.skim_payloads[0]["table_captions"][0]["table_id"] == "table-1"
    assert extractor.discovery_payloads[0]["paper_skims"][0]["document_id"] == "paper-1"

    skim_call_count = len(extractor.skim_payloads)
    assert service.read_research_objectives(collection_id) == objectives
    assert len(extractor.skim_payloads) == skim_call_count
    output_dir = collection_service.get_paths(collection_id).output_dir
    assert not list(output_dir.glob("*objective*"))


def test_research_objective_service_strengthens_broad_objective_axes(tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Strengthening")
    collection_id = collection["collection_id"]
    service = ResearchObjectiveService(
        collection_service=collection_service,
        structured_extractor=_BroadObjectiveExtractor(),
    )
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
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

    objectives = service.build_research_objectives(collection_id)

    assert len(objectives) == 1
    objective = objectives[0]
    assert objective.comparison_intent is not None
    assert "energy density" in objective.process_axes
    assert "scanning strategy" in objective.process_axes
    assert "scanning speed" in objective.process_axes
    assert "yield strength" in objective.property_axes
    assert "ultimate tensile strength" in objective.property_axes
    assert "elongation" in objective.property_axes
    assert "microhardness" in objective.property_axes


def test_research_objective_service_merges_overlapping_mechanical_objectives(
    tmp_path,
):
    collection_service = CollectionService(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Merge")
    collection_id = collection["collection_id"]
    service = ResearchObjectiveService(
        collection_service=collection_service,
        structured_extractor=_DuplicateMechanicalObjectiveExtractor(),
    )
    service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
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

    objectives = service.build_research_objectives(collection_id)

    assert len(objectives) == 2
    structure_objective = next(
        objective
        for objective in objectives
        if "densification" in objective.property_axes
    )
    mechanical_objective = next(
        objective
        for objective in objectives
        if "yield strength" in objective.property_axes
    )
    assert structure_objective.property_axes == ("densification", "microstructure")
    assert "energy density" in mechanical_objective.process_axes
    assert "scanning speed" in mechanical_objective.process_axes
    assert "scanning strategy" in mechanical_objective.process_axes
    assert mechanical_objective.property_axes == (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    )
    assert mechanical_objective.question.startswith("How do")
