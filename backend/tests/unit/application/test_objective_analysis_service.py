from __future__ import annotations

from dataclasses import replace

from application.core.objective_analysis_service import ObjectiveAnalysisService
from domain.core import ResearchObjective, ResearchUnderstanding


def _objective(status: str = "confirmed") -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "objective_id": "objective-1",
            "question": "How does temperature affect strength?",
            "source_build_id": "build-1",
            "status": status,
        }
    )


class FakeObjectiveRepository:
    def __init__(self, status: str = "confirmed") -> None:
        self.objective = _objective(status)
        self.claim_count = 0

    def read_objective_workspace(self, collection_id, objective_id):
        return self.objective

    def confirm_objective(self, collection_id, objective_id):
        self.objective = replace(self.objective, status="confirmed")
        return self.objective

    def queue_objective_analysis(self, collection_id, objective_id):
        if self.objective.status not in {"queued", "running"}:
            self.objective = replace(
                self.objective,
                status="queued",
                analysis_error=None,
            )
        return self.objective

    def claim_objective_analysis(self, collection_id, objective_id):
        if self.objective.status != "queued":
            return None
        self.claim_count += 1
        self.objective = replace(self.objective, status="running")
        return self.objective

    def update_objective_analysis_progress(
        self, collection_id, objective_id, analysis_progress
    ):
        self.objective = replace(
            self.objective,
            analysis_progress=dict(analysis_progress),
        )
        return self.objective

    def mark_objective_analysis_ready(self, collection_id, objective_id):
        self.objective = replace(
            self.objective,
            status="ready",
            analysis_error=None,
        )
        return self.objective

    def mark_objective_analysis_failed(
        self, collection_id, objective_id, analysis_error
    ):
        self.objective = replace(
            self.objective,
            status="failed",
            analysis_error=analysis_error,
        )
        return self.objective


class FakeUnderstandingRepository:
    def __init__(self) -> None:
        self.understanding = None

    def upsert_objective_understanding(
        self,
        collection_id,
        objective_id,
        understanding,
    ):
        self.understanding = understanding

    def read_objective_understanding(self, collection_id, objective_id):
        return self.understanding


class FakeResearchObjectiveService:
    def __init__(self, *, finding_kind: str = "primary", error: Exception | None = None):
        self.finding_kind = finding_kind
        self.error = error
        self.calls = 0

    def analyze_objective(self, collection_id, objective_id, progress_callback=None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        if progress_callback is not None:
            progress_callback({"phase": "routing", "current": 1, "total": 1})
        presentation = {"primary_findings": [], "review_queue_findings": []}
        if self.finding_kind == "primary":
            presentation["primary_findings"] = [{"finding_id": "finding-1"}]
        elif self.finding_kind == "review":
            presentation["review_queue_findings"] = [{"finding_id": "finding-1"}]
        return ResearchUnderstanding.from_mapping(
            {
                "state": "ready",
                "scope": {
                    "scope_type": "objective",
                    "collection_id": collection_id,
                    "objective_id": objective_id,
                },
                "presentation": presentation,
            }
        )


class FakeResearchUnderstandingService:
    def with_presentation(self, understanding, *, recover_source_findings=True):
        assert recover_source_findings is False
        return understanding.to_record()


def _service(*, finding_kind="primary", error=None, status="confirmed"):
    objectives = FakeObjectiveRepository(status)
    understandings = FakeUnderstandingRepository()
    analyzer = FakeResearchObjectiveService(finding_kind=finding_kind, error=error)
    service = ObjectiveAnalysisService(
        objective_repository=objectives,
        research_understanding_repository=understandings,
        research_objective_service=analyzer,
        research_understanding_service=FakeResearchUnderstandingService(),
    )
    return service, objectives, understandings, analyzer


def test_objective_analysis_persists_findings_before_marking_ready() -> None:
    service, objectives, understandings, analyzer = _service()

    assert service.queue_analysis("collection-1", "objective-1")["objective"].status == "queued"
    result = service.run_analysis("collection-1", "objective-1")

    assert result["objective"].status == "ready"
    assert result["understanding"].scope.scope_type == "objective"
    assert understandings.understanding is not None
    assert objectives.objective.analysis_progress == {
        "phase": "routing",
        "current": 1,
        "total": 1,
    }
    assert analyzer.calls == 1


def test_objective_analysis_accepts_review_candidate_as_ready_with_warning() -> None:
    service, objectives, _, _ = _service(finding_kind="review")
    service.queue_analysis("collection-1", "objective-1")

    result = service.run_analysis("collection-1", "objective-1")

    assert objectives.objective.status == "ready"
    assert result["warnings"] == [
        "objective analysis produced review candidates but no primary research findings"
    ]


def test_objective_analysis_without_findings_fails_and_does_not_persist() -> None:
    service, objectives, understandings, _ = _service(finding_kind="none")
    service.queue_analysis("collection-1", "objective-1")

    result = service.run_analysis("collection-1", "objective-1")

    assert objectives.objective.status == "failed"
    assert objectives.objective.analysis_error == "objective analysis produced no research findings"
    assert understandings.understanding is None
    assert result["understanding"] is None


def test_objective_analysis_exception_is_diagnostic_and_retryable() -> None:
    service, objectives, _, analyzer = _service(error=RuntimeError("model unavailable"))
    service.queue_analysis("collection-1", "objective-1")
    first = service.run_analysis("collection-1", "objective-1")
    assert first["objective"].status == "failed"
    assert first["objective"].analysis_error == "model unavailable"

    analyzer.error = None
    retried = service.queue_analysis("collection-1", "objective-1")
    assert retried["objective"].status == "queued"
    assert service.run_analysis("collection-1", "objective-1")["objective"].status == "ready"


def test_losing_worker_does_not_run_duplicate_analysis() -> None:
    service, objectives, _, analyzer = _service(status="running")

    result = service.run_analysis("collection-1", "objective-1")

    assert result["objective"].status == "running"
    assert objectives.claim_count == 0
    assert analyzer.calls == 0
