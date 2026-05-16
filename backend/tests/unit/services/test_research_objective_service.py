from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from application.core.semantic_build.llm.schemas import (
    StructuredAxisCanonicalizationGroup,
    StructuredAxisCanonicalizationPlan,
    StructuredDocumentProfile,
    StructuredObjectiveEvidenceRoute,
    StructuredObjectiveEvidenceRoutes,
    StructuredObjectiveEvidenceUnit,
    StructuredObjectiveEvidenceUnits,
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
from domain.core import (
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectivePaperFrame,
    ResearchObjective,
)
from domain.source import SourceArtifactSet


class _ObjectiveExtractor:
    def __init__(self) -> None:
        self.skim_payloads: list[dict[str, Any]] = []
        self.discovery_payloads: list[dict[str, Any]] = []
        self.canonicalization_payloads: list[dict[str, Any]] = []
        self.merge_payloads: list[dict[str, Any]] = []
        self.frame_payloads: list[dict[str, Any]] = []
        self.route_payloads: list[dict[str, Any]] = []
        self.unit_payloads: list[dict[str, Any]] = []

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

    def extract_objective_evidence_units(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveEvidenceUnits:
        self.unit_payloads.append(payload)
        route = payload["evidence_route"]
        source = payload["source"]
        if route["source_kind"] == "table":
            return StructuredObjectiveEvidenceUnits(
                evidence_units=[
                    StructuredObjectiveEvidenceUnit(
                        unit_kind="measurement",
                        property_normalized="corrosion current",
                        material_system={"family": "316L stainless steel"},
                        sample_context={"label": "as-built"},
                        process_context={"process": "LPBF"},
                        test_condition={"method": "corrosion test"},
                        value_payload={
                            "value": 1.2,
                            "source_value_text": "1.2 uA/cm2",
                        },
                        unit="uA/cm2",
                        join_keys={"sample_key": "as-built"},
                        resolution_status="resolved",
                        confidence=0.86,
                    ),
                    StructuredObjectiveEvidenceUnit(
                        unit_kind="measurement",
                        property_normalized="corrosion current",
                        material_system={"family": "316L stainless steel"},
                        sample_context={"label": "heat-treated"},
                        process_context={
                            "process": "LPBF",
                            "post_treatment_summary": "heat treatment",
                        },
                        test_condition={"method": "corrosion test"},
                        value_payload={
                            "value": 0.4,
                            "source_value_text": "0.4 uA/cm2",
                        },
                        unit="uA/cm2",
                        join_keys={"sample_key": "heat-treated"},
                        resolution_status="resolved",
                        confidence=0.86,
                    ),
                ]
            )
        if source.get("text"):
            return StructuredObjectiveEvidenceUnits(
                evidence_units=[
                    StructuredObjectiveEvidenceUnit(
                        unit_kind="process_context",
                        property_normalized=None,
                        material_system={"family": "316L stainless steel"},
                        sample_context={"comparison": "before and after heat treatment"},
                        process_context={
                            "process": "LPBF",
                            "post_treatment_summary": "heat treatment",
                        },
                        value_payload={
                            "statement": "LPBF 316L was compared before and after heat treatment."
                        },
                        resolution_status="partial",
                        confidence=0.74,
                    )
                ]
            )
        return StructuredObjectiveEvidenceUnits()


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


def test_research_objective_service_forces_extractable_objective_route_roles(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )

    assert service._normalize_route_extractable(
        {"role": "current_experimental_evidence", "extractable": False}
    )
    assert service._normalize_route_extractable(
        {"role": "process_or_treatment", "extractable": False}
    )
    assert not service._normalize_route_extractable(
        {"role": "low_value_or_irrelevant", "extractable": True}
    )
    assert not service._normalize_route_extractable(
        {"role": "literature_comparison", "extractable": False}
    )


def test_research_objective_service_skips_failed_objective_unit_route(
    tmp_path,
    caplog,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["laser power"],
            "property_axes": ["relative density"],
            "confidence": 0.9,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-density",
            "question": objective.question,
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["laser power"],
            "process_context_axes": ["SLM"],
            "target_property_axes": ["relative density"],
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "relevant_tables": ["table-1"],
        }
    )
    table_route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Sample": "sample_id",
                "Relative density (%)": "target_property",
            },
            "confidence": 0.85,
        }
    )
    failing_text_route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "role": "process_or_treatment",
            "extractable": True,
            "confidence": 0.75,
        }
    )

    class FailingUnitExtractor:
        def __init__(self) -> None:
            self.unit_payloads: list[dict[str, Any]] = []

        def extract_objective_evidence_units(
            self,
            payload: dict[str, Any],
        ) -> StructuredObjectiveEvidenceUnits:
            self.unit_payloads.append(payload)
            raise RuntimeError("malformed objective evidence JSON")

    extractor = FailingUnitExtractor()
    table = SimpleNamespace(
        table_id="table-1",
        document_id="paper-1",
        page=1,
        caption_text="Relative density results",
        heading_path="Results",
        column_headers=["Sample", "Relative density (%)"],
        table_matrix=[
            ["Sample", "Relative density (%)"],
            ["S1", "99.5"],
        ],
    )
    block = SimpleNamespace(
        block_id="block-1",
        document_id="paper-1",
        page=1,
        block_type="paragraph",
        heading_path="Results",
        text="The model response for this text window is malformed.",
    )

    with caplog.at_level("ERROR"):
        units = service._build_objective_evidence_units(
            collection_id="col-test",
            extractor=extractor,
            objectives=(objective,),
            objective_contexts=(objective_context,),
            objective_paper_frames=(frame,),
            objective_evidence_routes=(table_route, failing_text_route),
            blocks_by_document_id={"paper-1": [block]},
            tables_by_document_id={"paper-1": [table]},
        )

    measurements = [unit for unit in units if unit.unit_kind == "measurement"]
    assert len(measurements) == 1
    assert measurements[0].property_normalized == "relative density"
    assert measurements[0].value_payload["value"] == 99.5
    assert [payload["evidence_route"]["source_ref"] for payload in extractor.unit_payloads] == [
        "block-1"
    ]
    assert any(
        "Research objective evidence-unit extraction route failed" in record.message
        and failing_text_route.route_id in record.message
        for record in caplog.records
    )


def test_research_objective_table_source_payload_includes_table_cells(tmp_path):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )
    table = SimpleNamespace(
        table_id="table-1",
        document_id="paper-1",
        page=1,
        caption_text="Density results",
        heading_path="Results",
        column_headers=["Specimens", "Density (%)"],
        table_matrix=[
            ["Specimens", "Density (%)"],
            ["as-SLM (140/", "92.19"],
        ],
    )
    cells = [
        SimpleNamespace(
            table_id="other-table",
            row_index=1,
            col_index=0,
            header_path="Specimens",
            cell_text="other",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=1,
            col_index=1,
            header_path="Density (%)",
            cell_text="92.19",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=1,
            col_index=0,
            header_path="Specimens",
            cell_text="as-SLM (140/",
        ),
    ]

    payload = service._build_objective_route_source_payload(
        route=route,
        blocks=[],
        tables=[table],
        table_cells=cells,
    )

    assert payload["table_cells"] == [
        {
            "row_index": 1,
            "col_index": 0,
            "header_path": "Specimens",
            "cell_text": "as-SLM (140/",
        },
        {
            "row_index": 1,
            "col_index": 1,
            "header_path": "Density (%)",
            "cell_text": "92.19",
        },
    ]


def test_research_objective_fragmented_table_cells_use_llm_repair_path(tmp_path):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-density",
            "question": "How do process settings affect relative density?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["process settings"],
            "property_axes": ["relative density"],
            "source_objective_ids": ["paper-1:obj"],
            "confidence": 0.88,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-density",
            "target_property_axes": ["relative density"],
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "relevant_tables": ["table-1"],
        }
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Specimens": "sample_id",
                "Density (%)": "target_property",
            },
            "confidence": 0.84,
        }
    )
    table = SimpleNamespace(
        table_id="table-1",
        document_id="paper-1",
        page=1,
        caption_text="Density results",
        heading_path="Results",
        column_headers=["Specimens", "Density (%)"],
        table_matrix=[
            ["Specimens", "Density (%)"],
            ["as-SLM (140/", "92.19"],
            ["S2", "99.5"],
        ],
    )
    table_cells = [
        SimpleNamespace(
            table_id="table-1",
            row_index=1,
            col_index=0,
            header_path="Specimens",
            cell_text="as-SLM (140/",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=1,
            col_index=1,
            header_path="Density (%)",
            cell_text="92.19",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=2,
            col_index=0,
            header_path="Specimens",
            cell_text="S2",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=2,
            col_index=1,
            header_path="Density (%)",
            cell_text="99.5",
        ),
    ]

    class RepairExtractor:
        def __init__(self) -> None:
            self.unit_payloads: list[dict[str, Any]] = []

        def extract_objective_evidence_units(
            self,
            payload: dict[str, Any],
        ) -> StructuredObjectiveEvidenceUnits:
            self.unit_payloads.append(payload)
            return StructuredObjectiveEvidenceUnits(
                evidence_units=[
                    StructuredObjectiveEvidenceUnit(
                        unit_kind="measurement",
                        property_normalized="relative density",
                        material_system={},
                        sample_context={"label": "repaired row label"},
                        process_context={},
                        test_condition={},
                        value_payload={
                            "value": 92.19,
                            "source_value_text": "92.19",
                        },
                        unit="%",
                        join_keys={"sample_key": "repaired row label"},
                        resolution_status="resolved",
                        confidence=0.86,
                    )
                ]
            )

    extractor = RepairExtractor()

    units = service._build_objective_evidence_units(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(objective_context,),
        objective_paper_frames=(frame,),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": [table]},
        table_cells_by_document_id={"paper-1": table_cells},
    )

    assert len(extractor.unit_payloads) == 1
    assert extractor.unit_payloads[0]["source"]["table_cells"][0] == {
        "row_index": 1,
        "col_index": 0,
        "header_path": "Specimens",
        "cell_text": "as-SLM (140/",
    }
    measurements = [unit for unit in units if unit.unit_kind == "measurement"]
    assert len(measurements) == 2
    assert {unit.value_payload.get("value") for unit in measurements} == {92.19, 99.5}
    assert any(
        unit.sample_context == {"label": "repaired row label"}
        for unit in measurements
    )
    assert any(
        unit.sample_context.get("Specimens") == "S2"
        for unit in measurements
    )
    assert all(
        unit.sample_context.get("Specimens") != "as-SLM (140/"
        for unit in measurements
    )


def test_research_objective_service_normalizes_result_table_values_to_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-2",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Sample number": "sample_id",
                "Condition number": "test_condition",
                "Yield Strength (MPa)": "result_property",
                "Standard deviation (HV)": "result_property",
            },
            "join_keys": {"condition_key": "Condition number"},
            "confidence": 0.84,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "target_property_axes": ["yield strength"],
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 4},
        objective_context=objective_context,
        extracted_record={
            "unit_kind": "sample_context",
            "sample_context": {"Sample number": "1"},
            "process_context": {"Condition number": "1"},
            "value_payload": {
                "Sample number": "1",
                "Yield Strength (MPa)": "236.65",
                "Standard deviation (HV)": "10.4",
            },
            "resolution_status": "partial",
        },
    )

    assert len(records) == 1
    record = records[0]
    assert record["unit_kind"] == "measurement"
    assert record["property_normalized"] == "yield strength"
    assert record["unit"] == "MPa"
    assert record["value_payload"] == {
        "source_value_text": "236.65",
        "value": 236.65,
    }
    assert record["sample_context"] == {"Sample number": "1"}
    assert record["process_context"] == {"Condition number": "1"}
    assert record["join_keys"] == {"condition_key": "Condition number"}
    assert record["resolution_status"] == "resolved"
    assert record["confidence"] == 0.84
    assert record["source_refs"] == (
        {
            "route_id": route.route_id,
            "source_kind": "table",
            "source_ref": "table-2",
            "role": "current_experimental_evidence",
            "page": 4,
        },
    )


def test_research_objective_service_uses_main_number_after_leading_uncertainty(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-3",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Specimens": "sample_id",
                "Hardness (HV)": "target_property",
                "Yield Strength (MPa)": "target_property",
            },
            "confidence": 0.84,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "target_property_axes": ["hardness", "yield strength"],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        source={
            "page": 5,
            "column_headers": [
                "Specimens",
                "Hardness (HV)",
                "Yield Strength (MPa)",
            ],
            "table_matrix": [
                ["Specimens", "Hardness (HV)", "Yield Strength (MPa)"],
                [
                    "as-SLM(120/100)",
                    "( ± 4.5) 176.0",
                    "( 10.2) 464.8 ( ± 5.8)",
                ],
            ],
        },
        objective_context=objective_context,
    )

    values_by_property = {
        record["property_normalized"]: record["value_payload"]["value"]
        for record in records
    }
    assert values_by_property == {
        "hardness": 176.0,
        "yield strength": 464.8,
    }


def test_research_objective_service_keeps_non_ascii_process_headers_out_of_results(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-texture",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-3",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "α ( ◦ )": "process_variable",
                "β ( ◦ )": "process_variable",
                "θ ( ◦ )": "process_variable",
                "Yield Strength Experiment (MPa)": "result_property",
            },
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-texture",
            "variable_process_axes": [
                "scan strategy rotation angle",
                "build orientation",
            ],
            "target_property_axes": [
                "crystallographic texture",
                "yield strength",
            ],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        source={
            "page": 8,
            "column_headers": [
                "α ( ◦ )",
                "β ( ◦ )",
                "θ ( ◦ )",
                "Yield Strength Experiment (MPa)",
            ],
            "table_matrix": [
                [
                    "α ( ◦ )",
                    "β ( ◦ )",
                    "θ ( ◦ )",
                    "Yield Strength Experiment (MPa)",
                ],
                ["0", "22.5", "45", "356.9"],
            ],
        },
        objective_context=objective_context,
    )

    assert len(records) == 1
    assert records[0]["property_normalized"] == "yield strength experiment"
    assert records[0]["value_payload"]["value"] == 356.9
    assert records[0]["sample_context"] == {"sample_number": "1"}
    assert records[0]["process_context"] == {
        "α ( ◦ )": "0",
        "β ( ◦ )": "22.5",
        "θ ( ◦ )": "45",
    }


def test_research_objective_service_uses_role_aliases_for_result_process_context(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-texture",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-3",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "α ( ◦ )": "rotation_angle_x",
                "β ( ◦ )": "rotation_angle_y",
                "θ ( ◦ )": "rotation_angle_z",
                "Yield Strength Experiment (MPa)": "experimental_yield_strength",
            },
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-texture",
            "variable_process_axes": [
                "scan strategy rotation angle",
                "build orientation",
            ],
            "target_property_axes": ["yield strength"],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        source={
            "page": 8,
            "column_headers": [
                "α ( ◦ )",
                "β ( ◦ )",
                "θ ( ◦ )",
                "Yield Strength Experiment (MPa)",
            ],
            "table_matrix": [
                [
                    "α ( ◦ )",
                    "β ( ◦ )",
                    "θ ( ◦ )",
                    "Yield Strength Experiment (MPa)",
                ],
                ["0", "22.5", "45", "356.9"],
            ],
        },
        objective_context=objective_context,
    )

    assert len(records) == 1
    assert records[0]["property_normalized"] == "experimental yield strength"
    assert records[0]["sample_context"] == {"sample_number": "1"}
    assert records[0]["process_context"] == {
        "rotation angle x": "0",
        "rotation angle y": "22.5",
        "rotation angle z": "45",
    }


def test_research_objective_service_uses_specific_role_label_for_abbreviated_result_header(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-4",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Printed": "sample",
                "TE [%]": "total elongation",
            },
            "confidence": 0.82,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "target_property_axes": ["elongation"],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        objective_context=objective_context,
        source={
            "page": 7,
            "column_headers": ["Printed", "TE [%]"],
            "table_matrix": [
                ["Printed", "TE [%]"],
                ["H-VED", "48.3 ± 3.2"],
            ],
        },
    )

    assert len(records) == 1
    assert records[0]["property_normalized"] == "elongation"
    assert records[0]["value_payload"]["value"] == 48.3


def test_research_objective_service_uses_matching_result_headers_when_role_is_broad(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Condition number": "test_condition",
                "Sample number": "test_condition",
                "Relative density": "current_experimental_evidence",
            },
            "confidence": 0.84,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-density",
            "target_property_axes": ["densification"],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        source={
            "page": 2,
            "column_headers": [
                "Condition number",
                "Sample number",
                "Relative density",
            ],
            "table_matrix": [
                ["Condition number", "Sample number", "Relative density"],
                ["1", "1", "95.4"],
                ["1", "2", "97.7"],
            ],
        },
        objective_context=objective_context,
    )

    assert [record["property_normalized"] for record in records] == [
        "relative density",
        "relative density",
    ]
    assert [record["value_payload"]["value"] for record in records] == [95.4, 97.7]
    assert records[0]["sample_context"]["Sample number"] == "1"
    assert records[1]["sample_context"]["Sample number"] == "2"


def test_research_objective_service_keeps_routed_model_metric_columns(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-texture",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-2",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Case": "test_condition",
                "ODF Correlation Coefficient (Experiment vs. Prediction)": (
                    "current_experimental_evidence"
                ),
                "Jeffrey ' s distance": "current_experimental_evidence",
            },
            "confidence": 0.82,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-texture",
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "microhardness",
            ],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        source={
            "page": 7,
            "column_headers": [
                "Case",
                "ODF Correlation Coefficient (Experiment vs. Prediction)",
                "Jeffrey ' s distance",
            ],
            "table_matrix": [
                [
                    "Case",
                    "ODF Correlation Coefficient (Experiment vs. Prediction)",
                    "Jeffrey ' s distance",
                ],
                ["11", "0.1842", "1.7093"],
                ["12", "0.1195", "2.2264"],
            ],
        },
        objective_context=objective_context,
    )

    values_by_case_and_property = {
        (
            record["sample_context"]["Case"],
            record["property_normalized"],
        ): record["value_payload"]["value"]
        for record in records
    }
    assert values_by_case_and_property[
        ("12", "odf correlation coefficient")
    ] == 0.1195
    assert values_by_case_and_property[("12", "jeffrey ' s distance")] == 2.2264
    assert "yield strength" not in {
        record["property_normalized"]
        for record in records
    }


def test_research_objective_service_treats_relative_density_as_structural_target(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Condition number": "sample_id",
                "Sample number": "sample_id",
                "Hatch space (mm)": "process_variable",
                "Scan strategy": "process_variable",
                "Scanning speed (mm/s)": "process_variable",
                "Energy density (J/mm 3 )": "process_variable",
                "Relative density": "target_property",
            },
            "confidence": 0.84,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-density",
            "variable_process_axes": [
                "energy density",
                "scanning strategy",
                "scanning speed",
            ],
            "target_property_axes": ["densification", "microstructure"],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        source={
            "page": 2,
            "column_headers": [
                "Condition number",
                "Sample number",
                "Hatch space (mm)",
                "Scan strategy",
                "Scanning speed (mm/s)",
                "Energy density (J/mm 3 )",
                "Relative density",
            ],
            "table_matrix": [
                [
                    "Condition number",
                    "Sample number",
                    "Hatch space (mm)",
                    "Scan strategy",
                    "Scanning speed (mm/s)",
                    "Energy density (J/mm 3 )",
                    "Relative density",
                ],
                ["1", "1", "0.114", "A", "0.25", "70", "95.4"],
                ["1", "2", "0.114", "B", "0.25", "70", "97.7"],
                ["6", "16", "0.12", "C", "0.111", "150", "98.6"],
            ],
        },
        objective_context=objective_context,
    )

    assert [record["property_normalized"] for record in records] == [
        "relative density",
        "relative density",
        "relative density",
    ]
    assert [record["sample_context"]["Sample number"] for record in records] == [
        "1",
        "2",
        "16",
    ]
    assert records[2]["process_context"] == {
        "Energy density (J/mm 3 )": "150",
        "Hatch space (mm)": "0.12",
        "Scan strategy": "C",
        "Scanning speed (mm/s)": "0.111",
    }
    assert records[2]["value_payload"]["value"] == 98.6


def test_research_objective_service_skips_matrix_test_condition_table_fallback(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "test_condition",
            "extractable": True,
            "column_roles": {
                "Condition number": "condition",
                "Sample number": "sample",
                "Scan strategy": "process_variable",
                "Relative density": "result",
            },
        }
    )

    assert service._objective_table_route_should_skip_llm_fallback(route)


def test_research_objective_service_skips_untyped_table_test_condition_fallback(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "test_condition",
            "extractable": True,
        }
    )

    assert service._objective_table_route_should_skip_llm_fallback(route)


def test_research_objective_service_skips_off_target_result_table_fallback(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-corrosion",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Sample": "sample_index",
                "E corr (mV)": "electrochemical_parameter",
                "E d (mV)": "electrochemical_parameter",
                "E p (mV)": "electrochemical_parameter",
                "E p - E d (mV)": "electrochemical_parameter",
            },
        }
    )
    mechanical_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
        }
    )
    corrosion_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-corrosion",
            "target_property_axes": [
                "corrosion potential",
                "pitting potential",
            ],
        }
    )
    corrosion_route = ObjectiveEvidenceRoute.from_mapping(
        {
            **route.to_record(),
            "objective_id": "obj-corrosion",
            "column_roles": {
                "Sample": "sample_condition",
                "E corr (mV)": "corrosion_potential",
                "E d (mV)": "passivation_potential",
                "E p (mV)": "pitting_potential",
                "E p - E d (mV)": "passivation_interval",
            },
        }
    )

    assert service._objective_table_route_should_skip_llm_fallback(
        route,
        objective_context=mechanical_context,
    )
    assert not service._objective_table_route_should_skip_llm_fallback(
        corrosion_route,
        objective_context=corrosion_context,
    )

    eis_route = ObjectiveEvidenceRoute.from_mapping(
        {
            **route.to_record(),
            "source_ref": "table-eis",
            "column_roles": {
                "Sample": "sample_index",
                "R s (ohm cm2)": "current_experimental_evidence",
                "Q film > n film": "current_experimental_evidence",
                "R film (ohm cm2)": "current_experimental_evidence",
            },
        }
    )

    assert service._objective_table_route_should_skip_llm_fallback(
        eis_route,
        objective_context=mechanical_context,
    )


def test_research_objective_service_builds_method_conditions_and_binds_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "target_property_axes": ["yield strength", "microhardness"],
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
        }
    )
    blocks = [
        SimpleNamespace(
            block_id="tensile-method",
            page=5,
            heading_path="2.2. Mechanical Testing",
            text=(
                "Tests were carried out at quasi-static rates (0.02 mm/min) "
                "in an INSTRON mechanical testing machine. Specimens were "
                "prepared as per ASTM E8M standard."
            ),
        ),
        SimpleNamespace(
            block_id="hardness-method",
            page=5,
            heading_path="2.3. Microhardness",
            text=(
                "The microhardness was measured using a standard Vickers "
                "microhardness tester (Wilson) under a load of 10 N for 15 s. "
                "The average of 20 readings were taken into account."
            ),
        ),
    ]

    method_units = service._build_objective_method_family_test_condition_units(
        objective_contexts=(objective_context,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": blocks},
    )

    assert [unit.property_normalized for unit in method_units] == [
        "tensile_mechanics",
        "microhardness",
    ]
    tensile_condition = method_units[0].test_condition
    hardness_condition = method_units[1].test_condition
    assert tensile_condition["method"] == "tensile testing"
    assert tensile_condition["standard"] == "ASTM E8M"
    assert hardness_condition["method"] == "Vickers microhardness"
    assert hardness_condition["load"] == "10 N"

    measurements = (
        ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": "yield-measurement",
                "objective_id": "obj-mechanical",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "yield strength",
                "value_payload": {"source_value_text": "236.65", "value": 236.65},
                "resolution_status": "resolved",
            }
        ),
        ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": "hardness-measurement",
                "objective_id": "obj-mechanical",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "microhardness",
                "value_payload": {"source_value_text": "224.7", "value": 224.7},
                "resolution_status": "resolved",
            }
        ),
    )

    resolved = service._attach_objective_method_test_conditions_to_measurements(
        (*method_units, *measurements)
    )
    resolved_measurements = [
        unit for unit in resolved if unit.unit_kind == "measurement"
    ]

    assert resolved_measurements[0].test_condition["method"] == "tensile testing"
    assert (
        resolved_measurements[0].resolved_condition["test_condition_unit_id"]
        == method_units[0].evidence_unit_id
    )
    assert resolved_measurements[1].test_condition["method"] == "Vickers microhardness"
    assert (
        resolved_measurements[1].resolved_condition["test_condition_unit_id"]
        == method_units[1].evidence_unit_id
    )


def test_research_objective_service_derives_table_characterization_units(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-density",
            "target_property_axes": ["densification", "microstructure"],
        }
    )

    def density_unit(
        evidence_unit_id: str,
        *,
        sample_number: str,
        strategy: str,
        value: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "relative density",
                "sample_context": {"Sample number": sample_number},
                "process_context": {"Scan strategy": strategy},
                "value_payload": {"source_value_text": str(value), "value": value},
                "unit": "%",
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-1",
                        "page": 2,
                    }
                ],
                "resolution_status": "resolved",
            }
        )

    units = service._build_objective_table_characterization_units(
        units=(
            density_unit("density-s1", sample_number="1", strategy="A", value=95.4),
            density_unit("density-s2", sample_number="2", strategy="B", value=97.7),
            density_unit("density-s3", sample_number="3", strategy="C", value=93.8),
        ),
        objective_contexts=(objective_context,),
    )

    characterization_types = {
        unit.value_payload["characterization_type"]
        for unit in units
    }
    assert characterization_types == {
        "density_porosity_sem_imagej",
        "highest_density_sample",
        "scan_strategy_a",
        "scan_strategy_b",
        "scan_strategy_c",
    }
    highest = next(
        unit
        for unit in units
        if unit.value_payload["characterization_type"] == "highest_density_sample"
    )
    assert highest.sample_context == {"Sample number": "2"}
    assert highest.value_payload["relative_density"] == 97.7


def test_research_objective_service_does_not_keep_text_trends_as_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 5},
        objective_context=None,
        extracted_record={
            "unit_kind": "measurement",
            "property_normalized": "microstructure",
            "value_payload": {"result": "refined microstructure"},
            "resolution_status": "partial",
        },
    )

    assert len(records) == 1
    record = records[0]
    assert record["unit_kind"] == "characterization"
    assert record["interpretation"] == "refined microstructure"
    assert record["source_refs"] == (
        {
            "route_id": route.route_id,
            "source_kind": "text_window",
            "source_ref": "block-1",
            "role": "characterization",
            "page": 5,
        },
    )


def test_research_objective_service_keeps_non_numeric_text_characterization(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-characterization",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 3},
        objective_context=None,
        extracted_record={
            "unit_kind": "characterization",
            "property_normalized": "microstructure",
            "value_payload": {"observation": "irregular pores were observed"},
            "resolution_status": "partial",
        },
    )

    assert len(records) == 1
    assert records[0]["unit_kind"] == "characterization"
    assert records[0]["property_normalized"] == "microstructure"


def test_research_objective_service_keeps_numeric_density_text_as_measurement(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-density",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 3},
        objective_context=None,
        extracted_record={
            "unit_kind": "characterization",
            "sample_context": {"sample_id": "375 W-2100 mm·s -1"},
            "process_context": {
                "laser_power": "375 W",
                "scanning_speed": "2100 mm·s -1",
            },
            "value_payload": {"density_value": "97.83"},
            "unit": "%",
            "resolution_status": "resolved",
        },
    )

    assert len(records) == 1
    record = records[0]
    assert record["unit_kind"] == "measurement"
    assert record["property_normalized"] == "relative density"
    assert record["value_payload"] == {
        "source_value_text": "97.83",
        "value": 97.83,
    }
    assert record["unit"] == "%"


def test_research_objective_service_expands_respective_density_text_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-density",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 3},
        objective_context=None,
        extracted_record={
            "unit_kind": "characterization",
            "sample_context": {
                "sample_ids": [
                    "375 W-2100 mm·s -1",
                    "255 W-1400 mm·s -1",
                    "135 W-750 mm·s -1",
                ],
            },
            "value_payload": {
                "source_value_text": (
                    "The density of the three samples of 375 W-2100 mm·s -1, "
                    "255 W-1400 mm·s -1, and 135 W-750 mm·s -1 was measured, "
                    "which was 97.83, 99.5, and 99.26%, respectively."
                ),
            },
            "resolution_status": "resolved",
        },
    )

    assert [
        (
            record["unit_kind"],
            record["property_normalized"],
            record["sample_context"],
            record["value_payload"],
            record["unit"],
        )
        for record in records
    ] == [
        (
            "measurement",
            "relative density",
            {"sample_id": "375 W-2100 mm·s -1"},
            {"source_value_text": "97.83", "value": 97.83},
            "%",
        ),
        (
            "measurement",
            "relative density",
            {"sample_id": "255 W-1400 mm·s -1"},
            {"source_value_text": "99.5", "value": 99.5},
            "%",
        ),
        (
            "measurement",
            "relative density",
            {"sample_id": "135 W-750 mm·s -1"},
            {"source_value_text": "99.26", "value": 99.26},
            "%",
        ),
    ]


def test_research_objective_service_expands_mapped_density_text_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-density",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 3},
        objective_context=None,
        extracted_record={
            "unit_kind": "characterization",
            "property_normalized": "relative density",
            "sample_context": {
                "samples": [
                    {
                        "laser_power": "375 W",
                        "scanning_speed": "2100 mm/s",
                    },
                    {
                        "laser_power": "255 W",
                        "scanning_speed": "1400 mm/s",
                    },
                    {
                        "laser_power": "135 W",
                        "scanning_speed": "750 mm/s",
                    },
                ],
            },
            "process_context": {"process": "Selective Laser Melting"},
            "value_payload": {
                "source_value_text": {
                    "375 W-2100 mm/s": "97.83%",
                    "255 W-1400 mm/s": "99.5%",
                    "135 W-750 mm/s": "99.26%",
                },
            },
            "unit": "%",
            "resolution_status": "resolved",
        },
    )

    assert [
        (
            record["unit_kind"],
            record["property_normalized"],
            record["sample_context"],
            record["process_context"],
            record["value_payload"],
            record["unit"],
        )
        for record in records
    ] == [
        (
            "measurement",
            "relative density",
            {"sample_id": "375 W-2100 mm/s"},
            {"process": "Selective Laser Melting"},
            {"source_value_text": "97.83%", "value": 97.83},
            "%",
        ),
        (
            "measurement",
            "relative density",
            {"sample_id": "255 W-1400 mm/s"},
            {"process": "Selective Laser Melting"},
            {"source_value_text": "99.5%", "value": 99.5},
            "%",
        ),
        (
            "measurement",
            "relative density",
            {"sample_id": "135 W-750 mm/s"},
            {"process": "Selective Laser Melting"},
            {"source_value_text": "99.26%", "value": 99.26},
            "%",
        ),
    ]


def test_research_objective_service_expands_mapped_numeric_text_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-preheat",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "thermal-simulation",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 5},
        objective_context=None,
        extracted_record={
            "unit_kind": "characterization",
            "property_normalized": "cooling rate",
            "process_context": {"process": "laser beam powder bed fusion"},
            "value_payload": {
                "P150": "1.43x10^6 C/s",
                "NP": "1.65x10^6 C/s",
            },
            "resolution_status": "resolved",
        },
    )

    assert [
        (
            record["unit_kind"],
            record["property_normalized"],
            record["sample_context"],
            record["process_context"],
            record["value_payload"],
            record["unit"],
        )
        for record in records
    ] == [
        (
            "measurement",
            "cooling rate",
            {"sample_id": "P150"},
            {"process": "laser beam powder bed fusion"},
            {"source_value_text": "1.43x10^6 C/s", "value": 1.43e6},
            "C/s",
        ),
        (
            "measurement",
            "cooling rate",
            {"sample_id": "NP"},
            {"process": "laser beam powder bed fusion"},
            {"source_value_text": "1.65x10^6 C/s", "value": 1.65e6},
            "C/s",
        ),
    ]


def test_research_objective_service_expands_mapped_residual_stress_text_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-heat-treatment",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "residual-stress",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 4},
        objective_context=None,
        extracted_record={
            "unit_kind": "characterization",
            "property_normalized": "residual stress",
            "process_context": {"laser_power": "120 W", "scan_speed": "100 mm/s"},
            "value_payload": {
                "HT-SLM": "17.8 MPa",
                "HIP-SLM": "27.5 MPa",
                "as-SLM": "99.5 MPa",
            },
            "resolution_status": "resolved",
        },
    )

    assert [
        (
            record["unit_kind"],
            record["property_normalized"],
            record["sample_context"],
            record["value_payload"],
            record["unit"],
        )
        for record in records
    ] == [
        (
            "measurement",
            "residual stress",
            {"sample_id": "HT-SLM"},
            {"source_value_text": "17.8 MPa", "value": 17.8},
            "MPa",
        ),
        (
            "measurement",
            "residual stress",
            {"sample_id": "HIP-SLM"},
            {"source_value_text": "27.5 MPa", "value": 27.5},
            "MPa",
        ),
        (
            "measurement",
            "residual stress",
            {"sample_id": "as-SLM"},
            {"source_value_text": "99.5 MPa", "value": 99.5},
            "MPa",
        ),
    ]


def test_research_objective_service_expands_source_text_density_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-density",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={
            "page": 3,
            "text": (
                "The density of the three samples of 375 W-2100 mm·s -1, "
                "255 W-1400 mm·s -1, and 135 W-750 mm·s -1 was measured, "
                "which was 97.83, 99.5, and 99.26%, respectively."
            ),
        },
        objective_context=None,
        extracted_record={
            "unit_kind": "characterization",
            "property_normalized": "relative density",
            "sample_context": {
                "density": "97.83%",
                "sample_id": "375 W-2100 mm·s -1",
            },
            "process_context": {
                "laser_power": "375 W",
                "scanning_speed": "2100 mm·s -1",
            },
            "value_payload": {"density_value": "97.83"},
            "unit": "%",
            "resolution_status": "resolved",
        },
    )

    assert [
        (
            record["unit_kind"],
            record["property_normalized"],
            record["sample_context"],
            record["process_context"],
            record["value_payload"],
            record["unit"],
        )
        for record in records
    ] == [
        (
            "measurement",
            "relative density",
            {"sample_id": "375 W-2100 mm·s -1"},
            {},
            {"source_value_text": "97.83", "value": 97.83},
            "%",
        ),
        (
            "measurement",
            "relative density",
            {"sample_id": "255 W-1400 mm·s -1"},
            {},
            {"source_value_text": "99.5", "value": 99.5},
            "%",
        ),
        (
            "measurement",
            "relative density",
            {"sample_id": "135 W-750 mm·s -1"},
            {},
            {"source_value_text": "99.26", "value": 99.26},
            "%",
        ),
    ]


def test_research_objective_service_dedupes_shared_density_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    corrosion_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-corrosion",
            "target_property_axes": ["corrosion potential", "pitting potential"],
        }
    )
    mechanical_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
        }
    )
    corrosion_density = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "density-corrosion",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "relative density",
            "sample_context": {"sample_number": "1", "sample_id": "sample-a"},
            "value_payload": {"source_value_text": "97.83", "value": 97.83},
            "unit": "%",
        }
    )
    mechanical_density = ObjectiveEvidenceUnit.from_mapping(
        {
            **corrosion_density.to_record(),
            "evidence_unit_id": "density-mechanical",
            "objective_id": "obj-mechanical",
        }
    )

    deduped = service._dedupe_shared_density_measurements(
        (corrosion_density, mechanical_density),
        context_by_objective_id={
            corrosion_context.objective_id: corrosion_context,
            mechanical_context.objective_id: mechanical_context,
        },
    )

    assert [unit.evidence_unit_id for unit in deduped] == ["density-mechanical"]


def test_research_objective_service_reclassifies_mechanical_text_trends(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 6},
        objective_context=None,
        extracted_record={
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "value_payload": {"result": "higher for strategy A"},
            "resolution_status": "partial",
        },
    )

    assert len(records) == 1
    assert records[0]["unit_kind"] == "interpretation"
    assert records[0]["interpretation"] == "higher for strategy A"


def test_research_objective_service_reclassifies_off_target_text_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-microstructure",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "conclusion",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )
    microstructure_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-microstructure",
            "target_property_axes": ["microstructure"],
        }
    )
    mechanical_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "target_property_axes": ["yield strength", "elongation"],
        }
    )
    extracted_record = {
        "unit_kind": "measurement",
        "property_normalized": "elongation",
        "sample_context": {"sample_number": "3"},
        "value_payload": {"trend": "increase", "value": "10%"},
        "unit": "percentage",
        "resolution_status": "resolved",
    }

    off_target_records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 8},
        objective_context=microstructure_context,
        extracted_record=extracted_record,
    )
    on_target_records = service._objective_evidence_unit_records_from_extracted(
        route=ObjectiveEvidenceRoute.from_mapping(
            {**route.to_record(), "objective_id": "obj-mechanical"}
        ),
        source={"page": 8},
        objective_context=mechanical_context,
        extracted_record=extracted_record,
    )

    assert off_target_records[0]["unit_kind"] == "interpretation"
    assert off_target_records[0]["property_normalized"] == "elongation"
    assert on_target_records[0]["unit_kind"] == "measurement"


def test_research_objective_service_preserves_numeric_text_mechanisms(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-preheat",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "thermal-simulation",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-preheat",
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "porosity",
            ],
        }
    )

    extracted_records = [
        {
            "unit_kind": "measurement",
            "property_normalized": "cooling rate",
            "sample_context": {"condition": "P150"},
            "value_payload": {
                "source_value_text": "1.43x10 6 C/s",
                "value": 1.43e6,
            },
            "unit": "C/s",
            "resolution_status": "resolved",
        },
        {
            "unit_kind": "measurement",
            "property_normalized": "melt pool width/depth ratio",
            "sample_context": {"condition": "P150"},
            "value_payload": {"source_value_text": "1.7", "value": 1.7},
            "resolution_status": "resolved",
        },
        {
            "unit_kind": "measurement",
            "property_normalized": "residual stress",
            "sample_context": {"condition": "as-SLM"},
            "value_payload": {"source_value_text": "99.5 MPa", "value": 99.5},
            "unit": "MPa",
            "resolution_status": "resolved",
        },
    ]

    records = tuple(
        service._objective_evidence_unit_records_from_extracted(
            route=route,
            source={"page": 5},
            objective_context=objective_context,
            extracted_record=record,
        )[0]
        for record in extracted_records
    )

    assert [record["unit_kind"] for record in records] == [
        "characterization",
        "characterization",
        "characterization",
    ]
    assert [record["property_normalized"] for record in records] == [
        "cooling rate",
        "melt pool width/depth ratio",
        "residual stress",
    ]
    assert [record["value_payload"]["value"] for record in records] == [
        1.43e6,
        1.7,
        99.5,
    ]


def test_research_objective_service_reclassifies_text_comparison_without_pair_context(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.62,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 12},
        objective_context=None,
        extracted_record={
            "unit_kind": "comparison",
            "interpretation": (
                "Scanning strategy A exhibited highest densification compared "
                "to strategies B and C."
            ),
            "resolution_status": "resolved",
        },
    )

    assert len(records) == 1
    assert records[0]["unit_kind"] == "characterization"
    assert records[0]["interpretation"].startswith("Scanning strategy A")


def test_research_objective_service_does_not_expand_text_trends_into_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-2",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.72,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 6},
        objective_context=None,
        extracted_record={
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "value_payload": {"yield strength": "better mechanical properties"},
            "interpretation": "Strategy A performed better than B and C.",
            "resolution_status": "partial",
        },
    )

    assert len(records) == 1
    record = records[0]
    assert record["unit_kind"] == "interpretation"
    assert record["interpretation"] == "Strategy A performed better than B and C."
    assert record["value_payload"] == {"yield strength": "better mechanical properties"}


def test_research_objective_service_expands_result_table_matrix_measurements(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-2",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Condition number": "sample_condition",
                "Sample number": "sample_id",
                "Yield Strength (MPa)": "yield_strength",
                "Ultimate Tensile Strength (MPa)": "ultimate_tensile_strength",
                "Elongation (%)": "elongation",
                "Microhadness (HV)": "microhardness",
                "Standard deviation (HV)": "standard_deviation",
            },
            "confidence": 0.8,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "microhardness",
            ],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        objective_context=objective_context,
        source={
            "page": 3,
            "column_headers": [
                "Condition number",
                "Sample number",
                "Yield Strength (MPa)",
                "Ultimate Tensile Strength (MPa)",
                "Elongation (%)",
                "Microhadness (HV)",
                "Standard deviation (HV)",
            ],
            "table_matrix": [
                [
                    "Condition number",
                    "Sample number",
                    "Yield Strength (MPa)",
                    "Ultimate Tensile Strength (MPa)",
                    "Elongation (%)",
                    "Microhadness (HV)",
                    "Standard deviation (HV)",
                ],
                ["1", "1", "236.65", "375.13", "7.21", "215.65", "10.4"],
                ["1", "2", "159.97", "196.78", "1.79", "192.275", "10.9"],
            ],
        },
    )

    assert len(records) == 8
    assert {record["property_normalized"] for record in records} == {
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    }
    assert all(record["unit_kind"] == "measurement" for record in records)
    assert all(record["resolution_status"] == "resolved" for record in records)
    assert not any(
        record["property_normalized"] == "Standard deviation"
        for record in records
    )
    yield_record = next(
        record
        for record in records
        if record["property_normalized"] == "yield strength"
        and record["sample_context"]["Sample number"] == "1"
    )
    assert yield_record["sample_context"] == {
        "Condition number": "1",
        "Sample number": "1",
    }
    assert yield_record["value_payload"] == {
        "source_value_text": "236.65",
        "value": 236.65,
    }
    assert yield_record["unit"] == "MPa"
    assert yield_record["join_keys"] == {
        "condition_number": "1",
        "sample_number": "1",
    }


def test_research_objective_service_normalizes_compact_tensile_headers(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-preheat",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-mechanical",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Build platform conditions": "sample_condition",
                "\u0131 y (MPa)": "result_property",
                "\u0131 u (MPa)": "result_property",
                "EL%": "result_property",
            },
            "confidence": 0.82,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-preheat",
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        objective_context=objective_context,
        source={
            "page": 8,
            "column_headers": [
                "Build platform conditions",
                "\u0131 y (MPa)",
                "\u0131 u (MPa)",
                "EL%",
            ],
            "table_matrix": [
                [
                    "Build platform conditions",
                    "\u0131 y (MPa)",
                    "\u0131 u (MPa)",
                    "EL%",
                ],
                ["Non-preheated", "448", "617", "72"],
                ["Preheated", "465", "618", "82"],
            ],
        },
    )

    assert len(records) == 6
    assert {record["property_normalized"] for record in records} == {
        "yield strength",
        "ultimate tensile strength",
        "elongation",
    }
    assert {
        (
            record["sample_context"]["Build platform conditions"],
            record["sample_context"]["sample_number"],
            record["property_normalized"],
            record["value_payload"]["value"],
        )
        for record in records
    } == {
        ("Non-preheated", "1", "yield strength", 448.0),
        ("Non-preheated", "1", "ultimate tensile strength", 617.0),
        ("Non-preheated", "1", "elongation", 72.0),
        ("Preheated", "2", "yield strength", 465.0),
        ("Preheated", "2", "ultimate tensile strength", 618.0),
        ("Preheated", "2", "elongation", 82.0),
    }


def test_research_objective_service_skips_reference_rows_and_keeps_condition_axis(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-preheat",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-mechanical",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Build platform conditions": "test_condition",
                "\u0131 y (MPa)": "current_experimental_evidence",
                "\u0131 u (MPa)": "current_experimental_evidence",
                "El%": "current_experimental_evidence",
            },
            "confidence": 0.82,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-preheat",
            "variable_process_axes": ["build platform preheating"],
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        objective_context=objective_context,
        source={
            "page": 8,
            "column_headers": [
                "Build platform conditions",
                "\u0131 y (MPa)",
                "\u0131 u (MPa)",
                "El%",
            ],
            "table_matrix": [
                [
                    "Build platform conditions",
                    "\u0131 y (MPa)",
                    "\u0131 u (MPa)",
                    "El%",
                ],
                ["Non-preheated", "448", "617", "72"],
                ["Preheated", "465", "618", "82"],
                ["LB-PBF 316L [20]", "485", "594", "58"],
                ["Wrought [21][22,23]", "255-310", "535-623", "30-40"],
            ],
        },
    )

    assert len(records) == 6
    assert {
        (
            record["sample_context"]["Build platform conditions"],
            record["sample_context"]["sample_number"],
            record["property_normalized"],
            record["value_payload"]["value"],
        )
        for record in records
    } == {
        ("Non-preheated", "1", "yield strength", 448.0),
        ("Non-preheated", "1", "ultimate tensile strength", 617.0),
        ("Non-preheated", "1", "elongation", 72.0),
        ("Preheated", "2", "yield strength", 465.0),
        ("Preheated", "2", "ultimate tensile strength", 618.0),
        ("Preheated", "2", "elongation", 82.0),
    }

    comparison_units = service._build_objective_pairwise_comparison_units(
        tuple(ObjectiveEvidenceUnit.from_mapping(record) for record in records),
        objective_contexts=(objective_context,),
    )

    assert {
        (
            unit.sample_context["sample_number"],
            unit.baseline_context["sample_context"]["sample_number"],
            unit.property_normalized,
            unit.value_payload["comparison_axis"],
        )
        for unit in comparison_units
    } == {
        ("2", "1", "yield strength", "Build platform conditions"),
        ("2", "1", "ultimate tensile strength", "Build platform conditions"),
        ("2", "1", "elongation", "Build platform conditions"),
    }


def test_research_objective_service_skips_non_target_result_property_columns(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-preheat",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-chemistry",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Si": "result_property",
                "O": "result_property",
                "N": "result_property",
                "S": "result_property",
            },
            "confidence": 0.76,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-preheat",
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        objective_context=objective_context,
        source={
            "page": 3,
            "column_headers": ["Si", "O", "N", "S"],
            "table_matrix": [
                ["Si", "O", "N", "S"],
                ["0.10", "<0.10", "<0.10", "<0.03"],
            ],
        },
    )

    assert records == ()


def test_research_objective_service_skips_table_matrix_continuation_header_rows(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-eis",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Sample": "sample_id",
                "R film (Ω cm 2 )": "current_result",
            },
            "confidence": 0.8,
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        objective_context=None,
        source={
            "page": 8,
            "column_headers": ["Sample", "R film (Ω cm 2 )"],
            "table_matrix": [
                ["Sample", "R film"],
                ["", ""],
                ["", "film resistance"],
                ["375 W-2100 mm·s -1", "5.03×10 4"],
                ["255 W-1400 mm·s -1", "5.67×10 4"],
                ["135 W-750 mm·s -1", "1.90×10 5"],
            ],
        },
    )

    assert [record["sample_context"]["sample_number"] for record in records] == [
        "1",
        "2",
        "3",
    ]
    assert [record["sample_context"]["Sample"] for record in records] == [
        "375 W-2100 mm·s -1",
        "255 W-1400 mm·s -1",
        "135 W-750 mm·s -1",
    ]


def test_research_objective_service_adds_sample_numbers_to_labeled_table_rows(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-3",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Sample": "sample_id",
                "Density (%)": "target_property",
            },
            "confidence": 0.8,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-density",
            "target_property_axes": ["density"],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        objective_context=objective_context,
        source={
            "page": 7,
            "column_headers": ["Sample", "Density (%)"],
            "table_matrix": [
                ["Sample", "Density (%)"],
                ["375 W-2100 mm·s -1", "97.83"],
                ["255 W-1400 mm·s -1", "99.50"],
            ],
        },
    )

    assert [record["sample_context"] for record in records] == [
        {"Sample": "375 W-2100 mm·s -1", "sample_number": "1"},
        {"Sample": "255 W-1400 mm·s -1", "sample_number": "2"},
    ]


def test_research_objective_service_adds_sample_numbers_to_process_table_rows(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-process",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-2",
            "role": "process_or_treatment",
            "extractable": True,
            "column_roles": {
                "Laser power (W)": "variable_process_axis",
                "Scan speed (mm·s -1)": "variable_process_axis",
                "Energy density (J mm -3)": "variable_process_axis",
            },
            "confidence": 0.8,
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        objective_context=None,
        source={
            "page": 2,
            "column_headers": [
                "Test",
                "Laser power (W)",
                "Scan speed (mm·s -1)",
                "Energy density (J mm -3)",
            ],
            "table_matrix": [
                [
                    "Test",
                    "Laser power (W)",
                    "Scan speed (mm·s -1)",
                    "Energy density (J mm -3)",
                ],
                ["1", "375", "2100", "100"],
                ["2", "255", "1400", "100"],
            ],
        },
    )

    assert [record["sample_context"] for record in records] == [
        {"sample_number": "1"},
        {"sample_number": "2"},
    ]


def test_research_objective_service_keeps_unlabeled_process_table_columns_as_context(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-process",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "process_or_treatment",
            "extractable": True,
            "column_roles": {
                "Sample #": "sample_id",
            },
            "confidence": 0.8,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-process",
            "variable_process_axes": [
                "scan strategy rotation angle",
                "build orientation",
            ],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        objective_context=objective_context,
        source={
            "page": 2,
            "column_headers": ["Sample #", "ɵ ( ◦ )", "α ( ◦ )", "β ( ◦ )"],
            "table_matrix": [
                ["Sample #", "ɵ ( ◦ )", "α ( ◦ )", "β ( ◦ )"],
                ["1", "0", "0", "0"],
                ["2", "45", "0", "45"],
            ],
        },
    )

    assert len(records) == 2
    assert records[0]["sample_context"] == {"Sample #": "1"}
    assert records[0]["process_context"] == {
        "ɵ ( ◦ )": "0",
        "α ( ◦ )": "0",
        "β ( ◦ )": "0",
    }
    assert records[1]["sample_context"] == {"Sample #": "2"}
    assert records[1]["process_context"] == {
        "ɵ ( ◦ )": "45",
        "α ( ◦ )": "0",
        "β ( ◦ )": "45",
    }


def test_research_objective_service_resolves_measurements_from_process_units(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-measurement",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "Yield Strength",
            "sample_context": {
                "Condition number": "1",
                "Sample number": "2",
            },
            "value_payload": {
                "source_value_text": "236.65",
                "value": 236.65,
            },
            "unit": "MPa",
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-context",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "Condition number": "1",
                "Sample number": "2",
            },
            "process_context": {
                "Scan strategy": "Chessboard",
                "Scanning speed (mm/s)": "0.25",
                "Energy density (J/mm3)": "70",
            },
            "test_condition": {
                "Build atmosphere": "argon",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )
    duplicate_test_condition = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-test-condition",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "test_condition",
            "sample_context": {
                "Condition number": "1",
                "Sample number": "2",
            },
            "test_condition": {
                "Test method": "tensile test",
            },
            "resolution_status": "partial",
            "confidence": 0.72,
        }
    )
    other_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-other-process-context",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "Condition number": "2",
                "Sample number": "1",
            },
            "process_context": {
                "Scan strategy": "Stripe",
                "Scanning speed (mm/s)": "0.5",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )

    resolved_units = service._resolve_objective_evidence_unit_contexts(
        (
            measurement,
            duplicate_test_condition,
            process_context,
            other_process_context,
        ),
    )

    resolved_measurement = resolved_units[0]
    assert resolved_measurement.evidence_unit_id == "oeu-measurement"
    assert resolved_measurement.process_context == {
        "Scan strategy": "Chessboard",
        "Scanning speed (mm/s)": "0.25",
        "Energy density (J/mm3)": "70",
    }
    assert resolved_measurement.test_condition == {"Build atmosphere": "argon"}
    assert resolved_measurement.resolved_condition == {
        "context_unit_id": "oeu-process-context",
        "matched_sample_context": {
            "Condition number": "1",
            "Sample number": "2",
        },
    }
    assert resolved_measurement.resolution_status == "resolved"


def test_research_objective_service_resolves_measurements_from_process_label(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-measurement",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "pitting potential",
            "sample_context": {
                "Sample": "135 W-750 mm·s -1",
            },
            "value_payload": {
                "source_value_text": "355.4",
                "value": 355.4,
            },
            "unit": "mV",
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    matching_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-135-750",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "sample_number": "3",
            },
            "process_context": {
                "Laser power (W)": "135",
                "Scan speed (mm·s -1)": "750",
                "Energy density (J mm -3)": "100",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )
    other_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-255-1400",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "process_context": {
                "Laser power (W)": "255",
                "Scan speed (mm·s -1)": "1400",
                "Energy density (J mm -3)": "100",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )
    matching_text_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-text-135-750",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "porosity": "low",
                "process": "Selective Laser Melting",
            },
            "process_context": {
                "Laser power": "135 W",
                "Scanning speed": "750 mm/s",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )

    resolved_units = service._resolve_objective_evidence_unit_contexts(
        (
            measurement,
            matching_process_context,
            other_process_context,
            matching_text_context,
        ),
    )

    resolved_measurement = resolved_units[0]
    assert resolved_measurement.process_context == {
        "Laser power (W)": "135",
        "Scan speed (mm·s -1)": "750",
        "Energy density (J mm -3)": "100",
    }
    assert resolved_measurement.sample_context == {
        "Sample": "135 W-750 mm·s -1",
        "sample_number": "3",
    }
    assert resolved_measurement.resolved_condition == {
        "context_unit_id": "oeu-process-135-750",
        "matched_sample_context": {"sample_number": "3"},
    }
    assert resolved_measurement.resolution_status == "resolved"


def test_research_objective_service_prefers_sample_label_over_row_number_context(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-yield-as-slm",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {
                "Specimens": "as-SLM(120/100)",
                "sample_number": "11",
            },
            "value_payload": {
                "source_value_text": "464.8",
                "value": 464.8,
            },
            "unit": "MPa",
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    matching_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-as-slm",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "Specimens": "as-SLM (120/100)",
                "sample_number": "10",
            },
            "process_context": {
                "Specimens": "as-SLM (120/100)",
                "laser power": "120",
                "scan speed": "100",
                "treatment type": "-",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )
    duplicate_matching_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-as-slm-row-only",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "sample_number": "10",
            },
            "process_context": {
                "Specimens": "as-SLM (120/100)",
                "laser power": "120",
                "scan speed": "100",
                "treatment type": "-",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )
    row_number_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-row-11",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "Specimens": "HT-SLM (120/100)",
                "sample_number": "11",
            },
            "process_context": {
                "Specimens": "HT-SLM (120/100)",
                "laser power": "120",
                "scan speed": "100",
                "treatment type": "Furnace HT",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )

    resolved_units = service._resolve_objective_evidence_unit_contexts(
        (
            measurement,
            row_number_process_context,
            duplicate_matching_process_context,
            matching_process_context,
        ),
    )

    resolved_measurement = resolved_units[0]
    assert resolved_measurement.process_context["treatment type"] == "-"
    assert resolved_measurement.resolved_condition == {
        "context_unit_id": "oeu-process-as-slm",
        "matched_sample_context": {
            "Specimens": "as-SLM (120/100)",
            "sample_number": "10",
        },
    }
    assert resolved_measurement.sample_context["sample_number"] == "11"


def test_research_objective_service_prefers_descriptive_label_over_row_number_context(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-yield-as-slm-140-200",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {
                "Specimens": "as-SLM(140/ 200)",
                "sample_number": "23",
            },
            "value_payload": {
                "source_value_text": "426.7",
                "value": 426.7,
            },
            "unit": "MPa",
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    matching_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-as-slm-140-200",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "Specimens": "(140/ 100) as-SLM",
                "sample_number": "22",
            },
            "process_context": {
                "Laser energy density (J/ mm 3 )": "194",
                "Laser power (W)": "140",
                "Scan speed (mm/s)": "200",
                "Type of heat treatment": "-",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )
    row_number_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-ht-slm-140-200",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "Specimens": "(140/ 200) HT-SLM",
                "sample_number": "23",
            },
            "process_context": {
                "Laser energy density (J/ mm 3 )": "194",
                "Laser power (W)": "140",
                "Scan speed (mm/s)": "200",
                "Type of heat treatment": "Furnace HT",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )

    resolved_units = service._resolve_objective_evidence_unit_contexts(
        (
            measurement,
            row_number_process_context,
            matching_process_context,
        ),
    )

    resolved_measurement = resolved_units[0]
    assert resolved_measurement.process_context["Type of heat treatment"] == "-"
    assert resolved_measurement.resolved_condition == {
        "context_unit_id": "oeu-process-as-slm-140-200",
        "matched_sample_context": {
            "Specimens": "(140/ 100) as-SLM",
            "sample_number": "22",
        },
    }


def test_research_objective_service_uses_process_context_label_tokens(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-yield-as-slm-140-200",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {
                "Specimens": "as-SLM(140/ 200)",
                "sample_number": "23",
            },
            "value_payload": {
                "source_value_text": "426.7",
                "value": 426.7,
            },
            "unit": "MPa",
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    matching_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-as-slm-140-200",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "sample_number": "22",
            },
            "process_context": {
                "Laser energy density (J/ mm 3 )": "194",
                "Laser power (W)": "140",
                "Scan speed (mm/s)": "200",
                "Specimens": "(140/ 100) as-SLM",
                "Type of heat treatment": "-",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )
    row_number_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-hip-slm-140-200",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "sample_number": "24",
            },
            "process_context": {
                "Laser energy density (J/ mm 3 )": "194",
                "Laser power (W)": "140",
                "Scan speed (mm/s)": "200",
                "Specimens": "(140/ 200)",
                "Type of heat treatment": "HIP",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )

    resolved_units = service._resolve_objective_evidence_unit_contexts(
        (
            measurement,
            row_number_process_context,
            matching_process_context,
        ),
    )

    resolved_measurement = resolved_units[0]
    assert resolved_measurement.process_context["Type of heat treatment"] == "-"
    assert resolved_measurement.resolved_condition == {
        "context_unit_id": "oeu-process-as-slm-140-200",
        "matched_sample_context": {
            "sample_number": "22",
        },
    }


def test_research_objective_service_resolves_measurements_from_process_context(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-density-255-1400",
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "relative density",
            "sample_context": {
                "material": "316L stainless steel",
                "process": "Selective Laser Melting",
            },
            "process_context": {
                "laser_power": "255 W",
                "scanning_speed": "1400 mm/s",
            },
            "value_payload": {
                "source_value_text": "99.5%",
                "value": 99.5,
            },
            "unit": "%",
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    matching_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-255-1400",
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "sample_number": "2",
            },
            "process_context": {
                "Laser power (W)": "255",
                "Scan speed (mm·s -1)": "1400",
                "Energy density (J mm -3)": "100",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )
    other_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-135-750",
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {
                "sample_number": "3",
            },
            "process_context": {
                "Laser power (W)": "135",
                "Scan speed (mm·s -1)": "750",
                "Energy density (J mm -3)": "100",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )

    resolved_units = service._resolve_objective_evidence_unit_contexts(
        (
            measurement,
            matching_process_context,
            other_process_context,
        ),
    )

    resolved_measurement = resolved_units[0]
    assert resolved_measurement.process_context == {
        "Laser power (W)": "255",
        "Scan speed (mm·s -1)": "1400",
        "Energy density (J mm -3)": "100",
        "laser_power": "255 W",
        "scanning_speed": "1400 mm/s",
    }
    assert resolved_measurement.sample_context == {
        "material": "316L stainless steel",
        "process": "Selective Laser Melting",
        "sample_number": "2",
    }
    assert resolved_measurement.resolved_condition == {
        "context_unit_id": "oeu-process-255-1400",
        "matched_sample_context": {"sample_number": "2"},
    }
    assert resolved_measurement.resolution_status == "resolved"


def test_research_objective_service_generates_pairwise_comparison_units(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "question": "How do process axes affect yield strength?",
            "variable_process_axes": [
                "energy density",
                "scanning strategy",
                "scanning speed",
            ],
            "target_property_axes": ["yield strength"],
        }
    )

    def measurement(
        evidence_unit_id: str,
        *,
        condition_number: str,
        sample_number: str,
        strategy: str,
        speed: str,
        value: float,
        confidence: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-mechanical",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "yield strength",
                "sample_context": {
                    "Condition number": condition_number,
                    "Sample number": sample_number,
                },
                "process_context": {
                    "Energy density (J/mm 3 )": "70",
                    "Scan strategy": strategy,
                    "Scanning speed (mm/s)": speed,
                },
                "value_payload": {
                    "source_value_text": str(value),
                    "value": value,
                },
                "unit": "MPa",
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-2",
                        "page": 3,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": confidence,
            }
        )

    measurements = (
        measurement(
            "oeu-s1-yield",
            condition_number="1",
            sample_number="1",
            strategy="A",
            speed="0.25",
            value=236.65,
            confidence=0.8,
        ),
        measurement(
            "oeu-s2-yield",
            condition_number="1",
            sample_number="2",
            strategy="B",
            speed="0.25",
            value=159.97,
            confidence=0.7,
        ),
        measurement(
            "oeu-s8-yield",
            condition_number="4",
            sample_number="8",
            strategy="A",
            speed="0.239",
            value=187.82,
            confidence=0.75,
        ),
    )

    comparison_units = service._build_objective_pairwise_comparison_units(
        measurements,
        objective_contexts=(objective_context,),
    )

    assert len(comparison_units) == 2
    comparisons_by_axis = {
        unit.value_payload["comparison_axis"]: unit
        for unit in comparison_units
    }
    strategy_comparison = comparisons_by_axis["scanning strategy"]
    assert strategy_comparison.unit_kind == "comparison"
    assert strategy_comparison.sample_context["Sample number"] == "1"
    assert strategy_comparison.baseline_context["sample_context"][
        "Sample number"
    ] == "2"
    assert strategy_comparison.value_payload["value"] == 236.65
    assert strategy_comparison.baseline_context["value"] == 159.97
    assert strategy_comparison.value_payload["direction"] == "increase"
    assert strategy_comparison.source_refs == (
        {
            "source_kind": "table",
            "source_ref": "table-2",
            "page": 3,
        },
    )
    speed_comparison = comparisons_by_axis["scanning speed"]
    assert speed_comparison.sample_context["Sample number"] == "1"
    assert speed_comparison.baseline_context["sample_context"]["Sample number"] == "8"
    assert speed_comparison.value_payload["baseline_evidence_unit_id"] == (
        "oeu-s8-yield"
    )


def test_research_objective_service_matches_contextual_property_variants_for_pairwise(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-yield",
            "variable_process_axes": ["scan strategy rotation angle"],
            "target_property_axes": ["yield strength"],
        }
    )

    def measurement(
        evidence_unit_id: str,
        *,
        sample_number: str,
        rotation_angle: str,
        value: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-yield",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "yield strength experiment",
                "sample_context": {"sample_number": sample_number},
                "process_context": {"θ ( ◦ )": rotation_angle},
                "value_payload": {"source_value_text": str(value), "value": value},
                "unit": "MPa",
                "resolution_status": "resolved",
                "confidence": 0.84,
            }
        )

    comparison_units = service._build_objective_pairwise_comparison_units(
        (
            measurement(
                "oeu-yield-1",
                sample_number="1",
                rotation_angle="0",
                value=334.2,
            ),
            measurement(
                "oeu-yield-4",
                sample_number="4",
                rotation_angle="45",
                value=351.9,
            ),
        ),
        objective_contexts=(objective_context,),
    )

    assert len(comparison_units) == 1
    assert comparison_units[0].property_normalized == "yield strength experiment"
    assert comparison_units[0].sample_context["sample_number"] == "4"
    assert comparison_units[0].baseline_context["sample_context"]["sample_number"] == "1"


def test_research_objective_service_selects_large_grid_pairs_from_raw_angle_axes(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-yield",
            "variable_process_axes": ["scan strategy rotation angle"],
            "target_property_axes": ["yield strength"],
        }
    )

    def measurement(
        evidence_unit_id: str,
        *,
        sample_number: str,
        theta: str,
        value: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-yield",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "yield strength experiment",
                "sample_context": {"sample_number": sample_number},
                "process_context": {"θ ( ◦ )": theta},
                "value_payload": {"source_value_text": str(value), "value": value},
                "unit": "MPa",
                "resolution_status": "resolved",
                "confidence": 0.84,
            }
        )

    comparison_units = service._build_objective_pairwise_comparison_units(
        (
            measurement("oeu-yield-1", sample_number="1", theta="0", value=334.2),
            measurement("oeu-yield-2", sample_number="2", theta="30", value=342.5),
            measurement("oeu-yield-3", sample_number="3", theta="45", value=351.9),
            measurement("oeu-yield-4", sample_number="4", theta="90", value=365.6),
        ),
        objective_contexts=(objective_context,),
    )

    comparison_pairs = {
        (
            unit.sample_context["sample_number"],
            unit.baseline_context["sample_context"]["sample_number"],
            unit.value_payload["comparison_axis"],
        )
        for unit in comparison_units
    }

    assert comparison_pairs == {
        ("2", "1", "θ"),
        ("3", "2", "θ"),
        ("4", "3", "θ"),
    }


def test_research_objective_service_orders_numeric_axis_comparison_before_value_direction(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-ved",
            "variable_process_axes": ["volumetric energy density"],
            "target_property_axes": ["ultimate tensile strength"],
        }
    )

    def measurement(
        evidence_unit_id: str,
        *,
        sample_label: str,
        ved: str,
        value: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-ved",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "ultimate tensile strength",
                "sample_context": {"sample_id": sample_label},
                "process_context": {"VED [J/mm 3]": ved},
                "value_payload": {"source_value_text": str(value), "value": value},
                "unit": "MPa",
                "resolution_status": "resolved",
                "confidence": 0.84,
            }
        )

    comparison_units = service._build_objective_pairwise_comparison_units(
        (
            measurement("oeu-l-uts", sample_label="L-VED", ved="50", value=610),
            measurement("oeu-h-uts", sample_label="H-VED", ved="150", value=560),
        ),
        objective_contexts=(objective_context,),
    )

    assert len(comparison_units) == 1
    comparison = comparison_units[0]
    assert comparison.sample_context["sample_id"] == "H-VED"
    assert comparison.baseline_context["sample_context"]["sample_id"] == "L-VED"
    assert comparison.value_payload["current_value"] == 560.0
    assert comparison.baseline_context["value"] == 610.0
    assert comparison.value_payload["direction"] == "decrease"


def test_research_objective_service_does_not_use_ascii_raw_process_fallback(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-yield",
            "variable_process_axes": ["scan strategy rotation angle"],
            "target_property_axes": ["yield strength"],
        }
    )

    def measurement(
        evidence_unit_id: str,
        *,
        sample_number: str,
        operator_note: str,
        value: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-yield",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "yield strength",
                "sample_context": {"sample_number": sample_number},
                "process_context": {"Operator note": operator_note},
                "value_payload": {"source_value_text": str(value), "value": value},
                "unit": "MPa",
                "resolution_status": "resolved",
                "confidence": 0.84,
            }
        )

    comparison_units = service._build_objective_pairwise_comparison_units(
        (
            measurement(
                "oeu-yield-1",
                sample_number="1",
                operator_note="batch A",
                value=334.2,
            ),
            measurement(
                "oeu-yield-2",
                sample_number="2",
                operator_note="batch B",
                value=351.9,
            ),
        ),
        objective_contexts=(objective_context,),
    )

    assert comparison_units == ()


def test_research_objective_service_generates_small_set_multi_axis_comparisons(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-density",
            "question": "How do laser power and scan speed affect density?",
            "variable_process_axes": [
                "laser power",
                "scan speed",
                "energy density",
            ],
            "target_property_axes": ["density"],
        }
    )

    def density_unit(
        evidence_unit_id: str,
        *,
        sample_number: str,
        laser_power: str,
        scan_speed: str,
        density: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "density",
                "sample_context": {"sample_number": sample_number},
                "process_context": {
                    "Laser power (W)": laser_power,
                    "Scan speed (mm·s -1)": scan_speed,
                    "Energy density (J mm -3)": "100",
                },
                "value_payload": {
                    "source_value_text": str(density),
                    "value": density,
                },
                "unit": "%",
                "resolution_status": "resolved",
                "confidence": 0.8,
            }
        )

    comparison_units = service._build_objective_pairwise_comparison_units(
        (
            density_unit(
                "oeu-density-1",
                sample_number="1",
                laser_power="375",
                scan_speed="2100",
                density=97.83,
            ),
            density_unit(
                "oeu-density-2",
                sample_number="2",
                laser_power="255",
                scan_speed="1400",
                density=99.5,
            ),
            density_unit(
                "oeu-density-3",
                sample_number="3",
                laser_power="135",
                scan_speed="750",
                density=99.26,
            ),
        ),
        objective_contexts=(objective_context,),
    )

    assert {
        (
            unit.sample_context["sample_number"],
            unit.baseline_context["sample_context"]["sample_number"],
            unit.value_payload["comparison_axis"],
        )
        for unit in comparison_units
    } == {
        ("2", "1", "laser power, scan speed"),
        ("3", "1", "laser power, scan speed"),
        ("2", "3", "laser power, scan speed"),
    }


def test_research_objective_service_generates_pairwise_from_sample_condition_axis(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-preheat",
            "question": "How does build platform preheating affect tensile properties?",
            "variable_process_axes": ["build platform preheating"],
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
        }
    )

    def measurement(
        evidence_unit_id: str,
        *,
        sample_number: str,
        platform_condition: str,
        property_name: str,
        value: float,
        unit: str,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-preheat",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": property_name,
                "sample_context": {
                    "Build platform conditions": platform_condition,
                    "sample_number": sample_number,
                },
                "process_context": {},
                "value_payload": {
                    "source_value_text": str(value),
                    "value": value,
                },
                "unit": unit,
                "resolution_status": "resolved",
                "confidence": 0.82,
            }
        )

    comparison_units = service._build_objective_pairwise_comparison_units(
        (
            measurement(
                "oeu-np-yield",
                sample_number="1",
                platform_condition="Non-preheated",
                property_name="yield strength",
                value=448,
                unit="MPa",
            ),
            measurement(
                "oeu-p-yield",
                sample_number="2",
                platform_condition="Preheated",
                property_name="yield strength",
                value=465,
                unit="MPa",
            ),
            measurement(
                "oeu-np-uts",
                sample_number="1",
                platform_condition="Non-preheated",
                property_name="ultimate tensile strength",
                value=617,
                unit="MPa",
            ),
            measurement(
                "oeu-p-uts",
                sample_number="2",
                platform_condition="Preheated",
                property_name="ultimate tensile strength",
                value=618,
                unit="MPa",
            ),
            measurement(
                "oeu-np-el",
                sample_number="1",
                platform_condition="Non-preheated",
                property_name="elongation",
                value=72,
                unit="%",
            ),
            measurement(
                "oeu-p-el",
                sample_number="2",
                platform_condition="Preheated",
                property_name="elongation",
                value=82,
                unit="%",
            ),
        ),
        objective_contexts=(objective_context,),
    )

    assert {
        (
            unit.sample_context["sample_number"],
            unit.baseline_context["sample_context"]["sample_number"],
            unit.property_normalized,
            unit.value_payload["comparison_axis"],
            unit.value_payload["current_value"],
            unit.baseline_context["value"],
        )
        for unit in comparison_units
    } == {
        ("2", "1", "yield strength", "Build platform conditions", 465.0, 448.0),
        (
            "2",
            "1",
            "ultimate tensile strength",
            "Build platform conditions",
            618.0,
            617.0,
        ),
        ("2", "1", "elongation", "Build platform conditions", 82.0, 72.0),
    }


def test_research_objective_service_limits_pairwise_to_target_properties(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-corrosion",
            "question": "How do process axes affect corrosion potential?",
            "variable_process_axes": ["laser power"],
            "target_property_axes": ["pitting potential"],
        }
    )

    def measurement(
        evidence_unit_id: str,
        *,
        sample_number: str,
        laser_power: str,
        property_name: str,
        value: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-corrosion",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": property_name,
                "sample_context": {"sample_number": sample_number},
                "process_context": {"Laser power (W)": laser_power},
                "value_payload": {
                    "source_value_text": str(value),
                    "value": value,
                },
                "unit": "mV",
                "resolution_status": "resolved",
                "confidence": 0.8,
            }
        )

    comparison_units = service._build_objective_pairwise_comparison_units(
        (
            measurement(
                "oeu-ep-1",
                sample_number="1",
                laser_power="135",
                property_name="E p",
                value=124.7,
            ),
            measurement(
                "oeu-ep-2",
                sample_number="2",
                laser_power="255",
                property_name="E p",
                value=199.7,
            ),
            measurement(
                "oeu-rfilm-1",
                sample_number="1",
                laser_power="135",
                property_name="R film",
                value=5.03,
            ),
            measurement(
                "oeu-rfilm-2",
                sample_number="2",
                laser_power="255",
                property_name="R film",
                value=5.67,
            ),
        ),
        objective_contexts=(objective_context,),
    )

    assert len(comparison_units) == 1
    assert comparison_units[0].property_normalized == "E p"
    assert comparison_units[0].value_payload["comparison_axis"] == "laser power"


def test_research_objective_service_limits_large_grid_to_adjacent_axis_pairs(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-grid",
            "question": "How do laser power and scan speed affect yield strength?",
            "variable_process_axes": ["laser power", "scan speed"],
            "target_property_axes": ["yield strength"],
        }
    )

    def measurement(
        sample_number: str,
        *,
        laser_power: str,
        scan_speed: str,
        value: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": f"oeu-grid-{sample_number}",
                "objective_id": "obj-grid",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "yield strength",
                "sample_context": {"sample_number": sample_number},
                "process_context": {
                    "Laser power (W)": laser_power,
                    "Scan speed (mm/s)": scan_speed,
                },
                "value_payload": {
                    "source_value_text": str(value),
                    "value": value,
                },
                "unit": "MPa",
                "resolution_status": "resolved",
                "confidence": 0.8,
            }
        )

    comparison_units = service._build_objective_pairwise_comparison_units(
        (
            measurement("1", laser_power="100", scan_speed="100", value=100),
            measurement("2", laser_power="120", scan_speed="100", value=120),
            measurement("3", laser_power="140", scan_speed="100", value=140),
            measurement("4", laser_power="100", scan_speed="200", value=110),
            measurement("5", laser_power="120", scan_speed="200", value=130),
            measurement("6", laser_power="140", scan_speed="200", value=150),
        ),
        objective_contexts=(objective_context,),
    )

    comparison_pairs = {
        (
            unit.sample_context["sample_number"],
            unit.baseline_context["sample_context"]["sample_number"],
        )
        for unit in comparison_units
    }
    assert comparison_pairs == {
        ("2", "1"),
        ("3", "2"),
        ("4", "1"),
        ("5", "2"),
        ("5", "4"),
        ("6", "3"),
        ("6", "5"),
    }


def test_research_objective_service_caps_large_multiaxis_table_comparisons(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-large-table",
            "question": (
                "How do laser power, scan speed, and heat treatment affect "
                "mechanical properties?"
            ),
            "variable_process_axes": [
                "laser power",
                "scan speed",
                "heat treatment type",
            ],
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "hardness",
            ],
        }
    )

    def measurement(
        evidence_unit_id: str,
        *,
        sample_number: str,
        laser_power: str,
        scan_speed: str,
        heat_treatment: str,
        property_name: str,
        value: float,
        unit: str,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-large-table",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": property_name,
                "sample_context": {"sample_number": sample_number},
                "process_context": {
                    "Laser power (W)": laser_power,
                    "Scan speed (mm/s)": scan_speed,
                    "Heat treatment type": heat_treatment,
                },
                "value_payload": {
                    "source_value_text": str(value),
                    "value": value,
                },
                "unit": unit,
                "resolution_status": "resolved",
                "confidence": 0.84,
            }
        )

    units: list[ObjectiveEvidenceUnit] = []
    properties = (
        ("yield strength", "MPa", 300.0),
        ("ultimate tensile strength", "MPa", 500.0),
        ("elongation", "%", 8.0),
        ("hardness", "HV", 180.0),
    )
    sample_index = 0
    for heat_index, heat_treatment in enumerate(("as-built", "stress-relieved")):
        for speed_index, scan_speed in enumerate(("700", "900", "1100")):
            for power_index, laser_power in enumerate(("150", "200", "250")):
                sample_index += 1
                for property_index, (property_name, unit, base_value) in enumerate(
                    properties
                ):
                    value = (
                        base_value
                        + power_index * 11
                        + speed_index * 17
                        + heat_index * 23
                        + property_index
                    )
                    units.append(
                        measurement(
                            f"oeu-large-{sample_index}-{property_index}",
                            sample_number=str(sample_index),
                            laser_power=laser_power,
                            scan_speed=scan_speed,
                            heat_treatment=heat_treatment,
                            property_name=property_name,
                            value=value,
                            unit=unit,
                        )
                    )

    comparison_units = service._build_objective_pairwise_comparison_units(
        tuple(units),
        objective_contexts=(objective_context,),
    )

    comparison_counts: dict[tuple[str | None, str], int] = {}
    for unit in comparison_units:
        key = (
            unit.property_normalized,
            unit.value_payload["comparison_axis"],
        )
        comparison_counts[key] = comparison_counts.get(key, 0) + 1

    assert len(comparison_units) == 36
    assert set(comparison_counts.values()) == {3}
    assert all(
        len(unit.value_payload.get("controlled_axes") or []) >= 2
        for unit in comparison_units
    )


def test_research_objective_service_limits_pbf_pairwise_comparisons_to_controlled_specs(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    density_objective_id = "obj-density"
    mechanical_objective_id = "obj-mechanical"
    density_context = ObjectiveContext.from_mapping(
        {
            "objective_id": density_objective_id,
            "question": "How do process axes affect densification?",
            "variable_process_axes": [
                "energy density",
                "scanning strategy",
                "scanning speed",
            ],
            "target_property_axes": ["densification", "microstructure"],
        }
    )
    mechanical_context = ObjectiveContext.from_mapping(
        {
            "objective_id": mechanical_objective_id,
            "question": "How do process axes affect mechanical properties?",
            "variable_process_axes": [
                "energy density",
                "scanning strategy",
                "scanning speed",
            ],
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "microhardness",
            ],
        }
    )
    process_rows = {
        "1": ("1", "A", "70", "0.25"),
        "2": ("1", "B", "70", "0.25"),
        "3": ("1", "C", "70", "0.25"),
        "4": ("2", "A", "100", "0.175"),
        "5": ("3", "A", "150", "0.12"),
        "6": ("3", "B", "150", "0.12"),
        "7": ("3", "C", "150", "0.12"),
        "8": ("4", "A", "70", "0.239"),
        "9": ("4", "B", "70", "0.239"),
        "10": ("4", "C", "70", "0.239"),
        "11": ("5", "A", "100", "0.167"),
        "12": ("5", "B", "100", "0.167"),
        "13": ("5", "C", "100", "0.167"),
        "14": ("6", "A", "150", "0.111"),
        "15": ("6", "B", "150", "0.111"),
        "16": ("6", "C", "150", "0.111"),
    }
    density_values = {
        "1": 95.4,
        "2": 97.7,
        "3": 93.8,
        "4": 93.9,
        "5": 97.14,
        "6": 95.7,
        "7": 94.3,
        "8": 96.8,
        "9": 92.4,
        "10": 93.8,
        "11": 96.2,
        "12": 96.1,
        "13": 98.0,
        "14": 99.45,
        "15": 96.7,
        "16": 98.6,
    }
    mechanical_values = {
        "1": (236.65, 375.13, 7.21, 215.65),
        "2": (159.97, 196.78, 1.79, 192.275),
        "3": (169.4, 199.47, 2.27, 187.95),
        "4": (341.38, 459.58, 6.62, 219.4),
        "5": (302.24, 384.5, 6.4, 189.1),
        "6": (200.31, 278.13, 1.62, 190.05),
        "7": (263.55, 356.84, 2.93, 186.55),
        "8": (187.82, 269.95, 3.66, 216.35),
        "9": (148.36, 178.37, 2.08, 178.1),
        "10": (161.61, 198.47, 2.12, 176.35),
        "11": (177.68, 203.48, 3.31, 182.8),
        "12": (201.08, 239.34, 2.42, 184.1),
        "13": (186.46, 256.68, 2.194, 188.05),
        "14": (462.02, 584.44, 41.9, 223.4),
        "15": (278.76, 342.23, 4.29, 184.0),
        "16": (414.07, 530.37, 1.17, 187.7),
    }

    def measurement(
        objective_id: str,
        sample_number: str,
        property_name: str,
        value: float,
        unit: str,
    ) -> ObjectiveEvidenceUnit:
        condition_number, strategy, energy_density, scan_speed = process_rows[
            sample_number
        ]
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": (
                    f"oeu-{objective_id}-{sample_number}-{property_name}"
                ),
                "objective_id": objective_id,
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": property_name,
                "sample_context": {
                    "Condition number": condition_number,
                    "Sample number": sample_number,
                },
                "process_context": {
                    "Energy density (J/mm 3 )": energy_density,
                    "Scan strategy": strategy,
                    "Scanning speed (mm/s)": scan_speed,
                },
                "value_payload": {
                    "source_value_text": str(value),
                    "value": value,
                },
                "unit": unit,
                "resolution_status": "resolved",
                "confidence": 0.8,
            }
        )

    units: list[ObjectiveEvidenceUnit] = [
        measurement(
            density_objective_id,
            sample_number,
            "relative density",
            value,
            "%",
        )
        for sample_number, value in density_values.items()
    ]
    for sample_number, values in mechanical_values.items():
        for property_name, value, unit in (
            ("yield strength", values[0], "MPa"),
            ("ultimate tensile strength", values[1], "MPa"),
            ("elongation", values[2], "%"),
            ("microhardness", values[3], "HV"),
        ):
            units.append(
                measurement(
                    mechanical_objective_id,
                    sample_number,
                    property_name,
                    value,
                    unit,
                )
            )

    comparison_units = service._build_objective_pairwise_comparison_units(
        tuple(units),
        objective_contexts=(density_context, mechanical_context),
    )

    comparison_keys = {
        (
            unit.objective_id,
            unit.sample_context["Sample number"],
            unit.baseline_context["sample_context"]["Sample number"],
            unit.property_normalized,
        )
        for unit in comparison_units
    }
    assert len(comparison_units) == 19
    assert all(
        unit.property_normalized != "microhardness" for unit in comparison_units
    )
    assert comparison_keys == {
        (density_objective_id, "1", "3", "relative density"),
        (density_objective_id, "2", "1", "relative density"),
        (density_objective_id, "4", "11", "relative density"),
        (density_objective_id, "5", "14", "relative density"),
        (mechanical_objective_id, "1", "2", "yield strength"),
        (mechanical_objective_id, "1", "2", "ultimate tensile strength"),
        (mechanical_objective_id, "1", "2", "elongation"),
        (mechanical_objective_id, "1", "8", "yield strength"),
        (mechanical_objective_id, "1", "8", "ultimate tensile strength"),
        (mechanical_objective_id, "1", "8", "elongation"),
        (mechanical_objective_id, "4", "11", "yield strength"),
        (mechanical_objective_id, "4", "11", "ultimate tensile strength"),
        (mechanical_objective_id, "5", "14", "yield strength"),
        (mechanical_objective_id, "5", "14", "ultimate tensile strength"),
        (mechanical_objective_id, "5", "14", "elongation"),
        (mechanical_objective_id, "14", "15", "yield strength"),
        (mechanical_objective_id, "14", "16", "yield strength"),
        (mechanical_objective_id, "14", "15", "elongation"),
        (mechanical_objective_id, "14", "16", "elongation"),
    }


def test_research_objective_service_adds_context_hint_route_for_condition_table(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "relevant_tables": ["table-2"],
            "excluded_tables": ["table-1"],
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "question": "How do processing parameters affect yield strength?",
            "variable_process_axes": [
                "energy density",
                "scanning strategy",
                "scanning speed",
            ],
            "target_property_axes": ["yield strength"],
            "routing_hints": [
                {
                    "document_id": "paper-1",
                    "table_id": "table-1",
                    "role": "condition_context",
                    "reason": "Table contains process variables.",
                }
            ],
            "confidence": 0.9,
        }
    )
    routes: list[ObjectiveEvidenceRoute] = []

    service._append_objective_context_hint_routes(
        routes=routes,
        seen=set(),
        frame=frame,
        objective_context=objective_context,
        candidate_by_key={
            ("table", "table-1"): {
                "source_kind": "table",
                "source_ref": "table-1",
                "frame_status": "excluded",
                "table_schema": {
                    "column_headers": [
                        "Condition number",
                        "Sample number",
                        "Scan strategy",
                        "Scanning speed (mm/s)",
                        "Energy density (J/mm 3 )",
                        "Relative density",
                    ],
                },
            }
        },
    )

    assert len(routes) == 1
    route = routes[0]
    assert route.role == "process_or_treatment"
    assert route.extractable is True
    assert route.source_ref == "table-1"
    assert route.column_roles == {
        "Condition number": "sample_condition",
        "Sample number": "sample_id",
        "Scan strategy": "process_variable",
        "Scanning speed (mm/s)": "process_variable",
        "Energy density (J/mm 3 )": "process_variable",
    }


def test_research_objective_service_ranks_result_text_candidates(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-structure",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["scanning speed", "energy density"],
            "measured_property_scope": ["microstructure", "densification"],
            "relevant_sections": ["Paper title"],
        }
    )
    blocks = [
        SimpleNamespace(
            block_id="intro",
            block_order=1,
            block_type="paragraph",
            heading_path="Paper title",
            text="Prior work studied 316L stainless steel processing.",
        ),
        SimpleNamespace(
            block_id="microstructure-results",
            block_order=100,
            block_type="paragraph",
            heading_path="3.3. Microstructure",
            text=(
                "The higher scanning speed samples showed refined "
                "microstructure and better densification."
            ),
        ),
        SimpleNamespace(
            block_id="conclusion",
            block_order=120,
            block_type="list_item",
            heading_path="4. Conclusion",
            text=(
                "Samples processed at higher scanning speed exhibited better "
                "densification and refined microstructure."
            ),
        ),
    ]

    candidates = service._build_route_source_candidates(
        frame=frame,
        blocks=blocks,
        tables=[],
    )

    candidate_refs = [candidate["source_ref"] for candidate in candidates]
    assert set(candidate_refs[:2]) == {"microstructure-results", "conclusion"}
    assert "intro" not in candidate_refs

    routes: list[ObjectiveEvidenceRoute] = []
    service._append_ranked_text_hint_routes(
        routes=routes,
        seen=set(),
        frame=frame,
        source_candidates=candidates,
    )

    assert [route.source_ref for route in routes] == [
        "conclusion",
        "microstructure-results",
    ]
    assert {route.role for route in routes} == {"characterization"}


def test_research_objective_service_keeps_numeric_mechanism_text_candidates(
    tmp_path,
):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-preheating",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["build platform temperature"],
            "measured_property_scope": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "porosity",
            ],
            "test_environment_scope": ["preheating"],
            "relevant_sections": ["Abstract"],
        }
    )
    blocks = [
        SimpleNamespace(
            block_id="cooling-rate",
            block_order=86,
            block_type="paragraph",
            heading_path="Thermal Simulation and Microstructure",
            text=(
                "The cooling rate values were obtained from the simulation "
                "to be 1.43x10 6 C/s for P150, and 1.65x10 6 C/s for "
                "the NP condition."
            ),
        ),
        SimpleNamespace(
            block_id="melt-pool-ratio",
            block_order=87,
            block_type="paragraph",
            heading_path="Thermal Simulation and Microstructure",
            text=(
                "The average width to depth ratios of the melt pool are "
                "calculated for NP and P150 conditions to be 1.38 and 1.7, "
                "respectively."
            ),
        ),
        SimpleNamespace(
            block_id="residual-stress",
            block_order=88,
            block_type="paragraph",
            heading_path="3.1. X-ray diffraction and residual stress",
            text=(
                "The HT-SLM (i.e., 17.8 MPa) and HIP-SLM (i.e., 27.5 MPa) "
                "showed comparable residual stress values, whereas the "
                "as-SLM residual stress was found to be 99.5 MPa."
            ),
        ),
    ]

    candidates = service._build_route_source_candidates(
        frame=frame,
        blocks=blocks,
        tables=[],
    )

    assert {candidate["source_ref"] for candidate in candidates} == {
        "cooling-rate",
        "melt-pool-ratio",
        "residual-stress",
    }


def test_research_objective_service_drops_known_empty_evidence_units(tmp_path):
    service = ResearchObjectiveService(
        collection_service=CollectionService(tmp_path / "collections"),
    )
    empty_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "objective_id": "obj-1",
            "document_id": "paper-1",
            "unit_kind": "characterization",
            "source_refs": [{"source_kind": "text_window", "source_ref": "b1"}],
        }
    )
    useful_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "objective_id": "obj-1",
            "document_id": "paper-1",
            "unit_kind": "characterization",
            "source_refs": [{"source_kind": "text_window", "source_ref": "b1"}],
            "value_payload": {"microstructure": "refined dendrites"},
        }
    )
    empty_measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "objective_id": "obj-1",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {"scanning_strategy": "A"},
            "process_context": {"process": "Selective Laser Melting"},
            "source_refs": [{"source_kind": "text_window", "source_ref": "b2"}],
        }
    )

    assert not service._objective_evidence_unit_has_payload(empty_unit)
    assert not service._objective_evidence_unit_has_payload(empty_measurement)
    assert service._objective_evidence_unit_has_payload(useful_unit)


def test_structured_objective_evidence_unit_wraps_scalar_value_payload():
    unit = StructuredObjectiveEvidenceUnit.model_validate(
        {
            "unit_kind": "measurement",
            "sample_context": "not a mapping",
            "value_payload": 95.4,
        }
    )

    assert unit.sample_context == {}
    assert unit.value_payload == {
        "value": 95.4,
        "source_value_text": "95.4",
    }


def test_research_objective_service_builds_and_persists_db_records(tmp_path, caplog):
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

    with caplog.at_level("INFO"):
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
    assert len(facts.objective_evidence_units) == 3
    measurement_units = [
        unit
        for unit in facts.objective_evidence_units
        if unit.unit_kind == "measurement"
    ]
    assert len(measurement_units) == 2
    assert {unit.sample_context["sample"] for unit in measurement_units} == {
        "as-built",
        "heat-treated",
    }
    assert all(
        unit.source_refs[0]["route_id"] == table_route.route_id
        for unit in measurement_units
    )
    process_unit = next(
        unit
        for unit in facts.objective_evidence_units
        if unit.unit_kind == "process_context"
    )
    assert process_unit.source_refs[0]["route_id"] == text_route.route_id
    assert len(facts.objective_logic_chains) == 1
    chain_payload = facts.objective_logic_chains[0].chain_payload
    assert chain_payload["schema_version"] == "objective_logic_chain.v1"
    assert chain_payload["unit_counts_by_kind"]["measurement"] == 2
    assert chain_payload["cross_paper"]["resolved_measurement_count"] == 2
    assert chain_payload["cross_paper"]["measurement_range_ready"] is True
    value_ranges = chain_payload["cross_paper"]["measurement_value_ranges"]
    assert len(value_ranges) == 1
    corrosion_range = value_ranges[0]
    assert corrosion_range["property_normalized"] == "corrosion current"
    assert corrosion_range["measurement_count"] == 2
    assert corrosion_range["min"]["value"] == 0.4
    assert corrosion_range["min"]["source_value_text"] == "0.4 uA/cm2"
    assert corrosion_range["min"]["sample_context"] == {"sample": "heat-treated"}
    assert corrosion_range["max"]["value"] == 1.2
    assert corrosion_range["max"]["source_value_text"] == "1.2 uA/cm2"
    assert corrosion_range["max"]["sample_context"] == {"sample": "as-built"}
    assert "corrosion current range 0.4 uA/cm2-1.2 uA/cm2" in str(
        facts.objective_logic_chains[0].summary
    )
    assert len(extractor.route_payloads) == 1
    assert len(extractor.unit_payloads) == 1
    assert extractor.unit_payloads[0]["evidence_route"]["source_kind"] == "text_window"
    assert extractor.unit_payloads[0]["evidence_route"]["source_ref"] == "b2"
    assert extractor.route_payloads[0]["paper_frame"]["frame_id"] == active_frame.frame_id
    assert extractor.skim_payloads[0]["table_captions"][0]["table_id"] == "table-1"
    assert extractor.discovery_payloads[0]["paper_skims"][0]["document_id"] == "paper-1"
    assert extractor.frame_payloads[0]["objective_context"]["objective_id"] == (
        facts.research_objectives[0].objective_id
    )
    assert extractor.frame_payloads[0]["table_summaries"][0]["table_id"] == "table-1"
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
    assert any(
        "Research objective paper framing document finished" in record.message
        and "relevant_tables=1" in record.message
        for record in caplog.records
    )
    assert any(
        "Research objective evidence routing frame finished" in record.message
        and "extractable_route_count=2" in record.message
        for record in caplog.records
    )
    assert any(
        "Research objective evidence-unit extraction finished" in record.message
        and "objective_evidence_units=3" in record.message
        for record in caplog.records
    )
    assert any(
        "Research objective logic-chain assembly finished" in record.message
        and "logic_chain_count=1" in record.message
        for record in caplog.records
    )

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


def test_research_objective_service_dedupes_subset_after_rejected_merge_plan(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _DroppedObjectiveMergeExtractor(),
    )

    assert len(objectives) == 2
    mechanical_objective = next(
        objective
        for objective in objectives
        if "yield strength" in objective.property_axes
    )
    assert mechanical_objective.property_axes == (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    )


def test_research_objective_service_falls_back_when_merge_plan_invents_axis(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _InventedAxisMergeExtractor(),
    )

    assert len(objectives) == 2
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
