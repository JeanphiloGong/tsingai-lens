from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from application.core.objectives.analysis.diagnostics import record_analysis_diagnostic
from application.core.objectives.analysis.paper_experiment_contract import (
    PaperExperimentDraft,
    PaperExperimentModelOutput,
    ReconciledPaperExperimentOutput,
)
from application.core.objectives.analysis.paper_experiment_extraction import (
    PaperExperimentExtractionResult,
    build_source_bundle,
)
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from application.core.objectives.analysis_service import (
    ObjectiveAnalysisDispatchError,
    ObjectiveAnalysisService,
    _experiment_abstention,
)
from application.core.objectives.objective_analysis_service import (
    ObjectiveExperimentAnalysisArtifacts,
    ObjectiveExperimentAnalysisService,
    _used_draft_source_labels,
)
from application.repositories.objective_repository import (
    ObjectiveAnalysis,
    StoredObjective,
)
from application.repositories.pipeline_run_repository import (
    ModelUsage,
    TokenUsage,
)
from domain.core import (
    DocumentProfile,
    Finding,
    ObjectiveEvidence,
    PaperContribution,
    PreparedDocumentInput,
    ResearchObjective,
)
from infra.llm.usage import record_llm_completion, record_llm_prompt_version

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


def _native_finding(version: int) -> Finding:
    """A Finding whose provenance is the experiment selection graph."""

    return Finding.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": version,
            "finding_id": "experiment-finding-1",
            "statement": "Temperature was associated with strength.",
            "factors": ["temperature"],
            "outcome": "strength",
            "direction": "increase",
            "assertion_strength": "associative",
            "attribution_scope": "isolated_effect",
            "synthesis_status": "single_study",
            "certainty": 0.5,
            "mechanisms": [],
            "scientific_context": {
                "material": [{"name": "alloy", "value": "Alloy A"}],
                "sample": [],
                "process": [],
                "test": [],
            },
            "paper_contributions": [],
            "selection_ids": ["selection-1"],
        }
    )


def _artifacts(version: int) -> ObjectiveExperimentAnalysisArtifacts:
    return ObjectiveExperimentAnalysisArtifacts(
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
        experiment_outputs=(),
    )


def test_boundary_source_labels_are_counted_from_nested_split_evidence() -> None:
    output = ReconciledPaperExperimentOutput(
        output=PaperExperimentModelOutput(
            document_id="paper-1",
            source_fingerprint="fingerprint-paper-1",
            experiments=(
                PaperExperimentDraft(
                    payload={
                        "series_key": "split-a",
                        "scope_kind": "physical_split",
                        "split_evidence": [
                            {
                                "source_label": "S001",
                                "reason": "independent population",
                            }
                        ],
                    }
                ),
            ),
            source_labels={
                "S001": {
                    "source_kind": "block",
                    "source_ref": "source-1",
                }
            },
        ),
        accepted_experiment_keys=("split-a",),
    )

    assert _used_draft_source_labels(output) == {"S001"}


class RecordingPaperExperimentExtractor:
    def __init__(self, result: PaperExperimentExtractionResult) -> None:
        self.result = result
        self.calls = []

    def extract(self, *, objective, bundle):
        self.calls.append({"objective": objective, "bundle": bundle})
        return self.result


def _document_extraction_service(result: PaperExperimentExtractionResult):
    extractor = RecordingPaperExperimentExtractor(result)
    return (
        ObjectiveExperimentAnalysisService(
            collection_service=object(),
            paper_map_repository=object(),
            objective_repository=object(),
            objective_input_service=object(),
            objective_source_screener=object(),
            paper_experiment_extractor=extractor,
        ),
        extractor,
    )


def _paper_frame() -> PaperAnalysisFrame:
    return PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "objective-1",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["Alloy A"],
            "changed_variables": ["temperature"],
            "measured_property_scope": ["strength"],
        }
    )


def _document_objective_inputs() -> dict:
    return {
        "documents": (SimpleNamespace(document_id="paper-1"),),
        "paper_maps": (),
        "profiles_by_document_id": {"paper-1": None},
        "blocks_by_document_id": {"paper-1": ()},
        "tables_by_document_id": {"paper-1": ()},
        "table_cells_by_document_id": {"paper-1": ()},
        "figures_by_document_id": {"paper-1": ()},
        "document_trees_by_document_id": {"paper-1": None},
    }


def _route(source_ref: str):
    return SimpleNamespace(
        document_id="paper-1",
        source_kind="block",
        source_ref=source_ref,
        extractable=True,
    )


def _bundle_for_refs(*source_refs: str, omitted=()):
    built = build_source_bundle(
        document_id="paper-1",
        source_fingerprint="fingerprint-paper-1",
        source_payloads=tuple(
            {
                "source_kind": "block",
                "source_ref": source_ref,
                "text": f"Source text for {source_ref}",
            }
            for source_ref in source_refs
        ),
    )
    return replace(built, omitted_source_refs=tuple(omitted))


def _patch_document_source_flow(
    monkeypatch: pytest.MonkeyPatch,
    *,
    routes,
    bundle,
) -> None:
    import application.core.objectives.objective_analysis_service as service_module

    monkeypatch.setattr(service_module, "screen_sources", lambda **_kwargs: (_paper_frame(),))
    monkeypatch.setattr(service_module, "route_sources", lambda **_kwargs: tuple(routes))
    monkeypatch.setattr(service_module, "build_bundle_from_routes", lambda **_kwargs: bundle)


def test_document_source_accounting_uses_authoritative_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = PaperExperimentExtractionResult(
        output=None,
        readiness=None,
        attempts=(),
        status="abstained",
    )
    service, _extractor = _document_extraction_service(result)
    bundle = _bundle_for_refs("results-1")
    _patch_document_source_flow(
        monkeypatch,
        routes=(_route("results-1"),),
        bundle=bundle,
    )

    artifacts = service._reconstruct_document_experiments(
        collection_id="collection-1",
        analysis=_analysis(1, "running"),
        objective=_objective(),
        objective_inputs=_document_objective_inputs(),
        progress_callback=None,
    )

    assert artifacts.contribution.evidence_disposition == "no_grounded_evidence"
    assert artifacts.contribution.routed_source_count == 1
    assert artifacts.contribution.uninspected_source_count == 0
    assert tuple(
        (item.source_kind, item.source_ref)
        for item in artifacts.contribution.inspected_source_refs
    ) == (("text_window", "results-1"),)


def test_document_provider_failure_marks_bundle_sources_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = PaperExperimentExtractionResult(
        output=None,
        readiness=None,
        attempts=(),
        status="technical_failure",
        diagnostics=("provider_technical_failure",),
    )
    service, _extractor = _document_extraction_service(result)
    bundle = _bundle_for_refs("results-1")
    _patch_document_source_flow(
        monkeypatch,
        routes=(_route("results-1"),),
        bundle=bundle,
    )

    artifacts = service._reconstruct_document_experiments(
        collection_id="collection-1",
        analysis=_analysis(1, "running"),
        objective=_objective(),
        objective_inputs=_document_objective_inputs(),
        progress_callback=None,
    )

    assert artifacts.contribution.evidence_disposition == "extraction_failed"
    assert artifacts.contribution.analysis_status == "failed"
    assert artifacts.contribution.failed_source_count == 1
    assert artifacts.contribution.uninspected_source_count == 0
    assert artifacts.contribution.inspected_source_refs == ()


def test_document_omitted_source_remains_uninspected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = PaperExperimentExtractionResult(
        output=None,
        readiness=None,
        attempts=(),
        status="abstained",
        omitted_source_refs=("results-2",),
    )
    service, _extractor = _document_extraction_service(result)
    bundle = _bundle_for_refs("results-1", omitted=("results-2",))
    _patch_document_source_flow(
        monkeypatch,
        routes=(_route("results-1"), _route("results-2")),
        bundle=bundle,
    )

    artifacts = service._reconstruct_document_experiments(
        collection_id="collection-1",
        analysis=_analysis(1, "running"),
        objective=_objective(),
        objective_inputs=_document_objective_inputs(),
        progress_callback=None,
    )

    assert artifacts.contribution.evidence_disposition == "coverage_incomplete"
    assert artifacts.contribution.routed_source_count == 2
    assert artifacts.contribution.uninspected_source_count == 1
    assert artifacts.contribution.failed_source_count == 0


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
        native_findings: tuple[Finding, ...] | None = None,
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
        self.experiment_published_calls = 0
        self.published_transaction = None
        self.native_findings = native_findings

    async def read_objective(self, collection_id, objective_id):
        return self.objective

    async def read_objective_record(self, collection_id, objective_id):
        return StoredObjective(self.objective)

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
        self.objective = self.objective.publish_analysis(
            collection_id=analysis.collection_id,
            objective_id=analysis.objective_id,
            analysis_version=analysis.analysis_version,
            status=analysis.status,
        )
        self.findings[analysis_version] = artifacts["findings"]
        self.contributions[analysis_version] = artifacts["contributions"]
        self.evidence[analysis_version] = artifacts["evidence_records"]
        self.published_calls += 1
        return self.objective, analysis

    async def publish_experiment_analysis(
        self,
        collection_id,
        objective_id,
        analysis_version,
        *,
        contributions=(),
        abstention_reason=None,
        abstention_note=None,
        transaction=None,
    ):
        self.published_transaction = transaction
        analysis = self.analyses[analysis_version].succeed(
            abstention_reason=abstention_reason,
            abstention_note=abstention_note,
        )
        self.analyses[analysis_version] = analysis
        self.objective = self.objective.publish_analysis(
            collection_id=analysis.collection_id,
            objective_id=analysis.objective_id,
            analysis_version=analysis.analysis_version,
            status=analysis.status,
        )
        self.findings[analysis_version] = (
            self.native_findings
            if self.native_findings is not None
            else (_native_finding(analysis_version),)
        )
        self.contributions[analysis_version] = contributions or _artifacts(
            analysis_version
        ).contributions
        # Native publication does not copy the legacy ObjectiveEvidence ledger.
        self.evidence[analysis_version] = ()
        self.experiment_published_calls += 1
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


class FakeObjectiveInputService:
    def __init__(self) -> None:
        async def read_document_profiles(collection_id, document_ids=None):
            if document_ids is not None and "paper-1" not in document_ids:
                return ()
            return (
                DocumentProfile.from_mapping(
                    {
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


class FakeObjectiveExperimentAnalysisService:
    def __init__(self, *, artifacts=None, error: Exception | None = None) -> None:
        self.artifacts = artifacts
        self.error = error
        self.calls = 0

    async def generate_experiment_analysis_artifacts(
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


class UsageRecordingObjectiveExperimentAnalysisService(FakeObjectiveExperimentAnalysisService):
    async def generate_experiment_analysis_artifacts(
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
        return await super().generate_experiment_analysis_artifacts(
            collection_id,
            analysis,
            progress_callback=progress_callback,
        )


class DiagnosticsRecordingObjectiveExperimentAnalysisService(FakeObjectiveExperimentAnalysisService):
    async def generate_experiment_analysis_artifacts(
        self, collection_id, analysis, progress_callback=None
    ):
        record_analysis_diagnostic(
            {
                "trace_type": "table_matrix_repair",
                "table_id": "table-1",
                "status": "verified",
            }
        )
        return await super().generate_experiment_analysis_artifacts(
            collection_id,
            analysis,
            progress_callback=progress_callback,
        )


class RecordingExperimentAnalysisWriter:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    async def write_experiment_analysis(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            findings=(_native_finding(1),),
            selections=(SimpleNamespace(comparison_keys=("comparison-1",)),),
        )

    async def write(self, **_kwargs):
        pytest.fail("legacy experiment writer method must not be called")


class NativeRecordingExperimentAnalysisWriter:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        findings: tuple[Finding, ...] | None = None,
        selections: tuple[object, ...] | None = None,
    ) -> None:
        self.error = error
        self.calls: list[dict] = []
        self.findings = findings
        self.selections = selections

    async def write_experiment_analysis(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            findings=(
                self.findings
                if self.findings is not None
                else (_native_finding(kwargs["analysis"].analysis_version),)
            ),
            selections=(
                self.selections
                if self.selections is not None
                else (SimpleNamespace(comparison_keys=("comparison-1",)),)
            ),
        )

    async def write(self, **_kwargs):
        pytest.fail("native writer path must not call the legacy write method")


class RecordingAnalysisTransactionFactory:
    def __init__(self) -> None:
        self.handle = object()
        self.events: list[str] = []

    @asynccontextmanager
    async def begin(self):
        self.events.append("begin")
        try:
            yield self.handle
        except BaseException:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")


def _service(
    *,
    repository=None,
    analyzer=None,
    experiment_analysis_writer=None,
    experiment_analysis_transaction_factory=None,
    experiment_compatibility_projection=None,
):
    repository = repository or FakeObjectiveRepository()
    analyzer = analyzer or FakeObjectiveExperimentAnalysisService()
    experiment_analysis_writer = (
        experiment_analysis_writer or NativeRecordingExperimentAnalysisWriter()
    )
    if getattr(experiment_analysis_writer, "findings", None) is not None:
        repository.native_findings = experiment_analysis_writer.findings
    inputs = FakeObjectiveInputService()
    service = ObjectiveAnalysisService(
        objective_repository=repository,
        experiment_analysis_service=analyzer,
        objective_input_service=inputs,
        document_profile_service=inputs.document_profile_service,
        experiment_analysis_writer=experiment_analysis_writer,
        experiment_analysis_transaction_factory=experiment_analysis_transaction_factory,
        experiment_compatibility_projection=experiment_compatibility_projection,
    )
    return service, repository, analyzer


class RecordingExperimentCompatibilityProjection:
    async def list_findings(self, *args, **kwargs):
        return (
            ({"finding_id": "projected-finding", "paper_contributions": []},),
            1,
        )

    async def read_finding(self, *args, **kwargs):
        return {"finding_id": "projected-finding", "paper_contributions": []}

    async def list_evidence(self, *args, **kwargs):
        return (
            (
                {
                    "evidence_id": "projected-evidence",
                    "supports_finding": True,
                    "eligible_for_finding_authoring": True,
                },
            ),
            1,
        )


async def test_analysis_queries_use_experiment_projection_without_changing_arguments() -> None:
    projection = RecordingExperimentCompatibilityProjection()
    service, _repository, _analyzer = _service(
        repository=FakeObjectiveRepository(published=True),
        experiment_compatibility_projection=projection,
    )

    findings = await service.list_findings(
        "collection-1",
        "objective-1",
        analysis_version=1,
        offset=2,
        limit=7,
    )
    evidence = await service.list_evidence(
        "collection-1",
        "objective-1",
        analysis_version=1,
        finding_id="projected-finding",
        offset=3,
        limit=8,
    )

    assert findings["items"][0]["finding_id"] == "projected-finding"
    assert evidence["items"][0]["evidence_id"] == "projected-evidence"


async def test_authored_analysis_keeps_authored_snapshot_when_projection_is_available() -> None:
    repository = FakeObjectiveRepository(published=True)
    authored = replace(
        repository.analyses[1],
        origin="human_authored",
        scientific_record_source="authored_snapshot",
        source_analysis_version=0,
        created_by_user_id="researcher-1",
    )
    repository.analyses[1] = authored

    class RejectingProjection:
        async def list_findings(self, *args, **kwargs):  # noqa: ARG002
            pytest.fail("authored analysis must not read the experiment projection")

        async def list_evidence(self, *args, **kwargs):  # noqa: ARG002
            pytest.fail("authored analysis must not read the experiment projection")

    service, _, _ = _service(
        repository=repository,
        experiment_compatibility_projection=RejectingProjection(),
    )

    findings = await service.list_findings(
        "collection-1", "objective-1", analysis_version=1
    )
    evidence = await service.list_evidence(
        "collection-1", "objective-1", analysis_version=1
    )

    assert findings["items"][0]["finding_id"] == "finding-1"
    assert evidence["items"][0]["evidence_id"] == "evidence-1"


async def test_legacy_automatic_analysis_keeps_snapshot_when_projection_is_available() -> None:
    repository = FakeObjectiveRepository(published=True)
    repository.analyses[1] = replace(
        repository.analyses[1],
        scientific_record_source="legacy_snapshot",
    )

    class RejectingProjection:
        async def list_findings(self, *args, **kwargs):  # noqa: ARG002
            pytest.fail("legacy automatic analysis must not read the experiment projection")

        async def list_evidence(self, *args, **kwargs):  # noqa: ARG002
            pytest.fail("legacy automatic analysis must not read the experiment projection")

    service, _, _ = _service(
        repository=repository,
        experiment_compatibility_projection=RejectingProjection(),
    )

    findings = await service.list_findings(
        "collection-1", "objective-1", analysis_version=1
    )

    assert findings["items"][0]["finding_id"] == "finding-1"


async def test_experiment_abstention_still_reads_experiment_projection() -> None:
    repository = FakeObjectiveRepository(published=True)
    repository.analyses[1] = replace(
        repository.analyses[1],
        scientific_record_source="experiment_graph",
        abstention_reason="no_grounded_evidence",
        abstention_note="No source-grounded selection was recovered.",
    )
    repository.findings[1] = ()
    projection = RecordingExperimentCompatibilityProjection()
    service, _, _ = _service(
        repository=repository,
        experiment_compatibility_projection=projection,
    )

    findings = await service.list_findings(
        "collection-1", "objective-1", analysis_version=1
    )

    assert findings["items"][0]["finding_id"] == "projected-finding"


def test_partial_experiment_archive_is_insufficient_not_no_grounded_evidence() -> None:
    result = SimpleNamespace(
        findings=(),
        selections=(),
        revisions=(
            SimpleNamespace(
                measurements=(SimpleNamespace(measurement_key="m1"),),
                comparisons=(),
                reported_interpretations=(),
            ),
        ),
    )

    reason, note = _experiment_abstention(result)

    assert reason == "insufficient_evidence"
    assert note is not None
    assert "partial bindings" in note


def test_partial_stored_experiment_archive_unwraps_revision_payload() -> None:
    result = SimpleNamespace(
        findings=(),
        selections=(),
        revisions=(
            SimpleNamespace(
                revision=SimpleNamespace(
                    measurements=(SimpleNamespace(measurement_key="m1"),),
                    comparisons=(),
                    reported_interpretations=(),
                ),
            ),
        ),
    )

    reason, note = _experiment_abstention(result)

    assert reason == "insufficient_evidence"
    assert note is not None
    assert "partial bindings" in note


async def test_objective_analysis_publishes_one_complete_version() -> None:
    service, repository, _analyzer = _service()
    queued = await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert queued["analysis"].status == "queued"
    assert result["analysis"].status == "succeeded"
    assert result["analysis"].progress_message == "Objective analysis completed."
    assert result["objective"].objective.published_analysis_version == 1
    assert result["findings"] == (_native_finding(1),)
    assert result["paper_contributions"] == _artifacts(1).contributions
    assert result["warnings"] == []
    assert repository.experiment_published_calls == 1
    assert repository.published_calls == 0


async def test_objective_analysis_writes_experiment_records_without_legacy_publication() -> None:
    writer = RecordingExperimentAnalysisWriter()
    service, repository, _analyzer = _service(
        experiment_analysis_writer=writer,
    )

    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "succeeded"
    assert repository.experiment_published_calls == 1
    assert repository.published_calls == 0
    assert len(writer.calls) == 1
    call = writer.calls[0]
    assert call["collection_id"] == "collection-1"
    assert call["objective"].objective_id == repository.objective.objective_id
    assert call["objective"].collection_id == repository.objective.collection_id
    assert call["analysis"].analysis_version == 1
    assert call["experiment_outputs"] == _artifacts(1).experiment_outputs
    assert call["partial_experiment_outputs"] == _artifacts(1).partial_experiment_outputs
    assert "findings" not in call


async def test_experiment_write_failure_prevents_successful_analysis_publication() -> None:
    writer = RecordingExperimentAnalysisWriter(error=RuntimeError("experiment write failed"))
    service, repository, _analyzer = _service(
        experiment_analysis_writer=writer,
    )

    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "failed"
    assert repository.published_calls == 0
    assert len(writer.calls) == 1


async def test_native_experiment_writer_publishes_without_legacy_publication() -> None:
    writer = NativeRecordingExperimentAnalysisWriter()
    service, repository, _analyzer = _service(
        experiment_analysis_writer=writer,
    )

    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "succeeded"
    assert repository.experiment_published_calls == 1
    assert repository.published_calls == 0
    assert len(writer.calls) == 1
    assert writer.calls[0]["analysis"].analysis_version == 1


async def test_experiment_publication_commits_one_shared_transaction() -> None:
    transaction_factory = RecordingAnalysisTransactionFactory()
    writer = NativeRecordingExperimentAnalysisWriter()
    service, repository, _analyzer = _service(
        experiment_analysis_writer=writer,
        experiment_analysis_transaction_factory=transaction_factory,
    )

    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "succeeded"
    assert transaction_factory.events == ["begin", "commit"]
    assert writer.calls[0]["transaction"] is transaction_factory.handle
    assert repository.published_transaction is transaction_factory.handle


async def test_experiment_publication_rolls_back_when_writer_fails() -> None:
    transaction_factory = RecordingAnalysisTransactionFactory()
    writer = NativeRecordingExperimentAnalysisWriter(
        error=RuntimeError("experiment write failed")
    )
    service, repository, _analyzer = _service(
        experiment_analysis_writer=writer,
        experiment_analysis_transaction_factory=transaction_factory,
    )

    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "failed"
    assert transaction_factory.events == ["begin", "rollback"]
    assert writer.calls[0]["transaction"] is transaction_factory.handle
    assert repository.experiment_published_calls == 0
    assert repository.published_transaction is None


async def test_native_experiment_writer_failure_prevents_successful_publication() -> None:
    writer = NativeRecordingExperimentAnalysisWriter(
        error=RuntimeError("native experiment write failed")
    )
    service, repository, _analyzer = _service(
        experiment_analysis_writer=writer,
    )

    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "failed"
    assert repository.experiment_published_calls == 0
    assert repository.published_calls == 0
    assert len(writer.calls) == 1


async def test_analysis_view_reads_one_typed_objective_snapshot() -> None:
    class CountingRepository(FakeObjectiveRepository):
        metadata_reads = 0
        analysis_reads = 0

        async def read_objective(self, collection_id, objective_id):
            pytest.fail("the view must not reread the same Objective without metadata")

        async def read_objective_record(self, collection_id, objective_id):
            self.metadata_reads += 1
            return StoredObjective(self.objective)

        async def read_analysis(self, collection_id, objective_id, analysis_version=None):
            assert analysis_version is not None
            self.analysis_reads += 1
            return await super().read_analysis(collection_id, objective_id, analysis_version)

        async def read_published_analysis(self, collection_id, objective_id):
            pytest.fail("the view already knows the published version")

    repository = CountingRepository(published=True)
    service, _, _ = _service(repository=repository)

    result = await service.get_analysis_state("collection-1", "objective-1")

    assert result["objective"].objective == repository.objective
    assert repository.metadata_reads == 1
    assert repository.analysis_reads == 1


async def test_queue_analysis_confirms_a_candidate_and_queues_version_one() -> None:
    repository = FakeObjectiveRepository(confirmation_status="candidate")
    service, _, _ = _service(repository=repository)

    result = await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    assert result["objective"].objective.confirmation_status == "confirmed"
    assert result["objective"].objective.active_analysis_version == 1
    assert result["analysis"].analysis_version == 1
    assert result["analysis"].status == "queued"


async def test_start_analysis_queues_and_dispatches_the_canonical_worker() -> None:
    service, repository, analyzer = _service()

    queued = await service.start_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    assert queued["analysis"].status == "queued"
    assert queued["objective"].objective.active_analysis_version == 1
    await asyncio.gather(*tuple(service._analysis_tasks))
    completed = await service.get_analysis_state("collection-1", "objective-1")
    assert completed["analysis"].status == "succeeded"
    assert analyzer.calls == 1
    assert repository.experiment_published_calls == 1
    assert repository.published_calls == 0


async def test_start_analysis_marks_a_version_failed_when_dispatch_cannot_start() -> None:
    repository = FakeObjectiveRepository()
    analyzer = FakeObjectiveExperimentAnalysisService()

    def unavailable_task_factory(_coroutine):
        raise RuntimeError("event loop unavailable")

    inputs = FakeObjectiveInputService()
    service = ObjectiveAnalysisService(
        objective_repository=repository,
        experiment_analysis_service=analyzer,
        objective_input_service=inputs,
        document_profile_service=inputs.document_profile_service,
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
    inputs = FakeObjectiveInputService()
    service = ObjectiveAnalysisService(
        objective_repository=FakeObjectiveRepository(),
        experiment_analysis_service=FakeObjectiveExperimentAnalysisService(),
        objective_input_service=inputs,
        document_profile_service=inputs.document_profile_service,
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
        analyzer=UsageRecordingObjectiveExperimentAnalysisService()
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
        analyzer=FakeObjectiveExperimentAnalysisService(artifacts=artifacts)
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
        analyzer=DiagnosticsRecordingObjectiveExperimentAnalysisService()
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
        analyzer=DiagnosticsRecordingObjectiveExperimentAnalysisService(
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
    assert analysis.diagnostics[0] == {
        "trace_type": "table_matrix_repair",
        "table_id": "table-1",
        "status": "verified",
    }
    assert analysis.diagnostics[1]["trace_type"] == "objective_analysis_failure"
    assert analysis.diagnostics[1]["error_type"] == "RuntimeError"
    assert len(analysis.diagnostics) == 2


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
    assert progressed.processed_document_count == 0
    assert progressed.total_document_count == 6


async def test_concurrent_progress_counts_only_unique_completed_papers() -> None:
    service, repository, _analyzer = _service(
        repository=FakeObjectiveRepository(candidate_document_count=4)
    )
    await service.queue_analysis(
        "collection-1", "objective-1", tuple(f"paper-{i}" for i in range(1, 5))
    )
    running = await repository.claim_analysis("collection-1", "objective-1", 1)
    progress = service._build_progress_callback(running)

    await asyncio.gather(
        *(
            asyncio.to_thread(
                progress,
                {
                    "phase": "objective_paper_framing_started",
                    "current": position,
                    "total": 4,
                    "unit": "documents",
                    "active_document_id": f"paper-{position}",
                },
            )
            for position in range(1, 5)
        )
    )
    started = await repository.read_analysis("collection-1", "objective-1", 1)
    assert started.processed_document_count == 0

    counts = []
    for document_id in ("paper-4", "paper-1", "paper-4", "paper-2", "paper-3"):
        await asyncio.to_thread(
            progress,
            {
                "phase": "objective_document_evidence_completed",
                "unit": "documents",
                "active_document_id": document_id,
            },
        )
        updated = await repository.read_analysis("collection-1", "objective-1", 1)
        counts.append(updated.processed_document_count)
        assert updated.total_document_count == 4

    assert counts == [1, 2, 2, 3, 4]


async def test_empty_finding_output_publishes_scientific_abstention() -> None:
    artifacts = _artifacts(1)
    service, repository, _analyzer = _service(
        analyzer=FakeObjectiveExperimentAnalysisService(artifacts=artifacts),
        experiment_analysis_writer=NativeRecordingExperimentAnalysisWriter(
            findings=(),
            selections=(SimpleNamespace(comparison_keys=("comparison-1",)),),
        ),
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "succeeded"
    assert result["objective"].objective.published_analysis_version == 1
    assert result["findings"] == ()
    assert result["paper_contributions"] == artifacts.contributions
    assert repository.experiment_published_calls == 1
    assert repository.published_calls == 0


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
    artifacts = ObjectiveExperimentAnalysisArtifacts(
        contributions=(contribution,),
        experiment_outputs=(),
    )
    service, repository, _analyzer = _service(
        analyzer=FakeObjectiveExperimentAnalysisService(artifacts=artifacts),
        experiment_analysis_writer=NativeRecordingExperimentAnalysisWriter(
            findings=(),
            selections=(),
        ),
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "succeeded"
    assert result["objective"].objective.published_analysis_version == 1
    assert result["findings"] == ()
    assert result["analysis"].abstention_reason == "no_grounded_evidence"
    assert result["paper_contributions"]
    assert result["warnings"] == []
    assert repository.evidence[1] == ()
    assert repository.experiment_published_calls == 1
    assert repository.published_calls == 0


async def test_missing_paper_contributions_still_fails_without_publication() -> None:
    artifacts = replace(_artifacts(1), contributions=())
    service, repository, _analyzer = _service(
        analyzer=FakeObjectiveExperimentAnalysisService(artifacts=artifacts)
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "failed"
    assert (
        result["analysis"].error_message
        == "Objective analysis could not be completed. Retry the analysis."
    )
    assert result["objective"].objective.published_analysis_version is None
    assert repository.published_calls == 0


async def test_all_relevant_paper_extractions_failed_without_publication() -> None:
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
    artifacts = ObjectiveExperimentAnalysisArtifacts(
        contributions=(failed_contribution,),
        experiment_outputs=(),
    )
    service, repository, _analyzer = _service(
        analyzer=FakeObjectiveExperimentAnalysisService(artifacts=artifacts)
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    result = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )

    assert result["analysis"].status == "failed"
    assert (
        result["analysis"].error_message
        == "Objective analysis could not be completed. Retry the analysis."
    )
    assert result["objective"].objective.published_analysis_version is None
    assert repository.published_calls == 0


async def test_rejected_automatic_drafts_fail_analysis_instead_of_publishing_absence() -> None:
    from application.core.objectives.analysis.paper_experiment_extraction import (
        PaperExperimentExtractor,
        build_source_bundle,
    )
    from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
    from application.core.objectives.objective_analysis_service import (
        _build_contribution_for_extraction,
    )

    class InvalidDraftClient:
        def complete(self, *, response_model, **kwargs):
            return response_model.model_validate({
                "experiments": [{
                    "label": "Reported tensile experiment",
                    "scope_description": "Same batch under two treatments",
                    "test_conditions": [{
                        "test_key": None,
                        "test_type": "tensile",
                        "source_labels": ["S001"],
                    }],
                }],
                "source_labels": ["S001"],
            })

    service, repository, analyzer = _service()
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    analysis = await repository.read_analysis("collection-1", "objective-1", 1)
    objective = repository.objective
    bundle = build_source_bundle(
        document_id="paper-1", source_fingerprint="prepared-1",
        source_payloads=({"source_kind": "block", "source_ref": "methods-1",
                          "text": "Both treatment groups underwent tensile testing."},),
    )
    extraction = PaperExperimentExtractor(InvalidDraftClient()).extract(
        objective=objective, bundle=bundle,
    )
    assert extraction.status == "technical_failure"
    assert len(extraction.attempts) == 3
    refs = tuple(bundle.source_catalog.values())
    contribution = _build_contribution_for_extraction(
        collection_id="collection-1", analysis=analysis, objective=objective,
        frame=PaperAnalysisFrame.from_mapping({"document_id": "paper-1", "relevance": "high"}),
        extraction=extraction, routed_source_refs=refs,
        inspected_source_refs=(), failed_source_refs=refs, omitted_source_refs=(),
    )
    assert contribution.analysis_status == "failed"
    assert contribution.evidence_disposition == "extraction_failed"
    assert contribution.failed_source_count == 1
    analyzer.artifacts = ObjectiveExperimentAnalysisArtifacts(
        contributions=(contribution,), experiment_outputs=(),
    )

    result = await service.execute_queued_analysis("collection-1", "objective-1", 1)

    assert result["analysis"].status == "failed"
    assert result["analysis"].abstention_reason is None
    assert result["objective"].objective.published_analysis_version is None
    assert repository.experiment_published_calls == 0


async def test_analysis_exception_is_diagnostic_and_retry_allocates_new_version() -> None:
    analyzer = FakeObjectiveExperimentAnalysisService(error=RuntimeError("model unavailable"))
    service, repository, _analyzer = _service(analyzer=analyzer)
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    failed = await service.execute_queued_analysis(
        "collection-1", "objective-1", 1
    )
    retry = await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)

    assert failed["analysis"].status == "failed"
    assert failed["analysis"].error_message == (
        "Objective analysis could not be completed. Retry the analysis."
    )
    assert retry["analysis"].analysis_version == 2
    assert repository.objective.active_analysis_version == 2


@pytest.mark.parametrize(
    ("exception_type", "code", "message"),
    [
        (
            TimeoutError,
            "provider_timeout",
            "The analysis request timed out. Retry the analysis.",
        ),
        (
            ValueError,
            "invalid_analysis_artifact",
            "The analysis returned an invalid result. Retry the analysis.",
        ),
        (
            RuntimeError,
            "objective_analysis_failed",
            "Objective analysis could not be completed. Retry the analysis.",
        ),
    ],
)
async def test_failure_keeps_safe_diagnostics_without_exposing_provider_text(
    exception_type: type[Exception],
    code: str,
    message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_marker = "private-provider-response-marker"
    service, repository, _ = _service(
        analyzer=FakeObjectiveExperimentAnalysisService(error=exception_type(secret_marker))
    )
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    result = await service.execute_queued_analysis("collection-1", "objective-1", 1)
    status = await service.get_analysis_status("collection-1", "objective-1")

    assert result["analysis"].error_message == message
    assert status["error_code"] == code
    assert status["error_message"] == message
    stored = repository.analyses[1]
    failure = stored.diagnostics[-1]
    assert failure["error_type"] == exception_type.__name__
    assert failure["frames"][-1]["function"] == "generate_experiment_analysis_artifacts"
    assert secret_marker not in str(stored.to_record())
    assert secret_marker not in str(stored.diagnostics)
    assert secret_marker not in caplog.text


@pytest.mark.parametrize("error_code", ["provider_timeout", "legacy_unknown", None])
async def test_historical_failure_is_safe_without_rewriting_published_or_stored_state(
    error_code: str | None,
) -> None:
    repository = FakeObjectiveRepository(published=True)
    service, _, _ = _service(repository=repository)
    await service.queue_analysis("collection-1", "objective-1", _DOCUMENT_IDS)
    stored_failure = replace(
        repository.analyses[2].fail(
            error_code="legacy", error_message="private-history-marker"
        ),
        error_code=error_code,
    )
    repository.analyses[2] = stored_failure

    result = await service.get_analysis_state("collection-1", "objective-1")
    status = await service.get_analysis_status("collection-1", "objective-1")

    assert result["analysis"].status == "failed"
    assert result["analysis"].error_code == error_code
    assert "private-history-marker" not in result["analysis"].error_message
    assert status["error_message"] == result["analysis"].error_message
    assert result["published_analysis"].analysis_version == 1
    assert result["findings"] == (_finding(1),)
    assert repository.analyses[2] is stored_failure


async def test_losing_worker_does_not_run_duplicate_analysis() -> None:
    repository = FakeObjectiveRepository(claimable=False)
    analyzer = FakeObjectiveExperimentAnalysisService()
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
    analyzer = FakeObjectiveExperimentAnalysisService(error=TimeoutError("provider timeout"))
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
    assert result["analysis"].error_message == (
        "Objective analysis could not be completed. Retry the analysis."
    )
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
