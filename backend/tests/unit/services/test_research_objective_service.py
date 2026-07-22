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
    StructuredResearchUnderstandingRelations,
    StructuredResearchObjective,
    StructuredResearchObjectives,
    StructuredTableMatrixRepair,
)
from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveService as _ResearchObjectiveService,
)
from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
)
from application.core.research_understanding_service import (
    ResearchUnderstandingService,
)
from tests.support.collection_service import build_test_collection_service
from domain.core import (
    DocumentProfile,
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectiveFactSet,
    ObjectiveLogicChain,
    ObjectivePaperFrame,
    PaperSkim,
    ResearchObjective,
)
from domain.source import SourceArtifactSet, SourceDocumentNode, SourceDocumentTree
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.source_artifact_repository import MemorySourceArtifactRepository
from tests.support.objective_understanding_repository import (
    InMemoryObjectiveUnderstandingRepository,
)


def _build_research_objective_service(
    *,
    collection_service,
    **kwargs,
) -> _ResearchObjectiveService:
    source_repository = kwargs.pop("source_artifact_repository", None)
    if source_repository is None:
        source_repository = getattr(
            kwargs.get("document_profile_service"),
            "source_artifact_repository",
            None,
        ) or MemorySourceArtifactRepository()
    paper_fact_repository = kwargs.pop(
        "paper_fact_repository",
        MemoryPaperFactRepository(),
    )
    objective_repository = kwargs.pop(
        "objective_repository",
        MemoryObjectiveRepository(),
    )
    research_understanding_repository = kwargs.pop(
        "research_understanding_repository",
        InMemoryObjectiveUnderstandingRepository(),
    )
    document_profile_service = kwargs.pop("document_profile_service", None)
    if document_profile_service is None:
        document_profile_service = DocumentProfileService(
            collection_service=collection_service,
            source_artifact_repository=source_repository,
            paper_fact_repository=paper_fact_repository,
        )
    research_understanding_service = kwargs.pop(
        "research_understanding_service",
        ResearchUnderstandingService(
            source_artifact_repository=source_repository,
            structured_extractor=kwargs.get("structured_extractor"),
        ),
    )
    return _ResearchObjectiveService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
        objective_repository=objective_repository,
        research_understanding_repository=research_understanding_repository,
        document_profile_service=document_profile_service,
        research_understanding_service=research_understanding_service,
        **kwargs,
    )


def _seed_document_profiles(
    service: _ResearchObjectiveService,
    collection_id: str,
) -> None:
    documents = service.source_artifact_repository.read_collection_artifacts(
        collection_id
    ).documents
    profiles: list[DocumentProfile] = []
    for document in documents:
        metadata = dict(document.metadata)
        title = document.title
        profiles.append(
            DocumentProfile.from_mapping(
                {
                    "document_id": document.document_id,
                    "collection_id": collection_id,
                    "title": title,
                    "source_filename": metadata.get("source_filename"),
                    "doc_type": "review" if "Review" in title else "experimental",
                    "parsing_warnings": [],
                    "confidence": 0.9,
                }
            )
        )
    service.paper_fact_repository.replace_document_profiles(
        collection_id,
        "build_test",
        tuple(profiles),
    )


def test_research_objective_reads_do_not_trigger_generation(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection_id = collection_service.create_collection("Empty objectives")[
        "collection_id"
    ]
    extractor = _ObjectiveExtractor()
    service = _build_research_objective_service(
        collection_service=collection_service,
        structured_extractor=extractor,
    )

    assert service.read_paper_skims(collection_id) == ()
    assert service.read_research_objectives(collection_id) == ()
    assert service.read_objective_contexts(collection_id) == ()
    assert extractor.skim_payloads == []
    assert extractor.discovery_payloads == []


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
        if not isinstance(payload.get("current_source"), dict):
            raise ValueError("objective evidence routing requires current_source")
        candidates = [payload["current_source"]]
        routes: list[StructuredObjectiveEvidenceRoute] = []
        for candidate in candidates:
            if candidate["frame_status"] == "excluded":
                routes.append(
                    StructuredObjectiveEvidenceRoute(
                        role="low_value_or_irrelevant",
                        extractable=False,
                        confidence=0.7,
                    )
                )
                continue
            if candidate["source_kind"] == "text_window":
                routes.append(
                    StructuredObjectiveEvidenceRoute(
                        role="process_or_treatment",
                        extractable=True,
                        confidence=0.72,
                    )
                )
                continue
            table_schema = candidate.get("table_schema") or {}
            column_headers = (
                table_schema.get("column_headers")
                if isinstance(table_schema.get("column_headers"), list)
                else candidate.get("column_headers")
                if isinstance(candidate.get("column_headers"), list)
                else []
            )
            text = " ".join(
                str(value or "")
                for value in (
                    candidate.get("caption_text"),
                    candidate.get("heading_path"),
                    " ".join(column_headers),
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
                    role=role,
                    extractable=True,
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

    def extract_research_understanding_relations(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchUnderstandingRelations:
        return StructuredResearchUnderstandingRelations(relations=[])


class _FailingRouteExtractor(_ObjectiveExtractor):
    def route_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveEvidenceRoutes:
        self.route_payloads.append(payload)
        raise RuntimeError("route model failed")


class _FailingFrameExtractor(_ObjectiveExtractor):
    def frame_objective_paper(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectivePaperFrame:
        self.frame_payloads.append(payload)
        raise RuntimeError("frame model failed")


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


class _CrossObjectiveAxisMergeExtractor(_DuplicateMechanicalObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "How do laser power and scanning speed affect yield "
                        "strength and elongation of SLM 316L stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=[
                        "Selective Laser Melting",
                        "laser power",
                        "scanning speed",
                    ],
                    property_axes=["yield strength", "elongation"],
                    comparison_intent=(
                        "Compare laser power and scanning speed effects on "
                        "mechanical properties."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="mechanical objective",
                ),
                StructuredResearchObjective(
                    question=(
                        "How does porosity influence corrosion potential and "
                        "pitting potential of SLM 316L stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=["Selective Laser Melting", "porosity"],
                    property_axes=["corrosion potential", "pitting potential"],
                    comparison_intent=(
                        "Compare corrosion response across porosity conditions."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="corrosion objective",
                ),
            ]
        )

    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        groups: list[StructuredObjectiveMergeGroup] = []
        for candidate in payload["candidate_objectives"]:
            process_axes = list(candidate["process_axes"])
            if "yield strength" in candidate["property_axes"]:
                process_axes.append("porosity")
            groups.append(
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[candidate["objective_id"]],
                    question=candidate["question"],
                    material_scope=candidate["material_scope"],
                    process_axes=process_axes,
                    property_axes=candidate["property_axes"],
                    comparison_intent=candidate["comparison_intent"],
                    confidence=candidate["confidence"],
                    reason="invalid plan leaks axes between objectives",
                )
            )
        return StructuredObjectiveMergePlan(merged_objectives=groups)


class _UnmatchedSeedObjectiveExtractor(_DuplicateMechanicalObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "How does heat treatment affect yield strength of "
                        "SLM 316L stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=["Selective Laser Melting"],
                    property_axes=["mechanical properties"],
                    comparison_intent="Compare heat-treatment effects on strength.",
                    seed_document_ids=["P002-heat-treatment.pdf"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="model returned a source filename instead of document id",
                )
            ]
        )


class _OverbroadPersistedObjectiveExtractor(_DuplicateMechanicalObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "How do energy density, scanning speed, porosity, heat "
                        "treatment, and scan strategy affect yield strength of "
                        "SLM 316L stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    process_axes=[
                        "Selective Laser Melting",
                        "energy density",
                        "scanning speed",
                        "porosity",
                        "heat treatment",
                        "scan strategy",
                    ],
                    property_axes=["yield strength"],
                    comparison_intent=(
                        "Compare reported yield strength across all process axes."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="persisted objective contains unrelated process axes",
                )
            ]
        )

    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            candidate_materials=["316L stainless steel"],
            candidate_processes=["Selective Laser Melting"],
            candidate_properties=["yield strength"],
            changed_variables=["energy density", "scanning speed"],
            possible_objectives=[
                "How do energy density and scanning speed affect yield strength?"
            ],
            evidence_density="high",
            confidence=0.91,
            warnings=[],
        )

    def extract_objective_evidence_units(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveEvidenceUnits:
        self.unit_payloads.append(payload)
        return StructuredObjectiveEvidenceUnits(
            evidence_units=[
                StructuredObjectiveEvidenceUnit(
                    unit_kind="measurement",
                    property_normalized="yield strength",
                    material_system={"family": "316L stainless steel"},
                    sample_context={"label": "S1"},
                    process_context={
                        "energy density": "100 J/mm3",
                        "scanning speed": "1200 mm/s",
                    },
                    value_payload={"value": 450, "source_value_text": "450 MPa"},
                    unit="MPa",
                    resolution_status="resolved",
                    confidence=0.86,
                )
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_service_continues_after_failed_objective_unit_route(
    tmp_path,
    caplog,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    succeeding_text_route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-2",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.82,
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
            if payload["evidence_route"]["source_ref"] == "block-1":
                raise RuntimeError("malformed objective evidence JSON")
            return StructuredObjectiveEvidenceUnits(
                evidence_units=[
                    StructuredObjectiveEvidenceUnit(
                        unit_kind="measurement",
                        property_normalized="relative density",
                        material_system={"family": "316L stainless steel"},
                        sample_context={"label": "S2"},
                        process_context={"laser_power_w": 220},
                        value_payload={
                            "value": 98.1,
                            "source_value_text": "98.1%",
                        },
                        unit="%",
                        join_keys={"sample_key": "S2"},
                        resolution_status="resolved",
                        confidence=0.88,
                    )
                ]
            )

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
    succeeding_block = SimpleNamespace(
        block_id="block-2",
        document_id="paper-1",
        page=2,
        block_type="paragraph",
        heading_path="Results",
        text="At 220 W, specimen S2 reached a relative density of 98.1%.",
    )

    with caplog.at_level("ERROR"):
        units = service._build_objective_evidence_units(
            collection_id="col-test",
            extractor=extractor,
            objectives=(objective,),
            objective_contexts=(objective_context,),
            objective_paper_frames=(frame,),
            objective_evidence_routes=(
                table_route,
                failing_text_route,
                succeeding_text_route,
            ),
            blocks_by_document_id={"paper-1": [block, succeeding_block]},
            tables_by_document_id={"paper-1": [table]},
            document_trees_by_document_id={},
        )

    measurements = [unit for unit in units if unit.unit_kind == "measurement"]
    assert len(measurements) == 2
    assert {unit.property_normalized for unit in measurements} == {"relative density"}
    assert {unit.value_payload["value"] for unit in measurements} == {98.1, 99.5}
    assert [payload["evidence_route"]["source_ref"] for payload in extractor.unit_payloads] == [
        "block-1",
        "block-2",
    ]
    assert any(
        "Research objective evidence-unit extraction route failed" in record.message
        and failing_text_route.route_id in record.message
        for record in caplog.records
    )


def test_research_objective_table_source_payload_includes_table_cells(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_text_source_payload_uses_document_tree(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods",
            "role": "process_or_treatment",
            "extractable": True,
        }
    )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("methods-section",),
                node_type="document",
                order=0,
            ),
            "methods-section": SourceDocumentNode(
                node_id="methods-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("methods-node",),
                node_type="section",
                order=100,
                title="Methods",
                heading_path=("Methods",),
            ),
            "methods-node": SourceDocumentNode(
                node_id="methods-node",
                document_id="paper-1",
                parent_id="methods-section",
                child_ids=(),
                node_type="paragraph",
                order=110,
                text="The 316L samples used heat treatment at 650 C for 4 h.",
                heading_path=("Methods",),
                source_ref_kind="block",
                source_ref_id="methods",
                page_start=2,
                page_end=2,
            ),
        },
    )

    payload = service._build_objective_route_source_payload(
        route=route,
        blocks=[],
        tables=[],
        document_tree=document_tree,
    )

    assert payload == {
        "source_kind": "text_window",
        "source_ref": "methods",
        "document_id": "paper-1",
        "page": 2,
        "block_type": "paragraph",
        "heading_path": "Methods",
        "text": "The 316L samples used heat treatment at 650 C for 4 h.",
    }


def test_objective_paper_frame_payload_prioritizes_relevant_tree_sections(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-texture-yield",
            "question": (
                "How do scan strategy rotation angle and build orientation angle "
                "affect crystallographic texture and yield strength of LPBF 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": ["scan strategy rotation angle", "build orientation angle"],
            "property_axes": ["crystallographic texture", "yield strength"],
            "confidence": 0.9,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": objective.objective_id,
            "question": objective.question,
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": [
                "scan strategy rotation angle",
                "build orientation angle",
            ],
            "process_context_axes": ["Laser Powder Bed Fusion"],
            "target_property_axes": ["crystallographic texture", "yield strength"],
            "confidence": 0.9,
        }
    )
    child_ids = [f"section-{index}" for index in range(30)]
    child_ids.extend(("texture-section", "yield-section"))
    nodes: dict[str, SourceDocumentNode] = {
        "root": SourceDocumentNode(
            node_id="root",
            document_id="paper-p006",
            parent_id=None,
            child_ids=tuple(child_ids),
            node_type="document",
            order=0,
        )
    }
    for index in range(30):
        section_id = f"section-{index}"
        paragraph_id = f"paragraph-{index}"
        nodes[section_id] = SourceDocumentNode(
            node_id=section_id,
            document_id="paper-p006",
            parent_id="root",
            child_ids=(paragraph_id,),
            node_type="section",
            order=100 + index,
            title=f"Background {index}",
            heading_path=(f"Background {index}",),
        )
        nodes[paragraph_id] = SourceDocumentNode(
            node_id=paragraph_id,
            document_id="paper-p006",
            parent_id=section_id,
            child_ids=(),
            node_type="paragraph",
            order=101 + index,
            text=(
                "General additive-manufacturing background and introduction text "
                "without the active variables."
            ),
            heading_path=(f"Background {index}",),
        )
    nodes["texture-section"] = SourceDocumentNode(
        node_id="texture-section",
        document_id="paper-p006",
        parent_id="root",
        child_ids=("texture-paragraph",),
        node_type="section",
        order=1000,
        title="Texture results",
        heading_path=("Results", "Texture results"),
    )
    nodes["texture-paragraph"] = SourceDocumentNode(
        node_id="texture-paragraph",
        document_id="paper-p006",
        parent_id="texture-section",
        child_ids=(),
        node_type="paragraph",
        order=1001,
        text=(
            "Scan strategy rotation angle and build orientation changed "
            "crystallographic texture intensity in LPBF 316L."
        ),
        heading_path=("Results", "Texture results"),
    )
    nodes["yield-section"] = SourceDocumentNode(
        node_id="yield-section",
        document_id="paper-p006",
        parent_id="root",
        child_ids=("yield-paragraph",),
        node_type="section",
        order=1100,
        title="Tensile properties",
        heading_path=("Results", "Tensile properties"),
    )
    nodes["yield-paragraph"] = SourceDocumentNode(
        node_id="yield-paragraph",
        document_id="paper-p006",
        parent_id="yield-section",
        child_ids=(),
        node_type="paragraph",
        order=1101,
        text=(
            "Build orientation angle changed yield strength and tensile response "
            "for 316L stainless steel."
        ),
        heading_path=("Results", "Tensile properties"),
    )
    document_tree = SourceDocumentTree(
        document_id="paper-p006",
        collection_id="col-test",
        root_node_id="root",
        nodes=nodes,
    )

    payload = service._build_objective_paper_frame_payload(
        collection_id="col-test",
        objective=objective,
        objective_context=objective_context,
        paper_skim=None,
        document=SimpleNamespace(
            document_id="paper-p006",
            title="Mapping the roles of scan strategy and build orientation",
        ),
        profile=None,
        blocks=[],
        tables=[],
        document_tree=document_tree,
    )

    labels = [item["section_label"] for item in payload["section_snippets"]]
    assert "Results > Texture results" in labels
    assert "Results > Tensile properties" in labels
    assert len(labels) <= 12
    assert set(payload["objective_context"]) == {
        "objective_id",
        "question",
        "material_scope",
        "variable_process_axes",
        "process_context_axes",
        "target_property_axes",
        "excluded_property_axes",
        "confidence",
    }
    assert "routing_hints" not in payload["objective_context"]
    assert "objective_evidence_lens" not in payload["objective_context"]
    assert "extraction_guidance" not in payload["objective_context"]


def test_objective_paper_frame_payload_filters_unscored_tables(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-texture-yield",
            "question": (
                "How do scan strategy rotation angle and build orientation angle "
                "affect crystallographic texture and yield strength?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": ["scan strategy rotation angle", "build orientation angle"],
            "property_axes": ["crystallographic texture", "yield strength"],
            "confidence": 0.9,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": objective.objective_id,
            "question": objective.question,
            "variable_process_axes": [
                "scan strategy rotation angle",
                "build orientation angle",
            ],
            "target_property_axes": ["crystallographic texture", "yield strength"],
            "confidence": 0.9,
        }
    )

    payload = service._build_objective_paper_frame_payload(
        collection_id="col-test",
        objective=objective,
        objective_context=objective_context,
        paper_skim=None,
        document=SimpleNamespace(
            document_id="paper-p006",
            title="Mapping the roles of scan strategy and build orientation",
        ),
        profile=None,
        blocks=[],
        tables=[
            SimpleNamespace(
                table_id="tbl-density",
                table_order=1,
                caption_text="VED settings and density.",
                heading_path="Methods",
                column_headers=("VED", "Density"),
                row_count=2,
                col_count=2,
                table_matrix=(("VED", "Density"), ("50", "91.9")),
            ),
            SimpleNamespace(
                table_id="tbl-yield-texture",
                table_order=2,
                caption_text="Build orientation angle, scan strategy rotation angle, texture and yield strength.",
                heading_path="Results",
                column_headers=(
                    "build orientation angle",
                    "scan strategy rotation angle",
                    "texture",
                    "yield strength",
                ),
                row_count=2,
                col_count=4,
                table_matrix=(
                    (
                        "build orientation angle",
                        "scan strategy rotation angle",
                        "texture",
                        "yield strength",
                    ),
                    ("0", "67", "strong", "460"),
                ),
            ),
        ],
        document_tree=None,
    )

    table_ids = [item["table_id"] for item in payload["table_summaries"]]
    assert "tbl-yield-texture" in table_ids
    assert "tbl-density" not in table_ids


def test_deterministic_frame_requires_variable_and_property_axis(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-texture-yield",
            "question": (
                "How do scan strategy rotation angle and build orientation angle "
                "affect crystallographic texture and yield strength?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": ["scan strategy rotation angle", "build orientation angle"],
            "property_axes": ["crystallographic texture", "yield strength"],
            "confidence": 0.9,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": objective.objective_id,
            "question": objective.question,
            "variable_process_axes": [
                "scan strategy rotation angle",
                "build orientation angle",
            ],
            "target_property_axes": ["crystallographic texture", "yield strength"],
            "confidence": 0.9,
        }
    )
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-ved",
            "collection_id": "col-test",
            "doc_role": "experimental",
            "candidate_processes": ["LPBF", "VED"],
            "candidate_properties": ["density"],
            "changed_variables": ["laser power", "scan speed"],
            "evidence_density": "low",
        }
    )

    record = service._build_deterministic_objective_paper_frame_record(
        objective=objective,
        objective_context=objective_context,
        paper_skim=paper_skim,
        payload={
            "document": {
                "document_id": "paper-ved",
                "title": "VED density study",
            },
            "section_snippets": [
                {
                    "section_label": "Results",
                    "text": "Laser power and scan speed changed density.",
                }
            ],
            "table_summaries": [
                {
                    "table_id": "tbl-density",
                    "caption_text": "VED and density.",
                    "column_headers": ["VED", "density"],
                }
            ],
        },
    )

    assert record["relevance"] == "irrelevant"
    assert record["relevant_tables"] == []


def test_research_objective_text_source_payload_resolves_tree_node_to_block(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-node",
            "role": "process_or_treatment",
            "extractable": True,
        }
    )
    block = SimpleNamespace(
        block_id="block-methods",
        page=2,
        block_type="paragraph",
        heading_path="Methods",
        text="The 316L samples used heat treatment at 650 C for 4 h.",
    )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("methods-section",),
                node_type="document",
                order=0,
            ),
            "methods-section": SourceDocumentNode(
                node_id="methods-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("methods-node",),
                node_type="section",
                order=100,
                title="Methods",
                heading_path=("Methods",),
            ),
            "methods-node": SourceDocumentNode(
                node_id="methods-node",
                document_id="paper-1",
                parent_id="methods-section",
                child_ids=(),
                node_type="paragraph",
                order=110,
                heading_path=("Methods",),
                source_ref_kind="block",
                source_ref_id="block-methods",
                page_start=2,
                page_end=2,
            ),
        },
    )

    payload = service._build_objective_route_source_payload(
        route=route,
        blocks=[block],
        tables=[],
        document_tree=document_tree,
    )

    assert payload == {
        "source_kind": "text_window",
        "source_ref": "methods-node",
        "document_id": "paper-1",
        "page": 2,
        "block_type": "paragraph",
        "heading_path": "Methods",
        "text": "The 316L samples used heat treatment at 650 C for 4 h.",
    }


def test_research_objective_prompt_source_uses_cells_without_duplicate_matrix(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    source = {
        "source_kind": "table",
        "source_ref": "table-1",
        "document_id": "paper-1",
        "page": 4,
        "caption_text": "Measured density",
        "heading_path": "Results",
        "column_headers": ["sample", "density"],
        "table_matrix": [["sample", "density"], ["A", "99.6"]],
        "table_cells": [
            {
                "row_index": 1,
                "col_index": 0,
                "header_path": "sample",
                "cell_text": "A",
            }
        ],
    }

    projected = service._objective_evidence_prompt_source(source)

    assert "table_matrix" not in projected
    assert projected["table_cells"] == source["table_cells"]

    fallback = service._objective_evidence_prompt_source(
        {key: value for key, value in source.items() if key != "table_cells"}
    )
    assert fallback["table_matrix"] == [["sample", "density"], ["A", "99.6"]]


def test_research_objective_evidence_units_carry_forward_document_state(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": objective.question,
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["heat treatment"],
            "target_property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
        }
    )
    method_route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods",
            "role": "process_or_treatment",
            "extractable": True,
            "confidence": 0.82,
        }
    )
    result_route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.86,
        }
    )
    blocks = [
        SimpleNamespace(
            block_id="methods",
            document_id="paper-1",
            page=2,
            block_type="paragraph",
            heading_path="Methods",
            text="S1 was aged at 650 C for 4 h.",
        ),
        SimpleNamespace(
            block_id="results",
            document_id="paper-1",
            page=5,
            block_type="paragraph",
            heading_path="Results",
            text="S1 reached a yield strength of 900 MPa.",
        ),
    ]
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("methods-section", "results-section"),
                node_type="document",
                order=0,
            ),
            "methods-section": SourceDocumentNode(
                node_id="methods-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("methods-node",),
                node_type="section",
                order=100,
                title="Methods",
                heading_path=("Methods",),
            ),
            "methods-node": SourceDocumentNode(
                node_id="methods-node",
                document_id="paper-1",
                parent_id="methods-section",
                child_ids=(),
                node_type="paragraph",
                order=110,
                heading_path=("Methods",),
                source_ref_kind="block",
                source_ref_id="methods",
            ),
            "results-section": SourceDocumentNode(
                node_id="results-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("results-node",),
                node_type="section",
                order=200,
                title="Results",
                heading_path=("Results",),
            ),
            "results-node": SourceDocumentNode(
                node_id="results-node",
                document_id="paper-1",
                parent_id="results-section",
                child_ids=(),
                node_type="paragraph",
                order=210,
                heading_path=("Results",),
                source_ref_kind="block",
                source_ref_id="results",
            ),
        },
    )

    class StatefulUnitExtractor:
        def __init__(self) -> None:
            self.unit_payloads: list[dict[str, Any]] = []

        def extract_objective_evidence_units(
            self,
            payload: dict[str, Any],
        ) -> StructuredObjectiveEvidenceUnits:
            self.unit_payloads.append(payload)
            source_ref = payload["evidence_route"]["source_ref"]
            if source_ref == "methods":
                return StructuredObjectiveEvidenceUnits(
                    evidence_units=[
                        StructuredObjectiveEvidenceUnit(
                            unit_kind="process_context",
                            sample_context={"sample": "S1"},
                            process_context={"aging_temperature_c": 650},
                            value_payload={"statement": "S1 aged at 650 C"},
                            join_keys={
                                "sample_key": "S1",
                                "document_id": "paper-1",
                                "objective_id": "obj-heat",
                                "source_ref": "methods",
                                "evidence_route_document_id": "paper-1",
                                "tree_position_node_id": "methods-node",
                            },
                            resolution_status="partial",
                            confidence=0.82,
                        )
                    ]
                )
            state = payload["document_state"]
            process_context = state["process_contexts"][0]["value"]
            return StructuredObjectiveEvidenceUnits(
                evidence_units=[
                    StructuredObjectiveEvidenceUnit(
                        unit_kind="measurement",
                        property_normalized="yield strength",
                        sample_context={"sample": "S1"},
                        process_context=dict(process_context),
                        value_payload={
                            "value": 900,
                            "source_value_text": "900 MPa",
                        },
                        unit="MPa",
                        join_keys={"sample_key": "S1"},
                        resolution_status="resolved",
                        confidence=0.86,
                    )
                ]
            )

    extractor = StatefulUnitExtractor()

    units = service._build_objective_evidence_units(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(objective_context,),
        objective_paper_frames=(frame,),
        objective_evidence_routes=(result_route, method_route),
        blocks_by_document_id={"paper-1": blocks},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert [payload["evidence_route"]["source_ref"] for payload in extractor.unit_payloads] == [
        "methods",
        "results",
    ]
    assert extractor.unit_payloads[0]["tree_position"]["section_path"] == ["Methods"]
    assert extractor.unit_payloads[1]["tree_position"]["section_path"] == ["Results"]
    assert extractor.unit_payloads[0]["document_state"]["evidence_counts_by_kind"] == {}
    assert extractor.unit_payloads[1]["document_state"]["evidence_counts_by_kind"] == {
        "process_context": 1,
    }
    assert extractor.unit_payloads[1]["document_state"]["process_contexts"][0]["value"] == {
        "aging_temperature_c": 650,
    }
    assert extractor.unit_payloads[1]["document_state"]["open_joins"][0][
        "join_keys"
    ] == {"sample_key": "S1"}
    assert extractor.unit_payloads[0]["objective"] == {
        "objective_id": "obj-heat",
        "question": "How does heat treatment affect yield strength?",
        "material_scope": ["316L stainless steel"],
        "process_axes": ["heat treatment"],
        "property_axes": ["yield strength"],
        "comparison_intent": None,
    }
    assert "routing_hints" not in extractor.unit_payloads[0]["objective_context"]
    assert set(extractor.unit_payloads[0]["paper_frame"]) == {
        "frame_id",
        "objective_id",
        "document_id",
        "relevance",
        "paper_role",
        "material_match",
        "changed_variables",
        "measured_property_scope",
        "test_environment_scope",
    }
    measurements = [unit for unit in units if unit.unit_kind == "measurement"]
    assert len(measurements) == 1
    assert measurements[0].process_context == {"aging_temperature_c": 650}


def test_research_objective_evidence_unit_prompt_compacts_long_text_source(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "background": "x" * 1000,
            "relevant_tables": ["table-1"],
            "excluded_tables": ["table-2"],
        }
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "long-results",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.86,
        }
    )
    block = SimpleNamespace(
        block_id="long-results",
        document_id="paper-1",
        page=4,
        block_type="paragraph",
        heading_path="Results",
        text="Yield strength improved after heat treatment. " * 200,
    )

    class PayloadCaptureExtractor:
        def __init__(self) -> None:
            self.unit_payloads: list[dict[str, Any]] = []

        def extract_objective_evidence_units(
            self,
            payload: dict[str, Any],
        ) -> StructuredObjectiveEvidenceUnits:
            self.unit_payloads.append(payload)
            return StructuredObjectiveEvidenceUnits()

    extractor = PayloadCaptureExtractor()

    service._build_objective_evidence_units(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(),
        objective_paper_frames=(frame,),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    payload = extractor.unit_payloads[0]
    assert len(payload["source"]["text"]) <= 1800
    assert "background" not in payload["paper_frame"]
    assert "relevant_tables" not in payload["paper_frame"]
    assert "excluded_tables" not in payload["paper_frame"]


def test_research_objective_tree_state_supports_cross_block_logic_chain(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": objective.question,
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["heat treatment"],
            "target_property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
        }
    )
    routes = (
        ObjectiveEvidenceRoute.from_mapping(
            {
                "objective_id": "obj-heat",
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "discussion",
                "role": "characterization",
                "extractable": True,
                "confidence": 0.84,
            }
        ),
        ObjectiveEvidenceRoute.from_mapping(
            {
                "objective_id": "obj-heat",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-1",
                "role": "current_experimental_evidence",
                "extractable": True,
                "column_roles": {
                    "sample": "sample_id",
                    "heat treatment": "process_variable",
                    "yield strength (MPa)": "target_property",
                },
                "confidence": 0.88,
            }
        ),
        ObjectiveEvidenceRoute.from_mapping(
            {
                "objective_id": "obj-heat",
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "methods",
                "role": "process_or_treatment",
                "extractable": True,
                "confidence": 0.82,
            }
        ),
    )
    blocks = [
        SimpleNamespace(
            block_id="methods",
            document_id="paper-1",
            page=2,
            block_type="paragraph",
            heading_path="Methods",
            text="S1 was heat treated at 650 C for 4 h.",
        ),
        SimpleNamespace(
            block_id="discussion",
            document_id="paper-1",
            page=6,
            block_type="paragraph",
            heading_path="Discussion",
            text="The strength improvement is attributed to the heat treatment.",
        ),
    ]
    table = SimpleNamespace(
        table_id="table-1",
        document_id="paper-1",
        page=5,
        caption_text="Yield strength results",
        heading_path="Results",
        column_headers=["sample", "heat treatment", "yield strength (MPa)"],
        table_matrix=[
            ["sample", "heat treatment", "yield strength (MPa)"],
            ["S1", "650 C for 4 h", "900"],
        ],
    )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("methods-section", "results-section", "discussion-section"),
                node_type="document",
                order=0,
            ),
            "methods-section": SourceDocumentNode(
                node_id="methods-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("methods-node",),
                node_type="section",
                order=100,
                title="Methods",
                heading_path=("Methods",),
            ),
            "methods-node": SourceDocumentNode(
                node_id="methods-node",
                document_id="paper-1",
                parent_id="methods-section",
                child_ids=(),
                node_type="paragraph",
                order=110,
                heading_path=("Methods",),
                source_ref_kind="block",
                source_ref_id="methods",
            ),
            "results-section": SourceDocumentNode(
                node_id="results-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("table-node",),
                node_type="section",
                order=200,
                title="Results",
                heading_path=("Results",),
            ),
            "table-node": SourceDocumentNode(
                node_id="table-node",
                document_id="paper-1",
                parent_id="results-section",
                child_ids=(),
                node_type="table",
                order=210,
                heading_path=("Results",),
                source_ref_kind="table",
                source_ref_id="table-1",
            ),
            "discussion-section": SourceDocumentNode(
                node_id="discussion-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("discussion-node",),
                node_type="section",
                order=300,
                title="Discussion",
                heading_path=("Discussion",),
            ),
            "discussion-node": SourceDocumentNode(
                node_id="discussion-node",
                document_id="paper-1",
                parent_id="discussion-section",
                child_ids=(),
                node_type="paragraph",
                order=310,
                heading_path=("Discussion",),
                source_ref_kind="block",
                source_ref_id="discussion",
            ),
        },
    )

    class ChainExtractor:
        def __init__(self) -> None:
            self.unit_payloads: list[dict[str, Any]] = []

        def extract_objective_evidence_units(
            self,
            payload: dict[str, Any],
        ) -> StructuredObjectiveEvidenceUnits:
            self.unit_payloads.append(payload)
            source_ref = payload["evidence_route"]["source_ref"]
            if source_ref == "methods":
                return StructuredObjectiveEvidenceUnits(
                    evidence_units=[
                        StructuredObjectiveEvidenceUnit(
                            unit_kind="process_context",
                            sample_context={"sample": "S1"},
                            process_context={"heat_treatment": "650 C for 4 h"},
                            join_keys={"sample_key": "S1"},
                            resolution_status="partial",
                            confidence=0.82,
                        )
                    ]
                )
            if source_ref == "discussion":
                assert payload["document_state"]["process_contexts"][0]["value"] == {
                    "heat_treatment": "650 C for 4 h",
                }
                return StructuredObjectiveEvidenceUnits(
                    evidence_units=[
                        StructuredObjectiveEvidenceUnit(
                            unit_kind="interpretation",
                            sample_context={"sample": "S1"},
                            process_context={
                                "heat_treatment": "650 C for 4 h",
                            },
                            interpretation=(
                                "Strength improvement is attributed to heat treatment."
                            ),
                            value_payload={"mechanism": "heat treatment response"},
                            join_keys={"sample_key": "S1"},
                            resolution_status="resolved",
                            confidence=0.84,
                        )
                    ]
                )
            return StructuredObjectiveEvidenceUnits()

    extractor = ChainExtractor()

    units = service._build_objective_evidence_units(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(objective_context,),
        objective_paper_frames=(frame,),
        objective_evidence_routes=routes,
        blocks_by_document_id={"paper-1": blocks},
        tables_by_document_id={"paper-1": [table]},
        document_trees_by_document_id={"paper-1": document_tree},
    )
    chains = service._build_objective_logic_chains(
        collection_id="col-test",
        objectives=(objective,),
        objective_contexts=(objective_context,),
        objective_evidence_units=units,
    )

    assert [payload["evidence_route"]["source_ref"] for payload in extractor.unit_payloads] == [
        "methods",
        "discussion",
    ]
    measurement = next(unit for unit in units if unit.unit_kind == "measurement")
    assert measurement.process_context["heat_treatment"] == "650 C for 4 h"
    assert measurement.value_payload["value"] == 900.0
    chain_payload = chains[0].chain_payload
    paper_chain = chain_payload["paper_chains"][0]
    assert paper_chain["sample_and_process_contexts"]
    assert paper_chain["measurement_results"]
    assert paper_chain["author_interpretations"]
    assert chain_payload["cross_paper"]["resolved_measurement_count"] == 1
    assert chain_payload["evidence_unit_ids_by_role"]["interpretations"]


def test_research_objective_fragmented_table_cells_repair_table_matrix_before_extraction(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
        column_headers=[
            "Specimens",
            "Type of heat treatment",
            "Laser power (W)",
            "Scan speed (mm/s)",
            "Laser energy density (J/ mm 3 )",
            "Density (%)",
        ],
        table_matrix=[
            [
                "Specimens",
                "Type of heat treatment",
                "Laser power (W)",
                "Scan speed (mm/s)",
                "Laser energy density (J/ mm 3 )",
                "Density (%)",
            ],
            ["as-SLM (100/", "-", "100", "100", "278", "97.83"],
            ["100) HT-SLM (100/", "Furnace HT", "100", "100", "278", "98.70"],
            ["100) HIP-SLM (100/", "HIP", "100", "100", "278", "98.15"],
        ],
    )
    table_cells = [
        SimpleNamespace(
            table_id="table-1",
            row_index=1,
            col_index=0,
            header_path="Specimens",
            cell_text="as-SLM (100/",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=1,
            col_index=1,
            header_path="Type of heat treatment",
            cell_text="-",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=2,
            col_index=0,
            header_path="Specimens",
            cell_text="100) HT-SLM (100/",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=2,
            col_index=1,
            header_path="Type of heat treatment",
            cell_text="Furnace HT",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=3,
            col_index=0,
            header_path="Specimens",
            cell_text="100) HIP-SLM (100/",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=3,
            col_index=1,
            header_path="Type of heat treatment",
            cell_text="HIP",
        ),
    ]

    class TableMatrixRepairExtractor:
        def __init__(self) -> None:
            self.repair_payloads: list[dict[str, Any]] = []
            self.unit_payloads: list[dict[str, Any]] = []

        def repair_table_matrix(
            self,
            payload: dict[str, Any],
        ) -> StructuredTableMatrixRepair:
            self.repair_payloads.append(payload)
            return StructuredTableMatrixRepair(
                repaired_table_matrix=[
                    [
                        "Specimens",
                        "Type of heat treatment",
                        "Laser power (W)",
                        "Scan speed (mm/s)",
                        "Laser energy density (J/ mm 3 )",
                        "Density (%)",
                    ],
                    ["as-SLM (100/100)", "-", "100", "100", "278", "97.83"],
                    [
                        "100) HT-SLM (100/100)",
                        "Furnace HT",
                        "100",
                        "100",
                        "278",
                        "98.70",
                    ],
                    [
                        "100) HIP-SLM (100/100)",
                        "HIP",
                        "100",
                        "100",
                        "278",
                        "98.15",
                    ],
                ],
                confidence=0.88,
            )

        def extract_objective_evidence_units(
            self,
            payload: dict[str, Any],
        ) -> StructuredObjectiveEvidenceUnits:
            self.unit_payloads.append(payload)
            return StructuredObjectiveEvidenceUnits()

    extractor = TableMatrixRepairExtractor()

    units = service._build_objective_evidence_units(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(objective_context,),
        objective_paper_frames=(frame,),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": [table]},
        document_trees_by_document_id={},
        table_cells_by_document_id={"paper-1": table_cells},
    )

    assert len(extractor.repair_payloads) == 1
    repair_payload = extractor.repair_payloads[0]
    assert set(repair_payload) == {"table_role", "repair_focus", "source"}
    assert "objective" not in repair_payload
    assert "paper_frame" not in repair_payload
    assert "evidence_route" not in repair_payload
    assert repair_payload["source"]["table_cells"][0] == {
        "row_index": 1,
        "col_index": 0,
        "header_path": "Specimens",
        "cell_text": "as-SLM (100/",
    }
    assert all(
        cell["col_index"] == 0
        for cell in repair_payload["source"]["table_cells"]
    )
    assert extractor.unit_payloads == []
    measurements = [unit for unit in units if unit.unit_kind == "measurement"]
    assert len(measurements) == 3
    assert {unit.value_payload.get("value") for unit in measurements} == {
        97.83,
        98.70,
        98.15,
    }
    sample_labels = {
        str(unit.sample_context.get("Specimens") or "")
        for unit in measurements
    }
    assert sample_labels == {
        "as-SLM (100/100)",
        "HT-SLM (100/100)",
        "HIP-SLM (100/100)",
    }
    assert all(
        "100) HT-SLM" not in label and "100) HIP-SLM" not in label
        for label in sample_labels
    )
    assert all(
        unit.material_system == {"family": "316L stainless steel"}
        for unit in measurements
    )
    assert all(
        "(100/" not in str(unit.sample_context.get("Specimens") or "")
        or str(unit.sample_context.get("Specimens") or "").endswith("(100/100)")
        for unit in measurements
    )


def test_research_objective_fragmented_table_matrix_triggers_structural_repair(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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

    assert service._objective_table_source_needs_llm_structural_repair(
        route=route,
        source={
            "table_matrix": [
                ["Specimens", "Density (%)"],
                ["100) HIP-SLM (100/", "98.15"],
            ],
            "table_cells": [],
        },
    )


def test_research_objective_service_inherits_single_objective_material(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "material_scope": ["316L stainless steel"],
        }
    )
    units = (
        ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": "oeu-missing-material",
                "objective_id": "obj-mechanical",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "yield strength",
                "value_payload": {"value": 236.65},
                "resolution_status": "resolved",
            }
        ),
        ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": "oeu-explicit-material",
                "objective_id": "obj-mechanical",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "material_system": {"family": "AISI 316L stainless steel"},
                "property_normalized": "yield strength",
                "value_payload": {"value": 159.97},
                "resolution_status": "resolved",
            }
        ),
    )

    resolved = service._inherit_objective_material_systems(
        units,
        objective_contexts=(objective_context,),
    )

    assert resolved[0].material_system == {"family": "316L stainless steel"}
    assert resolved[1].material_system == {
        "family": "AISI 316L stainless steel"
    }


def test_research_objective_service_does_not_inherit_ambiguous_material(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-multi-material",
            "material_scope": ["316L stainless steel", "Ti-6Al-4V"],
        }
    )
    unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-missing-material",
            "objective_id": "obj-multi-material",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "value_payload": {"value": 236.65},
            "resolution_status": "resolved",
        }
    )

    resolved = service._inherit_objective_material_systems(
        (unit,),
        objective_contexts=(objective_context,),
    )

    assert resolved[0].material_system == {}


def test_research_objective_service_normalizes_result_table_values_to_measurements(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_service_keeps_process_label_numbers_out_of_text_measurements(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "blk-elongation",
            "role": "characterization",
            "extractable": True,
            "confidence": 0.72,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "target_property_axes": ["elongation"],
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 8, "text": "Ductility increased for the low-porosity sample."},
        objective_context=objective_context,
        extracted_record={
            "unit_kind": "measurement",
            "property_normalized": "elongation",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "135 W-750 mm·s -1"},
            "value_payload": {
                "source_value_text": (
                    "The relatively low porosity levels in the 135 W-750 "
                    "mm·s -1 sample increase the ductility by about 10%."
                )
            },
            "unit": "%",
            "resolution_status": "partial",
        },
    )

    assert len(records) == 1
    assert records[0]["unit_kind"] == "interpretation"
    assert records[0]["property_normalized"] == "elongation"
    assert "value" not in records[0]["value_payload"]


def test_research_objective_service_carries_route_evidence_role_to_source_refs(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "blk-lof-defects",
            "role": "characterization",
            "extractable": True,
            "join_plan": {"evidence_role": "mediator_context"},
            "confidence": 0.72,
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={
            "page": 6,
            "text": "LoF defects located at melt pool boundaries were observed.",
        },
        objective_context=ObjectiveContext.from_mapping(
            {
                "objective_id": "obj-corrosion",
                "target_property_axes": ["pitting corrosion behavior"],
            }
        ),
        extracted_record={
            "unit_kind": "characterization",
            "property_normalized": "lack of fusion defects",
            "value_payload": {
                "summary": "LoF defects located at melt pool boundaries were observed.",
            },
            "resolution_status": "resolved",
        },
    )

    assert records[0]["source_refs"][0]["evidence_role"] == "mediator_context"


def test_research_objective_service_reads_evidence_role_from_unit_source():
    unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-lof",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "characterization",
            "property_normalized": "lack of fusion defects",
            "value_payload": {
                "summary": "LoF defects located at melt pool boundaries were observed.",
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "blk-lof-defects",
                    "role": "characterization",
                    "evidence_role": "mediator_context",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.84,
        }
    )

    assert unit.evidence_role == "mediator_context"


def test_research_objective_service_uses_main_number_after_leading_uncertainty(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_service_keeps_unrole_result_table_case_as_sample_key(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
                "Yield Strength Experiment (MPa)": "target_property",
                "Yield Strength Prediction (MPa)": "target_property",
            },
            "confidence": 0.84,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-texture",
            "variable_process_axes": [
                "scan strategy rotation angle",
                "build orientation angle",
            ],
            "target_property_axes": ["yield strength"],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        source={
            "page": 9,
            "column_headers": [
                "Case",
                "Yield Strength Experiment (MPa)",
                "Yield Strength Prediction (MPa)",
            ],
            "table_matrix": [
                [
                    "Case",
                    "Yield Strength Experiment (MPa)",
                    "Yield Strength Prediction (MPa)",
                ],
                ["4", "351.9", "345.64"],
            ],
        },
        objective_context=objective_context,
    )

    assert len(records) == 2
    assert {record["property_normalized"] for record in records} == {
        "yield strength experiment",
        "yield strength prediction",
    }
    assert all(record["sample_context"] == {"Case": "4"} for record in records)
    assert all(record["join_keys"] == {"case": "4"} for record in records)


def test_research_objective_service_expands_fatigue_and_defect_result_columns(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-fatigue",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-5",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Printed 316L": "sample_id",
                "FAT50 % [MPa]": "target_property",
                "FAT at 10 4 cycles [MPa]": "target_property",
                "Max. Defect length (LCSM) [ μ m]": "target_property",
            },
            "confidence": 0.84,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-fatigue",
            "variable_process_axes": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
                "hatch spacing",
                "layer thickness",
            ],
            "target_property_axes": ["defect structure", "fatigue strength"],
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=route,
        source={
            "page": 10,
            "column_headers": [
                "Printed 316L",
                "UTS [MPa]",
                "FAT50 % [MPa]",
                "FAT/ UTS -",
                "FAT at 10 4 cycles [MPa]",
                "Max. Defect length (LCSM) [ μ m]",
            ],
            "table_matrix": [
                [
                    "Printed 316L",
                    "UTS [MPa]",
                    "FAT50 % [MPa]",
                    "FAT/ UTS -",
                    "FAT at 10 4 cycles [MPa]",
                    "Max. Defect length (LCSM) [ μ m]",
                ],
                ["L-VED", "610 ± 6", "93", "0.15", "340", "394"],
            ],
        },
        objective_context=objective_context,
    )

    values_by_property = {
        record["property_normalized"]: record["value_payload"]["value"]
        for record in records
    }
    assert values_by_property == {
        "fatigue strength": 340.0,
        "fatigue limit": 93.0,
        "max defect length": 394.0,
    }
    assert all(record["sample_context"] == {"Printed 316L": "L-VED"} for record in records)


def test_research_objective_service_uses_role_aliases_for_result_process_context(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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

    assert service._objective_table_route_should_skip_llm_fallback(route)
    assert service._objective_table_route_should_skip_llm_fallback(corrosion_route)

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

    assert service._objective_table_route_should_skip_llm_fallback(eis_route)


def test_research_objective_service_builds_method_conditions_and_binds_measurements(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_service_expands_mapped_density_interpretation(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-density",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.72,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-density",
            "question": "How do laser power and scan speed affect density?",
            "target_property_axes": ["density"],
        }
    )

    records = service._objective_evidence_unit_records_from_extracted(
        route=route,
        source={"page": 3},
        objective_context=objective_context,
        extracted_record={
            "unit_kind": "interpretation",
            "property_normalized": "density",
            "value_payload": {
                "375W-2100mm/s": "97.83%",
                "255W-1400mm/s": "99.5%",
                "135W-750mm/s": "99.26%",
            },
            "resolution_status": "resolved",
        },
    )

    assert [record["unit_kind"] for record in records] == [
        "measurement",
        "measurement",
        "measurement",
    ]
    assert [record["property_normalized"] for record in records] == [
        "density",
        "density",
        "density",
    ]
    assert [record["value_payload"]["value"] for record in records] == [
        97.83,
        99.5,
        99.26,
    ]


def test_research_objective_service_expands_mapped_numeric_text_measurements(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_service_expands_source_text_density_measurements_when_model_misclassifies_unit(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
            "unit_kind": "process_context",
            "property_normalized": "microstructure",
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_service_builds_objective_evidence_lens(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-corrosion",
            "question": (
                "How do laser power, porosity, and pore size affect pitting "
                "corrosion behavior of SLM 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": ["laser power", "SLM"],
            "property_axes": ["pitting potential"],
        }
    )

    lens = service._build_objective_evidence_lens(
        objective=objective,
        variable_process_axes=["laser power"],
        process_context_axes=["SLM"],
        target_property_axes=["pitting potential"],
        excluded_property_axes=["yield strength"],
    )

    assert lens["target_outcome_axes"] == ["pitting potential"]
    assert lens["mediator_axes"] == ["porosity", "pore", "pore size"]
    assert lens["variable_process_axes"] == ["laser power"]
    assert lens["context_axes"] == ["316L stainless steel", "SLM"]
    assert lens["excluded_axes"] == ["yield strength"]
    assert any("target_outcome_axis" in rule for rule in lens["direct_support_rules"])
    assert any("Mediator axes" in rule for rule in lens["direct_support_rules"])


def test_research_objective_service_routes_matching_tables_beyond_seed_documents(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-density",
            "question": "How does volumetric energy density affect density?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["volumetric energy density"],
            "property_axes": ["density"],
            "seed_document_ids": ["paper-seed"],
        }
    )

    hints = service._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-seed-density",
                document_id="paper-seed",
                caption_text="Density results for the seed paper.",
                column_headers=("VED [J/mm3]", "Density [%]"),
                table_matrix=(("L-VED", "91.9"),),
            ),
            SimpleNamespace(
                table_id="tbl-independent-density",
                document_id="paper-independent",
                caption_text="Independent density results at different VEDs.",
                column_headers=("VED [J/mm3]", "Density [%]"),
                table_matrix=(("L-VED", "91.90"), ("H-VED", "99.60")),
            ),
        ),
        target_property_axes=["density"],
        variable_process_axes=["volumetric energy density"],
    )

    assert {
        (hint["document_id"], hint["table_id"], hint["role"])
        for hint in hints
    } == {
        ("paper-seed", "tbl-seed-density", "result_table"),
        (
            "paper-independent",
            "tbl-independent-density",
            "result_table",
        ),
    }


def test_research_objective_service_does_not_route_single_letter_acronym_tables(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-density",
            "question": "How does scan speed affect density?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["scan speed"],
            "property_axes": ["density"],
        }
    )

    hints = service._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-composition",
                document_id="paper-1",
                caption_text="Chemical composition of SS316L powder.",
                column_headers=("C", "Cr", "Ni", "P", "S", "Fe"),
                table_matrix=(("0.02", "16.7", "11.9", "0.01", "0.02", "Bal."),),
            ),
            SimpleNamespace(
                table_id="tbl-polarization",
                document_id="paper-1",
                caption_text="Electrochemical polarization parameters.",
                column_headers=("Sample", "E corr", "E d", "E p"),
                table_matrix=(("sample-1", "-312.9", "-208.0", "124.7"),),
            ),
        ),
        target_property_axes=["density"],
        variable_process_axes=["scan speed"],
    )

    assert hints == []


def test_research_objective_service_treats_energy_density_only_table_as_condition(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-density",
            "question": "How do laser power and scan speed affect density?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["laser power", "scan speed"],
            "property_axes": ["density"],
        }
    )

    hints = service._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-process",
                document_id="paper-1",
                caption_text="SLM process parameters.",
                column_headers=(
                    "Laser power [W]",
                    "Scan speed [mm/s]",
                    "Energy density [J/mm3]",
                ),
                table_matrix=(("375", "2100", "100"),),
            ),
        ),
        target_property_axes=["density"],
        variable_process_axes=["laser power", "scan speed"],
    )

    assert len(hints) == 1
    assert hints[0]["role"] == "condition_context"
    assert hints[0]["matched_property_axes"] == []


def test_research_objective_service_normalizes_archimedes_density_column(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-density",
            "question": "How does volumetric energy density affect density?",
            "target_property_axes": ["density"],
        }
    )

    normalized = service._normalize_objective_unit_property(
        "Density [%] > Archimedes ' method",
        objective_context=objective_context,
    )

    assert normalized == "density"


def test_research_objective_service_ignores_analysis_purpose_as_table_result(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-microstructure",
            "question": "How does heat treatment affect microstructure?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["microstructure"],
        }
    )

    hints = service._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-sample-angles",
                document_id="paper-1",
                caption_text=(
                    "Scan strategy and build orientation of cubes for "
                    "microstructure analysis."
                ),
                column_headers=("Sample", "rotation angle", "build orientation"),
                table_matrix=(("1", "0", "0"), ("2", "15", "0")),
            ),
        ),
        target_property_axes=["microstructure"],
        variable_process_axes=["heat treatment"],
    )

    assert hints == []


def test_research_objective_service_recovers_non_seed_condition_and_result_routes(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "question": "How do LPBF parameters affect tensile properties?",
            "material_scope": ["316L stainless steel"],
            "process_axes": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
                "hatch spacing",
            ],
            "property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
            "seed_document_ids": ["paper-seed"],
        }
    )
    condition_table = SimpleNamespace(
        table_id="table-conditions",
        document_id="paper-independent",
        caption_text="Fabrication parameters for samples with varying VED.",
        heading_path="Materials and methods",
        column_headers=(
            "ID",
            "Volumetric energy density [J/mm3]",
            "Laser power [W]",
            "Scanning speed [mm/s]",
            "Hatch spacing [um]",
        ),
        row_count=3,
        col_count=5,
        table_matrix=(
            ("L-VED", "50.8", "160", "875", "120"),
            ("H-VED", "84.3", "220", "725", "120"),
        ),
    )
    result_table = SimpleNamespace(
        table_id="table-results",
        document_id="paper-independent",
        caption_text="Tensile properties for samples printed at different VEDs.",
        heading_path="Results",
        column_headers=(
            "Printed 316L",
            "Yield strength [MPa]",
            "Ultimate tensile strength [MPa]",
            "Total elongation [%]",
        ),
        row_count=3,
        col_count=4,
        table_matrix=(
            ("L-VED", "462", "610", "33.2"),
            ("H-VED", "437", "560", "48.3"),
        ),
    )
    hints = service._build_objective_table_routing_hints(
        objective,
        tables=(condition_table, result_table),
        target_property_axes=list(objective.property_axes),
        variable_process_axes=list(objective.process_axes),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": objective.objective_id,
            "question": objective.question,
            "material_scope": list(objective.material_scope),
            "variable_process_axes": list(objective.process_axes),
            "target_property_axes": list(objective.property_axes),
            "routing_hints": hints,
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-independent",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": list(objective.process_axes),
            "measured_property_scope": list(objective.property_axes),
            "relevant_tables": [],
            "excluded_tables": ["table-conditions", "table-results"],
        }
    )

    routes = service._build_objective_evidence_routes(
        collection_id="col-test",
        extractor=_ObjectiveExtractor(),
        objectives=(objective,),
        objective_contexts=(objective_context,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-independent": []},
        tables_by_document_id={
            "paper-independent": [condition_table, result_table]
        },
        document_trees_by_document_id={},
    )

    active_routes = {
        (route.source_ref, route.role)
        for route in routes
        if route.extractable
    }
    assert active_routes == {
        ("table-conditions", "process_or_treatment"),
        ("table-results", "current_experimental_evidence"),
    }


def test_research_objective_service_routes_pitting_corrosion_metric_tables_as_results(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-corrosion",
            "question": (
                "How do laser power and energy density affect pitting corrosion "
                "behavior of SLM 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": ["laser power", "energy density"],
            "property_axes": ["pitting corrosion behavior"],
        }
    )

    hints = service._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-electrochemical",
                document_id="paper-1",
                caption_text=(
                    "Table 3 Electrochemical parameters results obtained from "
                    "the polarization test"
                ),
                column_headers=(
                    "Sample",
                    "E corr (mV)",
                    "E d (mV)",
                    "E p (mV)",
                    "E p - E d (mV)",
                ),
                table_matrix=(
                    ("Sample", "E corr (mV)", "E p (mV)"),
                    ("375 W-2100 mm·s -1", "-312.9", "124.7"),
                ),
            ),
            SimpleNamespace(
                table_id="tbl-eis",
                document_id="paper-1",
                caption_text="Table 4 Fitted parameters obtained from the EIS plots",
                column_headers=("Sample", "R s (Ω cm 2 )", "R film (Ω cm 2 )"),
                table_matrix=(
                    ("Sample", "R s (Ω cm 2 )", "R film (Ω cm 2 )"),
                    ("135 W-750 mm·s -1", "5.21", "1.90×10 5"),
                ),
            ),
        ),
        target_property_axes=["pitting corrosion behavior"],
        variable_process_axes=["laser power", "energy density"],
    )

    assert {
        (hint["table_id"], hint["role"], tuple(hint["matched_property_axes"]))
        for hint in hints
    } == {
        ("tbl-electrochemical", "result_table", ("pitting corrosion behavior",)),
        ("tbl-eis", "result_table", ("pitting corrosion behavior",)),
    }


def test_research_objective_service_keeps_density_out_of_defect_structure_results(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-fatigue",
            "question": (
                "How does volumetric energy density affect defect structure and "
                "fatigue strength of LPBF 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": ["volumetric energy density"],
            "property_axes": ["defect structure", "fatigue strength"],
        }
    )

    hints = service._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-density",
                document_id="paper-1",
                caption_text="Table 1 SLM processing parameters and relative densities.",
                column_headers=("VED", "Relative density"),
                table_matrix=(
                    ("VED", "Relative density"),
                    ("50", "91.9"),
                    ("100", "98.9"),
                ),
            ),
        ),
        target_property_axes=["defect structure", "fatigue strength"],
        variable_process_axes=["volumetric energy density"],
    )

    assert all(hint["role"] != "result_table" for hint in hints)


def test_research_objective_service_route_payload_includes_objective_evidence_lens(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-corrosion",
            "question": "How does porosity affect pitting corrosion?",
            "target_property_axes": ["pitting potential"],
            "objective_evidence_lens": {
                "target_outcome_axes": ["pitting potential"],
                "mediator_axes": ["porosity"],
                "variable_process_axes": [],
                "context_axes": ["316L stainless steel"],
                "excluded_axes": [],
                "direct_support_rules": [
                    "Direct support must explicitly report a target outcome."
                ],
            },
        }
    )

    payload = service._route_prompt_objective_context_record(context)

    assert payload["objective_evidence_lens"]["target_outcome_axes"] == [
        "pitting potential"
    ]
    assert payload["objective_evidence_lens"]["mediator_axes"] == ["porosity"]


def test_research_objective_service_adds_sample_numbers_to_process_table_rows(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-mechanical-results",
                    "evidence_role": "direct_support",
                }
            ],
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
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-process-conditions",
                    "evidence_role": "background_context",
                }
            ],
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
    assert resolved_measurement.source_refs == (
        {
            "source_kind": "table",
            "source_ref": "table-mechanical-results",
            "evidence_role": "direct_support",
        },
        {
            "source_kind": "table",
            "source_ref": "table-process-conditions",
            "evidence_role": "condition_context",
        },
    )
    assert resolved_measurement.resolution_status == "resolved"


def test_research_objective_service_resolves_case_measurements_from_sample_number_process_units(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-yield-case-4",
            "objective_id": "obj-texture",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {"Case": "4"},
            "value_payload": {
                "source_value_text": "351.9",
                "value": 351.9,
            },
            "unit": "MPa",
            "resolution_status": "partial",
            "confidence": 0.84,
        }
    )
    process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-angle-sample-4",
            "objective_id": "obj-texture",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {"Sample #": "4"},
            "process_context": {
                "α ( ◦ )": "0",
                "β ( ◦ )": "22.5",
                "ɵ ( ◦ )": "45",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )

    resolved_units = service._resolve_objective_evidence_unit_contexts(
        (measurement, process_context),
    )

    resolved_measurement = resolved_units[0]
    assert resolved_measurement.process_context == {
        "α ( ◦ )": "0",
        "β ( ◦ )": "22.5",
        "ɵ ( ◦ )": "45",
    }
    assert resolved_measurement.resolution_status == "resolved"
    assert resolved_measurement.resolved_condition == {
        "context_unit_id": "oeu-angle-sample-4",
        "matched_sample_context": {"Sample #": "4"},
    }


def test_research_objective_service_resolves_measurements_from_process_label(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_service_matches_all_unique_specimen_numbers(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-elongation-hip-140-100",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "elongation",
            "sample_context": {"Specimens": "HIP-SLM (140/100)"},
            "value_payload": {
                "source_value_text": "52.7 ( +/- 3.6)",
                "value": 52.7,
            },
            "unit": "%",
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    wrong_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-hip-100-100",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {"Specimens": "100) HIP-SLM (100/"},
            "process_context": {
                "Laser energy density (J/mm3)": "278",
                "Laser power (W)": "100",
                "Scan speed (mm/s)": "100",
                "Type of heat treatment": "HIP",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )
    matching_process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-hip-140-100",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {"Specimens": "100) HIP-SLM"},
            "process_context": {
                "Laser energy density (J/mm3)": "389",
                "Laser power (W)": "140",
                "Scan speed (mm/s)": "100",
                "Type of heat treatment": "HIP",
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )

    resolved_units = service._resolve_objective_evidence_unit_contexts(
        (measurement, wrong_process_context, matching_process_context),
    )

    resolved_measurement = resolved_units[0]
    assert resolved_measurement.process_context["Laser power (W)"] == "140"
    assert resolved_measurement.process_context["Laser energy density (J/mm3)"] == "389"
    assert resolved_measurement.resolved_condition == {
        "context_unit_id": "oeu-process-hip-140-100",
        "matched_sample_context": {"Specimens": "100) HIP-SLM"},
    }


def test_research_objective_service_prefers_descriptive_label_over_row_number_context(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_pairwise_selection_keeps_valid_pairs_when_non_objective_axes_define_groups(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-density",
            "question": "How does scan speed affect density?",
            "variable_process_axes": ["scan speed"],
            "target_property_axes": ["density"],
        }
    )

    def density_unit(
        evidence_unit_id: str,
        *,
        sample_number: str,
        hatch_spacing: str,
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
                "sample_context": {"Sample number": sample_number},
                "process_context": {
                    "Hatch space (mm)": hatch_spacing,
                    "Scan strategy": "A",
                    "Scanning speed (mm/s)": scan_speed,
                },
                "value_payload": {
                    "source_value_text": str(density),
                    "value": density,
                },
                "unit": "%",
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-density",
                        "page": 2,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparisons = service._build_objective_pairwise_comparison_units(
        (
            density_unit(
                "oeu-density-1",
                sample_number="1",
                hatch_spacing="0.114",
                scan_speed="0.25",
                density=95.4,
            ),
            density_unit(
                "oeu-density-4",
                sample_number="4",
                hatch_spacing="0.114",
                scan_speed="0.175",
                density=93.9,
            ),
            density_unit(
                "oeu-density-8",
                sample_number="8",
                hatch_spacing="0.12",
                scan_speed="0.239",
                density=96.8,
            ),
            density_unit(
                "oeu-density-11",
                sample_number="11",
                hatch_spacing="0.12",
                scan_speed="0.167",
                density=96.2,
            ),
        ),
        objective_contexts=(objective_context,),
    )

    assert {
        frozenset(
            {
                unit.sample_context["Sample number"],
                unit.baseline_context["sample_context"]["Sample number"],
            }
        )
        for unit in comparisons
    } == {frozenset({"1", "4"}), frozenset({"8", "11"})}
    assert {unit.value_payload["comparison_axis"] for unit in comparisons} == {
        "scan speed"
    }
    assert {
        tuple(
            (item["axis"], item["value"])
            for item in unit.value_payload["controlled_axes"]
        )
        for unit in comparisons
    } == {
        (("hatch space", "0.114"), ("scan strategy", "a")),
        (("hatch space", "0.12"), ("scan strategy", "a")),
    }


def test_research_objective_service_matches_contextual_property_variants_for_pairwise(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_service_generates_pairwise_from_symbol_angle_axes(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-texture",
            "variable_process_axes": [
                "scan strategy rotation angle",
                "build orientation angle",
            ],
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
                "objective_id": "obj-texture",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "yield strength",
                "sample_context": {"sample_number": sample_number},
                "process_context": {
                    "α ( ◦ )": "0",
                    "β ( ◦ )": "0",
                    "ɵ ( ◦ )": theta,
                },
                "value_payload": {"source_value_text": str(value), "value": value},
                "unit": "MPa",
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-angles",
                        "page": 8,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparison_units = service._build_objective_pairwise_comparison_units(
        (
            measurement("oeu-yield-1", sample_number="1", theta="0", value=342.5),
            measurement("oeu-yield-7", sample_number="7", theta="90", value=410.2),
        ),
        objective_contexts=(objective_context,),
    )

    assert len(comparison_units) == 1
    assert comparison_units[0].value_payload["comparison_axis"] == "ɵ"
    assert comparison_units[0].sample_context["sample_number"] == "7"
    assert comparison_units[0].baseline_context["sample_context"]["sample_number"] == "1"


def test_research_objective_service_selects_large_grid_pairs_from_raw_angle_axes(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_service_skips_pair_when_unmodeled_hatch_spacing_changes(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "variable_process_axes": [
                "scanning strategy",
                "scanning speed",
                "energy density",
            ],
            "target_property_axes": ["elongation"],
        }
    )

    def elongation_unit(
        evidence_unit_id: str,
        *,
        sample_number: str,
        scan_speed: str,
        hatch_spacing: str,
        value: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-mechanical",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "elongation",
                "sample_context": {"Sample number": sample_number},
                "process_context": {
                    "Energy density (J/mm3)": "150",
                    "Hatch space (mm)": hatch_spacing,
                    "Scan strategy": "A",
                    "Scanning speed (mm/s)": scan_speed,
                },
                "value_payload": {
                    "source_value_text": str(value),
                    "value": value,
                },
                "unit": "%",
                "resolution_status": "resolved",
                "confidence": 0.8,
            }
        )

    comparison_units = service._build_objective_pairwise_comparison_units(
        (
            elongation_unit(
                "oeu-elongation-5",
                sample_number="5",
                scan_speed="0.12",
                hatch_spacing="0.111",
                value=6.4,
            ),
            elongation_unit(
                "oeu-elongation-14",
                sample_number="14",
                scan_speed="0.111",
                hatch_spacing="0.12",
                value=41.9,
            ),
        ),
        objective_contexts=(objective_context,),
    )

    assert comparison_units == ()


def test_research_objective_service_skips_pair_when_treatment_and_energy_input_change(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "variable_process_axes": ["energy density", "scanning speed"],
            "target_property_axes": ["yield strength"],
        }
    )

    def yield_unit(
        evidence_unit_id: str,
        *,
        specimen: str,
        energy_density: str,
        laser_power: str,
        treatment: str,
        value: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-mechanical",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "yield strength",
                "sample_context": {"Specimens": specimen},
                "process_context": {
                    "Laser energy density (J/mm3)": energy_density,
                    "Laser power (W)": laser_power,
                    "Scan speed (mm/s)": "200",
                    "Type of heat treatment": treatment,
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
            yield_unit(
                "oeu-yield-as-slm",
                specimen="as-SLM(140/200)",
                energy_density="194",
                laser_power="140",
                treatment="-",
                value=426.7,
            ),
            yield_unit(
                "oeu-yield-hip-slm",
                specimen="HIP-SLM(120/200)",
                energy_density="167",
                laser_power="120",
                treatment="HIP",
                value=265.1,
            ),
        ),
        objective_contexts=(objective_context,),
    )

    assert comparison_units == ()


def test_research_objective_service_does_not_promote_ved_when_sample_controls_change(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-elongation",
            "variable_process_axes": ["energy density"],
            "target_property_axes": ["elongation"],
        }
    )

    def elongation_unit(
        evidence_unit_id: str,
        *,
        specimen: str,
        energy_density: str,
        treatment: str,
        value: float,
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": evidence_unit_id,
                "objective_id": "obj-elongation",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "elongation",
                "sample_context": {
                    "Specimens": specimen,
                    "Laser energy density (J/mm3)": energy_density,
                    "Type of heat treatment": treatment,
                },
                "value_payload": {
                    "source_value_text": str(value),
                    "value": value,
                },
                "unit": "%",
                "resolution_status": "resolved",
                "confidence": 0.8,
            }
        )

    comparison_units = service._build_objective_pairwise_comparison_units(
        (
            elongation_unit(
                "oeu-elongation-as-slm",
                specimen="as-SLM (120/100)",
                energy_density="333",
                treatment="-",
                value=35.0,
            ),
            elongation_unit(
                "oeu-elongation-hip-slm",
                specimen="HIP-SLM (140/100)",
                energy_density="389",
                treatment="HIP",
                value=52.7,
            ),
        ),
        objective_contexts=(objective_context,),
    )

    assert comparison_units == ()


def test_research_objective_service_attributes_derived_ved_change_to_scan_speed(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-density",
            "variable_process_axes": [
                "energy density",
                "laser power",
                "scan speed",
            ],
            "target_property_axes": ["density"],
        }
    )

    def density_unit(
        evidence_unit_id: str,
        *,
        sample_number: str,
        scan_speed: str,
        energy_density: str,
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
                    "Laser energy density (J/mm3)": energy_density,
                    "Laser power (W)": "100",
                    "Scan speed (mm/s)": scan_speed,
                    "Type of heat treatment": "-",
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
                "oeu-density-fast",
                sample_number="2",
                scan_speed="200",
                energy_density="139",
                density=91.84,
            ),
            density_unit(
                "oeu-density-slow",
                sample_number="1",
                scan_speed="100",
                energy_density="278",
                density=97.83,
            ),
        ),
        objective_contexts=(objective_context,),
    )

    assert len(comparison_units) == 1
    assert comparison_units[0].value_payload["comparison_axis"] == "scan speed"


def test_research_objective_service_generates_pairwise_from_sample_condition_axis(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_service_generates_pairwise_from_process_condition_axis(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
                "sample_context": {"sample_number": sample_number},
                "process_context": {"Build platform conditions": platform_condition},
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
        ("2", "1", "yield strength", "build platform preheating", 465.0, 448.0),
        (
            "2",
            "1",
            "ultimate tensile strength",
            "build platform preheating",
            618.0,
            617.0,
        ),
        ("2", "1", "elongation", "build platform preheating", 82.0, 72.0),
    }


def test_research_objective_service_limits_pairwise_to_target_properties(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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


def test_research_objective_service_resolves_ved_fatigue_table_from_printed_label(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-fatigue",
            "question": (
                "How do volumetric energy density and process parameters affect "
                "defect structure and fatigue strength?"
            ),
            "variable_process_axes": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
                "hatch spacing",
                "layer thickness",
            ],
            "target_property_axes": ["defect structure", "fatigue strength"],
        }
    )

    process_units = [
        ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": f"oeu-process-{sample_label}",
                "objective_id": "obj-fatigue",
                "document_id": "paper-ved",
                "unit_kind": "process_context",
                "sample_context": {"ID": sample_label},
                "process_context": {
                    "VED [J/mm 3 ]": ved,
                    "Laser power [W]": laser_power,
                    "Scanning speed [mm/s]": scan_speed,
                    "Hatch spacing [ μ m]": hatch_spacing,
                    "Layer thickness [ μ m]": "30",
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-fabrication",
                        "role": "process_or_treatment",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.84,
            }
        )
        for sample_label, ved, laser_power, scan_speed, hatch_spacing in (
            ("L-VED", "50.8", "160", "875", "120"),
            ("M-VED", "79.4", "190", "800", "100"),
            ("H-VED", "84.3", "220", "725", "120"),
        )
    ]
    measurement_units = [
        ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": f"oeu-fatigue-{sample_label}",
                "objective_id": "obj-fatigue",
                "document_id": "paper-ved",
                "unit_kind": "measurement",
                "property_normalized": "fatigue strength",
                "sample_context": {"Printed 316L": sample_label},
                "value_payload": {
                    "source_value_text": str(fatigue_strength),
                    "value": fatigue_strength,
                },
                "unit": "MPa",
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-fatigue",
                        "role": "current_experimental_evidence",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.88,
            }
        )
        for sample_label, fatigue_strength in (
            ("L-VED", 340),
            ("M-VED", 450),
            ("H-VED", 470),
        )
    ]
    defect_units = [
        ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": f"oeu-defect-{sample_label}",
                "objective_id": "obj-fatigue",
                "document_id": "paper-ved",
                "unit_kind": "measurement",
                "property_normalized": "max defect length",
                "sample_context": {"Printed 316L": sample_label},
                "value_payload": {
                    "source_value_text": str(defect_length),
                    "value": defect_length,
                },
                "unit": "μm",
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-fatigue",
                        "role": "current_experimental_evidence",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.88,
            }
        )
        for sample_label, defect_length in (
            ("L-VED", 394),
            ("M-VED", 179),
            ("H-VED", 86),
        )
    ]

    resolved_units = service._resolve_objective_evidence_unit_contexts(
        (*process_units, *measurement_units, *defect_units)
    )
    comparison_units = service._build_objective_pairwise_comparison_units(
        resolved_units,
        objective_contexts=(objective_context,),
    )

    fatigue_units = [
        unit
        for unit in resolved_units
        if unit.unit_kind == "measurement"
        and unit.property_normalized == "fatigue strength"
        and unit.sample_context.get("Printed 316L") in {"L-VED", "M-VED", "H-VED"}
    ]
    assert all("VED [J/mm 3 ]" in unit.process_context for unit in fatigue_units)
    assert {
        unit.sample_context["Printed 316L"]: unit.process_context["VED [J/mm 3 ]"]
        for unit in fatigue_units
    } == {"L-VED": "50.8", "M-VED": "79.4", "H-VED": "84.3"}
    assert {
        (unit.value_payload["comparison_axis"], unit.property_normalized)
        for unit in comparison_units
    } == {
        ("laser power, scanning speed", "fatigue strength"),
        ("laser power, scanning speed", "max defect length"),
        ("laser power, scanning speed, hatch spacing", "fatigue strength"),
        ("laser power, scanning speed, hatch spacing", "max defect length"),
    }


def test_research_objective_service_inferrs_sample_and_defect_columns_without_model_roles(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-fatigue",
            "question": (
                "How do volumetric energy density and process parameters affect "
                "defect structure and fatigue strength?"
            ),
            "variable_process_axes": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
                "hatch spacing",
                "layer thickness",
            ],
            "target_property_axes": ["defect structure", "fatigue strength"],
        }
    )
    process_route = ObjectiveEvidenceRoute.from_mapping(
        {
            "route_id": "route-process",
            "objective_id": "obj-fatigue",
            "document_id": "paper-ved",
            "source_kind": "table",
            "source_ref": "table-fabrication",
            "role": "process_or_treatment",
            "extractable": True,
            "column_roles": {
                "VED [J/mm 3]": "process_variable",
                "Laser power [W]": "process_variable",
                "Scanning speed [mm/s]": "process_variable",
                "Hatch spacing [ μ m]": "process_variable",
                "Layer thickness [ μ m]": "process_variable",
            },
            "confidence": 0.84,
        }
    )
    result_route = ObjectiveEvidenceRoute.from_mapping(
        {
            "route_id": "route-fatigue",
            "objective_id": "obj-fatigue",
            "document_id": "paper-ved",
            "source_kind": "table",
            "source_ref": "table-fatigue",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "FAT at 10 4 cycles [MPa]": "target_property",
            },
            "confidence": 0.88,
        }
    )

    process_records = service._objective_table_matrix_evidence_unit_records(
        route=process_route,
        source={
            "page": 4,
            "column_headers": [
                "ID",
                "VED [J/mm 3]",
                "Laser power [W]",
                "Scanning speed [mm/s]",
                "Hatch spacing [ μ m]",
                "Layer thickness [ μ m]",
            ],
            "table_matrix": [
                [
                    "ID",
                    "VED [J/mm 3]",
                    "Laser power [W]",
                    "Scanning speed [mm/s]",
                    "Hatch spacing [ μ m]",
                    "Layer thickness [ μ m]",
                ],
                ["L-VED", "50.8", "160", "875", "120", "30"],
                ["M-VED", "79.4", "190", "800", "100", "30"],
                ["H-VED", "84.3", "220", "725", "120", "30"],
            ],
        },
        objective_context=objective_context,
    )
    result_records = service._objective_table_matrix_evidence_unit_records(
        route=result_route,
        source={
            "page": 10,
            "column_headers": [
                "Printed 316L",
                "UTS [MPa]",
                "FAT50 % [MPa]",
                "FAT/ UTS -",
                "FAT at 10 4 cycles [MPa]",
                "Max. Defect length (LCSM) [ μ m]",
            ],
            "table_matrix": [
                [
                    "Printed 316L",
                    "UTS [MPa]",
                    "FAT50 % [MPa]",
                    "FAT/ UTS -",
                    "FAT at 10 4 cycles [MPa]",
                    "Max. Defect length (LCSM) [ μ m]",
                ],
                ["L-VED", "610 ± 6", "93", "0.15", "340", "394"],
                ["M-VED", "595 ± 13", "82", "0.14", "450", "179"],
                ["H-VED", "560 ± 4", "97", "0.17", "470", "86"],
                ["Wrought", "624 ± 2", "256", "0.41", "390", "-"],
            ],
        },
        objective_context=objective_context,
    )
    units = tuple(
        ObjectiveEvidenceUnit.from_mapping(record)
        for record in (*process_records, *result_records)
    )
    resolved_units = service._resolve_objective_evidence_unit_contexts(units)
    comparison_units = service._build_objective_pairwise_comparison_units(
        resolved_units,
        objective_contexts=(objective_context,),
    )

    result_by_property = {
        record["property_normalized"]
        for record in result_records
    }
    assert {"fatigue strength", "fatigue limit", "max defect length"} <= result_by_property
    assert all(
        record["sample_context"].get("Printed 316L")
        for record in result_records
        if record["property_normalized"] in {"fatigue strength", "max defect length"}
    )
    assert {
        unit.sample_context.get("Printed 316L"): unit.process_context.get("VED [J/mm 3]")
        for unit in resolved_units
        if unit.unit_kind == "measurement"
        and unit.property_normalized == "fatigue strength"
        and unit.sample_context.get("Printed 316L") in {"L-VED", "M-VED", "H-VED"}
    } == {"L-VED": "50.8", "M-VED": "79.4", "H-VED": "84.3"}
    assert {
        (unit.value_payload["comparison_axis"], unit.property_normalized)
        for unit in comparison_units
    } == {
        ("laser power, scanning speed", "fatigue limit"),
        ("laser power, scanning speed", "fatigue strength"),
        ("laser power, scanning speed", "max defect length"),
        ("laser power, scanning speed, hatch spacing", "fatigue limit"),
        ("laser power, scanning speed, hatch spacing", "fatigue strength"),
        ("laser power, scanning speed, hatch spacing", "max defect length"),
    }


def test_process_route_does_not_treat_result_columns_as_process_context(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-fatigue",
            "variable_process_axes": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
                "hatch spacing",
                "layer thickness",
            ],
            "target_property_axes": ["defect structure", "fatigue strength"],
        }
    )
    misrouted_result_table = ObjectiveEvidenceRoute.from_mapping(
        {
            "route_id": "route-misclassified-results",
            "objective_id": "obj-fatigue",
            "document_id": "paper-ved",
            "source_kind": "table",
            "source_ref": "table-melt-pool-density",
            "role": "process_or_treatment",
            "extractable": True,
            "column_roles": {
                "Grain Size [um] > Eq. diam.": "statistical_measure",
            },
            "confidence": 0.84,
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=misrouted_result_table,
        source={
            "page": 5,
            "column_headers": [
                "ID",
                "Melt Pool Size [um] > Width",
                "Grain Size [um] > Eq. diam.",
                "Density [%] > Archimedes method",
            ],
            "table_matrix": [
                [
                    "ID",
                    "Melt Pool Size [um] > Width",
                    "Grain Size [um] > Eq. diam.",
                    "Density [%] > Archimedes method",
                ],
                ["L-VED", "148", "81", "91.90"],
            ],
        },
        objective_context=objective_context,
    )

    assert records == ()


def test_process_route_recovers_target_columns_from_mixed_table(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-fatigue",
            "variable_process_axes": ["volumetric energy density"],
            "target_property_axes": ["fatigue strength"],
        }
    )
    mixed_route = ObjectiveEvidenceRoute.from_mapping(
        {
            "route_id": "route-mixed-fatigue",
            "objective_id": "obj-fatigue",
            "document_id": "paper-ved",
            "source_kind": "table",
            "source_ref": "table-mixed-fatigue",
            "role": "process_or_treatment",
            "extractable": True,
            "column_roles": {
                "ID": "sample_id",
                "VED [J/mm3]": "process_variable",
                "Fatigue strength [MPa]": "target_property",
                "Standard deviation [MPa]": "statistical_measure",
            },
            "confidence": 0.9,
        }
    )

    records = service._objective_table_matrix_evidence_unit_records(
        route=mixed_route,
        source={
            "page": 10,
            "column_headers": [
                "ID",
                "VED [J/mm3]",
                "Fatigue strength [MPa]",
                "Standard deviation [MPa]",
            ],
            "table_matrix": [
                ["ID", "VED [J/mm3]", "Fatigue strength [MPa]", "Standard deviation [MPa]"],
                ["L-VED", "50.8", "340", "8"],
            ],
        },
        objective_context=objective_context,
    )

    process_record = next(record for record in records if record["unit_kind"] == "process_context")
    result_record = next(record for record in records if record["unit_kind"] == "measurement")
    assert process_record["process_context"] == {"VED [J/mm3]": "50.8"}
    assert "Fatigue strength [MPa]" not in process_record["process_context"]
    assert "Standard deviation [MPa]" not in process_record["process_context"]
    assert result_record["property_normalized"] == "fatigue strength"
    assert result_record["value_payload"] == {
        "source_value_text": "340",
        "value": 340.0,
    }


def test_research_objective_service_adds_context_hint_route_for_condition_table(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-structure",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["scanning speed", "energy density"],
            "target_property_axes": ["microstructure", "densification"],
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
        objective_context=objective_context,
        source_candidates=candidates,
    )

    assert [route.source_ref for route in routes] == [
        "conclusion",
        "microstructure-results",
    ]
    assert {route.role for route in routes} == {"characterization"}
    assert {route.join_plan["evidence_role"] for route in routes} == {
        "direct_support"
    }


def test_research_objective_service_text_hint_keeps_mediator_out_of_direct_support(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["laser power"],
            "measured_property_scope": ["pitting corrosion"],
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-corrosion",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["laser power"],
            "process_context_axes": ["SLM"],
            "target_property_axes": ["pitting potential"],
            "objective_evidence_lens": {
                "target_outcome_axes": ["pitting potential"],
                "mediator_axes": ["porosity", "pore size", "lack of fusion"],
                "variable_process_axes": ["laser power"],
                "context_axes": ["316L stainless steel", "SLM"],
                "excluded_axes": [],
                "direct_support_rules": [
                    "Direct support must explicitly report a target outcome."
                ],
            },
        }
    )
    candidates = [
        {
            "source_kind": "text_window",
            "source_ref": "lof-defects",
            "section_label": "3. Results",
            "block_type": "paragraph",
            "text": (
                "Lack of fusion defects were observed at melt pool boundaries "
                "with irregular pore morphology."
            ),
        },
        {
            "source_kind": "text_window",
            "source_ref": "pitting-result",
            "section_label": "4. Conclusion",
            "block_type": "paragraph",
            "text": (
                "The pitting potential increased when porosity decreased, "
                "indicating improved pitting corrosion resistance."
            ),
        },
    ]
    routes: list[ObjectiveEvidenceRoute] = []

    service._append_ranked_text_hint_routes(
        routes=routes,
        seen=set(),
        frame=frame,
        objective_context=objective_context,
        source_candidates=candidates,
    )

    route_by_ref = {route.source_ref: route for route in routes}
    assert route_by_ref["lof-defects"].join_plan["evidence_role"] == "mediator_context"
    assert route_by_ref["lof-defects"].role == "characterization"
    assert route_by_ref["lof-defects"].extractable is False
    assert route_by_ref["pitting-result"].join_plan["evidence_role"] == "direct_support"
    assert route_by_ref["pitting-result"].extractable is True


def test_research_objective_routing_uses_document_tree_order(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
        }
    )
    blocks = [
        SimpleNamespace(
            block_id="results",
            block_order=1,
            block_type="paragraph",
            heading_path="Results",
            text="The yield strength result showed 900 MPa after heat treatment.",
        ),
        SimpleNamespace(
            block_id="methods",
            block_order=100,
            block_type="paragraph",
            heading_path="Methods",
            text="The 316L samples used heat treatment at 650 C for 4 h.",
        ),
    ]
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("methods-section", "results-section"),
                node_type="document",
                order=0,
            ),
            "methods-section": SourceDocumentNode(
                node_id="methods-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("methods-node",),
                node_type="section",
                order=100,
                title="Methods",
                heading_path=("Methods",),
            ),
            "methods-node": SourceDocumentNode(
                node_id="methods-node",
                document_id="paper-1",
                parent_id="methods-section",
                child_ids=(),
                node_type="paragraph",
                order=110,
                heading_path=("Methods",),
                source_ref_kind="block",
                source_ref_id="methods",
            ),
            "results-section": SourceDocumentNode(
                node_id="results-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("results-node",),
                node_type="section",
                order=200,
                title="Results",
                heading_path=("Results",),
            ),
            "results-node": SourceDocumentNode(
                node_id="results-node",
                document_id="paper-1",
                parent_id="results-section",
                child_ids=(),
                node_type="paragraph",
                order=210,
                heading_path=("Results",),
                source_ref_kind="block",
                source_ref_id="results",
            ),
        },
    )
    extractor = _ObjectiveExtractor()

    service._build_objective_evidence_routes(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": blocks},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert [payload["current_source"]["source_ref"] for payload in extractor.route_payloads] == [
        "methods",
        "results",
    ]
    assert extractor.route_payloads[0]["tree_position"]["section_path"] == ["Methods"]
    assert extractor.route_payloads[1]["tree_position"]["section_path"] == ["Results"]


def test_research_objective_routing_binds_current_source_to_model_decision(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
            "relevant_tables": ["table-1"],
        }
    )
    table = SimpleNamespace(
        table_id="table-1",
        caption_text="Yield strength results after heat treatment.",
        heading_path="Results",
        columns=("condition", "yield strength"),
        rows=(("HT", "900 MPa"),),
    )
    extractor = _ObjectiveExtractor()

    routes = service._build_objective_evidence_routes(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": [table]},
        document_trees_by_document_id={},
    )

    assert len(extractor.route_payloads) == 1
    assert extractor.route_payloads[0]["current_source"]["source_ref"] == "table-1"
    assert len(routes) == 1
    assert routes[0].source_kind == "table"
    assert routes[0].source_ref == "table-1"
    assert routes[0].role == "current_experimental_evidence"
    assert routes[0].join_plan["evidence_role"] == "direct_support"


def test_research_objective_routing_uses_compact_prompt_payload(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["yield strength"],
            "comparison_intent": "compare treated and untreated samples",
            "confidence": 0.9,
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": objective.question,
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["heat treatment"],
            "process_context_axes": ["LPBF"],
            "target_property_axes": ["yield strength"],
            "routing_hints": [
                {
                    "table_id": "table-1",
                    "role": "result_table",
                    "reason": "Large hint text should not enter routing prompt.",
                }
            ],
            "extraction_guidance": {"large": "x" * 1000},
            "confidence": 0.8,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "background": "x" * 1000,
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
            "relevant_sections": ["Results"],
            "relevant_tables": ["table-1"],
            "excluded_tables": ["table-2"],
        }
    )
    table = SimpleNamespace(
        table_id="table-1",
        caption_text="Yield strength results after heat treatment.",
        heading_path="Results",
        columns=("condition", "yield strength"),
        column_headers=["condition", "yield strength"],
        row_count=200,
        col_count=10,
        table_matrix=[["condition", "yield strength"], *[["HT", "900 MPa"]] * 20],
    )
    extractor = _ObjectiveExtractor()

    service._build_objective_evidence_routes(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(objective_context,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": [table]},
        document_trees_by_document_id={},
    )

    route_payload = extractor.route_payloads[0]
    assert "routing_hints" not in route_payload["objective_context"]
    assert "extraction_guidance" not in route_payload["objective_context"]
    assert "background" not in route_payload["paper_frame"]
    assert "relevant_tables" not in route_payload["paper_frame"]
    assert "excluded_tables" not in route_payload["paper_frame"]
    assert "table_schema" not in route_payload["current_source"]
    assert "sample_rows" not in route_payload["current_source"]
    assert route_payload["current_source"]["column_headers"] == [
        "condition",
        "yield strength",
    ]
    assert route_payload["current_source"]["row_count"] == 200


def test_research_objective_routing_uses_text_hint_not_source_text(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
        }
    )
    long_text = "Heat treatment changed yield strength. " + ("x" * 1000)
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("results-node",),
                node_type="document",
                order=0,
            ),
            "results-node": SourceDocumentNode(
                node_id="results-node",
                document_id="paper-1",
                parent_id="root",
                child_ids=(),
                node_type="paragraph",
                order=100,
                text=long_text,
                heading_path=("Results",),
                source_ref_kind="block",
                source_ref_id="results",
            ),
        },
    )
    extractor = _ObjectiveExtractor()

    service._build_objective_evidence_routes(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    current_source = extractor.route_payloads[0]["current_source"]
    assert "text" not in current_source
    assert current_source["text_hint"] == long_text[:320]
    assert len(current_source["text_hint"]) == 320


def test_research_objective_routing_builds_text_candidates_from_document_tree(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
        }
    )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("methods-section", "results-section", "refs-section"),
                node_type="document",
                order=0,
            ),
            "methods-section": SourceDocumentNode(
                node_id="methods-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("methods-node",),
                node_type="section",
                order=100,
                title="Methods",
                heading_path=("Methods",),
            ),
            "methods-node": SourceDocumentNode(
                node_id="methods-node",
                document_id="paper-1",
                parent_id="methods-section",
                child_ids=(),
                node_type="paragraph",
                order=110,
                text="The 316L samples used heat treatment at 650 C for 4 h.",
                heading_path=("Methods",),
                source_ref_kind="block",
                source_ref_id="methods",
            ),
            "results-section": SourceDocumentNode(
                node_id="results-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("results-node",),
                node_type="section",
                order=200,
                title="Results",
                heading_path=("Results",),
            ),
            "results-node": SourceDocumentNode(
                node_id="results-node",
                document_id="paper-1",
                parent_id="results-section",
                child_ids=(),
                node_type="paragraph",
                order=210,
                text="The yield strength result showed 900 MPa after heat treatment.",
                heading_path=("Results",),
                source_ref_kind="block",
                source_ref_id="results",
            ),
            "refs-section": SourceDocumentNode(
                node_id="refs-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("reference-node",),
                node_type="references_section",
                order=300,
                title="References",
                heading_path=("References",),
            ),
            "reference-node": SourceDocumentNode(
                node_id="reference-node",
                document_id="paper-1",
                parent_id="refs-section",
                child_ids=(),
                node_type="paragraph",
                order=310,
                text="A reference also mentions yield strength after heat treatment.",
                heading_path=("References",),
                source_ref_kind="block",
                source_ref_id="reference",
            ),
        },
    )
    extractor = _ObjectiveExtractor()

    service._build_objective_evidence_routes(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert [payload["current_source"]["source_ref"] for payload in extractor.route_payloads] == [
        "methods",
        "results",
    ]
    assert "reference" not in {
        payload["current_source"]["source_ref"]
        for payload in extractor.route_payloads
    }


def test_research_objective_low_relevance_tree_routing_uses_frame_sections(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "low",
            "paper_role": "supporting_background",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
            "relevant_sections": ["Results"],
        }
    )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("methods-section", "results-section"),
                node_type="document",
                order=0,
            ),
            "methods-section": SourceDocumentNode(
                node_id="methods-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("methods-node",),
                node_type="section",
                order=100,
                title="Methods",
                heading_path=("Methods",),
            ),
            "methods-node": SourceDocumentNode(
                node_id="methods-node",
                document_id="paper-1",
                parent_id="methods-section",
                child_ids=(),
                node_type="paragraph",
                order=110,
                text="The 316L samples used heat treatment at 650 C for 4 h.",
                heading_path=("Methods",),
                source_ref_kind="block",
                source_ref_id="methods",
            ),
            "results-section": SourceDocumentNode(
                node_id="results-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("results-node",),
                node_type="section",
                order=200,
                title="Results",
                heading_path=("Results",),
            ),
            "results-node": SourceDocumentNode(
                node_id="results-node",
                document_id="paper-1",
                parent_id="results-section",
                child_ids=(),
                node_type="paragraph",
                order=210,
                text="The yield strength result showed 900 MPa after heat treatment.",
                heading_path=("Results",),
                source_ref_kind="block",
                source_ref_id="results",
            ),
        },
    )
    extractor = _ObjectiveExtractor()

    service._build_objective_evidence_routes(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert [payload["current_source"]["source_ref"] for payload in extractor.route_payloads] == [
        "results",
    ]


def test_research_objective_low_relevance_tree_routing_limits_unsectioned_text(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "low",
            "paper_role": "supporting_background",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
        }
    )
    child_ids = tuple(f"node-{index}" for index in range(30))
    nodes: dict[str, SourceDocumentNode] = {
        "root": SourceDocumentNode(
            node_id="root",
            document_id="paper-1",
            parent_id=None,
            child_ids=child_ids,
            node_type="document",
            order=0,
        )
    }
    for index, node_id in enumerate(child_ids):
        nodes[node_id] = SourceDocumentNode(
            node_id=node_id,
            document_id="paper-1",
            parent_id="root",
            child_ids=(),
            node_type="paragraph",
            order=100 + index,
            text=(
                f"S{index} 316L samples used heat treatment and reported "
                f"yield strength result {800 + index} MPa."
            ),
            heading_path=("Results",),
            source_ref_kind="block",
            source_ref_id=f"block-{index}",
        )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes=nodes,
    )
    extractor = _ObjectiveExtractor()

    service._build_objective_evidence_routes(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    routed_refs = [
        payload["current_source"]["source_ref"]
        for payload in extractor.route_payloads
    ]
    assert len(routed_refs) == 8
    assert routed_refs == [f"block-{index}" for index in range(8)]


def test_research_objective_tree_routing_keeps_late_document_nodes(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
        }
    )
    child_ids = tuple(f"node-{index}" for index in range(45))
    nodes: dict[str, SourceDocumentNode] = {
        "root": SourceDocumentNode(
            node_id="root",
            document_id="paper-1",
            parent_id=None,
            child_ids=child_ids,
            node_type="document",
            order=0,
        )
    }
    for index, node_id in enumerate(child_ids):
        nodes[node_id] = SourceDocumentNode(
            node_id=node_id,
            document_id="paper-1",
            parent_id="root",
            child_ids=(),
            node_type="paragraph",
            order=100 + index,
            text=(
                f"S{index} 316L samples used heat treatment and reported "
                f"yield strength result {800 + index} MPa."
            ),
            heading_path=("Results",),
            source_ref_kind="block",
            source_ref_id=f"block-{index}",
        )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes=nodes,
    )
    extractor = _ObjectiveExtractor()

    service._build_objective_evidence_routes(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_contexts=(),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    routed_refs = [
        payload["current_source"]["source_ref"]
        for payload in extractor.route_payloads
    ]
    assert len(routed_refs) == 8
    assert routed_refs[-1] == "block-44"
    assert routed_refs == sorted(
        routed_refs,
        key=lambda ref: int(ref.replace("block-", "")),
    )


def test_research_objective_service_keeps_numeric_mechanism_text_candidates(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
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
        structured_extractor=extractor,
    )
    service.research_understanding_service.structured_extractor = extractor
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
        objectives = service.build_research_objectives(
            collection_id,
            build_id="build_test",
        )

    assert len(objectives) == 1
    assert objectives[0].question.startswith("How does heat treatment")
    facts = service.objective_repository.read(collection_id)
    assert facts.research_objectives_ready is True
    assert (
        service.research_understanding_repository.list_objective_understandings(
            collection_id
        )
        == ()
    )
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
    assert table_route.column_roles == {
        "sample": "sample_id",
        "corrosion current": "target_property",
    }
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
    assert len(extractor.route_payloads) == 2
    assert len(extractor.unit_payloads) == 1
    assert extractor.unit_payloads[0]["evidence_route"]["source_kind"] == "text_window"
    assert extractor.unit_payloads[0]["evidence_route"]["source_ref"] == "b2"
    assert all("source_candidates" not in payload for payload in extractor.route_payloads)
    assert [payload["current_source"]["source_ref"] for payload in extractor.route_payloads] == [
        "b2",
        "table-1",
    ]
    assert extractor.route_payloads[0]["paper_frame"]["frame_id"] == active_frame.frame_id
    assert extractor.route_payloads[0]["tree_position"]["section_path"] == ["Abstract"]
    assert extractor.unit_payloads[0]["tree_position"]["section_path"] == ["Abstract"]
    assert extractor.unit_payloads[0]["document_state"]["schema_version"] == (
        "objective_document_state.v1"
    )
    assert extractor.unit_payloads[0]["document_state"]["evidence_counts_by_kind"] == {}
    assert extractor.skim_payloads[0]["headings"] == ["Abstract", "References"]
    assert "Additional abstract context" in extractor.skim_payloads[0]["text_preview"]
    assert "Reference text should not" not in extractor.skim_payloads[0]["text_preview"]
    assert extractor.skim_payloads[0]["table_captions"][0]["table_id"] == "table-1"
    assert extractor.discovery_payloads[0]["paper_skims"][0]["document_id"] == "paper-1"
    assert extractor.frame_payloads[0]["objective_context"]["objective_id"] == (
        facts.research_objectives[0].objective_id
    )
    assert extractor.frame_payloads[0]["section_snippets"] == [
        {
            "section_label": "Abstract",
            "block_type": "section",
            "text": (
                "LPBF 316L was compared before and after heat treatment.\n\n"
                "Additional abstract context stayed in the same section."
            ),
        }
    ]
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
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Strengthening")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        structured_extractor=_BroadObjectiveExtractor(),
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

    objectives = service.build_research_objectives(
        collection_id,
        build_id="build_test",
    )

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
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Merge")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        structured_extractor=_DuplicateMechanicalObjectiveExtractor(),
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

    objectives = service.build_research_objectives(
        collection_id,
        build_id="build_test",
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
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Contexts")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        structured_extractor=_DuplicateMechanicalObjectiveExtractor(),
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

    service.build_research_objectives(collection_id, build_id="build_test")
    facts = service.objective_repository.read(collection_id)
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
        if "yield strength" in objective.property_axes
    )
    corrosion_objective = next(
        objective
        for objective in objectives
        if "corrosion potential" in objective.property_axes
    )
    assert "porosity" not in mechanical_objective.process_axes
    assert "porosity" in corrosion_objective.process_axes


def test_research_objective_service_does_not_global_fill_unmatched_seed_axes(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _UnmatchedSeedObjectiveExtractor(),
    )

    assert len(objectives) == 1
    objective = objectives[0]
    assert objective.process_axes == ("Selective Laser Melting",)
    assert objective.property_axes == ("mechanical properties",)


def test_research_objective_service_list_prunes_overbroad_display_axes(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Display")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        structured_extractor=_OverbroadPersistedObjectiveExtractor(),
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

    service.build_research_objectives(collection_id, build_id="build_test")
    workspace = service.list_objective_workspaces(collection_id)

    objective = workspace["objectives"][0]
    assert objective["process_axes"] == ["energy density", "scanning speed"]
    assert "porosity" not in objective["question"]
    assert "heat treatment" not in objective["question"]


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
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Duplicate Objectives")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        structured_extractor=_DuplicateObjectiveIdExtractor(),
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

    objectives = service.build_research_objectives(
        collection_id,
        build_id="build_test",
    )

    assert len(objectives) == 1
    facts = service.objective_repository.read(collection_id)
    assert len(facts.research_objectives) == 1


def test_objective_analysis_uses_deterministic_frame_when_frame_model_fails(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective frame fallback")
    collection_id = collection["collection_id"]
    extractor = _FailingFrameExtractor()
    service = _build_research_objective_service(
        collection_service=collection_service,
        structured_extractor=extractor,
    )
    service.research_understanding_service.structured_extractor = extractor
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
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj_texture_yield",
            "question": "How does scan strategy affect texture and yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["scan strategy rotation angle"],
            "property_axes": ["crystallographic texture", "yield strength"],
            "comparison_intent": "Compare texture and yield strength across scan strategy.",
            "seed_document_ids": ["paper-1"],
            "confidence": 0.9,
        }
    )
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "collection_id": collection_id,
            "source_filename": "paper-1.pdf",
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
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": objective.objective_id,
            "material_scope": ["316L stainless steel"],
            "process_context_axes": ["LPBF"],
            "variable_process_axes": ["scan strategy rotation angle"],
            "target_property_axes": ["crystallographic texture", "yield strength"],
        }
    )
    service.objective_repository.replace(
        collection_id,
        "build_test",
        ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=(paper_skim,),
            research_objectives=(objective,),
            objective_contexts=(objective_context,),
        ),
    )
    service.objective_repository.confirm_objective(
        collection_id,
        objective.objective_id,
    )

    understanding = service.analyze_objective(collection_id, objective.objective_id)

    facts = service.objective_repository.read(collection_id)
    assert extractor.frame_payloads
    assert facts.objective_paper_frames == ()
    assert facts.objective_evidence_units == ()
    assert understanding.scope.scope_type == "objective"


def test_objective_analysis_uses_deterministic_route_when_route_model_fails(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective stage retry")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        structured_extractor=_ObjectiveExtractor(),
    )
    service.research_understanding_service.structured_extractor = service._structured_extractor
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
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj_corrosion",
            "question": "How does heat treatment affect corrosion current?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["LPBF", "heat treatment"],
            "property_axes": ["corrosion current"],
            "comparison_intent": "Compare corrosion current before and after heat treatment.",
            "seed_document_ids": ["paper-1"],
            "confidence": 0.9,
        }
    )
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "collection_id": collection_id,
            "source_filename": "paper-1.pdf",
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
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": objective.objective_id,
            "material_scope": ["316L stainless steel"],
            "process_context_axes": ["LPBF"],
            "variable_process_axes": ["heat treatment"],
            "target_property_axes": ["corrosion current"],
        }
    )
    service.objective_repository.replace(
        collection_id,
        "build_test",
        ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=(paper_skim,),
            research_objectives=(objective,),
            objective_contexts=(objective_context,),
        ),
    )
    service.objective_repository.confirm_objective(
        collection_id,
        objective.objective_id,
    )

    failing_extractor = _FailingRouteExtractor()
    service._structured_extractor = failing_extractor
    service.research_understanding_service.structured_extractor = failing_extractor
    understanding = service.analyze_objective(collection_id, objective.objective_id)

    assert understanding.scope.scope_type == "objective"
    assert failing_extractor.route_payloads
    facts = service.objective_repository.read(collection_id)
    assert facts.objective_paper_frames == ()
    assert facts.objective_evidence_routes == ()
    assert facts.objective_evidence_units == ()
    assert facts.objective_logic_chains == ()


def test_objective_analysis_does_not_mutate_active_objective_facts(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective force rebuild")
    collection_id = collection["collection_id"]
    extractor = _ObjectiveExtractor()
    service = _build_research_objective_service(
        collection_service=collection_service,
        structured_extractor=extractor,
    )
    service.research_understanding_service.structured_extractor = extractor
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
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj_corrosion",
            "question": "How does heat treatment affect corrosion current?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["LPBF", "heat treatment"],
            "property_axes": ["corrosion current"],
            "comparison_intent": "Compare corrosion current before and after heat treatment.",
            "seed_document_ids": ["paper-1"],
            "confidence": 0.9,
        }
    )
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "collection_id": collection_id,
            "source_filename": "paper-1.pdf",
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
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": objective.objective_id,
            "material_scope": ["316L stainless steel"],
            "process_context_axes": ["LPBF"],
            "variable_process_axes": ["heat treatment"],
            "target_property_axes": ["corrosion current"],
        }
    )
    stale_frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "low",
            "paper_role": "uncertain",
            "relevant_sections": [],
            "relevant_tables": [],
        }
    )
    stale_route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "stale-block",
            "role": "low_value_or_irrelevant",
            "extractable": False,
        }
    )
    stale_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu_stale",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "stale property",
            "value_payload": {"source_value_text": "stale"},
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "stale-block",
                }
            ],
            "resolution_status": "resolved",
        }
    )
    stale_chain = ObjectiveLogicChain.from_mapping(
        {
            "objective_id": objective.objective_id,
            "chain_scope": "objective",
            "evidence_unit_ids": ["oeu_stale"],
            "summary": "stale chain",
        }
    )
    service.objective_repository.replace(
        collection_id,
        "build_test",
        ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=(paper_skim,),
            research_objectives=(objective,),
            objective_contexts=(objective_context,),
            objective_paper_frames=(stale_frame,),
            objective_evidence_routes=(stale_route,),
            objective_evidence_units=(stale_unit,),
            objective_logic_chains=(stale_chain,),
        ),
    )
    active_facts = service.objective_repository.read(collection_id)
    service.objective_repository.confirm_objective(
        collection_id,
        objective.objective_id,
    )

    understanding = service.analyze_objective(collection_id, objective.objective_id)

    facts = service.objective_repository.read(collection_id)
    assert extractor.frame_payloads
    assert extractor.route_payloads
    assert facts == active_facts
    assert understanding.scope.scope_type == "objective"


def _build_duplicate_paper_objectives(
    tmp_path,
    extractor: _ObjectiveExtractor,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Merge")
    collection_id = collection["collection_id"]
    service = _build_research_objective_service(
        collection_service=collection_service,
        structured_extractor=extractor,
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
    return service.build_research_objectives(
        collection_id,
        build_id="build_test",
    )
