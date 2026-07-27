from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.core import (
    OBJECTIVE_ANALYSIS_STATUSES,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    ResearchObjective,
    build_research_objective_id,
    is_question_shaped_objective,
    normalize_objective_confidence,
    normalize_objective_terms,
)


def _objective(**overrides) -> ResearchObjective:
    payload = {
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "question": "How does heat treatment affect strength?",
        "material_scope": ["316L"],
        "process_axes": ["heat treatment"],
        "property_axes": ["strength"],
        "seed_document_ids": ["paper-1", "paper-2"],
    }
    payload.update(overrides)
    return ResearchObjective.from_mapping(payload)


def _analysis(**overrides) -> ObjectiveAnalysis:
    payload = {
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "analysis_version": 1,
        "source_build_id": "build-1",
        "pipeline_version": "objective-analysis.v1",
        "model_name": "model-1",
        "prompt_versions": {"evidence": "v1", "finding": "v1"},
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
        "evidence_kind": "measurement",
        "resolution_status": "unknown",
    }
    payload.update(overrides)
    return ObjectiveEvidence.from_mapping(payload)


def test_build_research_objective_id_is_stable_for_same_question() -> None:
    question = "How does heat treatment affect corrosion resistance of LPBF 316L?"

    assert build_research_objective_id(question) == build_research_objective_id(question)
    assert build_research_objective_id(question).startswith(
        "obj_how-does-heat-treatment-affect-corrosion-resistance"
    )


def test_research_objective_normalizes_scope_and_round_trips() -> None:
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": "collection-1",
            "question": "How does heat treatment affect corrosion resistance?",
            "material_scope": ["316L", "316L", ""],
            "process_axes": ["LPBF", "heat treatment", None],
            "property_axes": ("corrosion", "EIS"),
            "seed_document_ids": ["paper-1", "paper-2"],
            "excluded_document_ids": ["paper-3"],
            "confidence": 1.2,
        }
    )

    record = objective.to_record()

    assert record["collection_id"] == "collection-1"
    assert record["objective_id"] == build_research_objective_id(record["question"])
    assert record["material_scope"] == ["316L"]
    assert record["process_axes"] == ["LPBF", "heat treatment"]
    assert record["property_axes"] == ["corrosion", "EIS"]
    assert record["confidence"] == 1.0
    assert record["confirmation_status"] == "candidate"
    assert "analysis_error" not in record
    assert "analysis_progress" not in record
    assert is_question_shaped_objective(objective) is True


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
    queued = _analysis()
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


def test_objective_analysis_statuses_do_not_include_objective_confirmation() -> None:
    assert OBJECTIVE_ANALYSIS_STATUSES == {
        "queued",
        "running",
        "succeeded",
        "failed",
    }


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
        property_normalized="yield strength",
        value_payload={"value": 610},
        unit="MPa",
        material_system={"alloy": "316L"},
        join_keys={"isolated_variable": "heat treatment"},
    )

    assert candidate.selection_status == "candidate"
    assert selected.selection_status == "selected"
    assert extracted.selection_status == "extracted"
    assert extracted.source_excerpt == "The heat-treated sample reached 610 MPa."
    assert extracted.value_payload == {"value": 610}
    assert extracted.supports_finding is True
    assert "route_id" not in extracted.to_record()
    assert "evidence_unit_id" not in extracted.to_record()


def test_context_only_evidence_cannot_establish_finding_by_itself() -> None:
    evidence = _candidate_evidence(
        evidence_role="condition_context",
        evidence_kind="test_condition",
    ).select(evidence_role="condition_context")
    extracted = evidence.mark_extracted(test_condition={"temperature_c": 25})

    assert extracted.supports_finding is True
    assert extracted.evidence_role == "condition_context"


def test_objective_evidence_rejects_invalid_state_and_empty_source() -> None:
    rejected = _candidate_evidence().reject("Not relevant to the target property.")

    with pytest.raises(ValueError, match="rejected -> extracted"):
        rejected.mark_extracted(interpretation="invalid")
    with pytest.raises(ValueError, match="identity and source"):
        _candidate_evidence(source_excerpt="")


def test_normalizers_remain_stable() -> None:
    assert normalize_objective_terms(["LPBF", "lpbf", " SLM "]) == (
        "LPBF",
        "SLM",
    )
    assert normalize_objective_confidence(float("nan")) == 0.0
