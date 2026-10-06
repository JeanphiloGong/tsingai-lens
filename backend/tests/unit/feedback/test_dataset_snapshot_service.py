from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from application.feedback.dataset_snapshot_service import (
    DatasetSelection,
    DatasetSnapshotIntegrityError,
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
    DatasetSnapshot,
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

    async def read(self, dataset_id):
        return next(
            (snapshot for snapshot in self.saved if snapshot.dataset_id == dataset_id),
            None,
        )


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
            "evidence_coverage": {
                "inspected_sources": [
                    {
                        "document_id": "doc-b",
                        "document_title": "Paper B",
                        "source_kind": "figure_caption",
                        "source_ref": "source-b-caption",
                        "page": 4,
                        "heading_path": "Results > Figure 3",
                        "quote": "Figure 3 caption records preheating at 200 C.",
                    }
                ],
                "coverage_status": "partial",
            },
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
            selections=(DatasetSelection("case-1"),),
            now="2026-09-24T00:01:00+00:00",
        )
    )
    assert snapshot.row_count == 1
    assert "split" not in snapshot.rows[0]
    assert "paper_families" not in snapshot.provenance
    assert snapshot.provenance["items"][0]["document_ids"] == ["doc-a", "doc-b"]
    assert snapshot.rows[0]["reference"] is None
    assert snapshot.rows[0]["evidence"][0]["document_title"] == "Paper B"
    assert snapshot.rows[0]["evidence"][0]["quote"].startswith("Figure 3")
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
            selections=(DatasetSelection("case-1"),),
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
            selections=(DatasetSelection("case-1"),),
        )
    )
    preference = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="preference",
            selections=(DatasetSelection("case-1"),),
        )
    )
    assert sft.rows[0]["record_type"] == "sft"
    assert sft.rows[0]["target"] == "A corrected answer"
    assert preference.rows[0]["record_type"] == "preference"
    assert preference.rows[0]["chosen"] == "A corrected answer"
    assert preference.rows[0]["rejected"] == "B has no preheating."


def test_download_rows_keep_readable_evidence_but_hide_internal_ids() -> None:
    service, _ = _fixture()
    snapshot = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="sft",
            selections=(DatasetSelection("case-1"),),
        )
    )

    _, payload = asyncio.run(
        service.jsonl_for_user(owner_id="user-1", dataset_id=snapshot.dataset_id)
    )
    row = json.loads(payload.decode().splitlines()[0])

    assert row["evidence"][0] == {
        "document_title": "Paper B",
        "source_kind": "figure_caption",
        "page": 4,
        "heading_path": "Results > Figure 3",
        "quote": "Figure 3 caption records preheating at 200 C.",
    }
    assert "case_id" not in row
    assert "session_id" not in row
    assert "source_refs" not in row
    assert "review_id" not in row


def test_sft_is_excluded_when_support_source_has_no_readable_content() -> None:
    service, _ = _fixture()
    service.case_repository.case = FeedbackCase(
        **{
            **service.case_repository.case.to_record(),
            "context_snapshot": {
                "requested_scope": [{"document_id": "doc-b", "document_title": "Paper B"}],
                "source_refs": ["source-b-caption"],
            },
        }
    )
    snapshot = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="sft",
            selections=(DatasetSelection("case-1"),),
        )
    )

    assert snapshot.row_count == 0
    assert snapshot.exclusions[0]["reason"] == "evidence_content_missing"


def test_sft_is_excluded_when_evidence_has_no_readable_document_title() -> None:
    service, _ = _fixture()
    service.case_repository.case = FeedbackCase(
        **{
            **service.case_repository.case.to_record(),
            "context_snapshot": {
                "requested_scope": [{"document_id": "doc-b"}],
                "source_refs": ["source-b-caption"],
                "evidence_coverage": {
                    "inspected_sources": [
                        {
                            "document_id": "doc-b",
                            "source_ref": "source-b-caption",
                            "quote": "A quote without a document title.",
                        }
                    ]
                },
            },
        }
    )

    snapshot = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="sft",
            selections=(DatasetSelection("case-1"),),
        )
    )

    assert snapshot.row_count == 0
    assert snapshot.exclusions[0]["reason"] == "evidence_content_missing"


def test_selection_order_is_canonical_for_digest() -> None:
    service, _ = _fixture(target=None)
    first = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="evaluation",
            selections=(DatasetSelection("case-1"),),
        )
    )
    second = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="evaluation",
            selections=(DatasetSelection("case-1"),),
        )
    )
    assert first.manifest_digest == second.manifest_digest


def test_duplicate_case_is_excluded_without_experiment_grouping() -> None:
    service, _ = _fixture()
    snapshot = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="evaluation",
            selections=(DatasetSelection("case-1"), DatasetSelection("case-1")),
        )
    )
    assert snapshot.row_count == 1
    assert snapshot.exclusions[0]["reason"] == "duplicate_selection"


def test_historical_snapshot_download_preserves_bytes_and_digests() -> None:
    from application.feedback.dataset_snapshot_service import _digest

    service, snapshots = _fixture()
    snapshot = asyncio.run(service.create_for_user(
        owner_id="user-1", collection_id="collection-1", dataset_type="evaluation",
        selections=(DatasetSelection("case-1"),),
    ))
    rows = [{**snapshot.rows[0], "split": "eval"}]
    provenance = {
        **snapshot.provenance, "schema_version": "feedback-dataset-provenance.v1",
        "paper_families": {"doc-b": "paper-b"},
        "items": [{**snapshot.provenance["items"][0], "split": "eval",
                   "row_digest": _digest(rows[0]), "paper_family_keys": ["paper-b"]}],
    }
    basis = {key: snapshot.manifest[key] for key in (
        "schema_version", "owner_id", "collection_id", "dataset_type",
        "rows", "exclusions", "provenance_digest",
    )}
    basis.update(schema_version="feedback-dataset.v2", rows=rows, provenance_digest=_digest(provenance))
    payload = jsonl_bytes_for_rows(rows)
    manifest = {**snapshot.manifest, **basis, "manifest_digest": _digest(basis),
                "content_digest": hashlib.sha256(payload).hexdigest()}
    record = snapshot.to_record()
    for key in ("row_count", "excluded_count", "is_empty"):
        record.pop(key)
    historical = DatasetSnapshot(**{**record, "rows": tuple(rows), "provenance": provenance,
        "manifest": manifest, "manifest_digest": manifest["manifest_digest"],
        "provenance_digest": basis["provenance_digest"], "content_digest": manifest["content_digest"]})
    snapshots.saved = [historical]
    read, downloaded = asyncio.run(service.jsonl_for_user(owner_id="user-1", dataset_id=historical.dataset_id))
    assert downloaded == payload
    assert read.manifest == manifest


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
            inspected_sources=(
                {
                    "document_id": "doc-b",
                    "document_title": "Paper B",
                    "source_ref": "suggested-ref",
                    "source_kind": "figure_caption",
                    "quote": "The caption records the preheating condition.",
                },
            ),
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
            selections=(DatasetSelection("case-1"),),
        )
    )
    assert snapshot.row_count == 1


def test_read_rejects_snapshot_when_provenance_digest_no_longer_matches() -> None:
    service, snapshots = _fixture(target=None)
    snapshot = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="evaluation",
            selections=(DatasetSelection("case-1"),),
        )
    )
    snapshot.provenance["items"].append({"case_id": "tampered", "split": "eval"})

    with pytest.raises(
        DatasetSnapshotIntegrityError,
        match="dataset_snapshot_provenance_digest_mismatch",
    ):
        asyncio.run(
            service.read_for_user(owner_id="user-1", dataset_id=snapshot.dataset_id)
        )


def test_download_rejects_snapshot_when_manifest_digest_no_longer_matches() -> None:
    service, snapshots = _fixture(target=None)
    snapshot = asyncio.run(
        service.create_for_user(
            owner_id="user-1",
            collection_id="collection-1",
            dataset_type="evaluation",
            selections=(DatasetSelection("case-1"),),
        )
    )
    snapshot.manifest["manifest_digest"] = "0" * 64

    with pytest.raises(
        DatasetSnapshotIntegrityError,
        match="dataset_snapshot_manifest_digest_mismatch",
    ):
        asyncio.run(
            service.jsonl_for_user(owner_id="user-1", dataset_id=snapshot.dataset_id)
        )
