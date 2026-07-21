"""Direct PostgreSQL persistence for Objective Research Understanding."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha1, sha256
import json
from typing import Any, Mapping

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from domain.core.research_understanding import ResearchUnderstanding
from infra.persistence.postgres.models.objective import ResearchObjectiveLifecycle
from infra.persistence.postgres.models.understanding import (
    ResearchClaimRecord,
    ResearchContextRecord,
    ResearchEvidenceRefRecord,
    ResearchFindingRecord,
    ResearchRelationRecord,
    ResearchUnderstandingRecord,
    research_claim_context_links,
    research_claim_evidence_links,
    research_finding_evidence_links,
    research_relation_context_links,
    research_relation_evidence_links,
)


class PostgresResearchUnderstandingRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_objective_understanding(
        self,
        collection_id: str,
        objective_id: str,
        understanding: ResearchUnderstanding,
    ) -> None:
        _require_objective_scope(collection_id, objective_id, understanding)
        payload = understanding.to_record()
        with self.session_factory.begin() as session:
            lifecycle = session.get(
                ResearchObjectiveLifecycle,
                {"collection_id": collection_id, "objective_id": objective_id},
            )
            if lifecycle is None:
                raise ValueError(
                    f"research objective not found: {collection_id}/{objective_id}"
                )
            session.execute(
                delete(ResearchUnderstandingRecord).where(
                    ResearchUnderstandingRecord.collection_id == collection_id,
                    ResearchUnderstandingRecord.objective_id == objective_id,
                )
            )
            session.flush()
            understanding_id = _understanding_id(collection_id, objective_id)
            session.add(
                ResearchUnderstandingRecord(
                    understanding_id=understanding_id,
                    collection_id=collection_id,
                    objective_id=objective_id,
                    source_build_id=lifecycle.source_build_id,
                    version=1,
                    schema_version=understanding.schema_version,
                    state=understanding.state,
                    title=understanding.scope.title,
                    content_sha256=_content_hash(payload),
                    warnings=list(understanding.warnings),
                    presentation_metadata={
                        key: value
                        for key, value in understanding.presentation.items()
                        if key not in {"findings", "review_candidates"}
                    },
                    model_traces=[dict(trace) for trace in understanding.model_traces],
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.flush()
            self._write_children(session, understanding_id, payload)

    def read_objective_understanding(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchUnderstanding | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ResearchUnderstandingRecord).where(
                    ResearchUnderstandingRecord.collection_id == collection_id,
                    ResearchUnderstandingRecord.objective_id == objective_id,
                )
            )
            return self._to_domain(session, row) if row is not None else None

    def list_objective_understandings(
        self,
        collection_id: str,
    ) -> tuple[ResearchUnderstanding, ...]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ResearchUnderstandingRecord)
                .where(ResearchUnderstandingRecord.collection_id == collection_id)
                .order_by(ResearchUnderstandingRecord.objective_id)
            )
            return tuple(self._to_domain(session, row) for row in rows)

    @staticmethod
    def _write_children(
        session: Session,
        understanding_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        evidence_refs = list(payload.get("evidence_refs") or ())
        contexts = list(payload.get("contexts") or ())
        claims = list(payload.get("claims") or ())
        relations = list(payload.get("relations") or ())
        for position, ref in enumerate(evidence_refs):
            session.add(
                ResearchEvidenceRefRecord(
                    understanding_id=understanding_id,
                    evidence_ref_id=str(ref["evidence_ref_id"]),
                    evidence_order=position,
                    source_kind=str(ref.get("source_kind") or "unknown"),
                    source_document_id=_optional_text(ref.get("document_id")),
                    label=str(ref.get("label") or ref["evidence_ref_id"]),
                    locator=dict(ref.get("locator") or {}),
                    fact_ids=list(ref.get("fact_ids") or ()),
                    anchor_ids=list(ref.get("anchor_ids") or ()),
                    confidence=ref.get("confidence"),
                    traceability_status=str(
                        ref.get("traceability_status") or "unknown"
                    ),
                    evidence_role=_optional_text(ref.get("evidence_role")),
                    quote=_optional_text(ref.get("quote")),
                    href=_optional_text(ref.get("href")),
                )
            )
        for position, context in enumerate(contexts):
            session.add(
                ResearchContextRecord(
                    understanding_id=understanding_id,
                    context_id=str(context["context_id"]),
                    context_order=position,
                    label=str(context.get("label") or context["context_id"]),
                    material_scope=list(context.get("material_scope") or ()),
                    process_context=dict(context.get("process_context") or {}),
                    test_condition=dict(context.get("test_condition") or {}),
                    property_scope=list(context.get("property_scope") or ()),
                    limitations=list(context.get("limitations") or ()),
                )
            )
        for position, claim in enumerate(claims):
            session.add(
                ResearchClaimRecord(
                    understanding_id=understanding_id,
                    claim_id=str(claim["claim_id"]),
                    claim_order=position,
                    claim_type=str(claim.get("claim_type") or "finding"),
                    statement=str(claim.get("statement") or ""),
                    status=str(claim.get("status") or "limited"),
                    confidence=claim.get("confidence"),
                    strength=_optional_text(claim.get("strength")),
                    source_object_ids=list(claim.get("source_object_ids") or ()),
                    warnings=list(claim.get("warnings") or ()),
                )
            )
        for position, relation in enumerate(relations):
            session.add(
                ResearchRelationRecord(
                    understanding_id=understanding_id,
                    relation_id=str(relation["relation_id"]),
                    relation_order=position,
                    relation_type=str(relation.get("relation_type") or "compares"),
                    subject=str(relation.get("subject") or ""),
                    predicate=str(relation.get("predicate") or ""),
                    object=str(relation.get("object") or ""),
                    statement=_optional_text(relation.get("statement")),
                    status=str(relation.get("status") or "limited"),
                    confidence=relation.get("confidence"),
                    details={
                        key: value
                        for key, value in relation.items()
                        if key
                        not in {
                            "relation_id",
                            "relation_type",
                            "subject",
                            "predicate",
                            "object",
                            "statement",
                            "status",
                            "confidence",
                            "evidence_ref_ids",
                            "context_ids",
                            "supporting_evidence_ref_ids",
                            "conflicting_evidence_ref_ids",
                            "context_evidence_ref_ids",
                            "mechanism_evidence_ref_ids",
                        }
                    },
                )
            )
        session.flush()
        for claim in claims:
            for position, evidence_ref_id in enumerate(
                claim.get("evidence_ref_ids") or ()
            ):
                session.execute(
                    research_claim_evidence_links.insert().values(
                        understanding_id=understanding_id,
                        claim_id=str(claim["claim_id"]),
                        evidence_ref_id=str(evidence_ref_id),
                        position=position,
                    )
                )
            for position, context_id in enumerate(claim.get("context_ids") or ()):
                session.execute(
                    research_claim_context_links.insert().values(
                        understanding_id=understanding_id,
                        claim_id=str(claim["claim_id"]),
                        context_id=str(context_id),
                        position=position,
                    )
                )
        for relation in relations:
            evidence_groups = (
                ("direct", relation.get("evidence_ref_ids") or ()),
                ("supporting", relation.get("supporting_evidence_ref_ids") or ()),
                ("conflicting", relation.get("conflicting_evidence_ref_ids") or ()),
                ("context", relation.get("context_evidence_ref_ids") or ()),
                ("mechanism", relation.get("mechanism_evidence_ref_ids") or ()),
            )
            for role, evidence_ids in evidence_groups:
                for position, evidence_ref_id in enumerate(evidence_ids):
                    session.execute(
                        research_relation_evidence_links.insert().values(
                            understanding_id=understanding_id,
                            relation_id=str(relation["relation_id"]),
                            evidence_ref_id=str(evidence_ref_id),
                            role=role,
                            position=position,
                        )
                    )
            for position, context_id in enumerate(relation.get("context_ids") or ()):
                session.execute(
                    research_relation_context_links.insert().values(
                        understanding_id=understanding_id,
                        relation_id=str(relation["relation_id"]),
                        context_id=str(context_id),
                        position=position,
                    )
                )
        for position, finding in enumerate(_findings(payload)):
            evidence_ids = list(finding.get("evidence_ref_ids") or ())
            session.add(
                ResearchFindingRecord(
                    understanding_id=understanding_id,
                    finding_id=str(finding["finding_id"]),
                    claim_id=str(finding["claim_id"]),
                    finding_order=position,
                    statement=str(finding.get("statement") or ""),
                    fingerprint=_optional_text(
                        finding.get("fingerprint")
                        or finding.get("finding_fingerprint")
                    ),
                    review_status=_optional_text(finding.get("review_status")),
                    evidence_ref_ids=evidence_ids,
                    details={
                        key: value
                        for key, value in finding.items()
                        if key
                        not in {
                            "finding_id",
                            "claim_id",
                            "statement",
                            "fingerprint",
                            "finding_fingerprint",
                            "review_status",
                            "evidence_ref_ids",
                        }
                    },
                )
            )
            session.flush()
            for evidence_position, evidence_ref_id in enumerate(evidence_ids):
                session.execute(
                    research_finding_evidence_links.insert().values(
                        understanding_id=understanding_id,
                        finding_id=str(finding["finding_id"]),
                        evidence_ref_id=str(evidence_ref_id),
                        position=evidence_position,
                    )
                )

    @staticmethod
    def _to_domain(
        session: Session,
        row: ResearchUnderstandingRecord,
    ) -> ResearchUnderstanding:
        understanding_id = row.understanding_id
        claim_evidence = _ordered_links(
            session, research_claim_evidence_links, understanding_id, "claim_id", "evidence_ref_id"
        )
        claim_contexts = _ordered_links(
            session, research_claim_context_links, understanding_id, "claim_id", "context_id"
        )
        relation_contexts = _ordered_links(
            session, research_relation_context_links, understanding_id, "relation_id", "context_id"
        )
        relation_evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
        for link in session.execute(
            select(research_relation_evidence_links)
            .where(
                research_relation_evidence_links.c.understanding_id
                == understanding_id
            )
            .order_by(
                research_relation_evidence_links.c.relation_id,
                research_relation_evidence_links.c.role,
                research_relation_evidence_links.c.position,
            )
        ).mappings():
            relation_evidence[(str(link["relation_id"]), str(link["role"]))].append(
                str(link["evidence_ref_id"])
            )
        findings = []
        for finding in session.scalars(
            select(ResearchFindingRecord)
            .where(ResearchFindingRecord.understanding_id == understanding_id)
            .order_by(ResearchFindingRecord.finding_order)
        ):
            findings.append(
                {
                    **dict(finding.details),
                    "finding_id": finding.finding_id,
                    "claim_id": finding.claim_id,
                    "statement": finding.statement,
                    "finding_fingerprint": finding.fingerprint,
                    "review_status": finding.review_status,
                    "evidence_ref_ids": list(finding.evidence_ref_ids),
                }
            )
        presentation = dict(row.presentation_metadata)
        if findings:
            presentation["findings"] = findings
        return ResearchUnderstanding.from_mapping(
            {
                "schema_version": row.schema_version,
                "state": row.state,
                "scope": {
                    "scope_type": "objective",
                    "collection_id": row.collection_id,
                    "objective_id": row.objective_id,
                    "title": row.title,
                },
                "claims": [
                    {
                        "claim_id": claim.claim_id,
                        "claim_type": claim.claim_type,
                        "statement": claim.statement,
                        "status": claim.status,
                        "confidence": claim.confidence,
                        "strength": claim.strength,
                        "evidence_ref_ids": claim_evidence[claim.claim_id],
                        "context_ids": claim_contexts[claim.claim_id],
                        "source_object_ids": list(claim.source_object_ids),
                        "warnings": list(claim.warnings),
                    }
                    for claim in session.scalars(
                        select(ResearchClaimRecord)
                        .where(ResearchClaimRecord.understanding_id == understanding_id)
                        .order_by(ResearchClaimRecord.claim_order)
                    )
                ],
                "relations": [
                    {
                        **dict(relation.details),
                        "relation_id": relation.relation_id,
                        "relation_type": relation.relation_type,
                        "subject": relation.subject,
                        "predicate": relation.predicate,
                        "object": relation.object,
                        "statement": relation.statement,
                        "status": relation.status,
                        "confidence": relation.confidence,
                        "evidence_ref_ids": relation_evidence[
                            (relation.relation_id, "direct")
                        ],
                        "supporting_evidence_ref_ids": relation_evidence[
                            (relation.relation_id, "supporting")
                        ],
                        "conflicting_evidence_ref_ids": relation_evidence[
                            (relation.relation_id, "conflicting")
                        ],
                        "context_evidence_ref_ids": relation_evidence[
                            (relation.relation_id, "context")
                        ],
                        "mechanism_evidence_ref_ids": relation_evidence[
                            (relation.relation_id, "mechanism")
                        ],
                        "context_ids": relation_contexts[relation.relation_id],
                    }
                    for relation in session.scalars(
                        select(ResearchRelationRecord)
                        .where(ResearchRelationRecord.understanding_id == understanding_id)
                        .order_by(ResearchRelationRecord.relation_order)
                    )
                ],
                "evidence_refs": [
                    {
                        "evidence_ref_id": ref.evidence_ref_id,
                        "source_kind": ref.source_kind,
                        "document_id": ref.source_document_id,
                        "label": ref.label,
                        "locator": dict(ref.locator),
                        "fact_ids": list(ref.fact_ids),
                        "anchor_ids": list(ref.anchor_ids),
                        "confidence": ref.confidence,
                        "traceability_status": ref.traceability_status,
                        "evidence_role": ref.evidence_role,
                        "quote": ref.quote,
                        "href": ref.href,
                    }
                    for ref in session.scalars(
                        select(ResearchEvidenceRefRecord)
                        .where(
                            ResearchEvidenceRefRecord.understanding_id
                            == understanding_id
                        )
                        .order_by(ResearchEvidenceRefRecord.evidence_order)
                    )
                ],
                "contexts": [
                    {
                        "context_id": context.context_id,
                        "label": context.label,
                        "material_scope": list(context.material_scope),
                        "process_context": dict(context.process_context),
                        "test_condition": dict(context.test_condition),
                        "property_scope": list(context.property_scope),
                        "limitations": list(context.limitations),
                    }
                    for context in session.scalars(
                        select(ResearchContextRecord)
                        .where(ResearchContextRecord.understanding_id == understanding_id)
                        .order_by(ResearchContextRecord.context_order)
                    )
                ],
                "warnings": list(row.warnings),
                "presentation": presentation,
                "model_traces": [dict(trace) for trace in row.model_traces],
            }
        )


def _ordered_links(
    session: Session,
    table: Any,
    understanding_id: str,
    owner_column: str,
    value_column: str,
) -> dict[str, list[str]]:
    values: dict[str, list[str]] = defaultdict(list)
    for row in session.execute(
        select(table)
        .where(table.c.understanding_id == understanding_id)
        .order_by(getattr(table.c, owner_column), table.c.position)
    ).mappings():
        values[str(row[owner_column])].append(str(row[value_column]))
    return values


def _require_objective_scope(
    collection_id: str,
    objective_id: str,
    understanding: ResearchUnderstanding,
) -> None:
    scope = understanding.scope
    if (
        scope.scope_type != "objective"
        or scope.collection_id != collection_id
        or scope.objective_id != objective_id
    ):
        raise ValueError("Research Understanding must match its Objective scope")


def _findings(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    presentation = payload.get("presentation")
    if not isinstance(presentation, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("findings", "review_candidates"):
        value = presentation.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, Mapping):
                continue
            finding = dict(item)
            finding_id = str(finding.get("finding_id") or "")
            if finding_id and finding_id not in seen:
                seen.add(finding_id)
                rows.append(finding)
    return rows


def _understanding_id(collection_id: str, objective_id: str) -> str:
    digest = sha1(f"{collection_id}\x1f{objective_id}".encode("utf-8")).hexdigest()[:20]
    return f"understanding_{digest}"


def _content_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = ["PostgresResearchUnderstandingRepository"]
