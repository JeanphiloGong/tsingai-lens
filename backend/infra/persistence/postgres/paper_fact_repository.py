"""Build-versioned PostgreSQL persistence for document profiles and paper facts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import Table, delete, select
from sqlalchemy.orm import Session, sessionmaker

from domain.core.document_profile import DocumentProfile
from domain.core.evidence_backbone import (
    BaselineReference,
    CharacterizationObservation,
    EvidenceAnchor,
    MeasurementResult,
    MethodFact,
    SampleVariant,
    StructureFeature,
    TestCondition,
)
from domain.core.paper_fact import PaperFactSet
from infra.persistence.postgres.models.build import (
    CollectionActiveBuild,
    CollectionBuild,
)
from infra.persistence.postgres.models.paper_fact import (
    PaperFactBaselineReference,
    PaperFactBuild,
    PaperFactCharacterizationObservation,
    PaperFactDocumentProfile,
    PaperFactEvidenceAnchor,
    PaperFactMeasurementResult,
    PaperFactMethod,
    PaperFactSampleVariant,
    PaperFactStructureFeature,
    PaperFactTestCondition,
    paper_fact_baseline_evidence_anchors,
    paper_fact_condition_evidence_anchors,
    paper_fact_feature_observations,
    paper_fact_method_evidence_anchors,
    paper_fact_observation_evidence_anchors,
    paper_fact_result_evidence_anchors,
    paper_fact_result_observations,
    paper_fact_result_structure_features,
    paper_fact_variant_evidence_anchors,
    paper_fact_variant_structure_features,
)
from infra.persistence.postgres.models.source import SourceDocument


_LINK_TABLES = (
    paper_fact_result_evidence_anchors,
    paper_fact_result_observations,
    paper_fact_result_structure_features,
    paper_fact_variant_evidence_anchors,
    paper_fact_variant_structure_features,
    paper_fact_condition_evidence_anchors,
    paper_fact_baseline_evidence_anchors,
    paper_fact_observation_evidence_anchors,
    paper_fact_feature_observations,
    paper_fact_method_evidence_anchors,
)


class PostgresPaperFactRepository:
    """Store one immutable paper-fact aggregate per collection build."""

    backend_name = "postgres"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def replace_document_profiles(
        self,
        collection_id: str,
        build_id: str,
        document_profiles: tuple[DocumentProfile, ...],
    ) -> None:
        with self.session_factory.begin() as session:
            self._require_writable_build(session, collection_id, build_id)
            lineage = self._source_document_lineage(session, collection_id, build_id)
            marker = session.get(PaperFactBuild, build_id)
            if marker is None:
                session.add(
                    PaperFactBuild(
                        build_id=build_id,
                        collection_id=collection_id,
                        paper_facts_ready=False,
                    )
                )
            session.execute(
                delete(PaperFactDocumentProfile).where(
                    PaperFactDocumentProfile.build_id == build_id
                )
            )
            session.add_all(
                PaperFactDocumentProfile(
                    build_id=build_id,
                    source_document_id=profile.document_id,
                    collection_id=collection_id,
                    document_version_id=self._document_version_id(
                        lineage,
                        collection_id,
                        profile.document_id,
                        profile.collection_id,
                    ),
                    profile_order=position,
                    title=profile.title,
                    source_filename=profile.source_filename,
                    doc_type=profile.doc_type,
                    parsing_warnings=list(profile.parsing_warnings),
                    confidence=profile.confidence,
                )
                for position, profile in enumerate(document_profiles)
            )

    def replace_paper_facts(
        self,
        collection_id: str,
        build_id: str,
        facts: PaperFactSet,
    ) -> None:
        with self.session_factory.begin() as session:
            self._require_writable_build(session, collection_id, build_id)
            lineage = self._source_document_lineage(session, collection_id, build_id)
            marker = session.get(PaperFactBuild, build_id)
            if marker is None:
                marker = PaperFactBuild(
                    build_id=build_id,
                    collection_id=collection_id,
                    paper_facts_ready=facts.paper_facts_ready,
                )
                session.add(marker)
            else:
                marker.paper_facts_ready = facts.paper_facts_ready

            for table in _LINK_TABLES:
                session.execute(delete(table).where(table.c.build_id == build_id))
            for model in (
                PaperFactMeasurementResult,
                PaperFactBaselineReference,
                PaperFactStructureFeature,
                PaperFactCharacterizationObservation,
                PaperFactTestCondition,
                PaperFactSampleVariant,
                PaperFactMethod,
                PaperFactEvidenceAnchor,
            ):
                session.execute(delete(model).where(model.build_id == build_id))

            session.add_all(
                self._anchor_row(collection_id, build_id, lineage, position, item)
                for position, item in enumerate(facts.evidence_anchors)
            )
            session.add_all(
                self._method_row(collection_id, build_id, lineage, position, item)
                for position, item in enumerate(facts.method_facts)
            )
            session.add_all(
                self._variant_row(collection_id, build_id, lineage, position, item)
                for position, item in enumerate(facts.sample_variants)
            )
            session.add_all(
                self._condition_row(collection_id, build_id, lineage, position, item)
                for position, item in enumerate(facts.test_conditions)
            )
            session.flush()
            session.add_all(
                self._baseline_row(collection_id, build_id, lineage, position, item)
                for position, item in enumerate(facts.baseline_references)
            )
            session.add_all(
                self._observation_row(collection_id, build_id, lineage, position, item)
                for position, item in enumerate(facts.characterization_observations)
            )
            session.add_all(
                self._feature_row(collection_id, build_id, lineage, position, item)
                for position, item in enumerate(facts.structure_features)
            )
            session.flush()
            session.add_all(
                self._result_row(collection_id, build_id, lineage, position, item)
                for position, item in enumerate(facts.measurement_results)
            )
            session.flush()

            self._write_links(session, build_id, facts)

    def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> PaperFactSet:
        with self.session_factory() as session:
            resolved_build_id = self._resolve_read_build(
                session,
                collection_id,
                build_id,
            )
            if resolved_build_id is None:
                return PaperFactSet()
            marker = session.get(PaperFactBuild, resolved_build_id)
            if marker is None or marker.collection_id != collection_id:
                return PaperFactSet()

            method_anchors = self._read_links(
                session,
                paper_fact_method_evidence_anchors,
                resolved_build_id,
                "method_id",
                "anchor_id",
            )
            variant_features = self._read_links(
                session,
                paper_fact_variant_structure_features,
                resolved_build_id,
                "variant_id",
                "feature_id",
            )
            variant_anchors = self._read_links(
                session,
                paper_fact_variant_evidence_anchors,
                resolved_build_id,
                "variant_id",
                "anchor_id",
            )
            condition_anchors = self._read_links(
                session,
                paper_fact_condition_evidence_anchors,
                resolved_build_id,
                "test_condition_id",
                "anchor_id",
            )
            baseline_anchors = self._read_links(
                session,
                paper_fact_baseline_evidence_anchors,
                resolved_build_id,
                "baseline_id",
                "anchor_id",
            )
            observation_anchors = self._read_links(
                session,
                paper_fact_observation_evidence_anchors,
                resolved_build_id,
                "observation_id",
                "anchor_id",
            )
            feature_observations = self._read_links(
                session,
                paper_fact_feature_observations,
                resolved_build_id,
                "feature_id",
                "observation_id",
            )
            result_features = self._read_links(
                session,
                paper_fact_result_structure_features,
                resolved_build_id,
                "result_id",
                "feature_id",
            )
            result_observations = self._read_links(
                session,
                paper_fact_result_observations,
                resolved_build_id,
                "result_id",
                "observation_id",
            )
            result_anchors = self._read_links(
                session,
                paper_fact_result_evidence_anchors,
                resolved_build_id,
                "result_id",
                "anchor_id",
            )

            return PaperFactSet(
                paper_facts_ready=marker.paper_facts_ready,
                document_profiles=tuple(
                    DocumentProfile.from_mapping(
                        {
                            "document_id": row.source_document_id,
                            "collection_id": row.collection_id,
                            "title": row.title,
                            "source_filename": row.source_filename,
                            "doc_type": row.doc_type,
                            "parsing_warnings": row.parsing_warnings,
                            "confidence": row.confidence,
                        }
                    )
                    for row in self._ordered_rows(
                        session,
                        PaperFactDocumentProfile,
                        collection_id,
                        resolved_build_id,
                        PaperFactDocumentProfile.profile_order,
                        PaperFactDocumentProfile.source_document_id,
                    )
                ),
                evidence_anchors=tuple(
                    EvidenceAnchor.from_mapping(
                        {
                            "anchor_id": row.anchor_id,
                            "document_id": row.source_document_id,
                            "locator_type": row.locator_type,
                            "locator_confidence": row.locator_confidence,
                            "source_type": row.source_type,
                            "section_id": row.section_id,
                            "char_range": row.char_range_json,
                            "bbox": row.bbox_json,
                            "page": row.page,
                            "quote": row.quote,
                            "deep_link": row.deep_link,
                            "block_id": row.block_id,
                            "snippet_id": row.snippet_id,
                            "figure_or_table": row.figure_or_table,
                            "quote_span": row.quote_span,
                        }
                    )
                    for row in self._ordered_rows(
                        session,
                        PaperFactEvidenceAnchor,
                        collection_id,
                        resolved_build_id,
                        PaperFactEvidenceAnchor.anchor_order,
                        PaperFactEvidenceAnchor.anchor_id,
                    )
                ),
                method_facts=tuple(
                    MethodFact.from_mapping(
                        {
                            "method_id": row.method_id,
                            "document_id": row.source_document_id,
                            "collection_id": row.collection_id,
                            "domain_profile": row.domain_profile,
                            "method_role": row.method_role,
                            "method_name": row.method_name,
                            "method_payload": row.method_payload,
                            "evidence_anchor_ids": method_anchors[row.method_id],
                            "confidence": row.confidence,
                            "epistemic_status": row.epistemic_status,
                        }
                    )
                    for row in self._ordered_rows(
                        session,
                        PaperFactMethod,
                        collection_id,
                        resolved_build_id,
                        PaperFactMethod.fact_order,
                        PaperFactMethod.method_id,
                    )
                ),
                sample_variants=tuple(
                    SampleVariant.from_mapping(
                        {
                            "variant_id": row.variant_id,
                            "document_id": row.source_document_id,
                            "collection_id": row.collection_id,
                            "domain_profile": row.domain_profile,
                            "variant_label": row.variant_label,
                            "host_material_system": row.host_material_system,
                            "composition": row.composition,
                            "variable_axis_type": row.variable_axis_type,
                            "variable_value": row.variable_value,
                            "process_context": row.process_context,
                            "profile_payload": row.profile_payload,
                            "structure_feature_ids": variant_features[row.variant_id],
                            "source_anchor_ids": variant_anchors[row.variant_id],
                            "confidence": row.confidence,
                            "epistemic_status": row.epistemic_status,
                        }
                    )
                    for row in self._ordered_rows(
                        session,
                        PaperFactSampleVariant,
                        collection_id,
                        resolved_build_id,
                        PaperFactSampleVariant.fact_order,
                        PaperFactSampleVariant.variant_id,
                    )
                ),
                test_conditions=tuple(
                    TestCondition.from_mapping(
                        {
                            "test_condition_id": row.test_condition_id,
                            "document_id": row.source_document_id,
                            "collection_id": row.collection_id,
                            "domain_profile": row.domain_profile,
                            "property_type": row.property_type,
                            "template_type": row.template_type,
                            "scope_level": row.scope_level,
                            "condition_payload": row.condition_payload,
                            "condition_completeness": row.condition_completeness,
                            "missing_fields": row.missing_fields,
                            "evidence_anchor_ids": condition_anchors[
                                row.test_condition_id
                            ],
                            "confidence": row.confidence,
                            "epistemic_status": row.epistemic_status,
                        }
                    )
                    for row in self._ordered_rows(
                        session,
                        PaperFactTestCondition,
                        collection_id,
                        resolved_build_id,
                        PaperFactTestCondition.fact_order,
                        PaperFactTestCondition.test_condition_id,
                    )
                ),
                baseline_references=tuple(
                    BaselineReference.from_mapping(
                        {
                            "baseline_id": row.baseline_id,
                            "document_id": row.source_document_id,
                            "collection_id": row.collection_id,
                            "domain_profile": row.domain_profile,
                            "variant_id": row.variant_id,
                            "baseline_type": row.baseline_type,
                            "baseline_label": row.baseline_label,
                            "baseline_scope": row.baseline_scope,
                            "evidence_anchor_ids": baseline_anchors[row.baseline_id],
                            "confidence": row.confidence,
                            "epistemic_status": row.epistemic_status,
                        }
                    )
                    for row in self._ordered_rows(
                        session,
                        PaperFactBaselineReference,
                        collection_id,
                        resolved_build_id,
                        PaperFactBaselineReference.fact_order,
                        PaperFactBaselineReference.baseline_id,
                    )
                ),
                measurement_results=tuple(
                    MeasurementResult.from_mapping(
                        {
                            "result_id": row.result_id,
                            "document_id": row.source_document_id,
                            "collection_id": row.collection_id,
                            "domain_profile": row.domain_profile,
                            "variant_id": row.variant_id,
                            "property_normalized": row.property_normalized,
                            "result_type": row.result_type,
                            "claim_scope": row.claim_scope,
                            "value_payload": row.value_payload,
                            "unit": row.unit,
                            "test_condition_id": row.test_condition_id,
                            "baseline_id": row.baseline_id,
                            "structure_feature_ids": result_features[row.result_id],
                            "characterization_observation_ids": result_observations[
                                row.result_id
                            ],
                            "evidence_anchor_ids": result_anchors[row.result_id],
                            "traceability_status": row.traceability_status,
                            "result_source_type": row.result_source_type,
                            "epistemic_status": row.epistemic_status,
                        }
                    )
                    for row in self._ordered_rows(
                        session,
                        PaperFactMeasurementResult,
                        collection_id,
                        resolved_build_id,
                        PaperFactMeasurementResult.fact_order,
                        PaperFactMeasurementResult.result_id,
                    )
                ),
                characterization_observations=tuple(
                    CharacterizationObservation.from_mapping(
                        {
                            "observation_id": row.observation_id,
                            "document_id": row.source_document_id,
                            "collection_id": row.collection_id,
                            "variant_id": row.variant_id,
                            "characterization_type": row.characterization_type,
                            "observation_text": row.observation_text,
                            "observed_value": row.observed_value,
                            "observed_unit": row.observed_unit,
                            "condition_context": row.condition_context,
                            "evidence_anchor_ids": observation_anchors[
                                row.observation_id
                            ],
                            "confidence": row.confidence,
                            "epistemic_status": row.epistemic_status,
                        }
                    )
                    for row in self._ordered_rows(
                        session,
                        PaperFactCharacterizationObservation,
                        collection_id,
                        resolved_build_id,
                        PaperFactCharacterizationObservation.fact_order,
                        PaperFactCharacterizationObservation.observation_id,
                    )
                ),
                structure_features=tuple(
                    StructureFeature.from_mapping(
                        {
                            "feature_id": row.feature_id,
                            "document_id": row.source_document_id,
                            "collection_id": row.collection_id,
                            "variant_id": row.variant_id,
                            "feature_type": row.feature_type,
                            "feature_value": row.feature_value,
                            "feature_unit": row.feature_unit,
                            "qualitative_descriptor": row.qualitative_descriptor,
                            "source_observation_ids": feature_observations[
                                row.feature_id
                            ],
                            "confidence": row.confidence,
                            "epistemic_status": row.epistemic_status,
                        }
                    )
                    for row in self._ordered_rows(
                        session,
                        PaperFactStructureFeature,
                        collection_id,
                        resolved_build_id,
                        PaperFactStructureFeature.fact_order,
                        PaperFactStructureFeature.feature_id,
                    )
                ),
            )

    @staticmethod
    def _anchor_row(
        collection_id: str,
        build_id: str,
        lineage: dict[str, str],
        position: int,
        item: EvidenceAnchor,
    ) -> PaperFactEvidenceAnchor:
        return PaperFactEvidenceAnchor(
            build_id=build_id,
            anchor_id=item.anchor_id,
            collection_id=collection_id,
            source_document_id=item.document_id,
            document_version_id=PostgresPaperFactRepository._document_version_id(
                lineage, collection_id, item.document_id
            ),
            anchor_order=position,
            locator_type=item.locator_type,
            locator_confidence=item.locator_confidence,
            source_type=item.source_type,
            section_id=item.section_id,
            char_range_json=item.char_range,
            bbox_json=item.bbox,
            page=item.page,
            quote=item.quote,
            deep_link=item.deep_link,
            block_id=item.block_id,
            snippet_id=item.snippet_id,
            figure_or_table=item.figure_or_table,
            quote_span=item.quote_span,
        )

    @staticmethod
    def _method_row(
        collection_id: str,
        build_id: str,
        lineage: dict[str, str],
        position: int,
        item: MethodFact,
    ) -> PaperFactMethod:
        return PaperFactMethod(
            build_id=build_id,
            method_id=item.method_id,
            collection_id=collection_id,
            source_document_id=item.document_id,
            document_version_id=PostgresPaperFactRepository._document_version_id(
                lineage, collection_id, item.document_id, item.collection_id
            ),
            fact_order=position,
            domain_profile=item.domain_profile,
            method_role=item.method_role,
            method_name=item.method_name,
            method_payload=item.method_payload,
            confidence=item.confidence,
            epistemic_status=item.epistemic_status,
        )

    @staticmethod
    def _variant_row(
        collection_id: str,
        build_id: str,
        lineage: dict[str, str],
        position: int,
        item: SampleVariant,
    ) -> PaperFactSampleVariant:
        return PaperFactSampleVariant(
            build_id=build_id,
            variant_id=item.variant_id,
            collection_id=collection_id,
            source_document_id=item.document_id,
            document_version_id=PostgresPaperFactRepository._document_version_id(
                lineage, collection_id, item.document_id, item.collection_id
            ),
            fact_order=position,
            domain_profile=item.domain_profile,
            variant_label=item.variant_label,
            host_material_system=item.host_material_system,
            composition=item.composition,
            variable_axis_type=item.variable_axis_type,
            variable_value=item.variable_value,
            process_context=item.process_context,
            profile_payload=item.profile_payload,
            confidence=item.confidence,
            epistemic_status=item.epistemic_status,
        )

    @staticmethod
    def _condition_row(
        collection_id: str,
        build_id: str,
        lineage: dict[str, str],
        position: int,
        item: TestCondition,
    ) -> PaperFactTestCondition:
        return PaperFactTestCondition(
            build_id=build_id,
            test_condition_id=item.test_condition_id,
            collection_id=collection_id,
            source_document_id=item.document_id,
            document_version_id=PostgresPaperFactRepository._document_version_id(
                lineage, collection_id, item.document_id, item.collection_id
            ),
            fact_order=position,
            domain_profile=item.domain_profile,
            property_type=item.property_type,
            template_type=item.template_type,
            scope_level=item.scope_level,
            condition_payload=item.condition_payload,
            condition_completeness=item.condition_completeness,
            missing_fields=list(item.missing_fields),
            confidence=item.confidence,
            epistemic_status=item.epistemic_status,
        )

    @staticmethod
    def _baseline_row(
        collection_id: str,
        build_id: str,
        lineage: dict[str, str],
        position: int,
        item: BaselineReference,
    ) -> PaperFactBaselineReference:
        return PaperFactBaselineReference(
            build_id=build_id,
            baseline_id=item.baseline_id,
            collection_id=collection_id,
            source_document_id=item.document_id,
            document_version_id=PostgresPaperFactRepository._document_version_id(
                lineage, collection_id, item.document_id, item.collection_id
            ),
            fact_order=position,
            domain_profile=item.domain_profile,
            variant_id=item.variant_id,
            baseline_type=item.baseline_type,
            baseline_label=item.baseline_label,
            baseline_scope=item.baseline_scope,
            confidence=item.confidence,
            epistemic_status=item.epistemic_status,
        )

    @staticmethod
    def _observation_row(
        collection_id: str,
        build_id: str,
        lineage: dict[str, str],
        position: int,
        item: CharacterizationObservation,
    ) -> PaperFactCharacterizationObservation:
        return PaperFactCharacterizationObservation(
            build_id=build_id,
            observation_id=item.observation_id,
            collection_id=collection_id,
            source_document_id=item.document_id,
            document_version_id=PostgresPaperFactRepository._document_version_id(
                lineage, collection_id, item.document_id, item.collection_id
            ),
            fact_order=position,
            variant_id=item.variant_id,
            characterization_type=item.characterization_type,
            observation_text=item.observation_text,
            observed_value=item.observed_value,
            observed_unit=item.observed_unit,
            condition_context=item.condition_context,
            confidence=item.confidence,
            epistemic_status=item.epistemic_status,
        )

    @staticmethod
    def _feature_row(
        collection_id: str,
        build_id: str,
        lineage: dict[str, str],
        position: int,
        item: StructureFeature,
    ) -> PaperFactStructureFeature:
        return PaperFactStructureFeature(
            build_id=build_id,
            feature_id=item.feature_id,
            collection_id=collection_id,
            source_document_id=item.document_id,
            document_version_id=PostgresPaperFactRepository._document_version_id(
                lineage, collection_id, item.document_id, item.collection_id
            ),
            fact_order=position,
            variant_id=item.variant_id,
            feature_type=item.feature_type,
            feature_value=item.feature_value,
            feature_unit=item.feature_unit,
            qualitative_descriptor=item.qualitative_descriptor,
            confidence=item.confidence,
            epistemic_status=item.epistemic_status,
        )

    @staticmethod
    def _result_row(
        collection_id: str,
        build_id: str,
        lineage: dict[str, str],
        position: int,
        item: MeasurementResult,
    ) -> PaperFactMeasurementResult:
        return PaperFactMeasurementResult(
            build_id=build_id,
            result_id=item.result_id,
            collection_id=collection_id,
            source_document_id=item.document_id,
            document_version_id=PostgresPaperFactRepository._document_version_id(
                lineage, collection_id, item.document_id, item.collection_id
            ),
            fact_order=position,
            domain_profile=item.domain_profile,
            variant_id=item.variant_id,
            property_normalized=item.property_normalized,
            result_type=item.result_type,
            claim_scope=item.claim_scope,
            value_payload=item.value_payload,
            unit=item.unit,
            test_condition_id=item.test_condition_id,
            baseline_id=item.baseline_id,
            traceability_status=item.traceability_status,
            result_source_type=item.result_source_type,
            epistemic_status=item.epistemic_status,
        )

    @staticmethod
    def _write_links(
        session: Session,
        build_id: str,
        facts: PaperFactSet,
    ) -> None:
        links: tuple[tuple[Table, list[dict[str, Any]]], ...] = (
            (
                paper_fact_method_evidence_anchors,
                [
                    {
                        "build_id": build_id,
                        "method_id": item.method_id,
                        "anchor_id": target_id,
                        "position": position,
                    }
                    for item in facts.method_facts
                    for position, target_id in enumerate(item.evidence_anchor_ids)
                ],
            ),
            (
                paper_fact_variant_structure_features,
                [
                    {
                        "build_id": build_id,
                        "variant_id": item.variant_id,
                        "feature_id": target_id,
                        "position": position,
                    }
                    for item in facts.sample_variants
                    for position, target_id in enumerate(item.structure_feature_ids)
                ],
            ),
            (
                paper_fact_variant_evidence_anchors,
                [
                    {
                        "build_id": build_id,
                        "variant_id": item.variant_id,
                        "anchor_id": target_id,
                        "position": position,
                    }
                    for item in facts.sample_variants
                    for position, target_id in enumerate(item.source_anchor_ids)
                ],
            ),
            (
                paper_fact_condition_evidence_anchors,
                [
                    {
                        "build_id": build_id,
                        "test_condition_id": item.test_condition_id,
                        "anchor_id": target_id,
                        "position": position,
                    }
                    for item in facts.test_conditions
                    for position, target_id in enumerate(item.evidence_anchor_ids)
                ],
            ),
            (
                paper_fact_baseline_evidence_anchors,
                [
                    {
                        "build_id": build_id,
                        "baseline_id": item.baseline_id,
                        "anchor_id": target_id,
                        "position": position,
                    }
                    for item in facts.baseline_references
                    for position, target_id in enumerate(item.evidence_anchor_ids)
                ],
            ),
            (
                paper_fact_observation_evidence_anchors,
                [
                    {
                        "build_id": build_id,
                        "observation_id": item.observation_id,
                        "anchor_id": target_id,
                        "position": position,
                    }
                    for item in facts.characterization_observations
                    for position, target_id in enumerate(item.evidence_anchor_ids)
                ],
            ),
            (
                paper_fact_feature_observations,
                [
                    {
                        "build_id": build_id,
                        "feature_id": item.feature_id,
                        "observation_id": target_id,
                        "position": position,
                    }
                    for item in facts.structure_features
                    for position, target_id in enumerate(item.source_observation_ids)
                ],
            ),
            (
                paper_fact_result_structure_features,
                [
                    {
                        "build_id": build_id,
                        "result_id": item.result_id,
                        "feature_id": target_id,
                        "position": position,
                    }
                    for item in facts.measurement_results
                    for position, target_id in enumerate(item.structure_feature_ids)
                ],
            ),
            (
                paper_fact_result_observations,
                [
                    {
                        "build_id": build_id,
                        "result_id": item.result_id,
                        "observation_id": target_id,
                        "position": position,
                    }
                    for item in facts.measurement_results
                    for position, target_id in enumerate(
                        item.characterization_observation_ids
                    )
                ],
            ),
            (
                paper_fact_result_evidence_anchors,
                [
                    {
                        "build_id": build_id,
                        "result_id": item.result_id,
                        "anchor_id": target_id,
                        "position": position,
                    }
                    for item in facts.measurement_results
                    for position, target_id in enumerate(item.evidence_anchor_ids)
                ],
            ),
        )
        for table, rows in links:
            if rows:
                session.execute(table.insert(), rows)

    @staticmethod
    def _ordered_rows(
        session: Session,
        model: Any,
        collection_id: str,
        build_id: str,
        order_column: Any,
        id_column: Any,
    ) -> list[Any]:
        return list(
            session.scalars(
                select(model)
                .where(
                    model.collection_id == collection_id,
                    model.build_id == build_id,
                )
                .order_by(order_column, id_column)
            )
        )

    @staticmethod
    def _read_links(
        session: Session,
        table: Table,
        build_id: str,
        owner_column: str,
        target_column: str,
    ) -> defaultdict[str, tuple[str, ...]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        owner = table.c[owner_column]
        target = table.c[target_column]
        for owner_id, target_id in session.execute(
            select(owner, target)
            .where(table.c.build_id == build_id)
            .order_by(owner, table.c.position, target)
        ):
            grouped[str(owner_id)].append(str(target_id))
        return defaultdict(tuple, {key: tuple(value) for key, value in grouped.items()})

    @staticmethod
    def _source_document_lineage(
        session: Session,
        collection_id: str,
        build_id: str,
    ) -> dict[str, str]:
        return {
            str(source_document_id): str(document_version_id)
            for source_document_id, document_version_id in session.execute(
                select(
                    SourceDocument.source_document_id,
                    SourceDocument.document_version_id,
                ).where(
                    SourceDocument.collection_id == collection_id,
                    SourceDocument.build_id == build_id,
                )
            )
        }

    @staticmethod
    def _document_version_id(
        lineage: dict[str, str],
        collection_id: str,
        source_document_id: str,
        record_collection_id: str | None = None,
    ) -> str:
        if record_collection_id and record_collection_id != collection_id:
            raise ValueError(f"paper fact collection mismatch: {record_collection_id}")
        try:
            return lineage[source_document_id]
        except KeyError as exc:
            raise FileNotFoundError(
                f"source document not found: {collection_id}/{source_document_id}"
            ) from exc

    @staticmethod
    def _require_build(
        session: Session,
        collection_id: str,
        build_id: str,
    ) -> CollectionBuild:
        build = session.get(CollectionBuild, build_id)
        if build is None or build.collection_id != collection_id:
            raise FileNotFoundError(
                f"collection build not found: {collection_id}/{build_id}"
            )
        return build

    @classmethod
    def _require_writable_build(
        cls,
        session: Session,
        collection_id: str,
        build_id: str,
    ) -> CollectionBuild:
        build = cls._require_build(session, collection_id, build_id)
        if build.status not in {"queued", "building"}:
            raise ValueError(f"collection build is not writable: {build_id}")
        return build

    @classmethod
    def _resolve_read_build(
        cls,
        session: Session,
        collection_id: str,
        build_id: str | None,
    ) -> str | None:
        if build_id is not None:
            cls._require_build(session, collection_id, build_id)
            return build_id
        return session.scalar(
            select(CollectionActiveBuild.build_id).where(
                CollectionActiveBuild.collection_id == collection_id
            )
        )


__all__ = ["PostgresPaperFactRepository"]
