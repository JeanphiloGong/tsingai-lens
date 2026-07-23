"""replace objective analysis with versioned aggregate

Revision ID: 20260722_0019
Revises: 20260722_0018
Create Date: 2026-07-22 17:16:37.502182

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = '20260722_0019'
down_revision: Union[str, Sequence[str], None] = '20260722_0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Generated Objective analysis data is intentionally discarded. The new
    # aggregate has different ownership and identities, so retaining it would
    # attach review records to scientifically different results.
    with op.batch_alter_table("comparable_results") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_comparable_results_typed_source_valid"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("fk_comparable_results_objective_unit"),
            type_="foreignkey",
        )
        batch_op.drop_column("objective_evidence_unit_id")
        batch_op.create_check_constraint(
            op.f("ck_comparable_results_typed_source_valid"),
            "source_kind = 'paper_measurement' AND paper_result_id IS NOT NULL",
        )

    for table_name in (
        "objective_experiment_plans",
        "objective_messages",
        "objective_sessions",
        "research_understanding_feedback_records",
        "research_understanding_curation_records",
        "research_finding_evidence_links",
        "research_claim_evidence_links",
        "research_claim_context_links",
        "research_relation_evidence_links",
        "research_relation_context_links",
        "research_findings",
        "research_claims",
        "research_relations",
        "research_evidence_refs",
        "research_contexts",
        "research_understandings",
        "objective_unit_anchor_links",
        "objective_unit_source_refs",
        "objective_logic_chain_unit_links",
        "objective_evidence_units",
        "objective_logic_chains",
        "objective_frame_table_links",
        "objective_evidence_routes",
        "objective_paper_frames",
        "objective_contexts",
        "objective_document_links",
        "research_objective_lifecycles",
        "research_objectives",
    ):
        op.drop_table(table_name)

    json_document = sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()), "postgresql"
    )
    op.create_table(
        "research_objectives",
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("material_scope", json_document, nullable=False),
        sa.Column("process_axes", json_document, nullable=False),
        sa.Column("property_axes", json_document, nullable=False),
        sa.Column("comparison_intent", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("confirmation_status", sa.String(length=16), nullable=False),
        sa.Column("active_analysis_version", sa.Integer(), nullable=True),
        sa.Column("published_analysis_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_research_objectives_confidence_range"),
        ),
        sa.CheckConstraint(
            "confirmation_status IN ('candidate', 'confirmed')",
            name=op.f("ck_research_objectives_confirmation_status_valid"),
        ),
        sa.CheckConstraint(
            "active_analysis_version IS NULL OR active_analysis_version > 0",
            name=op.f("ck_research_objectives_active_analysis_version_positive"),
        ),
        sa.CheckConstraint(
            "published_analysis_version IS NULL OR published_analysis_version > 0",
            name=op.f("ck_research_objectives_published_analysis_version_positive"),
        ),
        sa.CheckConstraint(
            "published_analysis_version IS NULL OR "
            "(active_analysis_version IS NOT NULL AND "
            "published_analysis_version <= active_analysis_version)",
            name=op.f("ck_research_objectives_published_analysis_not_newer_than_active"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_research_objectives_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "collection_id",
            "objective_id",
            name=op.f("pk_research_objectives"),
        ),
    )

    op.create_table(
        "objective_sessions",
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("focused_material_id", sa.String(length=128), nullable=True),
        sa.Column("focused_paper_id", sa.String(length=128), nullable=True),
        sa.Column("focused_objective_id", sa.String(length=128), nullable=True),
        sa.Column("goal_text", sa.Text(), nullable=True),
        sa.Column("intent_brief", json_document, nullable=False),
        sa.Column("answer_mode", sa.String(length=32), nullable=False),
        sa.Column("rolling_summary", sa.Text(), nullable=False),
        sa.Column("last_evidence_ids", json_document, nullable=False),
        sa.Column("last_material_ids", json_document, nullable=False),
        sa.Column("last_paper_ids", json_document, nullable=False),
        sa.Column("collection_data_version", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["auth_users.user_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.collection_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "focused_objective_id"],
            ["research_objectives.collection_id", "research_objectives.objective_id"],
            name="fk_objective_sessions_focus",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_objective_sessions")),
    )
    op.create_table(
        "objective_messages",
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_mode", sa.String(length=64), nullable=True),
        sa.Column("used_evidence_ids", json_document, nullable=False),
        sa.Column("warnings", json_document, nullable=False),
        sa.Column("links", json_document, nullable=False),
        sa.Column("source_links", json_document, nullable=False),
        sa.Column("review_gate", sa.String(length=64), nullable=True),
        sa.Column("source_finding_refs", json_document, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_objective_messages_position_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["objective_sessions.session_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("message_id", name=op.f("pk_objective_messages")),
        sa.UniqueConstraint(
            "session_id", "position", name="uq_objective_messages_position"
        ),
    )
    op.create_index(
        op.f("ix_objective_messages_session_id"),
        "objective_messages",
        ["session_id"],
        unique=False,
    )
    op.create_table(
        "objective_experiment_plans",
        sa.Column("plan_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("source_message_id", sa.String(length=128), nullable=True),
        sa.Column("source_links", json_document, nullable=False),
        sa.Column("metadata_json", json_document, nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id", "objective_id"],
            ["research_objectives.collection_id", "research_objectives.objective_id"],
            name="fk_objective_experiment_plans_objective",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["objective_messages.message_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["auth_users.user_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint(
            "plan_id", name=op.f("pk_objective_experiment_plans")
        ),
    )
    op.create_index(
        op.f("ix_objective_experiment_plans_collection_id"),
        "objective_experiment_plans",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_objective_experiment_plans_objective_id"),
        "objective_experiment_plans",
        ["objective_id"],
        unique=False,
    )
    op.create_table('objective_document_scope',
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('scope_kind', sa.String(length=16), nullable=False),
    sa.Column('source_document_id', sa.String(length=128), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.CheckConstraint("scope_kind IN ('seed', 'excluded')", name=op.f('ck_objective_document_scope_scope_kind_valid')),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id'], ['research_objectives.collection_id', 'research_objectives.objective_id'], name='fk_objective_document_scope_objective', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', 'scope_kind', 'source_document_id', name=op.f('pk_objective_document_scope'))
    )
    op.create_table('objective_analyses',
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('source_build_id', sa.String(length=64), nullable=False),
    sa.Column('pipeline_version', sa.String(length=64), nullable=False),
    sa.Column('model_name', sa.String(length=255), nullable=True),
    sa.Column('prompt_versions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('phase', sa.String(length=64), nullable=False),
    sa.Column('processed_document_count', sa.Integer(), nullable=False),
    sa.Column('total_document_count', sa.Integer(), nullable=False),
    sa.Column('current_document_id', sa.String(length=128), nullable=True),
    sa.Column('progress_message', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status != 'failed' OR error_message IS NOT NULL", name=op.f('ck_objective_analyses_failed_has_error')),
    sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name=op.f('ck_objective_analyses_status_valid')),
    sa.CheckConstraint('analysis_version > 0', name=op.f('ck_objective_analyses_analysis_version_positive')),
    sa.CheckConstraint('processed_document_count >= 0 AND total_document_count >= 0 AND processed_document_count <= total_document_count', name=op.f('ck_objective_analyses_document_progress_valid')),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id'], ['research_objectives.collection_id', 'research_objectives.objective_id'], name='fk_objective_analyses_objective', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['collection_id', 'source_build_id'], ['collection_builds.collection_id', 'collection_builds.build_id'], name='fk_objective_analyses_source_build', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', 'analysis_version', name=op.f('pk_objective_analyses'))
    )
    op.create_index(op.f('ix_objective_analyses_status'), 'objective_analyses', ['status'], unique=False)
    op.create_table('objective_build_candidates',
    sa.Column('build_id', sa.String(length=64), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('objective_order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['collection_id', 'build_id'], ['objective_builds.collection_id', 'objective_builds.build_id'], name='fk_objective_build_candidates_build', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id'], ['research_objectives.collection_id', 'research_objectives.objective_id'], name='fk_objective_build_candidates_objective', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('build_id', 'collection_id', 'objective_id', name=op.f('pk_objective_build_candidates'))
    )
    op.create_table('objective_findings',
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('finding_level', sa.String(length=16), nullable=False),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('variables', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('mediators', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('outcomes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('direction', sa.Text(), nullable=True),
    sa.Column('scope_summary', sa.Text(), nullable=False),
    sa.Column('evidence_strength', sa.String(length=16), nullable=False),
    sa.Column('generalization_status', sa.String(length=32), nullable=False),
    sa.Column('paper_count', sa.Integer(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('display_rank', sa.Integer(), nullable=False),
    sa.CheckConstraint("evidence_strength IN ('strong', 'moderate', 'weak', 'insufficient')", name=op.f('ck_objective_findings_evidence_strength_valid')),
    sa.CheckConstraint("finding_level IN ('paper', 'cross_paper')", name=op.f('ck_objective_findings_finding_level_valid')),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name=op.f('ck_objective_findings_confidence_range')),
    sa.CheckConstraint('display_rank >= 0', name=op.f('ck_objective_findings_display_rank_non_negative')),
    sa.CheckConstraint('paper_count > 0', name=op.f('ck_objective_findings_paper_count_positive')),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version'], ['objective_analyses.collection_id', 'objective_analyses.objective_id', 'objective_analyses.analysis_version'], name='fk_objective_findings_analysis', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', 'analysis_version', 'finding_id', name=op.f('pk_objective_findings'))
    )
    op.create_table('objective_paper_contributions',
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('source_document_id', sa.String(length=128), nullable=False),
    sa.Column('source_build_id', sa.String(length=64), nullable=False),
    sa.Column('analysis_status', sa.String(length=16), nullable=False),
    sa.Column('relevance', sa.String(length=32), nullable=False),
    sa.Column('paper_role', sa.String(length=64), nullable=False),
    sa.Column('contribution_summary', sa.Text(), nullable=True),
    sa.Column('material_match', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('changed_variables', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('measured_property_scope', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('test_environment_scope', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('exclusion_reason', sa.Text(), nullable=True),
    sa.Column('warnings', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.CheckConstraint("analysis_status IN ('pending', 'analyzed', 'excluded', 'failed')", name=op.f('ck_objective_paper_contributions_analysis_status_valid')),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name=op.f('ck_objective_paper_contributions_confidence_range')),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version'], ['objective_analyses.collection_id', 'objective_analyses.objective_id', 'objective_analyses.analysis_version'], name='fk_objective_contributions_analysis', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['collection_id', 'source_build_id', 'source_document_id'], ['source_documents.collection_id', 'source_documents.build_id', 'source_documents.source_document_id'], name='fk_objective_contributions_source_document', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', 'analysis_version', 'source_document_id', name=op.f('pk_objective_paper_contributions'))
    )
    op.create_table('finding_curation_records',
    sa.Column('curation_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('curated_status', sa.String(length=64), nullable=False),
    sa.Column('curated_statement', sa.Text(), nullable=False),
    sa.Column('curated_support_grade', sa.String(length=64), nullable=True),
    sa.Column('curated_review_status', sa.String(length=64), nullable=True),
    sa.Column('curated_variables', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('curated_mediators', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('curated_outcomes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('curated_direction', sa.String(length=64), nullable=True),
    sa.Column('curated_scope_summary', sa.Text(), nullable=True),
    sa.Column('curated_evidence_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('reviewer', sa.String(length=255), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version', 'finding_id'], ['objective_findings.collection_id', 'objective_findings.objective_id', 'objective_findings.analysis_version', 'objective_findings.finding_id'], name='fk_finding_curations_finding', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('curation_id', name=op.f('pk_finding_curation_records'))
    )
    op.create_index(op.f('ix_finding_curation_records_collection_id'), 'finding_curation_records', ['collection_id'], unique=False)
    op.create_index(op.f('ix_finding_curation_records_objective_id'), 'finding_curation_records', ['objective_id'], unique=False)
    op.create_table('finding_feedback_records',
    sa.Column('feedback_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('review_status', sa.String(length=64), nullable=False),
    sa.Column('issue_type', sa.String(length=64), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('reviewer', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version', 'finding_id'], ['objective_findings.collection_id', 'objective_findings.objective_id', 'objective_findings.analysis_version', 'objective_findings.finding_id'], name='fk_finding_feedback_finding', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('feedback_id', name=op.f('pk_finding_feedback_records'))
    )
    op.create_index(op.f('ix_finding_feedback_records_collection_id'), 'finding_feedback_records', ['collection_id'], unique=False)
    op.create_index(op.f('ix_finding_feedback_records_objective_id'), 'finding_feedback_records', ['objective_id'], unique=False)
    op.create_table('objective_evidence',
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('evidence_id', sa.String(length=128), nullable=False),
    sa.Column('source_document_id', sa.String(length=128), nullable=False),
    sa.Column('evidence_order', sa.Integer(), nullable=False),
    sa.Column('source_kind', sa.String(length=32), nullable=False),
    sa.Column('source_ref', sa.Text(), nullable=False),
    sa.Column('source_excerpt', sa.Text(), nullable=False),
    sa.Column('page_numbers', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('related_source_refs', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('evidence_role', sa.String(length=32), nullable=False),
    sa.Column('selection_status', sa.String(length=16), nullable=False),
    sa.Column('selection_reason', sa.Text(), nullable=True),
    sa.Column('evidence_kind', sa.String(length=64), nullable=False),
    sa.Column('property_normalized', sa.Text(), nullable=True),
    sa.Column('material_system', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('sample_context', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('process_context', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('test_condition', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('resolved_condition', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('value_payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('unit', sa.Text(), nullable=True),
    sa.Column('baseline_context', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('interpretation', sa.Text(), nullable=True),
    sa.Column('join_keys', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('anchor_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('resolution_status', sa.String(length=32), nullable=False),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.CheckConstraint("evidence_role IN ('direct_result', 'condition_context', 'mechanism_context', 'baseline_context', 'comparison_context', 'background_context', 'contradictory_result', 'irrelevant')", name=op.f('ck_objective_evidence_evidence_role_valid')),
    sa.CheckConstraint("selection_status != 'failed' OR failure_reason IS NOT NULL", name=op.f('ck_objective_evidence_failed_has_reason')),
    sa.CheckConstraint("selection_status IN ('candidate', 'selected', 'extracted', 'rejected', 'failed')", name=op.f('ck_objective_evidence_selection_status_valid')),
    sa.CheckConstraint("source_kind IN ('text_window', 'table', 'figure')", name=op.f('ck_objective_evidence_source_kind_valid')),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name=op.f('ck_objective_evidence_confidence_range')),
    sa.CheckConstraint('length(source_excerpt) > 0', name=op.f('ck_objective_evidence_source_excerpt_non_empty')),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version', 'source_document_id'], ['objective_paper_contributions.collection_id', 'objective_paper_contributions.objective_id', 'objective_paper_contributions.analysis_version', 'objective_paper_contributions.source_document_id'], name='fk_objective_evidence_contribution', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version'], ['objective_analyses.collection_id', 'objective_analyses.objective_id', 'objective_analyses.analysis_version'], name='fk_objective_evidence_analysis', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', 'analysis_version', 'evidence_id', name=op.f('pk_objective_evidence'))
    )
    op.create_table('objective_finding_contexts',
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('material_system', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('process_conditions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('sample_state', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('test_conditions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('comparison_baseline', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('limitations', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version', 'finding_id'], ['objective_findings.collection_id', 'objective_findings.objective_id', 'objective_findings.analysis_version', 'objective_findings.finding_id'], name='fk_objective_finding_contexts_finding', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', 'analysis_version', 'finding_id', name=op.f('pk_objective_finding_contexts'))
    )
    op.create_table('objective_finding_derivations',
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('synthesis_mode', sa.String(length=16), nullable=False),
    sa.Column('comparison_status', sa.String(length=32), nullable=False),
    sa.Column('contributing_document_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.CheckConstraint("comparison_status IN ('agreement', 'conflict', 'condition_dependent', 'insufficient_confirmation')", name=op.f('ck_objective_finding_derivations_comparison_status_valid')),
    sa.CheckConstraint("synthesis_mode IN ('paper', 'cross_paper')", name=op.f('ck_objective_finding_derivations_synthesis_mode_valid')),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version', 'finding_id'], ['objective_findings.collection_id', 'objective_findings.objective_id', 'objective_findings.analysis_version', 'objective_findings.finding_id'], name='fk_objective_finding_derivations_finding', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', 'analysis_version', 'finding_id', name=op.f('pk_objective_finding_derivations'))
    )
    op.create_table('objective_finding_relations',
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('relation_order', sa.Integer(), nullable=False),
    sa.Column('source_term', sa.Text(), nullable=False),
    sa.Column('relation_type', sa.String(length=64), nullable=False),
    sa.Column('target_term', sa.Text(), nullable=False),
    sa.Column('direction', sa.Text(), nullable=True),
    sa.Column('assertion_strength', sa.String(length=16), nullable=False),
    sa.CheckConstraint("assertion_strength IN ('causal', 'associative', 'descriptive', 'uncertain')", name=op.f('ck_objective_finding_relations_assertion_strength_valid')),
    sa.CheckConstraint('relation_order >= 0', name=op.f('ck_objective_finding_relations_relation_order_non_negative')),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version', 'finding_id'], ['objective_findings.collection_id', 'objective_findings.objective_id', 'objective_findings.analysis_version', 'objective_findings.finding_id'], name='fk_objective_finding_relations_finding', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', 'analysis_version', 'finding_id', 'relation_order', name=op.f('pk_objective_finding_relations'))
    )
    op.create_table('objective_finding_evidence_links',
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('evidence_id', sa.String(length=128), nullable=False),
    sa.Column('link_role', sa.String(length=16), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.CheckConstraint("link_role IN ('supporting', 'contradicting', 'context')", name=op.f('ck_objective_finding_evidence_links_link_role_valid')),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version', 'evidence_id'], ['objective_evidence.collection_id', 'objective_evidence.objective_id', 'objective_evidence.analysis_version', 'objective_evidence.evidence_id'], name='fk_objective_finding_evidence_evidence', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version', 'finding_id'], ['objective_findings.collection_id', 'objective_findings.objective_id', 'objective_findings.analysis_version', 'objective_findings.finding_id'], name='fk_objective_finding_evidence_finding', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', 'analysis_version', 'finding_id', 'evidence_id', 'link_role', name=op.f('pk_objective_finding_evidence_links'))
    )
    op.create_table('objective_finding_relation_evidence_links',
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('relation_order', sa.Integer(), nullable=False),
    sa.Column('evidence_id', sa.String(length=128), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version', 'evidence_id'], ['objective_evidence.collection_id', 'objective_evidence.objective_id', 'objective_evidence.analysis_version', 'objective_evidence.evidence_id'], name='fk_objective_finding_relation_evidence_evidence', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version', 'finding_id', 'relation_order'], ['objective_finding_relations.collection_id', 'objective_finding_relations.objective_id', 'objective_finding_relations.analysis_version', 'objective_finding_relations.finding_id', 'objective_finding_relations.relation_order'], name='fk_objective_finding_relation_evidence_relation', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', 'analysis_version', 'finding_id', 'relation_order', 'evidence_id', name=op.f('pk_objective_finding_relation_evidence_links'))
    )


def downgrade() -> None:
    """The aggregate replacement intentionally discards incompatible data."""
    raise NotImplementedError(
        "20260722_0019 is irreversible: legacy Objective analysis identities "
        "cannot be reconstructed from versioned Findings and Evidence"
    )
