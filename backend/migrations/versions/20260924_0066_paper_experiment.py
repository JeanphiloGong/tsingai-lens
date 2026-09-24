"""Add immutable PaperExperiment revisions and component tables."""

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260924_0066"
down_revision = "20260924_0065"
branch_labels = None
depends_on = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    # Revision 0038 builds the then-current ORM snapshot.  On databases that
    # passed through that cutover these tables already exist; only older
    # partial databases need the explicit table definitions below.
    if "paper_experiment" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "paper_experiment",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("experiment_id", sa.String(length=120), nullable=False),
        sa.Column("experiment_version", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=200), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("scope_description", sa.Text(), nullable=False),
        sa.Column("design_type", sa.String(length=40), nullable=False),
        sa.Column("identity_status", sa.String(length=20), nullable=False),
        sa.Column("binding_status", sa.String(length=20), nullable=False),
        sa.Column("source_refs_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("unresolved_issues_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "experiment_version >= 1",
            name="ck_paper_experiment_version_positive",
        ),
        sa.CheckConstraint(
            "design_type IN ('parallel', 'factorial', 'dose_response', "
            "'observational', 'unknown')",
            name="ck_paper_experiment_design_type_valid",
        ),
        sa.CheckConstraint(
            "identity_status IN ('identified', 'partial', 'unknown')",
            name="ck_paper_experiment_identity_status_valid",
        ),
        sa.CheckConstraint(
            "binding_status IN ('draft', 'partial', 'bound')",
            name="ck_paper_experiment_binding_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            name="fk_paper_experiment_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_paper_experiment"),
        sa.UniqueConstraint(
            "experiment_id",
            "experiment_version",
            name="uq_paper_experiment_identity_version",
        ),
    )
    op.create_index(
        "ix_paper_experiment_document_id",
        "paper_experiment",
        ["document_id"],
    )
    op.create_index(
        "ix_paper_experiment_experiment_id",
        "paper_experiment",
        ["experiment_id"],
    )

    op.create_table(
        "experimental_variant",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("paper_experiment_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("variant_key", sa.String(length=100), nullable=False),
        sa.Column("variant_label", sa.String(length=300), nullable=False),
        sa.Column("subject_attributes_json", _JSON_DOCUMENT, nullable=False),
        sa.Column(
            "intervention_attributes_json", _JSON_DOCUMENT, nullable=False
        ),
        sa.Column("state_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("population_scope_json", _JSON_DOCUMENT, nullable=True),
        sa.Column("source_refs_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("binding_source_refs_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("binding_status", sa.String(length=20), nullable=False),
        sa.Column("notes_json", _JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "binding_status IN ('direct', 'derived', 'uncertain', 'conflict')",
            name="ck_experimental_variant_binding_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id"],
            ["paper_experiment.id"],
            name="fk_experimental_variant_paper_experiment_id_paper_experiment",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_experimental_variant"),
        sa.UniqueConstraint(
            "paper_experiment_id",
            "variant_key",
            name="uq_experimental_variant_revision_key",
        ),
        sa.UniqueConstraint(
            "paper_experiment_id",
            "position",
            name="uq_experimental_variant_revision_position",
        ),
    )
    op.create_index(
        "ix_experimental_variant_paper_experiment_id",
        "experimental_variant",
        ["paper_experiment_id"],
    )

    op.create_table(
        "test_condition",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("paper_experiment_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("test_key", sa.String(length=100), nullable=False),
        sa.Column("test_type", sa.String(length=200), nullable=False),
        sa.Column("parameters_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("population_scope_json", _JSON_DOCUMENT, nullable=True),
        sa.Column("source_refs_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("binding_status", sa.String(length=20), nullable=False),
        sa.Column("notes_json", _JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "binding_status IN ('direct', 'derived', 'uncertain', 'conflict')",
            name="ck_test_condition_binding_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id"],
            ["paper_experiment.id"],
            name="fk_test_condition_paper_experiment_id_paper_experiment",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_test_condition"),
        sa.UniqueConstraint(
            "paper_experiment_id",
            "test_key",
            name="uq_test_condition_revision_key",
        ),
        sa.UniqueConstraint(
            "paper_experiment_id",
            "position",
            name="uq_test_condition_revision_position",
        ),
    )
    op.create_index(
        "ix_test_condition_paper_experiment_id",
        "test_condition",
        ["paper_experiment_id"],
    )

    op.create_table(
        "measurement_result",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("paper_experiment_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("measurement_key", sa.String(length=100), nullable=False),
        sa.Column("variant_key", sa.String(length=100), nullable=True),
        sa.Column("test_key", sa.String(length=100), nullable=True),
        sa.Column("outcome", sa.String(length=300), nullable=False),
        sa.Column("value_numeric", sa.Numeric(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column("statistics_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("measurement_scope_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("result_kind", sa.String(length=30), nullable=False),
        sa.Column("source_refs_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("binding_source_refs_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("binding_status", sa.String(length=20), nullable=False),
        sa.Column("notes_json", _JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "value_numeric IS NOT NULL OR value_text IS NOT NULL "
            "OR result_text IS NOT NULL",
            name="ck_measurement_result_value_present",
        ),
        sa.CheckConstraint(
            "result_kind IN ('measured', 'observed', 'simulated', 'predicted', "
            "'unknown')",
            name="ck_measurement_result_result_kind_valid",
        ),
        sa.CheckConstraint(
            "binding_status IN ('direct', 'derived', 'uncertain', 'conflict')",
            name="ck_measurement_result_binding_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id"],
            ["paper_experiment.id"],
            name="fk_measurement_result_paper_experiment_id_paper_experiment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id", "variant_key"],
            [
                "experimental_variant.paper_experiment_id",
                "experimental_variant.variant_key",
            ],
            name="fk_measurement_result_revision_variant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id", "test_key"],
            ["test_condition.paper_experiment_id", "test_condition.test_key"],
            name="fk_measurement_result_revision_test",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_measurement_result"),
        sa.UniqueConstraint(
            "paper_experiment_id",
            "measurement_key",
            name="uq_measurement_result_revision_key",
        ),
        sa.UniqueConstraint(
            "paper_experiment_id",
            "position",
            name="uq_measurement_result_revision_position",
        ),
    )
    op.create_index(
        "ix_measurement_result_outcome", "measurement_result", ["outcome"]
    )
    op.create_index(
        "ix_measurement_result_paper_experiment_id",
        "measurement_result",
        ["paper_experiment_id"],
    )

    op.create_table(
        "experiment_comparison",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("paper_experiment_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("comparison_key", sa.String(length=100), nullable=False),
        sa.Column("baseline_variant_key", sa.String(length=100), nullable=False),
        sa.Column("target_variant_key", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=300), nullable=False),
        sa.Column("changed_variables_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("matched_conditions_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("basis", sa.String(length=20), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("reported_statement", sa.Text(), nullable=True),
        sa.Column("attribution_scope", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reasons_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("source_refs_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("binding_source_refs_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("relation_status", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "basis IN ('reported', 'derived')",
            name="ck_experiment_comparison_basis_valid",
        ),
        sa.CheckConstraint(
            "direction IN ('increase', 'decrease', 'no_change', 'mixed', 'unknown')",
            name="ck_experiment_comparison_direction_valid",
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'insufficient_context', 'non_comparable')",
            name="ck_experiment_comparison_status_valid",
        ),
        sa.CheckConstraint(
            "relation_status IN ('direct', 'derived', 'uncertain', 'conflict')",
            name="ck_experiment_comparison_relation_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id"],
            ["paper_experiment.id"],
            name="fk_experiment_comparison_paper_experiment_id_paper_experiment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id", "baseline_variant_key"],
            [
                "experimental_variant.paper_experiment_id",
                "experimental_variant.variant_key",
            ],
            name="fk_experiment_comparison_revision_baseline_variant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id", "target_variant_key"],
            [
                "experimental_variant.paper_experiment_id",
                "experimental_variant.variant_key",
            ],
            name="fk_experiment_comparison_revision_target_variant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_experiment_comparison"),
        sa.UniqueConstraint(
            "paper_experiment_id",
            "comparison_key",
            name="uq_experiment_comparison_revision_key",
        ),
        sa.UniqueConstraint(
            "paper_experiment_id",
            "position",
            name="uq_experiment_comparison_revision_position",
        ),
    )
    op.create_index(
        "ix_experiment_comparison_paper_experiment_id",
        "experiment_comparison",
        ["paper_experiment_id"],
    )

    op.create_table(
        "experiment_comparison_measurement",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("paper_experiment_id", sa.BigInteger(), nullable=False),
        sa.Column("comparison_key", sa.String(length=100), nullable=False),
        sa.Column("side", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("measurement_key", sa.String(length=100), nullable=False),
        sa.CheckConstraint(
            "side IN ('baseline', 'target')",
            name="ck_experiment_comparison_measurement_side_valid",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id"],
            ["paper_experiment.id"],
            name="fk_experiment_comparison_measurement_experiment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id", "comparison_key"],
            [
                "experiment_comparison.paper_experiment_id",
                "experiment_comparison.comparison_key",
            ],
            name="fk_experiment_comparison_measurement_comparison",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id", "measurement_key"],
            [
                "measurement_result.paper_experiment_id",
                "measurement_result.measurement_key",
            ],
            name="fk_experiment_comparison_measurement_measurement",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_experiment_comparison_measurement"
        ),
        sa.UniqueConstraint(
            "paper_experiment_id",
            "comparison_key",
            "side",
            "position",
            name="uq_experiment_comparison_measurement_position",
        ),
        sa.UniqueConstraint(
            "paper_experiment_id",
            "comparison_key",
            "side",
            "measurement_key",
            name="uq_experiment_comparison_measurement_member",
        ),
    )
    op.create_index(
        "ix_experiment_comparison_measurement_paper_experiment_id",
        "experiment_comparison_measurement",
        ["paper_experiment_id"],
    )

    op.create_table(
        "reported_interpretation",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("paper_experiment_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("measurement_keys_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("comparison_keys_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("source_refs_json", _JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "kind IN ('result_summary', 'mechanism_hypothesis', 'limitation')",
            name="ck_reported_interpretation_kind_valid",
        ),
        sa.ForeignKeyConstraint(
            ["paper_experiment_id"],
            ["paper_experiment.id"],
            name="fk_reported_interpretation_paper_experiment_id_paper_experiment",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reported_interpretation"),
        sa.UniqueConstraint(
            "paper_experiment_id",
            "position",
            name="uq_reported_interpretation_revision_position",
        ),
    )
    op.create_index(
        "ix_reported_interpretation_paper_experiment_id",
        "reported_interpretation",
        ["paper_experiment_id"],
    )


def downgrade():
    op.drop_index(
        "ix_reported_interpretation_paper_experiment_id",
        table_name="reported_interpretation",
    )
    op.drop_table("reported_interpretation")
    op.drop_index(
        "ix_experiment_comparison_measurement_paper_experiment_id",
        table_name="experiment_comparison_measurement",
    )
    op.drop_table("experiment_comparison_measurement")
    op.drop_index(
        "ix_experiment_comparison_paper_experiment_id",
        table_name="experiment_comparison",
    )
    op.drop_table("experiment_comparison")
    op.drop_index(
        "ix_measurement_result_paper_experiment_id",
        table_name="measurement_result",
    )
    op.drop_index("ix_measurement_result_outcome", table_name="measurement_result")
    op.drop_table("measurement_result")
    op.drop_index(
        "ix_test_condition_paper_experiment_id", table_name="test_condition"
    )
    op.drop_table("test_condition")
    op.drop_index(
        "ix_experimental_variant_paper_experiment_id",
        table_name="experimental_variant",
    )
    op.drop_table("experimental_variant")
    op.drop_index(
        "ix_paper_experiment_experiment_id", table_name="paper_experiment"
    )
    op.drop_index(
        "ix_paper_experiment_document_id", table_name="paper_experiment"
    )
    op.drop_table("paper_experiment")
