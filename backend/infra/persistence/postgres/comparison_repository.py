"""Build-versioned PostgreSQL persistence for comparison semantics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import Table, delete, select
from sqlalchemy.orm import Session, sessionmaker

from domain.core.comparison import (
    CollectionComparableResult,
    ComparableResult,
    ComparisonFactSet,
    PairwiseComparisonRelation,
)
from infra.persistence.postgres.models.build import (
    CollectionActiveBuild,
    CollectionBuild,
)
from infra.persistence.postgres.models.comparison import (
    CollectionComparableResultRecord,
    ComparableResultRecord,
    ComparisonBuild,
    PairwiseComparisonRelationRecord,
    comparable_result_anchor_links,
    comparable_result_evidence_links,
    comparable_result_feature_links,
    comparable_result_observation_links,
    pairwise_comparison_anchor_links,
)
from infra.persistence.postgres.models.paper_fact import (
    PaperFactBaselineReference,
    PaperFactCharacterizationObservation,
    PaperFactEvidenceAnchor,
    PaperFactMeasurementResult,
    PaperFactSampleVariant,
    PaperFactStructureFeature,
    PaperFactTestCondition,
)


_RESULT_LINK_TABLES = (
    comparable_result_anchor_links,
    comparable_result_evidence_links,
    comparable_result_feature_links,
    comparable_result_observation_links,
)


class PostgresComparisonRepository:
    """Store one immutable comparison aggregate per collection build."""

    backend_name = "postgres"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def replace(
        self,
        collection_id: str,
        build_id: str,
        facts: ComparisonFactSet,
    ) -> None:
        with self.session_factory.begin() as session:
            self._require_writable_build(session, collection_id, build_id)
            source_kinds = self._validate_facts(
                session,
                collection_id,
                build_id,
                facts,
            )
            self._delete_build_records(session, build_id)
            session.add(
                ComparisonBuild(
                    build_id=build_id,
                    collection_id=collection_id,
                    comparison_artifacts_ready=facts.comparison_artifacts_ready,
                )
            )
            session.flush()
            session.add_all(
                self._comparable_row(
                    collection_id,
                    build_id,
                    position,
                    item,
                    source_kinds[item.comparable_result_id],
                )
                for position, item in enumerate(facts.comparable_results)
            )
            session.flush()
            session.add_all(
                self._scoped_row(collection_id, build_id, item)
                for item in facts.collection_comparable_results
            )
            session.add_all(
                self._pairwise_row(collection_id, build_id, position, item)
                for position, item in enumerate(facts.pairwise_comparison_relations)
            )
            session.flush()
            self._write_links(session, build_id, facts)

    def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> ComparisonFactSet:
        with self.session_factory() as session:
            resolved_build_id = self._resolve_read_build(
                session,
                collection_id,
                build_id,
            )
            if resolved_build_id is None:
                return ComparisonFactSet()
            marker = session.get(ComparisonBuild, resolved_build_id)
            if marker is None or marker.collection_id != collection_id:
                return ComparisonFactSet()

            evidence_links = self._read_links(
                session,
                comparable_result_evidence_links,
                resolved_build_id,
                "comparable_result_id",
                "evidence_id",
            )
            feature_links = self._read_links(
                session,
                comparable_result_feature_links,
                resolved_build_id,
                "comparable_result_id",
                "feature_id",
            )
            observation_links = self._read_links(
                session,
                comparable_result_observation_links,
                resolved_build_id,
                "comparable_result_id",
                "observation_id",
            )
            direct_anchors: dict[str, list[str]] = defaultdict(list)
            contextual_anchors: dict[str, list[str]] = defaultdict(list)
            for row in session.execute(
                select(comparable_result_anchor_links)
                .where(comparable_result_anchor_links.c.build_id == resolved_build_id)
                .order_by(
                    comparable_result_anchor_links.c.comparable_result_id,
                    comparable_result_anchor_links.c.link_kind,
                    comparable_result_anchor_links.c.position,
                )
            ).mappings():
                target = (
                    direct_anchors
                    if row["link_kind"] == "direct"
                    else contextual_anchors
                )
                target[str(row["comparable_result_id"])].append(str(row["anchor_id"]))

            comparable_results = tuple(
                self._comparable_record(
                    row,
                    direct_anchors,
                    contextual_anchors,
                    evidence_links,
                    feature_links,
                    observation_links,
                )
                for row in session.scalars(
                    select(ComparableResultRecord)
                    .where(ComparableResultRecord.build_id == resolved_build_id)
                    .order_by(ComparableResultRecord.result_order)
                )
            )
            scoped_results = tuple(
                self._scoped_record(row)
                for row in session.scalars(
                    select(CollectionComparableResultRecord)
                    .where(
                        CollectionComparableResultRecord.build_id == resolved_build_id
                    )
                    .order_by(
                        CollectionComparableResultRecord.sort_order.asc().nullslast(),
                        CollectionComparableResultRecord.comparable_result_id,
                    )
                )
            )
            pairwise_anchors = self._read_links(
                session,
                pairwise_comparison_anchor_links,
                resolved_build_id,
                "relation_id",
                "anchor_id",
            )
            pairwise_relations = tuple(
                self._pairwise_record(row, pairwise_anchors)
                for row in session.scalars(
                    select(PairwiseComparisonRelationRecord)
                    .where(
                        PairwiseComparisonRelationRecord.build_id == resolved_build_id
                    )
                    .order_by(PairwiseComparisonRelationRecord.relation_order)
                )
            )
            return ComparisonFactSet(
                comparison_artifacts_ready=marker.comparison_artifacts_ready,
                comparable_results=comparable_results,
                collection_comparable_results=scoped_results,
                pairwise_comparison_relations=pairwise_relations,
            )

    def _validate_facts(
        self,
        session: Session,
        collection_id: str,
        build_id: str,
        facts: ComparisonFactSet,
    ) -> dict[str, str]:
        result_ids = self._unique_ids(
            (item.comparable_result_id for item in facts.comparable_results),
            "comparable result",
        )
        self._unique_ids(
            (item.relation_id for item in facts.pairwise_comparison_relations),
            "pairwise relation",
        )
        source_kinds: dict[str, str] = {}
        for item in facts.comparable_results:
            source_kind = self._validate_comparable_source(
                session,
                collection_id,
                build_id,
                item,
            )
            source_kinds[item.comparable_result_id] = source_kind
            self._validate_comparable_links(
                session,
                collection_id,
                build_id,
                item,
                source_kind,
            )
        scoped_ids = self._unique_ids(
            (item.comparable_result_id for item in facts.collection_comparable_results),
            "collection comparable result",
        )
        if scoped_ids - result_ids:
            raise ValueError("collection comparable result has no same-build result")
        if any(
            item.collection_id != collection_id
            for item in facts.collection_comparable_results
        ):
            raise ValueError(
                "collection comparable result belongs to another collection"
            )
        for relation in facts.pairwise_comparison_relations:
            self._validate_pairwise_relation(
                session,
                collection_id,
                build_id,
                relation,
            )
        return source_kinds

    def _validate_comparable_source(
        self,
        session: Session,
        collection_id: str,
        build_id: str,
        item: ComparableResult,
    ) -> str:
        paper_source = session.get(
            PaperFactMeasurementResult,
            (build_id, item.source_result_id),
        )
        if paper_source is None:
            raise ValueError("comparable source result must resolve to paper measurement")
        source = paper_source
        if (
            source.collection_id != collection_id
            or source.source_document_id != item.source_document_id
        ):
            raise ValueError(
                "comparable source result has cross-build document lineage"
            )
        return "paper_measurement"

    def _validate_comparable_links(
        self,
        session: Session,
        collection_id: str,
        build_id: str,
        item: ComparableResult,
        source_kind: str,
    ) -> None:
        self._require_document_records(
            session,
            PaperFactEvidenceAnchor,
            build_id,
            (*item.evidence.direct_anchor_ids, *item.evidence.contextual_anchor_ids),
            item.source_document_id,
            "evidence anchor",
        )
        self._require_document_records(
            session,
            PaperFactStructureFeature,
            build_id,
            item.evidence.structure_feature_ids,
            item.source_document_id,
            "structure feature",
        )
        self._require_document_records(
            session,
            PaperFactCharacterizationObservation,
            build_id,
            item.evidence.characterization_observation_ids,
            item.source_document_id,
            "characterization observation",
        )
        expected_evidence_id = (
            f"ev_result_{item.source_result_id}"
            if source_kind == "paper_measurement"
            else item.source_result_id
        )
        if any(value != expected_evidence_id for value in item.evidence.evidence_ids):
            raise ValueError("comparison evidence id does not match its source result")
        if source_kind != "paper_measurement":
            return
        for model, value, label in (
            (PaperFactSampleVariant, item.binding.variant_id, "sample variant"),
            (PaperFactBaselineReference, item.binding.baseline_id, "baseline"),
            (PaperFactTestCondition, item.binding.test_condition_id, "test condition"),
        ):
            if value is None:
                continue
            self._require_document_records(
                session,
                model,
                build_id,
                (value,),
                item.source_document_id,
                label,
            )

    def _validate_pairwise_relation(
        self,
        session: Session,
        collection_id: str,
        build_id: str,
        item: PairwiseComparisonRelation,
    ) -> None:
        if item.collection_id != collection_id:
            raise ValueError("pairwise relation belongs to another collection")
        for result_id in (item.current_result_id, item.reference_result_id):
            self._require_document_records(
                session,
                PaperFactMeasurementResult,
                build_id,
                (result_id,),
                item.document_id,
                "pairwise result",
            )
        for variant_id in (item.current_variant_id, item.reference_variant_id):
            self._require_document_records(
                session,
                PaperFactSampleVariant,
                build_id,
                (variant_id,),
                item.document_id,
                "pairwise variant",
            )
        self._require_document_records(
            session,
            PaperFactEvidenceAnchor,
            build_id,
            item.evidence_anchor_ids,
            item.document_id,
            "pairwise evidence anchor",
        )

    def _require_document_records(
        self,
        session: Session,
        model: type,
        build_id: str,
        record_ids: tuple[str, ...],
        source_document_id: str,
        label: str,
    ) -> None:
        id_column = {
            PaperFactEvidenceAnchor: PaperFactEvidenceAnchor.anchor_id,
            PaperFactStructureFeature: PaperFactStructureFeature.feature_id,
            PaperFactCharacterizationObservation: PaperFactCharacterizationObservation.observation_id,
            PaperFactSampleVariant: PaperFactSampleVariant.variant_id,
            PaperFactBaselineReference: PaperFactBaselineReference.baseline_id,
            PaperFactTestCondition: PaperFactTestCondition.test_condition_id,
            PaperFactMeasurementResult: PaperFactMeasurementResult.result_id,
        }[model]
        for record_id in record_ids:
            row = session.scalar(
                select(model).where(
                    model.build_id == build_id,
                    id_column == record_id,
                )
            )
            if row is None or row.source_document_id != source_document_id:
                raise ValueError(f"{label} has missing or cross-build lineage")

    def _delete_build_records(self, session: Session, build_id: str) -> None:
        session.execute(
            delete(pairwise_comparison_anchor_links).where(
                pairwise_comparison_anchor_links.c.build_id == build_id
            )
        )
        for table in _RESULT_LINK_TABLES:
            session.execute(delete(table).where(table.c.build_id == build_id))
        for model in (
            CollectionComparableResultRecord,
            PairwiseComparisonRelationRecord,
            ComparableResultRecord,
            ComparisonBuild,
        ):
            session.execute(delete(model).where(model.build_id == build_id))

    def _write_links(
        self,
        session: Session,
        build_id: str,
        facts: ComparisonFactSet,
    ) -> None:
        for item in facts.comparable_results:
            for link_kind, values in (
                ("direct", item.evidence.direct_anchor_ids),
                ("contextual", item.evidence.contextual_anchor_ids),
            ):
                if values:
                    session.execute(
                        comparable_result_anchor_links.insert(),
                        [
                            {
                                "build_id": build_id,
                                "comparable_result_id": item.comparable_result_id,
                                "link_kind": link_kind,
                                "anchor_id": value,
                                "position": position,
                            }
                            for position, value in enumerate(values)
                        ],
                    )
            for table, column, values in (
                (
                    comparable_result_evidence_links,
                    "evidence_id",
                    item.evidence.evidence_ids,
                ),
                (
                    comparable_result_feature_links,
                    "feature_id",
                    item.evidence.structure_feature_ids,
                ),
                (
                    comparable_result_observation_links,
                    "observation_id",
                    item.evidence.characterization_observation_ids,
                ),
            ):
                if values:
                    session.execute(
                        table.insert(),
                        [
                            {
                                "build_id": build_id,
                                "comparable_result_id": item.comparable_result_id,
                                column: value,
                                "position": position,
                            }
                            for position, value in enumerate(values)
                        ],
                    )
        for item in facts.pairwise_comparison_relations:
            if item.evidence_anchor_ids:
                session.execute(
                    pairwise_comparison_anchor_links.insert(),
                    [
                        {
                            "build_id": build_id,
                            "relation_id": item.relation_id,
                            "anchor_id": value,
                            "position": position,
                        }
                        for position, value in enumerate(item.evidence_anchor_ids)
                    ],
                )

    def _comparable_row(
        self,
        collection_id: str,
        build_id: str,
        position: int,
        item: ComparableResult,
        source_kind: str,
    ) -> ComparableResultRecord:
        return ComparableResultRecord(
            build_id=build_id,
            comparable_result_id=item.comparable_result_id,
            collection_id=collection_id,
            result_order=position,
            source_kind=source_kind,
            paper_result_id=(
                item.source_result_id if source_kind == "paper_measurement" else None
            ),
            source_document_id=item.source_document_id,
            variant_id=item.binding.variant_id,
            baseline_id=item.binding.baseline_id,
            test_condition_id=item.binding.test_condition_id,
            material_system_normalized=item.normalized_context.material_system_normalized,
            process_normalized=item.normalized_context.process_normalized,
            baseline_normalized=item.normalized_context.baseline_normalized,
            test_condition_normalized=item.normalized_context.test_condition_normalized,
            axis_name=item.axis.axis_name,
            axis_value=item.axis.axis_value,
            axis_unit=item.axis.axis_unit,
            property_normalized=item.value.property_normalized,
            result_type=item.value.result_type,
            numeric_value=item.value.numeric_value,
            unit=item.value.unit,
            summary=item.value.summary,
            statistic_type=item.value.statistic_type,
            uncertainty=item.value.uncertainty,
            traceability_status=item.evidence.traceability_status,
            variant_label=item.variant_label,
            baseline_reference=item.baseline_reference,
            result_source_type=item.result_source_type,
            epistemic_status=item.epistemic_status,
            normalization_version=item.normalization_version,
        )

    def _scoped_row(
        self,
        collection_id: str,
        build_id: str,
        item: CollectionComparableResult,
    ) -> CollectionComparableResultRecord:
        assessment = item.assessment
        return CollectionComparableResultRecord(
            build_id=build_id,
            comparable_result_id=item.comparable_result_id,
            collection_id=collection_id,
            missing_critical_context=list(assessment.missing_critical_context),
            comparability_basis=list(assessment.comparability_basis),
            comparability_warnings=list(assessment.comparability_warnings),
            comparability_status=assessment.comparability_status,
            requires_expert_review=assessment.requires_expert_review,
            assessment_epistemic_status=assessment.assessment_epistemic_status,
            epistemic_status=item.epistemic_status,
            included=item.included,
            sort_order=item.sort_order,
            policy_family=item.policy_family,
            policy_version=item.policy_version,
            comparable_result_normalization_version=item.comparable_result_normalization_version,
            assessment_input_fingerprint=item.assessment_input_fingerprint,
            reassessment_triggers=list(item.reassessment_triggers),
        )

    def _pairwise_row(
        self,
        collection_id: str,
        build_id: str,
        position: int,
        item: PairwiseComparisonRelation,
    ) -> PairwiseComparisonRelationRecord:
        return PairwiseComparisonRelationRecord(
            build_id=build_id,
            relation_id=item.relation_id,
            collection_id=collection_id,
            relation_order=position,
            source_document_id=item.document_id,
            current_variant_id=item.current_variant_id,
            reference_variant_id=item.reference_variant_id,
            comparison_axis=item.comparison_axis,
            property_normalized=item.property_normalized,
            current_result_id=item.current_result_id,
            reference_result_id=item.reference_result_id,
            current_value=item.current_value,
            reference_value=item.reference_value,
            unit=item.unit,
            direction=item.direction,
            relation_payload=dict(item.relation_payload),
            confidence=item.confidence,
            epistemic_status=item.epistemic_status,
            relation_version=item.relation_version,
        )

    def _comparable_record(
        self,
        row: ComparableResultRecord,
        direct_anchors: dict[str, list[str]],
        contextual_anchors: dict[str, list[str]],
        evidence_links: dict[str, list[str]],
        feature_links: dict[str, list[str]],
        observation_links: dict[str, list[str]],
    ) -> ComparableResult:
        result_id = row.comparable_result_id
        return ComparableResult.from_mapping(
            {
                "comparable_result_id": result_id,
                "source_result_id": row.paper_result_id,
                "source_document_id": row.source_document_id,
                "binding": {
                    "variant_id": row.variant_id,
                    "baseline_id": row.baseline_id,
                    "test_condition_id": row.test_condition_id,
                },
                "normalized_context": {
                    "material_system_normalized": row.material_system_normalized,
                    "process_normalized": row.process_normalized,
                    "baseline_normalized": row.baseline_normalized,
                    "test_condition_normalized": row.test_condition_normalized,
                },
                "axis": {
                    "axis_name": row.axis_name,
                    "axis_value": row.axis_value,
                    "axis_unit": row.axis_unit,
                },
                "value": {
                    "property_normalized": row.property_normalized,
                    "result_type": row.result_type,
                    "numeric_value": row.numeric_value,
                    "unit": row.unit,
                    "summary": row.summary,
                    "statistic_type": row.statistic_type,
                    "uncertainty": row.uncertainty,
                },
                "evidence": {
                    "direct_anchor_ids": direct_anchors[result_id],
                    "contextual_anchor_ids": contextual_anchors[result_id],
                    "evidence_ids": evidence_links[result_id],
                    "structure_feature_ids": feature_links[result_id],
                    "characterization_observation_ids": observation_links[result_id],
                    "traceability_status": row.traceability_status,
                },
                "variant_label": row.variant_label,
                "baseline_reference": row.baseline_reference,
                "result_source_type": row.result_source_type,
                "epistemic_status": row.epistemic_status,
                "normalization_version": row.normalization_version,
            }
        )

    def _scoped_record(
        self,
        row: CollectionComparableResultRecord,
    ) -> CollectionComparableResult:
        return CollectionComparableResult.from_mapping(
            {
                "collection_id": row.collection_id,
                "comparable_result_id": row.comparable_result_id,
                "assessment": {
                    "missing_critical_context": row.missing_critical_context,
                    "comparability_basis": row.comparability_basis,
                    "comparability_warnings": row.comparability_warnings,
                    "comparability_status": row.comparability_status,
                    "requires_expert_review": row.requires_expert_review,
                    "assessment_epistemic_status": row.assessment_epistemic_status,
                },
                "epistemic_status": row.epistemic_status,
                "included": row.included,
                "sort_order": row.sort_order,
                "policy_family": row.policy_family,
                "policy_version": row.policy_version,
                "comparable_result_normalization_version": row.comparable_result_normalization_version,
                "assessment_input_fingerprint": row.assessment_input_fingerprint,
                "reassessment_triggers": row.reassessment_triggers,
            }
        )

    def _pairwise_record(
        self,
        row: PairwiseComparisonRelationRecord,
        anchors: dict[str, list[str]],
    ) -> PairwiseComparisonRelation:
        return PairwiseComparisonRelation.from_mapping(
            {
                "relation_id": row.relation_id,
                "collection_id": row.collection_id,
                "document_id": row.source_document_id,
                "current_variant_id": row.current_variant_id,
                "reference_variant_id": row.reference_variant_id,
                "comparison_axis": row.comparison_axis,
                "property_normalized": row.property_normalized,
                "current_result_id": row.current_result_id,
                "reference_result_id": row.reference_result_id,
                "current_value": row.current_value,
                "reference_value": row.reference_value,
                "unit": row.unit,
                "direction": row.direction,
                "evidence_anchor_ids": anchors[row.relation_id],
                "relation_payload": row.relation_payload,
                "confidence": row.confidence,
                "epistemic_status": row.epistemic_status,
                "relation_version": row.relation_version,
            }
        )

    def _read_links(
        self,
        session: Session,
        table: Table,
        build_id: str,
        owner_column: str,
        value_column: str,
    ) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for row in session.execute(
            select(table)
            .where(table.c.build_id == build_id)
            .order_by(table.c[owner_column], table.c.position)
        ).mappings():
            grouped[str(row[owner_column])].append(str(row[value_column]))
        return grouped

    def _resolve_read_build(
        self,
        session: Session,
        collection_id: str,
        build_id: str | None,
    ) -> str | None:
        if build_id is not None:
            build = session.get(CollectionBuild, build_id)
            return (
                build_id
                if build is not None and build.collection_id == collection_id
                else None
            )
        active = session.get(CollectionActiveBuild, collection_id)
        return active.build_id if active is not None else None

    def _require_writable_build(
        self,
        session: Session,
        collection_id: str,
        build_id: str,
    ) -> None:
        build = session.get(CollectionBuild, build_id)
        if (
            build is None
            or build.collection_id != collection_id
            or build.status not in {"queued", "building"}
        ):
            raise ValueError("collection build is not writable")

    def _unique_ids(self, values: Any, label: str) -> set[str]:
        identifiers = list(values)
        if any(not value for value in identifiers) or len(set(identifiers)) != len(
            identifiers
        ):
            raise ValueError(f"{label} ids must be non-empty and unique")
        return set(identifiers)


__all__ = ["PostgresComparisonRepository"]
