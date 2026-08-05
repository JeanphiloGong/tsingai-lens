from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from application.core.objectives.evidence_extraction import ExtractedEvidenceDraft
from application.core.objectives.evidence_routing import EvidenceCandidate
from application.core.objectives.schemas import (
    StructuredEvidenceExtraction,
    StructuredEvidenceExtractions,
)
from domain.core import ObjectiveAnalysis
from tests.support.collection_service import build_test_collection_service
from tests.support.research_objective_service import (
    build_research_objective_service as _build_research_objective_service,
    research_objective as _research_objective,
)


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
                    text=(
                        "Laser power was 150 W in the methods."
                        if source_ref == "paper-1-methods"
                        else (
                            "Laser power increased from 150 W to 200 W, and relative "
                            "density increased from 96.1% to 99.2%."
                        )
                    ),
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
        paper_skims=(),
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
            text=f"Source text for {source_ref}. Test temperature was 25 C.",
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
        paper_skims=(),
        objective_paper_frames=(),
        objective_evidence_routes=routes,
        blocks_by_document_id={"paper-1": blocks},
        tables_by_document_id={},
        document_trees_by_document_id={},
    )

    assert extractor.calls == 2
    assert len(units) == 1
    assert units[0].source_ref == "block-recovered"


def test_objective_context_drops_model_changed_variable_without_values(tmp_path):
    class ContextExtractor:
        def extract_objective_evidence(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
                        evidence_role="condition_context",
                        changed_variables=[
                            {"name": "build platform preheating temperature"}
                        ],
                        attribution_scope="descriptive_only",
                        scientific_context={
                            "process": [
                                {
                                    "name": "build platform preheating temperature",
                                    "value": 150,
                                    "unit": "C",
                                }
                            ]
                        },
                        resolution_status="resolved",
                        confidence=0.8,
                    )
                ]
            )

    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-preheating",
            "variables": ["build platform preheating temperature"],
            "outcomes": ["microstructure"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-context",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    block = SimpleNamespace(
        block_id="block-context",
        text="The build platform preheating temperature was 150 C.",
        page=2,
        block_type="paragraph",
        heading_path="Methods",
    )

    units = service._build_objective_evidence(
        collection_id="col-test",
        extractor=ContextExtractor(),
        objectives=(objective,),
        paper_skims=(),
        objective_paper_frames=(),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={},
        document_trees_by_document_id={},
    )

    assert len(units) == 1
    assert units[0].changed_variables == ()
    assert units[0].comparison is None
    assert units[0].scientific_context.process[0].value == 150


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


def test_pairwise_comparison_joins_process_and_result_tables_by_sample_label(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )

    def process_context(
        evidence_id: str,
        sample_label: str,
        *,
        ved: float,
        laser_power: int,
        scanning_speed: int,
        hatch_spacing: int,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-defect",
                "document_id": "paper-ved",
                "source_kind": "table",
                "source_ref": "table-process",
                "evidence_role": "condition_context",
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "sample": [{"name": "ID", "value": sample_label}],
                    "process": [
                        {
                            "name": "volumetric energy density",
                            "value": ved,
                            "unit": "J/mm3",
                        },
                        {"name": "laser power", "value": laser_power, "unit": "W"},
                        {
                            "name": "scanning speed",
                            "value": scanning_speed,
                            "unit": "mm/s",
                        },
                        {
                            "name": "hatch spacing",
                            "value": hatch_spacing,
                            "unit": "um",
                        },
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-process",
                        "source_excerpt": f"ID: {sample_label} | VED: {ved}",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    def defect_result(
        evidence_id: str,
        sample_label: str,
        defect_length: int,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-defect",
                "document_id": "paper-ved",
                "source_kind": "table",
                "source_ref": "table-defect",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "max defect length",
                    "value": defect_length,
                    "unit": "um",
                    "direction": "unknown",
                    "result_text": f"Max defect length = {defect_length} um.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [
                        {"name": "Printed 316L", "value": sample_label}
                    ]
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-defect",
                        "source_excerpt": (
                            f"Printed 316L: {sample_label} | Max defect length: "
                            f"{defect_length}"
                        ),
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    units = (
        process_context(
            "process-low",
            "L-VED",
            ved=50.8,
            laser_power=160,
            scanning_speed=875,
            hatch_spacing=120,
        ),
        process_context(
            "process-high",
            "H-VED",
            ved=84.3,
            laser_power=220,
            scanning_speed=725,
            hatch_spacing=120,
        ),
        defect_result("defect-low", "L-VED", 394),
        defect_result("defect-high", "H-VED", 86),
    )

    bound_units = service._bind_objective_result_process_context(units)
    comparisons = service._build_objective_pairwise_comparison_units(
        bound_units,
        objectives=(),
    )

    assert {
        item.name for item in bound_units[2].scientific_context.process
    } == {
        "volumetric energy density",
        "laser power",
        "scanning speed",
        "hatch spacing",
    }
    assert {ref["source_ref"] for ref in bound_units[2].source_refs} == {
        "table-process",
        "table-defect",
    }
    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.attribution_scope == "joint_effect"
    assert {item.name for item in comparison.changed_variables} == {
        "volumetric energy density",
        "laser power",
        "scanning speed",
    }


def test_text_result_process_binding_requires_exact_groups_and_expands_axes(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )

    def process_context(
        evidence_id: str,
        sample_label: str,
        *,
        ved: float,
        laser_power: int,
        scanning_speed: int,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-defect",
                "document_id": "paper-ved",
                "source_kind": "table",
                "source_ref": "table-process",
                "evidence_role": "condition_context",
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "sample": [{"name": "ID", "value": sample_label}],
                    "process": [
                        {
                            "name": "volumetric energy density",
                            "value": ved,
                            "unit": "J/mm3",
                        },
                        {"name": "laser power", "value": laser_power, "unit": "W"},
                        {
                            "name": "scanning speed",
                            "value": scanning_speed,
                            "unit": "mm/s",
                        },
                        {"name": "hatch spacing", "value": 120, "unit": "um"},
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-process",
                        "source_excerpt": f"ID: {sample_label} | VED: {ved}",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    def text_result(
        evidence_id: str,
        baseline_label: str,
        target_label: str,
        source_excerpt: str,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-defect",
                "document_id": "paper-ved",
                "source_kind": "text_window",
                "source_ref": evidence_id,
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "volumetric energy density",
                        "baseline_value": baseline_label,
                        "target_value": target_label,
                    }
                ],
                "comparison": {
                    "baseline_label": baseline_label,
                    "target_label": target_label,
                    "axis_names": ["volumetric energy density"],
                    "comparable": True,
                },
                "reported_result": {
                    "outcome": "defect structure",
                    "value": None,
                    "unit": None,
                    "direction": "decrease",
                    "result_text": "Maximum defect sizes decrease with increasing VED.",
                },
                "attribution_scope": "isolated_effect",
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": evidence_id,
                        "source_excerpt": source_excerpt,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        )

    units = service._bind_objective_result_process_context(
        (
            process_context(
                "process-low",
                "L-VED",
                ved=50.8,
                laser_power=160,
                scanning_speed=875,
            ),
            process_context(
                "process-high",
                "H-VED",
                ved=84.3,
                laser_power=220,
                scanning_speed=725,
            ),
            text_result(
                "block-defects",
                "L-VED",
                "H-VED",
                "Maximum defect sizes decrease from L-VED to H-VED.",
            ),
            text_result(
                "block-fatigue",
                "high",
                "low",
                (
                    "The high VED structure had the largest defect. All structures "
                    "exhibited a low fatigue limit."
                ),
            ),
        )
    )

    grounded = units[2]
    assert grounded.attribution_scope == "joint_effect"
    assert {
        item.name for item in grounded.changed_variables
    } == {
        "volumetric energy density",
        "laser power",
        "scanning speed",
    }
    assert grounded.comparison is not None
    assert set(grounded.comparison.axis_names) == {
        "volumetric energy density",
        "laser power",
        "scanning speed",
    }
    assert {
        item.name for item in grounded.scientific_context.process
    } == {"hatch spacing"}
    assert {ref["source_ref"] for ref in grounded.source_refs} == {
        "block-defects",
        "table-process",
    }

    ungrounded = units[3]
    assert ungrounded.attribution_scope == "not_attributable"
    assert ungrounded.changed_variables == ()
    assert ungrounded.comparison is not None
    assert not ungrounded.comparison.comparable
    assert ungrounded.comparison.incomparability_reasons == (
        "comparison groups do not bind to source process conditions",
    )


def test_process_result_table_join_rejects_conflicting_sample_context(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    context_payload = {
        "objective_id": "obj-defect",
        "document_id": "paper-ved",
        "source_kind": "table",
        "evidence_role": "condition_context",
        "attribution_scope": "not_attributable",
        "scientific_context": {
            "sample": [{"name": "ID", "value": "L-VED"}],
        },
        "source_refs": [{"source_kind": "table", "source_ref": "table-process"}],
        "resolution_status": "resolved",
    }
    first_context = ExtractedEvidenceDraft.from_mapping(
        {
            **context_payload,
            "evidence_id": "process-low-a",
            "scientific_context": {
                **context_payload["scientific_context"],
                "process": [{"name": "laser power", "value": 160, "unit": "W"}],
            },
        }
    )
    conflicting_context = ExtractedEvidenceDraft.from_mapping(
        {
            **context_payload,
            "evidence_id": "process-low-b",
            "scientific_context": {
                **context_payload["scientific_context"],
                "process": [{"name": "laser power", "value": 190, "unit": "W"}],
            },
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "defect-low",
            "objective_id": "obj-defect",
            "document_id": "paper-ved",
            "source_kind": "table",
            "source_ref": "table-defect",
            "evidence_role": "direct_result",
            "reported_result": {
                "outcome": "max defect length",
                "value": 394,
                "unit": "um",
                "direction": "unknown",
                "result_text": "Max defect length = 394 um.",
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {
                "sample": [{"name": "Printed 316L", "value": "L-VED"}]
            },
            "source_refs": [{"source_kind": "table", "source_ref": "table-defect"}],
            "resolution_status": "resolved",
        }
    )

    bound = service._bind_objective_result_process_context(
        (first_context, conflicting_context, result)
    )

    assert bound[2] == result


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
    assert comparison.scientific_context.to_record() == {
        "material": [],
        "sample": [],
        "process": [{"name": "laser power", "value": 200, "unit": "W"}],
        "test": [],
    }


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


def test_pairwise_comparison_keeps_semantic_values_from_generic_sample_column(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )

    def result(evidence_id: str, sample: str, energy_density: int, strength: float):
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
                    "value": strength,
                    "unit": "MPa",
                    "direction": "unknown",
                    "result_text": f"Yield strength = {strength} MPa.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "Sample", "value": sample}],
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
            result("as-slm", "as-SLM", 194, 426.7),
            result("hip-slm", "HIP-SLM", 167, 265.1),
        ),
        objectives=(),
    )[0]

    assert comparison.attribution_scope == "not_attributable"
    assert comparison.comparison is not None
    assert any(
        "sample condition differs for Sample" in reason
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
