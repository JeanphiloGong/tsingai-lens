"""Normalized Objective-scoped Research Understanding storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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


class ResearchUnderstandingRecord(Base):
    __tablename__ = "research_understandings"
    __table_args__ = (
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("length(content_sha256) = 64", name="content_sha256_length"),
        CheckConstraint("content_sha256 = lower(content_sha256)", name="content_sha256_lowercase"),
        ForeignKeyConstraint(
            ["collection_id", "objective_id"],
            [
                "research_objective_lifecycles.collection_id",
                "research_objective_lifecycles.objective_id",
            ],
            name="fk_research_understandings_objective",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "objective_id",
            "version",
            name="uq_research_understandings_objective_version",
        ),
    )

    understanding_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_build_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    presentation_metadata: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    model_traces: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchClaimRecord(Base):
    __tablename__ = "research_claims"
    __table_args__ = (
        CheckConstraint("claim_order >= 0", name="claim_order_non_negative"),
    )

    understanding_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("research_understandings.understanding_id", ondelete="CASCADE"),
        primary_key=True,
    )
    claim_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    claim_order: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    strength: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_object_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ResearchRelationRecord(Base):
    __tablename__ = "research_relations"
    __table_args__ = (
        CheckConstraint("relation_order >= 0", name="relation_order_non_negative"),
    )

    understanding_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("research_understandings.understanding_id", ondelete="CASCADE"),
        primary_key=True,
    )
    relation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    relation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    predicate: Mapped[str] = mapped_column(Text, nullable=False)
    object: Mapped[str] = mapped_column(Text, nullable=False)
    statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ResearchEvidenceRefRecord(Base):
    __tablename__ = "research_evidence_refs"
    __table_args__ = (
        CheckConstraint("evidence_order >= 0", name="evidence_order_non_negative"),
    )

    understanding_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("research_understandings.understanding_id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_ref_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    evidence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    fact_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    anchor_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    traceability_status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    href: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResearchContextRecord(Base):
    __tablename__ = "research_contexts"
    __table_args__ = (
        CheckConstraint("context_order >= 0", name="context_order_non_negative"),
    )

    understanding_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("research_understandings.understanding_id", ondelete="CASCADE"),
        primary_key=True,
    )
    context_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    context_order: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    material_scope: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    process_context: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    test_condition: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    property_scope: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ResearchFindingRecord(Base):
    __tablename__ = "research_findings"
    __table_args__ = (
        CheckConstraint("finding_order >= 0", name="finding_order_non_negative"),
        ForeignKeyConstraint(
            ["understanding_id", "claim_id"],
            ["research_claims.understanding_id", "research_claims.claim_id"],
            name="fk_research_findings_claim",
            ondelete="CASCADE",
        ),
    )

    understanding_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(128), nullable=False)
    finding_order: Mapped[int] = mapped_column(Integer, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_ref_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)


research_claim_evidence_links = Table(
    "research_claim_evidence_links",
    Base.metadata,
    Column("understanding_id", String(128), primary_key=True),
    Column("claim_id", String(128), primary_key=True),
    Column("evidence_ref_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["understanding_id", "claim_id"],
        ["research_claims.understanding_id", "research_claims.claim_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["understanding_id", "evidence_ref_id"],
        [
            "research_evidence_refs.understanding_id",
            "research_evidence_refs.evidence_ref_id",
        ],
        ondelete="CASCADE",
    ),
)


research_claim_context_links = Table(
    "research_claim_context_links",
    Base.metadata,
    Column("understanding_id", String(128), primary_key=True),
    Column("claim_id", String(128), primary_key=True),
    Column("context_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["understanding_id", "claim_id"],
        ["research_claims.understanding_id", "research_claims.claim_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["understanding_id", "context_id"],
        ["research_contexts.understanding_id", "research_contexts.context_id"],
        ondelete="CASCADE",
    ),
)


research_relation_evidence_links = Table(
    "research_relation_evidence_links",
    Base.metadata,
    Column("understanding_id", String(128), primary_key=True),
    Column("relation_id", String(128), primary_key=True),
    Column("evidence_ref_id", String(128), primary_key=True),
    Column("role", String(32), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["understanding_id", "relation_id"],
        ["research_relations.understanding_id", "research_relations.relation_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["understanding_id", "evidence_ref_id"],
        [
            "research_evidence_refs.understanding_id",
            "research_evidence_refs.evidence_ref_id",
        ],
        ondelete="CASCADE",
    ),
)


research_relation_context_links = Table(
    "research_relation_context_links",
    Base.metadata,
    Column("understanding_id", String(128), primary_key=True),
    Column("relation_id", String(128), primary_key=True),
    Column("context_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["understanding_id", "relation_id"],
        ["research_relations.understanding_id", "research_relations.relation_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["understanding_id", "context_id"],
        ["research_contexts.understanding_id", "research_contexts.context_id"],
        ondelete="CASCADE",
    ),
)


research_finding_evidence_links = Table(
    "research_finding_evidence_links",
    Base.metadata,
    Column("understanding_id", String(128), primary_key=True),
    Column("finding_id", String(128), primary_key=True),
    Column("evidence_ref_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["understanding_id", "finding_id"],
        ["research_findings.understanding_id", "research_findings.finding_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["understanding_id", "evidence_ref_id"],
        [
            "research_evidence_refs.understanding_id",
            "research_evidence_refs.evidence_ref_id",
        ],
        ondelete="CASCADE",
    ),
)


__all__ = [
    "ResearchClaimRecord",
    "ResearchContextRecord",
    "ResearchEvidenceRefRecord",
    "ResearchFindingRecord",
    "ResearchRelationRecord",
    "ResearchUnderstandingRecord",
    "research_claim_context_links",
    "research_claim_evidence_links",
    "research_finding_evidence_links",
    "research_relation_context_links",
    "research_relation_evidence_links",
]
