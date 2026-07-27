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
            "process_axes": ["temperature"],
            "property_axes": ["strength"],
            "comparison_intent": "compare temperature conditions",
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


def _prepare_candidate(source_repository, builds, build_id: str = "build_objectives"):
    task = _task(f"task_{build_id}")
    builds.add_task(task, build_id=build_id)
    source_repository.replace_collection_artifacts(
        "col_source", build_id, _artifacts()
    )
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    repository.replace("col_source", build_id, _candidate_facts())
    _finish(builds, task, success=True)
    return repository


def _contribution(version: int) -> PaperContribution:
    return PaperContribution.from_mapping(
        {
            "collection_id": "col_source",
            "objective_id": "objective-1",
            "analysis_version": version,
            "document_id": "srcdoc_runtime",
            "analysis_status": "analyzed",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "contribution_summary": "Direct experimental evidence.",
            "material_match": ["Alloy A"],
            "changed_variables": ["temperature"],
            "measured_property_scope": ["strength"],
            "test_environment_scope": ["ambient"],
            "confidence": 0.9,
        }
    )


def _evidence(version: int) -> ObjectiveEvidence:
    return ObjectiveEvidence.from_mapping(
        {
            "collection_id": "col_source",
            "objective_id": "objective-1",
            "analysis_version": version,
            "evidence_id": "evidence-1",
            "document_id": "srcdoc_runtime",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "source_excerpt": "Result",
            "page_numbers": [1],
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "selection_reason": "Reports measured strength.",
            "evidence_kind": "measurement",
            "property_normalized": "strength",
            "material_system": {"name": "Alloy A"},
            "process_context": {"temperature_c": 600},
            "value_payload": {"value": 100},
            "unit": "MPa",
            "join_keys": {"isolated_variable": "temperature"},
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )


def _finding(version: int) -> Finding:
    return Finding.from_mapping(
        {
            "collection_id": "col_source",
            "objective_id": "objective-1",
            "analysis_version": version,
            "finding_id": "finding-1",
            "finding_level": "paper",
            "statement": "Temperature was associated with strength in this paper.",
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "direction": "changes",
            "scope_summary": "Alloy A under the reported tensile condition.",
            "evidence_strength": "weak",
            "generalization_status": "paper_level_only",
            "paper_count": 1,
            "confidence": 0.8,
            "display_rank": 0,
            "relations": [
                {
                    "source_term": "temperature",
                    "relation_type": "associated_with",
                    "target_term": "strength",
                    "assertion_strength": "associative",
                    "supporting_evidence_ids": ["evidence-1"],
                }
            ],
            "context": {
                "material_system": {"name": "Alloy A"},
                "supporting_evidence_ids": ["evidence-1"],
            },
            "derivation": {
                "synthesis_mode": "paper",
                "comparison_status": "insufficient_confirmation",
                "contributing_document_ids": ["srcdoc_runtime"],
                "supporting_evidence_ids": ["evidence-1"],
                "rationale": "One paper directly reports the result.",
            },
        }
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
        contributions=(_contribution(version),),
        evidence_records=(_evidence(version),),
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
    assert evidence_total == 1
    assert evidence == (_evidence(version),)


def test_failed_retry_preserves_previous_published_version(source_repositories) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_candidate(source_repository, builds)
    _objective_row, claimed = _queue_and_claim(repository)
    repository.publish_analysis(
        "col_source",
        "objective-1",
        1,
        contributions=(_contribution(1),),
        evidence_records=(_evidence(1),),
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
            contributions=(_contribution(1),),
            evidence_records=(replace(_evidence(1), analysis_version=2),),
            findings=(_finding(1),),
        )

    assert repository.read_analysis("col_source", "objective-1", 1).status == "running"
    assert repository.read_published_analysis("col_source", "objective-1") is None
