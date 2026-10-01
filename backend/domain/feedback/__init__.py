"""Domain objects for the feedback analysis workbench."""

from domain.feedback.analysis_result import AnalysisResult, FeedbackProblemType
from domain.feedback.annotation import (
    AnnotationSeverity,
    DatasetUse,
    FeedbackAnnotation,
)
from domain.feedback.correction_signal import (
    CORRECTION_SIGNAL_TYPE,
    CorrectionSignal,
    CorrectionSignalAnalysisResult,
    correction_signal_id,
    is_correction_challenge,
)
from domain.feedback.dataset import DATASET_TASK_TYPES, Dataset, DatasetTaskType
from domain.feedback.dataset_export import (
    EXPORT_SCHEMA_VERSION,
    DatasetExport,
    ExportFormat,
    ExportIssue,
    ExportMember,
    ExportPreview,
    content_digest_for_rows,
    digest_for_value,
    jsonl_bytes_for_rows,
    member_digest,
    provenance_digest_for_rows,
)
from domain.feedback.dataset_sample import DatasetSample, DatasetSampleStatus
from domain.feedback.dataset_snapshot import DatasetSnapshot, DatasetType
from domain.feedback.evidence_coverage import EvidenceCoverage
from domain.feedback.feedback_case import FeedbackCase, FeedbackCaseStatus
from domain.feedback.review_decision import ReviewDecision, ReviewDecisionValue
from domain.feedback.sample_revision import (
    EVALUATION_SCHEMA_VERSION,
    PREFERENCE_SCHEMA_VERSION,
    SFT_SCHEMA_VERSION,
    EvaluationRevisionContent,
    PreferenceRevisionContent,
    RevisionAuthorKind,
    RevisionContent,
    SampleRevision,
    SftRevisionContent,
    content_digest_for,
    parse_revision_content,
)
from domain.feedback.tool_failure import (
    TOOL_FAILURE_SIGNAL_TYPE,
    ToolFailureAnalysisResult,
    ToolFailureSignal,
    tool_failure_signal_id,
    tool_result_digest,
)

__all__ = [
    "AnalysisResult",
    "CorrectionSignal",
    "CorrectionSignalAnalysisResult",
    "CORRECTION_SIGNAL_TYPE",
    "correction_signal_id",
    "is_correction_challenge",
    "TOOL_FAILURE_SIGNAL_TYPE",
    "ToolFailureAnalysisResult",
    "ToolFailureSignal",
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
    "DatasetSample",
    "DatasetSampleStatus",
    "RevisionAuthorKind",
    "RevisionContent",
    "SFT_SCHEMA_VERSION",
    "PREFERENCE_SCHEMA_VERSION",
    "EVALUATION_SCHEMA_VERSION",
    "EvaluationRevisionContent",
    "PreferenceRevisionContent",
    "SampleRevision",
    "SftRevisionContent",
    "content_digest_for",
    "parse_revision_content",
    "EXPORT_SCHEMA_VERSION",
    "DatasetExport",
    "ExportFormat",
    "ExportIssue",
    "ExportMember",
    "ExportPreview",
    "content_digest_for_rows",
    "digest_for_value",
    "jsonl_bytes_for_rows",
    "member_digest",
    "provenance_digest_for_rows",
]
