"""Research Objective aggregate persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ObjectiveBuild(Base):
    """Collection-build marker for generated Objective candidates."""

    __tablename__ = "objective_builds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["collection_builds.collection_id", "collection_builds.build_id"],
            name="fk_objective_builds_collection_build",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id", "build_id", name="uq_objective_builds_collection_build"
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    research_objectives_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ObjectivePaperSkim(Base):
    __tablename__ = "objective_paper_skims"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["objective_builds.collection_id", "objective_builds.build_id"],
            name="fk_objective_skims_build",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_objective_skims_source_document",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    skim_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_role: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_materials: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    candidate_processes: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    candidate_properties: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    changed_variables: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    possible_objectives: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    evidence_density: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ObjectiveResearchRecord(Base):
    """The one persisted ResearchObjective aggregate root."""

    __tablename__ = "research_objectives"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "confirmation_status IN ('candidate', 'confirmed')",
            name="confirmation_status_valid",
        ),
        CheckConstraint(
            "active_analysis_version IS NULL OR active_analysis_version > 0",
            name="active_analysis_version_positive",
        ),
        CheckConstraint(
            "published_analysis_version IS NULL OR published_analysis_version > 0",
            name="published_analysis_version_positive",
        ),
        CheckConstraint(
            "published_analysis_version IS NULL OR "
            "(active_analysis_version IS NOT NULL AND "
            "published_analysis_version <= active_analysis_version)",
            name="published_analysis_not_newer_than_active",
        ),
    )

    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        primary_key=True,
    )
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    material_scope: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    process_axes: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    property_axes: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    comparison_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    active_analysis_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_analysis_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


objective_build_candidates = Table(
    "objective_build_candidates",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("collection_id", String(64), primary_key=True),
    Column("objective_id", String(128), primary_key=True),
    Column("objective_order", Integer, nullable=False),
    ForeignKeyConstraint(
        ["collection_id", "build_id"],
        ["objective_builds.collection_id", "objective_builds.build_id"],
        name="fk_objective_build_candidates_build",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["collection_id", "objective_id"],
        ["research_objectives.collection_id", "research_objectives.objective_id"],
        name="fk_objective_build_candidates_objective",
        ondelete="CASCADE",
    ),
)


objective_document_scope = Table(
    "objective_document_scope",
    Base.metadata,
    Column("collection_id", String(64), primary_key=True),
    Column("objective_id", String(128), primary_key=True),
    Column("scope_kind", String(16), primary_key=True),
    Column("source_document_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    CheckConstraint("scope_kind IN ('seed', 'excluded')", name="scope_kind_valid"),
    ForeignKeyConstraint(
        ["collection_id", "objective_id"],
        ["research_objectives.collection_id", "research_objectives.objective_id"],
        name="fk_objective_document_scope_objective",
        ondelete="CASCADE",
    ),
)


class ObjectiveAnalysisRecord(Base):
    __tablename__ = "objective_analyses"
    __table_args__ = (
        CheckConstraint("analysis_version > 0", name="analysis_version_positive"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="status_valid",
        ),
        CheckConstraint(
            "processed_document_count >= 0 AND total_document_count >= 0 AND "
            "processed_document_count <= total_document_count",
            name="document_progress_valid",
        ),
        CheckConstraint(
            "status != 'failed' OR error_message IS NOT NULL",
            name="failed_has_error",
        ),
        ForeignKeyConstraint(
            ["collection_id", "objective_id"],
            ["research_objectives.collection_id", "research_objectives.objective_id"],
            name="fk_objective_analyses_objective",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "source_build_id"],
            ["collection_builds.collection_id", "collection_builds.build_id"],
            name="fk_objective_analyses_source_build",
            ondelete="RESTRICT",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_build_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_versions: Mapped[dict[str, str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    current_document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ObjectivePaperContributionRecord(Base):
    __tablename__ = "objective_paper_contributions"
    __table_args__ = (
        CheckConstraint(
            "analysis_status IN ('pending', 'analyzed', 'excluded', 'failed')",
            name="analysis_status_valid",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_objective_contributions_analysis",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            [
                "collection_id",
                "source_build_id",
                "source_document_id",
            ],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_objective_contributions_source_document",
            ondelete="RESTRICT",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_build_id: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_status: Mapped[str] = mapped_column(String(16), nullable=False)
    relevance: Mapped[str] = mapped_column(String(32), nullable=False)
    paper_role: Mapped[str] = mapped_column(String(64), nullable=False)
    contribution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    material_match: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    changed_variables: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    measured_property_scope: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    test_environment_scope: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class ObjectiveEvidenceRecord(Base):
    __tablename__ = "objective_evidence"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "selection_status IN ('candidate', 'selected', 'extracted', 'rejected', 'failed')",
            name="selection_status_valid",
        ),
        CheckConstraint(
            "evidence_role IN ('direct_result', 'condition_context', "
            "'mechanism_context', 'baseline_context', 'comparison_context', "
            "'background_context', 'contradictory_result', 'irrelevant')",
            name="evidence_role_valid",
        ),
        CheckConstraint(
            "source_kind IN ('text_window', 'table', 'figure')",
            name="source_kind_valid",
        ),
        CheckConstraint("length(source_excerpt) > 0", name="source_excerpt_non_empty"),
        CheckConstraint(
            "selection_status != 'failed' OR failure_reason IS NOT NULL",
            name="failed_has_reason",
        ),
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_objective_evidence_analysis",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            [
                "collection_id",
                "objective_id",
                "analysis_version",
                "source_document_id",
            ],
            [
                "objective_paper_contributions.collection_id",
                "objective_paper_contributions.objective_id",
                "objective_paper_contributions.analysis_version",
                "objective_paper_contributions.source_document_id",
            ],
            name="fk_objective_evidence_contribution",
            ondelete="CASCADE",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    source_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    page_numbers: Mapped[list[int]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    related_source_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    evidence_role: Mapped[str] = mapped_column(String(32), nullable=False)
    selection_status: Mapped[str] = mapped_column(String(16), nullable=False)
    selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    property_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    material_system: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    sample_context: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    process_context: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    test_condition: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    resolved_condition: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    value_payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_context: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    interpretation: Mapped[str | None] = mapped_column(Text, nullable=True)
    join_keys: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    anchor_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class ObjectiveFindingRecord(Base):
    __tablename__ = "objective_findings"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("paper_count > 0", name="paper_count_positive"),
        CheckConstraint("display_rank >= 0", name="display_rank_non_negative"),
        CheckConstraint(
            "finding_level IN ('paper', 'cross_paper')", name="finding_level_valid"
        ),
        CheckConstraint(
            "evidence_strength IN ('strong', 'moderate', 'weak', 'insufficient')",
            name="evidence_strength_valid",
        ),
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_objective_findings_analysis",
            ondelete="CASCADE",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    finding_level: Mapped[str] = mapped_column(String(16), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    mediators: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    outcomes: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_strength: Mapped[str] = mapped_column(String(16), nullable=False)
    generalization_status: Mapped[str] = mapped_column(String(32), nullable=False)
    paper_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    display_rank: Mapped[int] = mapped_column(Integer, nullable=False)


class ObjectiveFindingRelationRecord(Base):
    __tablename__ = "objective_finding_relations"
    __table_args__ = (
        CheckConstraint("relation_order >= 0", name="relation_order_non_negative"),
        CheckConstraint(
            "assertion_strength IN ('causal', 'associative', 'descriptive', 'uncertain')",
            name="assertion_strength_valid",
        ),
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version", "finding_id"],
            [
                "objective_findings.collection_id",
                "objective_findings.objective_id",
                "objective_findings.analysis_version",
                "objective_findings.finding_id",
            ],
            name="fk_objective_finding_relations_finding",
            ondelete="CASCADE",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    relation_order: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_term: Mapped[str] = mapped_column(Text, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_term: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    assertion_strength: Mapped[str] = mapped_column(String(16), nullable=False)


class ObjectiveFindingContextRecord(Base):
    __tablename__ = "objective_finding_contexts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version", "finding_id"],
            [
                "objective_findings.collection_id",
                "objective_findings.objective_id",
                "objective_findings.analysis_version",
                "objective_findings.finding_id",
            ],
            name="fk_objective_finding_contexts_finding",
            ondelete="CASCADE",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    material_system: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    process_conditions: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    sample_state: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    test_conditions: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    comparison_baseline: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    limitations: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ObjectiveFindingDerivationRecord(Base):
    __tablename__ = "objective_finding_derivations"
    __table_args__ = (
        CheckConstraint(
            "synthesis_mode IN ('paper', 'cross_paper')", name="synthesis_mode_valid"
        ),
        CheckConstraint(
            "comparison_status IN ('agreement', 'conflict', 'condition_dependent', "
            "'insufficient_confirmation')",
            name="comparison_status_valid",
        ),
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version", "finding_id"],
            [
                "objective_findings.collection_id",
                "objective_findings.objective_id",
                "objective_findings.analysis_version",
                "objective_findings.finding_id",
            ],
            name="fk_objective_finding_derivations_finding",
            ondelete="CASCADE",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    synthesis_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    comparison_status: Mapped[str] = mapped_column(String(32), nullable=False)
    contributing_document_ids: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)


objective_finding_evidence_links = Table(
    "objective_finding_evidence_links",
    Base.metadata,
    Column("collection_id", String(64), primary_key=True),
    Column("objective_id", String(128), primary_key=True),
    Column("analysis_version", Integer, primary_key=True),
    Column("finding_id", String(128), primary_key=True),
    Column("evidence_id", String(128), primary_key=True),
    Column("link_role", String(16), primary_key=True),
    Column("position", Integer, nullable=False),
    CheckConstraint(
        "link_role IN ('supporting', 'contradicting', 'context')",
        name="link_role_valid",
    ),
    ForeignKeyConstraint(
        ["collection_id", "objective_id", "analysis_version", "finding_id"],
        [
            "objective_findings.collection_id",
            "objective_findings.objective_id",
            "objective_findings.analysis_version",
            "objective_findings.finding_id",
        ],
        name="fk_objective_finding_evidence_finding",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["collection_id", "objective_id", "analysis_version", "evidence_id"],
        [
            "objective_evidence.collection_id",
            "objective_evidence.objective_id",
            "objective_evidence.analysis_version",
            "objective_evidence.evidence_id",
        ],
        name="fk_objective_finding_evidence_evidence",
        ondelete="RESTRICT",
    ),
)


objective_finding_relation_evidence_links = Table(
    "objective_finding_relation_evidence_links",
    Base.metadata,
    Column("collection_id", String(64), primary_key=True),
    Column("objective_id", String(128), primary_key=True),
    Column("analysis_version", Integer, primary_key=True),
    Column("finding_id", String(128), primary_key=True),
    Column("relation_order", Integer, primary_key=True),
    Column("evidence_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        [
            "collection_id",
            "objective_id",
            "analysis_version",
            "finding_id",
            "relation_order",
        ],
        [
            "objective_finding_relations.collection_id",
            "objective_finding_relations.objective_id",
            "objective_finding_relations.analysis_version",
            "objective_finding_relations.finding_id",
            "objective_finding_relations.relation_order",
        ],
        name="fk_objective_finding_relation_evidence_relation",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["collection_id", "objective_id", "analysis_version", "evidence_id"],
        [
            "objective_evidence.collection_id",
            "objective_evidence.objective_id",
            "objective_evidence.analysis_version",
            "objective_evidence.evidence_id",
        ],
        name="fk_objective_finding_relation_evidence_evidence",
        ondelete="RESTRICT",
    ),
)


__all__ = [
    "ObjectiveAnalysisRecord",
    "ObjectiveBuild",
    "ObjectiveEvidenceRecord",
    "ObjectiveFindingContextRecord",
    "ObjectiveFindingDerivationRecord",
    "ObjectiveFindingRecord",
    "ObjectiveFindingRelationRecord",
    "ObjectivePaperContributionRecord",
    "ObjectivePaperSkim",
    "ObjectiveResearchRecord",
    "objective_build_candidates",
    "objective_document_scope",
    "objective_finding_evidence_links",
    "objective_finding_relation_evidence_links",
]
