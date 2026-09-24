"""Application contract for feedback analysis results and cases."""

from __future__ import annotations

from typing import Any, Protocol

from domain.feedback.analysis_result import AnalysisResult
from domain.feedback.feedback_case import FeedbackCase


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

    async def list_cases(
        self,
        *,
        collection_id: str | None = None,
        status: str | None = None,
        problem_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[FeedbackCase, ...]: ...


__all__ = ["FeedbackCaseRepository"]
