"""PostgreSQL ORM model registry."""

from infra.persistence.postgres.models.auth import AuthSession, AuthUser
from infra.persistence.postgres.models.task import Task, TaskStage
from infra.persistence.postgres.models.chat import (
    ChatMessageRow,
    ChatSessionRow,
    ChatToolCallRow,
    ChatToolResultRow,
)
from infra.persistence.postgres.models.collection import Collection
from infra.persistence.postgres.models.document import Document
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
    ObjectiveDiscoveryRecord,
    ObjectiveEvidenceRecord,
    ObjectiveFindingRecord,
    ObjectivePaperContributionRecord,
    ObjectiveResearchRecord,
)
from infra.persistence.postgres.models.objective_workspace import ObjectiveExperimentPlan
from infra.persistence.postgres.models.source import (
    SourceBlock,
    SourceBlockTextUnit,
    SourceDocument,
    SourceFigure,
    SourceReferenceCandidate,
    SourceReferenceEntry,
    SourceReferenceMention,
    SourceReferenceResolution,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
)
__all__ = [
    "AuthSession",
    "AuthUser",
    "ChatMessageRow",
    "ChatSessionRow",
    "ChatToolCallRow",
    "ChatToolResultRow",
    "Collection",
    "Document",
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
    "ObjectiveDiscoveryRecord",
    "ObjectiveExperimentPlan",
    "ObjectiveEvidenceRecord",
    "ObjectiveFindingRecord",
    "ObjectivePaperContributionRecord",
    "ObjectiveResearchRecord",
    "PaperMapRow",
    "SourceBlock",
    "SourceBlockTextUnit",
    "SourceDocument",
    "SourceFigure",
    "SourceReferenceCandidate",
    "SourceReferenceEntry",
    "SourceReferenceMention",
    "SourceReferenceResolution",
    "SourceTable",
    "SourceTableCell",
    "SourceTableRow",
    "SourceTextUnit",
    "Task",
    "TaskStage",
]
