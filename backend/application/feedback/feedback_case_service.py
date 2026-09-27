"""User-scoped read projections for the feedback workbench."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from application.repositories.chat_repository import ChatRepository
from application.repositories.feedback_case_repository import FeedbackCaseRepository
from application.source.collection_service import CollectionService
from domain.chat import ChatMessageRole
from domain.feedback import AnalysisResult, FeedbackAnnotation, FeedbackCase, ReviewDecision


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
        signal_reader = getattr(
            self.case_repository, "read_correction_signal_analysis_results", None
        )
        signal_results = (
            await signal_reader(case.signal_analysis_result_ids)
            if signal_reader is not None
            else ()
        )
        tool_failure_reader = getattr(
            self.case_repository, "read_tool_failure_analysis_results", None
        )
        tool_failure_results = (
            await tool_failure_reader(case.tool_failure_analysis_result_ids)
            if tool_failure_reader is not None
            else ()
        )
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
        correction_items = _correction_signal_records(
            signal_results,
            messages=messages,
            session_id=case.session_id,
        )
        annotation_reader = getattr(self.case_repository, "read_annotation", None)
        annotation = (
            await annotation_reader(case.case_id)
            if annotation_reader is not None
            else None
        )
        review_reader = getattr(self.case_repository, "read_review_decisions", None)
        decisions = await review_reader(case.case_id) if review_reader is not None else ()
        return _detail(
            case,
            messages,
            results,
            feedback,
            annotation,
            decisions,
            signal_results=signal_results,
            correction_items=correction_items,
            tool_failure_results=tool_failure_results,
        )

    async def export_for_user(
        self,
        *,
        user_id: str,
        collection_id: str,
        status: str | None = None,
        limit: int = 2000,
    ) -> tuple[dict[str, Any], ...]:
        """Project candidate analysis records for inspection outside the UI.

        This export intentionally includes cases at every lifecycle state. It
        is an audit/analysis export, not a training release: only the separate
        dataset snapshot flow can turn an accepted case into model data.
        """
        if limit < 1 or limit > 2000:
            raise ValueError("invalid export limit")
        summaries_list: list[FeedbackCaseSummary] = []
        offset = 0
        while len(summaries_list) < limit:
            page_size = min(200, limit - len(summaries_list))
            page = await self.list_for_user(
                user_id=user_id,
                collection_id=collection_id,
                status=status,
                limit=page_size,
                offset=offset,
            )
            summaries_list.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)
        summaries = tuple(summaries_list)
        records: list[dict[str, Any]] = []
        exported_at = datetime.now(timezone.utc).isoformat()
        for summary in summaries:
            detail = await self.read_for_user(summary.case_id, user_id)
            records.append(
                {
                    "schema_version": "feedback-case-analysis.v1",
                    "export_kind": "candidate_analysis",
                    "training_ready": detail["status"] == "accepted",
                    "exported_at": exported_at,
                    **detail,
                }
            )
        return tuple(records)

    async def save_annotation_for_user(
        self,
        *,
        case_id: str,
        user_id: str,
        expected_digest: str | None,
        problem_type: str,
        severity: str,
        target: str | None,
        support_source_refs: tuple[str, ...],
        dataset_uses: tuple[str, ...],
        reason: str,
        now: str | None = None,
    ) -> FeedbackAnnotation:
        """Persist a human judgment after re-reading the case's evidence boundary."""
        case, results = await self._authorized_case(case_id, user_id)
        # A rejected or insufficient review is a request for better material,
        # not a terminal deletion.  A new annotation version may reopen those
        # cases, while accepted/withdrawn cases remain immutable until an
        # explicit future workflow defines how to revoke them.
        if case.status not in {
            "needs_annotation",
            "ready_for_review",
            "rejected",
            "insufficient",
        }:
            raise ValueError("feedback_case_not_annotatable")
        allowed_source_refs = _case_source_refs(case, results)
        requested_refs = tuple(dict.fromkeys(str(item).strip() for item in support_source_refs if str(item).strip()))
        if any(ref not in allowed_source_refs for ref in requested_refs):
            raise ValueError("annotation_source_not_in_case")
        current = await self._read_annotation(case.case_id)
        timestamp = now or datetime.now(timezone.utc).isoformat()
        version = current.version + 1 if current is not None else 1
        annotation = FeedbackAnnotation.build(
            annotation_id=f"annotation_{uuid4().hex[:32]}",
            case_id=case.case_id,
            version=version,
            problem_type=problem_type,  # type: ignore[arg-type]
            severity=severity,  # type: ignore[arg-type]
            target=target,
            support_source_refs=requested_refs,
            dataset_uses=tuple(dataset_uses),  # type: ignore[arg-type]
            reason=reason,
            created_by=user_id,
            created_at=timestamp,
        )
        saver = getattr(self.case_repository, "save_annotation", None)
        if saver is None:
            raise RuntimeError("feedback annotation persistence is not configured")
        return await saver(annotation, expected_digest=expected_digest, now=timestamp)

    async def _authorized_case(
        self, case_id: str, user_id: str
    ) -> tuple[FeedbackCase, tuple[AnalysisResult, ...]]:
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
        results = await self.case_repository.read_analysis_results(case.analysis_result_ids)
        signal_reader = getattr(
            self.case_repository, "read_correction_signal_analysis_results", None
        )
        signal_results = (
            await signal_reader(case.signal_analysis_result_ids)
            if signal_reader is not None
            else ()
        )
        tool_failure_reader = getattr(
            self.case_repository, "read_tool_failure_analysis_results", None
        )
        tool_failure_results = (
            await tool_failure_reader(case.tool_failure_analysis_result_ids)
            if tool_failure_reader is not None
            else ()
        )
        return case, (*results, *signal_results, *tool_failure_results)

    async def _read_annotation(self, case_id: str) -> FeedbackAnnotation | None:
        reader = getattr(self.case_repository, "read_annotation", None)
        return await reader(case_id) if reader is not None else None

    async def submit_review_for_user(
        self,
        *,
        case_id: str,
        user_id: str,
        expected_annotation_digest: str,
        decision: str,
        reason: str | None,
        idempotency_key: str | None = None,
        now: str | None = None,
    ) -> ReviewDecision:
        case, _ = await self._authorized_case(case_id, user_id)
        annotation = await self._read_annotation(case.case_id)
        if annotation is None:
            raise ValueError("feedback_case_annotation_required")
        if annotation.annotation_digest != expected_annotation_digest:
            raise ValueError("feedback_case_stale")
        if decision == "accept":
            await self._validate_review_acceptance(case, annotation)
        reader = getattr(self.case_repository, "read_review_decisions", None)
        previous = await reader(case.case_id) if reader is not None else ()
        timestamp = now or datetime.now(timezone.utc).isoformat()
        review = ReviewDecision(
            decision_id=_review_decision_id(
                case_id=case.case_id,
                user_id=user_id,
                idempotency_key=idempotency_key,
            ),
            case_id=case.case_id,
            annotation_digest=annotation.annotation_digest,
            decision=decision,  # type: ignore[arg-type]
            reason=reason,
            created_by=user_id,
            seq=len(previous) + 1,
            created_at=timestamp,
        )
        appender = getattr(self.case_repository, "append_review_decision", None)
        if appender is None:
            raise RuntimeError("feedback review persistence is not configured")
        return await appender(
            review,
            expected_annotation_digest=expected_annotation_digest,
            now=timestamp,
        )

    async def _validate_review_acceptance(
        self, case: FeedbackCase, annotation: FeedbackAnnotation
    ) -> None:
        """Reject an approval that cannot produce any declared dataset row.

        Snapshot creation repeats these checks against the frozen read set. The
        review boundary also performs them so an ``accept`` record cannot claim
        that an unusable SFT or preference sample was admitted.
        """
        uses = set(annotation.dataset_uses)
        if not uses:
            raise ValueError("review_dataset_use_missing")
        needs_target = bool(uses & {"sft", "preference"})
        if needs_target and not annotation.target:
            raise ValueError("review_target_missing")
        if needs_target and not annotation.support_source_refs:
            raise ValueError("review_support_source_missing")
        if "preference" not in uses:
            return
        messages = await self.chat_repository.read_messages(case.session_id)
        answer = next(
            (message for message in messages if message.message_id == case.anchor_message_id),
            None,
        )
        if answer is None or answer.role is not ChatMessageRole.ASSISTANT:
            raise ValueError("review_anchor_answer_missing")
        if annotation.target.strip() == answer.content.strip():
            raise ValueError("review_preference_pair_missing")

    async def list_reviews_for_user(
        self, *, case_id: str, user_id: str
    ) -> tuple[ReviewDecision, ...]:
        case, _ = await self._authorized_case(case_id, user_id)
        reader = getattr(self.case_repository, "read_review_decisions", None)
        if reader is None:
            return ()
        return await reader(case.case_id)

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
        results = await self.case_repository.read_analysis_results(case.analysis_result_ids)
        signal_reader = getattr(
            self.case_repository, "read_correction_signal_analysis_results", None
        )
        signal_results = (
            await signal_reader(case.signal_analysis_result_ids)
            if signal_reader is not None
            else ()
        )
        tool_failure_reader = getattr(
            self.case_repository, "read_tool_failure_analysis_results", None
        )
        tool_failure_results = (
            await tool_failure_reader(case.tool_failure_analysis_result_ids)
            if tool_failure_reader is not None
            else ()
        )
        result = _latest_result((*results, *signal_results, *tool_failure_results))
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

def _detail(
    case: FeedbackCase,
    messages: tuple[Any, ...],
    results: tuple[AnalysisResult, ...],
    feedback: tuple[Any, ...],
    annotation: FeedbackAnnotation | None = None,
    decisions: tuple[ReviewDecision, ...] = (),
    *,
    signal_results: tuple[Any, ...] = (),
    correction_items: tuple[dict[str, Any], ...] = (),
    tool_failure_results: tuple[Any, ...] = (),
) -> dict[str, Any]:
    latest = _latest_result((*results, *signal_results, *tool_failure_results))
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
                "signal_type": "chat_message_feedback",
                "feedback_id": item.feedback_id,
                "rating": item.rating,
                "reason": item.reason,
                "comment": item.comment,
                "created_at": item.created_at,
            }
            for item in feedback
        ] + list(correction_items) + list(_tool_failure_records(tool_failure_results)),
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
            _analysis_projection(latest)
            if latest
            else None
        ),
        "annotation": annotation.to_record() if annotation is not None else None,
        "review_decisions": [item.to_record() for item in decisions],
        "current_annotation_digest": case.annotation_digest,
        "technical_error": case.context_snapshot.get("technical_error"),
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


def _latest_result(results: tuple[Any, ...]) -> Any | None:
    return max(results, key=lambda item: (item.created_at, item.result_id), default=None)


def _analysis_projection(result: Any) -> dict[str, Any]:
    projection = {
        "problem_type": result.problem_type,
        "confidence": result.confidence,
        "suggested_target": result.suggested_target,
        "model": result.model,
        "result_id": result.result_id,
        "coverage_status": result.evidence_coverage.coverage_status,
    }
    if hasattr(result, "signal_type"):
        projection.update(
            {
                "signal_type": result.signal_type,
                "signal_id": result.signal_id,
                "resolution": "unresolved_candidate",
            }
        )
        if hasattr(result, "trigger_message_id"):
            projection["trigger_message_id"] = result.trigger_message_id
        if hasattr(result, "tool_call_id"):
            projection.update(
                {
                    "tool_call_id": result.tool_call_id,
                    "result_message_id": result.result_message_id,
                    "tool_name": result.tool_name,
                    "error_code": result.error_code,
                }
            )
    else:
        projection["signal_type"] = "chat_message_feedback"
        projection["feedback_id"] = result.feedback_id
    return projection


def _correction_signal_records(
    results: tuple[Any, ...],
    *,
    messages: tuple[Any, ...],
    session_id: str,
) -> tuple[dict[str, Any], ...]:
    by_id = {item.message_id: item for item in messages}
    records: list[dict[str, Any]] = []
    for result in results:
        trigger = by_id.get(result.trigger_message_id)
        if trigger is None or trigger.session_id != session_id:
            continue
        records.append(
            {
                "signal_type": result.signal_type,
                "signal_id": result.signal_id,
                "anchor_message_id": result.anchor_message_id,
                "trigger_message_id": result.trigger_message_id,
                "content": trigger.content,
                "created_at": trigger.created_at,
                "problem_type": result.problem_type,
                "confidence": result.confidence,
                "suggested_target": None,
                "resolution": "unresolved_candidate",
            }
        )
    return tuple(records)


def _tool_failure_records(results: tuple[Any, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "signal_type": result.signal_type,
            "signal_id": result.signal_id,
            "tool_call_id": result.tool_call_id,
            "assistant_message_id": result.assistant_message_id,
            "result_message_id": result.result_message_id,
            "tool_name": result.tool_name,
            "error_code": result.error_code,
            "problem_type": result.problem_type,
            "confidence": result.confidence,
            "suggested_target": None,
            "resolution": "unresolved_candidate",
            "created_at": result.created_at,
        }
        for result in results
    )


def _case_source_refs(
    case: FeedbackCase, results: tuple[AnalysisResult, ...]
) -> set[str]:
    refs: set[str] = set()
    for result in results:
        coverage = result.evidence_coverage.to_record()
        for field in ("inspected_sources", "omitted_candidates", "claim_support"):
            for item in coverage.get(field) or ():
                if isinstance(item, dict):
                    value = item.get("source_ref") or item.get("source_id")
                    if value:
                        refs.add(str(value))
        refs.update(str(value) for value in result.suggested_evidence if value)
    for item in (case.context_snapshot.get("source_refs") or ()):
        if isinstance(item, dict):
            value = item.get("source_ref") or item.get("source_id")
        else:
            value = item
        if value:
            refs.add(str(value))
    return refs


def _review_decision_id(
    *, case_id: str, user_id: str, idempotency_key: str | None
) -> str:
    """Bind an HTTP retry key to one user's case without persisting another key.

    The review table already treats ``decision_id`` as the idempotency identity.
    A stable digest lets the public API reuse that guarantee while keeping the
    key scoped to the authenticated user and case. Requests without a key keep
    the historical random identity and remain append-only.
    """
    if idempotency_key is None:
        return f"review_{uuid4().hex[:32]}"
    key = idempotency_key.strip()
    if not key:
        raise ValueError("idempotency_key_invalid")
    digest = sha256(f"{user_id}\0{case_id}\0{key}".encode("utf-8")).hexdigest()
    return f"review_{digest[:48]}"


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
