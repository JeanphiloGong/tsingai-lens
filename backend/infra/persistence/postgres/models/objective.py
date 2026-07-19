"""Build-versioned research objectives and objective-scoped evidence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Float,
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
    research_objectives_ready: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


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
    candidate_materials: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    candidate_processes: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    candidate_properties: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    changed_variables: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    possible_objectives: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    evidence_density: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ObjectiveResearchRecord(Base):
    __tablename__ = "research_objectives"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["objective_builds.collection_id", "objective_builds.build_id"],
            name="fk_research_objectives_build",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "objective_id",
            name="uq_research_objectives_collection_build_objective",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_order: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    material_scope: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    process_axes: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    property_axes: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    comparison_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


objective_document_links = Table(
    "objective_document_links",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("objective_id", String(128), primary_key=True),
    Column("link_kind", String(16), primary_key=True),
    Column("source_document_id", String(128), primary_key=True),
    Column("collection_id", String(64), nullable=False),
    Column("position", Integer, nullable=False),
    CheckConstraint("link_kind IN ('seed', 'excluded')", name="link_kind_valid"),
    ForeignKeyConstraint(
        ["collection_id", "build_id", "objective_id"],
        [
            "research_objectives.collection_id",
            "research_objectives.build_id",
            "research_objectives.objective_id",
        ],
        name="fk_objective_document_links_objective",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["collection_id", "build_id", "source_document_id"],
        [
            "source_documents.collection_id",
            "source_documents.build_id",
            "source_documents.source_document_id",
        ],
        name="fk_objective_document_links_source",
        ondelete="RESTRICT",
    ),
)


class ObjectiveContextRecord(Base):
    __tablename__ = "objective_contexts"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "objective_id"],
            [
                "research_objectives.collection_id",
                "research_objectives.build_id",
                "research_objectives.objective_id",
            ],
            name="fk_objective_contexts_objective",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    context_order: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    material_scope: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    variable_process_axes: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    process_context_axes: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    target_property_axes: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    excluded_property_axes: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    objective_evidence_lens: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    routing_hints: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    extraction_guidance: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class ObjectivePaperFrameRecord(Base):
    __tablename__ = "objective_paper_frames"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "build_id", "objective_id"],
            [
                "research_objectives.collection_id",
                "research_objectives.build_id",
                "research_objectives.objective_id",
            ],
            name="fk_objective_frames_objective",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "frame_id",
            name="uq_objective_frames_collection_build_frame",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_objective_frames_source_document",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    frame_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    frame_order: Mapped[int] = mapped_column(Integer, nullable=False)
    relevance: Mapped[str] = mapped_column(String(32), nullable=False)
    paper_role: Mapped[str] = mapped_column(String(64), nullable=False)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    material_match: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    changed_variables: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    measured_property_scope: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    test_environment_scope: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    relevant_sections: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


objective_frame_table_links = Table(
    "objective_frame_table_links",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("frame_id", String(128), primary_key=True),
    Column("link_kind", String(16), primary_key=True),
    Column("table_id", String(128), primary_key=True),
    Column("collection_id", String(64), nullable=False),
    Column("source_document_id", String(128), nullable=False),
    Column("position", Integer, nullable=False),
    CheckConstraint("link_kind IN ('relevant', 'excluded')", name="link_kind_valid"),
    ForeignKeyConstraint(
        ["collection_id", "build_id", "frame_id"],
        [
            "objective_paper_frames.collection_id",
            "objective_paper_frames.build_id",
            "objective_paper_frames.frame_id",
        ],
        name="fk_objective_frame_tables_frame",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["collection_id", "build_id", "source_document_id", "table_id"],
        [
            "source_tables.collection_id",
            "source_tables.build_id",
            "source_tables.source_document_id",
            "source_tables.table_id",
        ],
        name="fk_objective_frame_tables_source",
        ondelete="RESTRICT",
    ),
)


class ObjectiveEvidenceRouteRecord(Base):
    __tablename__ = "objective_evidence_routes"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "(source_kind = 'text_window' AND source_block_id IS NOT NULL "
            "AND source_table_id IS NULL AND source_figure_id IS NULL) OR "
            "(source_kind = 'table' AND source_block_id IS NULL "
            "AND source_table_id IS NOT NULL AND source_figure_id IS NULL) OR "
            "(source_kind = 'figure' AND source_block_id IS NULL "
            "AND source_table_id IS NULL AND source_figure_id IS NOT NULL)",
            name="typed_source_valid",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "objective_id"],
            [
                "research_objectives.collection_id",
                "research_objectives.build_id",
                "research_objectives.objective_id",
            ],
            name="fk_objective_routes_objective",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_objective_routes_source_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "source_block_id"],
            [
                "source_blocks.collection_id",
                "source_blocks.build_id",
                "source_blocks.source_document_id",
                "source_blocks.block_id",
            ],
            name="fk_objective_routes_block",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "source_table_id"],
            [
                "source_tables.collection_id",
                "source_tables.build_id",
                "source_tables.source_document_id",
                "source_tables.table_id",
            ],
            name="fk_objective_routes_table",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "source_figure_id"],
            [
                "source_figures.collection_id",
                "source_figures.build_id",
                "source_figures.source_document_id",
                "source_figures.figure_id",
            ],
            name="fk_objective_routes_figure",
            ondelete="RESTRICT",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    route_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    route_order: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    source_block_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_table_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_figure_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    extractable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    table_schema: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    column_roles: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    join_keys: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    join_plan: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class ObjectiveEvidenceUnitRecord(Base):
    __tablename__ = "objective_evidence_units"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "objective_id"],
            [
                "research_objectives.collection_id",
                "research_objectives.build_id",
                "research_objectives.objective_id",
            ],
            name="fk_objective_units_objective",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "evidence_unit_id",
            name="uq_objective_units_collection_build_unit",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_objective_units_source_document",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_unit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    unit_order: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    property_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    material_system: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    sample_context: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    process_context: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    resolved_condition: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    test_condition: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    value_payload: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_context: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    interpretation: Mapped[str | None] = mapped_column(Text, nullable=True)
    join_keys: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


objective_unit_source_refs = Table(
    "objective_unit_source_refs",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("evidence_unit_id", String(128), primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("collection_id", String(64), nullable=False),
    Column("source_document_id", String(128), nullable=False),
    Column("source_kind", String(32), nullable=False),
    Column("source_ref", String(128), nullable=False),
    Column("source_block_id", String(128), nullable=True),
    Column("source_table_id", String(128), nullable=True),
    Column("source_figure_id", String(128), nullable=True),
    Column("metadata_json", _JSON_DOCUMENT, nullable=False),
    CheckConstraint(
        "(source_kind = 'text_window' AND source_block_id IS NOT NULL "
        "AND source_table_id IS NULL AND source_figure_id IS NULL) OR "
        "(source_kind = 'table' AND source_block_id IS NULL "
        "AND source_table_id IS NOT NULL AND source_figure_id IS NULL) OR "
        "(source_kind = 'figure' AND source_block_id IS NULL "
        "AND source_table_id IS NULL AND source_figure_id IS NOT NULL)",
        name="typed_source_valid",
    ),
    ForeignKeyConstraint(
        ["collection_id", "build_id", "evidence_unit_id"],
        [
            "objective_evidence_units.collection_id",
            "objective_evidence_units.build_id",
            "objective_evidence_units.evidence_unit_id",
        ],
        name="fk_objective_unit_refs_unit",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["collection_id", "build_id", "source_document_id", "source_block_id"],
        [
            "source_blocks.collection_id",
            "source_blocks.build_id",
            "source_blocks.source_document_id",
            "source_blocks.block_id",
        ],
        name="fk_objective_unit_refs_block",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["collection_id", "build_id", "source_document_id", "source_table_id"],
        [
            "source_tables.collection_id",
            "source_tables.build_id",
            "source_tables.source_document_id",
            "source_tables.table_id",
        ],
        name="fk_objective_unit_refs_table",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["collection_id", "build_id", "source_document_id", "source_figure_id"],
        [
            "source_figures.collection_id",
            "source_figures.build_id",
            "source_figures.source_document_id",
            "source_figures.figure_id",
        ],
        name="fk_objective_unit_refs_figure",
        ondelete="RESTRICT",
    ),
)


objective_unit_anchor_links = Table(
    "objective_unit_anchor_links",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("evidence_unit_id", String(128), primary_key=True),
    Column("anchor_id", String(128), primary_key=True),
    Column("collection_id", String(64), nullable=False),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["collection_id", "build_id", "evidence_unit_id"],
        [
            "objective_evidence_units.collection_id",
            "objective_evidence_units.build_id",
            "objective_evidence_units.evidence_unit_id",
        ],
        name="fk_objective_unit_anchors_unit",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["build_id", "anchor_id"],
        [
            "paper_fact_evidence_anchors.build_id",
            "paper_fact_evidence_anchors.anchor_id",
        ],
        name="fk_objective_unit_anchors_anchor",
        ondelete="RESTRICT",
    ),
)


class ObjectiveLogicChainRecord(Base):
    __tablename__ = "objective_logic_chains"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "objective_id"],
            [
                "research_objectives.collection_id",
                "research_objectives.build_id",
                "research_objectives.objective_id",
            ],
            name="fk_objective_chains_objective",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "logic_chain_id",
            name="uq_objective_chains_collection_build_chain",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_objective_chains_source_document",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    logic_chain_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False)
    chain_order: Mapped[int] = mapped_column(Integer, nullable=False)
    chain_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    source_document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    chain_payload: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


objective_logic_chain_unit_links = Table(
    "objective_logic_chain_unit_links",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("logic_chain_id", String(128), primary_key=True),
    Column("evidence_unit_id", String(128), primary_key=True),
    Column("collection_id", String(64), nullable=False),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["collection_id", "build_id", "logic_chain_id"],
        [
            "objective_logic_chains.collection_id",
            "objective_logic_chains.build_id",
            "objective_logic_chains.logic_chain_id",
        ],
        name="fk_objective_chain_units_chain",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["collection_id", "build_id", "evidence_unit_id"],
        [
            "objective_evidence_units.collection_id",
            "objective_evidence_units.build_id",
            "objective_evidence_units.evidence_unit_id",
        ],
        name="fk_objective_chain_units_unit",
        ondelete="RESTRICT",
    ),
)


__all__ = [
    "ObjectiveBuild",
    "ObjectiveContextRecord",
    "ObjectiveEvidenceRouteRecord",
    "ObjectiveEvidenceUnitRecord",
    "ObjectiveLogicChainRecord",
    "ObjectivePaperFrameRecord",
    "ObjectivePaperSkim",
    "ObjectiveResearchRecord",
    "objective_document_links",
    "objective_frame_table_links",
    "objective_logic_chain_unit_links",
    "objective_unit_anchor_links",
    "objective_unit_source_refs",
]
