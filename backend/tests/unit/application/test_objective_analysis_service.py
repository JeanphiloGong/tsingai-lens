from __future__ import annotations

from dataclasses import replace

from application.core.objective_analysis_service import ObjectiveAnalysisService
from application.core.semantic_build.research_objective_service import (
    ObjectiveAnalysisArtifacts,
)
from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    ResearchObjective,
)


def _objective(*, published: int | None = None) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "question": "How does temperature affect strength?",
            "material_scope": ["Alloy A"],
            "process_axes": ["temperature"],
            "property_axes": ["strength"],
            "seed_document_ids": ["paper-1"],
            "confidence": 0.9,
            "confirmation_status": "confirmed",
            "active_analysis_version": published,
            "published_analysis_version": published,
        }
    )


def _analysis(version: int, status: str = "queued") -> ObjectiveAnalysis:
    analysis = ObjectiveAnalysis(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=version,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
        total_document_count=1,
    )
    if status == "running":
        return analysis.start()
    if status == "succeeded":
        return analysis.start().succeed()
    if status == "failed":
        return analysis.fail(error_code="failed", error_message="failed")
    return analysis


def _evidence(version: int) -> ObjectiveEvidence:
    return ObjectiveEvidence.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": version,
            "evidence_id": "evidence-1",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "source_excerpt": "Temperature changed strength.",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "evidence_kind": "measurement",
            "property_normalized": "strength",
            "value_payload": {"direction": "changes"},
            "join_keys": {"isolated_variable": "temperature"},
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )


def _finding(version: int) -> Finding:
    return Finding.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": version,
            "finding_id": "finding-1",
            "finding_level": "paper",
            "statement": "Temperature was associated with strength.",
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "scope_summary": "Alloy A",
            "evidence_strength": "weak",
            "generalization_status": "paper_level_only",
            "paper_count": 1,
            "confidence": 0.8,
            "relations": [
                {
                    "source_term": "temperature",
                    "relation_type": "associated_with",
                    "target_term": "strength",
                    "assertion_strength": "associative",
                    "supporting_evidence_ids": ["evidence-1"],
                }
            ],
            "context": {"supporting_evidence_ids": ["evidence-1"]},
            "derivation": {
                "synthesis_mode": "paper",
                "comparison_status": "insufficient_confirmation",
                "contributing_document_ids": ["paper-1"],
                "supporting_evidence_ids": ["evidence-1"],
                "rationale": "One direct result.",
            },
        }
    )


def _artifacts(version: int) -> ObjectiveAnalysisArtifacts:
    return ObjectiveAnalysisArtifacts(
        contributions=(
            PaperContribution.from_mapping(
                {
                    "collection_id": "collection-1",
                    "objective_id": "objective-1",
                    "analysis_version": version,
                    "document_id": "paper-1",
                    "analysis_status": "analyzed",
                    "relevance": "high",
                    "paper_role": "primary_experiment",
                    "confidence": 0.9,
                }
            ),
        ),
        evidence_records=(_evidence(version),),
        findings=(_finding(version),),
    )


class FakeObjectiveRepository:
    def __init__(self, *, published: bool = False, claimable: bool = True) -> None:
        self.objective = _objective(published=1 if published else None)
        self.analyses: dict[int, ObjectiveAnalysis] = (
            {1: _analysis(1, "succeeded")} if published else {}
        )
        self.findings = {1: (_finding(1),)} if published else {}
        self.claimable = claimable
        self.published_calls = 0

    def read_objective(self, collection_id, objective_id):
        return self.objective

    def confirm_objective(self, collection_id, objective_id):
        if self.objective.confirmation_status == "candidate":
            self.objective = self.objective.confirm()
        return self.objective

    def queue_analysis(self, collection_id, objective_id, **_kwargs):
        if any(item.status in {"queued", "running"} for item in self.analyses.values()):
            analysis = next(
                item
                for item in self.analyses.values()
                if item.status in {"queued", "running"}
            )
            return self.objective, analysis
        version = max(self.analyses, default=0) + 1
        analysis = _analysis(version)
        self.analyses[version] = analysis
        self.objective = self.objective.queue_analysis(version)
        return self.objective, analysis

    def claim_analysis(self, collection_id, objective_id, analysis_version):
        analysis = self.analyses[analysis_version]
        if not self.claimable or analysis.status != "queued":
            return None
        self.analyses[analysis_version] = analysis.start()
        return self.analyses[analysis_version]

    def update_analysis_progress(self, collection_id, objective_id, analysis_version, **kwargs):
        analysis = self.analyses[analysis_version].update_progress(**kwargs)
        self.analyses[analysis_version] = analysis
        return analysis

    def fail_analysis(self, collection_id, objective_id, analysis_version, **kwargs):
        analysis = self.analyses[analysis_version].fail(**kwargs)
        self.analyses[analysis_version] = analysis
        return analysis

    def publish_analysis(self, collection_id, objective_id, analysis_version, **artifacts):
        assert artifacts["findings"]
        analysis = self.analyses[analysis_version].succeed()
        self.analyses[analysis_version] = analysis
        self.objective = self.objective.publish_analysis(analysis)
        self.findings[analysis_version] = artifacts["findings"]
        self.published_calls += 1
        return self.objective, analysis

    def read_analysis(self, collection_id, objective_id, analysis_version=None):
        if analysis_version is None:
            analysis_version = self.objective.active_analysis_version
        return self.analyses.get(analysis_version)

    def read_published_analysis(self, collection_id, objective_id):
        return self.analyses.get(self.objective.published_analysis_version)

    def list_findings(self, collection_id, objective_id, analysis_version, **_kwargs):
        findings = self.findings.get(analysis_version, ())
        return findings, len(findings)


class FakeResearchObjectiveService:
    def __init__(self, *, artifacts=None, error: Exception | None = None) -> None:
        self.artifacts = artifacts
        self.error = error
        self.calls = 0

    def analyze_objective(self, collection_id, analysis, progress_callback=None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "evidence",
                    "current": 1,
                    "total": 1,
                    "active_document_id": "paper-1",
                    "message": "Extracting evidence.",
                }
            )
        return self.artifacts or _artifacts(analysis.analysis_version)


def _service(*, repository=None, analyzer=None):
    repository = repository or FakeObjectiveRepository()
    analyzer = analyzer or FakeResearchObjectiveService()
    service = ObjectiveAnalysisService(
        objective_repository=repository,
        research_objective_service=analyzer,
        model_name="test-model",
    )
    return service, repository, analyzer


def test_objective_analysis_publishes_one_complete_version() -> None:
    service, repository, _analyzer = _service()
    queued = service.queue_analysis("collection-1", "objective-1")
    result = service.run_analysis("collection-1", "objective-1")

    assert queued["analysis"].status == "queued"
    assert result["analysis"].status == "succeeded"
    assert result["objective"].published_analysis_version == 1
    assert result["findings"] == (_finding(1),)
    assert repository.published_calls == 1


def test_empty_finding_output_fails_version_without_publication() -> None:
    artifacts = replace(_artifacts(1), findings=())
    service, repository, _analyzer = _service(
        analyzer=FakeResearchObjectiveService(artifacts=artifacts)
    )
    service.queue_analysis("collection-1", "objective-1")
    result = service.run_analysis("collection-1", "objective-1")

    assert result["analysis"].status == "failed"
    assert result["objective"].published_analysis_version is None
    assert repository.published_calls == 0


def test_analysis_exception_is_diagnostic_and_retry_allocates_new_version() -> None:
    analyzer = FakeResearchObjectiveService(error=RuntimeError("model unavailable"))
    service, repository, _analyzer = _service(analyzer=analyzer)
    service.queue_analysis("collection-1", "objective-1")
    failed = service.run_analysis("collection-1", "objective-1")
    retry = service.queue_analysis("collection-1", "objective-1")

    assert failed["analysis"].status == "failed"
    assert failed["analysis"].error_message == "model unavailable"
    assert retry["analysis"].analysis_version == 2
    assert repository.objective.active_analysis_version == 2


def test_losing_worker_does_not_run_duplicate_analysis() -> None:
    repository = FakeObjectiveRepository(claimable=False)
    analyzer = FakeResearchObjectiveService()
    service, _repository, _analyzer = _service(
        repository=repository, analyzer=analyzer
    )
    service.queue_analysis("collection-1", "objective-1")
    result = service.run_analysis("collection-1", "objective-1")

    assert result["analysis"].status == "queued"
    assert analyzer.calls == 0


def test_failed_retry_keeps_previous_published_findings_readable() -> None:
    repository = FakeObjectiveRepository(published=True)
    analyzer = FakeResearchObjectiveService(error=TimeoutError("provider timeout"))
    service, _repository, _analyzer = _service(
        repository=repository, analyzer=analyzer
    )
    queued = service.queue_analysis("collection-1", "objective-1")
    result = service.run_analysis("collection-1", "objective-1")

    assert queued["analysis"].analysis_version == 2
    assert result["analysis"].status == "failed"
    assert result["published_analysis"].analysis_version == 1
    assert result["findings"] == (_finding(1),)
