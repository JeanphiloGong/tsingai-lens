"""User-scoped read projections for the feedback workbench."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from application.repositories.chat_repository import ChatRepository
from application.repositories.feedback_case_repository import FeedbackCaseRepository
from application.source.collection_service import CollectionService
from domain.chat import ChatMessageRole
from domain.feedback import AnalysisResult, FeedbackCase


@dataclass(frozen=True)
class FeedbackCaseSummary:
    case_id: str
    collection_id: str
    status: str
    anchor_message_id: str
    problem_type: str | None
    confidence: float | None
    needs_human_review: bool
    created_at: str
    question_preview: str = ""
    answer_preview: str = ""
    document_titles: tuple[str, ...] = ()
    coverage_status: str = "unknown"


class FeedbackCaseService:
    """Translate stored cases into projections a researcher can understand."""

    def __init__(
        self,
        *,
        case_repository: FeedbackCaseRepository,
        chat_repository: ChatRepository,
        collection_service: CollectionService,
    ) -> None:
        self.case_repository = case_repository
        self.chat_repository = chat_repository
        self.collection_service = collection_service

    async def list_for_user(
        self,
        *,
        user_id: str,
        collection_id: str | None = None,
        status: str | None = None,
        problem_type: str | None = None,
        needs_human_review: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[FeedbackCaseSummary, ...]:
        if limit < 1 or limit > 200 or offset < 0:
            raise ValueError("invalid pagination")
        collection_ids = await self._authorized_collection_ids(user_id, collection_id)
        rows: list[FeedbackCaseSummary] = []
        cases = await self.case_repository.list_cases(
            collection_ids=collection_ids,
            status=status,
            problem_type=problem_type,
            limit=None,
            offset=0,
        )
        for case in cases:
            summary = await self._summarize(
                case,
                user_id=user_id,
                needs_human_review=needs_human_review,
            )
            if summary is not None:
                rows.append(summary)
        rows.sort(key=lambda item: (item.created_at, item.case_id))
        return tuple(rows[offset : offset + limit])

    async def read_for_user(self, case_id: str, user_id: str) -> dict[str, Any]:
        case = await self.case_repository.read_case(case_id)
        if case is None:
            raise FileNotFoundError(f"feedback case not found: {case_id}")
        await self.collection_service.get_collection_for_user(case.collection_id, user_id)
        session = await self.chat_repository.read_session(case.session_id)
        if (
            session is None
            or session.user_id != user_id
            or session.collection_id != case.collection_id
        ):
            raise FileNotFoundError(f"feedback case not found: {case_id}")
        messages = await self.chat_repository.read_messages(case.session_id)
        if any(message.session_id != case.session_id for message in messages):
            raise FileNotFoundError(f"feedback case not found: {case_id}")
        results = await self.case_repository.read_analysis_results(case.analysis_result_ids)
        feedback_items: list[Any] = []
        for signal_id in case.source_signal_ids:
            item = await self.chat_repository.read_feedback_by_id(signal_id)
            if (
                item is not None
                and item.session_id == case.session_id
                and item.user_id == user_id
            ):
                feedback_items.append(item)
        feedback = tuple(feedback_items)
        return _detail(case, messages, results, feedback)

    async def _authorized_collection_ids(
        self, user_id: str, collection_id: str | None
    ) -> tuple[str, ...]:
        if collection_id is not None:
            await self.collection_service.get_collection_for_user(collection_id, user_id)
            return (collection_id,)
        collections = await self.collection_service.list_collections(user_id)
        return tuple(item.collection_id for item in collections)

    async def _summarize(
        self,
        case: FeedbackCase,
        *,
        user_id: str,
        needs_human_review: bool | None,
    ) -> FeedbackCaseSummary | None:
        session = await self.chat_repository.read_session(case.session_id)
        if (
            session is None
            or session.user_id != user_id
            or session.collection_id != case.collection_id
        ):
            return None
        messages = await self.chat_repository.read_messages(case.session_id)
        if any(message.session_id != case.session_id for message in messages):
            return None
        result = await self._latest_result(case)
        needs_review = case.status in {
            "detected",
            "collecting_context",
            "needs_annotation",
            "insufficient",
            "ready_for_review",
        }
        if needs_human_review is not None and needs_review != needs_human_review:
            return None
        answer = next(
            (message for message in messages if message.message_id == case.anchor_message_id),
            None,
        )
        question = _previous_user_question(messages, answer)
        coverage = result.evidence_coverage if result else None
        document_titles = _document_titles(coverage.to_record() if coverage else {})
        return FeedbackCaseSummary(
            case_id=case.case_id,
            collection_id=case.collection_id,
            status=case.status,
            anchor_message_id=case.anchor_message_id,
            problem_type=result.problem_type if result else None,
            confidence=result.confidence if result else None,
            needs_human_review=needs_review,
            created_at=case.created_at,
            question_preview=_preview(question),
            answer_preview=_preview(answer.content if answer is not None else str(case.context_snapshot.get("answer") or "")),
            document_titles=document_titles,
            coverage_status=coverage.coverage_status if coverage else "unknown",
        )

    async def _latest_result(self, case: FeedbackCase) -> AnalysisResult | None:
        results = await self.case_repository.read_analysis_results(case.analysis_result_ids)
        return max(results, key=lambda item: (item.created_at, item.result_id), default=None)


def _detail(
    case: FeedbackCase,
    messages: tuple[Any, ...],
    results: tuple[AnalysisResult, ...],
    feedback: tuple[Any, ...],
) -> dict[str, Any]:
    latest = max(results, key=lambda item: (item.created_at, item.result_id), default=None)
    answer = next(
        (message for message in messages if message.message_id == case.anchor_message_id),
        None,
    )
    question = ""
    if answer is not None:
        prior_users = [
            message.content
            for message in messages
            if message.role is ChatMessageRole.USER and message.created_at <= answer.created_at
        ]
        question = prior_users[-1] if prior_users else ""
    coverage = latest.evidence_coverage.to_record() if latest else {}
    return {
        "case_id": case.case_id,
        "collection_id": case.collection_id,
        "session_id": case.session_id,
        "status": case.status,
        "source_signals": [
            {
                "feedback_id": item.feedback_id,
                "rating": item.rating,
                "reason": item.reason,
                "comment": item.comment,
                "created_at": item.created_at,
            }
            for item in feedback
        ],
        "question": question,
        "answer": answer.content if answer is not None else str(case.context_snapshot.get("answer") or ""),
        "requested_scope": _readable_scope(
            coverage.get("requested_scope", case.context_snapshot.get("requested_scope", []))
        ),
        "inspected_sources": coverage.get("inspected_sources", case.context_snapshot.get("inspected_sources", [])),
        "omitted_candidates": coverage.get("omitted_candidates", case.context_snapshot.get("omitted_candidates", [])),
        "claim_support": coverage.get("claim_support", case.context_snapshot.get("claim_support", [])),
        "gaps": coverage.get("gaps", case.context_snapshot.get("gaps", [])),
        "coverage_status": coverage.get("coverage_status", "unknown"),
        "analysis": (
            {
                "problem_type": latest.problem_type,
                "confidence": latest.confidence,
                "suggested_target": latest.suggested_target,
                "model": latest.model,
                "result_id": latest.result_id,
                "coverage_status": latest.evidence_coverage.coverage_status,
            }
            if latest
            else None
        ),
        "annotation": None,
        "current_annotation_digest": case.annotation_digest,
        "technical_error": case.context_snapshot.get("technical_error"),
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


def _previous_user_question(messages: tuple[Any, ...], answer: Any | None) -> str:
    if answer is None:
        return ""
    prior = [
        message.content
        for message in messages
        if message.role is ChatMessageRole.USER and message.created_at <= answer.created_at
    ]
    return prior[-1] if prior else ""


def _preview(value: str, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _document_titles(coverage: dict[str, Any]) -> tuple[str, ...]:
    titles: list[str] = []
    for field in ("requested_scope", "inspected_sources", "omitted_candidates", "claim_support"):
        for item in coverage.get(field) or ():
            if not isinstance(item, dict):
                continue
            title = str(item.get("document_title") or item.get("title") or "").strip()
            if title and title not in titles:
                titles.append(title)
    return tuple(titles)


def _readable_scope(scope: Any) -> list[dict[str, Any]]:
    readable: list[dict[str, Any]] = []
    for item in scope or ():
        if not isinstance(item, dict):
            continue
        record = dict(item)
        if not record.get("title") and record.get("document_title"):
            record["title"] = record["document_title"]
        readable.append(record)
    return readable


__all__ = ["FeedbackCaseService", "FeedbackCaseSummary"]
