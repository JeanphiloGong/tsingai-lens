"""Test drivers for one explicitly claimed worker cycle.

Production entry points own resources and polling. These drivers let existing
business fixtures supply deterministic engines while exercising the same
concrete repository claims, execution functions, and heartbeat scope.
"""

from datetime import datetime, timezone

from application.feedback import (
    analysis_worker,
    correction_signal_worker,
    tool_failure_worker,
    sample_build_worker,
)
from application.feedback.analysis_handler import (
    analyze_feedback_job,
    RuleBasedFeedbackAnalysisEngine,
)
from application.feedback.correction_signal_handler import (
    analyze_correction_signal_job,
    RuleBasedCorrectionSignalAnalysisEngine,
)
from application.feedback.tool_failure_handler import (
    analyze_tool_failure_job,
    RuleBasedToolFailureAnalysisEngine,
)
from application.feedback.worker_lease import run_with_lease_heartbeat
from application.feedback.sft_sample_builder import SftSampleBuilder
from application.feedback.preference_sample_builder import PreferenceSampleBuilder
from application.feedback.evaluation_sample_builder import EvaluationSampleBuilder


class FeedbackAnalyzerFixture:
    def __init__(self, *, engine=None, model_name="rule-based-v1"):
        self.engine = engine or RuleBasedFeedbackAnalysisEngine()
        self.model_name = model_name

    async def handle(self, job):
        return await analyze_feedback_job(
            job, engine=self.engine, model_name=self.model_name
        )


class CorrectionAnalyzerFixture:
    def __init__(self, *, engine=None, model_name="rule-based-correction-v1"):
        self.engine = engine or RuleBasedCorrectionSignalAnalysisEngine()
        self.model_name = model_name

    async def handle(self, job):
        return await analyze_correction_signal_job(
            job, engine=self.engine, model_name=self.model_name
        )


class ToolFailureAnalyzerFixture:
    def __init__(self, *, engine=None, model_name="rule-based-tool-failure-v1"):
        self.engine = engine or RuleBasedToolFailureAnalysisEngine()
        self.model_name = model_name

    async def handle(self, job):
        return await analyze_tool_failure_job(
            job, engine=self.engine, model_name=self.model_name
        )


class FeedbackWorkerFixture:
    def __init__(self, *, handler):
        self.handler = handler

    async def run_once(self):
        now = datetime.now(timezone.utc).isoformat()
        job = await analysis_worker.AnalysisJobRepo.claim_next_feedback_analysis_job(
            now=now
        )
        if job is None:
            return None
        return await run_with_lease_heartbeat(
            job,
            lambda: analysis_worker.execute_feedback_analysis_job(
                job, engine=self.handler.engine, model_name=self.handler.model_name
            ),
        )


class CorrectionWorkerFixture:
    def __init__(self, *, handler):
        self.handler = handler

    async def run_once(self):
        now = datetime.now(timezone.utc).isoformat()
        job = await correction_signal_worker.AnalysisJobRepo.claim_next_correction_signal_analysis_job(
            now=now
        )
        if job is None:
            return None
        return await run_with_lease_heartbeat(
            job,
            lambda: correction_signal_worker.execute_correction_signal_analysis_job(
                job, engine=self.handler.engine, model_name=self.handler.model_name
            ),
        )


class ToolFailureWorkerFixture:
    def __init__(self, *, handler):
        self.handler = handler

    async def run_once(self):
        now = datetime.now(timezone.utc).isoformat()
        job = await tool_failure_worker.AnalysisJobRepo.claim_next_tool_failure_analysis_job(
            now=now
        )
        if job is None:
            return None
        return await run_with_lease_heartbeat(
            job,
            lambda: tool_failure_worker.execute_tool_failure_analysis_job(
                job, engine=self.handler.engine, model_name=self.handler.model_name
            ),
        )


class SampleWorkerFixture:
    def __init__(self, *, builder=None, builders=None, build_timeout_seconds=600):
        self.builders = builders or {
            "sft": builder or SftSampleBuilder(),
            "preference": PreferenceSampleBuilder(),
            "evaluation": EvaluationSampleBuilder(),
        }
        self.timeout = build_timeout_seconds

    async def run_once(self):
        now = datetime.now(timezone.utc).isoformat()
        await sample_build_worker.AnalysisJobRepo.recover_expired_jobs(now=now)
        job = await sample_build_worker.AnalysisJobRepo.claim_next_dataset_sample_build_job(
            now=now
        )
        if job is None:
            return None
        return await sample_build_worker.execute_dataset_sample_build_job(
            job, builders=self.builders, build_timeout_seconds=self.timeout
        )


async def update_case_source_fixture(
    repository, result, *, context_snapshot, now, source_signal_ids=(), replace_correction=False
):
    """Change the upstream Case source to exercise sample invalidation, not replay a completed worker."""
    from sqlalchemy import select
    from infra.persistence import database
    from infra.persistence.postgres.models.feedback import FeedbackCaseRow
    from repositories.feedback_case_repository import _merge_context_snapshot
    from repositories.feedback_dataset_sample_repository import enqueue_case_samples
    from datetime import datetime

    async with database.AsyncSessionLocal() as db, db.begin():
        row = await db.scalar(
            select(FeedbackCaseRow)
            .where(
                FeedbackCaseRow.session_id == result.session_id,
                FeedbackCaseRow.anchor_message_id == result.anchor_message_id,
            )
            .with_for_update()
        )
        assert row is not None
        row.context_snapshot = _merge_context_snapshot(
            row.context_snapshot, context_snapshot, replace_correction=replace_correction
        )
        row.updated_at = datetime.fromisoformat(now)
        await enqueue_case_samples(db, row, now=row.updated_at)
        case_id = row.case_id
    return await repository.read_case(case_id)
