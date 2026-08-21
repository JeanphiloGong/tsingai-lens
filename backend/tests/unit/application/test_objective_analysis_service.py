from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from application.core.objectives.analysis_service import ObjectiveAnalysisService
from application.core.objectives.analysis.diagnostics import (
    record_analysis_diagnostic,
)
from application.core.objectives.research_objective_service import (
    ObjectiveAnalysisArtifacts,
)
from domain.core import (
    DocumentProfile,
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    ResearchObjective,
)
from domain.pipeline import ExecutionStats, ModelUsage, TokenUsage
from infra.llm.usage import (
    record_llm_completion,
    record_llm_prompt_version,
)


def _objective(*, published: int | None = None) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "question": "How does temperature affect strength?",
            "material_scope": ["Alloy A"],
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "seed_document_ids": ["paper-1"],
            "confidence": 0.9,
            "confirmation_status": "confirmed",
            "active_analysis_version": published,
            "published_analysis_version": published,
        }
    )


def _analysis(
    version: int,
    status: str = "queued",
    *,
    total_document_count: int = 1,
) -> ObjectiveAnalysis:
    analysis = ObjectiveAnalysis(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=version,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
        total_document_count=total_document_count,
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
            "changed_variables": [
                {
                    "name": "temperature",
                    "baseline_value": 500,
                    "target_value": 600,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "500 C",
                "target_label": "600 C",
                "axis_names": ["temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "strength",
                "value": 620,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Strength increased at 600 C.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [{"name": "alloy", "value": "Alloy A"}],
                "sample": [],
                "process": [],
                "test": [],
            },
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
            "statement": "Temperature was associated with strength.",
            "factors": ["temperature"],
            "outcome": "strength",
            "direction": "increase",
            "assertion_strength": "associative",
            "attribution_scope": "isolated_effect",
            "synthesis_status": "insufficient_confirmation",
            "certainty": 0.5,
            "mechanisms": [],
            "scientific_context": {
                "material": [{"name": "alloy", "value": "Alloy A"}],
                "sample": [],
                "process": [],
                "test": [],
            },
            "paper_contributions": [
                {
                    "document_id": "paper-1",
                    "analysis_status": "analyzed",
                    "supporting_evidence_ids": ["evidence-1"],
                }
            ],
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
                    "evidence_disposition": "comparable_evidence",
                    "routed_source_count": 1,
                    "extracted_source_count": 1,
                    "comparable_evidence_count": 1,
                    "failed_source_count": 0,
                }
            ),
        ),
        evidence_records=(_evidence(version),),
        findings=(_finding(version),),
    )


class FakeObjectiveRepository:
    def __init__(
        self,
        *,
        published: bool = False,
        claimable: bool = True,
        claim_error: Exception | None = None,
        claim_before_fail: bool = False,
        candidate_document_count: int = 1,
    ) -> None:
        self.objective = _objective(published=1 if published else None)
        self.analyses: dict[int, ObjectiveAnalysis] = (
            {1: _analysis(1, "succeeded")} if published else {}
        )
        self.findings = {1: (_finding(1),)} if published else {}
        self.evidence = {1: (_evidence(1),)} if published else {}
        self.contributions = (
            {1: _artifacts(1).contributions} if published else {}
        )
        self.claimable = claimable
        self.claim_error = claim_error
        self.claim_before_fail = claim_before_fail
        self.candidate_document_count = candidate_document_count
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
        analysis = _analysis(
            version,
            total_document_count=self.candidate_document_count,
        )
        self.analyses[version] = analysis
        self.objective = self.objective.queue_analysis(version)
        return self.objective, analysis

    def claim_analysis(self, collection_id, objective_id, analysis_version):
        if self.claim_error is not None:
            raise self.claim_error
        analysis = self.analyses[analysis_version]
        if not self.claimable or analysis.status != "queued":
            return None
        self.analyses[analysis_version] = analysis.start()
        return self.analyses[analysis_version]

    def update_analysis_progress(self, collection_id, objective_id, analysis_version, **kwargs):
        analysis = self.analyses[analysis_version].update_progress(**kwargs)
        self.analyses[analysis_version] = analysis
        return analysis

    def update_analysis_execution_stats(
        self,
        collection_id,
        objective_id,
        analysis_version,
        *,
        stats,
        model_name,
        prompt_versions,
        diagnostics,
    ):
        analysis = replace(
            self.analyses[analysis_version],
            stats=stats,
            model_name=model_name,
            prompt_versions=prompt_versions,
            diagnostics=diagnostics,
        )
        self.analyses[analysis_version] = analysis
        return analysis

    def fail_analysis(self, collection_id, objective_id, analysis_version, **kwargs):
        analysis = self.analyses[analysis_version]
        if self.claim_before_fail and analysis.status == "queued":
            analysis = analysis.start()
            self.analyses[analysis_version] = analysis
        expected_status = kwargs.pop("expected_status", None)
        if expected_status is not None and analysis.status != expected_status:
            return analysis
        analysis = analysis.fail(**kwargs)
        self.analyses[analysis_version] = analysis
        return analysis

    def publish_analysis(self, collection_id, objective_id, analysis_version, **artifacts):
        analysis = self.analyses[analysis_version].succeed()
        self.analyses[analysis_version] = analysis
        self.objective = self.objective.publish_analysis(analysis)
        self.findings[analysis_version] = artifacts["findings"]
        self.contributions[analysis_version] = artifacts["contributions"]
        self.evidence[analysis_version] = artifacts["evidence_records"]
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

    def list_contributions(self, collection_id, objective_id, analysis_version):
        return self.contributions.get(analysis_version, ())

    def list_evidence(self, collection_id, objective_id, analysis_version, **kwargs):
        records = self.evidence.get(analysis_version, ())
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", 100)
        return records[offset : offset + limit], len(records)


class FakeResearchObjectiveService:
    def __init__(self, *, artifacts=None, error: Exception | None = None) -> None:
        self.artifacts = artifacts
        self.error = error
        self.calls = 0
        self.document_profile_service = SimpleNamespace(
            read_document_profiles=lambda collection_id, build_id=None: (
                DocumentProfile.from_mapping(
                    {
                        "collection_id": collection_id,
                        "document_id": "paper-1",
                        "title": "Heat treatment paper",
                        "doc_type": "experimental",
                        "confidence": 0.9,
                    }
                ),
            )
        )

    def generate_objective_analysis_artifacts(
        self, collection_id, analysis, progress_callback=None
    ):
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


class UsageRecordingResearchObjectiveService(FakeResearchObjectiveService):
    def generate_objective_analysis_artifacts(
        self, collection_id, analysis, progress_callback=None
    ):
        record_llm_prompt_version("paper_framing", "paper_framing.v1")
        record_llm_completion(
            SimpleNamespace(
                model="model-a",
                usage=SimpleNamespace(
                    prompt_tokens=200,
                    completion_tokens=40,
                    total_tokens=240,
                ),
            ),
            requested_model="configured-model",
        )
        return super().generate_objective_analysis_artifacts(
            collection_id,
            analysis,
            progress_callback=progress_callback,
        )


class DiagnosticsRecordingResearchObjectiveService(FakeResearchObjectiveService):
    def generate_objective_analysis_artifacts(
        self, collection_id, analysis, progress_callback=None
    ):
        record_analysis_diagnostic(
            {
                "trace_type": "table_matrix_repair",
                "table_id": "table-1",
                "status": "verified",
            }
        )
        return super().generate_objective_analysis_artifacts(
            collection_id,
            analysis,
            progress_callback=progress_callback,
        )


def _service(*, repository=None, analyzer=None):
    repository = repository or FakeObjectiveRepository()
    analyzer = analyzer or FakeResearchObjectiveService()
    service = ObjectiveAnalysisService(
        objective_repository=repository,
        research_objective_service=analyzer,
    )
    return service, repository, analyzer


def test_objective_analysis_publishes_one_complete_version() -> None:
    service, repository, _analyzer = _service()
    queued = service.queue_analysis("collection-1", "objective-1")
    result = service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert queued["analysis"].status == "queued"
    assert result["analysis"].status == "succeeded"
    assert result["analysis"].progress_message == "Objective analysis completed."
    assert result["objective"].published_analysis_version == 1
    assert result["findings"] == (_finding(1),)
    assert result["paper_contributions"] == _artifacts(1).contributions
    assert result["warnings"] == []
    assert repository.published_calls == 1


def test_objective_analysis_aggregates_persisted_contribution_warnings() -> None:
    repository = FakeObjectiveRepository(published=True)
    contribution = _artifacts(1).contributions[0]
    warning = "1 selected source(s) failed extraction."
    repository.contributions[1] = (
        replace(contribution, warnings=(warning, warning)),
        replace(
            contribution,
            document_id="paper-2",
            warnings=(
                warning,
                "1 Source unit(s) used conservative paper framing fallback.",
            ),
        ),
    )
    service, _repository, _analyzer = _service(repository=repository)

    result = service.get_analysis_state("collection-1", "objective-1")

    assert result["warnings"] == [
        f"paper-1: {warning}",
        f"paper-2: {warning}",
        "paper-2: 1 Source unit(s) used conservative paper framing fallback.",
    ]


def test_objective_analysis_persists_real_model_prompt_and_token_usage() -> None:
    service, _repository, _analyzer = _service(
        analyzer=UsageRecordingResearchObjectiveService()
    )
    service.queue_analysis("collection-1", "objective-1")

    result = service.execute_queued_analysis("collection-1", "objective-1", 1)

    analysis = result["analysis"]
    assert analysis.model_name == "model-a"
    assert analysis.prompt_versions == {"paper_framing": "paper_framing.v1"}
    assert analysis.stats.model_usage == (
        ModelUsage("model-a", 1, TokenUsage(200, 40, 240)),
    )
    assert analysis.stats.prompt_versions == {
        "paper_framing": "paper_framing.v1"
    }
    assert analysis.stats.duration_ms is not None


def test_objective_analysis_persists_internal_diagnostics_without_public_exposure(
) -> None:
    service, repository, _analyzer = _service(
        analyzer=DiagnosticsRecordingResearchObjectiveService()
    )
    service.queue_analysis("collection-1", "objective-1")

    result = service.execute_queued_analysis("collection-1", "objective-1", 1)

    analysis = repository.read_analysis("collection-1", "objective-1", 1)
    assert analysis is not None
    assert analysis.diagnostics == (
        {
            "trace_type": "table_matrix_repair",
            "table_id": "table-1",
            "status": "verified",
        },
    )
    assert "diagnostics" not in analysis.to_record()
    assert "diagnostics" not in result["analysis"].to_record()


def test_failed_objective_analysis_keeps_internal_diagnostics() -> None:
    service, repository, _analyzer = _service(
        analyzer=DiagnosticsRecordingResearchObjectiveService(
            error=RuntimeError("analysis failed after table repair")
        )
    )
    service.queue_analysis("collection-1", "objective-1")

    result = service.execute_queued_analysis("collection-1", "objective-1", 1)

    analysis = repository.read_analysis("collection-1", "objective-1", 1)
    assert analysis is not None
    assert result["analysis"].status == "failed"
    assert analysis.diagnostics == (
        {
            "trace_type": "table_matrix_repair",
            "table_id": "table-1",
            "status": "verified",
        },
    )


def test_route_progress_does_not_replace_candidate_paper_count() -> None:
    service, repository, _analyzer = _service(
        repository=FakeObjectiveRepository(candidate_document_count=6)
    )
    service.queue_analysis("collection-1", "objective-1")
    running = repository.claim_analysis("collection-1", "objective-1", 1)
    assert running is not None

    progress = service._build_progress_callback(running)
    progress(
        {
            "phase": "objective_evidence_routing_started",
            "current": 1,
            "total": 7,
            "unit": "frames",
            "active_document_id": "paper-1",
            "message": "Routing the first paper.",
        }
    )
    progress(
        {
            "phase": "objective_evidence_extraction_started",
            "current": 26,
            "total": 26,
            "unit": "selections",
            "active_document_id": "paper-6",
            "message": "Extracting selected evidence.",
        }
    )

    progressed = repository.read_analysis("collection-1", "objective-1", 1)
    assert progressed.processed_document_count == 2
    assert progressed.total_document_count == 6


def test_empty_finding_output_publishes_scientific_abstention() -> None:
    artifacts = replace(_artifacts(1), findings=())
    service, repository, _analyzer = _service(
        analyzer=FakeResearchObjectiveService(artifacts=artifacts)
    )
    service.queue_analysis("collection-1", "objective-1")
    result = service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "succeeded"
    assert result["objective"].published_analysis_version == 1
    assert result["findings"] == ()
    assert result["paper_contributions"] == artifacts.contributions
    assert repository.published_calls == 1


@pytest.mark.parametrize(
    ("missing_field", "expected_error"),
    (
        ("contributions", "objective analysis produced no paper contributions"),
        ("evidence_records", "objective analysis produced no source-backed evidence"),
    ),
)
def test_missing_required_analysis_artifacts_still_fail_without_publication(
    missing_field: str,
    expected_error: str,
) -> None:
    artifacts = replace(_artifacts(1), **{missing_field: ()})
    service, repository, _analyzer = _service(
        analyzer=FakeResearchObjectiveService(artifacts=artifacts)
    )
    service.queue_analysis("collection-1", "objective-1")

    result = service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "failed"
    assert result["analysis"].error_message == expected_error
    assert result["objective"].published_analysis_version is None
    assert repository.published_calls == 0


def test_analysis_exception_is_diagnostic_and_retry_allocates_new_version() -> None:
    analyzer = FakeResearchObjectiveService(error=RuntimeError("model unavailable"))
    service, repository, _analyzer = _service(analyzer=analyzer)
    service.queue_analysis("collection-1", "objective-1")
    failed = service.execute_queued_analysis("collection-1", "objective-1", 1)
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
    result = service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "queued"
    assert analyzer.calls == 0


def test_failed_retry_keeps_previous_published_findings_readable() -> None:
    repository = FakeObjectiveRepository(published=True)
    analyzer = FakeResearchObjectiveService(error=TimeoutError("provider timeout"))
    service, _repository, _analyzer = _service(
        repository=repository, analyzer=analyzer
    )
    queued = service.queue_analysis("collection-1", "objective-1")
    result = service.execute_queued_analysis("collection-1", "objective-1", 2)

    assert queued["analysis"].analysis_version == 2
    assert result["analysis"].status == "failed"
    assert result["published_analysis"].analysis_version == 1
    assert result["findings"] == (_finding(1),)


def test_evidence_map_reads_only_the_published_analysis_version() -> None:
    service, _repository, _analyzer = _service(
        repository=FakeObjectiveRepository(published=True)
    )

    payload = service.get_evidence_map("collection-1", "objective-1")

    assert payload["analysis_version"] == 1
    assert payload["projection_version"] == "objective-evidence-map.v1"
    assert payload["coverage"]["finding_count"] == 1
    assert any(
        node["type"] == "document" and node["label"] == "Heat treatment paper"
        for node in payload["nodes"]
    )


def test_dispatch_failure_marks_the_queued_version_failed() -> None:
    service, repository, _analyzer = _service()
    service.queue_analysis("collection-1", "objective-1")

    result = service.fail_analysis_dispatch("collection-1", "objective-1", 1)

    assert result["analysis"].status == "failed"
    assert result["analysis"].error_code == "analysis_dispatch_failed"
    assert result["analysis"].error_message == (
        "Objective analysis could not be scheduled. Retry the analysis."
    )
    assert repository.read_analysis("collection-1", "objective-1", 1).status == (
        "failed"
    )


def test_dispatch_failure_does_not_fail_a_version_claimed_concurrently() -> None:
    repository = FakeObjectiveRepository(claim_before_fail=True)
    service, _repository, _analyzer = _service(repository=repository)
    service.queue_analysis("collection-1", "objective-1")

    result = service.fail_analysis_dispatch("collection-1", "objective-1", 1)

    assert result["analysis"].status == "running"


def test_claim_failure_marks_the_queued_version_failed() -> None:
    repository = FakeObjectiveRepository(
        claim_error=RuntimeError("database unavailable")
    )
    service, _repository, analyzer = _service(repository=repository)
    service.queue_analysis("collection-1", "objective-1")

    result = service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "failed"
    assert result["analysis"].error_message == "database unavailable"
    assert analyzer.calls == 0


def test_delayed_worker_does_not_claim_a_newer_retry_version() -> None:
    service, repository, analyzer = _service()
    service.queue_analysis("collection-1", "objective-1")
    repository.analyses[1] = repository.analyses[1].fail(
        error_code="failed",
        error_message="first attempt failed",
    )
    service.queue_analysis("collection-1", "objective-1")

    result = service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].analysis_version == 2
    assert result["analysis"].status == "queued"
    assert analyzer.calls == 0
