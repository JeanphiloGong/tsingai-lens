"""Goal conversation domain records."""

from domain.goal.experiment_plan import (
    EXPERIMENT_PLAN_STATUSES,
    ExperimentPlanRecord,
    ExperimentPlanStatus,
    normalize_experiment_plan_status,
)
from domain.goal.session import (
    ANSWER_MODES,
    MESSAGE_ROLES,
    SOURCE_LINK_KINDS,
    SOURCE_MODES,
    GoalAnswerMode,
    GoalMessageRecord,
    GoalMessageRole,
    GoalSessionRecord,
    GoalSourceLink,
    GoalSourceLinkKind,
    GoalSourceMode,
    normalize_answer_mode,
    normalize_message_role,
    normalize_source_link_kind,
    normalize_source_mode,
)

__all__ = [
    "ANSWER_MODES",
    "EXPERIMENT_PLAN_STATUSES",
    "ExperimentPlanRecord",
    "ExperimentPlanStatus",
    "GoalAnswerMode",
    "GoalMessageRecord",
    "GoalMessageRole",
    "GoalSessionRecord",
    "GoalSourceLink",
    "GoalSourceLinkKind",
    "GoalSourceMode",
    "MESSAGE_ROLES",
    "SOURCE_LINK_KINDS",
    "SOURCE_MODES",
    "normalize_answer_mode",
    "normalize_experiment_plan_status",
    "normalize_message_role",
    "normalize_source_link_kind",
    "normalize_source_mode",
]
