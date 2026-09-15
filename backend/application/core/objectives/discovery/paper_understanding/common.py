from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

PAPER_RESEARCH_MAP_WARNING_LIMIT = (2, 240)
PAPER_RESEARCH_MAP_SCOPE_LIMIT = 4
PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT = 6
# A bounded paper-map window can legitimately mention more than eight distinct
# variables/outcomes. Keep the map lightweight, but do not turn a valid scope
# response into a JSON failure merely because one batch contains nine or ten
# unresolved signals. Contextual rereading remains bounded per document.
PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT = 12

_STUDY_CONTEXT_LIMIT = 12
_STUDY_CONTEXT_VALUE_CHARS = 160
_VARIED_FACTOR_LIMIT = 12
_PAPER_MAP_STUDY_LIMIT = 2
_PAPER_MAP_CONTEXT_LIMIT = 4
_PAPER_MAP_VARIED_FACTOR_LIMIT = 6
_REVIEW_KNOWLEDGE_ITEM_LIMIT = 2
_REVIEW_CITATION_LEAD_LIMIT = 3


def _normalize_list(value: object) -> object:
    return [] if value is None else value


def _normalize_warnings(value: object) -> object:
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    normalized: list[object] = []
    for item in value[: PAPER_RESEARCH_MAP_WARNING_LIMIT[0]]:
        if not isinstance(item, str):
            normalized.append(item)
            continue
        text = item.strip()
        if text:
            normalized.append(text[: PAPER_RESEARCH_MAP_WARNING_LIMIT[1]])
    return normalized


def _bounded_unique_items(
    value: object,
    *,
    limit: int,
    path: str,
    overflows: list[str],
) -> object:
    if not isinstance(value, list):
        return value
    unique: list[object] = []
    identities: set[str] = set()
    for item in value:
        try:
            identity = json.dumps(
                item,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            identity = repr(item)
        if identity in identities:
            continue
        identities.add(identity)
        unique.append(item)
    if len(unique) > limit:
        overflows.append(f"{path} omitted {len(unique) - limit}")
    return unique[:limit]


def _bounded_mapping_list(
    payload: dict[str, Any],
    field_name: str,
    *,
    limit: int,
    path: str,
    overflows: list[str],
) -> list[object]:
    bounded = _bounded_unique_items(
        payload.get(field_name),
        limit=limit,
        path=path,
        overflows=overflows,
    )
    if isinstance(bounded, list):
        payload[field_name] = bounded
        return bounded
    return []


def _mark_bounded_output(
    payload: dict[str, Any],
    *,
    overflows: list[str],
) -> dict[str, Any]:
    if not overflows:
        return payload
    omitted_by_field: dict[str, int] = {}
    for overflow in overflows:
        path, _, count_text = overflow.rpartition(" omitted ")
        field_name = path.rsplit(".", 1)[-1].split("[", 1)[0]
        omitted_by_field[field_name] = omitted_by_field.get(field_name, 0) + int(
            count_text
        )
    overflow_summary = ", ".join(
        f"{field_name}={omitted_by_field[field_name]}"
        for field_name in sorted(omitted_by_field)
    )
    warning = (
        "Backend bounded list overflow; omitted item counts: "
        + overflow_summary
        + ". Retained source-grounded items within the paper-map contract."
    )[: PAPER_RESEARCH_MAP_WARNING_LIMIT[1]]
    existing_warnings = (
        payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    )
    payload["warnings"] = [warning, *existing_warnings][
        : PAPER_RESEARCH_MAP_WARNING_LIMIT[0]
    ]
    payload["output_saturated"] = True
    return payload


class _PaperResearchMapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("confidence", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_confidence(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["confidence"].get_default(call_default_factory=True)
