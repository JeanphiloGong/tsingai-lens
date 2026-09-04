from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from application.core.objectives.analysis_service import (
    ObjectiveAnalysisDispatchError,
    ObjectiveAnalysisService,
)
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
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.pipeline import ExecutionStats, ModelUsage, TokenUsage
from infra.llm.usage import (
    record_llm_completion,
    record_llm_prompt_version,
)

pytestmark = pytest.mark.anyio

_DOCUMENT_IDS = ("paper-1",)
_DOCUMENT_INPUTS = (
    PreparedDocumentInput(
        document_id="paper-1",
        preparation_fingerprint="fingerprint-paper-1",
    ),
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _objective(
    *,
    published: int | None = None,
    confirmation_status: str = "confirmed",
) -> ResearchObjective:
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
            "confirmation_status": confirmation_status,
            "active_analysis_version": published,
            "published_analysis_version": published,
        }
    )


def _analysis(
    version: int,
    status: str = "queued",
    *,
    total_document_count: int = 1,
    document_inputs: tuple[PreparedDocumentInput, ...] = _DOCUMENT_INPUTS,
) -> ObjectiveAnalysis:
    analysis = ObjectiveAnalysis(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=version,
        document_inputs=document_inputs,
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


async def test_published_analysis_explains_scientific_abstention_for_incomplete_evidence() -> None:
    """A reported result without a comparison is not an unexplained empty run."""

    descriptive_evidence = replace(
        _evidence(1),
        evidence_id="descriptive-evidence",
        source_ref="block-descriptive-evidence",
        changed_variables=(),
        comparison=None,
        attribution_scope="descriptive_only",
    )
    contribution = replace(
        _artifacts(1).contributions[0],
        comparable_evidence_count=0,
        evidence_disposition="no_comparable_evidence",
        evidence_disposition_reason=(
            "Selected sources produced no comparable direct result for this Objective."
        ),
        evidence_status_counts=(("descriptive", 1),),
    )
    artifacts = ObjectiveAnalysisArtifacts(
        contributions=(contribution,),
        evidence_records=(descriptive_evidence,),
        findings=(),
    )
    service, _repository, _analyzer = _service(
        analyzer=FakeResearchObjectiveService(artifacts=artifacts)
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "succeeded"
    assert result["analysis"].abstention_reason == "insufficient_evidence"
    assert result["analysis"].abstention_note is not None
    assert "descriptive" in result["analysis"].abstention_note


async def test_published_analysis_exposes_all_evidence_statuses_and_actionable_gaps() -> None:
    """A missing Finding must not hide source-backed results or technical gaps."""

    base = _evidence(1)
    descriptive = replace(
        base,
        evidence_id="descriptive-evidence",
        source_ref="block-descriptive",
        changed_variables=(),
        comparison=None,
        attribution_scope="descriptive_only",
    )
    needs_context = replace(
        base,
        evidence_id="needs-context-evidence",
        source_ref="block-context",
        selection_status="candidate",
        selection_reason="Target outcome mentioned but needs same-paper context.",
        changed_variables=(),
        comparison=None,
        reported_result=None,
        attribution_scope="not_attributable",
        scientific_context=base.scientific_context.__class__(),
        resolution_status="unresolved",
        confidence=0.0,
    )
    failed = replace(
        base,
        evidence_id="failed-evidence",
        source_ref="block-failed",
        selection_status="failed",
        selection_reason="Selected source requires extraction.",
        failure_reason="StructuredOutputSaturatedError: output limit",
        changed_variables=(),
        comparison=None,
        reported_result=None,
        attribution_scope="not_attributable",
        scientific_context=base.scientific_context.__class__(),
        resolution_status="unknown",
        confidence=0.0,
    )
    contribution = replace(
        _artifacts(1).contributions[0],
        comparable_evidence_count=1,
        evidence_status_counts=(
            ("comparable", 1),
            ("descriptive", 1),
            ("extraction_failed", 1),
            ("needs_context", 1),
        ),
    )
    artifacts = ObjectiveAnalysisArtifacts(
        contributions=(contribution,),
        evidence_records=(base, descriptive, needs_context, failed),
        findings=(_finding(1),),
    )
    service, _repository, _analyzer = _service(
        analyzer=FakeResearchObjectiveService(artifacts=artifacts)
    )

    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis("collection-1", "objective-1", 1)

    review = result["evidence_review"]
    assert review["total_evidence_count"] == 4
    assert review["status_counts"] == {
        "comparable": 1,
        "descriptive": 1,
        "extraction_failed": 1,
        "needs_context": 1,
    }
    assert review["comparable_evidence_count"] == 1
    assert review["gap_count"] == 3
    assert {item["evidence_status"] for item in review["gaps"]} == {
        "descriptive",
        "extraction_failed",
        "needs_context",
    }
    assert any("output limit" in item["reason"] for item in review["gaps"])


class FakeObjectiveRepository:
    def __init__(
        self,
        *,
        published: bool = False,
        claimable: bool = True,
        claim_error: Exception | None = None,
        claim_before_fail: bool = False,
        candidate_document_count: int = 1,
        confirmation_status: str = "confirmed",
    ) -> None:
        self.objective = _objective(
            published=1 if published else None,
            confirmation_status=confirmation_status,
        )
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

    async def read_objective(self, collection_id, objective_id):
        return self.objective

    async def read_objective_record(self, collection_id, objective_id):
        return self.objective.to_record()

    async def queue_analysis(self, collection_id, objective_id, **_kwargs):
        if self.objective.confirmation_status == "candidate":
            self.objective = self.objective.confirm()
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
            total_document_count=len(_kwargs["document_inputs"]),
            document_inputs=_kwargs["document_inputs"],
        )
        self.analyses[version] = analysis
        self.objective = self.objective.queue_analysis(version)
        return self.objective, analysis

    async def claim_analysis(self, collection_id, objective_id, analysis_version):
        if self.claim_error is not None:
            raise self.claim_error
        analysis = self.analyses[analysis_version]
        if not self.claimable or analysis.status != "queued":
            return None
        self.analyses[analysis_version] = analysis.start()
        return self.analyses[analysis_version]

    async def update_analysis_progress(
        self, collection_id, objective_id, analysis_version, **kwargs
    ):
        analysis = self.analyses[analysis_version].update_progress(**kwargs)
        self.analyses[analysis_version] = analysis
        return analysis

    async def update_analysis_execution_stats(
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

    async def fail_analysis(
        self, collection_id, objective_id, analysis_version, **kwargs
    ):
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

    async def publish_analysis(
        self, collection_id, objective_id, analysis_version, **artifacts
    ):
        analysis = self.analyses[analysis_version].succeed(
            abstention_reason=artifacts.get("abstention_reason"),
            abstention_note=artifacts.get("abstention_note"),
        )
        self.analyses[analysis_version] = analysis
        self.objective = self.objective.publish_analysis(analysis)
        self.findings[analysis_version] = artifacts["findings"]
        self.contributions[analysis_version] = artifacts["contributions"]
        self.evidence[analysis_version] = artifacts["evidence_records"]
        self.published_calls += 1
        return self.objective, analysis

    async def read_analysis(
        self, collection_id, objective_id, analysis_version=None
    ):
        if analysis_version is None:
            analysis_version = self.objective.active_analysis_version
        return self.analyses.get(analysis_version)

    async def read_published_analysis(self, collection_id, objective_id):
        return self.analyses.get(self.objective.published_analysis_version)

    async def interrupt_active_analyses(self):
        interrupted = 0
        for version, analysis in tuple(self.analyses.items()):
            if analysis.status not in {"queued", "running"}:
                continue
            self.analyses[version] = analysis.fail(
                error_code="analysis_interrupted",
                error_message=(
                    "Objective analysis was interrupted by a backend restart. "
                    "Retry the analysis."
                ),
            )
            interrupted += 1
        return interrupted

    async def list_findings(
        self, collection_id, objective_id, analysis_version, **_kwargs
    ):
        findings = self.findings.get(analysis_version, ())
        return findings, len(findings)

    async def list_contributions(
        self, collection_id, objective_id, analysis_version
    ):
        return self.contributions.get(analysis_version, ())

    async def list_evidence(
        self, collection_id, objective_id, analysis_version, **kwargs
    ):
        records = self.evidence.get(analysis_version, ())
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", 100)
        return records[offset : offset + limit], len(records)


class FakeResearchObjectiveService:
    def __init__(self, *, artifacts=None, error: Exception | None = None) -> None:
        self.artifacts = artifacts
        self.error = error
        self.calls = 0
        async def read_document_profiles(collection_id, document_ids=None):
            if document_ids is not None and "paper-1" not in document_ids:
                return ()
            return (
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

        self.document_profile_service = SimpleNamespace(
            read_document_profiles=read_document_profiles
        )

    async def resolve_prepared_document_inputs(self, collection_id, document_ids):
        assert collection_id == "collection-1"
        assert document_ids
        return tuple(
            PreparedDocumentInput(
                document_id=document_id,
                preparation_fingerprint=f"fingerprint-{document_id}",
            )
            for document_id in document_ids
        )

    async def generate_objective_analysis_artifacts(
        self, collection_id, analysis, progress_callback=None
    ):
        self.calls += 1
        if self.error is not None:
            raise self.error
        if progress_callback is not None:
            await asyncio.to_thread(
                progress_callback,
                {
                    "phase": "evidence",
                    "current": 1,
                    "total": 1,
                    "active_document_id": "paper-1",
                    "message": "Extracting evidence.",
                },
            )
        return self.artifacts or _artifacts(analysis.analysis_version)


class UsageRecordingResearchObjectiveService(FakeResearchObjectiveService):
    async def generate_objective_analysis_artifacts(
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
        return await super().generate_objective_analysis_artifacts(
            collection_id,
            analysis,
            progress_callback=progress_callback,
        )


class DiagnosticsRecordingResearchObjectiveService(FakeResearchObjectiveService):
    async def generate_objective_analysis_artifacts(
        self, collection_id, analysis, progress_callback=None
    ):
        record_analysis_diagnostic(
            {
                "trace_type": "table_matrix_repair",
                "table_id": "table-1",
                "status": "verified",
            }
        )
        return await super().generate_objective_analysis_artifacts(
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


async def test_objective_analysis_publishes_one_complete_version() -> None:
    service, repository, _analyzer = _service()
    queued = await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert queued["analysis"].status == "queued"
    assert result["analysis"].status == "succeeded"
    assert result["analysis"].progress_message == "Objective analysis completed."
    assert result["objective"].published_analysis_version == 1
    assert result["findings"] == (_finding(1),)
    assert result["paper_contributions"] == _artifacts(1).contributions
    assert result["warnings"] == []
    assert repository.published_calls == 1


async def test_queue_analysis_confirms_a_candidate_and_queues_version_one() -> None:
    repository = FakeObjectiveRepository(confirmation_status="candidate")
    service, _, _ = _service(repository=repository)

    result = await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    assert result["objective"].confirmation_status == "confirmed"
    assert result["objective"].active_analysis_version == 1
    assert result["analysis"].analysis_version == 1
    assert result["analysis"].status == "queued"


async def test_start_analysis_queues_and_dispatches_the_canonical_worker() -> None:
    service, repository, analyzer = _service()

    queued = await service.start_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    assert queued["analysis"].status == "queued"
    assert queued["objective"].active_analysis_version == 1
    await asyncio.gather(*tuple(service._analysis_tasks))
    completed = await service.get_analysis_state("collection-1", "objective-1")
    assert completed["analysis"].status == "succeeded"
    assert analyzer.calls == 1
    assert repository.published_calls == 1


async def test_start_analysis_marks_a_version_failed_when_dispatch_cannot_start() -> None:
    repository = FakeObjectiveRepository()
    analyzer = FakeResearchObjectiveService()

    def unavailable_task_factory(_coroutine):
        raise RuntimeError("event loop unavailable")

    service = ObjectiveAnalysisService(
        objective_repository=repository,
        research_objective_service=analyzer,
        task_factory=unavailable_task_factory,
    )

    with pytest.raises(ObjectiveAnalysisDispatchError) as error:
        await service.start_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    assert error.value.analysis_version == 1
    failed = await repository.read_analysis("collection-1", "objective-1", 1)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "analysis_dispatch_failed"
    assert analyzer.calls == 0


async def test_start_analysis_enforces_the_service_concurrency_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ObjectiveAnalysisService(
        objective_repository=FakeObjectiveRepository(),
        research_objective_service=FakeResearchObjectiveService(),
        max_concurrency=1,
    )
    release_first = asyncio.Event()
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    active_count = 0
    maximum_active_count = 0

    async def queue_analysis(
        collection_id: str,
        objective_id: str,
        document_ids: tuple[str, ...],
    ) -> dict:
        assert document_ids
        version = 1 if objective_id == "objective-1" else 2
        return {"analysis": _analysis(version)}

    async def execute_queued_analysis(
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> dict:
        nonlocal active_count, maximum_active_count
        active_count += 1
        maximum_active_count = max(maximum_active_count, active_count)
        if objective_id == "objective-1":
            first_started.set()
            await release_first.wait()
        else:
            second_started.set()
        active_count -= 1
        return {"analysis_version": analysis_version}

    monkeypatch.setattr(service, "queue_analysis", queue_analysis)
    monkeypatch.setattr(service, "execute_queued_analysis", execute_queued_analysis)

    await service.start_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    await first_started.wait()
    await service.start_analysis("collection-1", "objective-2", ("paper-2",))
    await asyncio.sleep(0)

    assert not second_started.is_set()
    assert maximum_active_count == 1

    release_first.set()
    await asyncio.gather(*tuple(service._analysis_tasks))

    assert second_started.is_set()
    assert maximum_active_count == 1


async def test_restart_projects_unpublished_interrupted_analysis_as_not_started() -> None:
    service, repository, _ = _service()
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    repository.analyses[1] = repository.analyses[1].start()

    recovered = await service.recover_interrupted_analyses()
    state = await service.get_analysis_state("collection-1", "objective-1")

    assert recovered == 1
    assert repository.analyses[1].status == "failed"
    assert repository.analyses[1].error_code == "analysis_interrupted"
    assert state["analysis"] is None
    assert state["published_analysis"] is None


async def test_restart_preserves_published_results_and_retry_uses_next_version() -> None:
    service, repository, _ = _service(repository=FakeObjectiveRepository(published=True))
    _, interrupted = await repository.queue_analysis(
        "collection-1",
        "objective-1",
        document_inputs=_DOCUMENT_INPUTS,
    )
    repository.analyses[interrupted.analysis_version] = interrupted.start()

    recovered = await service.recover_interrupted_analyses()
    state = await service.get_analysis_state("collection-1", "objective-1")
    retry = await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    assert recovered == 1
    assert state["analysis"] is None
    assert state["published_analysis"].analysis_version == 1
    assert state["findings"] == (_finding(1),)
    assert retry["analysis"].analysis_version == 3
    assert retry["analysis"].status == "queued"


async def test_objective_analysis_aggregates_persisted_contribution_warnings() -> None:
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

    result = await service.get_analysis_state("collection-1", "objective-1")

    assert result["warnings"] == [
        f"paper-1: {warning}",
        f"paper-2: {warning}",
        "paper-2: 1 Source unit(s) used conservative paper framing fallback.",
    ]


async def test_objective_analysis_persists_real_model_prompt_and_token_usage() -> None:
    service, _repository, _analyzer = _service(
        analyzer=UsageRecordingResearchObjectiveService()
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

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


async def test_checkpoint_only_analysis_preserves_the_evidence_model_name() -> None:
    artifacts = replace(_artifacts(1), model_name="cached-evidence-model")
    service, _repository, _analyzer = _service(
        analyzer=FakeResearchObjectiveService(artifacts=artifacts)
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "succeeded"
    assert result["analysis"].model_name == "cached-evidence-model"


async def test_objective_analysis_persists_internal_diagnostics_without_public_exposure(
) -> None:
    service, repository, _analyzer = _service(
        analyzer=DiagnosticsRecordingResearchObjectiveService()
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    analysis = await repository.read_analysis("collection-1", "objective-1", 1)
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


async def test_failed_objective_analysis_keeps_internal_diagnostics() -> None:
    service, repository, _analyzer = _service(
        analyzer=DiagnosticsRecordingResearchObjectiveService(
            error=RuntimeError("analysis failed after table repair")
        )
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    analysis = await repository.read_analysis("collection-1", "objective-1", 1)
    assert analysis is not None
    assert result["analysis"].status == "failed"
    assert analysis.diagnostics == (
        {
            "trace_type": "table_matrix_repair",
            "table_id": "table-1",
            "status": "verified",
        },
    )


async def test_route_progress_does_not_replace_candidate_paper_count() -> None:
    service, repository, _analyzer = _service(
        repository=FakeObjectiveRepository(candidate_document_count=6)
    )
    await service.queue_analysis(
        "collection-1",
        "objective-1",
        tuple(f"paper-{index}" for index in range(1, 7)),
    )
    running = await repository.claim_analysis("collection-1", "objective-1", 1)
    assert running is not None

    progress = service._build_progress_callback(running)
    await asyncio.to_thread(
        progress,
        {
            "phase": "objective_evidence_routing_started",
            "current": 1,
            "total": 7,
            "unit": "frames",
            "active_document_id": "paper-1",
            "message": "Routing the first paper.",
        },
    )
    await asyncio.to_thread(
        progress,
        {
            "phase": "objective_evidence_extraction_started",
            "current": 26,
            "total": 26,
            "unit": "selections",
            "active_document_id": "paper-6",
            "message": "Extracting selected evidence.",
        },
    )

    progressed = await repository.read_analysis("collection-1", "objective-1", 1)
    assert progressed.processed_document_count == 2
    assert progressed.total_document_count == 6


async def test_empty_finding_output_publishes_scientific_abstention() -> None:
    artifacts = replace(_artifacts(1), findings=())
    service, repository, _analyzer = _service(
        analyzer=FakeResearchObjectiveService(artifacts=artifacts)
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "succeeded"
    assert result["objective"].published_analysis_version == 1
    assert result["findings"] == ()
    assert result["paper_contributions"] == artifacts.contributions
    assert repository.published_calls == 1


async def test_no_grounded_evidence_publishes_scientific_abstention() -> None:
    contribution = PaperContribution.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "document_id": "paper-1",
            "analysis_status": "analyzed",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "confidence": 0.9,
            "evidence_disposition": "no_routable_evidence",
            "routed_source_count": 0,
            "extracted_source_count": 0,
            "comparable_evidence_count": 0,
            "failed_source_count": 0,
            "evidence_disposition_reason": (
                "No source in this paper was selected for Objective extraction."
            ),
        }
    )
    artifacts = ObjectiveAnalysisArtifacts(
        contributions=(contribution,),
        evidence_records=(),
        findings=(),
    )
    service, repository, _analyzer = _service(
        analyzer=FakeResearchObjectiveService(artifacts=artifacts)
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "succeeded"
    assert result["objective"].published_analysis_version == 1
    assert result["findings"] == ()
    assert result["paper_contributions"] == (contribution,)
    assert result["warnings"] == [
        "paper-1: No source in this paper was selected for Objective extraction."
    ]
    assert repository.evidence[1] == ()
    assert repository.published_calls == 1


async def test_missing_paper_contributions_still_fails_without_publication() -> None:
    artifacts = replace(_artifacts(1), contributions=())
    service, repository, _analyzer = _service(
        analyzer=FakeResearchObjectiveService(artifacts=artifacts)
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "failed"
    assert (
        result["analysis"].error_message
        == "objective analysis produced no paper contributions"
    )
    assert result["objective"].published_analysis_version is None
    assert repository.published_calls == 0


async def test_all_relevant_paper_extractions_failed_without_publication() -> None:
    failed_evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "evidence_id": "failed-evidence-1",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "source_excerpt": "Source selected for inspection.",
            "evidence_role": "irrelevant",
            "selection_status": "failed",
            "attribution_scope": "not_attributable",
            "resolution_status": "unknown",
            "failure_reason": "RuntimeError: model unavailable",
            "confidence": 0.0,
        }
    )
    failed_contribution = PaperContribution.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "document_id": "paper-1",
            "analysis_status": "failed",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "warnings": ["1 selected source(s) failed extraction."],
            "confidence": 0.9,
            "evidence_disposition": "extraction_failed",
            "routed_source_count": 1,
            "extracted_source_count": 0,
            "comparable_evidence_count": 0,
            "failed_source_count": 1,
            "evidence_disposition_reason": (
                "1 selected source(s) failed extraction."
            ),
        }
    )
    artifacts = ObjectiveAnalysisArtifacts(
        contributions=(failed_contribution,),
        evidence_records=(failed_evidence,),
        findings=(),
    )
    service, repository, _analyzer = _service(
        analyzer=FakeResearchObjectiveService(artifacts=artifacts)
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "failed"
    assert (
        result["analysis"].error_message
        == "objective analysis failed to extract every relevant paper"
    )
    assert result["objective"].published_analysis_version is None
    assert repository.published_calls == 0


async def test_analysis_exception_is_diagnostic_and_retry_allocates_new_version() -> None:
    analyzer = FakeResearchObjectiveService(error=RuntimeError("model unavailable"))
    service, repository, _analyzer = _service(analyzer=analyzer)
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    failed = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )
    retry = await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    assert failed["analysis"].status == "failed"
    assert failed["analysis"].error_message == "model unavailable"
    assert retry["analysis"].analysis_version == 2
    assert repository.objective.active_analysis_version == 2


async def test_losing_worker_does_not_run_duplicate_analysis() -> None:
    repository = FakeObjectiveRepository(claimable=False)
    analyzer = FakeResearchObjectiveService()
    service, _repository, _analyzer = _service(
        repository=repository, analyzer=analyzer
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "queued"
    assert analyzer.calls == 0


async def test_failed_retry_keeps_previous_published_findings_readable() -> None:
    repository = FakeObjectiveRepository(published=True)
    analyzer = FakeResearchObjectiveService(error=TimeoutError("provider timeout"))
    service, _repository, _analyzer = _service(
        repository=repository, analyzer=analyzer
    )
    queued = await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 2
    )

    assert queued["analysis"].analysis_version == 2
    assert result["analysis"].status == "failed"
    assert result["published_analysis"].analysis_version == 1
    assert result["findings"] == (_finding(1),)


async def test_evidence_map_reads_only_the_published_analysis_version() -> None:
    service, _repository, _analyzer = _service(
        repository=FakeObjectiveRepository(published=True)
    )

    payload = await service.get_evidence_map("collection-1", "objective-1")

    assert payload["analysis_version"] == 1
    assert payload["projection_version"] == "objective-evidence-map.v1"
    assert payload["coverage"]["finding_count"] == 1
    assert any(
        node["type"] == "document" and node["label"] == "Heat treatment paper"
        for node in payload["nodes"]
    )


async def test_dispatch_failure_marks_the_queued_version_failed() -> None:
    service, repository, _analyzer = _service()
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.fail_analysis_dispatch(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "failed"
    assert result["analysis"].error_code == "analysis_dispatch_failed"
    assert result["analysis"].error_message == (
        "Objective analysis could not be scheduled. Retry the analysis."
    )
    analysis = await repository.read_analysis("collection-1", "objective-1", 1)
    assert analysis is not None
    assert analysis.status == "failed"


async def test_dispatch_failure_does_not_fail_a_version_claimed_concurrently() -> None:
    repository = FakeObjectiveRepository(claim_before_fail=True)
    service, _repository, _analyzer = _service(repository=repository)
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.fail_analysis_dispatch(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "running"


async def test_claim_failure_marks_the_queued_version_failed() -> None:
    repository = FakeObjectiveRepository(
        claim_error=RuntimeError("database unavailable")
    )
    service, _repository, analyzer = _service(repository=repository)
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "failed"
    assert result["analysis"].error_message == "database unavailable"
    assert analyzer.calls == 0


async def test_delayed_worker_does_not_claim_a_newer_retry_version() -> None:
    service, repository, analyzer = _service()
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    repository.analyses[1] = repository.analyses[1].fail(
        error_code="failed",
        error_message="first attempt failed",
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].analysis_version == 2
    assert result["analysis"].status == "queued"
    assert analyzer.calls == 0
