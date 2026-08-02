from __future__ import annotations

from dataclasses import replace

import pytest

from domain.core import (
    Finding,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperSkim,
    ResearchObjective,
)
from infra.persistence.postgres.objective_repository import PostgresObjectiveRepository
from tests.integration.persistence.test_postgres_source_artifacts import (
    _artifacts,
    _finish,
    _task,
)

pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)


def _objective(question: str = "How does temperature affect strength?") -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "col_source",
            "objective_id": "objective-1",
            "question": question,
            "material_scope": ["Alloy A"],
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "requested_comparator": "compare temperature conditions",
            "seed_document_ids": ["srcdoc_runtime"],
            "confidence": 0.9,
            "reason": "The paper reports comparable measurements.",
        }
    )


def _candidate_facts(objective: ResearchObjective | None = None) -> ObjectiveFactSet:
    return ObjectiveFactSet(
        research_objectives_ready=True,
        paper_skims=(
            PaperSkim.from_mapping(
                {
                    "document_id": "srcdoc_runtime",
                    "title": "Paper",
                    "source_filename": "paper.pdf",
                    "doc_role": "primary_experiment",
                    "candidate_materials": ["Alloy A"],
                    "candidate_processes": ["temperature"],
                    "candidate_properties": ["strength"],
                    "changed_variables": ["temperature"],
                    "possible_objectives": ["temperature versus strength"],
                    "evidence_density": "high",
                    "confidence": 0.9,
                }
            ),
        ),
        research_objectives=(objective or _objective(),),
    )


def _analysis_artifacts():
    artifacts = _artifacts()
    source_document_ids = (
        "srcdoc_runtime",
        "srcdoc_supporting",
        "srcdoc_contradicting",
        "srcdoc_excluded",
    )
    blocks = tuple(
        replace(
            artifacts.blocks[0],
            block_id=block_id,
            document_id=document_id,
            text=text,
            text_unit_ids=(),
        )
        for block_id, document_id, text in (
            ("block-support-1", source_document_ids[0], "Strength increased."),
            ("block-support-2", source_document_ids[1], "Strength increased."),
            ("block-contradict", source_document_ids[2], "Strength decreased."),
            ("block-context", source_document_ids[0], "Tests used ambient air."),
            ("block-mechanism", source_document_ids[0], "Grain refinement occurred."),
        )
    )
    return replace(
        artifacts,
        documents=tuple(
            replace(
                artifacts.documents[0],
                document_id=document_id,
                human_readable_id=position,
                title=f"Paper {position + 1}",
                text_unit_ids=(),
            )
            for position, document_id in enumerate(source_document_ids)
        ),
        text_units=(),
        blocks=blocks,
        tables=(),
        table_rows=(),
        table_cells=(),
    )


def _prepare_candidate(source_repository, builds, build_id: str = "build_objectives"):
    task = _task(f"task_{build_id}")
    builds.add_task(task, build_id=build_id)
    source_repository.replace_collection_artifacts(
        "col_source", build_id, _analysis_artifacts()
    )
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    repository.replace("col_source", build_id, _candidate_facts())
    _finish(builds, task, success=True)
    return repository


def _contribution(
    version: int,
    document_id: str = "srcdoc_runtime",
    *,
    analysis_status: str = "analyzed",
) -> PaperContribution:
    return PaperContribution.from_mapping(
        {
            "collection_id": "col_source",
            "objective_id": "objective-1",
            "analysis_version": version,
            "document_id": document_id,
            "analysis_status": analysis_status,
            "relevance": "high" if analysis_status == "analyzed" else "none",
            "paper_role": "primary_experiment",
            "contribution_summary": "Direct experimental evidence.",
            "material_match": ["Alloy A"],
            "changed_variables": ["temperature"],
            "measured_property_scope": ["strength"],
            "test_environment_scope": ["ambient"],
            "exclusion_reason": (
                "Outside the confirmed Objective scope."
                if analysis_status == "excluded"
                else None
            ),
            "confidence": 0.9,
        }
    )


def _evidence(
    version: int,
    evidence_id: str = "evidence-support-1",
    document_id: str = "srcdoc_runtime",
    source_ref: str = "block-support-1",
    *,
    evidence_role: str = "direct_result",
    direction: str = "increase",
    confidence: float = 0.9,
) -> ObjectiveEvidence:
    is_result = evidence_role in {"direct_result", "contradictory_result"}
    return ObjectiveEvidence.from_mapping(
        {
            "collection_id": "col_source",
            "objective_id": "objective-1",
            "analysis_version": version,
            "evidence_id": evidence_id,
            "document_id": document_id,
            "source_kind": "text_window",
            "source_ref": source_ref,
            "source_excerpt": "Strength increased from 90 to 100 MPa at 600 C.",
            "page_numbers": [1],
            "evidence_role": evidence_role,
            "selection_status": "extracted",
            "selection_reason": "Reports measured strength.",
            "changed_variables": [
                {
                    "name": "temperature",
                    "baseline_value": 500,
                    "target_value": 600,
                    "unit": "C",
                }
            ] if is_result else [],
            "comparison": {
                "baseline_label": "500 C",
                "target_label": "600 C",
                "axis_names": ["temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            } if is_result else None,
            "reported_result": {
                "outcome": "strength",
                "value": 100,
                "unit": "MPa",
                "direction": direction,
                "result_text": "Strength increased from 90 to 100 MPa.",
            } if is_result else None,
            "attribution_scope": (
                "isolated_effect" if is_result else "descriptive_only"
            ),
            "scientific_context": {
                "material": [{"name": "name", "value": "Alloy A"}],
                "sample": [],
                "process": [{"name": "temperature", "value": 600, "unit": "C"}],
                "test": [{"name": "environment", "value": "ambient"}],
            },
            "resolution_status": "resolved",
            "confidence": confidence,
        }
    )


def _finding(version: int) -> Finding:
    return Finding.from_mapping(
        {
            "collection_id": "col_source",
            "objective_id": "objective-1",
            "analysis_version": version,
            "finding_id": "finding-1",
            "statement": "Temperature was associated with strength under reported conditions.",
            "factors": ["temperature"],
            "outcome": "strength",
            "direction": "increase",
            "assertion_strength": "associative",
            "attribution_scope": "isolated_effect",
            "synthesis_status": "condition_dependent",
            "certainty": 0.7,
            "display_rank": 0,
            "mechanisms": [
                {
                    "source_term": "temperature",
                    "relation_type": "changes",
                    "target_term": "grain refinement",
                    "direction": "increase",
                    "assertion_strength": "descriptive",
                    "supporting_evidence_ids": ["evidence-mechanism"],
                }
            ],
            "scientific_context": {
                "material": [{"name": "name", "value": "Alloy A"}],
                "sample": [],
                "process": [{"name": "temperature", "value": 600, "unit": "C"}],
                "test": [{"name": "environment", "value": "ambient"}],
            },
            "limitations": ["The papers report an explicit condition boundary."],
            "paper_contributions": [
                {
                    "document_id": "srcdoc_runtime",
                    "analysis_status": "analyzed",
                    "supporting_evidence_ids": ["evidence-support-1"],
                    "context_evidence_ids": [
                        "evidence-context",
                        "evidence-mechanism",
                    ],
                    "condition_boundary_evidence_ids": ["evidence-context"],
                },
                {
                    "document_id": "srcdoc_supporting",
                    "analysis_status": "analyzed",
                    "supporting_evidence_ids": ["evidence-support-2"],
                },
                {
                    "document_id": "srcdoc_contradicting",
                    "analysis_status": "analyzed",
                    "contradicting_evidence_ids": ["evidence-contradict"],
                },
                {
                    "document_id": "srcdoc_excluded",
                    "analysis_status": "excluded",
                },
            ],
        }
    )


def _analysis_contributions(version: int) -> tuple[PaperContribution, ...]:
    return (
        _contribution(version),
        _contribution(version, "srcdoc_supporting"),
        _contribution(version, "srcdoc_contradicting"),
        _contribution(version, "srcdoc_excluded", analysis_status="excluded"),
    )


def _analysis_evidence(version: int) -> tuple[ObjectiveEvidence, ...]:
    return (
        _evidence(version),
        _evidence(
            version,
            "evidence-support-2",
            "srcdoc_supporting",
            "block-support-2",
            confidence=0.8,
        ),
        _evidence(
            version,
            "evidence-contradict",
            "srcdoc_contradicting",
            "block-contradict",
            evidence_role="contradictory_result",
            direction="decrease",
            confidence=0.7,
        ),
        _evidence(
            version,
            "evidence-context",
            "srcdoc_runtime",
            "block-context",
            evidence_role="condition_context",
        ),
        _evidence(
            version,
            "evidence-mechanism",
            "srcdoc_runtime",
            "block-mechanism",
            evidence_role="mechanism_context",
        ),
    )


def _queue_and_claim(repository: PostgresObjectiveRepository):
    repository.confirm_objective("col_source", "objective-1")
    objective, queued = repository.queue_analysis(
        "col_source",
        "objective-1",
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={"finding": "v1"},
    )
    claimed = repository.claim_analysis(
        "col_source", "objective-1", queued.analysis_version
    )
    assert claimed is not None
    return objective, claimed


def test_candidate_build_round_trips_without_analysis_artifacts(source_repositories) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_candidate(source_repository, builds)

    facts = repository.read("col_source")
    assert facts.research_objectives_ready is True
    assert facts.paper_skims == _candidate_facts().paper_skims
    assert tuple(
        {
            key: value
            for key, value in item.to_record().items()
            if key not in {"created_at", "updated_at"}
        }
        for item in facts.research_objectives
    ) == tuple(
        {
            key: value
            for key, value in item.to_record().items()
            if key not in {"created_at", "updated_at"}
        }
        for item in _candidate_facts().research_objectives
    )
    assert repository.list_objectives("col_source")[0].objective_id == "objective-1"
    assert repository.read_published_analysis("col_source", "objective-1") is None


def test_analysis_version_claim_progress_and_retry_are_explicit(source_repositories) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_candidate(source_repository, builds)
    objective, claimed = _queue_and_claim(repository)

    assert objective.active_analysis_version == 1
    assert claimed.status == "running"
    assert repository.claim_analysis("col_source", "objective-1", 1) is None
    progressed = repository.update_analysis_progress(
        "col_source",
        "objective-1",
        1,
        phase="evidence",
        processed_document_count=1,
        total_document_count=1,
        current_document_id="srcdoc_runtime",
        progress_message="Extracting evidence.",
    )
    assert progressed.phase == "evidence"

    failed = repository.fail_analysis(
        "col_source",
        "objective-1",
        1,
        error_code="provider_timeout",
        error_message="model unavailable",
    )
    assert failed.status == "failed"
    objective, retry = repository.queue_analysis(
        "col_source",
        "objective-1",
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    assert retry.analysis_version == 2
    assert objective.active_analysis_version == 2


def test_publish_is_atomic_and_reads_findings_and_exact_evidence(source_repositories) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_candidate(source_repository, builds)
    _objective_row, claimed = _queue_and_claim(repository)
    version = claimed.analysis_version

    objective, succeeded = repository.publish_analysis(
        "col_source",
        "objective-1",
        version,
        contributions=_analysis_contributions(version),
        evidence_records=_analysis_evidence(version),
        findings=(_finding(version),),
    )

    assert succeeded.status == "succeeded"
    assert objective.published_analysis_version == version
    published = repository.read_published_analysis("col_source", "objective-1")
    assert published is not None
    assert published.key == succeeded.key
    assert published.status == "succeeded"
    findings, finding_total = repository.list_findings(
        "col_source", "objective-1", version
    )
    evidence, evidence_total = repository.list_evidence(
        "col_source", "objective-1", version, finding_id="finding-1"
    )
    assert finding_total == 1
    assert findings == (_finding(version),)
    assert evidence_total == 5
    assert evidence == _analysis_evidence(version)


def test_failed_retry_preserves_previous_published_version(source_repositories) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_candidate(source_repository, builds)
    _objective_row, claimed = _queue_and_claim(repository)
    repository.publish_analysis(
        "col_source",
        "objective-1",
        1,
        contributions=_analysis_contributions(1),
        evidence_records=_analysis_evidence(1),
        findings=(_finding(1),),
    )
    objective, retry = repository.queue_analysis(
        "col_source",
        "objective-1",
        pipeline_version="test.v2",
        model_name=None,
        prompt_versions={},
    )
    repository.claim_analysis("col_source", "objective-1", retry.analysis_version)
    repository.fail_analysis(
        "col_source",
        "objective-1",
        retry.analysis_version,
        error_code="provider_timeout",
        error_message="timeout",
    )

    current = repository.read_objective("col_source", "objective-1")
    assert current is not None
    assert current.active_analysis_version == 2
    assert current.published_analysis_version == 1
    assert repository.read_published_analysis("col_source", "objective-1").analysis_version == 1


def test_publish_rejects_cross_version_artifacts_without_partial_writes(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_candidate(source_repository, builds)
    _objective_row, claimed = _queue_and_claim(repository)

    with pytest.raises(ValueError, match="cross-version"):
        repository.publish_analysis(
            "col_source",
            "objective-1",
            claimed.analysis_version,
            contributions=_analysis_contributions(1),
            evidence_records=(replace(_evidence(1), analysis_version=2),),
            findings=(_finding(1),),
        )

    assert repository.read_analysis("col_source", "objective-1", 1).status == "running"
    assert repository.read_published_analysis("col_source", "objective-1") is None
