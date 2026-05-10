"""Goal conversation domain records."""

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
    "normalize_message_role",
    "normalize_source_link_kind",
    "normalize_source_mode",
]
