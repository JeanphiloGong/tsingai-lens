from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from application.repositories.analysis_job_repository import (
    CORRECTION_SIGNAL_JOB_TYPE,
    TOOL_FAILURE_JOB_TYPE,
    correction_signal_idempotency_key,
    tool_failure_idempotency_key,
)
from infra.persistence.postgres.analysis_job_repository import (
    PostgresAnalysisJobRepository,
)
from infra.persistence.postgres.models.feedback import AnalysisJobRow

pytestmark = pytest.mark.anyio

BASE_TIME = datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)


async def _insert_job(
    session_factory,
    *,
    job_id: str,
    job_type: str = "feedback_analysis",
    status: str = "pending",
    result_id: str | None = None,
    lease_expires_at: datetime | None = None,
    worker_id: str | None = None,
    lease_version: int = 0,
) -> None:
    started_at = BASE_TIME if status in {"running", "succeeded", "failed", "cancelled"} else None
    finished_at = (
        BASE_TIME + timedelta(seconds=1)
        if status in {"succeeded", "failed", "cancelled"}
        else None
    )
    async with session_factory.begin() as session:
        session.add(
            AnalysisJobRow(
                job_id=job_id,
                job_type=job_type,
                payload_version=1,
                payload={"feedback_id": f"feedback-{job_id}"},
                status=status,
                available_at=BASE_TIME,
                started_at=started_at,
                finished_at=finished_at,
                result_id=result_id,
                error_code="provider_failed" if status == "failed" else None,
                idempotency_key=f"idempotency-{job_id}",
                created_at=BASE_TIME,
                updated_at=finished_at or BASE_TIME,
                worker_id=worker_id,
                lease_expires_at=lease_expires_at,
                heartbeat_at=BASE_TIME if worker_id else None,
                lease_version=lease_version,
            )
        )


async def test_failed_feedback_analysis_job_can_be_requeued_and_claimed(
    postgres_session_factory,
) -> None:
    repository = PostgresAnalysisJobRepository(postgres_session_factory)
    await _insert_job(postgres_session_factory, job_id="job-requeue")

    claimed = await repository.claim_next_feedback_analysis_job(
        (BASE_TIME + timedelta(seconds=1)).isoformat()
    )
    assert claimed is not None
    failed = await repository.mark_failed(
        claimed.job_id,
        error_code="provider_failed",
        finished_at=(BASE_TIME + timedelta(seconds=2)).isoformat(),
    )
    assert failed.status == "failed"
    assert failed.error_code == "provider_failed"

    requeued = await repository.requeue_failed_feedback_analysis_job(
        claimed.job_id,
        now=(BASE_TIME + timedelta(seconds=3)).isoformat(),
    )
    assert requeued.status == "pending"
    assert requeued.started_at is None
    assert requeued.finished_at is None
    assert requeued.result_id is None
    assert requeued.error_code is None
    assert requeued.available_at == "2026-09-24T00:00:03+00:00"

    claimed_again = await repository.claim_next_feedback_analysis_job(
        (BASE_TIME + timedelta(seconds=4)).isoformat()
    )
    assert claimed_again is not None
    assert claimed_again.job_id == claimed.job_id
    assert claimed_again.status == "running"


async def test_expired_running_job_is_recovered_and_claimed_again(
    postgres_session_factory,
) -> None:
    repository = PostgresAnalysisJobRepository(
        postgres_session_factory,
        worker_id="worker-next",
    )
    await _insert_job(
        postgres_session_factory,
        job_id="job-expired",
        status="running",
        worker_id="worker-crashed",
        lease_expires_at=BASE_TIME + timedelta(seconds=5),
        lease_version=1,
    )

    recovery_time = BASE_TIME + timedelta(seconds=6)
    assert await repository.recover_expired_jobs(recovery_time.isoformat()) == 1
    recovered = await repository.read_job("job-expired")
    assert recovered is not None
    assert recovered.status == "pending"
    assert recovered.error_code == "worker_lease_expired"
    assert recovered.worker_id is None
    assert recovered.lease_expires_at is None

    claimed = await repository.claim_next_feedback_analysis_job(
        (recovery_time + timedelta(seconds=1)).isoformat()
    )
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.worker_id == "worker-next"
    assert claimed.heartbeat_at == "2026-09-24T00:00:07+00:00"
    assert claimed.lease_expires_at == "2026-09-24T00:15:07+00:00"
    assert claimed.lease_version == 2
    assert claimed.error_code is None


@pytest.mark.parametrize(
    ("job_type", "status", "result_id"),
    [
        ("feedback_analysis", "running", None),
        ("feedback_analysis", "succeeded", "result-1"),
        ("feedback_analysis", "cancelled", None),
        ("tool_failure_analysis", "failed", None),
        ("feedback_analysis", "failed", "result-1"),
    ],
)
async def test_requeue_rejects_unsupported_terminal_identity(
    postgres_session_factory,
    job_type: str,
    status: str,
    result_id: str | None,
) -> None:
    repository = PostgresAnalysisJobRepository(postgres_session_factory)
    await _insert_job(
        postgres_session_factory,
        job_id="job-invalid",
        job_type=job_type,
        status=status,
        result_id=result_id,
    )

    with pytest.raises(ValueError):
        await repository.requeue_failed_feedback_analysis_job(
            "job-invalid",
            now=(BASE_TIME + timedelta(seconds=3)).isoformat(),
        )

    stored = await repository.read_job("job-invalid")
    assert stored is not None
    assert stored.status == status
    assert stored.result_id == result_id


async def test_requeue_rejects_unknown_job(postgres_session_factory) -> None:
    repository = PostgresAnalysisJobRepository(postgres_session_factory)

    with pytest.raises(FileNotFoundError, match="job-missing"):
        await repository.requeue_failed_feedback_analysis_job(
            "job-missing",
            now=BASE_TIME.isoformat(),
        )


async def test_correction_signal_jobs_use_payload_identity_and_are_idempotent(
    postgres_session_factory,
) -> None:
    repository = PostgresAnalysisJobRepository(postgres_session_factory)
    kwargs = {
        "session_id": "session-1",
        "anchor_message_id": "answer-1",
        "trigger_message_id": "challenge-1",
        "trigger_digest": "a" * 64,
        "idempotency_key": correction_signal_idempotency_key(
            session_id="session-1",
            anchor_message_id="answer-1",
            trigger_message_id="challenge-1",
            trigger_digest="a" * 64,
        ),
        "now": BASE_TIME.isoformat(),
    }
    first = await repository.enqueue_correction_signal_analysis(**kwargs)
    second = await repository.enqueue_correction_signal_analysis(**kwargs)

    assert first.job_id == second.job_id
    assert first.job_type == CORRECTION_SIGNAL_JOB_TYPE
    assert first.payload == {
        "session_id": "session-1",
        "anchor_message_id": "answer-1",
        "trigger_message_id": "challenge-1",
        "trigger_digest": "a" * 64,
    }
    claimed = await repository.claim_next_correction_signal_analysis_job(
        (BASE_TIME + timedelta(seconds=1)).isoformat()
    )
    assert claimed is not None and claimed.job_id == first.job_id


async def test_correction_signal_pending_job_can_be_cancelled_by_trigger(
    postgres_session_factory,
) -> None:
    repository = PostgresAnalysisJobRepository(postgres_session_factory)
    trigger_digest = "b" * 64
    job = await repository.enqueue_correction_signal_analysis(
        session_id="session-1",
        anchor_message_id="answer-1",
        trigger_message_id="challenge-withdrawn",
        trigger_digest=trigger_digest,
        idempotency_key=correction_signal_idempotency_key(
            session_id="session-1",
            anchor_message_id="answer-1",
            trigger_message_id="challenge-withdrawn",
            trigger_digest=trigger_digest,
        ),
        now=BASE_TIME.isoformat(),
    )
    cancelled = await repository.cancel_correction_signal_analysis_jobs(
        trigger_message_id="challenge-withdrawn",
        finished_at=(BASE_TIME + timedelta(seconds=1)).isoformat(),
    )
    saved = await repository.read_job(job.job_id)

    assert cancelled == 1
    assert saved is not None
    assert saved.status == "cancelled"
    assert saved.error_code == "correction_signal_withdrawn"


async def test_tool_failure_enqueue_is_idempotent_and_claim_is_type_scoped(
    postgres_session_factory,
) -> None:
    repository = PostgresAnalysisJobRepository(postgres_session_factory)
    digest = "c" * 64
    kwargs = {
        "session_id": "session-tool-failure",
        "tool_call_id": "call-tool-failure",
        "assistant_message_id": "assistant-tool-failure",
        "result_message_id": "tool-result-failure",
        "result_digest": digest,
        "idempotency_key": tool_failure_idempotency_key(
            session_id="session-tool-failure",
            tool_call_id="call-tool-failure",
            assistant_message_id="assistant-tool-failure",
            result_message_id="tool-result-failure",
            result_digest=digest,
        ),
        "now": BASE_TIME.isoformat(),
    }
    first = await repository.enqueue_tool_failure_analysis(**kwargs)
    second = await repository.enqueue_tool_failure_analysis(**kwargs)
    feedback = await repository.enqueue_feedback_analysis(
        feedback_id="feedback-waits",
        idempotency_key="feedback-waits-key",
        now=BASE_TIME.isoformat(),
    )

    assert first.job_id == second.job_id
    assert first.job_type == TOOL_FAILURE_JOB_TYPE
    assert first.payload_version == 1
    assert first.payload == {
        "session_id": "session-tool-failure",
        "tool_call_id": "call-tool-failure",
        "assistant_message_id": "assistant-tool-failure",
        "result_message_id": "tool-result-failure",
        "result_digest": digest,
    }
    claimed = await repository.claim_next_tool_failure_analysis_job(
        (BASE_TIME + timedelta(seconds=1)).isoformat()
    )
    assert claimed is not None
    assert claimed.job_id == first.job_id
    assert claimed.job_type == TOOL_FAILURE_JOB_TYPE
    assert (await repository.read_job(feedback.job_id)).status == "pending"

    feedback_claimed = await repository.claim_next_feedback_analysis_job(
        (BASE_TIME + timedelta(seconds=1)).isoformat()
    )
    assert feedback_claimed is not None
    assert feedback_claimed.job_id == feedback.job_id
