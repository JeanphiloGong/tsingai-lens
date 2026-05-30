from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from config import DATA_DIR
from domain.core import (
    BaselineReference,
    CharacterizationObservation,
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
    CoreFactSet,
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
    MethodFact,
    MaterialReportArtifact,
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectiveLogicChain,
    ObjectivePaperFrame,
    ObjectiveReportArtifact,
    PaperSkim,
    PairwiseComparisonRelation,
    SampleVariant,
    ResearchObjective,
    StructureFeature,
    TestCondition,
)


@dataclass(frozen=True)
class _TableSpec:
    table_name: str
    attr_name: str
    record_cls: type
    id_column: str
    columns: tuple[str, ...]
    json_columns: frozenset[str] = frozenset()
    integer_columns: frozenset[str] = frozenset()
    real_columns: frozenset[str] = frozenset()
    boolean_columns: frozenset[str] = frozenset()
    index_columns: tuple[str, ...] = ()


_OBJECTIVE_TABLES: tuple[_TableSpec, ...] = (
    _TableSpec(
        table_name="core_paper_skims",
        attr_name="paper_skims",
        record_cls=PaperSkim,
        id_column="document_id",
        columns=(
            "document_id",
            "title",
            "source_filename",
            "doc_role",
            "candidate_materials",
            "candidate_processes",
            "candidate_properties",
            "changed_variables",
            "possible_objectives",
            "evidence_density",
            "confidence",
            "warnings",
        ),
        json_columns=frozenset(
            {
                "candidate_materials",
                "candidate_processes",
                "candidate_properties",
                "changed_variables",
                "possible_objectives",
                "warnings",
            }
        ),
        real_columns=frozenset({"confidence"}),
        index_columns=("document_id", "doc_role"),
    ),
    _TableSpec(
        table_name="core_research_objectives",
        attr_name="research_objectives",
        record_cls=ResearchObjective,
        id_column="objective_id",
        columns=(
            "objective_id",
            "question",
            "material_scope",
            "process_axes",
            "property_axes",
            "comparison_intent",
            "seed_document_ids",
            "excluded_document_ids",
            "confidence",
            "reason",
        ),
        json_columns=frozenset(
            {
                "material_scope",
                "process_axes",
                "property_axes",
                "seed_document_ids",
                "excluded_document_ids",
            }
        ),
        real_columns=frozenset({"confidence"}),
        index_columns=("objective_id",),
    ),
    _TableSpec(
        table_name="core_objective_contexts",
        attr_name="objective_contexts",
        record_cls=ObjectiveContext,
        id_column="objective_id",
        columns=(
            "objective_id",
            "question",
            "material_scope",
            "variable_process_axes",
            "process_context_axes",
            "target_property_axes",
            "excluded_property_axes",
            "routing_hints",
            "extraction_guidance",
            "confidence",
        ),
        json_columns=frozenset(
            {
                "material_scope",
                "variable_process_axes",
                "process_context_axes",
                "target_property_axes",
                "excluded_property_axes",
                "routing_hints",
                "extraction_guidance",
            }
        ),
        real_columns=frozenset({"confidence"}),
        index_columns=("objective_id",),
    ),
    _TableSpec(
        table_name="core_objective_paper_frames",
        attr_name="objective_paper_frames",
        record_cls=ObjectivePaperFrame,
        id_column="frame_id",
        columns=(
            "frame_id",
            "objective_id",
            "document_id",
            "relevance",
            "paper_role",
            "background",
            "material_match",
            "changed_variables",
            "measured_property_scope",
            "test_environment_scope",
            "relevant_sections",
            "relevant_tables",
            "excluded_tables",
        ),
        json_columns=frozenset(
            {
                "material_match",
                "changed_variables",
                "measured_property_scope",
                "test_environment_scope",
                "relevant_sections",
                "relevant_tables",
                "excluded_tables",
            }
        ),
        index_columns=("objective_id", "document_id", "relevance", "paper_role"),
    ),
    _TableSpec(
        table_name="core_objective_evidence_routes",
        attr_name="objective_evidence_routes",
        record_cls=ObjectiveEvidenceRoute,
        id_column="route_id",
        columns=(
            "route_id",
            "objective_id",
            "document_id",
            "source_kind",
            "source_ref",
            "role",
            "extractable",
            "reason",
            "table_schema",
            "column_roles",
            "join_keys",
            "join_plan",
            "confidence",
        ),
        json_columns=frozenset(
            {"table_schema", "column_roles", "join_keys", "join_plan"}
        ),
        boolean_columns=frozenset({"extractable"}),
        real_columns=frozenset({"confidence"}),
        index_columns=(
            "objective_id",
            "document_id",
            "source_kind",
            "source_ref",
            "role",
            "extractable",
        ),
    ),
    _TableSpec(
        table_name="core_objective_evidence_units",
        attr_name="objective_evidence_units",
        record_cls=ObjectiveEvidenceUnit,
        id_column="evidence_unit_id",
        columns=(
            "evidence_unit_id",
            "objective_id",
            "document_id",
            "unit_kind",
            "property_normalized",
            "material_system",
            "sample_context",
            "process_context",
            "resolved_condition",
            "test_condition",
            "value_payload",
            "unit",
            "baseline_context",
            "interpretation",
            "source_refs",
            "evidence_anchor_ids",
            "join_keys",
            "resolution_status",
            "confidence",
        ),
        json_columns=frozenset(
            {
                "material_system",
                "sample_context",
                "process_context",
                "resolved_condition",
                "test_condition",
                "value_payload",
                "baseline_context",
                "source_refs",
                "evidence_anchor_ids",
                "join_keys",
            }
        ),
        real_columns=frozenset({"confidence"}),
        index_columns=(
            "objective_id",
            "document_id",
            "unit_kind",
            "property_normalized",
            "resolution_status",
        ),
    ),
    _TableSpec(
        table_name="core_objective_logic_chains",
        attr_name="objective_logic_chains",
        record_cls=ObjectiveLogicChain,
        id_column="logic_chain_id",
        columns=(
            "logic_chain_id",
            "objective_id",
            "chain_scope",
            "document_id",
            "question",
            "evidence_unit_ids",
            "chain_payload",
            "summary",
            "confidence",
        ),
        json_columns=frozenset({"evidence_unit_ids", "chain_payload"}),
        real_columns=frozenset({"confidence"}),
        index_columns=("objective_id", "chain_scope", "document_id"),
    ),
)


_PAPER_FACT_TABLES: tuple[_TableSpec, ...] = (
    _TableSpec(
        table_name="core_document_profiles",
        attr_name="document_profiles",
        record_cls=DocumentProfile,
        id_column="document_id",
        columns=(
            "document_id",
            "collection_id",
            "title",
            "source_filename",
            "doc_type",
            "parsing_warnings",
            "confidence",
        ),
        json_columns=frozenset({"parsing_warnings"}),
        real_columns=frozenset({"confidence"}),
        index_columns=("document_id", "doc_type"),
    ),
    _TableSpec(
        table_name="core_evidence_anchors",
        attr_name="evidence_anchors",
        record_cls=EvidenceAnchor,
        id_column="anchor_id",
        columns=(
            "anchor_id",
            "document_id",
            "locator_type",
            "locator_confidence",
            "source_type",
            "section_id",
            "char_range",
            "bbox",
            "page",
            "quote",
            "deep_link",
            "block_id",
            "snippet_id",
            "figure_or_table",
            "quote_span",
        ),
        json_columns=frozenset({"char_range", "bbox"}),
        integer_columns=frozenset({"page"}),
        index_columns=("document_id", "source_type", "block_id", "figure_or_table"),
    ),
    _TableSpec(
        table_name="core_method_facts",
        attr_name="method_facts",
        record_cls=MethodFact,
        id_column="method_id",
        columns=(
            "method_id",
            "document_id",
            "collection_id",
            "domain_profile",
            "method_role",
            "method_name",
            "method_payload",
            "evidence_anchor_ids",
            "confidence",
            "epistemic_status",
        ),
        json_columns=frozenset({"method_payload", "evidence_anchor_ids"}),
        real_columns=frozenset({"confidence"}),
        index_columns=("document_id", "method_role"),
    ),
    _TableSpec(
        table_name="core_sample_variants",
        attr_name="sample_variants",
        record_cls=SampleVariant,
        id_column="variant_id",
        columns=(
            "variant_id",
            "document_id",
            "collection_id",
            "domain_profile",
            "variant_label",
            "host_material_system",
            "composition",
            "variable_axis_type",
            "variable_value",
            "process_context",
            "profile_payload",
            "structure_feature_ids",
            "source_anchor_ids",
            "confidence",
            "epistemic_status",
        ),
        json_columns=frozenset(
            {
                "host_material_system",
                "variable_value",
                "process_context",
                "profile_payload",
                "structure_feature_ids",
                "source_anchor_ids",
            }
        ),
        real_columns=frozenset({"confidence"}),
        index_columns=("document_id", "variant_label", "variable_axis_type"),
    ),
    _TableSpec(
        table_name="core_test_conditions",
        attr_name="test_conditions",
        record_cls=TestCondition,
        id_column="test_condition_id",
        columns=(
            "test_condition_id",
            "document_id",
            "collection_id",
            "domain_profile",
            "property_type",
            "template_type",
            "scope_level",
            "condition_payload",
            "condition_completeness",
            "missing_fields",
            "evidence_anchor_ids",
            "confidence",
            "epistemic_status",
        ),
        json_columns=frozenset(
            {"condition_payload", "missing_fields", "evidence_anchor_ids"}
        ),
        real_columns=frozenset({"confidence"}),
        index_columns=("document_id", "property_type", "template_type"),
    ),
    _TableSpec(
        table_name="core_baseline_references",
        attr_name="baseline_references",
        record_cls=BaselineReference,
        id_column="baseline_id",
        columns=(
            "baseline_id",
            "document_id",
            "collection_id",
            "domain_profile",
            "variant_id",
            "baseline_type",
            "baseline_label",
            "baseline_scope",
            "evidence_anchor_ids",
            "confidence",
            "epistemic_status",
        ),
        json_columns=frozenset({"evidence_anchor_ids"}),
        real_columns=frozenset({"confidence"}),
        index_columns=("document_id", "variant_id", "baseline_type"),
    ),
    _TableSpec(
        table_name="core_measurement_results",
        attr_name="measurement_results",
        record_cls=MeasurementResult,
        id_column="result_id",
        columns=(
            "result_id",
            "document_id",
            "collection_id",
            "domain_profile",
            "variant_id",
            "property_normalized",
            "result_type",
            "claim_scope",
            "value_payload",
            "unit",
            "test_condition_id",
            "baseline_id",
            "structure_feature_ids",
            "characterization_observation_ids",
            "evidence_anchor_ids",
            "traceability_status",
            "result_source_type",
            "epistemic_status",
        ),
        json_columns=frozenset(
            {
                "value_payload",
                "structure_feature_ids",
                "characterization_observation_ids",
                "evidence_anchor_ids",
            }
        ),
        index_columns=(
            "document_id",
            "variant_id",
            "property_normalized",
            "test_condition_id",
            "baseline_id",
        ),
    ),
    _TableSpec(
        table_name="core_characterization_observations",
        attr_name="characterization_observations",
        record_cls=CharacterizationObservation,
        id_column="observation_id",
        columns=(
            "observation_id",
            "document_id",
            "collection_id",
            "variant_id",
            "characterization_type",
            "observation_text",
            "observed_value",
            "observed_unit",
            "condition_context",
            "evidence_anchor_ids",
            "confidence",
            "epistemic_status",
        ),
        json_columns=frozenset(
            {"observed_value", "condition_context", "evidence_anchor_ids"}
        ),
        real_columns=frozenset({"confidence"}),
        index_columns=("document_id", "variant_id", "characterization_type"),
    ),
    _TableSpec(
        table_name="core_structure_features",
        attr_name="structure_features",
        record_cls=StructureFeature,
        id_column="feature_id",
        columns=(
            "feature_id",
            "document_id",
            "collection_id",
            "variant_id",
            "feature_type",
            "feature_value",
            "feature_unit",
            "qualitative_descriptor",
            "source_observation_ids",
            "confidence",
            "epistemic_status",
        ),
        json_columns=frozenset({"feature_value", "source_observation_ids"}),
        real_columns=frozenset({"confidence"}),
        index_columns=("document_id", "variant_id", "feature_type"),
    ),
)

_COMPARISON_TABLES: tuple[_TableSpec, ...] = (
    _TableSpec(
        table_name="core_comparable_results",
        attr_name="comparable_results",
        record_cls=ComparableResult,
        id_column="comparable_result_id",
        columns=(
            "comparable_result_id",
            "source_result_id",
            "source_document_id",
            "binding",
            "normalized_context",
            "axis",
            "value",
            "evidence",
            "variant_label",
            "baseline_reference",
            "result_source_type",
            "epistemic_status",
            "normalization_version",
        ),
        json_columns=frozenset(
            {"binding", "normalized_context", "axis", "value", "evidence"}
        ),
        index_columns=("source_document_id", "source_result_id"),
    ),
    _TableSpec(
        table_name="core_collection_comparable_results",
        attr_name="collection_comparable_results",
        record_cls=CollectionComparableResult,
        id_column="comparable_result_id",
        columns=(
            "collection_id",
            "comparable_result_id",
            "assessment",
            "epistemic_status",
            "included",
            "sort_order",
            "policy_family",
            "policy_version",
            "comparable_result_normalization_version",
            "assessment_input_fingerprint",
            "reassessment_triggers",
        ),
        json_columns=frozenset({"assessment", "reassessment_triggers"}),
        integer_columns=frozenset({"sort_order"}),
        boolean_columns=frozenset({"included"}),
        index_columns=("comparable_result_id", "included", "sort_order"),
    ),
    _TableSpec(
        table_name="core_pairwise_comparison_relations",
        attr_name="pairwise_comparison_relations",
        record_cls=PairwiseComparisonRelation,
        id_column="relation_id",
        columns=(
            "relation_id",
            "collection_id",
            "document_id",
            "current_variant_id",
            "reference_variant_id",
            "comparison_axis",
            "property_normalized",
            "current_result_id",
            "reference_result_id",
            "current_value",
            "reference_value",
            "unit",
            "direction",
            "evidence_anchor_ids",
            "relation_payload",
            "confidence",
            "epistemic_status",
            "relation_version",
        ),
        json_columns=frozenset({"evidence_anchor_ids", "relation_payload"}),
        real_columns=frozenset({"current_value", "reference_value", "confidence"}),
        index_columns=(
            "document_id",
            "current_variant_id",
            "reference_variant_id",
            "property_normalized",
        ),
    ),
    _TableSpec(
        table_name="core_comparison_rows",
        attr_name="comparison_rows",
        record_cls=ComparisonRowRecord,
        id_column="row_id",
        columns=(
            "row_id",
            "collection_id",
            "comparable_result_id",
            "source_document_id",
            "variant_id",
            "variant_label",
            "variable_axis",
            "variable_value",
            "baseline_reference",
            "result_source_type",
            "result_type",
            "result_summary",
            "supporting_evidence_ids",
            "supporting_anchor_ids",
            "characterization_observation_ids",
            "structure_feature_ids",
            "material_system_normalized",
            "process_normalized",
            "property_normalized",
            "baseline_normalized",
            "test_condition_normalized",
            "comparability_status",
            "comparability_warnings",
            "comparability_basis",
            "requires_expert_review",
            "assessment_epistemic_status",
            "missing_critical_context",
            "value",
            "unit",
        ),
        json_columns=frozenset(
            {
                "variable_value",
                "supporting_evidence_ids",
                "supporting_anchor_ids",
                "characterization_observation_ids",
                "structure_feature_ids",
                "comparability_warnings",
                "comparability_basis",
                "missing_critical_context",
            }
        ),
        real_columns=frozenset({"value"}),
        boolean_columns=frozenset({"requires_expert_review"}),
        index_columns=(
            "comparable_result_id",
            "source_document_id",
            "variant_id",
            "material_system_normalized",
            "property_normalized",
            "baseline_normalized",
            "test_condition_normalized",
        ),
    ),
)

_FACT_REPLACE_TABLES = (*_PAPER_FACT_TABLES, *_COMPARISON_TABLES)
_ALL_TABLES = (*_OBJECTIVE_TABLES, *_PAPER_FACT_TABLES, *_COMPARISON_TABLES)
_STATUS_TABLE = "core_fact_collection_status"
_OBJECTIVE_REPORT_TABLE = _TableSpec(
    table_name="core_objective_report_artifacts",
    attr_name="objective_report_artifacts",
    record_cls=ObjectiveReportArtifact,
    id_column="objective_id",
    columns=(
        "report_id",
        "objective_id",
        "status",
        "stage",
        "message",
        "title",
        "language",
        "model",
        "data_version",
        "markdown",
        "warnings",
        "source_refs",
        "created_at",
        "updated_at",
        "generated_at",
    ),
    json_columns=frozenset({"warnings", "source_refs"}),
    index_columns=("objective_id", "status"),
)
_MATERIAL_REPORT_TABLE = _TableSpec(
    table_name="core_material_report_artifacts",
    attr_name="material_report_artifacts",
    record_cls=MaterialReportArtifact,
    id_column="material_id",
    columns=(
        "report_id",
        "material_id",
        "status",
        "stage",
        "message",
        "title",
        "language",
        "model",
        "data_version",
        "markdown",
        "warnings",
        "source_refs",
        "evidence_appendix",
        "created_at",
        "updated_at",
        "generated_at",
    ),
    json_columns=frozenset({"warnings", "source_refs", "evidence_appendix"}),
    index_columns=("material_id", "status"),
)


class SqliteCoreFactRepository:
    """SQLite-backed persistence for Core semantic fact records."""

    backend_name = "sqlite"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or (DATA_DIR / "lens.sqlite")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def replace_collection_research_objectives(
        self,
        collection_id: str,
        paper_skims: tuple[PaperSkim, ...],
        research_objectives: tuple[ResearchObjective, ...],
        objective_contexts: tuple[ObjectiveContext, ...],
        objective_paper_frames: tuple[ObjectivePaperFrame, ...],
        objective_evidence_routes: tuple[ObjectiveEvidenceRoute, ...],
        objective_evidence_units: tuple[ObjectiveEvidenceUnit, ...],
        objective_logic_chains: tuple[ObjectiveLogicChain, ...],
    ) -> None:
        self._ensure_schema()
        records_by_attr = {
            "paper_skims": paper_skims,
            "research_objectives": research_objectives,
            "objective_contexts": objective_contexts,
            "objective_paper_frames": objective_paper_frames,
            "objective_evidence_routes": objective_evidence_routes,
            "objective_evidence_units": objective_evidence_units,
            "objective_logic_chains": objective_logic_chains,
        }
        with self._connection() as connection:
            for spec in _OBJECTIVE_TABLES:
                self._delete_collection(connection, spec, collection_id)
            for spec in _OBJECTIVE_TABLES:
                self._insert_records(
                    connection,
                    spec,
                    collection_id,
                    records_by_attr[spec.attr_name],
                )
            self._upsert_status(
                connection,
                collection_id,
                research_objectives_ready=any(records_by_attr.values()),
            )

    def replace_collection_document_profiles(
        self,
        collection_id: str,
        document_profiles: tuple[DocumentProfile, ...],
    ) -> None:
        self._ensure_schema()
        spec = _PAPER_FACT_TABLES[0]
        with self._connection() as connection:
            self._delete_collection(connection, spec, collection_id)
            self._insert_records(
                connection,
                spec,
                collection_id,
                document_profiles,
            )
            self._upsert_status(connection, collection_id)

    def replace_collection_facts(
        self,
        collection_id: str,
        facts: CoreFactSet,
    ) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            for spec in _FACT_REPLACE_TABLES:
                self._delete_collection(connection, spec, collection_id)
            for spec in _FACT_REPLACE_TABLES:
                self._insert_records(
                    connection,
                    spec,
                    collection_id,
                    getattr(facts, spec.attr_name),
                )
            self._upsert_status(
                connection,
                collection_id,
                paper_facts_ready=True,
                comparison_artifacts_ready=(
                    facts.comparison_artifacts_ready
                    or bool(
                        facts.comparable_results
                        or facts.collection_comparable_results
                        or facts.pairwise_comparison_relations
                        or facts.comparison_rows
                    )
                ),
            )

    def replace_collection_comparison_artifacts(
        self,
        collection_id: str,
        comparable_results: tuple[ComparableResult, ...],
        collection_comparable_results: tuple[CollectionComparableResult, ...],
        comparison_rows: tuple[ComparisonRowRecord, ...],
        pairwise_comparison_relations: tuple[PairwiseComparisonRelation, ...] = (),
    ) -> None:
        self._ensure_schema()
        records_by_attr = {
            "comparable_results": comparable_results,
            "collection_comparable_results": collection_comparable_results,
            "pairwise_comparison_relations": pairwise_comparison_relations,
            "comparison_rows": comparison_rows,
        }
        with self._connection() as connection:
            for spec in _COMPARISON_TABLES:
                self._delete_collection(connection, spec, collection_id)
            for spec in _COMPARISON_TABLES:
                self._insert_records(
                    connection,
                    spec,
                    collection_id,
                    records_by_attr[spec.attr_name],
                )
            self._upsert_status(
                connection,
                collection_id,
                comparison_artifacts_ready=True,
            )

    def read_collection_facts(self, collection_id: str) -> CoreFactSet:
        self._ensure_schema()
        with self._connection() as connection:
            records_by_attr = {
                spec.attr_name: self._read_records(connection, spec, collection_id)
                for spec in _ALL_TABLES
            }
            status = self._read_status(connection, collection_id, records_by_attr)
        return CoreFactSet(**status, **records_by_attr)

    def upsert_objective_report_artifact(
        self,
        collection_id: str,
        artifact: ObjectiveReportArtifact,
    ) -> None:
        self._upsert_report_artifact(collection_id, _OBJECTIVE_REPORT_TABLE, artifact)

    def read_objective_report_artifact(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveReportArtifact | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT {", ".join(_OBJECTIVE_REPORT_TABLE.columns)}
                FROM {_OBJECTIVE_REPORT_TABLE.table_name}
                WHERE collection_id = ? AND objective_id = ?
                """,
                (collection_id, objective_id),
            ).fetchone()
        if row is None:
            return None
        return ObjectiveReportArtifact.from_mapping(
            self._payload_from_row(_OBJECTIVE_REPORT_TABLE, row)
        )

    def upsert_material_report_artifact(
        self,
        collection_id: str,
        artifact: MaterialReportArtifact,
    ) -> None:
        self._upsert_report_artifact(collection_id, _MATERIAL_REPORT_TABLE, artifact)

    def read_material_report_artifact(
        self,
        collection_id: str,
        material_id: str,
    ) -> MaterialReportArtifact | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT {", ".join(_MATERIAL_REPORT_TABLE.columns)}
                FROM {_MATERIAL_REPORT_TABLE.table_name}
                WHERE collection_id = ? AND material_id = ?
                """,
                (collection_id, material_id),
            ).fetchone()
        if row is None:
            return None
        return MaterialReportArtifact.from_mapping(
            self._payload_from_row(_MATERIAL_REPORT_TABLE, row)
        )

    def _upsert_report_artifact(
        self,
        collection_id: str,
        spec: _TableSpec,
        artifact: Any,
    ) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            columns = self._storage_columns(spec)
            placeholders = ", ".join("?" for _ in columns)
            update_columns = [
                column
                for column in columns
                if column not in {"collection_id", spec.id_column}
            ]
            updates = ", ".join(
                f"{column} = excluded.{column}" for column in update_columns
            )
            connection.execute(
                f"""
                INSERT INTO {spec.table_name} ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(collection_id, {spec.id_column})
                DO UPDATE SET {updates}
                """,
                self._record_values(spec, collection_id, artifact),
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            self._create_status_table(connection)
            for spec in _ALL_TABLES:
                self._create_table(connection, spec)
                self._create_indexes(connection, spec)
            self._create_table(connection, _OBJECTIVE_REPORT_TABLE)
            self._create_indexes(connection, _OBJECTIVE_REPORT_TABLE)
            self._create_table(connection, _MATERIAL_REPORT_TABLE)
            self._create_indexes(connection, _MATERIAL_REPORT_TABLE)

    def _create_status_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_STATUS_TABLE} (
                collection_id TEXT PRIMARY KEY,
                research_objectives_ready INTEGER NOT NULL DEFAULT 0,
                paper_facts_ready INTEGER NOT NULL DEFAULT 0,
                comparison_artifacts_ready INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._ensure_status_column(
            connection,
            "research_objectives_ready",
            "INTEGER NOT NULL DEFAULT 0",
        )

    def _ensure_status_column(
        self,
        connection: sqlite3.Connection,
        column_name: str,
        column_definition: str,
    ) -> None:
        rows = connection.execute(f"PRAGMA table_info({_STATUS_TABLE})").fetchall()
        existing = {str(row["name"]) for row in rows}
        if column_name in existing:
            return
        connection.execute(
            f"ALTER TABLE {_STATUS_TABLE} ADD COLUMN {column_name} {column_definition}"
        )

    def _upsert_status(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        *,
        research_objectives_ready: bool | None = None,
        paper_facts_ready: bool | None = None,
        comparison_artifacts_ready: bool | None = None,
    ) -> None:
        current = connection.execute(
            f"""
            SELECT
                research_objectives_ready,
                paper_facts_ready,
                comparison_artifacts_ready
            FROM {_STATUS_TABLE}
            WHERE collection_id = ?
            """,
            (collection_id,),
        ).fetchone()
        next_research_objectives_ready = (
            bool(current["research_objectives_ready"]) if current else False
        )
        next_paper_facts_ready = (
            bool(current["paper_facts_ready"]) if current else False
        )
        next_comparison_artifacts_ready = (
            bool(current["comparison_artifacts_ready"]) if current else False
        )
        if paper_facts_ready is not None:
            next_paper_facts_ready = bool(paper_facts_ready)
        if research_objectives_ready is not None:
            next_research_objectives_ready = bool(research_objectives_ready)
        if comparison_artifacts_ready is not None:
            next_comparison_artifacts_ready = bool(comparison_artifacts_ready)
        connection.execute(
            f"""
            INSERT INTO {_STATUS_TABLE} (
                collection_id,
                research_objectives_ready,
                paper_facts_ready,
                comparison_artifacts_ready
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(collection_id) DO UPDATE SET
                research_objectives_ready = excluded.research_objectives_ready,
                paper_facts_ready = excluded.paper_facts_ready,
                comparison_artifacts_ready = excluded.comparison_artifacts_ready
            """,
            (
                collection_id,
                int(next_research_objectives_ready),
                int(next_paper_facts_ready),
                int(next_comparison_artifacts_ready),
            ),
        )

    def _read_status(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        records_by_attr: dict[str, tuple[Any, ...]],
    ) -> dict[str, bool]:
        row = connection.execute(
            f"""
            SELECT
                research_objectives_ready,
                paper_facts_ready,
                comparison_artifacts_ready
            FROM {_STATUS_TABLE}
            WHERE collection_id = ?
            """,
            (collection_id,),
        ).fetchone()
        if row is not None:
            return {
                "research_objectives_ready": bool(row["research_objectives_ready"]),
                "paper_facts_ready": bool(row["paper_facts_ready"]),
                "comparison_artifacts_ready": bool(
                    row["comparison_artifacts_ready"]
                ),
            }
        return {
            "research_objectives_ready": any(
                records_by_attr[spec.attr_name] for spec in _OBJECTIVE_TABLES
            ),
            "paper_facts_ready": any(
                records_by_attr[spec.attr_name] for spec in _PAPER_FACT_TABLES[1:]
            ),
            "comparison_artifacts_ready": any(
                records_by_attr[spec.attr_name] for spec in _COMPARISON_TABLES
            ),
        }

    def _create_table(
        self,
        connection: sqlite3.Connection,
        spec: _TableSpec,
    ) -> None:
        columns = [
            self._column_definition(spec, column)
            for column in self._storage_columns(spec)
        ]
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {spec.table_name} (
                {", ".join(columns)},
                PRIMARY KEY(collection_id, {spec.id_column})
            )
            """
        )

    def _create_indexes(
        self,
        connection: sqlite3.Connection,
        spec: _TableSpec,
    ) -> None:
        for column in spec.index_columns:
            if column == "collection_id":
                continue
            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{spec.table_name}_{column}
                ON {spec.table_name}(collection_id, {column})
                """
            )

    def _column_definition(self, spec: _TableSpec, column: str) -> str:
        if column == "collection_id" or column == spec.id_column:
            return f"{column} TEXT NOT NULL"
        return f"{column} {self._column_type(spec, column)}"

    def _column_type(self, spec: _TableSpec, column: str) -> str:
        if column in spec.integer_columns or column in spec.boolean_columns:
            return "INTEGER"
        if column in spec.real_columns:
            return "REAL"
        return "TEXT"

    def _insert_records(
        self,
        connection: sqlite3.Connection,
        spec: _TableSpec,
        collection_id: str,
        records: tuple[Any, ...],
    ) -> None:
        if not records:
            return
        columns = self._storage_columns(spec)
        placeholders = ", ".join("?" for _ in columns)
        connection.executemany(
            f"""
            INSERT INTO {spec.table_name} ({", ".join(columns)})
            VALUES ({placeholders})
            """,
            [
                self._record_values(spec, collection_id, record)
                for record in records
            ],
        )

    def _record_values(
        self,
        spec: _TableSpec,
        collection_id: str,
        record: Any,
    ) -> tuple[Any, ...]:
        payload = record.to_record()
        values: list[Any] = []
        for column in self._storage_columns(spec):
            value = collection_id if column == "collection_id" else payload.get(column)
            values.append(self._store_value(spec, column, value))
        return tuple(values)

    def _read_records(
        self,
        connection: sqlite3.Connection,
        spec: _TableSpec,
        collection_id: str,
    ) -> tuple[Any, ...]:
        rows = connection.execute(
            f"""
            SELECT {", ".join(spec.columns)}
            FROM {spec.table_name}
            WHERE collection_id = ?
            ORDER BY {spec.id_column} ASC
            """,
            (collection_id,),
        ).fetchall()
        return tuple(
            spec.record_cls.from_mapping(self._payload_from_row(spec, row))
            for row in rows
        )

    def _payload_from_row(
        self,
        spec: _TableSpec,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        payload = dict(row)
        for column in spec.json_columns:
            if column in payload:
                payload[column] = self._load_json(payload[column])
        return payload

    def _delete_collection(
        self,
        connection: sqlite3.Connection,
        spec: _TableSpec,
        collection_id: str,
    ) -> None:
        connection.execute(
            f"DELETE FROM {spec.table_name} WHERE collection_id = ?",
            (collection_id,),
        )

    def _storage_columns(self, spec: _TableSpec) -> tuple[str, ...]:
        return ("collection_id",) + tuple(
            column for column in spec.columns if column != "collection_id"
        )

    def _store_value(self, spec: _TableSpec, column: str, value: Any) -> Any:
        if column in spec.json_columns:
            return json.dumps(
                self._normalize_json_value(value),
                ensure_ascii=False,
                sort_keys=True,
            )
        if column in spec.boolean_columns:
            return int(bool(value))
        if isinstance(value, float) and math.isnan(value):
            return None
        return value

    def _load_json(self, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return None
        return json.loads(text)

    def _normalize_json_value(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        if isinstance(value, dict):
            return {
                str(key): self._normalize_json_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._normalize_json_value(item) for item in value]
        if hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
            converted = value.tolist()
            if converted is not value:
                return self._normalize_json_value(converted)
        if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
            try:
                return self._normalize_json_value(value.item())
            except Exception:
                return value
        return value


__all__ = ["SqliteCoreFactRepository"]
