from __future__ import annotations

from typing import Any

from application.core.semantic_build.llm.schemas import (
    StructuredAxisCanonicalizationGroup,
    StructuredAxisCanonicalizationPlan,
    StructuredDocumentProfile,
    StructuredObjectiveEvidenceRoute,
    StructuredObjectiveEvidenceRoutes,
    StructuredObjectiveMergeGroup,
    StructuredObjectiveMergePlan,
    StructuredObjectivePaperFrame,
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
        self.canonicalization_payloads: list[dict[str, Any]] = []
        self.merge_payloads: list[dict[str, Any]] = []
        self.frame_payloads: list[dict[str, Any]] = []
        self.route_payloads: list[dict[str, Any]] = []

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

    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            axis_groups=[
                StructuredAxisCanonicalizationGroup(
                    axis_type=axis_type,
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for axis_type, values in payload["axis_candidates"].items()
                for value in values
            ]
        )

    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[candidate["objective_id"]],
                    question=candidate["question"],
                    material_scope=candidate["material_scope"],
                    process_axes=candidate["process_axes"],
                    property_axes=candidate["property_axes"],
                    comparison_intent=candidate["comparison_intent"],
                    confidence=candidate["confidence"],
                    reason=candidate["reason"],
                )
                for candidate in payload["candidate_objectives"]
            ]
        )

    def frame_objective_paper(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectivePaperFrame:
        self.frame_payloads.append(payload)
        objective = payload["objective"]
        document = payload["document"]
        paper_skim = payload["paper_skim"]
        document_id = str(document.get("document_id") or "")
        table_summaries = payload["table_summaries"]
        if document_id in objective.get("excluded_document_ids", ()):
            return StructuredObjectivePaperFrame(
                relevance="irrelevant",
                paper_role="review",
                background="Excluded by objective discovery.",
                material_match=[],
                changed_variables=[],
                measured_property_scope=[],
                test_environment_scope=[],
                relevant_sections=[],
                relevant_tables=[],
                excluded_tables=[
                    table["table_id"]
                    for table in table_summaries
                    if table.get("table_id")
                ],
            )
        relevant_tables = self._matching_frame_table_ids(
            table_summaries,
            axes=(
                *objective.get("process_axes", ()),
                *objective.get("property_axes", ()),
            ),
        )
        section_labels = [
            item["section_label"]
            for item in payload["section_snippets"]
            if item.get("section_label")
        ]
        return StructuredObjectivePaperFrame(
            relevance="high",
            paper_role="primary_experiment",
            background="Paper directly supports the active research objective.",
            material_match=list(paper_skim.get("candidate_materials") or []),
            changed_variables=list(paper_skim.get("changed_variables") or []),
            measured_property_scope=list(objective.get("property_axes") or []),
            test_environment_scope=[],
            relevant_sections=section_labels[:2],
            relevant_tables=relevant_tables,
            excluded_tables=[
                table["table_id"]
                for table in table_summaries
                if table.get("table_id") and table["table_id"] not in relevant_tables
            ],
        )

    def _matching_frame_table_ids(
        self,
        table_summaries: list[dict[str, Any]],
        *,
        axes: tuple[str, ...],
    ) -> list[str]:
        table_ids: list[str] = []
        for table in table_summaries:
            text = " ".join(
                str(value or "")
                for value in (
                    table.get("caption_text"),
                    table.get("heading_path"),
                    " ".join(table.get("column_headers") or []),
                )
            ).lower()
            if any(str(axis or "").lower() in text for axis in axes):
                table_ids.append(str(table["table_id"]))
        return table_ids

    def route_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveEvidenceRoutes:
        self.route_payloads.append(payload)
        objective = payload["objective"]
        routes: list[StructuredObjectiveEvidenceRoute] = []
        for candidate in payload["source_candidates"]:
            if candidate["frame_status"] == "excluded":
                routes.append(
                    StructuredObjectiveEvidenceRoute(
                        source_kind=candidate["source_kind"],
                        source_ref=candidate["source_ref"],
                        role="low_value_or_irrelevant",
                        extractable=False,
                        reason="Excluded by objective paper frame.",
                        confidence=0.7,
                    )
                )
                continue
            if candidate["source_kind"] == "text_window":
                routes.append(
                    StructuredObjectiveEvidenceRoute(
                        source_kind="text_window",
                        source_ref=candidate["source_ref"],
                        role="process_or_treatment",
                        extractable=True,
                        reason="Text window is in a relevant objective section.",
                        confidence=0.72,
                    )
                )
                continue
            table_schema = candidate.get("table_schema") or {}
            text = " ".join(
                str(value or "")
                for value in (
                    candidate.get("caption_text"),
                    candidate.get("heading_path"),
                    " ".join(table_schema.get("column_headers") or []),
                )
            ).lower()
            property_axes = [
                str(axis or "").lower()
                for axis in objective.get("property_axes", ())
                if str(axis or "").strip()
            ]
            role = (
                "current_experimental_evidence"
                if any(axis in text for axis in property_axes)
                else "process_or_treatment"
            )
            routes.append(
                StructuredObjectiveEvidenceRoute(
                    source_kind="table",
                    source_ref=candidate["source_ref"],
                    role=role,
                    extractable=True,
                    reason="Table is relevant for this objective.",
                    table_schema=table_schema,
                    column_roles={
                        header: "target_property"
                        for header in table_schema.get("column_headers", [])
                        if any(axis in str(header).lower() for axis in property_axes)
                    },
                    join_keys={"sample_key": "sample"}
                    if "sample" in text
                    else {},
                    join_plan={"join_on": "sample_key"}
                    if "sample" in text
                    else {},
                    confidence=0.82,
                )
            )
        return StructuredObjectiveEvidenceRoutes(routes=routes)


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

    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        candidates = payload["candidate_objectives"]
        structure_candidates = [
            candidate
            for candidate in candidates
            if "densification" in candidate["property_axes"]
        ]
        mechanical_candidates = [
            candidate
            for candidate in candidates
            if "yield strength" in candidate["property_axes"]
        ]
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[
                        candidate["objective_id"]
                        for candidate in structure_candidates
                    ],
                    question=structure_candidates[0]["question"],
                    material_scope=structure_candidates[0]["material_scope"],
                    process_axes=structure_candidates[0]["process_axes"],
                    property_axes=structure_candidates[0]["property_axes"],
                    comparison_intent=structure_candidates[0]["comparison_intent"],
                    confidence=0.9,
                    reason="kept structure objective separate",
                ),
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[
                        candidate["objective_id"]
                        for candidate in mechanical_candidates
                    ],
                    question=(
                        "How do energy density, scanning speed, and scanning "
                        "strategy affect the mechanical properties of 316L "
                        "stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=_merge_candidate_values(
                        mechanical_candidates,
                        "process_axes",
                    ),
                    property_axes=_merge_candidate_values(
                        mechanical_candidates,
                        "property_axes",
                    ),
                    comparison_intent=(
                        "Compare the combined effects of energy density, scanning "
                        "speed, and scanning strategy on mechanical properties."
                    ),
                    confidence=0.9,
                    reason="merged overlapping mechanical objectives",
                ),
            ]
        )


class _DroppedObjectiveMergeExtractor(_DuplicateMechanicalObjectiveExtractor):
    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        candidate = payload["candidate_objectives"][0]
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[candidate["objective_id"]],
                    question=candidate["question"],
                    material_scope=candidate["material_scope"],
                    process_axes=candidate["process_axes"],
                    property_axes=candidate["property_axes"],
                    comparison_intent=candidate["comparison_intent"],
                    confidence=candidate["confidence"],
                    reason="invalid plan drops other candidates",
                )
            ]
        )


class _CanonicalizingAxisExtractor(_DuplicateMechanicalObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            candidate_materials=["316L stainless steel"],
            candidate_processes=["Selective Laser Melting", "scanning strategy"],
            candidate_properties=[
                "mechanical properties",
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "microhardness",
                "densification",
                "microstructure",
            ],
            changed_variables=[
                "energy density",
                "scan strategy",
                "scanning speed",
            ],
            possible_objectives=[
                "How do SLM processing parameters affect 316L stainless steel?"
            ],
            evidence_density="high",
            confidence=0.91,
            warnings=[],
        )

    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            axis_groups=[
                StructuredAxisCanonicalizationGroup(
                    axis_type="material",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["material"]
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="process",
                    canonical="scanning strategy",
                    aliases=["scanning strategy", "scan strategy"],
                    confidence=0.95,
                    reason="same process variable phrased two ways",
                ),
                *[
                    StructuredAxisCanonicalizationGroup(
                        axis_type="process",
                        canonical=value,
                        aliases=[value],
                        confidence=1.0,
                        reason="kept separate",
                    )
                    for value in payload["axis_candidates"]["process"]
                    if value not in {"scanning strategy", "scan strategy"}
                ],
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="property",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["property"]
            ]
        )


class _InvalidAxisCanonicalizationExtractor(_CanonicalizingAxisExtractor):
    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            axis_groups=[
                StructuredAxisCanonicalizationGroup(
                    axis_type="process",
                    canonical="scanning strategy",
                    aliases=["scanning strategy", "scan strategy"],
                    confidence=0.95,
                    reason="invalid plan drops material and property axes",
                )
            ]
        )


class _OverbroadAxisCanonicalizationExtractor(_CanonicalizingAxisExtractor):
    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            axis_groups=[
                StructuredAxisCanonicalizationGroup(
                    axis_type="material",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["material"]
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="process",
                    canonical="Selective Laser Melting",
                    aliases=payload["axis_candidates"]["process"],
                    confidence=0.9,
                    reason="invalidly collapses distinct process axes",
                ),
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="property",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["property"]
            ]
        )


class _InventedAxisMergeExtractor(_DuplicateMechanicalObjectiveExtractor):
    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[candidate["objective_id"]],
                    question=candidate["question"],
                    material_scope=candidate["material_scope"],
                    process_axes=[
                        *candidate["process_axes"],
                        "laser power",
                    ],
                    property_axes=candidate["property_axes"],
                    comparison_intent=candidate["comparison_intent"],
                    confidence=candidate["confidence"],
                    reason="invalid plan invents an axis",
                )
                for candidate in payload["candidate_objectives"]
            ]
        )


class _DisjointPropertyMergeExtractor(_DuplicateMechanicalObjectiveExtractor):
    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        candidates = payload["candidate_objectives"]
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[
                        candidate["objective_id"]
                        for candidate in candidates
                    ],
                    question=(
                        "How do SLM parameters affect densification, "
                        "microstructure, and mechanical properties of 316L "
                        "stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=_merge_candidate_values(candidates, "process_axes"),
                    property_axes=_merge_candidate_values(candidates, "property_axes"),
                    comparison_intent=(
                        "Compare all reported structural and mechanical outcomes "
                        "under one objective."
                    ),
                    confidence=0.9,
                    reason="invalid plan merges disjoint property directions",
                )
            ]
        )


class _UnderSpecifiedMergeQuestionExtractor(_DuplicateMechanicalObjectiveExtractor):
    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        candidates = payload["candidate_objectives"]
        structure_candidates = [
            candidate
            for candidate in candidates
            if "densification" in candidate["property_axes"]
        ]
        mechanical_candidates = [
            candidate
            for candidate in candidates
            if "yield strength" in candidate["property_axes"]
        ]
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[
                        candidate["objective_id"]
                        for candidate in structure_candidates
                    ],
                    question=structure_candidates[0]["question"],
                    material_scope=structure_candidates[0]["material_scope"],
                    process_axes=structure_candidates[0]["process_axes"],
                    property_axes=structure_candidates[0]["property_axes"],
                    comparison_intent=structure_candidates[0]["comparison_intent"],
                    confidence=0.9,
                    reason="kept structure objective separate",
                ),
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[
                        candidate["objective_id"]
                        for candidate in mechanical_candidates
                    ],
                    question=(
                        "What is the relationship between scanning speed and "
                        "the mechanical properties of 316L stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=_merge_candidate_values(
                        mechanical_candidates,
                        "process_axes",
                    ),
                    property_axes=_merge_candidate_values(
                        mechanical_candidates,
                        "property_axes",
                    ),
                    comparison_intent=(
                        "Examine how variations in scanning speed influence "
                        "the mechanical properties of 316L stainless steel."
                    ),
                    confidence=0.9,
                    reason="merged overlapping mechanical objectives",
                ),
            ]
        )


class _SingleMixedObjectiveExtractor(_DuplicateMechanicalObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "How do SLM processing parameters affect densification, "
                        "microstructure, and mechanical properties of 316L "
                        "stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=[
                        "Selective Laser Melting",
                        "energy density",
                        "scanning strategy",
                        "scanning speed",
                    ],
                    property_axes=[
                        "densification",
                        "microstructure",
                        "yield strength",
                        "ultimate tensile strength",
                        "elongation",
                        "microhardness",
                    ],
                    comparison_intent=(
                        "Compare all reported structural and mechanical outcomes "
                        "under SLM parameter changes."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="invalidly mixed distinct property directions",
                )
            ]
        )


class _DuplicateObjectiveIdExtractor(_ObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        objective = StructuredResearchObjective(
            question="How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?",
            material_scope=["316L stainless steel"],
            process_axes=["LPBF", "heat treatment"],
            property_axes=["corrosion"],
            comparison_intent="compare heat treatment effects on corrosion",
            seed_document_ids=["paper-1"],
            excluded_document_ids=[],
            confidence=0.88,
            reason="duplicate objective emitted by model",
        )
        return StructuredResearchObjectives(objectives=[objective, objective])


def _merge_candidate_values(
    candidates: list[dict[str, Any]],
    key: str,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        for value in candidate[key]:
            text = str(value or "").strip()
            normalized = text.casefold()
            if not text or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(text)
    return merged


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

    objectives = service.build_research_objectives(collection_id)

    assert len(objectives) == 1
    assert objectives[0].question.startswith("How does heat treatment")
    facts = service.core_fact_repository.read_collection_facts(collection_id)
    assert facts.research_objectives_ready is True
    assert len(facts.paper_skims) == 2
    assert facts.paper_skims[0].source_filename == "paper-1.pdf"
    assert facts.research_objectives[0].excluded_document_ids == ("paper-2",)
    assert len(facts.objective_contexts) == 1
    objective_context = facts.objective_contexts[0]
    assert objective_context.objective_id == facts.research_objectives[0].objective_id
    assert objective_context.target_property_axes == ("corrosion",)
    assert objective_context.process_context_axes == ("LPBF", "heat treatment")
    assert objective_context.routing_hints[0]["table_id"] == "table-1"
    assert objective_context.routing_hints[0]["role"] == "result_table"
    assert len(facts.objective_paper_frames) == 2
    active_frame = next(
        frame
        for frame in facts.objective_paper_frames
        if frame.document_id == "paper-1"
    )
    excluded_frame = next(
        frame
        for frame in facts.objective_paper_frames
        if frame.document_id == "paper-2"
    )
    assert active_frame.objective_id == facts.research_objectives[0].objective_id
    assert active_frame.relevance == "high"
    assert active_frame.paper_role == "primary_experiment"
    assert active_frame.relevant_tables == ("table-1",)
    assert excluded_frame.relevance == "irrelevant"
    assert excluded_frame.paper_role == "review"
    table_route = next(
        route
        for route in facts.objective_evidence_routes
        if route.source_kind == "table" and route.source_ref == "table-1"
    )
    excluded_table_route = next(
        route
        for route in facts.objective_evidence_routes
        if route.source_kind == "table" and route.source_ref == "table-2"
    )
    text_route = next(
        route
        for route in facts.objective_evidence_routes
        if route.source_kind == "text_window" and route.source_ref == "b2"
    )
    assert table_route.role == "current_experimental_evidence"
    assert table_route.extractable is True
    assert table_route.table_schema["column_headers"] == [
        "sample",
        "corrosion current",
    ]
    assert table_route.column_roles == {"corrosion current": "target_property"}
    assert excluded_table_route.role == "low_value_or_irrelevant"
    assert excluded_table_route.extractable is False
    assert text_route.role == "process_or_treatment"
    assert len(extractor.route_payloads) == 1
    assert extractor.route_payloads[0]["paper_frame"]["frame_id"] == active_frame.frame_id
    assert extractor.skim_payloads[0]["table_captions"][0]["table_id"] == "table-1"
    assert extractor.discovery_payloads[0]["paper_skims"][0]["document_id"] == "paper-1"
    assert extractor.frame_payloads[0]["objective_context"]["objective_id"] == (
        facts.research_objectives[0].objective_id
    )
    assert extractor.frame_payloads[0]["table_summaries"][0]["table_id"] == "table-1"

    skim_call_count = len(extractor.skim_payloads)
    assert service.read_research_objectives(collection_id) == objectives
    assert service.read_objective_contexts(collection_id) == facts.objective_contexts
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


def test_research_objective_service_builds_targeted_objective_contexts(
    tmp_path,
):
    collection_service = CollectionService(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Contexts")
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

    service.build_research_objectives(collection_id)
    facts = service.core_fact_repository.read_collection_facts(collection_id)
    contexts = facts.objective_contexts

    assert len(contexts) == 2
    structure_context = next(
        context for context in contexts if "densification" in context.target_property_axes
    )
    mechanical_context = next(
        context for context in contexts if "yield strength" in context.target_property_axes
    )
    assert structure_context.variable_process_axes == (
        "energy density",
        "scanning strategy",
        "scanning speed",
    )
    assert structure_context.process_context_axes == ("Selective Laser Melting",)
    assert [
        hint["table_id"] for hint in structure_context.routing_hints
    ] == ["table-1"]
    assert structure_context.routing_hints[0]["role"] == "result_table"
    assert [
        (hint["table_id"], hint["role"]) for hint in mechanical_context.routing_hints
    ] == [("table-1", "condition_context"), ("table-2", "result_table")]
    assert "microhardness" in mechanical_context.routing_hints[1][
        "matched_property_axes"
    ]
    frames_by_objective_id = {
        frame.objective_id: frame
        for frame in facts.objective_paper_frames
    }
    assert frames_by_objective_id[structure_context.objective_id].relevant_tables == (
        "table-1",
    )
    assert frames_by_objective_id[mechanical_context.objective_id].relevant_tables == (
        "table-1",
        "table-2",
    )
    mechanical_routes = {
        route.source_ref: route
        for route in facts.objective_evidence_routes
        if route.objective_id == mechanical_context.objective_id
        and route.source_kind == "table"
    }
    assert mechanical_routes["table-1"].role == "process_or_treatment"
    assert mechanical_routes["table-2"].role == "current_experimental_evidence"


def test_research_objective_service_canonicalizes_axis_aliases_with_llm(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _CanonicalizingAxisExtractor(),
    )

    assert len(objectives) == 2
    all_process_axes = [
        process_axis
        for objective in objectives
        for process_axis in objective.process_axes
    ]
    assert "scanning strategy" in all_process_axes
    assert "scan strategy" not in all_process_axes


def test_research_objective_service_falls_back_when_axis_plan_drops_axes(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _InvalidAxisCanonicalizationExtractor(),
    )

    all_process_axes = [
        process_axis
        for objective in objectives
        for process_axis in objective.process_axes
    ]
    assert "scanning strategy" in all_process_axes
    assert "scan strategy" in all_process_axes


def test_research_objective_service_rejects_overbroad_axis_canonicalization(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _OverbroadAxisCanonicalizationExtractor(),
    )

    assert len(objectives) == 2
    all_process_axes = [
        process_axis
        for objective in objectives
        for process_axis in objective.process_axes
    ]
    assert "Selective Laser Melting" in all_process_axes
    assert "energy density" in all_process_axes
    assert "scanning speed" in all_process_axes
    assert "scan strategy" in all_process_axes


def test_research_objective_service_falls_back_when_merge_plan_drops_objective(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _DroppedObjectiveMergeExtractor(),
    )

    assert len(objectives) == 3


def test_research_objective_service_falls_back_when_merge_plan_invents_axis(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _InventedAxisMergeExtractor(),
    )

    assert len(objectives) == 3
    assert all("laser power" not in objective.process_axes for objective in objectives)


def test_research_objective_service_splits_merge_plan_with_disjoint_properties(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _DisjointPropertyMergeExtractor(),
    )

    assert len(objectives) == 2
    assert any("densification" in objective.property_axes for objective in objectives)
    assert any("yield strength" in objective.property_axes for objective in objectives)


def test_research_objective_service_aligns_question_with_restored_process_axes(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _UnderSpecifiedMergeQuestionExtractor(),
    )

    mechanical_objective = next(
        objective
        for objective in objectives
        if "yield strength" in objective.property_axes
    )
    assert mechanical_objective.question.startswith("How do")
    assert "energy density" in mechanical_objective.question
    assert "scanning strategy" in mechanical_objective.question
    assert "scanning speed" in mechanical_objective.question
    assert "Selective Laser Melting" in mechanical_objective.question
    assert "energy density" in str(mechanical_objective.comparison_intent)
    assert "scanning strategy" in str(mechanical_objective.comparison_intent)
    assert "scanning speed" in str(mechanical_objective.comparison_intent)


def test_research_objective_service_splits_single_mixed_property_objective(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _SingleMixedObjectiveExtractor(),
    )

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
    assert mechanical_objective.property_axes == (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    )
    assert "energy density" in mechanical_objective.question
    assert "scanning strategy" in mechanical_objective.question
    assert "scanning speed" in mechanical_objective.question


def test_research_objective_service_dedupes_repeated_objective_ids_before_persist(
    tmp_path,
):
    collection_service = CollectionService(tmp_path / "collections")
    collection = collection_service.create_collection("Duplicate Objectives")
    collection_id = collection["collection_id"]
    service = ResearchObjectiveService(
        collection_service=collection_service,
        structured_extractor=_DuplicateObjectiveIdExtractor(),
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

    objectives = service.build_research_objectives(collection_id)

    assert len(objectives) == 1
    facts = service.core_fact_repository.read_collection_facts(collection_id)
    assert len(facts.research_objectives) == 1


def _build_duplicate_paper_objectives(
    tmp_path,
    extractor: _ObjectiveExtractor,
):
    collection_service = CollectionService(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Merge")
    collection_id = collection["collection_id"]
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
    return service.build_research_objectives(collection_id)
