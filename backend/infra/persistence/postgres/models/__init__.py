"""PostgreSQL ORM model registry."""

from infra.persistence.postgres.models.model_connection import ModelConnectionAuditORM, ModelConnectionORM
from infra.persistence.postgres.models.execution import (
    PipelineRunORM,
    AnalysisJobORM,
)
from infra.persistence.postgres.models.chat import (
    AgentOperationORM,
    AgentTaskORM,
    AgentTaskStepORM,
    ChatToolCallORM,
)
from infra.persistence.postgres.models.chat import ChatModelCallORM
from infra.persistence.postgres.models.conversation import (
    ConversationORM,
    MessageFeedbackORM,
    MessageORM,
)
# Historical Feedback analysis mappings remain registered for Alembic metadata
# and migration inspection. Runtime rating reads and writes use MessageFeedbackORM.
from infra.persistence.postgres.models.feedback import FeedbackAnalysisResultORM, FeedbackSignalAnalysisResultORM, ToolFailureAnalysisResultORM, FeedbackAnnotationORM, FeedbackCaseORM, FeedbackReviewDecisionORM, FeedbackDatasetSnapshotORM
from infra.persistence.postgres.models.feedback_dataset import (
    FeedbackDatasetORM,
    FeedbackDatasetSampleORM,
    FeedbackSampleRevisionORM,
    FeedbackSampleActionORM,
    FeedbackDatasetExportPreviewORM,
    FeedbackDatasetExportORM,
    FeedbackDatasetExportMemberORM,
    FeedbackDatasetMigrationRunORM,
)
from infra.persistence.postgres.models.workspace import (
    WorkspaceORM,
    DocumentORM,
    DocumentPreparationORM,
)
from infra.persistence.postgres.models.evaluation import EvaluationGoldSetORM, EvaluationPredictionSnapshotORM, EvaluationRunORM
from infra.persistence.postgres.models.finding import (
    FindingCurationORM,
    FindingFeedbackORM,
    ExperimentFindingORM,
    FindingComparisonGroupORM,
    FindingSelectionORM,
)
from infra.persistence.postgres.models.objective import (
    ObjectiveAnalysisLegacyCheckpointORM,
    ObjectiveAnalysisORM,
    ObjectiveResearchORM,
    ObjectiveExperimentPlanORM,
    ObjectiveExperimentSelectionORM,
    SelectionComparisonORM,
    SelectionMeasurementORM,
    ComparisonGroupMemberORM,
    ComparisonGroupORM,
)
from infra.persistence.postgres.models.paper_experiment import (
    ExperimentComparisonMeasurementORM,
    ExperimentComparisonORM,
    ExperimentMeasurementResultORM,
    ExperimentTestConditionORM,
    ExperimentalVariantORM,
    PaperExperimentORM,
    ReportedInterpretationORM,
)
__all__ = [
    "ModelConnectionORM",
    "ModelConnectionAuditORM",
    "AnalysisJobORM",
    "ChatModelCallORM",
    "AgentOperationORM",
    "MessageORM",
    "MessageFeedbackORM",
    "ConversationORM",
    "AgentTaskORM",
    "AgentTaskStepORM",
    "ChatToolCallORM",
    "WorkspaceORM",
    "ComparisonGroupMemberORM",
    "ComparisonGroupORM",
    "ExperimentFindingORM",
    "FindingComparisonGroupORM",
    "FindingSelectionORM",
    "DocumentORM",
    "DocumentPreparationORM",
    "EvaluationGoldSetORM",
    "EvaluationPredictionSnapshotORM",
    "EvaluationRunORM",
    "ExperimentComparisonMeasurementORM",
    "ExperimentComparisonORM",
    "ExperimentMeasurementResultORM",
    "ExperimentTestConditionORM",
    "ExperimentalVariantORM",
    "FeedbackAnalysisResultORM",
    "FeedbackSignalAnalysisResultORM",
    "ToolFailureAnalysisResultORM",
    "FeedbackAnnotationORM",
    "FeedbackCaseORM",
    "FeedbackReviewDecisionORM",
    "FeedbackDatasetSnapshotORM",
    "FeedbackDatasetORM",
    "FeedbackDatasetSampleORM",
    "FeedbackSampleRevisionORM",
    "FeedbackSampleActionORM",
    "FeedbackDatasetExportPreviewORM",
    "FeedbackDatasetExportORM",
    "FeedbackDatasetExportMemberORM",
    "FeedbackDatasetMigrationRunORM",
    "FindingCurationORM",
    "FindingFeedbackORM",
    "ObjectiveAnalysisORM",
    "ObjectiveAnalysisLegacyCheckpointORM",
    "ObjectiveExperimentSelectionORM",
    "ObjectiveExperimentPlanORM",
    "ObjectiveResearchORM",
    "PaperExperimentORM",
    "PipelineRunORM",
    "ReportedInterpretationORM",
    "SelectionComparisonORM",
    "SelectionMeasurementORM",
]
