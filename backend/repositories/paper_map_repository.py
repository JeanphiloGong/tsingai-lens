"""PostgreSQL repository for paper map."""

from __future__ import annotations

from domain.core.research_objective import build_paper_research_scope_id

from domain.core.research_objective import (
    build_paper_research_relationship, build_paper_research_scope, build_paper_research_signal,
)

import json
from typing import Any, Mapping
from domain.core.research_objective import (
    PaperResearchSourceRef, ReviewKnowledgeItem, ReviewSynthesisMap,
    PaperResearchRelationship, PaperResearchScope, PaperResearchSignal,
    PaperSourceUnitCoverage, normalize_objective_terms, normalize_objective_confidence,
    _text,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core.research_objective import PaperResearchMap
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.document_preparation import (
    DocumentPreparationRow,
)


class PaperMapRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def replace(self, collection_id: str, paper_map: PaperResearchMap) -> None:
        async with self.session_factory.begin() as session:
            document = await session.get(Document, paper_map.document_id)
            if document is None or document.collection_id != collection_id:
                raise FileNotFoundError(
                    f"collection document not found: {collection_id}/{paper_map.document_id}"
                )
            row = await session.scalar(
                select(DocumentPreparationRow)
                .join(
                    Document,
                    Document.document_id == DocumentPreparationRow.document_id,
                )
                .where(
                    DocumentPreparationRow.document_id == paper_map.document_id,
                    Document.collection_id == collection_id,
                )
            )
            if row is None or not row.profile_json:
                raise FileNotFoundError(
                    f"document profile not found: {collection_id}/{paper_map.document_id}"
                )
            _replace_row(row, paper_map)

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> PaperResearchMap | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(DocumentPreparationRow)
                .join(
                    Document,
                    Document.document_id == DocumentPreparationRow.document_id,
                )
                .where(
                    DocumentPreparationRow.document_id == document_id,
                    Document.collection_id == collection_id,
                )
            )
            return _from_row(row) if row is not None and row.paper_map_payload else None

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[PaperResearchMap, ...]:
        if document_ids == ():
            return ()
        async with self.session_factory() as session:
            statement = (
                select(DocumentPreparationRow)
                .join(
                    Document,
                    Document.document_id == DocumentPreparationRow.document_id,
                )
                .where(Document.collection_id == collection_id)
            )
            if document_ids is not None:
                statement = statement.where(
                    DocumentPreparationRow.document_id.in_(document_ids)
                )
            rows = await session.scalars(
                statement.order_by(DocumentPreparationRow.document_id)
            )
            return tuple(_from_row(row) for row in rows if row.paper_map_payload)


def _replace_row(row: DocumentPreparationRow, paper_map: PaperResearchMap) -> None:
    row.paper_map_payload = paper_map_payload(paper_map)


def _from_row(row: DocumentPreparationRow) -> PaperResearchMap:
    payload = dict(row.paper_map_payload or {})
    payload.setdefault("document_id", row.document_id)
    return paper_map_from_payload(payload)


__all__ = ['PaperMapRepository']


def _source_ref(payload: Mapping[str, Any]) -> "PaperResearchSourceRef":
    return PaperResearchSourceRef(
        source_kind=_text(payload.get("source_kind")) or "",
        source_ref=_text(payload.get("source_ref")) or "",
    )


def _review_item(payload: Mapping[str, Any]) -> "ReviewKnowledgeItem":
    return ReviewKnowledgeItem(
        content=_text(payload.get("content")) or "",
        material_scope=normalize_objective_terms(payload.get("material_scope")),
        variables=normalize_objective_terms(payload.get("variables")),
        outcomes=normalize_objective_terms(payload.get("outcomes")),
        conditions=normalize_objective_terms(payload.get("conditions")),
        source_refs=_paper_research_source_refs(payload.get("source_refs")),
        confidence=normalize_objective_confidence(payload.get("confidence")),
    )


def _review_synthesis(payload: Mapping[str, Any] | None) -> "ReviewSynthesisMap":
    source = payload or {}

    def items(field_name: str) -> tuple[ReviewKnowledgeItem, ...]:
        return tuple(
            _review_item(item)
            for item in source.get(field_name) or ()
            if isinstance(item, Mapping)
        )

    return ReviewSynthesisMap(
        synthesis_claims=items("synthesis_claims"),
        disputes=items("disputes"),
        evidence_gaps=items("evidence_gaps"),
        citation_leads=items("citation_leads"),
    )


def _relationship(
    payload: Mapping[str, Any],
    *,
    parent_study_boundary: str | None = None,
) -> "PaperResearchRelationship":
    varied_factors = normalize_objective_terms(payload.get("varied_factors"))
    outcome = _text(payload.get("outcome")) or ""
    source_refs = _paper_research_source_refs(payload.get("source_refs"))
    relationship_id = _text(payload.get("relationship_id"))
    if relationship_id is None:
        return build_paper_research_relationship(
            document_id=_text(payload.get('document_id')) or '',
            varied_factors=varied_factors,
            outcome=outcome,
            source_refs=source_refs,
            confidence=normalize_objective_confidence(payload.get('confidence')),
            parent_study_boundary=parent_study_boundary,
        )
    return PaperResearchRelationship(
        relationship_id=relationship_id,
        varied_factors=varied_factors,
        outcome=outcome,
        source_refs=source_refs,
        confidence=normalize_objective_confidence(payload.get("confidence")),
    )


def research_scope_from_payload(payload: Mapping[str, Any]) -> "PaperResearchScope":
    document_id = _text(payload.get("document_id")) or ""
    design_type = _text(payload.get("design_type")) or "uncertain"
    claim_scope = _text(payload.get("claim_scope")) or "uncertain"
    experiment_label = _text(payload.get("experiment_label"))
    material_scope = normalize_objective_terms(payload.get("material_scope"))
    process_context = normalize_objective_terms(payload.get("process_context"))
    parent_study_boundary = json.dumps(
        {
            "document_id": document_id.casefold(),
            "design_type": design_type,
            "claim_scope": claim_scope,
            "experiment_label": (
                experiment_label.casefold() if experiment_label else None
            ),
            "material_scope": sorted(value.casefold() for value in material_scope),
            "process_context": sorted(
                value.casefold() for value in process_context
            ),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    relationships = tuple(
        _relationship(
            {**dict(item), "document_id": document_id},
            parent_study_boundary=parent_study_boundary,
        )
        for item in payload.get("relationships") or ()
        if isinstance(item, Mapping)
    )
    study_id = _text(payload.get("study_id"))
    if study_id is None:
        study_id = build_paper_research_scope_id(
            document_id=document_id,
            design_type=design_type,
            claim_scope=claim_scope,
            experiment_label=experiment_label,
            material_scope=material_scope,
            process_context=process_context,
            relationships=relationships,
        )
    return PaperResearchScope(
        study_id=study_id,
        document_id=document_id,
        design_type=design_type,
        claim_scope=claim_scope,
        experiment_label=experiment_label,
        material_scope=material_scope,
        process_context=process_context,
        relationships=relationships,
        confidence=normalize_objective_confidence(payload.get("confidence")),
    )


def research_signal_from_payload(payload: Mapping[str, Any]) -> "PaperResearchSignal":
    signal_type = _text(payload.get("signal_type")) or ""
    label = _text(payload.get("label")) or ""
    variable_role = _text(payload.get("variable_role")) or (
        "not_applicable" if signal_type == "outcome" else "uncertain"
    )
    design_type = _text(payload.get("design_type")) or "uncertain"
    claim_scope = _text(payload.get("claim_scope")) or "uncertain"
    experiment_label = _text(payload.get("experiment_label"))
    material_scope = normalize_objective_terms(payload.get("material_scope"))
    process_context = normalize_objective_terms(payload.get("process_context"))
    source_refs = _paper_research_source_refs(payload.get("source_refs"))
    signal_id = _text(payload.get("signal_id"))
    if signal_id is None:
        return build_paper_research_signal(
            document_id=_text(payload.get('document_id')) or '',
            signal_type=signal_type,
            label=label,
            variable_role=variable_role,
            design_type=design_type,
            claim_scope=claim_scope,
            experiment_label=experiment_label,
            material_scope=material_scope,
            process_context=process_context,
            source_refs=source_refs,
            confidence=normalize_objective_confidence(payload.get('confidence')),
            reason=_text(payload.get('reason')),
        )
    return PaperResearchSignal(
        signal_id=signal_id,
        signal_type=signal_type,
        label=label,
        variable_role=variable_role,
        design_type=design_type,
        claim_scope=claim_scope,
        experiment_label=experiment_label,
        material_scope=material_scope,
        process_context=process_context,
        source_refs=source_refs,
        confidence=normalize_objective_confidence(payload.get("confidence")),
        reason=_text(payload.get("reason")),
    )


def coverage_from_payload(payload: Mapping[str, Any]) -> "PaperSourceUnitCoverage":
    return PaperSourceUnitCoverage(
        source_unit_id=_text(payload.get("source_unit_id")) or "",
        window_id=_text(payload.get("window_id")) or "",
        source_kind=_text(payload.get("source_kind")) or "",
        source_ref=_text(payload.get("source_ref")) or "",
        status=PaperSourceUnitCoverage._status(payload.get("status")),
        reason=_text(payload.get("reason")),
    )


def paper_map_from_payload(payload: Mapping[str, Any]) -> "PaperResearchMap":
    document_id = _text(payload.get("document_id") or payload.get("paper_id")) or ""
    return PaperResearchMap(
        document_id=document_id,
        doc_role=_text(payload.get("doc_role")) or "uncertain",
        studies=tuple(
            research_scope_from_payload(
                {**dict(item), "document_id": item.get("document_id", document_id)}
            )
            for item in payload.get("studies") or ()
            if isinstance(item, Mapping)
        ),
        evidence_density=_text(payload.get("evidence_density")) or "unknown",
        confidence=normalize_objective_confidence(payload.get("confidence")),
        warnings=normalize_objective_terms(payload.get("warnings")),
        unresolved_signals=tuple(
            research_signal_from_payload(
                {**dict(item), "document_id": document_id}
            )
            for item in payload.get("unresolved_signals") or ()
            if isinstance(item, Mapping)
        ),
        source_unit_coverage=tuple(
            coverage_from_payload(item)
            for item in payload.get("source_unit_coverage") or ()
            if isinstance(item, Mapping)
        ),
        map_status=_text(payload.get("map_status")) or "unknown",
        map_limitations=normalize_objective_terms(
            payload.get("map_limitations")
        ),
        review_synthesis=_review_synthesis(
            payload.get("review_synthesis")
            if isinstance(payload.get("review_synthesis"), Mapping)
            else None
        ),
        input_fingerprint=_text(payload.get("input_fingerprint")) or None,
        map_version=_text(payload.get("map_version")) or None,
        generated_at=_text(payload.get("generated_at")) or None,
    )


def _paper_research_source_refs(value: Any) -> tuple[PaperResearchSourceRef, ...]:
    refs: list[PaperResearchSourceRef] = []
    seen: set[tuple[str, str]] = set()
    for item in value or ():
        if not isinstance(item, Mapping):
            continue
        source_ref = _source_ref(item)
        key = (source_ref.source_kind, source_ref.source_ref)
        if key in seen:
            continue
        seen.add(key)
        refs.append(source_ref)
    return tuple(refs)


def source_ref_payload(value: PaperResearchSourceRef) -> dict[str, str]:
    return {
        "source_kind": value.source_kind,
        "source_ref": value.source_ref,
    }


def review_item_payload(value: ReviewKnowledgeItem) -> dict[str, Any]:
    return {
        "content": value.content,
        "material_scope": list(value.material_scope),
        "variables": list(value.variables),
        "outcomes": list(value.outcomes),
        "conditions": list(value.conditions),
        "source_refs": [source_ref_payload(item) for item in value.source_refs],
        "confidence": value.confidence,
    }


def review_synthesis_payload(value: ReviewSynthesisMap) -> dict[str, Any]:
    return {
        field_name: [review_item_payload(item) for item in getattr(value, field_name)]
        for field_name in (
            "synthesis_claims",
            "disputes",
            "evidence_gaps",
            "citation_leads",
        )
    }


def research_relationship_payload(value: PaperResearchRelationship) -> dict[str, Any]:
    return {
        "relationship_id": value.relationship_id,
        "varied_factors": list(value.varied_factors),
        "outcome": value.outcome,
        "source_refs": [source_ref_payload(item) for item in value.source_refs],
        "confidence": value.confidence,
    }


def research_scope_payload(value: PaperResearchScope) -> dict[str, Any]:
    return {
        "study_id": value.study_id,
        "document_id": value.document_id,
        "design_type": value.design_type,
        "claim_scope": value.claim_scope,
        "experiment_label": value.experiment_label,
        "material_scope": list(value.material_scope),
        "process_context": list(value.process_context),
        "relationships": [research_relationship_payload(item) for item in value.relationships],
        "confidence": value.confidence,
    }


def research_signal_payload(value: PaperResearchSignal) -> dict[str, Any]:
    return {
        "signal_id": value.signal_id,
        "signal_type": value.signal_type,
        "label": value.label,
        "variable_role": value.variable_role,
        "design_type": value.design_type,
        "claim_scope": value.claim_scope,
        "experiment_label": value.experiment_label,
        "material_scope": list(value.material_scope),
        "process_context": list(value.process_context),
        "source_refs": [source_ref_payload(item) for item in value.source_refs],
        "confidence": value.confidence,
        "reason": value.reason,
    }


def coverage_payload(value: PaperSourceUnitCoverage) -> dict[str, Any]:
    return {
        "source_unit_id": value.source_unit_id,
        "window_id": value.window_id,
        "source_kind": value.source_kind,
        "source_ref": value.source_ref,
        "status": value.status.value,
        "reason": value.reason,
    }


def paper_map_payload(value: PaperResearchMap) -> dict[str, Any]:
    return {
        "document_id": value.document_id,
        "doc_role": value.doc_role,
        "studies": [research_scope_payload(study) for study in value.studies],
        "evidence_density": value.evidence_density,
        "confidence": value.confidence,
        "warnings": list(value.warnings),
        "unresolved_signals": [
            research_signal_payload(signal) for signal in value.unresolved_signals
        ],
        "source_unit_coverage": [
            coverage_payload(item) for item in value.source_unit_coverage
        ],
        "map_status": value.map_status,
        "map_limitations": list(value.map_limitations),
        "review_synthesis": review_synthesis_payload(value.review_synthesis),
        "input_fingerprint": value.input_fingerprint,
        "map_version": value.map_version,
        "generated_at": value.generated_at,
    }
