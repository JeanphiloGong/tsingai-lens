from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping


GoalAnswerMode = Literal["grounded", "hybrid", "general"]
GoalMessageRole = Literal["user", "assistant"]
GoalSourceLinkKind = Literal["document", "evidence"]
GoalSourceMode = Literal[
    "collection_grounded",
    "collection_limited",
    "general_fallback",
    "general_only",
]

ANSWER_MODES = {"grounded", "hybrid", "general"}
MESSAGE_ROLES = {"user", "assistant"}
SOURCE_LINK_KINDS = {"document", "evidence"}
SOURCE_MODES = {
    "collection_grounded",
    "collection_limited",
    "general_fallback",
    "general_only",
}


@dataclass(frozen=True)
class GoalSourceLink:
    kind: GoalSourceLinkKind
    label: str
    href: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "GoalSourceLink":
        kind = normalize_source_link_kind(payload.get("kind"))
        label = _normalize_required_text(payload.get("label"), "source link label")
        href = _normalize_required_text(payload.get("href"), "source link href")
        return cls(kind=kind, label=label, href=href)

    def to_record(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "label": self.label,
            "href": self.href,
        }


@dataclass(frozen=True)
class GoalMessageRecord:
    message_id: str
    session_id: str
    role: GoalMessageRole
    content: str
    created_at: str
    source_mode: GoalSourceMode | None = None
    used_evidence_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    links: Mapping[str, str] | None = None
    source_links: tuple[GoalSourceLink, ...] = ()

    @classmethod
    def user(
        cls,
        *,
        message_id: str,
        session_id: str,
        content: str,
        created_at: str,
    ) -> "GoalMessageRecord":
        return cls(
            message_id=_normalize_required_text(message_id, "message_id"),
            session_id=_normalize_required_text(session_id, "session_id"),
            role="user",
            content=_normalize_required_text(content, "content"),
            created_at=str(created_at),
        )

    @classmethod
    def assistant(
        cls,
        *,
        message_id: str,
        session_id: str,
        content: str,
        source_mode: Any,
        created_at: str,
        used_evidence_ids: Any = None,
        warnings: Any = None,
        links: Mapping[str, Any] | None = None,
        source_links: Any = None,
    ) -> "GoalMessageRecord":
        normalized_source_mode = normalize_source_mode(source_mode)
        evidence_ids = _stable_strings(used_evidence_ids)
        public_source_links = _normalize_source_links(source_links)
        if normalized_source_mode != "collection_grounded":
            evidence_ids = ()
            public_source_links = ()
        return cls(
            message_id=_normalize_required_text(message_id, "message_id"),
            session_id=_normalize_required_text(session_id, "session_id"),
            role="assistant",
            content=_normalize_required_text(content, "content"),
            source_mode=normalized_source_mode,
            used_evidence_ids=evidence_ids,
            warnings=_stable_strings(warnings),
            links=_normalize_string_mapping(links),
            source_links=public_source_links,
            created_at=str(created_at),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "GoalMessageRecord":
        role = normalize_message_role(payload.get("role"))
        if role == "assistant":
            return cls.assistant(
                message_id=payload.get("message_id"),
                session_id=payload.get("session_id"),
                content=payload.get("answer") or payload.get("content"),
                source_mode=payload.get("source_mode") or "collection_limited",
                used_evidence_ids=payload.get("used_evidence_ids"),
                warnings=payload.get("warnings"),
                links=payload.get("links"),
                source_links=payload.get("source_links"),
                created_at=payload.get("created_at") or "",
            )
        return cls.user(
            message_id=payload.get("message_id"),
            session_id=payload.get("session_id"),
            content=payload.get("content"),
            created_at=payload.get("created_at") or "",
        )

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
        }
        if self.role == "assistant":
            record.update(
                {
                    "answer": self.content,
                    "source_mode": self.source_mode,
                    "used_evidence_ids": list(self.used_evidence_ids),
                    "warnings": list(self.warnings),
                    "links": dict(self.links or {}),
                    "source_links": [
                        source_link.to_record() for source_link in self.source_links
                    ],
                }
            )
        return record


@dataclass(frozen=True)
class GoalSessionRecord:
    session_id: str
    user_id: str
    collection_id: str
    focused_material_id: str | None
    focused_paper_id: str | None
    goal_text: str | None
    goal_brief_json: Mapping[str, Any]
    answer_mode: GoalAnswerMode
    rolling_summary: str
    last_evidence_ids: tuple[str, ...]
    last_material_ids: tuple[str, ...]
    last_paper_ids: tuple[str, ...]
    collection_data_version: str | None
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        user_id: str,
        collection_id: str,
        focused_material_id: Any = None,
        focused_paper_id: Any = None,
        goal_text: Any = None,
        goal_brief_json: Mapping[str, Any] | None = None,
        answer_mode: Any = "hybrid",
        collection_data_version: Any = None,
        now_iso: str,
    ) -> "GoalSessionRecord":
        return cls(
            session_id=_normalize_required_text(session_id, "session_id"),
            user_id=_normalize_required_text(user_id, "user_id"),
            collection_id=_normalize_required_text(collection_id, "collection_id"),
            focused_material_id=_normalize_optional_text(focused_material_id),
            focused_paper_id=_normalize_optional_text(focused_paper_id),
            goal_text=_normalize_optional_text(goal_text),
            goal_brief_json=dict(goal_brief_json or {}),
            answer_mode=normalize_answer_mode(answer_mode),
            rolling_summary="",
            last_evidence_ids=(),
            last_material_ids=(),
            last_paper_ids=(),
            collection_data_version=_normalize_optional_text(collection_data_version),
            created_at=str(now_iso),
            updated_at=str(now_iso),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "GoalSessionRecord":
        return cls(
            session_id=_normalize_required_text(
                payload.get("session_id"), "session_id"
            ),
            user_id=_normalize_required_text(payload.get("user_id"), "user_id"),
            collection_id=_normalize_required_text(
                payload.get("collection_id"), "collection_id"
            ),
            focused_material_id=_normalize_optional_text(
                payload.get("focused_material_id")
            ),
            focused_paper_id=_normalize_optional_text(payload.get("focused_paper_id")),
            goal_text=_normalize_optional_text(payload.get("goal_text")),
            goal_brief_json=_normalize_mapping(payload.get("goal_brief_json")),
            answer_mode=normalize_answer_mode(payload.get("answer_mode")),
            rolling_summary=str(payload.get("rolling_summary") or ""),
            last_evidence_ids=_stable_strings(payload.get("last_evidence_ids")),
            last_material_ids=_stable_strings(payload.get("last_material_ids")),
            last_paper_ids=_stable_strings(payload.get("last_paper_ids")),
            collection_data_version=_normalize_optional_text(
                payload.get("collection_data_version")
            ),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )

    def bind_collection(
        self,
        collection_id: Any,
        *,
        clear_focus: bool = False,
    ) -> "GoalSessionRecord":
        next_record = replace(
            self,
            collection_id=_normalize_required_text(collection_id, "collection_id"),
        )
        if clear_focus:
            next_record = replace(
                next_record,
                focused_material_id=None,
                focused_paper_id=None,
            )
        return next_record

    def with_page_context(
        self,
        *,
        material_id: Any = None,
        paper_id: Any = None,
    ) -> "GoalSessionRecord":
        next_record = self
        material_text = _normalize_optional_text(material_id)
        if material_text:
            next_record = replace(next_record, focused_material_id=material_text)
        paper_text = _normalize_optional_text(paper_id)
        if paper_text:
            next_record = replace(next_record, focused_paper_id=paper_text)
        return next_record

    def with_focus(
        self,
        *,
        focused_material_id: Any,
        focused_paper_id: Any,
    ) -> "GoalSessionRecord":
        return replace(
            self,
            focused_material_id=_normalize_optional_text(focused_material_id),
            focused_paper_id=_normalize_optional_text(focused_paper_id),
        )

    def with_goal_text(self, goal_text: Any) -> "GoalSessionRecord":
        return replace(self, goal_text=_normalize_optional_text(goal_text))

    def with_goal_brief_json(self, goal_brief_json: Any) -> "GoalSessionRecord":
        return replace(
            self,
            goal_brief_json=_normalize_mapping(goal_brief_json),
        )

    def with_answer_mode(self, answer_mode: Any) -> "GoalSessionRecord":
        return replace(self, answer_mode=normalize_answer_mode(answer_mode))

    def with_collection_data_version(
        self,
        *,
        collection_data_version: Any,
        updated_at: str,
    ) -> "GoalSessionRecord":
        return replace(
            self,
            collection_data_version=_normalize_optional_text(collection_data_version),
            updated_at=str(updated_at),
        )

    def after_assistant_message(
        self,
        *,
        user_message: str,
        assistant_message: GoalMessageRecord,
        material_ids: Any,
        paper_ids: Any,
        collection_data_version: Any,
        updated_at: str,
        max_summary_chars: int,
    ) -> "GoalSessionRecord":
        summary_bits = [
            self.rolling_summary,
            (
                f"Last turn source={assistant_message.source_mode}; "
                f"user asked: {str(user_message)[:240]}"
            ),
        ]
        if assistant_message.source_mode == "general_fallback":
            summary_bits.append(
                "The previous answer used general background and is not collection evidence."
            )
        summary = "\n".join(bit for bit in summary_bits if bit).strip()
        return replace(
            self,
            last_evidence_ids=assistant_message.used_evidence_ids,
            last_material_ids=_stable_strings(material_ids),
            last_paper_ids=_stable_strings(paper_ids),
            rolling_summary=summary[-max_summary_chars:],
            collection_data_version=_normalize_optional_text(collection_data_version),
            updated_at=str(updated_at),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "collection_id": self.collection_id,
            "focused_material_id": self.focused_material_id,
            "focused_paper_id": self.focused_paper_id,
            "goal_text": self.goal_text,
            "goal_brief_json": dict(self.goal_brief_json),
            "answer_mode": self.answer_mode,
            "rolling_summary": self.rolling_summary,
            "last_evidence_ids": list(self.last_evidence_ids),
            "last_material_ids": list(self.last_material_ids),
            "last_paper_ids": list(self.last_paper_ids),
            "collection_data_version": self.collection_data_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def normalize_answer_mode(value: Any) -> GoalAnswerMode:
    mode = str(value or "hybrid").strip().lower()
    if mode not in ANSWER_MODES:
        raise ValueError("answer_mode must be one of: grounded, hybrid, general")
    return mode  # type: ignore[return-value]


def normalize_message_role(value: Any) -> GoalMessageRole:
    role = str(value or "").strip().lower()
    if role not in MESSAGE_ROLES:
        raise ValueError("message role must be one of: user, assistant")
    return role  # type: ignore[return-value]


def normalize_source_link_kind(value: Any) -> GoalSourceLinkKind:
    kind = str(value or "").strip().lower()
    if kind not in SOURCE_LINK_KINDS:
        raise ValueError("source link kind must be one of: document, evidence")
    return kind  # type: ignore[return-value]


def normalize_source_mode(value: Any) -> GoalSourceMode:
    source_mode = str(value or "").strip().lower()
    if source_mode not in SOURCE_MODES:
        raise ValueError(
            "source_mode must be one of: collection_grounded, collection_limited, "
            "general_fallback, general_only"
        )
    return source_mode  # type: ignore[return-value]


def _normalize_required_text(value: Any, field_name: str) -> str:
    text = _normalize_optional_text(value)
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _normalize_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _normalize_string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if _normalize_optional_text(key) and _normalize_optional_text(item)
    }


def _normalize_source_links(value: Any) -> tuple[GoalSourceLink, ...]:
    if not isinstance(value, list):
        return ()
    links: list[GoalSourceLink] = []
    seen_hrefs: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            continue
        source_link = GoalSourceLink.from_mapping(item)
        if source_link.href in seen_hrefs:
            continue
        seen_hrefs.add(source_link.href)
        links.append(source_link)
    return tuple(links)


def _stable_strings(values: Any) -> tuple[str, ...]:
    result: list[str] = []
    if not isinstance(values, list | tuple):
        return ()
    for value in values:
        text = _normalize_optional_text(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)


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
