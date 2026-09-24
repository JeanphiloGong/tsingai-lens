"""Application contract for feedback analysis results and cases."""

from __future__ import annotations

from typing import Any, Protocol

from domain.feedback.analysis_result import AnalysisResult
from domain.feedback.annotation import FeedbackAnnotation
from domain.feedback.feedback_case import FeedbackCase
from domain.feedback.review_decision import ReviewDecision


class FeedbackCaseRepository(Protocol):
    async def save_analysis_result(self, result: AnalysisResult) -> AnalysisResult: ...

    async def upsert_case_from_analysis(
        self,
        result: AnalysisResult,
        *,
        context_snapshot: dict[str, Any],
        source_signal_ids: tuple[str, ...] = (),
        now: str,
    ) -> FeedbackCase: ...

    async def read_case(self, case_id: str) -> FeedbackCase | None: ...

    async def read_analysis_results(
        self, result_ids: tuple[str, ...]
    ) -> tuple[AnalysisResult, ...]: ...

    async def list_cases(
        self,
        *,
        collection_id: str | None = None,
        collection_ids: tuple[str, ...] | None = None,
        status: str | None = None,
        problem_type: str | None = None,
        limit: int | None = 50,
        offset: int = 0,
    ) -> tuple[FeedbackCase, ...]: ...

    async def read_annotation(self, case_id: str) -> FeedbackAnnotation | None: ...

    async def save_annotation(
        self,
        annotation: FeedbackAnnotation,
        *,
        expected_digest: str | None,
        now: str,
    ) -> FeedbackAnnotation: ...

    async def read_review_decisions(self, case_id: str) -> tuple[ReviewDecision, ...]: ...

    async def append_review_decision(
        self,
        decision: ReviewDecision,
        *,
        expected_annotation_digest: str,
        now: str,
    ) -> ReviewDecision: ...


__all__ = ["FeedbackCaseRepository"]
