"""Domain objects for the feedback analysis workbench."""

from domain.feedback.analysis_job import AnalysisJob, AnalysisJobStatus
from domain.feedback.analysis_result import (
    AnalysisResult,
    FeedbackProblemType,
)
from domain.feedback.correction_signal import (
    CORRECTION_SIGNAL_JOB_TYPE,
    CORRECTION_SIGNAL_PAYLOAD_VERSION,
    CORRECTION_SIGNAL_TYPE,
    CorrectionSignal,
    CorrectionSignalAnalysisResult,
    correction_signal_id,
    correction_signal_idempotency_key,
    is_correction_challenge,
)
from domain.feedback.tool_failure import (
    TOOL_FAILURE_JOB_TYPE,
    TOOL_FAILURE_PAYLOAD_VERSION,
    TOOL_FAILURE_SIGNAL_TYPE,
    ToolFailureAnalysisResult,
    ToolFailureSignal,
    tool_failure_idempotency_key,
    tool_failure_signal_id,
    tool_result_digest,
)
from domain.feedback.evidence_coverage import EvidenceCoverage
from domain.feedback.feedback_case import FeedbackCase, FeedbackCaseStatus
from domain.feedback.annotation import AnnotationSeverity, DatasetUse, FeedbackAnnotation
from domain.feedback.review_decision import ReviewDecision, ReviewDecisionValue
from domain.feedback.dataset_snapshot import DatasetSnapshot, DatasetType
from domain.feedback.dataset import DATASET_TASK_TYPES, Dataset, DatasetTaskType
from domain.feedback.dataset_sample import (
    DATASET_SAMPLE_BUILD_JOB_TYPE,
    DATASET_SAMPLE_BUILD_PAYLOAD_VERSION,
    DatasetSample,
    DatasetSampleStatus,
    build_job_payload,
    sample_build_idempotency_key,
    source_digest_for_case,
)
from domain.feedback.sample_revision import (
    RevisionAuthorKind,
    RevisionContent,
    SFT_SCHEMA_VERSION,
    SampleRevision,
    SftRevisionContent,
    content_digest_for,
    parse_revision_content,
)

__all__ = [
    "AnalysisJob",
    "AnalysisJobStatus",
    "AnalysisResult",
    "CorrectionSignal",
    "CorrectionSignalAnalysisResult",
    "CORRECTION_SIGNAL_JOB_TYPE",
    "CORRECTION_SIGNAL_PAYLOAD_VERSION",
    "CORRECTION_SIGNAL_TYPE",
    "correction_signal_id",
    "correction_signal_idempotency_key",
    "is_correction_challenge",
    "TOOL_FAILURE_JOB_TYPE",
    "TOOL_FAILURE_PAYLOAD_VERSION",
    "TOOL_FAILURE_SIGNAL_TYPE",
    "ToolFailureAnalysisResult",
    "ToolFailureSignal",
    "tool_failure_idempotency_key",
    "tool_failure_signal_id",
    "tool_result_digest",
    "EvidenceCoverage",
    "FeedbackCase",
    "FeedbackCaseStatus",
    "FeedbackProblemType",
    "FeedbackAnnotation",
    "AnnotationSeverity",
    "DatasetUse",
    "ReviewDecision",
    "ReviewDecisionValue",
    "DatasetSnapshot",
    "DatasetType",
    "DATASET_TASK_TYPES",
    "Dataset",
    "DatasetTaskType",
    "DATASET_SAMPLE_BUILD_JOB_TYPE",
    "DATASET_SAMPLE_BUILD_PAYLOAD_VERSION",
    "DatasetSample",
    "DatasetSampleStatus",
    "build_job_payload",
    "sample_build_idempotency_key",
    "source_digest_for_case",
    "RevisionAuthorKind",
    "RevisionContent",
    "SFT_SCHEMA_VERSION",
    "SampleRevision",
    "SftRevisionContent",
    "content_digest_for",
    "parse_revision_content",
]
