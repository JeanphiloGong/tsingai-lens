from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from application.feedback.dataset_snapshot_service import (
    DatasetSelection,
    DatasetSnapshotError,
    DatasetSnapshotService,
    jsonl_bytes_for_rows,
)
from domain.chat import ChatMessage, ChatSession
from domain.feedback import (
    AnalysisResult,
    EvidenceCoverage,
    FeedbackAnnotation,
    FeedbackCase,
    ReviewDecision,
)


class _Collections:
    async def get_collection_for_user(self, collection_id: str, user_id: str):
        if (collection_id, user_id) != ("collection-1", "user-1"):
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id}


class _Chat:
    def __init__(self, session, messages):
        self.session = session
        self.messages = messages

    async def read_session(self, session_id: str):
        return self.session if session_id == self.session.session_id else None

    async def read_messages(self, session_id: str):
        return self.messages if session_id == self.session.session_id else ()


class _Cases:
    def __init__(self, case, annotation, review, results=()):
        self.case = case
        self.annotation = annotation
        self.review = review
        self.results = tuple(results)

    async def read_case(self, case_id: str):
        return self.case if case_id == self.case.case_id else None

    async def read_annotation(self, case_id: str):
        return self.annotation if case_id == self.case.case_id else None

    async def read_review_decisions(self, case_id: str):
        return (self.review,) if case_id == self.case.case_id else ()

    async def read_analysis_results(self, result_ids):
        return tuple(self.results)


class _Snapshots:
    def __init__(self):
        self.saved = []

    async def save(self, snapshot):
        self.saved.append(snapshot)
        return snapshot


def _fixture(*, target: str | None = "A corrected answer"):
    session = ChatSession.create(
        session_id="session-1",
        user_id="user-1",
        collection_id="collection-1",
        created_at="2026-09-24T00:00:00+00:00",
    )
    question = ChatMessage.user(
        message_id="question-1",
        session_id=session.session_id,
        content="Compare the preheating evidence in A and B.",
        created_at="2026-09-24T00:00:01+00:00",
    )
    answer = ChatMessage.assistant(
        message_id="answer-1",
        session_id=session.session_id,
        content="B has no preheating.",
        created_at="2026-09-24T00:00:02+00:00",
    )
    case = FeedbackCase(
        case_id="case-1",
        collection_id=session.collection_id,
        session_id=session.session_id,
        anchor_message_id=answer.message_id,
        source_signal_ids=("feedback-1",),
        analysis_result_ids=(),
        context_snapshot={
            "requested_scope": [
                {"document_id": "doc-a", "document_title": "Paper A"},
                {"document_id": "doc-b", "document_title": "Paper B"},
            ],
            "gaps": ["B figure caption was omitted"],
            "source_refs": ["source-b-caption"],
        },
        status="accepted",
        created_at="2026-09-24T00:00:03+00:00",
        updated_at="2026-09-24T00:00:03+00:00",
    )
    annotation = FeedbackAnnotation.build(
        annotation_id="annotation-1",
        case_id=case.case_id,
        version=1,
        problem_type="source_missing",
        severity="high",
        target=target,
        support_source_refs=("source-b-caption",) if target else (),
        dataset_uses=("evaluation", "sft", "preference") if target else ("evaluation",),
        reason="The figure caption supports the correction.",
        created_by="user-1",
        created_at="2026-09-24T00:00:04+00:00",
    )
    case = FeedbackCase(**{**case.to_record(), "annotation_digest": annotation.annotation_digest})
    review = ReviewDecision(
        decision_id="review-1",
        case_id=case.case_id,
        annotation_digest=annotation.annotation_digest,
        decision="accept",
        reason="Evidence checked.",
        created_by="user-1",
        seq=1,
        created_at="2026-09-24T00:00:05+00:00",
    )
    snapshots = _Snapshots()
    service = DatasetSnapshotService(
        repository=snapshots,
        case_repository=_Cases(case, annotation, review),
        chat_repository=_Chat(session, (question, answer)),
        collection_service=_Collections(),
    )
    return service, snapshots


def test_evaluation_snapshot_freezes_rows_and_digest() -> None:
    service, snapshots = _fixture(target=None)
    snapshot = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="evaluation",
            selections=(DatasetSelection("case-1", "eval"),),
            paper_families={"doc-a": "family-a", "doc-b": "family-b"},
            now="2026-09-24T00:01:00+00:00",
        )
    )
    assert snapshot.row_count == 1
    assert snapshot.rows[0]["reference"] is None
    assert snapshot.manifest["empty"] is False
    payload = jsonl_bytes_for_rows(snapshot.rows)
    assert hashlib.sha256(payload).hexdigest() == snapshot.content_digest
    assert json.loads(payload.decode().splitlines()[0])["record_type"] == "evaluation"
    assert snapshots.saved[0].rows == snapshot.rows


def test_sft_without_target_is_excluded_but_empty_snapshot_is_valid() -> None:
    service, _ = _fixture(target=None)
    snapshot = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="sft",
            selections=(DatasetSelection("case-1", "train"),),
            paper_families={"doc-a": "family-a", "doc-b": "family-b"},
        )
    )
    assert snapshot.row_count == 0
    assert snapshot.excluded_count == 1
    assert snapshot.exclusions[0]["reason"] == "dataset_use_not_authorized"
    assert snapshot.is_empty


def test_sft_and_preference_rows_use_distinct_frozen_shapes() -> None:
    service, _ = _fixture()
    sft = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="sft",
            selections=(DatasetSelection("case-1", "train"),),
            paper_families={"doc-a": "family-a", "doc-b": "family-b"},
        )
    )
    preference = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="preference",
            selections=(DatasetSelection("case-1", "eval"),),
            paper_families={"doc-a": "family-a", "doc-b": "family-b"},
        )
    )
    assert sft.rows[0]["record_type"] == "sft"
    assert sft.rows[0]["target"] == "A corrected answer"
    assert preference.rows[0]["record_type"] == "preference"
    assert preference.rows[0]["chosen"] == "A corrected answer"
    assert preference.rows[0]["rejected"] == "B has no preheating."


def test_selection_order_is_canonical_for_digest() -> None:
    service, _ = _fixture(target=None)
    first = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="evaluation",
            selections=(DatasetSelection("case-1", "eval"),),
            paper_families={"doc-a": "family-a", "doc-b": "family-b"},
        )
    )
    second = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="evaluation",
            selections=(DatasetSelection("case-1", "eval"),),
            paper_families={"doc-b": "family-b", "doc-a": "family-a"},
        )
    )
    assert first.manifest_digest == second.manifest_digest


def test_train_eval_family_or_session_leakage_is_rejected() -> None:
    service, _ = _fixture()
    with pytest.raises(DatasetSnapshotError, match="dataset_split_leakage"):
        asyncio.run(
            service.create_for_user(
                owner_id="user-1",
                collection_id="collection-1",
                dataset_type="evaluation",
                selections=(
                    DatasetSelection("case-1", "train"),
                    DatasetSelection("case-1", "eval"),
                ),
                paper_families={"doc-a": "family-a", "doc-b": "family-b"},
            )
        )


def test_cross_collection_access_is_rejected_before_reading_cases() -> None:
    service, _ = _fixture()
    with pytest.raises(FileNotFoundError):
        asyncio.run(
            service.create_for_user(
                owner_id="other-user",
                collection_id="collection-1",
                dataset_type="evaluation",
                selections=(),
            )
        )


def test_suggested_evidence_is_a_valid_support_source_for_export() -> None:
    service, _ = _fixture()
    case = service.case_repository.case
    annotation = service.case_repository.annotation
    annotation = FeedbackAnnotation.build(
        annotation_id=annotation.annotation_id,
        case_id=annotation.case_id,
        version=annotation.version,
        problem_type=annotation.problem_type,
        severity=annotation.severity,
        target=annotation.target,
        support_source_refs=("suggested-ref",),
        dataset_uses=annotation.dataset_uses,
        reason=annotation.reason,
        created_by=annotation.created_by,
        created_at=annotation.created_at,
    )
    case = FeedbackCase(**{**case.to_record(), "annotation_digest": annotation.annotation_digest})
    review = ReviewDecision(
        decision_id="review-suggested",
        case_id=case.case_id,
        annotation_digest=annotation.annotation_digest,
        decision="accept",
        reason="Evidence checked.",
        created_by="user-1",
        seq=1,
        created_at="2026-09-24T00:00:05+00:00",
    )
    result = AnalysisResult(
        result_id="result-1",
        job_id="job-1",
        feedback_id="feedback-1",
        session_id=case.session_id,
        collection_id=case.collection_id,
        anchor_message_id=case.anchor_message_id,
        problem_type="source_missing",
        confidence=0.9,
        related_message_ids=(case.anchor_message_id,),
        suggested_evidence=("suggested-ref",),
        suggested_target=None,
        evidence_coverage=EvidenceCoverage(
            requested_scope=({"document_id": "doc-a"}, {"document_id": "doc-b"}),
            coverage_status="partial",
        ),
        model="test-model",
        input_digest="d" * 64,
        created_at="2026-09-24T00:00:02+00:00",
    )
    service.case_repository = _Cases(case, annotation, review, (result,))

    snapshot = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="sft",
            selections=(DatasetSelection("case-1", "train"),),
            paper_families={"doc-a": "family-a", "doc-b": "family-b"},
        )
    )
    assert snapshot.row_count == 1
