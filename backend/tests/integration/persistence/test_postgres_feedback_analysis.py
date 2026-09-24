from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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
