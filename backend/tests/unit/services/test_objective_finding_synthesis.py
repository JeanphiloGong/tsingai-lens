from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.core.finding_synthesis_service import FindingSynthesisService
from domain.core import (
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    ResearchObjective,
)


class _Extractor:
    def __init__(self, findings: list[dict]) -> None:
        self.findings = findings
        self.payloads: list[dict] = []

    def synthesize_findings(self, payload: dict) -> SimpleNamespace:
        self.payloads.append(payload)
        requested_ids = {
            item["result_set_id"] for item in payload.get("result_sets", [])
        }
        findings = [
            finding
            for finding in self.findings
            if finding.get("result_set_id") in requested_ids
        ]
        return SimpleNamespace(model_dump=lambda: {"findings": findings})


def _objective(**overrides) -> ResearchObjective:
    payload = {
        "collection_id": "col-1",
        "objective_id": "obj-density",
        "question": "How do laser power and scan speed affect relative density?",
        "material_scope": ["316L stainless steel"],
        "process_axes": ["laser power", "scan speed"],
        "property_axes": ["relative density"],
        "confidence": 0.9,
        "confirmation_status": "confirmed",
        "active_analysis_version": 1,
    }
    payload.update(overrides)
    return ResearchObjective.from_mapping(payload)


def _analysis(**overrides) -> ObjectiveAnalysis:
    payload = {
        "collection_id": "col-1",
        "objective_id": "obj-density",
        "analysis_version": 1,
        "source_build_id": "build-1",
        "pipeline_version": "objective-analysis.v2",
        "model_name": "test-model",
        "prompt_versions": {},
        "status": "running",
        "phase": "finding_synthesis",
    }
    payload.update(overrides)
    return ObjectiveAnalysis(**payload)


def _contribution(document_id: str, **overrides) -> PaperContribution:
    payload = {
        "collection_id": "col-1",
        "objective_id": "obj-density",
        "analysis_version": 1,
        "document_id": document_id,
        "analysis_status": "analyzed",
        "relevance": "high",
        "paper_role": "primary_experiment",
        "contribution_summary": "Direct parameter comparison.",
        "material_match": ["316L stainless steel"],
        "changed_variables": ["laser power", "scan speed"],
        "measured_property_scope": ["relative density"],
        "test_environment_scope": [],
        "warnings": [],
        "confidence": 0.9,
    }
    payload.update(overrides)
    return PaperContribution.from_mapping(payload)


def _evidence(
    evidence_id: str,
    document_id: str,
    *,
    role: str = "direct_result",
    property_name: str | None = "relative density",
    **overrides,
) -> ObjectiveEvidence:
    payload = {
        "collection_id": "col-1",
        "objective_id": "obj-density",
        "analysis_version": 1,
        "evidence_id": evidence_id,
        "document_id": document_id,
        "source_kind": "text_window",
        "source_ref": f"block-{evidence_id}",
        "source_excerpt": (
            "Increasing laser power from 150 W to 200 W while scan speed also "
            "changed increased relative density from 96.1% to 99.2%."
        ),
        "page_numbers": [4],
        "related_source_refs": [],
        "evidence_role": role,
        "selection_status": "extracted",
        "selection_reason": "Direct objective result.",
        "evidence_kind": "comparison",
        "property_normalized": property_name,
        "material_system": {"alloy": "316L"},
        "sample_context": {"state": "as-built"},
        "process_context": {"process": "LPBF"},
        "test_condition": {},
        "resolved_condition": {},
        "value_payload": {
            "comparison_axis": "laser power and scan speed",
            "baseline_value": 96.1,
            "current_value": 99.2,
        },
        "unit": "%",
        "baseline_context": {"laser_power_w": 150},
        "interpretation": "Relative density increased for the coupled parameter set.",
        "join_keys": {"variable_process_axes": ["laser power", "scan speed"]},
        "anchor_ids": [f"anchor-{evidence_id}"],
        "resolution_status": "resolved",
        "confidence": 0.9,
    }
    payload.update(overrides)
    return ObjectiveEvidence.from_mapping(payload)


def _candidate(**overrides) -> dict:
    payload = {
        "result_set_id": "result_set_1",
        "source_concept": "laser power and scan speed",
        "outcomes": [
            {
                "concept": "relative density",
                "direction": "increases",
                "statement": "Relative density increased.",
                "conflicting_evidence_ids": [],
            }
        ],
        "mediator_concepts": [],
        "statement": (
            "In the reported LPBF 316L comparison, the coupled laser-power and "
            "scan-speed change was associated with higher relative density."
        ),
        "synthesis_status": "agreement",
        "context_evidence_ids": [],
        "mechanism_evidence_ids": [],
        "common_conditions": ["LPBF 316L, as-built"],
        "incomparable_conditions": [],
        "confidence": 0.86,
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def test_synthesis_keeps_single_paper_finding_at_paper_level() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(structured_extractor=extractor)
    evidence = _evidence("ev-1", "paper-1")

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(evidence,),
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.finding_level == "paper"
    assert finding.generalization_status == "paper_level_only"
    assert finding.paper_count == 1
    assert finding.variables == ("laser power", "scan speed")
    assert finding.outcomes == ("relative density",)
    assert finding.direction == "changes"
    assert finding.statement == (
        "In the reported comparison, the coupled condition defined by laser power, "
        "scan speed was associated with changes in relative density."
    )
    assert finding.derivation.supporting_evidence_ids == ("ev-1",)
    assert finding.relations[0].assertion_strength == "associative"
    assert finding.relations[0].direction == "changes"
    assert finding.context.limitations[0].startswith(
        "The reported comparison changes coupled variables"
    )
    assert extractor.payloads[0]["result_sets"][0]["direct_evidence"][0][
        "source_excerpt"
    ].startswith("Increasing laser power")


def test_synthesis_builds_cross_paper_finding_from_two_direct_papers() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence("ev-2", "paper-2"),
        ),
    )

    finding = findings[0]
    assert finding.finding_level == "cross_paper"
    assert finding.generalization_status == "cross_paper_agreement"
    assert finding.paper_count == 2
    assert finding.derivation.contributing_document_ids == ("paper-1", "paper-2")


def test_synthesis_prefers_comparison_evidence_over_component_measurements() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(
            _contribution(
                "paper-1",
                changed_variables=["laser power", "scan speed", "energy density"],
            ),
        ),
        evidence_records=(
            _evidence(
                "measurement-1",
                "paper-1",
                evidence_kind="measurement",
                join_keys={"sample": "A"},
            ),
            _evidence(
                "comparison-1",
                "paper-1",
                join_keys={
                    "comparison_axis": ["laser power", "scan speed"],
                    "controlled_axes": [{"axis": "energy density", "value": "100"}],
                },
            ),
        ),
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.variables == ("laser power", "scan speed")
    assert finding.derivation.supporting_evidence_ids == ("comparison-1",)
    assert "energy density" not in finding.variables
    assert [
        item["evidence_id"]
        for item in extractor.payloads[0]["result_sets"][0]["direct_evidence"]
    ] == ["comparison-1"]


def test_synthesis_excludes_explicit_axes_outside_the_objective() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "off-objective",
                "paper-1",
                join_keys={"comparison_axis": "build platform preheating"},
            ),
        ),
    )

    assert findings == ()
    assert extractor.payloads == []


def test_synthesis_does_not_expand_ambiguous_paper_axes_onto_measurements() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(
            _contribution(
                "paper-1",
                changed_variables=["laser power", "scan speed", "energy density"],
            ),
        ),
        evidence_records=(
            _evidence(
                "ambiguous-measurement",
                "paper-1",
                evidence_kind="measurement",
                process_context={"process": "LPBF"},
                join_keys={"sample": "A"},
                value_payload={"value": 99.2},
            ),
        ),
    )

    assert findings == ()
    assert extractor.payloads == []


def test_synthesis_processes_every_result_set_independently() -> None:
    extractor = _Extractor(
        [
            _candidate(
                result_set_id="result_set_1",
                source_concept="laser power",
                statement="Laser power was associated with relative density.",
            ),
            _candidate(
                result_set_id="result_set_2",
                source_concept="scan speed",
                outcomes=[
                    {
                        "concept": "elongation",
                        "direction": "decreases",
                        "statement": "Elongation decreased.",
                        "conflicting_evidence_ids": [],
                    }
                ],
                statement="Scan speed was associated with lower elongation.",
            ),
        ]
    )
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(property_axes=["relative density", "elongation"]),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "density",
                "paper-1",
                join_keys={"variable_process_axes": ["laser power"]},
            ),
            _evidence(
                "elongation",
                "paper-1",
                property_name="elongation",
                join_keys={"variable_process_axes": ["scan speed"]},
            ),
        ),
    )

    assert [finding.outcomes for finding in findings] == [
        ("relative density",),
        ("elongation",),
    ]
    assert [finding.display_rank for finding in findings] == [0, 1]
    assert [
        [item["result_set_id"] for item in payload["result_sets"]]
        for payload in extractor.payloads
    ] == [["result_set_1"], ["result_set_2"]]


def test_synthesis_continues_after_one_result_set_is_omitted() -> None:
    extractor = _Extractor(
        [
            _candidate(
                result_set_id="result_set_2",
                source_concept="scan speed",
                outcomes=[
                    {
                        "concept": "elongation",
                        "direction": "decreases",
                        "statement": "Elongation decreased.",
                        "conflicting_evidence_ids": [],
                    }
                ],
                statement="Scan speed was associated with lower elongation.",
            )
        ]
    )
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(property_axes=["relative density", "elongation"]),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "density",
                "paper-1",
                join_keys={"variable_process_axes": ["laser power"]},
            ),
            _evidence(
                "elongation",
                "paper-1",
                property_name="elongation",
                join_keys={"variable_process_axes": ["scan speed"]},
            ),
        ),
    )

    assert len(extractor.payloads) == 2
    assert len(findings) == 1
    assert findings[0].outcomes == ("elongation",)
    assert findings[0].display_rank == 0


def test_synthesis_binds_context_only_from_contributing_papers() -> None:
    extractor = _Extractor(
        [
            _candidate(
                context_evidence_ids=["context-1", "context-unrelated"],
                mechanism_evidence_ids=["mechanism-1"],
            )
        ]
    )
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence(
                "context-1",
                "paper-1",
                role="condition_context",
                property_name=None,
                evidence_kind="process_context",
            ),
            _evidence(
                "mechanism-1",
                "paper-1",
                role="mechanism_context",
                property_name=None,
                evidence_kind="characterization",
            ),
            _evidence(
                "context-unrelated",
                "paper-2",
                role="condition_context",
                property_name=None,
                evidence_kind="process_context",
            ),
        ),
    )

    assert findings[0].context.supporting_evidence_ids == (
        "ev-1",
        "context-1",
        "mechanism-1",
    )
    assert {
        item["evidence_id"] for item in extractor.payloads[0]["context_evidence"]
    } == {"context-1", "mechanism-1"}


def test_synthesis_returns_empty_without_direct_result() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "context-1",
                "paper-1",
                role="condition_context",
                property_name=None,
                evidence_kind="process_context",
            ),
        ),
    )

    assert findings == ()
    assert extractor.payloads == []


def test_synthesis_rejects_cross_version_children() -> None:
    service = FindingSynthesisService(structured_extractor=_Extractor([]))

    with pytest.raises(ValueError, match="another objective version"):
        service.synthesize(
            collection_id="col-1",
            objective=_objective(),
            analysis=_analysis(),
            contributions=(
                _contribution("paper-1", analysis_version=2),
            ),
            evidence_records=(),
        )
