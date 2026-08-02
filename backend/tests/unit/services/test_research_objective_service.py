from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from application.core.semantic_build.llm.schemas import (
    StructuredAxisCanonicalizationGroup,
    StructuredAxisCanonicalizationPlan,
    StructuredDocumentProfile,
    StructuredEvidenceSelection,
    StructuredEvidenceSelections,
    StructuredEvidenceExtraction,
    StructuredEvidenceExtractions,
    StructuredFindingSynthesis,
    StructuredFindingSynthesisItem,
    StructuredFindingSynthesisOutcome,
    StructuredObjectiveMergeGroup,
    StructuredObjectiveMergePlan,
    StructuredPaperContributionDraft,
    StructuredPaperSkim,
    StructuredResearchObjective,
    StructuredResearchObjectives,
    StructuredTableMatrixRepair,
)
from application.core.semantic_build.research_objective_service import (
    EvidenceCandidate,
    ExtractedEvidenceDraft,
    PaperAnalysisFrame,
    ResearchObjectiveService as _ResearchObjectiveService,
    SourceSelectionHint,
)
from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
)
from application.core.finding_synthesis_service import FindingSynthesisService
from tests.support.collection_service import build_test_collection_service
from domain.core import (
    DocumentProfile,
    ObjectiveAnalysis,
    ObjectiveFactSet,
    PaperSkim,
    ResearchObjective,
)
from domain.source import SourceArtifactSet, SourceDocumentNode, SourceDocumentTree
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.source_artifact_repository import MemorySourceArtifactRepository


def _research_objective(payload: dict[str, Any]) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "collection-test",
            "question": "How does process condition affect the target outcome?",
            "variables": ["process condition"],
            "outcomes": ["target outcome"],
            **payload,
        }
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
    document_profile_service = kwargs.pop("document_profile_service", None)
    if document_profile_service is None:
        document_profile_service = DocumentProfileService(
            collection_service=collection_service,
            source_artifact_repository=source_repository,
            paper_fact_repository=paper_fact_repository,
        )
    finding_synthesis_service = kwargs.pop(
        "finding_synthesis_service",
        FindingSynthesisService(
            structured_extractor=kwargs.get("structured_extractor"),
        ),
    )
    return _ResearchObjectiveService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
        objective_repository=objective_repository,
        document_profile_service=document_profile_service,
        finding_synthesis_service=finding_synthesis_service,
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


def _queue_running_analysis(
    service: _ResearchObjectiveService,
    collection_id: str,
    objective_id: str,
) -> ObjectiveAnalysis:
    service.objective_repository.confirm_objective(collection_id, objective_id)
    _, queued = service.objective_repository.queue_analysis(
        collection_id,
        objective_id,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    claimed = service.objective_repository.claim_analysis(
        collection_id,
        objective_id,
        queued.analysis_version,
    )
    assert claimed is not None
    return claimed


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


def test_objective_evidence_document_state_is_typed_and_document_scoped(tmp_path):
    class RecordingExtractor:
        def __init__(self) -> None:
            self.payloads: list[dict[str, Any]] = []

        def extract_objective_evidence(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            self.payloads.append(payload)
            source_ref = payload["evidence_route"]["source_ref"]
            if source_ref == "paper-1-methods":
                return StructuredEvidenceExtractions(
                    extractions=[
                        StructuredEvidenceExtraction(
                            evidence_role="condition_context",
                            attribution_scope="descriptive_only",
                            scientific_context={
                                "process": [
                                    {
                                        "name": "laser power",
                                        "value": 150,
                                        "unit": "W",
                                    }
                                ]
                            },
                            resolution_status="resolved",
                            confidence=0.9,
                        )
                    ]
                )
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
                        evidence_role="direct_result",
                        changed_variables=[
                            {
                                "name": "laser power",
                                "baseline_value": 150,
                                "target_value": 200,
                                "unit": "W",
                            }
                        ],
                        comparison={
                            "baseline_label": "150 W",
                            "target_label": "200 W",
                            "axis_names": ["laser power"],
                            "comparable": True,
                            "incomparability_reasons": [],
                        },
                        reported_result={
                            "outcome": "relative density",
                            "value": 99.2,
                            "unit": "%",
                            "direction": "increase",
                            "result_text": (
                                "Relative density increased from 96.1% to 99.2%."
                            ),
                        },
                        attribution_scope="isolated_effect",
                        resolution_status="resolved",
                        confidence=0.9,
                    )
                ]
            )

    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    extractor = RecordingExtractor()
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    routes = tuple(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": "obj-density",
                "document_id": document_id,
                "source_kind": "text_window",
                "source_ref": source_ref,
                "role": "current_experimental_evidence",
                "extractable": True,
                "confidence": 0.9,
            }
        )
        for document_id, source_ref in (
            ("paper-1", "paper-1-methods"),
            ("paper-1", "paper-1-results"),
            ("paper-2", "paper-2-results"),
        )
    )
    blocks = {
        document_id: [
            SimpleNamespace(
                block_id=source_ref,
                text=f"Source text for {source_ref}.",
                page=1,
                block_type="paragraph",
                heading_path="Results",
            )
            for route_document_id, source_ref in (
                ("paper-1", "paper-1-methods"),
                ("paper-1", "paper-1-results"),
                ("paper-2", "paper-2-results"),
            )
            if route_document_id == document_id
        ]
        for document_id in ("paper-1", "paper-2")
    }

    units = service._build_objective_evidence(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=routes,
        blocks_by_document_id=blocks,
        tables_by_document_id={},
        document_trees_by_document_id={},
    )

    assert len(units) == 3
    first_state, second_state, third_state = [
        payload["document_state"] for payload in extractor.payloads
    ]
    assert first_state == service._empty_objective_document_state()
    assert second_state["schema_version"] == "objective_document_state.v2"
    assert second_state["evidence_counts_by_role"] == {"condition_context": 1}
    prior = second_state["prior_evidence"][0]
    assert prior["source_refs"][0]["source_ref"] == "paper-1-methods"
    assert not {
        "changed_variables",
        "comparison",
        "reported_result",
        "scientific_context",
    } & prior.keys()
    assert third_state == service._empty_objective_document_state()
    assert units[1].document_id == "paper-1"
    assert units[1].source_ref == "paper-1-results"
    assert units[1].source_refs[0]["source_ref"] == "paper-1-results"


def test_objective_evidence_continues_after_one_route_format_failure(tmp_path):
    class RecoveringExtractor:
        def __init__(self) -> None:
            self.calls = 0

        def extract_objective_evidence(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            self.calls += 1
            if self.calls == 1:
                raise ValueError("invalid structured response")
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
                        evidence_role="condition_context",
                        attribution_scope="descriptive_only",
                        scientific_context={
                            "test": [{"name": "temperature", "value": 25, "unit": "C"}]
                        },
                        resolution_status="resolved",
                        confidence=0.8,
                    )
                ]
            )

    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    extractor = RecoveringExtractor()
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    routes = tuple(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": source_ref,
                "role": "current_experimental_evidence",
                "extractable": True,
                "confidence": 0.9,
            }
        )
        for source_ref in ("block-failed", "block-recovered")
    )
    blocks = [
        SimpleNamespace(
            block_id=source_ref,
            text=f"Source text for {source_ref}.",
            page=1,
            block_type="paragraph",
            heading_path="Results",
        )
        for source_ref in ("block-failed", "block-recovered")
    ]

    units = service._build_objective_evidence(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=routes,
        blocks_by_document_id={"paper-1": blocks},
        tables_by_document_id={},
        document_trees_by_document_id={},
    )

    assert extractor.calls == 2
    assert len(units) == 1
    assert units[0].source_ref == "block-recovered"


def test_pairwise_comparison_retains_every_changed_process_axis(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )

    def result(evidence_id: str, values: dict[str, float], density: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-density",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "relative density",
                    "value": density,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"Relative density = {density}%.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "process": [
                        {"name": name, "value": value}
                        for name, value in values.items()
                    ]
                },
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-density"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparisons = service._build_objective_pairwise_comparison_units(
        (
            result(
                "row-a",
                {"scan speed": 800, "hatch spacing": 0.12, "VED": 100},
                96.1,
            ),
            result(
                "row-b",
                {"scan speed": 700, "hatch spacing": 0.10, "VED": 120},
                99.2,
            ),
        ),
        objectives=(),
    )

    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.attribution_scope == "joint_effect"
    assert {item.name for item in comparison.changed_variables} == {
        "scan speed",
        "hatch spacing",
        "VED",
    }
    assert comparison.comparison is not None
    assert comparison.comparison.comparable


def test_pairwise_comparison_isolated_effect_requires_one_changed_axis(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )

    def result(evidence_id: str, scan_speed: int, density: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-density",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "relative density",
                    "value": density,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"Relative density = {density}%.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "process": [
                        {"name": "scan speed", "value": scan_speed, "unit": "mm/s"},
                        {"name": "laser power", "value": 200, "unit": "W"},
                    ]
                },
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-density"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparison = service._build_objective_pairwise_comparison_units(
        (result("row-a", 800, 96.1), result("row-b", 700, 99.2)),
        objectives=(),
    )[0]

    assert comparison.attribution_scope == "isolated_effect"
    assert [item.name for item in comparison.changed_variables] == ["scan speed"]
    assert comparison.comparison is not None
    assert comparison.comparison.axis_names == ("scan speed",)


def test_pairwise_comparison_marks_sample_state_change_incomparable(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )

    def result(
        evidence_id: str,
        *,
        energy_density: int,
        sample_state: str,
        yield_strength: float,
    ):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-strength",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-strength",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "yield strength",
                    "value": yield_strength,
                    "unit": "MPa",
                    "direction": "unknown",
                    "result_text": f"Yield strength = {yield_strength} MPa.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "sample state", "value": sample_state}],
                    "process": [
                        {
                            "name": "energy density",
                            "value": energy_density,
                            "unit": "J/mm3",
                        }
                    ],
                },
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-strength"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparison = service._build_objective_pairwise_comparison_units(
        (
            result(
                "as-slm",
                energy_density=194,
                sample_state="as-SLM",
                yield_strength=426.7,
            ),
            result(
                "hip-slm",
                energy_density=167,
                sample_state="HIP-SLM",
                yield_strength=265.1,
            ),
        ),
        objectives=(),
    )[0]

    assert comparison.attribution_scope == "not_attributable"
    assert comparison.comparison is not None
    assert not comparison.comparison.comparable
    assert any(
        "sample condition differs for sample state" in reason
        for reason in comparison.comparison.incomparability_reasons
    )


def test_pairwise_comparison_marks_sparse_process_axis_incomparable(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )

    def result(evidence_id: str, process: list[dict[str, Any]], value: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-density",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "relative density",
                    "value": value,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"Relative density = {value}%.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {"process": process},
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-density"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparison = service._build_objective_pairwise_comparison_units(
        (
            result("row-a", [{"name": "scan speed", "value": 800}], 96.1),
            result(
                "row-b",
                [
                    {"name": "scan speed", "value": 700},
                    {"name": "hatch spacing", "value": 0.1},
                ],
                99.2,
            ),
        ),
        objectives=(),
    )[0]

    assert comparison.attribution_scope == "not_attributable"
    assert comparison.comparison is not None
    assert not comparison.comparison.comparable
    assert any(
        "missing one group value for hatch spacing" in reason
        for reason in comparison.comparison.incomparability_reasons
    )


def test_pairwise_comparison_is_bounded_per_objective_document(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"row-{index}",
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-density",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "relative density",
                    "value": 90 + index / 10,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"Relative density = {90 + index / 10}%.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "process": [{"name": "scan speed", "value": 500 + index}]
                },
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-density"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )
        for index in range(100)
    )

    comparisons = service._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(),
    )

    assert len(comparisons) == 48


def test_table_material_and_cell_locators_bound_comparison_source(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-density",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Material": "material",
                "Scan speed": "process_variable",
                "Relative density [%]": "result_property",
            },
            "confidence": 0.9,
        }
    )
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "material_scope": ["316L", "Ti-6Al-4V"],
            "variables": ["scan speed"],
            "outcomes": ["relative density"],
        }
    )
    source = {
        "page": 4,
        "column_headers": ["Material", "Scan speed", "Relative density [%]"],
        "table_matrix": [
            ["Material", "Scan speed", "Relative density [%]"],
            ["316L", "800", "96.1"],
            ["Ti-6Al-4V", "700", "99.2"],
        ],
    }
    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for record in service._objective_table_matrix_evidence_records(
            route=route,
            source=source,
            objective_context=objective,
        )
    )

    assert [item.value for item in measurements[0].scientific_context.material] == [
        "316L"
    ]
    assert measurements[0].source_refs[0]["row_index"] == 1
    assert measurements[0].source_refs[0]["col_index"] == 2
    assert measurements[0].source_refs[0]["header_path"] == "Relative density [%]"
    comparison = service._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )[0]
    assert comparison.attribution_scope == "not_attributable"
    assert comparison.comparison is not None
    assert any(
        "material condition differs for Material" in reason
        for reason in comparison.comparison.incomparability_reasons
    )

    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id="obj-density",
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
    )
    table = SimpleNamespace(
        table_id="table-density",
        page=4,
        to_record=lambda: {"table_markdown": "full table"},
    )
    evidence = service._analysis_evidence_records(
        collection_id="col-test",
        analysis=analysis,
        drafts=(comparison,),
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": [table]},
        figures_by_document_id={},
    )[0]
    assert "Material: 316L" in evidence.source_excerpt
    assert "Material: Ti-6Al-4V" in evidence.source_excerpt
    assert {ref["row_index"] for ref in evidence.related_source_refs} == {1, 2}


class _ObjectiveExtractor:
    def __init__(self) -> None:
        self.skim_payloads: list[dict[str, Any]] = []
        self.discovery_payloads: list[dict[str, Any]] = []
        self.canonicalization_payloads: list[dict[str, Any]] = []
        self.merge_payloads: list[dict[str, Any]] = []
        self.frame_payloads: list[dict[str, Any]] = []
        self.route_payloads: list[dict[str, Any]] = []
        self.unit_payloads: list[dict[str, Any]] = []
        self.finding_payloads: list[dict[str, Any]] = []

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
                    variables=["heat treatment"],
                    outcomes=["corrosion"],
                    constraints=["LPBF"],
                    requested_comparator="compare as-built and heat-treated corrosion behavior",
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=["paper-2"],
                    confidence=0.88,
                    reason="paper skims share a clear material-process-property axis",
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
                    variables=candidate["variables"],
                    outcomes=candidate["outcomes"],
                    requested_comparator=candidate["requested_comparator"],
                    confidence=candidate["confidence"],
                    reason=candidate["reason"],
                )
                for candidate in payload["candidate_objectives"]
            ]
        )

    def assess_objective_paper(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperContributionDraft:
        self.frame_payloads.append(payload)
        objective = payload["objective"]
        document = payload["document"]
        paper_skim = payload["paper_skim"]
        document_id = str(document.get("document_id") or "")
        table_summaries = payload["table_summaries"]
        if document_id in objective.get("excluded_document_ids", ()):
            return StructuredPaperContributionDraft(
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
                *objective.get("variables", ()),
                *objective.get("outcomes", ()),
            ),
        )
        section_labels = [
            item["section_label"]
            for item in payload["section_snippets"]
            if item.get("section_label")
        ]
        return StructuredPaperContributionDraft(
            relevance="high",
            paper_role="primary_experiment",
            background="Paper directly supports the active research objective.",
            material_match=list(paper_skim.get("candidate_materials") or []),
            changed_variables=list(paper_skim.get("changed_variables") or []),
            measured_property_scope=list(objective.get("outcomes") or []),
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

    def select_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredEvidenceSelections:
        self.route_payloads.append(payload)
        objective = payload["objective"]
        if not isinstance(payload.get("current_source"), dict):
            raise ValueError("objective evidence routing requires current_source")
        candidates = [payload["current_source"]]
        routes: list[StructuredEvidenceSelection] = []
        for candidate in candidates:
            if candidate["frame_status"] == "excluded":
                routes.append(
                    StructuredEvidenceSelection(
                        role="low_value_or_irrelevant",
                        extractable=False,
                        confidence=0.7,
                    )
                )
                continue
            if candidate["source_kind"] == "text_window":
                routes.append(
                    StructuredEvidenceSelection(
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
            outcomes = [
                str(axis or "").lower()
                for axis in objective.get("outcomes", ())
                if str(axis or "").strip()
            ]
            role = (
                "current_experimental_evidence"
                if any(axis in text for axis in outcomes)
                else "process_or_treatment"
            )
            routes.append(
                StructuredEvidenceSelection(
                    role=role,
                    extractable=True,
                    confidence=0.82,
                )
            )
        return StructuredEvidenceSelections(selections=routes)

    def extract_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredEvidenceExtractions:
        self.unit_payloads.append(payload)
        route = payload["evidence_route"]
        source = payload["source"]
        if route["source_kind"] == "table":
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
                        evidence_role="direct_result",
                        changed_variables=[
                            {
                                "name": "heat treatment",
                                "baseline_value": "as-built",
                                "target_value": "heat-treated",
                            }
                        ],
                        comparison={
                            "baseline_label": "as-built",
                            "target_label": "heat-treated",
                            "axis_names": ["heat treatment"],
                            "comparable": True,
                            "incomparability_reasons": [],
                        },
                        reported_result={
                            "outcome": "corrosion current",
                            "value": 1.2,
                            "unit": "uA/cm2",
                            "direction": "decrease",
                            "result_text": (
                                "Corrosion current decreased from 1.2 to "
                                "0.4 uA/cm2 after heat treatment."
                            ),
                        },
                        attribution_scope="isolated_effect",
                        scientific_context={
                            "material": [
                                {
                                    "name": "family",
                                    "value": "316L stainless steel",
                                }
                            ],
                            "process": [{"name": "process", "value": "LPBF"}],
                            "test": [
                                {"name": "method", "value": "corrosion test"}
                            ],
                        },
                        resolution_status="resolved",
                        confidence=0.86,
                    ),
                ]
            )
        if source.get("text"):
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
                        evidence_role="condition_context",
                        attribution_scope="descriptive_only",
                        scientific_context={
                            "material": [
                                {
                                    "name": "family",
                                    "value": "316L stainless steel",
                                }
                            ],
                            "sample": [
                                {
                                    "name": "comparison",
                                    "value": "before and after heat treatment",
                                }
                            ],
                            "process": [
                                {"name": "process", "value": "LPBF"},
                                {
                                    "name": "post treatment",
                                    "value": "heat treatment",
                                },
                            ],
                        },
                        resolution_status="partial",
                        confidence=0.74,
                    )
                ]
            )
        return StructuredEvidenceExtractions()

    def synthesize_findings(
        self,
        payload: dict[str, Any],
    ) -> StructuredFindingSynthesis:
        self.finding_payloads.append(payload)
        findings: list[StructuredFindingSynthesisItem] = []
        for result_set in payload.get("result_sets", [])[:6]:
            source_axes = [
                str(value).strip()
                for value in result_set.get("source_axes", [])
                if str(value).strip()
            ]
            outcomes = [
                str(value).strip()
                for value in result_set.get("outcome_properties", [])
                if str(value).strip()
            ]
            if not source_axes or not outcomes:
                continue
            source_concept = " + ".join(source_axes)
            findings.append(
                StructuredFindingSynthesisItem(
                    result_set_id=str(result_set["result_set_id"]),
                    source_concept=source_concept,
                    outcomes=[
                        StructuredFindingSynthesisOutcome(
                            concept=outcome,
                            direction="changes",
                            statement=f"{source_concept} changes {outcome}.",
                        )
                        for outcome in outcomes
                    ],
                    statement=(
                        f"{source_concept} changes {', '.join(outcomes)} in the "
                        "reported paper conditions."
                    ),
                    synthesis_status="insufficient_confirmation",
                    confidence=0.82,
                )
            )
        return StructuredFindingSynthesis(findings=findings)


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
                    variables=["processing parameters"],
                    outcomes=["mechanical properties"],
                    constraints=["Selective Laser Melting"],
                    requested_comparator=None,
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
                    variables=[
                        "energy density",
                        "scanning strategy",
                        "scanning speed",
                    ],
                    outcomes=["densification", "microstructure"],
                    constraints=["Selective Laser Melting"],
                    requested_comparator=(
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
                    variables=[
                        "energy density",
                        "scanning speed",
                    ],
                    outcomes=[
                        "yield strength",
                        "ultimate tensile strength",
                        "elongation",
                        "microhardness",
                    ],
                    constraints=["Selective Laser Melting"],
                    requested_comparator=(
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
                    variables=["scanning strategy"],
                    outcomes=["yield strength", "microhardness"],
                    constraints=["Selective Laser Melting"],
                    requested_comparator=(
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
            if "densification" in candidate["outcomes"]
        ]
        mechanical_candidates = [
            candidate
            for candidate in candidates
            if "yield strength" in candidate["outcomes"]
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
                    variables=structure_candidates[0]["variables"],
                    outcomes=structure_candidates[0]["outcomes"],
                    requested_comparator=structure_candidates[0]["requested_comparator"],
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
                    variables=_merge_candidate_values(
                        mechanical_candidates,
                        "variables",
                    ),
                    outcomes=_merge_candidate_values(
                        mechanical_candidates,
                        "outcomes",
                    ),
                    requested_comparator=(
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
                    variables=candidate["variables"],
                    outcomes=candidate["outcomes"],
                    requested_comparator=candidate["requested_comparator"],
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
                    axis_type="variable",
                    canonical="scanning strategy",
                    aliases=["scanning strategy", "scan strategy"],
                    confidence=0.95,
                    reason="same process variable phrased two ways",
                ),
                *[
                    StructuredAxisCanonicalizationGroup(
                        axis_type="variable",
                        canonical=value,
                        aliases=[value],
                        confidence=1.0,
                        reason="kept separate",
                    )
                    for value in payload["axis_candidates"]["variable"]
                    if value not in {"scanning strategy", "scan strategy"}
                ],
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="outcome",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["outcome"]
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="constraint",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["constraint"]
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
                    axis_type="variable",
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
                    axis_type="variable",
                    canonical="Selective Laser Melting",
                    aliases=payload["axis_candidates"]["variable"],
                    confidence=0.9,
                    reason="invalidly collapses distinct process axes",
                ),
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="outcome",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["outcome"]
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
                    variables=[
                        *candidate["variables"],
                        "laser power",
                    ],
                    outcomes=candidate["outcomes"],
                    requested_comparator=candidate["requested_comparator"],
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
                    variables=[
                        "Selective Laser Melting",
                        "laser power",
                        "scanning speed",
                    ],
                    outcomes=["yield strength", "elongation"],
                    requested_comparator=(
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
                    variables=["porosity"],
                    outcomes=["corrosion potential", "pitting potential"],
                    constraints=["Selective Laser Melting"],
                    requested_comparator=(
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
            variables = list(candidate["variables"])
            if "yield strength" in candidate["outcomes"]:
                variables.append("porosity")
            groups.append(
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[candidate["objective_id"]],
                    question=candidate["question"],
                    material_scope=candidate["material_scope"],
                    variables=variables,
                    outcomes=candidate["outcomes"],
                    requested_comparator=candidate["requested_comparator"],
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
                    variables=["heat treatment"],
                    outcomes=["mechanical properties"],
                    constraints=["Selective Laser Melting"],
                    requested_comparator="Compare heat-treatment effects on strength.",
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
                    variables=[
                        "Selective Laser Melting",
                        "energy density",
                        "scanning speed",
                        "porosity",
                        "heat treatment",
                        "scan strategy",
                    ],
                    outcomes=["yield strength"],
                    requested_comparator=(
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

    def extract_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredEvidenceExtractions:
        self.unit_payloads.append(payload)
        return StructuredEvidenceExtractions(
            extractions=[
                StructuredEvidenceExtraction(
                    evidence_role="direct_result",
                    changed_variables=[
                        {
                            "name": "energy density",
                            "baseline_value": 80,
                            "target_value": 100,
                            "unit": "J/mm3",
                        },
                        {
                            "name": "scanning speed",
                            "baseline_value": 1000,
                            "target_value": 1200,
                            "unit": "mm/s",
                        },
                    ],
                    comparison={
                        "baseline_label": "condition A",
                        "target_label": "condition B",
                        "axis_names": ["energy density", "scanning speed"],
                        "comparable": True,
                        "incomparability_reasons": [],
                    },
                    reported_result={
                        "outcome": "yield strength",
                        "value": 450,
                        "unit": "MPa",
                        "direction": "increase",
                        "result_text": "Yield strength reached 450 MPa.",
                    },
                    attribution_scope="joint_effect",
                    scientific_context={
                        "material": [
                            {
                                "name": "family",
                                "value": "316L stainless steel",
                            }
                        ],
                        "sample": [{"name": "label", "value": "S1"}],
                        "process": [
                            {"name": "process", "value": "SLM"},
                        ],
                    },
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
                    variables=_merge_candidate_values(candidates, "variables"),
                    outcomes=_merge_candidate_values(candidates, "outcomes"),
                    requested_comparator=(
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
            if "densification" in candidate["outcomes"]
        ]
        mechanical_candidates = [
            candidate
            for candidate in candidates
            if "yield strength" in candidate["outcomes"]
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
                    variables=structure_candidates[0]["variables"],
                    outcomes=structure_candidates[0]["outcomes"],
                    requested_comparator=structure_candidates[0]["requested_comparator"],
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
                    variables=_merge_candidate_values(
                        mechanical_candidates,
                        "variables",
                    ),
                    outcomes=_merge_candidate_values(
                        mechanical_candidates,
                        "outcomes",
                    ),
                    requested_comparator=(
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
                    variables=[
                        "Selective Laser Melting",
                        "energy density",
                        "scanning strategy",
                        "scanning speed",
                    ],
                    outcomes=[
                        "densification",
                        "microstructure",
                        "yield strength",
                        "ultimate tensile strength",
                        "elongation",
                        "microhardness",
                    ],
                    requested_comparator=(
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
            variables=["heat treatment"],
            outcomes=["corrosion"],
            constraints=["LPBF"],
            requested_comparator="compare heat treatment effects on corrosion",
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


def test_research_objective_service_canonicalizes_model_document_references(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
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


def test_research_objective_table_source_payload_includes_table_cells(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
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
    route = EvidenceCandidate.from_mapping(
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
    objective = _research_objective(
        {
            "objective_id": "obj-texture-yield",
            "question": (
                "How do scan strategy rotation angle and build orientation angle "
                "affect crystallographic texture and yield strength of LPBF 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["scan strategy rotation angle", "build orientation angle"],
            "constraints": ["Laser Powder Bed Fusion"],
            "outcomes": ["crystallographic texture", "yield strength"],
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
    assert payload["objective"]["variables"] == [
        "scan strategy rotation angle",
        "build orientation angle",
    ]
    assert payload["objective"]["outcomes"] == [
        "crystallographic texture",
        "yield strength",
    ]
    assert payload["objective"]["constraints"] == ["Laser Powder Bed Fusion"]
    assert "objective_context" not in payload


def test_objective_paper_frame_payload_filters_unscored_tables(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-texture-yield",
            "question": (
                "How do scan strategy rotation angle and build orientation angle "
                "affect crystallographic texture and yield strength?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["scan strategy rotation angle", "build orientation angle"],
            "outcomes": ["crystallographic texture", "yield strength"],
            "confidence": 0.9,
        }
    )
    payload = service._build_objective_paper_frame_payload(
        collection_id="col-test",
        objective=objective,
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
    objective = _research_objective(
        {
            "objective_id": "obj-texture-yield",
            "question": (
                "How do scan strategy rotation angle and build orientation angle "
                "affect crystallographic texture and yield strength?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["scan strategy rotation angle", "build orientation angle"],
            "outcomes": ["crystallographic texture", "yield strength"],
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
    route = EvidenceCandidate.from_mapping(
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


def test_research_objective_evidence_prompt_compacts_long_text_source(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
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
    route = EvidenceCandidate.from_mapping(
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

        def extract_objective_evidence(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            self.unit_payloads.append(payload)
            return StructuredEvidenceExtractions()

    extractor = PayloadCaptureExtractor()

    service._build_objective_evidence(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
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


def test_research_objective_fragmented_table_matrix_triggers_structural_repair(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
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


def test_research_objective_service_skips_matrix_test_condition_table_fallback(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
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
    route = EvidenceCandidate.from_mapping(
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
    route = EvidenceCandidate.from_mapping(
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
    corrosion_route = EvidenceCandidate.from_mapping(
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

    eis_route = EvidenceCandidate.from_mapping(
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


def test_research_objective_service_skips_non_target_result_property_columns(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
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
    objective_context = _research_objective(
        {
            "objective_id": "obj-preheat",
            "outcomes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
        }
    )

    records = service._objective_table_matrix_evidence_records(
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


def test_research_objective_service_uses_objective_scientific_intent_directly(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-corrosion",
            "question": (
                "How do laser power, porosity, and pore size affect pitting "
                "corrosion behavior of SLM 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power"],
            "outcomes": ["pitting potential"],
            "mechanisms": ["porosity", "pore size"],
            "constraints": ["SLM"],
            "requested_comparator": "lower laser power",
        }
    )

    assert service._route_prompt_objective_record(objective) == {
        "objective_id": "obj-corrosion",
        "question": objective.question,
        "material_scope": ["316L stainless steel"],
        "variables": ["laser power"],
        "outcomes": ["pitting potential"],
        "mechanisms": ["porosity", "pore size"],
        "constraints": ["SLM"],
        "requested_comparator": "lower laser power",
    }


def test_research_objective_service_routes_matching_tables_beyond_seed_documents(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does volumetric energy density affect density?",
            "material_scope": ["316L stainless steel"],
            "variables": ["volumetric energy density"],
            "outcomes": ["density"],
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
    )

    assert {
        (hint.document_id, hint.table_id, hint.role)
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
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does scan speed affect density?",
            "material_scope": ["316L stainless steel"],
            "variables": ["scan speed"],
            "outcomes": ["density"],
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
    )

    assert hints == ()


def test_research_objective_service_treats_energy_density_only_table_as_condition(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How do laser power and scan speed affect density?",
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power", "scan speed"],
            "outcomes": ["density"],
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
    )

    assert len(hints) == 1
    assert hints[0].role == "condition_context"
    assert hints[0].matched_outcomes == ()


def test_research_objective_service_normalizes_archimedes_density_column(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does volumetric energy density affect density?",
            "outcomes": ["density"],
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
    objective = _research_objective(
        {
            "objective_id": "obj-microstructure",
            "question": "How does heat treatment affect microstructure?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["microstructure"],
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
    )

    assert hints == ()


def test_research_objective_service_recovers_non_seed_condition_and_result_routes(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-mechanical",
            "question": "How do LPBF parameters affect tensile properties?",
            "material_scope": ["316L stainless steel"],
            "variables": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
                "hatch spacing",
            ],
            "outcomes": [
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
    )
    objective_context = _research_objective(
        {
            "objective_id": objective.objective_id,
            "question": objective.question,
            "material_scope": list(objective.material_scope),
            "variables": list(objective.variables),
            "outcomes": list(objective.outcomes),
            "routing_hints": hints,
            "confidence": 0.9,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-independent",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": list(objective.variables),
            "measured_property_scope": list(objective.outcomes),
            "relevant_tables": [],
            "excluded_tables": ["table-conditions", "table-results"],
        }
    )

    routes = service._build_objective_evidence_routes(
        collection_id="col-test",
        extractor=_ObjectiveExtractor(),
        objectives=(objective,),
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
    objective = _research_objective(
        {
            "objective_id": "obj-corrosion",
            "question": (
                "How do laser power and energy density affect pitting corrosion "
                "behavior of SLM 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power", "energy density"],
            "outcomes": ["pitting corrosion behavior"],
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
    )

    assert {
        (hint.table_id, hint.role, hint.matched_outcomes)
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
    objective = _research_objective(
        {
            "objective_id": "obj-fatigue",
            "question": (
                "How does volumetric energy density affect defect structure and "
                "fatigue strength of LPBF 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["volumetric energy density"],
            "outcomes": ["defect structure", "fatigue strength"],
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
    )

    assert all(hint.role != "result_table" for hint in hints)


def test_research_objective_service_route_payload_uses_objective_contract(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    context = _research_objective(
        {
            "objective_id": "obj-corrosion",
            "question": "How does porosity affect pitting corrosion?",
            "outcomes": ["pitting potential"],
            "mechanisms": ["porosity"],
        }
    )

    payload = service._route_prompt_objective_record(context)

    assert payload["outcomes"] == ["pitting potential"]
    assert payload["mechanisms"] == ["porosity"]
    assert "objective_evidence_lens" not in payload


def test_process_route_does_not_treat_result_columns_as_process_context(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-fatigue",
            "variables": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
                "hatch spacing",
                "layer thickness",
            ],
            "outcomes": ["defect structure", "fatigue strength"],
        }
    )
    misrouted_result_table = EvidenceCandidate.from_mapping(
        {
            "source_ref": "route-misclassified-results",
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

    records = service._objective_table_matrix_evidence_records(
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


def test_research_objective_service_adds_context_hint_route_for_condition_table(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "relevant_tables": ["table-2"],
            "excluded_tables": ["table-1"],
        }
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-mechanical",
            "question": "How do processing parameters affect yield strength?",
            "variables": [
                "energy density",
                "scanning strategy",
                "scanning speed",
            ],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    routes: list[EvidenceCandidate] = []

    service._append_objective_context_hint_routes(
        routes=routes,
        seen=set(),
        frame=frame,
        objective_context=objective_context,
        routing_hints=(
            SourceSelectionHint.from_mapping(
                {
                    "document_id": "paper-1",
                    "table_id": "table-1",
                    "role": "condition_context",
                    "reason": "Table contains process variables.",
                }
            ),
        ),
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
    frame = PaperAnalysisFrame.from_mapping(
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
    objective_context = _research_objective(
        {
            "objective_id": "obj-structure",
            "material_scope": ["316L stainless steel"],
            "variables": ["scanning speed", "energy density"],
            "outcomes": ["microstructure", "densification"],
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

    routes: list[EvidenceCandidate] = []
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
    frame = PaperAnalysisFrame.from_mapping(
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
    objective_context = _research_objective(
        {
            "objective_id": "obj-corrosion",
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power"],
            "constraints": ["SLM"],
            "outcomes": ["pitting potential"],
            "mechanisms": ["porosity", "pore size", "lack of fusion"],
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
    routes: list[EvidenceCandidate] = []

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
    objective = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
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
    objective = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
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
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": [table]},
        document_trees_by_document_id={},
    )

    assert len(extractor.route_payloads) == 1
    assert extractor.route_payloads[0]["current_source"]["source_ref"] == "table-1"
    assert {
        (route.source_kind, route.source_ref, route.role)
        for route in routes
    } == {
        ("table", "table-1", "current_experimental_evidence"),
        ("table", "table-1", "process_or_treatment"),
    }
    result_route = next(
        route for route in routes if route.role == "current_experimental_evidence"
    )
    assert result_route.join_plan["evidence_role"] == "direct_support"


def test_research_objective_routing_uses_compact_prompt_payload(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["yield strength"],
            "requested_comparator": "compare treated and untreated samples",
            "confidence": 0.9,
        }
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": objective.question,
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "constraints": ["LPBF"],
            "outcomes": ["yield strength"],
            "routing_hints": [
                {
                    "table_id": "table-1",
                    "role": "result_table",
                    "reason": "Large hint text should not enter routing prompt.",
                }
            ],
            "confidence": 0.8,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
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
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": [table]},
        document_trees_by_document_id={},
    )

    route_payload = extractor.route_payloads[0]
    assert "routing_hints" not in route_payload["objective"]
    assert "extraction_guidance" not in route_payload["objective"]
    assert "objective_context" not in route_payload
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
    objective = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
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
    objective = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
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
    objective = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
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
    objective = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
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
    objective = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
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
    frame = PaperAnalysisFrame.from_mapping(
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
    service.finding_synthesis_service.structured_extractor = extractor
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
        objectives = service.build_objective_candidates(
            collection_id,
            build_id="build_test",
        )

    assert len(objectives) == 1
    assert objectives[0].question.startswith("How does heat treatment")
    facts = service.objective_repository.read(collection_id)
    assert facts.research_objectives_ready is True
    assert len(facts.paper_skims) == 2
    assert facts.paper_skims[0].source_filename == "paper-1.pdf"
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
        "changed_variables",
        "candidate_properties",
        "possible_objectives",
    }
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
    skim_call_count = len(extractor.skim_payloads)
    assert service.read_research_objectives(collection_id) == objectives
    assert len(extractor.skim_payloads) == skim_call_count
    output_dir = collection_service.get_paths(collection_id).output_dir
    assert not list(output_dir.glob("*objective*"))


def test_research_objective_service_preserves_discovered_scientific_intent(tmp_path):
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

    objectives = service.build_objective_candidates(
        collection_id,
        build_id="build_test",
    )

    assert len(objectives) == 1
    objective = objectives[0]
    assert objective.variables == ("processing parameters",)
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

    objectives = service.build_objective_candidates(
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

    objectives = service.build_objective_candidates(
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
    assert service._structured_extractor.frame_payloads == []
    assert service._structured_extractor.route_payloads == []
    assert service._structured_extractor.unit_payloads == []


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


def test_research_objective_service_does_not_global_fill_unmatched_seed_axes(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _UnmatchedSeedObjectiveExtractor(),
    )

    assert len(objectives) == 1
    objective = objectives[0]
    assert objective.variables == ("heat treatment",)
    assert objective.outcomes == ("mechanical properties",)
    assert objective.constraints == ("Selective Laser Melting",)


def test_research_objective_service_keeps_candidate_definition_as_source_of_truth(
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

    objectives = service.build_objective_candidates(
        collection_id,
        build_id="build_test",
    )

    assert service.objective_repository.list_objectives(collection_id) == objectives
    assert objectives[0].confirmation_status == "candidate"
    assert objectives[0].active_analysis_version is None
    assert objectives[0].published_analysis_version is None


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


def test_research_objective_service_preserves_single_mixed_property_objective(
    tmp_path,
):
    objectives = _build_duplicate_paper_objectives(
        tmp_path,
        _SingleMixedObjectiveExtractor(),
    )

    assert len(objectives) == 1
    assert objectives[0].outcomes == (
        "densification",
        "microstructure",
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    )


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

    objectives = service.build_objective_candidates(
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
    service.finding_synthesis_service.structured_extractor = extractor
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

    artifacts = service.analyze_objective(collection_id, analysis)

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
        structured_extractor=_ObjectiveExtractor(),
    )
    service.finding_synthesis_service.structured_extractor = service._structured_extractor
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
    service._structured_extractor = failing_extractor
    service.finding_synthesis_service.structured_extractor = failing_extractor
    artifacts = service.analyze_objective(collection_id, analysis)

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
        structured_extractor=extractor,
    )
    service.finding_synthesis_service.structured_extractor = extractor
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

    artifacts = service.analyze_objective(collection_id, analysis)

    facts = service.objective_repository.read(collection_id)
    assert extractor.frame_payloads
    assert extractor.route_payloads
    assert facts == active_facts
    assert artifacts.contributions


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
    return service.build_objective_candidates(
        collection_id,
        build_id="build_test",
    )
