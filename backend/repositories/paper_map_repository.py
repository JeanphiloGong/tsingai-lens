"""PostgreSQL repository for paper map."""

from __future__ import annotations

import json

from domain.core.research_objective import (
    PaperResearchMap,
    PaperResearchSourceRef,
    ReviewKnowledgeItem,
    ReviewSynthesisMap,
    PaperResearchRelationship,
    PaperResearchScope,
    PaperResearchSignal,
    PaperSourceUnitCoverage,
    build_paper_research_scope_id,
    build_paper_research_relationship,
    build_paper_research_signal,
)

from sqlalchemy import select

from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.document_preparation import (
    DocumentPreparationRow,
)


class PaperMapRepository:
    async def replace(self, collection_id: str, paper_map: PaperResearchMap) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            document = await db.get(Document, paper_map.document_id)
            if document is None or document.collection_id != collection_id:
                raise FileNotFoundError(
                    f"collection document not found: {collection_id}/{paper_map.document_id}"
                )
            row = await db.scalar(
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
            row.paper_map_payload = {
                "document_id": paper_map.document_id,
                "doc_role": paper_map.doc_role,
                "studies": [
                    {
                        "study_id": study.study_id,
                        "document_id": study.document_id,
                        "design_type": study.design_type,
                        "claim_scope": study.claim_scope,
                        "experiment_label": study.experiment_label,
                        "material_scope": list(study.material_scope),
                        "process_context": list(study.process_context),
                        "relationships": [
                            {
                                "relationship_id": item.relationship_id,
                                "varied_factors": list(item.varied_factors),
                                "outcome": item.outcome,
                                "source_refs": [
                                    {
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                    }
                                    for item in item.source_refs
                                ],
                                "confidence": item.confidence,
                            }
                            for item in study.relationships
                        ],
                        "confidence": study.confidence,
                    }
                    for study in paper_map.studies
                ],
                "evidence_density": paper_map.evidence_density,
                "confidence": paper_map.confidence,
                "warnings": list(paper_map.warnings),
                "unresolved_signals": [
                    {
                        "signal_id": signal.signal_id,
                        "signal_type": signal.signal_type,
                        "label": signal.label,
                        "variable_role": signal.variable_role,
                        "design_type": signal.design_type,
                        "claim_scope": signal.claim_scope,
                        "experiment_label": signal.experiment_label,
                        "material_scope": list(signal.material_scope),
                        "process_context": list(signal.process_context),
                        "source_refs": [
                            {
                                "source_kind": item.source_kind,
                                "source_ref": item.source_ref,
                            }
                            for item in signal.source_refs
                        ],
                        "confidence": signal.confidence,
                        "reason": signal.reason,
                    }
                    for signal in paper_map.unresolved_signals
                ],
                "source_unit_coverage": [
                    {
                        "source_unit_id": item.source_unit_id,
                        "window_id": item.window_id,
                        "source_kind": item.source_kind,
                        "source_ref": item.source_ref,
                        "status": item.status.value,
                        "reason": item.reason,
                    }
                    for item in paper_map.source_unit_coverage
                ],
                "map_status": paper_map.map_status,
                "map_limitations": list(paper_map.map_limitations),
                "review_synthesis": {
                    field_name: [
                        {
                            "content": item.content,
                            "material_scope": list(item.material_scope),
                            "variables": list(item.variables),
                            "outcomes": list(item.outcomes),
                            "conditions": list(item.conditions),
                            "source_refs": [
                                {
                                    "source_kind": item.source_kind,
                                    "source_ref": item.source_ref,
                                }
                                for item in item.source_refs
                            ],
                            "confidence": item.confidence,
                        }
                        for item in getattr(paper_map.review_synthesis, field_name)
                    ]
                    for field_name in (
                        "synthesis_claims",
                        "disputes",
                        "evidence_gaps",
                        "citation_leads",
                    )
                },
                "input_fingerprint": paper_map.input_fingerprint,
                "map_version": paper_map.map_version,
                "generated_at": paper_map.generated_at,
            }

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> PaperResearchMap | None:
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
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
            if row is None or not row.paper_map_payload:
                return None
            payload = row.paper_map_payload
            map_document_id = payload.get("document_id", row.document_id)
            studies = []
            for study in payload.get("studies", ()):
                document_id = study.get("document_id", map_document_id)
                design_type = study.get("design_type", "uncertain")
                claim_scope = study.get("claim_scope", "uncertain")
                experiment_label = study.get("experiment_label")
                material_scope = tuple(study.get("material_scope", ()))
                process_context = tuple(study.get("process_context", ()))
                parent_study_boundary = json.dumps(
                    {
                        "document_id": document_id.casefold(),
                        "design_type": design_type,
                        "claim_scope": claim_scope,
                        "experiment_label": (
                            experiment_label.casefold() if experiment_label else None
                        ),
                        "material_scope": sorted(
                            value.casefold() for value in material_scope
                        ),
                        "process_context": sorted(
                            value.casefold() for value in process_context
                        ),
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                relationships = []
                for relationship in study.get("relationships", ()):
                    varied_factors = tuple(relationship["varied_factors"])
                    source_refs = tuple(
                        dict.fromkeys(
                            PaperResearchSourceRef(
                                ref["source_kind"], ref["source_ref"]
                            )
                            for ref in relationship["source_refs"]
                        )
                    )
                    if relationship.get("relationship_id") is None:
                        relationships.append(
                            build_paper_research_relationship(
                                document_id=document_id,
                                varied_factors=varied_factors,
                                outcome=relationship["outcome"],
                                source_refs=source_refs,
                                confidence=relationship.get("confidence", 0.0),
                                parent_study_boundary=parent_study_boundary,
                            )
                        )
                    else:
                        relationships.append(
                            PaperResearchRelationship(
                                relationship_id=relationship["relationship_id"],
                                varied_factors=varied_factors,
                                outcome=relationship["outcome"],
                                source_refs=source_refs,
                                confidence=relationship.get("confidence", 0.0),
                            )
                        )
                relationships = tuple(relationships)
                study_id = study.get("study_id")
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
                studies.append(
                    PaperResearchScope(
                        study_id=study_id,
                        document_id=document_id,
                        design_type=design_type,
                        claim_scope=claim_scope,
                        experiment_label=experiment_label,
                        material_scope=material_scope,
                        process_context=process_context,
                        relationships=relationships,
                        confidence=study.get("confidence", 0.0),
                    )
                )
            signals = []
            for signal in payload.get("unresolved_signals", ()):
                signal_type = signal["signal_type"]
                variable_role = signal.get(
                    "variable_role",
                    "not_applicable" if signal_type == "outcome" else "uncertain",
                )
                source_refs = tuple(
                    dict.fromkeys(
                        PaperResearchSourceRef(ref["source_kind"], ref["source_ref"])
                        for ref in signal["source_refs"]
                    )
                )
                if signal.get("signal_id") is None:
                    signals.append(
                        build_paper_research_signal(
                            document_id=map_document_id,
                            signal_type=signal_type,
                            label=signal["label"],
                            variable_role=variable_role,
                            design_type=signal.get("design_type", "uncertain"),
                            claim_scope=signal.get("claim_scope", "uncertain"),
                            experiment_label=signal.get("experiment_label"),
                            material_scope=tuple(signal.get("material_scope", ())),
                            process_context=tuple(signal.get("process_context", ())),
                            source_refs=source_refs,
                            confidence=signal.get("confidence", 0.0),
                            reason=signal.get("reason"),
                        )
                    )
                else:
                    signals.append(
                        PaperResearchSignal(
                            signal_id=signal["signal_id"],
                            signal_type=signal_type,
                            label=signal["label"],
                            variable_role=variable_role,
                            design_type=signal.get("design_type", "uncertain"),
                            claim_scope=signal.get("claim_scope", "uncertain"),
                            experiment_label=signal.get("experiment_label"),
                            material_scope=tuple(signal.get("material_scope", ())),
                            process_context=tuple(signal.get("process_context", ())),
                            source_refs=source_refs,
                            confidence=signal.get("confidence", 0.0),
                            reason=signal.get("reason"),
                        )
                    )
            review = payload.get("review_synthesis", {})
            review_items = {}
            for field_name in (
                "synthesis_claims",
                "disputes",
                "evidence_gaps",
                "citation_leads",
            ):
                review_items[field_name] = tuple(
                    ReviewKnowledgeItem(
                        content=item["content"],
                        material_scope=tuple(item.get("material_scope", ())),
                        variables=tuple(item.get("variables", ())),
                        outcomes=tuple(item.get("outcomes", ())),
                        conditions=tuple(item.get("conditions", ())),
                        source_refs=tuple(
                            dict.fromkeys(
                                PaperResearchSourceRef(
                                    ref["source_kind"], ref["source_ref"]
                                )
                                for ref in item["source_refs"]
                            )
                        ),
                        confidence=item.get("confidence", 0.0),
                    )
                    for item in review.get(field_name, ())
                )
            paper_map = PaperResearchMap(
                document_id=map_document_id,
                doc_role=payload.get("doc_role", "uncertain"),
                studies=tuple(studies),
                evidence_density=payload.get("evidence_density", "unknown"),
                confidence=payload.get("confidence", 0.0),
                warnings=tuple(payload.get("warnings", ())),
                unresolved_signals=tuple(signals),
                source_unit_coverage=tuple(
                    PaperSourceUnitCoverage(
                        source_unit_id=item["source_unit_id"],
                        window_id=item["window_id"],
                        source_kind=item["source_kind"],
                        source_ref=item["source_ref"],
                        status=item["status"],
                        reason=item.get("reason"),
                    )
                    for item in payload.get("source_unit_coverage", ())
                ),
                map_status=payload.get("map_status", "unknown"),
                map_limitations=tuple(payload.get("map_limitations", ())),
                review_synthesis=ReviewSynthesisMap(
                    synthesis_claims=review_items["synthesis_claims"],
                    disputes=review_items["disputes"],
                    evidence_gaps=review_items["evidence_gaps"],
                    citation_leads=review_items["citation_leads"],
                ),
                input_fingerprint=payload.get("input_fingerprint"),
                map_version=payload.get("map_version"),
                generated_at=payload.get("generated_at"),
            )
            return paper_map

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[PaperResearchMap, ...]:
        if document_ids == ():
            return ()
        async with AsyncSessionLocal() as db:
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
            rows = await db.scalars(
                statement.order_by(DocumentPreparationRow.document_id)
            )
            paper_maps = []
            for row in rows:
                if not row.paper_map_payload:
                    continue
                payload = row.paper_map_payload
                map_document_id = payload.get("document_id", row.document_id)
                studies = []
                for study in payload.get("studies", ()):
                    document_id = study.get("document_id", map_document_id)
                    design_type = study.get("design_type", "uncertain")
                    claim_scope = study.get("claim_scope", "uncertain")
                    experiment_label = study.get("experiment_label")
                    material_scope = tuple(study.get("material_scope", ()))
                    process_context = tuple(study.get("process_context", ()))
                    parent_study_boundary = json.dumps(
                        {
                            "document_id": document_id.casefold(),
                            "design_type": design_type,
                            "claim_scope": claim_scope,
                            "experiment_label": (
                                experiment_label.casefold()
                                if experiment_label
                                else None
                            ),
                            "material_scope": sorted(
                                value.casefold() for value in material_scope
                            ),
                            "process_context": sorted(
                                value.casefold() for value in process_context
                            ),
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    relationships = []
                    for relationship in study.get("relationships", ()):
                        varied_factors = tuple(relationship["varied_factors"])
                        source_refs = tuple(
                            dict.fromkeys(
                                PaperResearchSourceRef(
                                    ref["source_kind"], ref["source_ref"]
                                )
                                for ref in relationship["source_refs"]
                            )
                        )
                        if relationship.get("relationship_id") is None:
                            relationships.append(
                                build_paper_research_relationship(
                                    document_id=document_id,
                                    varied_factors=varied_factors,
                                    outcome=relationship["outcome"],
                                    source_refs=source_refs,
                                    confidence=relationship.get("confidence", 0.0),
                                    parent_study_boundary=parent_study_boundary,
                                )
                            )
                        else:
                            relationships.append(
                                PaperResearchRelationship(
                                    relationship_id=relationship["relationship_id"],
                                    varied_factors=varied_factors,
                                    outcome=relationship["outcome"],
                                    source_refs=source_refs,
                                    confidence=relationship.get("confidence", 0.0),
                                )
                            )
                    relationships = tuple(relationships)
                    study_id = study.get("study_id")
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
                    studies.append(
                        PaperResearchScope(
                            study_id=study_id,
                            document_id=document_id,
                            design_type=design_type,
                            claim_scope=claim_scope,
                            experiment_label=experiment_label,
                            material_scope=material_scope,
                            process_context=process_context,
                            relationships=relationships,
                            confidence=study.get("confidence", 0.0),
                        )
                    )
                signals = []
                for signal in payload.get("unresolved_signals", ()):
                    signal_type = signal["signal_type"]
                    variable_role = signal.get(
                        "variable_role",
                        "not_applicable" if signal_type == "outcome" else "uncertain",
                    )
                    source_refs = tuple(
                        dict.fromkeys(
                            PaperResearchSourceRef(
                                ref["source_kind"], ref["source_ref"]
                            )
                            for ref in signal["source_refs"]
                        )
                    )
                    if signal.get("signal_id") is None:
                        signals.append(
                            build_paper_research_signal(
                                document_id=map_document_id,
                                signal_type=signal_type,
                                label=signal["label"],
                                variable_role=variable_role,
                                design_type=signal.get("design_type", "uncertain"),
                                claim_scope=signal.get("claim_scope", "uncertain"),
                                experiment_label=signal.get("experiment_label"),
                                material_scope=tuple(signal.get("material_scope", ())),
                                process_context=tuple(
                                    signal.get("process_context", ())
                                ),
                                source_refs=source_refs,
                                confidence=signal.get("confidence", 0.0),
                                reason=signal.get("reason"),
                            )
                        )
                    else:
                        signals.append(
                            PaperResearchSignal(
                                signal_id=signal["signal_id"],
                                signal_type=signal_type,
                                label=signal["label"],
                                variable_role=variable_role,
                                design_type=signal.get("design_type", "uncertain"),
                                claim_scope=signal.get("claim_scope", "uncertain"),
                                experiment_label=signal.get("experiment_label"),
                                material_scope=tuple(signal.get("material_scope", ())),
                                process_context=tuple(
                                    signal.get("process_context", ())
                                ),
                                source_refs=source_refs,
                                confidence=signal.get("confidence", 0.0),
                                reason=signal.get("reason"),
                            )
                        )
                review = payload.get("review_synthesis", {})
                review_items = {}
                for field_name in (
                    "synthesis_claims",
                    "disputes",
                    "evidence_gaps",
                    "citation_leads",
                ):
                    review_items[field_name] = tuple(
                        ReviewKnowledgeItem(
                            content=item["content"],
                            material_scope=tuple(item.get("material_scope", ())),
                            variables=tuple(item.get("variables", ())),
                            outcomes=tuple(item.get("outcomes", ())),
                            conditions=tuple(item.get("conditions", ())),
                            source_refs=tuple(
                                dict.fromkeys(
                                    PaperResearchSourceRef(
                                        ref["source_kind"], ref["source_ref"]
                                    )
                                    for ref in item["source_refs"]
                                )
                            ),
                            confidence=item.get("confidence", 0.0),
                        )
                        for item in review.get(field_name, ())
                    )
                paper_map = PaperResearchMap(
                    document_id=map_document_id,
                    doc_role=payload.get("doc_role", "uncertain"),
                    studies=tuple(studies),
                    evidence_density=payload.get("evidence_density", "unknown"),
                    confidence=payload.get("confidence", 0.0),
                    warnings=tuple(payload.get("warnings", ())),
                    unresolved_signals=tuple(signals),
                    source_unit_coverage=tuple(
                        PaperSourceUnitCoverage(
                            source_unit_id=item["source_unit_id"],
                            window_id=item["window_id"],
                            source_kind=item["source_kind"],
                            source_ref=item["source_ref"],
                            status=item["status"],
                            reason=item.get("reason"),
                        )
                        for item in payload.get("source_unit_coverage", ())
                    ),
                    map_status=payload.get("map_status", "unknown"),
                    map_limitations=tuple(payload.get("map_limitations", ())),
                    review_synthesis=ReviewSynthesisMap(
                        synthesis_claims=review_items["synthesis_claims"],
                        disputes=review_items["disputes"],
                        evidence_gaps=review_items["evidence_gaps"],
                        citation_leads=review_items["citation_leads"],
                    ),
                    input_fingerprint=payload.get("input_fingerprint"),
                    map_version=payload.get("map_version"),
                    generated_at=payload.get("generated_at"),
                )
                paper_maps.append(paper_map)
            return tuple(paper_maps)
