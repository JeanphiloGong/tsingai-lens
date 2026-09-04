from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.core import (
    OBJECTIVE_ANALYSIS_STATUSES,
    ObjectiveAnalysis,
    ObjectiveDocumentEvidence,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PreparedDocumentInput,
    PaperContribution,
    PaperSourceUnitCoverage,
    PaperSourceUnitCoverageStatus,
    PaperResearchScope,
    PaperResearchSignal,
    PaperStudyDisposition,
    PaperStudyDispositionStatus,
    PaperResearchRelationship,
    PaperResearchMap,
    ReviewKnowledgeItem,
    ReviewSynthesisMap,
    ResearchObjective,
    build_research_objective_id,
    is_question_shaped_objective,
    normalize_objective_confidence,
    normalize_objective_terms,
)


@pytest.mark.parametrize(
    "variable_role",
    ["varied", "compared", "modeled", "fixed", "context", "uncertain"],
)
def test_paper_research_variable_signal_round_trips_scientific_role(
    variable_role: str,
) -> None:
    signal = PaperResearchSignal.from_mapping(
        {
            "document_id": "paper-1",
            "signal_type": "variable",
            "label": "processing speed",
            "variable_role": variable_role,
            "design_type": "experimental",
            "claim_scope": "current_work",
            "source_refs": [
                {"source_kind": "block", "source_ref": "methods-1"}
            ],
        }
    )

    assert signal.variable_role == variable_role
    assert PaperResearchSignal.from_mapping(signal.to_record()) == signal


def test_paper_research_outcome_signal_has_no_factor_role() -> None:
    signal = PaperResearchSignal.from_mapping(
        {
            "document_id": "paper-1",
            "signal_type": "outcome",
            "label": "relative density",
            "variable_role": "not_applicable",
            "design_type": "experimental",
            "claim_scope": "current_work",
            "source_refs": [
                {"source_kind": "block", "source_ref": "results-1"}
            ],
        }
    )

    assert signal.variable_role == "not_applicable"


@pytest.mark.parametrize(
    ("signal_type", "variable_role"),
    [("variable", "not_applicable"), ("outcome", "varied")],
)
def test_paper_research_signal_rejects_role_type_mismatch(
    signal_type: str,
    variable_role: str,
) -> None:
    with pytest.raises(ValueError, match="variable role"):
        PaperResearchSignal.from_mapping(
            {
                "document_id": "paper-1",
                "signal_type": signal_type,
                "label": "research axis",
                "variable_role": variable_role,
                "source_refs": [
                    {"source_kind": "block", "source_ref": "source-1"}
                ],
            }
        )


def test_review_synthesis_map_round_trips_source_linked_research_judgments() -> None:
    item = ReviewKnowledgeItem.from_mapping(
        {
            "content": "Reported porosity trends disagree across scan strategies.",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["scan strategy"],
            "outcomes": ["porosity"],
            "conditions": ["laser powder bed fusion"],
            "source_refs": [
                {"source_kind": "block", "source_ref": "review-conclusion"}
            ],
            "confidence": 0.82,
        }
    )
    skim = PaperResearchMap.from_mapping(
        {
            "document_id": "review-paper",
            "doc_role": "review",
            "review_synthesis": ReviewSynthesisMap(disputes=(item,)).to_record(),
        }
    )

    restored = PaperResearchMap.from_mapping(skim.to_record())

    assert restored == skim
    assert restored.review_synthesis.disputes == (item,)
    assert restored.review_synthesis.citation_leads == ()


def test_non_review_paper_rejects_review_synthesis_map() -> None:
    with pytest.raises(ValueError, match="review synthesis requires a review paper"):
        PaperResearchMap.from_mapping(
            {
                "document_id": "experimental-paper",
                "doc_role": "experimental",
                "review_synthesis": {
                    "evidence_gaps": [
                        {
                            "content": "More validation is needed.",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "block-1"}
                            ],
                        }
                    ]
                },
            }
        )


def test_paper_source_unit_coverage_requires_status_specific_reason() -> None:
    no_signal = PaperSourceUnitCoverage.from_mapping(
        {
            "source_unit_id": "results-1-source-1",
            "window_id": "results-1",
            "source_kind": "block",
            "source_ref": "block-1",
            "status": "no_study_signal",
            "reason": "The unit contains only general background.",
        }
    )

    assert no_signal.status is PaperSourceUnitCoverageStatus.NO_STUDY_SIGNAL
    assert PaperSourceUnitCoverage.from_mapping(no_signal.to_record()) == no_signal

    with pytest.raises(ValueError, match="requires a reason"):
        PaperSourceUnitCoverage.from_mapping(
            {
                **no_signal.to_record(),
                "reason": None,
            }
        )

    with pytest.raises(ValueError, match="cannot have a reason"):
        PaperSourceUnitCoverage.from_mapping(
            {
                **no_signal.to_record(),
                "status": "relationship_emitted",
            }
        )


def test_paper_map_retains_unique_source_unit_coverage() -> None:
    coverage = PaperSourceUnitCoverage.from_mapping(
        {
            "source_unit_id": "methods-1-source-1",
            "window_id": "methods-1",
            "source_kind": "block",
            "source_ref": "block-1",
            "status": "extraction_failed",
            "reason": "The window extraction failed validation.",
        }
    )
    skim = PaperResearchMap.from_mapping(
        {
            "document_id": "paper-1",
            "source_unit_coverage": [coverage.to_record()],
        }
    )

    assert skim.source_unit_coverage == (coverage,)
    assert skim.coverage_complete is False
    assert PaperResearchMap.from_mapping(skim.to_record()) == skim

    with pytest.raises(ValueError, match="coverage ids must be unique"):
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "source_unit_coverage": [coverage.to_record(), coverage.to_record()],
            }
        )


def _objective(**overrides) -> ResearchObjective:
    payload = {
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "question": "How does heat treatment affect strength?",
        "material_scope": ["316L"],
        "variables": ["heat treatment"],
        "outcomes": ["strength"],
        "mechanisms": ["precipitation hardening"],
        "constraints": ["LPBF 316L"],
        "seed_document_ids": ["paper-1", "paper-2"],
    }
    payload.update(overrides)
    return ResearchObjective.from_mapping(payload)


def _analysis(**overrides) -> ObjectiveAnalysis:
    total_document_count = int(overrides.get("total_document_count", 2))
    payload = {
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "analysis_version": 1,
        "document_inputs": tuple(
            PreparedDocumentInput(
                f"paper-{position}",
                f"fingerprint-{position}",
            )
            for position in range(1, total_document_count + 1)
        ),
        "pipeline_version": "objective-analysis.v1",
        "model_name": "model-1",
        "prompt_versions": {"evidence": "v1", "finding": "v1"},
        "total_document_count": 2,
    }
    payload.update(overrides)
    return ObjectiveAnalysis(**payload)


def _candidate_evidence(**overrides) -> ObjectiveEvidence:
    payload = {
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "analysis_version": 1,
        "document_id": "paper-1",
        "source_kind": "text_window",
        "source_ref": "block-1",
        "source_excerpt": "The heat-treated sample reached 610 MPa.",
        "evidence_role": "direct_result",
        "selection_status": "candidate",
        "attribution_scope": "not_attributable",
        "resolution_status": "unknown",
    }
    payload.update(overrides)
    return ObjectiveEvidence.from_mapping(payload)


def test_build_research_objective_id_covers_complete_scientific_intent() -> None:
    question = "How does heat treatment affect corrosion resistance of LPBF 316L?"
    scientific_intent = {
        "question": question,
        "material_scope": ("316L",),
        "variables": ("heat treatment",),
        "outcomes": ("corrosion resistance",),
        "mechanisms": ("passive film stability",),
        "constraints": ("LPBF",),
        "requested_comparator": "as-built material",
    }

    objective_id = build_research_objective_id(**scientific_intent)

    assert objective_id == build_research_objective_id(**scientific_intent)
    assert objective_id.startswith(
        "obj_how-does-heat-treatment-affect-corrosion-resistance"
    )
    assert objective_id != build_research_objective_id(
        **{**scientific_intent, "outcomes": ("pitting potential",)}
    )


def test_research_objective_normalizes_scope_and_round_trips() -> None:
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": "collection-1",
            "question": "How does heat treatment affect corrosion resistance?",
            "material_scope": ["316L", "316L", ""],
            "variables": ["heat treatment", None],
            "outcomes": ("corrosion", "EIS"),
            "mechanisms": ["passive film stability"],
            "constraints": ["LPBF", "room-temperature electrochemical testing"],
            "requested_comparator": "as-built material",
            "seed_document_ids": ["paper-1", "paper-2"],
            "excluded_document_ids": ["paper-3"],
            "confidence": 1.2,
        }
    )

    record = objective.to_record()

    assert record["collection_id"] == "collection-1"
    assert record["objective_id"] == build_research_objective_id(
        question=record["question"],
        material_scope=tuple(record["material_scope"]),
        variables=tuple(record["variables"]),
        outcomes=tuple(record["outcomes"]),
        mechanisms=tuple(record["mechanisms"]),
        constraints=tuple(record["constraints"]),
        requested_comparator=record["requested_comparator"],
    )
    assert record["material_scope"] == ["316L"]
    assert record["variables"] == ["heat treatment"]
    assert record["outcomes"] == ["corrosion", "EIS"]
    assert record["mechanisms"] == ["passive film stability"]
    assert record["constraints"] == [
        "LPBF",
        "room-temperature electrochemical testing",
    ]
    assert record["requested_comparator"] == "as-built material"
    assert record["confidence"] == 1.0
    assert record["confirmation_status"] == "candidate"
    assert "analysis_error" not in record
    assert "analysis_progress" not in record
    assert is_question_shaped_objective(objective) is True


def test_research_objective_requires_explicit_variables_and_outcomes() -> None:
    with pytest.raises(ValueError, match="at least one variable"):
        _objective(variables=[])
    with pytest.raises(ValueError, match="at least one outcome"):
        _objective(outcomes=[])


def test_research_objective_recognizes_a_chinese_question_mark() -> None:
    objective = _objective(
        question="在激光增材制造 Ti-6Al-4V 中，能量输入如何影响延性？",
    )

    assert is_question_shaped_objective(objective) is True


def test_research_objective_rejects_secondary_terms_that_duplicate_primary_terms() -> None:
    with pytest.raises(ValueError, match="mechanisms duplicate"):
        _objective(mechanisms=["strength"])
    with pytest.raises(ValueError, match="constraints duplicate"):
        _objective(constraints=["heat treatment"])


def test_research_objective_rejects_overlapping_document_scope() -> None:
    with pytest.raises(ValueError, match="documents overlap"):
        _objective(excluded_document_ids=["paper-2"])


def test_research_objective_confirms_queues_and_publishes_active_version() -> None:
    candidate = _objective()
    confirmed = candidate.confirm()
    queued = confirmed.queue_analysis(1)
    succeeded = _analysis().start().succeed()
    published = queued.publish_analysis(succeeded)

    assert candidate.confirmation_status == "candidate"
    assert confirmed.confirmation_status == "confirmed"
    assert queued.active_analysis_version == 1
    assert queued.published_analysis_version is None
    assert published.published_analysis_version == 1


def test_research_objective_requires_newer_analysis_version() -> None:
    objective = _objective(
        confirmation_status="confirmed",
        active_analysis_version=2,
        published_analysis_version=1,
    )

    with pytest.raises(ValueError, match="newer than active"):
        objective.queue_analysis(2)


def test_research_objective_rejects_cross_objective_publication() -> None:
    objective = _objective(confirmation_status="confirmed").queue_analysis(1)
    analysis = _analysis(objective_id="another-objective").start().succeed()

    with pytest.raises(ValueError, match="another objective"):
        objective.publish_analysis(analysis)


def test_objective_analysis_lifecycle_and_progress_are_immutable() -> None:
    queued = _analysis(total_document_count=6)
    started_at = datetime(2026, 7, 22, tzinfo=timezone.utc)
    running = queued.start(started_at=started_at)
    progressed = running.update_progress(
        phase="evidence_extraction",
        processed_document_count=2,
        total_document_count=6,
        current_document_id="paper-3",
        progress_message="Analyzing paper 3 of 6.",
    )
    succeeded = progressed.succeed()

    assert queued.status == "queued"
    assert running.status == "running"
    assert running.started_at == started_at
    assert progressed.current_document_id == "paper-3"
    assert progressed.processed_document_count == 2
    assert succeeded.status == "succeeded"
    assert succeeded.processed_document_count == 6
    assert succeeded.current_document_id is None
    assert succeeded.error_message is None


def test_objective_analysis_records_exact_prepared_document_inputs() -> None:
    document_inputs = (
        PreparedDocumentInput("paper-1", "fingerprint-1"),
        PreparedDocumentInput("paper-2", "fingerprint-2"),
    )

    analysis = ObjectiveAnalysis(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        document_inputs=document_inputs,
        pipeline_version="objective-analysis.v1",
        model_name="test-model",
        prompt_versions={},
        total_document_count=2,
    )

    assert analysis.document_inputs == document_inputs
    assert analysis.to_record()["document_inputs"] == [
        {
            "document_id": "paper-1",
            "preparation_fingerprint": "fingerprint-1",
        },
        {
            "document_id": "paper-2",
            "preparation_fingerprint": "fingerprint-2",
        },
    ]


def test_objective_analysis_rejects_document_count_that_differs_from_manifest() -> None:
    with pytest.raises(ValueError, match="document input count"):
        ObjectiveAnalysis(
            collection_id="collection-1",
            objective_id="objective-1",
            analysis_version=1,
            document_inputs=(PreparedDocumentInput("paper-1", "fingerprint-1"),),
            pipeline_version="objective-analysis.v1",
            model_name=None,
            prompt_versions={},
            total_document_count=2,
        )


def test_objective_analysis_failure_is_terminal_and_retry_is_new_version() -> None:
    failed = _analysis().start().fail(
        error_code="provider_connection",
        error_message="model endpoint unavailable",
    )

    assert failed.status == "failed"
    assert failed.error_code == "provider_connection"
    with pytest.raises(ValueError, match="failed -> running"):
        failed.start()

    retry = _analysis(analysis_version=2)
    assert retry.status == "queued"
    assert retry.analysis_version == 2


def test_objective_analysis_rejects_invalid_document_progress() -> None:
    with pytest.raises(ValueError, match="exceeds total"):
        _analysis(processed_document_count=3, total_document_count=2)

    with pytest.raises(ValueError, match="status is queued"):
        _analysis().update_progress(
            phase="routing",
            processed_document_count=0,
            total_document_count=2,
        )

    with pytest.raises(ValueError, match="cannot change total document count"):
        _analysis(total_document_count=6).start().update_progress(
            phase="framing",
            processed_document_count=1,
            total_document_count=7,
        )


def test_objective_analysis_statuses_do_not_include_objective_confirmation() -> None:
    assert OBJECTIVE_ANALYSIS_STATUSES == {
        "queued",
        "running",
        "succeeded",
        "failed",
    }


def test_objective_document_evidence_preserves_scientific_absence_as_success() -> None:
    started_at = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)
    completed_at = datetime(2026, 8, 27, 8, 2, tzinfo=timezone.utc)
    running = ObjectiveDocumentEvidence.start(
        collection_id="collection-1",
        objective_id="objective-1",
        document_id="paper-1",
        input_fingerprint="checkpoint-input-1",
        analysis_version=2,
        extraction_version="objective-document-evidence.v1",
        model_name="test-model",
        started_at=started_at,
    )
    contribution = PaperContribution.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 2,
            "document_id": "paper-1",
            "analysis_status": "analyzed",
            "relevance": "low",
            "paper_role": "primary_experiment",
            "confidence": 0.8,
            "evidence_disposition": "no_routable_evidence",
            "routed_source_count": 0,
            "extracted_source_count": 0,
            "comparable_evidence_count": 0,
            "failed_source_count": 0,
            "evidence_disposition_reason": (
                "The paper was inspected and contains no Source for this Objective."
            ),
        }
    )

    succeeded = running.succeed(
        contribution=contribution,
        evidence_records=(),
        completed_at=completed_at,
    )

    assert succeeded.status == "succeeded"
    assert succeeded.contribution == contribution
    assert succeeded.evidence_records == ()
    assert succeeded.completed_at == completed_at
    assert ObjectiveDocumentEvidence.from_mapping(succeeded.to_record()) == succeeded


def test_objective_document_evidence_rejects_cross_document_payload() -> None:
    running = ObjectiveDocumentEvidence.start(
        collection_id="collection-1",
        objective_id="objective-1",
        document_id="paper-1",
        input_fingerprint="checkpoint-input-1",
        analysis_version=2,
        extraction_version="objective-document-evidence.v1",
        model_name="test-model",
    )
    contribution = PaperContribution.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 2,
            "document_id": "paper-2",
            "analysis_status": "failed",
            "relevance": "uncertain",
            "paper_role": "uncertain",
            "warnings": ["Technical extraction failed."],
            "confidence": 0,
        }
    )

    with pytest.raises(ValueError, match="another document"):
        running.fail(
            contribution=contribution,
            error_code="provider_error",
            error_message="provider unavailable",
        )


def test_paper_contribution_uses_document_as_subordinate_identity() -> None:
    contribution = PaperContribution.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "document_id": "paper-1",
            "analysis_status": "analyzed",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "contribution_summary": "Direct tensile comparison.",
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["strength"],
            "confidence": 0.9,
        }
    )

    assert contribution.key == (
        "collection-1",
        "objective-1",
        1,
        "paper-1",
    )
    assert "frame_id" not in contribution.to_record()


def test_paper_contribution_records_auditable_evidence_disposition() -> None:
    contribution = PaperContribution.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "document_id": "paper-1",
            "analysis_status": "analyzed",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "evidence_disposition": "comparable_evidence",
            "routed_source_count": 3,
            "extracted_source_count": 2,
            "comparable_evidence_count": 7,
            "failed_source_count": 1,
            "evidence_disposition_reason": (
                "One selected source failed; comparable evidence survived."
            ),
            "confidence": 0.9,
        }
    )

    assert contribution.evidence_disposition == "comparable_evidence"
    assert contribution.routed_source_count == 3
    assert contribution.extracted_source_count == 2
    assert contribution.comparable_evidence_count == 7
    assert contribution.failed_source_count == 1
    assert PaperContribution.from_mapping(contribution.to_record()) == contribution


def test_paper_contribution_rejects_partial_or_inconsistent_evidence_accounting() -> None:
    base = {
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "analysis_version": 1,
        "document_id": "paper-1",
        "analysis_status": "analyzed",
        "relevance": "high",
        "paper_role": "primary_experiment",
        "confidence": 0.9,
    }

    with pytest.raises(ValueError, match="all present or all absent"):
        PaperContribution.from_mapping(
            {
                **base,
                "evidence_disposition": "no_routable_evidence",
                "routed_source_count": 0,
            }
        )
    with pytest.raises(ValueError, match="requires comparable Evidence"):
        PaperContribution.from_mapping(
            {
                **base,
                "evidence_disposition": "comparable_evidence",
                "routed_source_count": 1,
                "extracted_source_count": 1,
                "comparable_evidence_count": 0,
                "failed_source_count": 0,
            }
        )


def test_excluded_paper_contribution_requires_reason() -> None:
    with pytest.raises(ValueError, match="requires a reason"):
        PaperContribution.from_mapping(
            {
                "collection_id": "collection-1",
                "objective_id": "objective-1",
                "analysis_version": 1,
                "document_id": "paper-1",
                "analysis_status": "excluded",
            }
        )


def test_objective_evidence_preserves_source_and_structured_result() -> None:
    candidate = _candidate_evidence()
    selected = candidate.select(
        evidence_role="direct_result",
        reason="Reports the target strength result.",
    )
    extracted = selected.mark_extracted(
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
        },
        reported_result={
            "outcome": "yield strength",
            "value": 610,
            "unit": "MPa",
            "direction": "increase",
            "result_text": "The heat-treated sample reached 610 MPa.",
        },
        attribution_scope="isolated_effect",
        scientific_context={
            "material": [{"name": "alloy", "value": "316L"}],
            "test": [{"name": "method", "value": "tensile test"}],
        },
    )

    assert candidate.selection_status == "candidate"
    assert selected.selection_status == "selected"
    assert extracted.selection_status == "extracted"
    assert extracted.source_excerpt == "The heat-treated sample reached 610 MPa."
    assert extracted.reported_result is not None
    assert extracted.reported_result.value == 610
    assert extracted.changed_variables[0].name == "heat treatment"
    assert extracted.attribution_scope == "isolated_effect"
    assert extracted.supports_finding is True
    assert "route_id" not in extracted.to_record()
    assert "evidence_unit_id" not in extracted.to_record()


def test_association_evidence_allows_variable_without_comparison_endpoints() -> None:
    evidence = _candidate_evidence(
        selection_status="extracted",
        changed_variables=[
            {
                "name": "laser exposure condition",
                "baseline_value": None,
                "target_value": None,
            }
        ],
        reported_result={
            "outcome": "residual stress",
            "value": None,
            "unit": None,
            "direction": "decrease",
            "result_text": "Scanning strategy was associated with lower residual stress.",
        },
        attribution_scope="association_only",
        resolution_status="partial",
    )

    assert evidence.changed_variables[0].baseline_value is None
    assert evidence.changed_variables[0].target_value is None
    assert evidence.supports_finding is True


def test_objective_evidence_exposes_research_state_without_promoting_incomplete_facts() -> None:
    comparable = _candidate_evidence(
        selection_status="extracted",
        changed_variables=[
            {
                "name": "heat treatment",
                "baseline_value": "as-built",
                "target_value": "annealed",
            }
        ],
        comparison={
            "baseline_label": "as-built",
            "target_label": "annealed",
            "axis_names": ["heat treatment"],
            "comparable": True,
        },
        reported_result={
            "outcome": "yield strength",
            "value": 610,
            "unit": "MPa",
            "direction": "increase",
            "result_text": "Yield strength increased to 610 MPa.",
        },
        attribution_scope="isolated_effect",
        resolution_status="resolved",
    )
    association = _candidate_evidence(
        selection_status="extracted",
        changed_variables=[{"name": "laser power"}],
        reported_result={
            "outcome": "porosity",
            "value": None,
            "unit": None,
            "direction": "decrease",
            "result_text": "Higher laser power was associated with lower porosity.",
        },
        attribution_scope="association_only",
        resolution_status="partial",
    )
    descriptive = _candidate_evidence(
        selection_status="extracted",
        reported_result={
            "outcome": "microstructure",
            "value": None,
            "unit": None,
            "direction": "mixed",
            "result_text": "The sample showed a cellular microstructure.",
        },
        attribution_scope="descriptive_only",
        resolution_status="partial",
    )
    incomparable = _candidate_evidence(
        selection_status="extracted",
        comparison={
            "baseline_label": "as-built",
            "target_label": "heat-treated",
            "axis_names": ["heat treatment"],
            "comparable": False,
            "incomparability_reasons": ["Different test methods."],
        },
        reported_result={
            "outcome": "yield strength",
            "value": 610,
            "unit": "MPa",
            "direction": "increase",
            "result_text": "Yield strength increased.",
        },
        attribution_scope="not_attributable",
        resolution_status="partial",
    )
    failed = _candidate_evidence(
        selection_status="failed",
        failure_reason="Provider timeout.",
    )

    assert comparable.evidence_status == "comparable"
    assert association.evidence_status == "association_only"
    assert descriptive.evidence_status == "descriptive"
    assert incomparable.evidence_status == "non_comparable"
    assert failed.evidence_status == "extraction_failed"


def test_objective_evidence_result_preserves_categorical_transition() -> None:
    evidence = _candidate_evidence(
        selection_status="extracted",
        changed_variables=[
            {
                "name": "heat treatment",
                "baseline_value": "as-built",
                "target_value": "annealed",
            }
        ],
        comparison={
            "baseline_label": "as-built",
            "target_label": "annealed",
            "axis_names": ["heat treatment"],
            "comparable": True,
        },
        reported_result={
            "outcome": "phase composition",
            "value": "alpha+beta",
            "baseline_value": "alpha-prime",
            "target_value": "alpha+beta",
            "unit": None,
            "direction": "changed",
            "result_text": "Phase composition changed from alpha-prime to alpha+beta.",
        },
        attribution_scope="isolated_effect",
        resolution_status="resolved",
    )

    assert evidence.reported_result is not None
    assert evidence.reported_result.baseline_value == "alpha-prime"
    assert evidence.reported_result.target_value == "alpha+beta"
    assert evidence.reported_result.direction == "changed"
    assert evidence.to_record()["reported_result"] == {
        "outcome": "phase composition",
        "value": "alpha+beta",
        "baseline_value": "alpha-prime",
        "target_value": "alpha+beta",
        "unit": None,
            "direction": "changed",
            "result_text": "Phase composition changed from alpha-prime to alpha+beta.",
            "result_kind": "observed",
        }


def test_context_only_evidence_cannot_establish_finding_by_itself() -> None:
    evidence = _candidate_evidence(
        evidence_role="condition_context",
    ).select(evidence_role="condition_context")
    extracted = evidence.mark_extracted(
        scientific_context={
            "test": [{"name": "temperature", "value": 25, "unit": "C"}]
        }
    )

    assert extracted.supports_finding is True
    assert extracted.evidence_role == "condition_context"


def test_objective_evidence_rejects_invalid_state_and_empty_source() -> None:
    rejected = _candidate_evidence().reject("Not relevant to the target property.")

    with pytest.raises(ValueError, match="rejected -> extracted"):
        rejected.mark_extracted(
            scientific_context={"process": [{"name": "state", "value": "invalid"}]}
        )
    with pytest.raises(ValueError, match="identity and source"):
        _candidate_evidence(source_excerpt="")


def test_objective_evidence_preserves_jointly_varied_factors() -> None:
    evidence = _candidate_evidence(
        selection_status="extracted",
        changed_variables=[
            {"name": "scan speed", "baseline_value": 750, "target_value": 1000, "unit": "mm/s"},
            {"name": "hatch spacing", "baseline_value": 80, "target_value": 100, "unit": "um"},
            {"name": "energy density", "baseline_value": 389, "target_value": 278, "unit": "J/mm3"},
        ],
        comparison={
            "baseline_label": "condition A",
            "target_label": "condition B",
            "axis_names": ["scan speed", "hatch spacing", "energy density"],
            "comparable": True,
        },
        reported_result={
            "outcome": "elongation",
            "value": 18.2,
            "unit": "%",
            "direction": "decrease",
            "result_text": "Elongation was 18.2% for condition B.",
        },
        attribution_scope="joint_effect",
        resolution_status="resolved",
    )

    assert [item.name for item in evidence.changed_variables] == [
        "scan speed",
        "hatch spacing",
        "energy density",
    ]
    assert evidence.attribution_scope == "joint_effect"


def test_objective_evidence_rejects_single_factor_attribution_for_joint_change() -> None:
    with pytest.raises(ValueError, match="isolated effect requires exactly one"):
        _candidate_evidence(
            selection_status="extracted",
            changed_variables=[
                {"name": "scan speed", "baseline_value": 750, "target_value": 1000},
                {"name": "hatch spacing", "baseline_value": 80, "target_value": 100},
            ],
            comparison={
                "baseline_label": "A",
                "target_label": "B",
                "axis_names": ["scan speed", "hatch spacing"],
                "comparable": True,
            },
            reported_result={
                "outcome": "density",
                "value": 98.9,
                "unit": "%",
                "direction": "increase",
                "result_text": "Density increased to 98.9%.",
            },
            attribution_scope="isolated_effect",
            resolution_status="resolved",
        )


def test_objective_evidence_rejects_effect_without_variable_change() -> None:
    with pytest.raises(ValueError, match="requires changed variable values"):
        _candidate_evidence(
            selection_status="extracted",
            changed_variables=[
                {"name": "laser power", "baseline_value": 200, "target_value": 200}
            ],
            comparison={
                "baseline_label": "A",
                "target_label": "B",
                "axis_names": ["laser power"],
                "comparable": True,
            },
            reported_result={
                "outcome": "density",
                "value": 98.9,
                "unit": "%",
                "direction": "no_change",
                "result_text": "Density was 98.9% in condition B.",
            },
            attribution_scope="isolated_effect",
            resolution_status="resolved",
        )


def test_objective_evidence_marks_incomparable_sample_states_unattributable() -> None:
    evidence = _candidate_evidence(
        selection_status="extracted",
        changed_variables=[
            {"name": "post treatment", "baseline_value": "as-SLM", "target_value": "HIP-SLM"}
        ],
        comparison={
            "baseline_label": "as-SLM",
            "target_label": "HIP-SLM",
            "axis_names": ["post treatment"],
            "comparable": False,
            "incomparability_reasons": ["HIP changes porosity and residual stress state"],
        },
        reported_result={
            "outcome": "fatigue life",
            "value": None,
            "unit": None,
            "direction": "increase",
            "result_text": "HIP-SLM showed longer fatigue life than as-SLM.",
        },
        attribution_scope="not_attributable",
        resolution_status="resolved",
    )

    assert evidence.comparison is not None
    assert evidence.comparison.comparable is False
    with pytest.raises(ValueError, match="incomparable evidence cannot be attributed"):
        _candidate_evidence(
            **{
                **evidence.to_record(),
                "attribution_scope": "isolated_effect",
            }
        )


def test_normalizers_remain_stable() -> None:
    assert normalize_objective_terms(["LPBF", "lpbf", " SLM "]) == (
        "LPBF",
        "SLM",
    )
    assert normalize_objective_confidence(float("nan")) == 0.0


def test_paper_research_map_round_trips_scope_and_unresolved_signals() -> None:
    skim = PaperResearchMap.from_mapping(
        {
            "document_id": "paper-1",
            "studies": [
                {
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "experiment_label": "LPBF process-window study",
                    "material_scope": ["316L"],
                    "process_context": ["LPBF"],
                    "relationships": [
                        {
                            "varied_factors": ["laser power", "hatch spacing"],
                            "outcome": "relative density",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "methods-1"},
                                {"source_kind": "table", "source_ref": "table-2"},
                            ],
                            "confidence": 0.88,
                        },
                        {
                            "varied_factors": ["laser power", "hatch spacing"],
                            "outcome": "yield strength",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "methods-1"},
                                {"source_kind": "block", "source_ref": "results-3"},
                            ],
                            "confidence": 0.84,
                        },
                    ],
                    "confidence": 0.88,
                }
            ],
            "unresolved_signals": [
                {
                    "signal_id": "signal-1",
                    "signal_type": "outcome",
                    "label": "surface roughness",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "experiment_label": "surface study",
                    "material_scope": ["316L"],
                    "process_context": ["LPBF"],
                    "source_refs": [
                        {"source_kind": "table", "source_ref": "table-4"}
                    ],
                    "confidence": 0.71,
                    "reason": "No source-supported changed variable was identified.",
                }
            ],
        }
    )

    record = skim.to_record()

    study = skim.studies[0]
    assert len(study.relationships) == 2
    assert study.relationships[0].varied_factors == ("laser power", "hatch spacing")
    assert {item.outcome for item in study.relationships} == {
        "relative density",
        "yield strength",
    }
    assert record["studies"][0]["material_scope"] == ["316L"]
    assert record["studies"][0]["process_context"] == ["LPBF"]
    assert record["studies"][0]["relationships"][0]["source_refs"] == [
        {"source_kind": "block", "source_ref": "methods-1"},
        {"source_kind": "table", "source_ref": "table-2"},
    ]
    assert record["unresolved_signals"][0]["signal_type"] == "outcome"
    assert record["unresolved_signals"][0]["design_type"] == "experimental"
    assert record["unresolved_signals"][0]["claim_scope"] == "current_work"
    assert record["unresolved_signals"][0]["experiment_label"] == "surface study"
    assert PaperResearchMap.from_mapping(record) == skim


def test_pre_objective_paper_map_does_not_represent_experiment_context() -> None:
    paper_map = PaperResearchMap.from_mapping(
        {
            "document_id": "paper-1",
            "studies": [
                {
                    "material_scope": ["Ti-6Al-4V"],
                    "process_context": ["laser powder bed fusion"],
                    "sample_context": ["vertical tensile coupons"],
                    "test_context": ["ASTM E8 tensile test"],
                    "comparator": "as-built reference",
                    "fixed_conditions": ["strain rate = 0.001 /s"],
                    "relationships": [
                        {
                            "varied_factors": ["laser power"],
                            "outcome": "porosity",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "abstract"}
                            ],
                        }
                    ],
                }
            ],
        }
    )

    scope = paper_map.studies[0]
    assert not hasattr(scope, "sample_context")
    assert not hasattr(scope, "test_context")
    assert not hasattr(scope, "comparator")
    assert not hasattr(scope, "fixed_conditions")
    assert set(paper_map.to_record()["studies"][0]) == {
        "study_id",
        "document_id",
        "design_type",
        "claim_scope",
        "experiment_label",
        "material_scope",
        "process_context",
        "relationships",
        "confidence",
    }


def test_paper_research_signal_identity_uses_only_preliminary_scope() -> None:
    payload = {
        "signal_type": "outcome",
        "label": "yield strength",
        "design_type": "experimental",
        "claim_scope": "current_work",
        "experiment_label": "tensile study",
        "material_scope": ["316L"],
        "process_context": ["LPBF"],
        "sample_context": ["vertical coupons"],
        "test_context": ["ASTM E8"],
        "comparator": "as-built reference",
        "fixed_conditions": ["strain rate = 0.001 /s"],
        "source_refs": [{"source_kind": "block", "source_ref": "results-1"}],
        "confidence": 0.8,
    }

    base = PaperResearchMap.from_mapping(
        {"document_id": "paper-1", "unresolved_signals": [payload]}
    ).unresolved_signals[0]
    other_test = PaperResearchMap.from_mapping(
        {
            "document_id": "paper-1",
            "unresolved_signals": [{**payload, "test_context": ["nanoindentation"]}],
        }
    ).unresolved_signals[0]

    assert base.signal_id == other_test.signal_id
    with pytest.raises(ValueError, match="design type"):
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "unresolved_signals": [{**payload, "design_type": "invalid"}],
            }
        )
    with pytest.raises(ValueError, match="claim scope"):
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "unresolved_signals": [{**payload, "claim_scope": "invalid"}],
            }
        )


def test_paper_study_signal_identity_is_scoped_to_its_document() -> None:
    signal = {
        "signal_type": "outcome",
        "label": "yield strength",
        "source_refs": [{"source_kind": "block", "source_ref": "results-1"}],
    }

    first = PaperResearchMap.from_mapping(
        {"document_id": "paper-1", "unresolved_signals": [signal]}
    ).unresolved_signals[0]
    second = PaperResearchMap.from_mapping(
        {"document_id": "paper-2", "unresolved_signals": [signal]}
    ).unresolved_signals[0]

    assert first.signal_id != second.signal_id


def test_paper_study_and_relationship_ids_are_backend_derived_and_stable() -> None:
    payload = {
        "document_id": "paper-1",
        "design_type": "experimental",
        "claim_scope": "current_work",
        "experiment_label": "density experiment",
        "material_scope": ["316L"],
        "process_context": ["LPBF"],
        "relationships": [
            {
                "varied_factors": ["laser power"],
                "outcome": "relative density",
                "source_refs": [
                    {"source_kind": "block", "source_ref": "methods-1"},
                    {"source_kind": "block", "source_ref": "results-1"},
                ],
                "confidence": 0.88,
            }
        ],
        "confidence": 0.88,
    }

    study = PaperResearchScope.from_mapping(payload)
    same_study = PaperResearchScope.from_mapping(payload)
    different_source = PaperResearchScope.from_mapping(
        {
            **payload,
            "relationships": [
                {
                    **payload["relationships"][0],
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "methods-1"},
                        {"source_kind": "block", "source_ref": "results-2"},
                    ],
                }
            ],
        }
    )

    assert study.study_id.startswith("study_")
    assert study.relationships[0].relationship_id.startswith("relationship_")
    assert same_study.study_id == study.study_id
    assert different_source.study_id != study.study_id
    assert PaperResearchScope.from_mapping(study.to_record()) == study


def test_relationship_identity_includes_its_parent_study_boundary() -> None:
    shared_relationship = {
        "varied_factors": ["laser power"],
        "outcome": "yield strength",
        "source_refs": [{"source_kind": "table", "source_ref": "table-1"}],
    }
    tensile_study = PaperResearchScope.from_mapping(
        {
            "document_id": "paper-1",
            "design_type": "experimental",
            "claim_scope": "current_work",
            "experiment_label": "tensile experiment",
            "test_context": ["ASTM E8 tensile test"],
            "relationships": [shared_relationship],
        }
    )
    hardness_study = PaperResearchScope.from_mapping(
        {
            "document_id": "paper-1",
            "design_type": "experimental",
            "claim_scope": "current_work",
            "experiment_label": "hardness experiment",
            "test_context": ["Vickers microhardness test"],
            "relationships": [shared_relationship],
        }
    )

    assert (
        tensile_study.relationships[0].relationship_id
        != hardness_study.relationships[0].relationship_id
    )
    PaperResearchMap.from_mapping(
        {
            "document_id": "paper-1",
            "studies": [
                tensile_study.to_record(),
                hardness_study.to_record(),
            ],
        }
    )


def test_paper_study_owns_nested_relationship_identity() -> None:
    relationship = {
        "varied_factors": ["laser power"],
        "outcome": "relative density",
        "source_refs": [{"source_kind": "block", "source_ref": "results-1"}],
    }

    expected = PaperResearchScope.from_mapping(
        {"document_id": "paper-1", "relationships": [relationship]}
    )
    attempted_override = PaperResearchScope.from_mapping(
        {
            "document_id": "paper-1",
            "relationships": [{**relationship, "document_id": "paper-2"}],
        }
    )

    assert attempted_override.relationships == expected.relationships


def test_paper_map_rejects_study_owned_by_another_document() -> None:
    study = PaperResearchScope.from_mapping(
        {
            "document_id": "paper-2",
            "relationships": [
                {
                    "varied_factors": ["laser power"],
                    "outcome": "density",
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "results-1"}
                    ],
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="another document|document"):
        PaperResearchMap(
            document_id="paper-1",
            doc_role="experimental",
            studies=(study,),
            evidence_density="high",
            confidence=0.9,
            warnings=(),
        )


def _accounted_study_skim(
    document_id: str,
    *,
    relationships: list[tuple[list[str], str]],
) -> PaperResearchMap:
    return PaperResearchMap.from_mapping(
        {
            "document_id": document_id,
            "studies": [
                {
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "relationships": [
                        {
                            "varied_factors": factors,
                            "outcome": outcome,
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": f"{document_id}-{position}",
                                }
                            ],
                            "confidence": 0.9,
                        }
                        for position, (factors, outcome) in enumerate(
                            relationships,
                            start=1,
                        )
                    ],
                    "confidence": 0.9,
                }
            ],
        }
    )


def _study_disposition(
    skim: PaperResearchMap,
    relationship_position: int,
    status: PaperStudyDispositionStatus,
    *,
    objective_id: str | None = None,
    reason: str | None = None,
) -> PaperStudyDisposition:
    study = skim.studies[0]
    return PaperStudyDisposition(
        document_id=skim.document_id,
        study_id=study.study_id,
        relationship_id=study.relationships[relationship_position].relationship_id,
        status=status,
        objective_id=objective_id,
        reason=reason,
    )


def test_ready_objective_fact_set_requires_every_relationship_exactly_once() -> None:
    skim = _accounted_study_skim(
        "paper-1", relationships=[(["laser power"], "density")]
    )

    with pytest.raises(ValueError, match="pending"):
        ObjectiveFactSet(
            research_objectives_ready=True,
            document_inputs=(PreparedDocumentInput("paper-1", "fingerprint-1"),),
            study_dispositions=(
                _study_disposition(
                    skim,
                    0,
                    PaperStudyDispositionStatus.PENDING,
                ),
            ),
        )


def test_ready_objective_fact_set_rejects_duplicate_relationship_accounting() -> None:
    skim = _accounted_study_skim(
        "paper-1", relationships=[(["laser power"], "density")]
    )
    rejected = _study_disposition(
        skim,
        0,
        PaperStudyDispositionStatus.REJECTED,
        reason="Insufficient evidence for a defensible comparison.",
    )

    with pytest.raises(ValueError, match="duplicate|exactly once|more than once"):
        ObjectiveFactSet(
            research_objectives_ready=True,
            document_inputs=(PreparedDocumentInput("paper-1", "fingerprint-1"),),
            study_dispositions=(rejected, rejected),
        )


def test_ready_objective_fact_set_rejects_unknown_relationship_disposition() -> None:
    skim = _accounted_study_skim(
        "paper-1", relationships=[(["laser power"], "density")]
    )

    with pytest.raises(ValueError, match="unselected"):
        ObjectiveFactSet(
            research_objectives_ready=True,
            document_inputs=(PreparedDocumentInput("paper-1", "fingerprint-1"),),
            study_dispositions=(
                _study_disposition(
                    skim,
                    0,
                    PaperStudyDispositionStatus.REJECTED,
                    reason="Insufficient evidence for a defensible comparison.",
                ),
                PaperStudyDisposition(
                    document_id="paper-missing",
                    study_id="study_missing",
                    relationship_id="relationship_missing",
                    status=PaperStudyDispositionStatus.REJECTED,
                    reason="No source relationship exists for this identity.",
                ),
            ),
        )


def test_ready_objective_fact_set_rejects_cross_document_objective_lineage() -> None:
    skim = _accounted_study_skim(
        "paper-1", relationships=[(["laser power"], "relative density")]
    )
    relationship_id = skim.studies[0].relationships[0].relationship_id
    objective = _objective(
        objective_id="objective-cross-document",
        question="How does laser power affect relative density?",
        material_scope=[],
        variables=["laser power"],
        outcomes=["relative density"],
        mechanisms=[],
        constraints=[],
        seed_document_ids=["paper-2"],
        source_relationship_ids=[relationship_id],
        rank=1,
    )

    with pytest.raises(ValueError):
        ObjectiveFactSet(
            research_objectives_ready=True,
            document_inputs=(
                PreparedDocumentInput("paper-1", "fingerprint-1"),
                PreparedDocumentInput("paper-2", "fingerprint-2"),
            ),
            research_objectives=(objective,),
            study_dispositions=(
                _study_disposition(
                    skim,
                    0,
                    PaperStudyDispositionStatus.PROMOTED,
                    objective_id=objective.objective_id,
                ),
            ),
        )


def test_ready_objective_fact_set_accounts_multi_outcome_relationships_separately() -> None:
    skim = _accounted_study_skim(
        "paper-1",
        relationships=[
            (["laser power", "hatch spacing"], "relative density"),
            (["laser power", "hatch spacing"], "yield strength"),
        ],
    )
    density_id, strength_id = (
        relationship.relationship_id for relationship in skim.studies[0].relationships
    )
    density_objective = _objective(
        objective_id="objective-density",
        question="How do laser power and hatch spacing affect relative density?",
        variables=["laser power", "hatch spacing"],
        outcomes=["relative density"],
        seed_document_ids=["paper-1"],
        source_relationship_ids=[density_id],
        rank=1,
    )
    strength_objective = _objective(
        objective_id="objective-strength",
        question="How do laser power and hatch spacing affect yield strength?",
        variables=["laser power", "hatch spacing"],
        outcomes=["yield strength"],
        seed_document_ids=["paper-1"],
        source_relationship_ids=[strength_id],
        rank=2,
    )

    facts = ObjectiveFactSet(
        research_objectives_ready=True,
        document_inputs=(PreparedDocumentInput("paper-1", "fingerprint-1"),),
        research_objectives=(density_objective, strength_objective),
        study_dispositions=(
            _study_disposition(
                skim,
                0,
                PaperStudyDispositionStatus.PROMOTED,
                objective_id=density_objective.objective_id,
            ),
            _study_disposition(
                skim,
                1,
                PaperStudyDispositionStatus.PROMOTED,
                objective_id=strength_objective.objective_id,
            ),
        ),
    )

    assert {item.relationship_id for item in facts.study_dispositions} == {
        density_id,
        strength_id,
    }
    assert density_objective.source_relationship_ids == (density_id,)
    assert strength_objective.source_relationship_ids == (strength_id,)
