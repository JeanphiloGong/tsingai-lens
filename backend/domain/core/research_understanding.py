from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import math
from typing import Any, Final, Mapping


UNDERSTANDING_SCHEMA_VERSION: Final[str] = "research_understanding.v1"
UNDERSTANDING_STATES: Final[frozenset[str]] = frozenset(
    {"empty", "partial", "ready", "limited"}
)
CLAIM_STATUSES: Final[frozenset[str]] = frozenset(
    {"supported", "limited", "conflicted", "unsupported"}
)
CLAIM_TYPES: Final[frozenset[str]] = frozenset(
    {"finding", "measurement", "comparison", "mechanism", "limitation", "context"}
)
RELATION_TYPES: Final[frozenset[str]] = frozenset(
    {"improves", "reduces", "increases", "decreases", "correlates", "explains", "conflicts", "compares"}
)


@dataclass(frozen=True)
class ResearchUnderstandingScope:
    scope_type: str
    collection_id: str
    goal_id: str | None = None
    material_id: str | None = None
    objective_id: str | None = None
    document_id: str | None = None
    title: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchUnderstandingScope":
        return cls(
            scope_type=_text(payload.get("scope_type")) or "collection",
            collection_id=_text(payload.get("collection_id")) or "",
            goal_id=_text(payload.get("goal_id")),
            material_id=_text(payload.get("material_id")),
            objective_id=_text(payload.get("objective_id")),
            document_id=_text(payload.get("document_id")),
            title=_text(payload.get("title")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "scope_type": self.scope_type,
            "collection_id": self.collection_id,
            "goal_id": self.goal_id,
            "material_id": self.material_id,
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "title": self.title,
        }


@dataclass(frozen=True)
class ResearchEvidenceRef:
    evidence_ref_id: str
    source_kind: str
    document_id: str | None
    label: str
    locator: dict[str, Any]
    fact_ids: tuple[str, ...]
    anchor_ids: tuple[str, ...]
    confidence: float | None
    traceability_status: str
    quote: str | None = None
    href: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchEvidenceRef":
        evidence_ref_id = _text(payload.get("evidence_ref_id")) or _stable_id(
            "evref",
            payload.get("source_kind"),
            payload.get("document_id"),
            payload.get("locator"),
            payload.get("fact_ids"),
            payload.get("anchor_ids"),
        )
        return cls(
            evidence_ref_id=evidence_ref_id,
            source_kind=_text(payload.get("source_kind")) or "unknown",
            document_id=_text(payload.get("document_id")),
            label=_text(payload.get("label")) or evidence_ref_id,
            locator=_mapping(payload.get("locator")),
            fact_ids=_strings(payload.get("fact_ids")),
            anchor_ids=_strings(payload.get("anchor_ids")),
            confidence=_confidence_or_none(payload.get("confidence")),
            traceability_status=_text(payload.get("traceability_status")) or "unknown",
            quote=_text(payload.get("quote")),
            href=_text(payload.get("href")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "evidence_ref_id": self.evidence_ref_id,
            "source_kind": self.source_kind,
            "document_id": self.document_id,
            "label": self.label,
            "locator": dict(self.locator),
            "fact_ids": list(self.fact_ids),
            "anchor_ids": list(self.anchor_ids),
            "confidence": self.confidence,
            "traceability_status": self.traceability_status,
            "quote": self.quote,
            "href": self.href,
        }


@dataclass(frozen=True)
class ResearchContext:
    context_id: str
    label: str
    material_scope: tuple[str, ...]
    process_context: dict[str, Any]
    test_condition: dict[str, Any]
    property_scope: tuple[str, ...]
    limitations: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchContext":
        context_id = _text(payload.get("context_id")) or _stable_id(
            "ctx",
            payload.get("label"),
            payload.get("material_scope"),
            payload.get("process_context"),
            payload.get("test_condition"),
            payload.get("property_scope"),
        )
        return cls(
            context_id=context_id,
            label=_text(payload.get("label")) or "Context",
            material_scope=_strings(payload.get("material_scope")),
            process_context=_mapping(payload.get("process_context")),
            test_condition=_mapping(payload.get("test_condition")),
            property_scope=_strings(payload.get("property_scope")),
            limitations=_strings(payload.get("limitations")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "label": self.label,
            "material_scope": list(self.material_scope),
            "process_context": dict(self.process_context),
            "test_condition": dict(self.test_condition),
            "property_scope": list(self.property_scope),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class ResearchClaim:
    claim_id: str
    claim_type: str
    statement: str
    status: str
    confidence: float | None
    strength: str | None
    evidence_ref_ids: tuple[str, ...]
    context_ids: tuple[str, ...]
    source_object_ids: tuple[str, ...]
    warnings: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchClaim":
        statement = _text(payload.get("statement")) or _text(payload.get("claim")) or ""
        claim_type = _choice(payload.get("claim_type") or payload.get("type"), CLAIM_TYPES, "finding")
        claim_id = _text(payload.get("claim_id")) or _stable_id(
            "claim",
            claim_type,
            statement,
            payload.get("evidence_ref_ids"),
            payload.get("source_object_ids"),
        )
        return cls(
            claim_id=claim_id,
            claim_type=claim_type,
            statement=statement,
            status=_choice(payload.get("status"), CLAIM_STATUSES, "limited"),
            confidence=_confidence_or_none(payload.get("confidence")),
            strength=_text(payload.get("strength")),
            evidence_ref_ids=_strings(payload.get("evidence_ref_ids")),
            context_ids=_strings(payload.get("context_ids")),
            source_object_ids=_strings(payload.get("source_object_ids")),
            warnings=_strings(payload.get("warnings")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_type": self.claim_type,
            "statement": self.statement,
            "status": self.status,
            "confidence": self.confidence,
            "strength": self.strength,
            "evidence_ref_ids": list(self.evidence_ref_ids),
            "context_ids": list(self.context_ids),
            "source_object_ids": list(self.source_object_ids),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ResearchRelation:
    relation_id: str
    relation_type: str
    subject: str
    predicate: str
    object: str
    status: str
    confidence: float | None
    evidence_ref_ids: tuple[str, ...]
    context_ids: tuple[str, ...]
    source_object_ids: tuple[str, ...]
    warnings: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchRelation":
        relation_type = _choice(payload.get("relation_type"), RELATION_TYPES, "compares")
        subject = _text(payload.get("subject")) or ""
        predicate = _text(payload.get("predicate")) or relation_type
        object_text = _text(payload.get("object")) or ""
        relation_id = _text(payload.get("relation_id")) or _stable_id(
            "rel",
            relation_type,
            subject,
            predicate,
            object_text,
            payload.get("evidence_ref_ids"),
        )
        return cls(
            relation_id=relation_id,
            relation_type=relation_type,
            subject=subject,
            predicate=predicate,
            object=object_text,
            status=_choice(payload.get("status"), CLAIM_STATUSES, "limited"),
            confidence=_confidence_or_none(payload.get("confidence")),
            evidence_ref_ids=_strings(payload.get("evidence_ref_ids")),
            context_ids=_strings(payload.get("context_ids")),
            source_object_ids=_strings(payload.get("source_object_ids")),
            warnings=_strings(payload.get("warnings")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "relation_type": self.relation_type,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "status": self.status,
            "confidence": self.confidence,
            "evidence_ref_ids": list(self.evidence_ref_ids),
            "context_ids": list(self.context_ids),
            "source_object_ids": list(self.source_object_ids),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ResearchUnderstanding:
    schema_version: str
    state: str
    scope: ResearchUnderstandingScope
    claims: tuple[ResearchClaim, ...]
    relations: tuple[ResearchRelation, ...]
    evidence_refs: tuple[ResearchEvidenceRef, ...]
    contexts: tuple[ResearchContext, ...]
    warnings: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchUnderstanding":
        return cls(
            schema_version=_text(payload.get("schema_version")) or UNDERSTANDING_SCHEMA_VERSION,
            state=_choice(payload.get("state"), UNDERSTANDING_STATES, "empty"),
            scope=ResearchUnderstandingScope.from_mapping(_mapping(payload.get("scope"))),
            claims=tuple(
                ResearchClaim.from_mapping(item)
                for item in _mapping_list(payload.get("claims"))
            ),
            relations=tuple(
                ResearchRelation.from_mapping(item)
                for item in _mapping_list(payload.get("relations"))
            ),
            evidence_refs=tuple(
                ResearchEvidenceRef.from_mapping(item)
                for item in _mapping_list(payload.get("evidence_refs"))
            ),
            contexts=tuple(
                ResearchContext.from_mapping(item)
                for item in _mapping_list(payload.get("contexts"))
            ),
            warnings=_strings(payload.get("warnings")),
        )

    @classmethod
    def empty(
        cls,
        *,
        scope_type: str,
        collection_id: str,
        goal_id: str | None = None,
        material_id: str | None = None,
        objective_id: str | None = None,
        title: str | None = None,
        warnings: tuple[str, ...] = (),
    ) -> "ResearchUnderstanding":
        return cls.from_mapping(
            {
                "state": "empty",
                "scope": {
                    "scope_type": scope_type,
                    "collection_id": collection_id,
                    "goal_id": goal_id,
                    "material_id": material_id,
                    "objective_id": objective_id,
                    "title": title,
                },
                "warnings": list(warnings),
            }
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "scope": self.scope.to_record(),
            "claims": [claim.to_record() for claim in self.claims],
            "relations": [relation.to_record() for relation in self.relations],
            "evidence_refs": [ref.to_record() for ref in self.evidence_refs],
            "contexts": [context.to_record() for context in self.contexts],
            "warnings": list(self.warnings),
            "summary": {
                "claim_count": len(self.claims),
                "relation_count": len(self.relations),
                "evidence_ref_count": len(self.evidence_refs),
                "context_count": len(self.contexts),
            },
        }

    @property
    def scope_id(self) -> str:
        if self.scope.scope_type == "goal" and self.scope.goal_id:
            return self.scope.goal_id
        if self.scope.scope_type == "objective" and self.scope.objective_id:
            return self.scope.objective_id
        if self.scope.scope_type == "material" and self.scope.material_id:
            return self.scope.material_id
        if self.scope.scope_type == "document" and self.scope.document_id:
            return self.scope.document_id
        return self.scope.collection_id


def _stable_id(prefix: str, *parts: Any) -> str:
    text = "|".join(_stable_text(part) for part in parts if part is not None)
    digest = sha1((text or prefix).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _stable_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return "|".join(
            f"{key}:{_stable_text(value[key])}" for key in sorted(value, key=str)
        )
    if isinstance(value, (list, tuple, set)):
        return ",".join(_stable_text(item) for item in value)
    return str(value or "")


def _choice(value: Any, allowed: frozenset[str], default: str) -> str:
    normalized = (_text(value) or "").lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in allowed else default


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _confidence_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
        if math.isnan(numeric):
            return None
        return round(min(1.0, max(0.0, numeric)), 2)
    except (TypeError, ValueError):
        return None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        items = value.values()
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = (value,)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return tuple(normalized)
