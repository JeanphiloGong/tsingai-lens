"""PostgreSQL ORM model registry."""

from infra.persistence.postgres.models.auth import AuthSession, AuthUser
from infra.persistence.postgres.models.pipeline_run import PipelineRunRow
from infra.persistence.postgres.models.chat import (
    ChatMessageRow,
    ChatSessionRow,
    ChatToolCallRow,
    ChatToolResultRow,
)
from infra.persistence.postgres.models.collection import Collection
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.document_source import DocumentSource
from infra.persistence.postgres.models.document_profile import DocumentProfileRow
from infra.persistence.postgres.models.evaluation import (
    EvaluationFailureRecord,
    EvaluationGoldItemRecord,
    EvaluationGoldSetRecord,
    EvaluationPredictionItemRecord,
    EvaluationPredictionSnapshotRecord,
    EvaluationRunRecord,
    EvaluationScoreRecord,
    FindingCurationRecord,
    FindingFeedbackRecord,
)
from infra.persistence.postgres.models.paper_map import PaperMapRow
from infra.persistence.postgres.models.objective import (
    ObjectiveAnalysisRecord,
    ObjectiveDocumentEvidenceRecord,
    ObjectiveDiscoveryRecord,
    ObjectiveEvidenceRecord,
    ObjectiveFindingRecord,
    ObjectivePaperContributionRecord,
    ObjectiveResearchRecord,
)
from infra.persistence.postgres.models.objective_workspace import ObjectiveExperimentPlan
__all__ = [
    "AuthSession",
    "AuthUser",
    "ChatMessageRow",
    "ChatSessionRow",
    "ChatToolCallRow",
    "ChatToolResultRow",
    "Collection",
    "Document",
    "DocumentSource",
    "DocumentProfileRow",
    "EvaluationFailureRecord",
    "EvaluationGoldItemRecord",
    "EvaluationGoldSetRecord",
    "EvaluationPredictionItemRecord",
    "EvaluationPredictionSnapshotRecord",
    "EvaluationRunRecord",
    "EvaluationScoreRecord",
    "FindingCurationRecord",
    "FindingFeedbackRecord",
    "ObjectiveAnalysisRecord",
    "ObjectiveDocumentEvidenceRecord",
    "ObjectiveDiscoveryRecord",
    "ObjectiveExperimentPlan",
    "ObjectiveEvidenceRecord",
    "ObjectiveFindingRecord",
    "ObjectivePaperContributionRecord",
    "ObjectiveResearchRecord",
    "PaperMapRow",
    "PipelineRunRow",
]
