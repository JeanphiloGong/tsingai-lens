from __future__ import annotations

import json
from typing import Any

import application.core.research_understanding_service as research_understanding_module
from application.core.research_understanding_service import (
    ResearchUnderstandingService,
)


class _EmptySourceArtifactRepository:
    def list_blocks(self, collection_id: str) -> list[Any]:
        return []

    def list_documents(self, collection_id: str) -> list[Any]:
        return []

    def list_tables(self, collection_id: str) -> list[Any]:
        return []


class _ModelItem:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def model_dump(self) -> dict[str, Any]:
        return dict(self.payload)


class _ModelFindings:
    def __init__(self, findings: list[dict[str, Any]]) -> None:
        self.findings = [_ModelItem(item) for item in findings]


class _FindingSynthesisExtractor:
    def __init__(self, findings: list[dict[str, Any]]) -> None:
        self.findings = findings
        self.payloads: list[dict[str, Any]] = []

    def synthesize_research_understanding_findings(
        self,
        payload: dict[str, Any],
    ) -> _ModelFindings:
        self.payloads.append(payload)
        return _ModelFindings(self.findings)

    def extract_research_understanding_relations(self, payload: dict[str, Any]):
        raise AssertionError("goal Finding synthesis must not use relation extraction")

    def consume_last_trace(self):
        return None


def _evidence_unit(
    unit_id: str,
    document_id: str,
    *,
    statement: str,
    direction: str,
    process: str = "LPBF",
) -> dict[str, Any]:
    return {
        "evidence_unit_id": unit_id,
        "objective_id": "obj-density",
        "document_id": document_id,
        "unit_kind": "comparison",
        "property_normalized": "relative density",
        "material_system": {"name": "316L stainless steel"},
        "sample_context": {},
        "process_context": {"process": process, "variable": "energy density"},
        "resolved_condition": {},
        "test_condition": {"method": "Archimedes"},
        "value_payload": {
            "statement": statement,
            "direction": direction,
        },
        "unit": "%",
        "baseline_context": {},
        "interpretation": statement,
        "source_refs": [
            {
                "source_kind": "text_window",
                "source_ref": f"block-{unit_id}",
                "document_id": document_id,
                "display_label": f"{document_id} Results",
                "quote": statement,
                "evidence_role": "direct_support",
            }
        ],
        "evidence_anchor_ids": [],
        "join_keys": {},
        "resolution_status": "resolved",
        "confidence": 0.9,
    }


def _context_unit(
    unit_id: str,
    document_id: str,
    *,
    unit_kind: str,
    statement: str,
    evidence_role: str = "direct_support",
) -> dict[str, Any]:
    return {
        "evidence_unit_id": unit_id,
        "objective_id": "obj-density",
        "document_id": document_id,
        "unit_kind": unit_kind,
        "property_normalized": "fatigue strength",
        "material_system": {"name": "316L stainless steel"},
        "sample_context": {},
        "process_context": {},
        "resolved_condition": {},
        "test_condition": {},
        "value_payload": {"statement": statement},
        "unit": None,
        "baseline_context": {},
        "interpretation": statement,
        "source_refs": [
            {
                "source_kind": "text_window",
                "source_ref": f"block-{unit_id}",
                "document_id": document_id,
                "display_label": f"{document_id} Discussion",
                "quote": statement,
                "evidence_role": evidence_role,
            }
        ],
        "evidence_anchor_ids": [],
        "join_keys": {},
        "resolution_status": "resolved",
        "confidence": 0.9,
    }


def _payload(evidence_units: list[dict[str, Any]]) -> dict[str, Any]:
    document_ids = list(dict.fromkeys(unit["document_id"] for unit in evidence_units))
    return {
        "collection_id": "col-1",
        "goal_id": "goal-density",
        "objective": {
            "objective_id": "obj-density",
            "question": "How does energy density affect relative density?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["energy density"],
            "property_axes": ["relative density"],
        },
        "objective_context": {
            "objective_id": "obj-density",
            "question": "How does energy density affect relative density?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["energy density"],
            "target_property_axes": ["relative density"],
        },
        "paper_frames": [
            {
                "document_id": document_id,
                "title": f"Study {document_id}",
                "source_filename": f"{document_id}.pdf",
                "relevance": "high",
                "paper_role": "primary_experiment",
                "material_match": ["316L stainless steel"],
                "changed_variables": ["energy density"],
                "measured_property_scope": ["relative density"],
                "test_environment_scope": ["Archimedes"],
            }
            for document_id in document_ids
        ],
        "evidence_routes": [],
        "evidence_units": evidence_units,
        "logic_chain": {
            "evidence_unit_ids": [
                unit["evidence_unit_id"] for unit in evidence_units
            ]
        },
    }


def _service(findings: list[dict[str, Any]]) -> tuple[
    ResearchUnderstandingService,
    _FindingSynthesisExtractor,
]:
    extractor = _FindingSynthesisExtractor(findings)
    return (
        ResearchUnderstandingService(
            source_artifact_repository=_EmptySourceArtifactRepository(),
            structured_extractor=extractor,
        ),
        extractor,
    )


def _result_units(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        unit
        for result_set in payload["result_sets"]
        for paper in result_set["document_evidence"]
        for unit in paper["result_units"]
    ]


def _model_finding(
    *,
    synthesis_status: str,
    supporting_ids: list[str],
    conflicting_ids: list[str] | None = None,
    context_ids: list[str] | None = None,
    mechanism_ids: list[str] | None = None,
    common_conditions: list[str] | None = None,
    incomparable_conditions: list[str] | None = None,
    target_concept: str = "relative density",
    direction: str | None = None,
    outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    outcome_direction = direction or (
        "mixed" if synthesis_status == "conflict" else "increases"
    )
    return {
        "result_set_id": "result_set_1",
        "source_concept": "energy density",
        "outcomes": outcomes
        or [
            {
                "concept": target_concept,
                "direction": outcome_direction,
                "statement": f"Energy density changes {target_concept}.",
                "supporting_evidence_unit_ids": supporting_ids,
                "conflicting_evidence_unit_ids": conflicting_ids or [],
            }
        ],
        "mediator_concepts": ["melt-pool stability"],
        "statement": (
            "Within comparable LPBF 316L conditions, higher energy density "
            "generally increased relative density."
        ),
        "synthesis_status": synthesis_status,
        "context_evidence_unit_ids": context_ids or [],
        "mechanism_evidence_unit_ids": mechanism_ids or [],
        "common_conditions": common_conditions or ["LPBF 316L", "Archimedes density"],
        "incomparable_conditions": incomparable_conditions or [],
        "confidence": 0.88,
        "warnings": [],
    }


def test_goal_synthesis_preserves_one_composite_single_paper_finding():
    defect = _evidence_unit(
        "unit-defect",
        "paper-ved",
        statement="The maximum defect length decreased from 394 um to 86 um.",
        direction="decreases",
    )
    defect["property_normalized"] = "maximum defect length"
    defect["value_payload"]["comparison_axis"] = "laser power, scanning speed"
    fatigue_strength = _evidence_unit(
        "unit-fatigue-strength",
        "paper-ved",
        statement=(
            "Fatigue strength at 10^4 cycles increased from 340 MPa to 470 MPa."
        ),
        direction="increases",
    )
    fatigue_strength["property_normalized"] = "fatigue strength at 10^4 cycles"
    fatigue_strength["value_payload"]["comparison_axis"] = (
        "laser power, scanning speed"
    )
    fatigue_limit = _evidence_unit(
        "unit-fatigue-limit",
        "paper-ved",
        statement="The fatigue limit increased from 93 MPa to 97 MPa.",
        direction="increases",
    )
    fatigue_limit["property_normalized"] = "HCF fatigue limit"
    fatigue_limit["value_payload"]["comparison_axis"] = "laser power, scanning speed"
    for unit, baseline_value, current_value, unit_text in (
        (defect, 394, 86, "um"),
        (fatigue_strength, 340, 470, "MPa"),
        (fatigue_limit, 93, 97, "MPa"),
    ):
        unit["process_context"] = {
            "VED [J/mm3]": "84.3",
            "Laser power [W]": "220",
            "Scanning speed [mm/s]": "725",
        }
        unit["baseline_context"] = {
            "process_context": {
                "VED [J/mm3]": "50.8",
                "Laser power [W]": "160",
                "Scanning speed [mm/s]": "875",
            },
            "source_value_text": str(baseline_value),
            "value": baseline_value,
        }
        unit["value_payload"].update(
            {
                "source_value_text": str(current_value),
                "value": current_value,
            }
        )
        unit["unit"] = unit_text
    author_interpretation = _context_unit(
        "unit-author-interpretation",
        "paper-ved",
        unit_kind="interpretation",
        statement=(
            "The closely clustered 80-100 MPa fatigue limits indicate only a "
            "small HCF improvement with increasing VED."
        ),
    )
    mechanism = _context_unit(
        "unit-mechanism",
        "paper-ved",
        unit_kind="mechanism",
        statement=(
            "The authors attributed the LCF improvement to fewer defects and "
            "greater ductility."
        ),
        evidence_role="mediator_context",
    )
    payload = _payload(
        [
            defect,
            fatigue_strength,
            fatigue_limit,
            author_interpretation,
            mechanism,
        ]
    )
    payload["objective"].update(
        {
            "question": (
                "How do coupled LPBF parameters affect defects and fatigue "
                "performance?"
            ),
            "process_axes": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
                "hatch spacing",
                "layer thickness",
            ],
            "property_axes": ["defect structure", "fatigue strength"],
        }
    )
    payload["objective_context"].update(
        {
            "question": payload["objective"]["question"],
            "variable_process_axes": payload["objective"]["process_axes"],
            "target_property_axes": payload["objective"]["property_axes"],
        }
    )
    payload["paper_frames"][0].update(
        {
            "changed_variables": ["laser power", "scanning speed"],
            "measured_property_scope": ["defect structure", "fatigue strength"],
        }
    )
    model_statement = (
        "Changing laser power and scanning speed affects defects and fatigue."
    )
    model_outcomes = [
        {
            "concept": "maximum defect length",
            "direction": "decreases",
            "statement": "Maximum defect length decreased from 394 um to 86 um.",
            "supporting_evidence_unit_ids": ["unit-defect"],
            "conflicting_evidence_unit_ids": [],
        },
        {
            "concept": "fatigue strength at 10^4 cycles",
            "direction": "increases",
            "statement": (
                "Fatigue strength at 10^4 cycles increased from 340 MPa to "
                "470 MPa."
            ),
            "supporting_evidence_unit_ids": ["unit-fatigue-strength"],
            "conflicting_evidence_unit_ids": [],
        },
        {
            "concept": "HCF fatigue limit",
            "direction": "changes",
            "statement": "HCF fatigue limits remained at 80-100 MPa.",
            "supporting_evidence_unit_ids": ["unit-fatigue-limit"],
            "conflicting_evidence_unit_ids": [],
        },
    ]
    model_finding = {
        **_model_finding(
            synthesis_status="agreement",
            supporting_ids=[
                "unit-defect",
                "unit-fatigue-strength",
                "unit-fatigue-limit",
            ],
            context_ids=[],
            outcomes=model_outcomes,
        ),
        "source_concept": (
            "Changes in laser power and scanning speed under fixed hatch "
            "spacing and layer thickness"
        ),
        "mediator_concepts": [],
        "statement": model_statement,
    }
    service, extractor = _service(
        [
            {
                **model_finding,
                "outcomes": [
                    {
                        **model_outcomes[0],
                        "concept": "defect structure",
                    },
                    *list(reversed(model_outcomes[1:])),
                ],
                "statement": "The same result set was returned in another order.",
            },
            model_finding,
        ]
    )

    understanding = service.build_goal_understanding(payload)

    context_payload = extractor.payloads[0]["document_context"]
    assert {
        unit["evidence_unit_id"]
        for document in context_payload
        for unit in document["context_units"]
    } == {"unit-author-interpretation", "unit-mechanism"}
    assert len(understanding["presentation"]["findings"]) == 1
    finding = understanding["presentation"]["findings"][0]
    assert finding["statement"] == (
        "The higher VED coupled parameter combination (laser power and scanning "
        "speed) reduced maximum defect length from 394 um to 86 um and increased "
        "fatigue strength at 10^4 cycles from 340 MPa to 470 MPa. However, the "
        "high-cycle fatigue limit remained concentrated in the 80-100 MPa range, "
        "indicating only limited improvement with VED. Reduced defects and higher "
        "ductility may explain the low-cycle fatigue improvement. This finding is "
        "directly supported by one paper."
    )
    assert "93 MPa to 97 MPa" not in finding["statement"]
    assert finding["variables"] == ["laser power and scanning speed"]
    assert finding["mediators"] == ["reduced defects", "ductility"]
    assert finding["paper_count"] == 1
    assert finding["synthesis_status"] == "insufficient_confirmation"
    assert finding["generalization_status"] == "paper_level_only"
    assert len(finding["evidence_bundle"]["direct_result"]) == 3
    assert len(finding["evidence_bundle"]["condition_context"]) == 1
    assert len(finding["evidence_bundle"]["mechanism"]) == 1


def test_goal_synthesis_aligns_one_multi_outcome_condition_contrast():
    fatigue_limit = _evidence_unit(
        "unit-fatigue-limit",
        "paper-ved",
        statement="Fatigue limit increased from 93 MPa to 97 MPa.",
        direction="increases",
    )
    fatigue_limit["property_normalized"] = "fatigue limit"
    fatigue_strength = _evidence_unit(
        "unit-fatigue-strength",
        "paper-ved",
        statement="Fatigue strength increased from 340 MPa to 470 MPa.",
        direction="increases",
    )
    fatigue_strength["property_normalized"] = "fatigue strength"
    defect = _evidence_unit(
        "unit-defect",
        "paper-ved",
        statement="Maximum defect length increased from 86 um to 394 um.",
        direction="increases",
    )
    defect["property_normalized"] = "maximum defect length"
    dominated = _evidence_unit(
        "unit-middle-fatigue",
        "paper-ved",
        statement="Fatigue strength increased from 340 MPa to 450 MPa.",
        direction="increases",
    )
    dominated["property_normalized"] = "fatigue strength"

    low = {
        "VED [J/mm3]": "50.8",
        "Laser power [W]": "160",
        "Scanning speed [mm/s]": "875",
        "Hatch spacing [um]": "120",
        "Layer thickness [um]": "30",
    }
    high = {
        "VED [J/mm3]": "84.3",
        "Laser power [W]": "220",
        "Scanning speed [mm/s]": "725",
        "Hatch spacing [um]": "120",
        "Layer thickness [um]": "30",
    }
    middle = {
        "VED [J/mm3]": "79.4",
        "Laser power [W]": "190",
        "Scanning speed [mm/s]": "800",
        "Hatch spacing [um]": "100",
        "Layer thickness [um]": "30",
    }
    for unit, baseline, current, value, baseline_value, axes in (
        (fatigue_limit, low, high, 97, 93, "laser power, scanning speed"),
        (fatigue_strength, low, high, 470, 340, "laser power, scanning speed"),
        (defect, high, low, 394, 86, "laser power, scanning speed"),
        (
            dominated,
            low,
            middle,
            450,
            340,
            "laser power, scanning speed, hatch spacing",
        ),
    ):
        unit["process_context"] = current
        unit["baseline_context"] = {
            "process_context": baseline,
            "source_value_text": str(baseline_value),
            "value": baseline_value,
        }
        unit["value_payload"].update(
            {
                "comparison_axis": axes,
                "source_value_text": str(value),
                "value": value,
                "direction": "increase",
            }
        )
        unit["unit"] = "MPa" if "fatigue" in unit["property_normalized"] else "um"

    payload = _payload([fatigue_limit, fatigue_strength, defect, dominated])
    payload["objective"].update(
        {
            "process_axes": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
                "hatch spacing",
                "layer thickness",
            ],
            "property_axes": ["defect structure", "fatigue strength"],
        }
    )
    payload["objective_context"].update(
        {
            "variable_process_axes": payload["objective"]["process_axes"],
            "target_property_axes": payload["objective"]["property_axes"],
        }
    )
    service, extractor = _service([])

    service.build_goal_understanding(payload)

    assert len(extractor.payloads[0]["result_sets"]) == 1
    result_set = extractor.payloads[0]["result_sets"][0]
    assert result_set["source_axes"] == ["laser power", "scanning speed"]
    assert set(result_set["outcome_properties"]) == {
        "fatigue limit",
        "fatigue strength",
        "maximum defect length",
    }
    result_units = result_set["document_evidence"][0]["result_units"]
    assert {unit["evidence_unit_id"] for unit in result_units} == {
        "unit-fatigue-limit",
        "unit-fatigue-strength",
        "unit-defect",
    }
    normalized_defect = next(
        unit for unit in result_units if unit["evidence_unit_id"] == "unit-defect"
    )
    assert "decreased maximum defect length from 394 um to 86 um" in (
        normalized_defect["statement"].lower()
    )
    assert (
        extractor.payloads[0]["input_coverage"][
            "alignment_omitted_evidence_unit_count"
        ]
        == 1
    )


def test_goal_synthesis_context_from_noncontributing_paper_cannot_raise_paper_count():
    direct = _evidence_unit(
        "unit-direct",
        "paper-direct",
        statement="Increasing energy density increased fatigue strength.",
        direction="increases",
    )
    unrelated_context = _context_unit(
        "unit-other-paper-context",
        "paper-context-only",
        unit_kind="interpretation",
        statement="A second paper discusses fatigue mechanisms without a result.",
    )
    payload = _payload([direct, unrelated_context])
    service, extractor = _service(
        [
            _model_finding(
                synthesis_status="agreement",
                supporting_ids=["unit-direct"],
                context_ids=["unit-other-paper-context"],
            )
        ]
    )

    understanding = service.build_goal_understanding(payload)

    assert extractor.payloads[0]["document_context"] == []
    assert [
        frame["document_id"] for frame in extractor.payloads[0]["paper_frames"]
    ] == ["paper-direct"]
    assert extractor.payloads[0]["input_coverage"]["document_count"] == 2
    finding = understanding["presentation"]["findings"][0]
    assert finding["paper_count"] == 1
    assert finding["synthesis_status"] == "insufficient_confirmation"


def test_goal_synthesis_context_excerpt_does_not_repeat_compact_statement():
    direct = _evidence_unit(
        "unit-direct",
        "paper-direct",
        statement="Increasing energy density increased fatigue strength.",
        direction="increases",
    )
    context = _context_unit(
        "unit-context",
        "paper-direct",
        unit_kind="interpretation",
        statement=(
            "Fatigue strength is more related to ductility, which may explain "
            "the LCF improvement."
        ),
    )
    service, extractor = _service([])

    service.build_goal_understanding(_payload([direct, context]))

    context_unit = extractor.payloads[0]["document_context"][0]["context_units"][0]
    assert context_unit["source_excerpt"] == (
        "Fatigue strength is more related to ductility, which may explain "
        "the LCF improvement."
    )
    assert context_unit["context_role"] == "mechanism"
    assert "statement" not in context_unit
    assert "omitted_by_document" not in extractor.payloads[0]["input_coverage"]


def test_goal_synthesis_model_payload_omits_redundant_evidence_fields():
    direct = _evidence_unit(
        "unit-direct",
        "paper-direct",
        statement="Increasing energy density increased relative density.",
        direction="increases",
    )
    context = _context_unit(
        "unit-context",
        "paper-direct",
        unit_kind="interpretation",
        statement=" ".join(["Lower porosity improves load transfer."] * 40),
    )
    service, extractor = _service([])

    service.build_goal_understanding(_payload([direct, context]))

    model_payload = extractor.payloads[0]
    assert set(model_payload["paper_frames"][0]) == {
        "document_id",
        "material_match",
        "changed_variables",
        "test_conditions",
    }
    assert set(_result_units(model_payload)[0]) == {
        "evidence_unit_id",
        "unit_kind",
        "property_normalized",
        "source_axes",
        "direct_result",
        "statement",
        "unit",
    }
    context_excerpt = model_payload["document_context"][0]["context_units"][0][
        "source_excerpt"
    ]
    assert len(context_excerpt) <= 421


def test_goal_synthesis_does_not_combine_different_properties_across_papers():
    defect = _evidence_unit(
        "unit-defect-paper-one",
        "paper-one",
        statement="Higher energy density reduced defect size.",
        direction="decreases",
    )
    defect["property_normalized"] = "defect size"
    fatigue = _evidence_unit(
        "unit-fatigue-paper-two",
        "paper-two",
        statement="Higher energy density increased fatigue strength.",
        direction="increases",
    )
    fatigue["property_normalized"] = "fatigue strength"
    service, _ = _service(
        [
            {
                **_model_finding(
                    synthesis_status="agreement",
                    supporting_ids=[
                        "unit-defect-paper-one",
                        "unit-fatigue-paper-two",
                    ],
                    outcomes=[
                        {
                            "concept": "defect size",
                            "direction": "decreases",
                            "statement": "Higher energy density reduced defect size.",
                            "supporting_evidence_unit_ids": [
                                "unit-defect-paper-one"
                            ],
                            "conflicting_evidence_unit_ids": [],
                        },
                        {
                            "concept": "fatigue strength",
                            "direction": "increases",
                            "statement": (
                                "Higher energy density increased fatigue strength."
                            ),
                            "supporting_evidence_unit_ids": [
                                "unit-fatigue-paper-two"
                            ],
                            "conflicting_evidence_unit_ids": [],
                        },
                    ],
                ),
                "statement": (
                    "Higher energy density reduced defect size and increased "
                    "fatigue strength."
                ),
            }
        ]
    )

    understanding = service.build_goal_understanding(_payload([defect, fatigue]))

    assert understanding["presentation"]["findings"] == []


def test_goal_synthesis_builds_one_cross_paper_finding_from_two_direct_papers():
    units = [
        _evidence_unit(
            "unit-paper-1",
            "paper-1",
            statement="Increasing energy density increased relative density to 99.1%.",
            direction="increases",
        ),
        _evidence_unit(
            "unit-paper-2",
            "paper-2",
            statement="The higher-energy condition reached 99.6% relative density.",
            direction="increases",
        ),
    ]
    service, extractor = _service(
        [
            {
                **_model_finding(
                    synthesis_status="agreement",
                    supporting_ids=["unit-paper-1", "unit-paper-2"],
                ),
                "statement": (
                    "Energy density increased relative density from 90% to 100%."
                ),
            }
        ]
    )

    understanding = service.build_goal_understanding(_payload(units))

    finding = understanding["presentation"]["findings"][0]
    assert finding["synthesis_status"] == "agreement"
    assert finding["paper_count"] == 2
    assert finding["generalization_status"] == "scoped_cross_paper"
    assert {item["document_id"] for item in finding["paper_contributions"]} == {
        "paper-1",
        "paper-2",
    }
    assert finding["paper_contributions"][0]["title"] == "Study paper-1"
    assert finding["paper_contributions"][0]["source_filename"] == "paper-1.pdf"
    assert finding["paper_contributions"][0]["evidence_unit_ids"] == [
        "unit-paper-1"
    ]
    assert isinstance(
        finding["paper_contributions"][0]["evidence_ref_ids"],
        list,
    )
    assert len(finding["evidence_bundle"]["direct_result"]) == 2
    assert finding["evidence_bundle"]["conflict"] == []
    assert finding["common_conditions"] == ["LPBF 316L", "Archimedes density"]
    assert "99.1%" in finding["statement"]
    assert "99.6%" in finding["statement"]
    assert "90%" not in finding["statement"]
    result_set = extractor.payloads[0]["result_sets"][0]
    assert result_set["source_axes"] == ["energy density"]
    assert result_set["outcome_properties"] == ["relative density"]
    assert [
        paper["document_id"] for paper in result_set["document_evidence"]
    ] == ["paper-1", "paper-2"]


def test_goal_synthesis_backend_binds_all_result_set_evidence():
    units = [
        _evidence_unit(
            "unit-paper-1",
            "paper-1",
            statement="Increasing energy density increased density to 99.1%.",
            direction="increases",
        ),
        _evidence_unit(
            "unit-paper-2",
            "paper-2",
            statement="Increasing energy density increased density to 99.6%.",
            direction="increases",
        ),
    ]
    model_finding = _model_finding(
        synthesis_status="agreement",
        supporting_ids=["unit-paper-1"],
    )
    service, _ = _service([model_finding])

    understanding = service.build_goal_understanding(_payload(units))

    finding = understanding["presentation"]["findings"][0]
    assert finding["paper_count"] == 2
    assert {
        item["document_id"] for item in finding["paper_contributions"]
    } == {"paper-1", "paper-2"}


def test_goal_synthesis_groups_matching_relationships_across_documents():
    paper_one_speed = _evidence_unit(
        "unit-paper-1-speed",
        "paper-1",
        statement="Higher scan speed decreased density.",
        direction="decreases",
    )
    paper_one_speed["value_payload"]["comparison_axis"] = "scan speed"
    paper_two_laser = _evidence_unit(
        "unit-paper-2-laser",
        "paper-2",
        statement="Higher laser power increased density.",
        direction="increases",
    )
    paper_two_laser["value_payload"]["comparison_axis"] = "laser power"
    paper_two_speed = _evidence_unit(
        "unit-paper-2-speed",
        "paper-2",
        statement="Higher scan speed decreased density.",
        direction="decreases",
    )
    paper_two_speed["value_payload"]["comparison_axis"] = "scan speed"
    payload = _payload([paper_one_speed, paper_two_laser, paper_two_speed])
    payload["objective"]["process_axes"] = ["scan speed", "laser power"]
    payload["objective_context"]["variable_process_axes"] = [
        "scan speed",
        "laser power",
    ]
    service, extractor = _service([])

    service.build_goal_understanding(payload)

    result_sets = extractor.payloads[0]["result_sets"]
    by_source_axes = {
        tuple(result_set["source_axes"]): result_set for result_set in result_sets
    }
    speed_results = by_source_axes[("scan speed",)]
    assert speed_results["outcome_properties"] == ["relative density"]
    assert [
        paper["document_id"] for paper in speed_results["document_evidence"]
    ] == ["paper-1", "paper-2"]
    assert ("laser power",) in by_source_axes


def test_goal_synthesis_groups_comparison_contrasts_across_documents():
    comparisons = [
        (
            _evidence_unit(
                "unit-paper-1-strategy-b",
                "paper-1",
                statement=(
                    "Changing scan speed from 0.167 to 0.239 decreased relative "
                    "density from 96.1% to 92.4%."
                ),
                direction="decreases",
            ),
            "B",
            "0.167",
            "0.239",
            "96.1",
            "92.4",
        ),
        (
            _evidence_unit(
                "unit-paper-1-strategy-c",
                "paper-1",
                statement=(
                    "Changing scan speed from 0.167 to 0.239 decreased relative "
                    "density from 98% to 93.8%."
                ),
                direction="decreases",
            ),
            "C",
            "0.167",
            "0.239",
            "98",
            "93.8",
        ),
        (
            _evidence_unit(
                "unit-paper-2-as-built",
                "paper-2",
                statement=(
                    "Changing scan speed from 100 to 200 decreased relative "
                    "density from 97.83% to 91.84%."
                ),
                direction="decreases",
            ),
            "as-built",
            "100",
            "200",
            "97.83",
            "91.84",
        ),
    ]
    for unit, condition, baseline_speed, current_speed, baseline, current in comparisons:
        unit["process_context"] = {
            "scan speed": current_speed,
            "condition": condition,
        }
        unit["baseline_context"] = {
            "process_context": {
                "scan speed": baseline_speed,
                "condition": condition,
            },
            "source_value_text": baseline,
            "value": baseline,
        }
        unit["value_payload"].update(
            {
                "comparison_axis": "scan speed",
                "source_value_text": current,
                "value": current,
            }
        )

    payload = _payload([item[0] for item in comparisons])
    payload["objective"]["process_axes"] = ["scan speed"]
    payload["objective_context"]["variable_process_axes"] = ["scan speed"]
    service, extractor = _service([])

    service.build_goal_understanding(payload)

    result_sets = extractor.payloads[0]["result_sets"]
    assert len(result_sets) == 1
    assert result_sets[0]["alignment"] == (
        "same source-axis and outcome relationship across condition contrasts"
    )
    assert result_sets[0]["source_axes"] == ["scan speed"]
    assert result_sets[0]["outcome_properties"] == ["relative density"]
    assert {
        item["document_id"] for item in result_sets[0]["document_evidence"]
    } == {"paper-1", "paper-2"}
    assert {
        unit["evidence_unit_id"]
        for item in result_sets[0]["document_evidence"]
        for unit in item["result_units"]
    } == {
        "unit-paper-1-strategy-b",
        "unit-paper-1-strategy-c",
        "unit-paper-2-as-built",
    }


def test_goal_synthesis_groups_overlapping_coupled_axes_as_condition_dependent():
    coupled = _evidence_unit(
        "unit-coupled-density",
        "paper-coupled",
        statement=(
            "Changing laser power, scanning speed, and hatch spacing increased "
            "relative density from 91.9% to 99.6%."
        ),
        direction="increases",
    )
    coupled["process_context"] = {
        "laser power": "220",
        "scanning speed": "725",
        "hatch spacing": "120",
    }
    coupled["baseline_context"] = {
        "process_context": {
            "laser power": "160",
            "scanning speed": "875",
            "hatch spacing": "120",
        },
        "source_value_text": "91.9",
        "value": "91.9",
    }
    coupled["value_payload"].update(
        {
            "comparison_axis": "laser power, scanning speed, hatch spacing",
            "source_value_text": "99.6",
            "value": "99.6",
        }
    )
    scan_speed = _evidence_unit(
        "unit-speed-density",
        "paper-speed",
        statement=(
            "Changing scanning speed from 100 to 280 decreased relative "
            "density from 98.11% to 90.04%."
        ),
        direction="decreases",
    )
    scan_speed["process_context"] = {
        "laser power": "120",
        "scanning speed": "280",
    }
    scan_speed["baseline_context"] = {
        "process_context": {
            "laser power": "120",
            "scanning speed": "100",
        },
        "source_value_text": "98.11",
        "value": "98.11",
    }
    scan_speed["value_payload"].update(
        {
            "comparison_axis": "scanning speed",
            "source_value_text": "90.04",
            "value": "90.04",
        }
    )
    payload = _payload([coupled, scan_speed])
    payload["objective"]["process_axes"] = [
        "laser power",
        "scanning speed",
        "hatch spacing",
    ]
    payload["objective_context"]["variable_process_axes"] = [
        "laser power",
        "scanning speed",
        "hatch spacing",
    ]
    model_finding = _model_finding(
        synthesis_status="agreement",
        supporting_ids=["unit-coupled-density", "unit-speed-density"],
        direction="mixed",
    )
    model_finding.update(
        {
            "source_concept": "scanning speed",
            "statement": (
                "Density depends on the tested coupled LPBF process conditions."
            ),
        }
    )
    service, extractor = _service([model_finding])

    understanding = service.build_goal_understanding(payload)

    result_sets = extractor.payloads[0]["result_sets"]
    assert len(result_sets) == 1
    assert result_sets[0]["alignment"] == (
        "overlapping source-axis and outcome relationship across condition contrasts"
    )
    assert result_sets[0]["source_axes"] == [
        "laser power",
        "scanning speed",
        "hatch spacing",
    ]
    assert {
        item["document_id"]: item["source_axes"]
        for item in result_sets[0]["document_evidence"]
    } == {
        "paper-coupled": ["laser power", "scanning speed", "hatch spacing"],
        "paper-speed": ["scanning speed"],
    }
    relation = understanding["relations"][0]
    assert relation["subject"] == "laser power, scanning speed, hatch spacing"
    assert relation["synthesis_status"] == "condition_dependent"
    assert "condition_dependent" in relation["warnings"]


def test_goal_synthesis_rejects_finding_that_mixes_result_sets():
    density = _evidence_unit(
        "unit-density",
        "paper-density",
        statement="Increasing scan speed decreased relative density.",
        direction="decreases",
    )
    density["value_payload"]["comparison_axis"] = "scan speed"
    microstructure = _evidence_unit(
        "unit-microstructure",
        "paper-microstructure",
        statement="Heat treatment coarsened the grain structure.",
        direction="increases",
    )
    microstructure["property_normalized"] = "microstructure"
    microstructure["value_payload"]["comparison_axis"] = "heat treatment"
    payload = _payload([density, microstructure])
    payload["objective"]["process_axes"] = ["scan speed", "heat treatment"]
    payload["objective"]["property_axes"] = ["relative density", "microstructure"]
    payload["objective_context"]["variable_process_axes"] = [
        "scan speed",
        "heat treatment",
    ]
    payload["objective_context"]["target_property_axes"] = [
        "relative density",
        "microstructure",
    ]
    payload["paper_frames"][0]["changed_variables"] = ["scan speed"]
    payload["paper_frames"][1]["changed_variables"] = ["heat treatment"]
    model_finding = {
        **_model_finding(
            synthesis_status="agreement",
            supporting_ids=["unit-density"],
            outcomes=[
                {
                    "concept": "relative density",
                    "direction": "decreases",
                    "statement": "Scan speed decreased relative density.",
                    "supporting_evidence_unit_ids": ["unit-density"],
                    "conflicting_evidence_unit_ids": [],
                },
                {
                    "concept": "microstructure",
                    "direction": "changes",
                    "statement": "Heat treatment changed microstructure.",
                    "supporting_evidence_unit_ids": ["unit-microstructure"],
                    "conflicting_evidence_unit_ids": [],
                },
            ],
        ),
        "result_set_id": "result_set_1",
        "source_concept": "scan speed and heat treatment",
    }
    service, extractor = _service([model_finding])

    understanding = service.build_goal_understanding(payload)

    assert [item["result_set_id"] for item in extractor.payloads[0]["result_sets"]] == [
        "result_set_1",
        "result_set_2",
    ]
    assert understanding["presentation"]["findings"] == []


def test_goal_synthesis_rejects_energy_density_context_for_density_outcome():
    direct = _evidence_unit(
        "unit-density",
        "paper-1",
        statement=(
            "Changing scan speed from 100 to 200 decreased relative density "
            "from 97.83% to 91.84%."
        ),
        direction="decreases",
    )
    direct["value_payload"]["comparison_axis"] = "scan speed"
    context = _context_unit(
        "unit-grain-context",
        "paper-1",
        unit_kind="mechanism",
        statement="Increasing energy density resulted in coarser grains.",
        evidence_role="mediator_context",
    )
    context["property_normalized"] = "microstructure"
    payload = _payload([direct, context])
    payload["objective"]["process_axes"] = ["scan speed"]
    payload["objective_context"]["variable_process_axes"] = ["scan speed"]
    model_finding = _model_finding(
        synthesis_status="insufficient_confirmation",
        supporting_ids=["unit-density"],
        mechanism_ids=["unit-grain-context"],
        direction="decreases",
    )
    model_finding.update(
        {
            "source_concept": "scan speed",
            "mediator_concepts": ["coarser grains"],
            "statement": (
                "Changing scan speed from 100 to 200 decreased relative density "
                "from 97.83% to 91.84%. Increasing energy density resulted in "
                "coarser grains."
            ),
        }
    )
    service, _ = _service([model_finding])

    understanding = service.build_goal_understanding(payload)

    relation = understanding["relations"][0]
    assert relation["statement"] == direct["value_payload"]["statement"]
    assert relation["mechanism_evidence_ref_ids"] == []
    assert relation["object"] == "relative density"


def test_goal_synthesis_rebuilds_cross_paper_statement_from_direct_evidence():
    paper_one = _evidence_unit(
        "unit-paper-1-density",
        "paper-1",
        statement=(
            "Higher scan speed decreased relative density from 98% to 93.8%."
        ),
        direction="decreases",
    )
    paper_two = _evidence_unit(
        "unit-paper-2-density",
        "paper-2",
        statement=(
            "Higher scan speed decreased relative density from 97.83% to 91.84%."
        ),
        direction="decreases",
    )
    for unit in (paper_one, paper_two):
        unit["value_payload"]["comparison_axis"] = "scan speed"
    context = _context_unit(
        "unit-unrelated-grain-context",
        "paper-1",
        unit_kind="mechanism",
        statement="Increasing energy density resulted in coarser grains.",
        evidence_role="mediator_context",
    )
    context["property_normalized"] = "microstructure"
    payload = _payload([paper_one, paper_two, context])
    payload["objective"]["process_axes"] = ["scan speed"]
    payload["objective_context"]["variable_process_axes"] = ["scan speed"]
    model_finding = _model_finding(
        synthesis_status="agreement",
        supporting_ids=["unit-paper-1-density", "unit-paper-2-density"],
        mechanism_ids=["unit-unrelated-grain-context"],
        direction="decreases",
    )
    model_finding.update(
        {
            "source_concept": "scan speed",
            "mediator_concepts": ["coarser grains"],
            "statement": (
                "Higher scan speed decreased relative density from 98% to "
                "93.8%, and from 97.83% to 91.84%. Increasing energy density "
                "resulted in coarser grains."
            ),
        }
    )
    service, _ = _service([model_finding])

    understanding = service.build_goal_understanding(payload)

    relation = understanding["relations"][0]
    assert relation["synthesis_status"] == "agreement"
    assert relation["statement"] == (
        "Higher scan speed decreased relative density from 98% to 93.8%. "
        "Higher scan speed decreased relative density from 97.83% to 91.84%."
    )
    assert relation["mechanism_evidence_ref_ids"] == []
    assert relation["object"] == "relative density"


def test_goal_synthesis_rejects_finding_with_outcomes_bound_to_another_property():
    paper_one = _evidence_unit(
        "unit-paper-1-density",
        "paper-1",
        statement=(
            "Changing scan speed from 0.167 to 0.239 decreased density "
            "from 98% to 93.8%."
        ),
        direction="decreases",
    )
    paper_two = _evidence_unit(
        "unit-paper-2-density",
        "paper-2",
        statement=(
            "Changing scan speed from 100 to 200 decreased density "
            "from 97.83% to 91.84%."
        ),
        direction="decreases",
    )
    for unit in (paper_one, paper_two):
        unit["property_normalized"] = "density"
        unit["value_payload"]["comparison_axis"] = "scan speed"
    payload = _payload([paper_one, paper_two])
    payload["objective"]["process_axes"] = ["scan speed"]
    payload["objective_context"]["variable_process_axes"] = ["scan speed"]
    model_finding = _model_finding(
        synthesis_status="insufficient_confirmation",
        supporting_ids=[],
        outcomes=[
            {
                "concept": "density",
                "direction": "decreases",
                "statement": "Increasing scan speed decreases density.",
                "supporting_evidence_unit_ids": [
                    "unit-paper-1-density",
                    "unit-paper-2-density",
                ],
                "conflicting_evidence_unit_ids": [],
            },
            {
                "concept": "microstructure",
                "direction": "changes",
                "statement": "Increasing scan speed changes microstructure.",
                "supporting_evidence_unit_ids": [
                    "unit-paper-1-density",
                    "unit-paper-2-density",
                ],
                "conflicting_evidence_unit_ids": [],
            },
            {
                "concept": "grain size",
                "direction": "increases",
                "statement": "Increasing scan speed increases grain size.",
                "supporting_evidence_unit_ids": ["unit-paper-2-density"],
                "conflicting_evidence_unit_ids": [],
            },
        ],
    )
    model_finding.update(
        {
            "source_concept": "scan speed",
            "statement": (
                "Increasing scan speed decreases density, changes microstructure, "
                "and increases grain size."
            ),
        }
    )
    service, _ = _service([model_finding])

    understanding = service.build_goal_understanding(payload)

    assert understanding["relations"] == []


def test_goal_synthesis_flags_cross_paper_axis_scale_mismatch():
    paper_one = _evidence_unit(
        "unit-paper-1-density",
        "paper-1",
        statement=(
            "Changing scan speed from 0.167 to 0.239 decreased density "
            "from 98% to 93.8%."
        ),
        direction="decreases",
    )
    paper_two = _evidence_unit(
        "unit-paper-2-density",
        "paper-2",
        statement=(
            "Changing scan speed from 100 to 200 decreased density "
            "from 97.83% to 91.84%."
        ),
        direction="decreases",
    )
    for unit, baseline_speed, current_speed in (
        (paper_one, "0.167", "0.239"),
        (paper_two, "100", "200"),
    ):
        unit["property_normalized"] = "density"
        unit["process_context"] = {"Scan speed (mm/s)": current_speed}
        unit["baseline_context"] = {
            "process_context": {"Scan speed (mm/s)": baseline_speed},
            "source_value_text": "98",
            "value": "98",
        }
        unit["value_payload"].update(
            {
                "comparison_axis": "scan speed",
                "current_value": "93.8",
                "source_value_text": "93.8",
                "value": "93.8",
            }
        )
    payload = _payload([paper_one, paper_two])
    payload["objective"]["process_axes"] = ["scan speed"]
    payload["objective_context"]["variable_process_axes"] = ["scan speed"]
    model_finding = _model_finding(
        synthesis_status="insufficient_confirmation",
        supporting_ids=["unit-paper-1-density", "unit-paper-2-density"],
        target_concept="density",
        direction="decreases",
    )
    model_finding.update(
        {
            "source_concept": "scan speed",
            "statement": "Increasing scan speed decreases density.",
            "common_conditions": [],
            "incomparable_conditions": [],
        }
    )
    service, _ = _service([model_finding])

    understanding = service.build_goal_understanding(payload)

    relation = understanding["relations"][0]
    assert relation["incomparable_conditions"] == [
        "Reported scan speed ranges differ by more than 100x across papers "
        "(0.167-0.239 mm/s versus 100-200 mm/s); verify source unit "
        "normalization before direct comparison."
    ]


def test_goal_synthesis_downgrades_model_agreement_with_one_direct_paper():
    units = [
        _evidence_unit(
            "unit-paper-1",
            "paper-1",
            statement="Increasing energy density increased relative density to 99.1%.",
            direction="increases",
        )
    ]
    service, _ = _service(
        [
            _model_finding(
                synthesis_status="agreement",
                supporting_ids=["unit-paper-1"],
            )
        ]
    )

    understanding = service.build_goal_understanding(_payload(units))

    finding = understanding["presentation"]["findings"][0]
    assert finding["synthesis_status"] == "insufficient_confirmation"
    assert finding["paper_count"] == 1
    assert finding["generalization_status"] == "paper_level_only"
    assert "needs_cross_paper_confirmation" in finding["review_reasons"]


def test_goal_synthesis_projects_single_paper_microstructure_finding_for_review():
    unit = _evidence_unit(
        "unit-preheating-microstructure",
        "paper-preheating",
        statement=(
            "Grain coarsening and shape change with increasing build platform "
            "preheating temperature during laser beam powder bed fusion of "
            "316L stainless steel."
        ),
        direction="increases",
    )
    unit["property_normalized"] = "microstructure"
    unit["process_context"] = {
        "process": "laser beam powder bed fusion",
        "variable": "build platform preheating temperature",
    }
    payload = _payload([unit])
    payload["objective"].update(
        {
            "question": "How does build platform preheating affect microstructure?",
            "process_axes": ["build platform preheating temperature"],
            "property_axes": ["microstructure"],
        }
    )
    payload["objective_context"].update(
        {
            "question": "How does build platform preheating affect microstructure?",
            "variable_process_axes": ["build platform preheating temperature"],
            "target_property_axes": ["microstructure"],
        }
    )
    payload["paper_frames"][0].update(
        {
            "changed_variables": ["build platform preheating temperature"],
            "measured_property_scope": ["microstructure"],
        }
    )
    service, _ = _service(
        [
            {
                **_model_finding(
                    synthesis_status="insufficient_confirmation",
                    supporting_ids=["unit-preheating-microstructure"],
                    target_concept="microstructure",
                    direction="increases",
                    common_conditions=["LPBF 316L"],
                ),
                "source_concept": "build platform preheating temperature",
                "mediator_concepts": [],
                "statement": (
                    "Build platform preheating temperature increases grain size "
                    "and changes grain shape."
                ),
                "confidence": 0.82,
            }
        ]
    )

    understanding = service.build_goal_understanding(payload)

    assert understanding["presentation"]["primary_findings"] == []
    finding = understanding["presentation"]["review_queue_findings"][0]
    assert finding["synthesis_status"] == "insufficient_confirmation"
    assert finding["paper_count"] == 1
    assert finding["evidence_bundle"]["direct_result"]


def test_goal_synthesis_excludes_low_relevance_background_evidence_from_ledger():
    unit = _evidence_unit(
        "unit-background",
        "paper-background",
        statement="Increasing VED coarsened grains in the background paper.",
        direction="increases",
    )
    payload = _payload([unit])
    payload["paper_frames"][0].update(
        {
            "relevance": "low",
            "paper_role": "supporting_background",
        }
    )
    service, extractor = _service(
        [
            _model_finding(
                synthesis_status="insufficient_confirmation",
                supporting_ids=["unit-background"],
            )
        ]
    )

    understanding = service.build_goal_understanding(payload)

    assert extractor.payloads[0]["result_sets"] == []
    assert understanding["presentation"]["findings"] == []


def test_goal_synthesis_keeps_low_relevance_direct_result_table_in_ledger():
    unit = _evidence_unit(
        "unit-result-table",
        "paper-result-table",
        statement=(
            "Changing scan speed from 100 to 280 decreased relative density "
            "from 98.11% to 90.04%."
        ),
        direction="decreases",
    )
    unit["value_payload"]["comparison_axis"] = "scan speed"
    unit["source_refs"][0]["source_kind"] = "table"
    payload = _payload([unit])
    payload["objective"]["process_axes"] = ["scan speed"]
    payload["objective_context"]["variable_process_axes"] = ["scan speed"]
    payload["paper_frames"][0].update(
        {
            "relevance": "low",
            "paper_role": "supporting_background",
        }
    )
    model_finding = _model_finding(
        synthesis_status="insufficient_confirmation",
        supporting_ids=["unit-result-table"],
    )
    model_finding["source_concept"] = "scan speed"
    service, extractor = _service([model_finding])

    understanding = service.build_goal_understanding(payload)

    assert extractor.payloads[0]["result_sets"][0]["document_evidence"][0][
        "document_id"
    ] == "paper-result-table"
    finding = understanding["presentation"]["findings"][0]
    assert finding["paper_count"] == 1
    assert finding["evidence_bundle"]["direct_result"]


def test_goal_synthesis_keeps_supporting_and_conflicting_evidence_separate():
    units = [
        _evidence_unit(
            "unit-support",
            "paper-support",
            statement="Increasing energy density increased relative density.",
            direction="increases",
        ),
        _evidence_unit(
            "unit-conflict",
            "paper-conflict",
            statement="Increasing energy density reduced relative density.",
            direction="decreases",
        ),
    ]
    service, _ = _service(
        [
            _model_finding(
                synthesis_status="conflict",
                supporting_ids=["unit-support"],
                conflicting_ids=["unit-conflict"],
            )
        ]
    )

    understanding = service.build_goal_understanding(_payload(units))

    finding = understanding["presentation"]["findings"][0]
    assert finding["synthesis_status"] == "conflict"
    assert finding["paper_count"] == 2
    assert len(finding["evidence_bundle"]["direct_result"]) == 1
    assert len(finding["evidence_bundle"]["conflict"]) == 1
    assert finding["generalization_status"] == "conflict_review_needed"
    assert {item["role"] for item in finding["paper_contributions"]} == {
        "supporting",
        "conflicting",
    }


def test_goal_synthesis_preserves_condition_dependent_boundaries():
    units = [
        _evidence_unit(
            "unit-lpbf",
            "paper-lpbf",
            statement="Higher energy density increased relative density in LPBF.",
            direction="increases",
            process="LPBF",
        ),
        _evidence_unit(
            "unit-hip",
            "paper-hip",
            statement="After HIP, relative density no longer tracked energy density.",
            direction="changes",
            process="LPBF + HIP",
        ),
    ]
    service, _ = _service(
        [
            _model_finding(
                synthesis_status="condition_dependent",
                supporting_ids=["unit-lpbf", "unit-hip"],
                common_conditions=["316L feedstock"],
                incomparable_conditions=["as-built LPBF versus post-HIP material"],
            )
        ]
    )

    understanding = service.build_goal_understanding(_payload(units))

    finding = understanding["presentation"]["findings"][0]
    assert finding["synthesis_status"] == "condition_dependent"
    assert finding["paper_count"] == 2
    assert finding["common_conditions"] == ["316L feedstock"]
    assert finding["incomparable_conditions"] == [
        "as-built LPBF versus post-HIP material"
    ]
    assert finding["generalization_status"] == "cross_paper_candidate"


def test_goal_synthesis_rejects_raw_measurement_as_relationship_support():
    unit = _evidence_unit(
        "unit-measurement",
        "paper-1",
        statement="Relative density is reported as 99.6%.",
        direction="unknown",
    )
    unit["unit_kind"] = "measurement"
    service, extractor = _service(
        [
            _model_finding(
                synthesis_status="insufficient_confirmation",
                supporting_ids=["unit-measurement"],
            )
        ]
    )

    understanding = service.build_goal_understanding(_payload([unit]))

    assert extractor.payloads[0]["result_sets"] == []
    assert understanding["presentation"]["findings"] == []


def test_goal_synthesis_rejects_characterization_built_from_isolated_number():
    unit = _evidence_unit(
        "unit-characterization-fragment",
        "paper-1",
        statement="10",
        direction="unknown",
    )
    unit.update(
        {
            "unit_kind": "characterization",
            "property_normalized": "microstructure",
            "process_context": {},
            "value_payload": {"value": "10"},
            "interpretation": None,
        }
    )
    service, extractor = _service(
        [
            _model_finding(
                synthesis_status="insufficient_confirmation",
                supporting_ids=["unit-characterization-fragment"],
            )
        ]
    )

    understanding = service.build_goal_understanding(_payload([unit]))

    assert extractor.payloads[0]["result_sets"] == []
    assert understanding["presentation"]["findings"] == []


def test_goal_synthesis_excludes_direct_units_without_relation_axes_or_target():
    missing_source_axis = _evidence_unit(
        "unit-missing-source-axis",
        "paper-1",
        statement="A direct result was observed under the tested condition.",
        direction="increases",
    )
    missing_target = _evidence_unit(
        "unit-missing-target",
        "paper-1",
        statement="Higher energy density changed the measured response.",
        direction="increases",
    )
    missing_target["property_normalized"] = None
    service, extractor = _service([])

    service.build_goal_understanding(_payload([missing_source_axis, missing_target]))

    assert extractor.payloads[0]["result_sets"] == []


def test_goal_synthesis_bounds_ledger_while_covering_each_paper():
    long_statement = "Higher energy density increased relative density. " * 24
    units = [
        _evidence_unit(
            f"unit-{paper_index}-{unit_index}",
            f"paper-{paper_index}",
            statement=long_statement,
            direction="increases",
        )
        for paper_index in range(1, 4)
        for unit_index in range(1, 7)
    ]
    service, extractor = _service([])

    service.build_goal_understanding(_payload(units))

    payload = extractor.payloads[0]
    included = _result_units(payload)
    serialized_length = sum(
        len(json.dumps(unit, ensure_ascii=False, separators=(",", ":")))
        for unit in included
    )
    assert serialized_length <= 4_500
    assert payload["input_coverage"]["omitted_evidence_unit_count"] > 0
    assert all(
        paper["result_units"]
        for result_set in payload["result_sets"]
        for paper in result_set["document_evidence"]
    )


def test_goal_synthesis_prioritizes_direct_results_before_measurements(monkeypatch):
    measurement = _evidence_unit(
        "unit-measurement",
        "paper-measurements",
        statement="Yield strength is reported as 456 MPa.",
        direction="unknown",
    )
    measurement["unit_kind"] = "measurement"
    direct_units = [
        _evidence_unit(
            "unit-direct-energy",
            "paper-direct-results",
            statement="Higher energy density increased relative density.",
            direction="increases",
        ),
        _evidence_unit(
            "unit-direct-speed",
            "paper-direct-results",
            statement="Higher scan speed reduced relative density.",
            direction="decreases",
        ),
    ]
    direct_units[1]["value_payload"]["comparison_axis"] = "scan speed"
    payload = _payload([measurement, *direct_units])
    payload["objective"]["process_axes"] = ["energy density", "scan speed"]
    payload["objective_context"]["variable_process_axes"] = [
        "energy density",
        "scan speed",
    ]
    service, extractor = _service([])
    direct_result_budget = sum(
        len(
            json.dumps(
                service._finding_synthesis_evidence_unit(
                    unit,
                    direct_result=True,
                    process_axes=["energy density", "scan speed"],
                ),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        for unit in direct_units
    )
    monkeypatch.setattr(
        research_understanding_module,
        "_FINDING_SYNTHESIS_EVIDENCE_CHAR_LIMIT",
        direct_result_budget,
    )

    service.build_goal_understanding(payload)

    included_units = _result_units(extractor.payloads[0])
    assert {
        unit["evidence_unit_id"]
        for unit in included_units
        if unit.get("direct_result") is True
    } == {"unit-direct-energy", "unit-direct-speed"}
    assert "unit-measurement" not in {
        unit["evidence_unit_id"] for unit in included_units
    }


def test_goal_synthesis_balances_bounded_ledger_across_source_axes():
    laser_units = []
    for index in range(20):
        unit = _evidence_unit(
            f"unit-laser-{index}",
            "paper-density",
            statement=("Laser power changed density under fixed conditions. " * 20),
            direction="increases",
        )
        unit["value_payload"].update(
            {
                "comparison_axis": "laser power",
                "current_value": 98.11 if index == 0 else 99.5,
                "value": 98.11 if index == 0 else 99.5,
            }
        )
        unit["baseline_context"] = {
            "value": 97.83,
            "source_value_text": "97.83",
        }
        laser_units.append(unit)

    scan_speed_unit = _evidence_unit(
        "unit-scan-speed",
        "paper-density",
        statement=("Scan speed changed density under fixed conditions. " * 20),
        direction="decreases",
    )
    scan_speed_unit["value_payload"]["comparison_axis"] = "scan speed"
    heat_treatment_unit = _evidence_unit(
        "unit-heat-treatment",
        "paper-density",
        statement=("Heat treatment type changed density under fixed conditions. " * 20),
        direction="increases",
    )
    heat_treatment_unit["value_payload"]["comparison_axis"] = "heat treatment type"
    payload = _payload([*laser_units, scan_speed_unit, heat_treatment_unit])
    payload["objective"]["process_axes"] = [
        "laser power",
        "scan speed",
        "heat treatment type",
    ]
    payload["objective_context"]["variable_process_axes"] = [
        "laser power",
        "scan speed",
        "heat treatment type",
    ]
    service, extractor = _service([])

    service.build_goal_understanding(payload)

    included_units = _result_units(extractor.payloads[0])
    included_axes = {
        tuple(unit.get("source_axes", []))
        for unit in included_units
        if unit.get("direct_result") is True
    }
    assert included_axes >= {
        ("laser power",),
        ("scan speed",),
        ("heat treatment type",),
    }
    assert next(
        unit
        for unit in included_units
        if unit.get("source_axes") == ["laser power"]
    )["evidence_unit_id"] == "unit-laser-1"


def test_goal_synthesis_calibrates_numeric_axis_direction_from_direct_comparison():
    unit = _evidence_unit(
        "unit-scan-speed-density",
        "paper-density",
        statement="Density changed between the two scan-speed conditions.",
        direction="decreases",
    )
    unit.update(
        {
            "property_normalized": "density",
            "process_context": {
                "Laser power (W)": "100",
                "Scan speed (mm/s)": "200",
                "Type of heat treatment": "-",
            },
            "value_payload": {
                "comparison_axis": "scan speed",
                "controlled_axes": [
                    {"axis": "laser power", "value": "100"},
                    {"axis": "heat treatment type", "value": "-"},
                ],
                "current_value": 91.84,
                "direction": "decrease",
                "source_value_text": "91.84",
                "value": 91.84,
            },
            "baseline_context": {
                "process_context": {
                    "Laser power (W)": "100",
                    "Scan speed (mm/s)": "100",
                    "Type of heat treatment": "-",
                },
                "source_value_text": "97.83",
                "value": 97.83,
            },
        }
    )
    payload = _payload([unit])
    payload["objective"].update(
        {
            "question": "How does scan speed affect density?",
            "process_axes": ["scan speed"],
            "property_axes": ["density"],
        }
    )
    payload["objective_context"].update(
        {
            "question": "How does scan speed affect density?",
            "variable_process_axes": ["scan speed"],
            "target_property_axes": ["density"],
        }
    )
    payload["paper_frames"][0].update(
        {
            "changed_variables": ["scan speed"],
            "measured_property_scope": ["density"],
        }
    )
    service, _ = _service(
        [
            {
                **_model_finding(
                    synthesis_status="insufficient_confirmation",
                    supporting_ids=["unit-scan-speed-density"],
                    target_concept="density",
                    direction="increases",
                ),
                "source_concept": "scan speed",
                "statement": "Increasing scan speed increases density.",
            }
        ]
    )

    understanding = service.build_goal_understanding(payload)

    finding = understanding["presentation"]["findings"][0]
    assert finding["direction"] == "decreases"
    assert (
        "changing scan speed from 100 to 200 decreased density from "
        "97.83 % to 91.84 %."
    ) in finding["statement"].lower()


def test_goal_synthesis_preserves_coupled_axis_and_transition_direction():
    unit = _evidence_unit(
        "unit-coupled-corrosion",
        "paper-corrosion",
        statement="Pitting potential changed across coupled process conditions.",
        direction="increases",
    )
    unit.update(
        {
            "property_normalized": "pitting potential",
            "process_context": {
                "Energy density (J mm-3)": "100",
                "Laser power (W)": "255",
                "Scan speed (mm/s)": "1400",
            },
            "value_payload": {
                "comparison_axis": "laser power, scanning speed",
                "controlled_axes": [
                    {"axis": "energy density", "value": "100"},
                ],
                "current_value": 199.7,
                "direction": "increase",
                "source_value_text": "199.7",
                "value": 199.7,
            },
            "baseline_context": {
                "process_context": {
                    "Energy density (J mm-3)": "100",
                    "Laser power (W)": "375",
                    "Scan speed (mm/s)": "2100",
                },
                "source_value_text": "124.7",
                "value": 124.7,
            },
            "unit": "mV",
        }
    )
    payload = _payload([unit])
    payload["objective"].update(
        {
            "question": "How do laser power and scanning speed affect pitting potential?",
            "process_axes": ["laser power", "scanning speed", "energy density"],
            "property_axes": ["pitting potential"],
        }
    )
    payload["objective_context"].update(
        {
            "question": "How do laser power and scanning speed affect pitting potential?",
            "variable_process_axes": [
                "laser power",
                "scanning speed",
                "energy density",
            ],
            "target_property_axes": ["pitting potential"],
        }
    )
    payload["paper_frames"][0].update(
        {
            "changed_variables": ["laser power", "scanning speed"],
            "measured_property_scope": ["pitting potential"],
        }
    )
    service, extractor = _service(
        [
            {
                **_model_finding(
                    synthesis_status="insufficient_confirmation",
                    supporting_ids=["unit-coupled-corrosion"],
                    target_concept="pitting potential",
                    direction="increases",
                ),
                "source_concept": "laser power and scanning speed",
                "statement": (
                    "Increasing laser power and scanning speed increases "
                    "pitting potential."
                ),
            }
        ]
    )

    understanding = service.build_goal_understanding(payload)

    result_unit = _result_units(extractor.payloads[0])[0]
    assert result_unit["source_axes"] == ["laser power", "scanning speed"]
    assert (
        "changing laser power from 375 to 255 and scanning speed from 2100 "
        "to 1400 increased pitting potential from 124.7 mv to 199.7 mv."
    ) in result_unit["statement"].lower()
    finding = understanding["presentation"]["findings"][0]
    assert finding["variables"] == ["laser power and scanning speed"]
    assert finding["direction"] == "decreases"


def test_goal_synthesis_rejects_source_concept_not_supported_by_cited_unit_axis():
    unit = _evidence_unit(
        "unit-defect-characterization",
        "paper-defects",
        statement=(
            "Lower laser power and scanning speed reduce porosity and pore size."
        ),
        direction="reduces",
    )
    unit.update(
        {
            "unit_kind": "characterization",
            "property_normalized": "defect structure",
            "process_context": {
                "parameters": {
                    "laser_power": "135 W",
                    "scanning_speed": "750 mm/s",
                },
                "process": "laser beam powder bed fusion",
            },
            "value_payload": {
                "porosity_cause": "reduced laser power and scanning speed",
                "porosity_observation": "few tiny pores",
            },
            "interpretation": (
                "Lower laser power and scanning speed reduce porosity and pore "
                "size."
            ),
        }
    )
    payload = _payload([unit])
    payload["objective"].update(
        {
            "question": "How do process parameters affect defect structure?",
            "process_axes": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
            ],
            "property_axes": ["defect structure"],
        }
    )
    payload["objective_context"].update(
        {
            "question": "How do process parameters affect defect structure?",
            "variable_process_axes": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
            ],
            "target_property_axes": ["defect structure"],
        }
    )
    payload["paper_frames"][0].update(
        {
            "changed_variables": ["laser power", "scanning speed"],
            "measured_property_scope": ["defect structure"],
        }
    )
    service, extractor = _service(
        [
            {
                **_model_finding(
                    synthesis_status="insufficient_confirmation",
                    supporting_ids=["unit-defect-characterization"],
                    target_concept="defect structure",
                    direction="decreases",
                ),
                "source_concept": "volumetric energy density",
                "statement": (
                    "Higher volumetric energy density reduces defect structure."
                ),
            }
        ]
    )

    understanding = service.build_goal_understanding(payload)

    result_unit = _result_units(extractor.payloads[0])[0]
    assert result_unit["source_axes"] == ["laser power", "scanning speed"]
    assert understanding["presentation"]["findings"] == []


def test_goal_synthesis_matches_qualified_axis_to_source_statement():
    unit = _evidence_unit(
        "unit-porosity-corrosion",
        "paper-corrosion",
        statement=(
            "Lower porosity stabilizes the passive film and improves corrosion "
            "properties."
        ),
        direction="improves",
    )
    unit.update(
        {
            "unit_kind": "interpretation",
            "property_normalized": "pitting corrosion behavior",
            "process_context": {},
            "value_payload": {
                "source_value_text": (
                    "pitting potential gradually increases with decreased porosity"
                ),
                "value": "pitting potential increases with lower porosity",
            },
            "interpretation": (
                "Lower porosity stabilizes the passive film and improves "
                "corrosion properties."
            ),
        }
    )
    payload = _payload([unit])
    payload["objective"].update(
        {
            "question": "How do process parameters affect pitting corrosion?",
            "process_axes": [
                "laser power",
                "scanning speed",
                "porosity level",
            ],
            "property_axes": ["pitting corrosion behavior"],
        }
    )
    payload["objective_context"].update(
        {
            "question": "How do process parameters affect pitting corrosion?",
            "variable_process_axes": [
                "laser power",
                "scanning speed",
                "porosity level",
            ],
            "target_property_axes": ["pitting corrosion behavior"],
        }
    )
    payload["paper_frames"][0].update(
        {
            "changed_variables": [
                "laser power",
                "scanning speed",
                "porosity level",
            ],
            "measured_property_scope": ["pitting corrosion behavior"],
        }
    )
    service, extractor = _service(
        [
            {
                **_model_finding(
                    synthesis_status="insufficient_confirmation",
                    supporting_ids=["unit-porosity-corrosion"],
                    target_concept="pitting corrosion behavior",
                    direction="improves",
                ),
                "source_concept": "laser power, scanning speed",
                "statement": (
                    "Lower laser power and scanning speed improve pitting "
                    "corrosion behavior."
                ),
            }
        ]
    )

    understanding = service.build_goal_understanding(payload)

    result_unit = _result_units(extractor.payloads[0])[0]
    assert result_unit["source_axes"] == ["porosity level"]
    assert understanding["claims"] == []


def test_goal_synthesis_presentation_does_not_reinfer_source_axis_from_table_quote():
    unit = _evidence_unit(
        "unit-scan-strategy-yield",
        "paper-strategy",
        statement="Scanning strategy A increased yield strength relative to B.",
        direction="increases",
    )
    unit.update(
        {
            "property_normalized": "yield strength",
            "process_context": {
                "Energy density (J/mm3)": "70",
                "Scan strategy": "A",
                "Scanning speed (mm/s)": "0.25",
            },
            "value_payload": {
                "comparison_axis": "scanning strategy",
                "controlled_axes": [
                    {"axis": "energy density", "value": "70"},
                    {"axis": "scanning speed", "value": "0.25"},
                ],
                "current_value": 236.65,
                "direction": "increase",
                "source_value_text": "236.65",
                "value": 236.65,
            },
            "baseline_context": {
                "process_context": {
                    "Energy density (J/mm3)": "70",
                    "Scan strategy": "B",
                    "Scanning speed (mm/s)": "0.25",
                },
                "source_value_text": "159.97",
                "value": 159.97,
            },
            "unit": "MPa",
        }
    )
    unit["source_refs"][0]["quote"] = (
        "Table columns include laser power, scan speed, and yield strength; "
        "the observed yield strength is 236.65 MPa."
    )
    payload = _payload([unit])
    payload["objective"].update(
        {
            "question": "How does scanning strategy affect yield strength?",
            "process_axes": ["scanning strategy", "scanning speed", "energy density"],
            "property_axes": ["yield strength"],
        }
    )
    payload["objective_context"].update(
        {
            "question": "How does scanning strategy affect yield strength?",
            "variable_process_axes": [
                "scanning strategy",
                "scanning speed",
                "energy density",
            ],
            "target_property_axes": ["yield strength"],
        }
    )
    payload["paper_frames"][0].update(
        {
            "changed_variables": ["scanning strategy"],
            "measured_property_scope": ["yield strength"],
        }
    )
    service, _ = _service(
        [
            {
                **_model_finding(
                    synthesis_status="insufficient_confirmation",
                    supporting_ids=["unit-scan-strategy-yield"],
                    target_concept="yield strength",
                    direction="changes",
                ),
                "source_concept": "scanning strategy",
                "statement": (
                    "Scanning strategy changes yield strength under constant "
                    "energy density and scanning speed."
                ),
            }
        ]
    )

    understanding = service.build_goal_understanding(payload)

    finding = understanding["presentation"]["findings"][0]
    assert finding["variables"] == ["scanning strategy"]
    assert "changing scanning strategy from b to a" in finding["statement"].lower()
