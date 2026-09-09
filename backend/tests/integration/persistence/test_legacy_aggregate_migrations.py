"""Exercise historical PostgreSQL shapes independently of the current ORM."""

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, inspect, select

from infra.persistence.postgres.base import Base
from tests.integration.persistence.database_cleanup import reset_postgres_schema
from tests.integration.conftest import BACKEND_ROOT


def _upgrade(connection, revision: str) -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND_ROOT / "alembic.ini")))
    context = MigrationContext.configure(
        connection, opts={"target_metadata": Base.metadata}
    )
    with Operations.context(context):
        script.get_revision(revision).module.upgrade()


def test_discovery_adds_boolean_to_legacy_postgres_collection(postgres_sync_engine):
    reset_postgres_schema(postgres_sync_engine)
    with postgres_sync_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE collections (collection_id TEXT PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO collections VALUES ('collection-1')")
        _upgrade(connection, "20260908_0050")
        assert connection.exec_driver_sql(
            "SELECT discovery_ready, discovery_objective_ids FROM collections"
        ).one() == (False, [])


def test_collection_count_removal_preserves_referencing_documents(postgres_sync_engine):
    reset_postgres_schema(postgres_sync_engine)
    with postgres_sync_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE collections (collection_id TEXT PRIMARY KEY, "
            "paper_count INTEGER NOT NULL DEFAULT 0, "
            "CONSTRAINT ck_collections_paper_count_non_negative CHECK (paper_count >= 0))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE documents (document_id TEXT PRIMARY KEY, "
            "collection_id TEXT REFERENCES collections(collection_id) ON DELETE CASCADE)"
        )
        connection.exec_driver_sql("INSERT INTO collections VALUES ('collection-1', 1)")
        connection.exec_driver_sql("INSERT INTO documents VALUES ('document-1', 'collection-1')")
        _upgrade(connection, "20260908_0052")
        assert connection.exec_driver_sql("SELECT * FROM documents").one() == (
            "document-1", "collection-1"
        )
        assert "paper_count" not in {
            column["name"] for column in inspect(connection).get_columns("collections")
        }


def test_objective_owner_constraint_preserves_referencing_analyses(postgres_sync_engine):
    reset_postgres_schema(postgres_sync_engine)
    with postgres_sync_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE collections (collection_id TEXT PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE research_objectives (objective_id TEXT PRIMARY KEY, collection_id TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE objective_analyses (analysis_id TEXT PRIMARY KEY, "
            "objective_id TEXT REFERENCES research_objectives(objective_id))"
        )
        connection.exec_driver_sql("INSERT INTO collections VALUES ('collection-1')")
        connection.exec_driver_sql("INSERT INTO research_objectives VALUES ('objective-1', 'collection-1')")
        connection.exec_driver_sql("INSERT INTO objective_analyses VALUES ('analysis-1', 'objective-1')")
        _upgrade(connection, "20260908_0053")
        assert connection.exec_driver_sql("SELECT * FROM objective_analyses").one() == (
            "analysis-1", "objective-1"
        )
        assert inspect(connection).get_foreign_keys("research_objectives")[0]["referred_table"] == "collections"


def test_preparation_merge_keeps_current_source_and_stale_profile_fingerprints(postgres_sync_engine):
    reset_postgres_schema(postgres_sync_engine)
    with postgres_sync_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE documents (document_id VARCHAR(64) PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO documents VALUES ('document-1')")
        connection.exec_driver_sql(
            "CREATE TABLE document_sources (document_id TEXT PRIMARY KEY, "
            "source_fingerprint TEXT, artifact_json JSONB)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE document_profiles (document_id TEXT PRIMARY KEY, "
            "source_fingerprint TEXT, paper_map_payload JSONB)"
        )
        connection.exec_driver_sql(
            "INSERT INTO document_sources VALUES ('document-1', 'current-source', '{\"text\":\"Methods\"}')"
        )
        connection.exec_driver_sql(
            "INSERT INTO document_profiles VALUES ('document-1', 'previous-source', '{\"studies\":[]}')"
        )
        _upgrade(connection, "20260908_0054")
        preparation = Table("document_preparations", MetaData(), autoload_with=connection)
        row = connection.execute(select(preparation)).mappings().one()
        assert row["source_fingerprint"] == "current-source"
        assert row["profile_json"]["source_fingerprint"] == "previous-source"
        assert row["artifact_json"] == {"text": "Methods"}


def test_result_merge_uses_authoritative_children_and_preserves_reviews(postgres_sync_engine):
    reset_postgres_schema(postgres_sync_engine)
    with postgres_sync_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE objective_analyses (collection_id TEXT, objective_id TEXT, "
            "analysis_version INTEGER, payload JSONB)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE objective_evidence (evidence_id TEXT PRIMARY KEY, collection_id TEXT, "
            "objective_id TEXT, analysis_version INTEGER, payload JSONB)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE objective_findings (finding_id TEXT PRIMARY KEY, collection_id TEXT, "
            "objective_id TEXT, analysis_version INTEGER, display_rank INTEGER, payload JSONB)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE finding_feedback_records (feedback_id TEXT PRIMARY KEY, "
            "finding_id TEXT CONSTRAINT fk_feedback_finding REFERENCES objective_findings(finding_id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO objective_analyses VALUES ('collection-1', 'objective-1', 1, "
            "'{\"evidence_records\":[],\"findings\":[],\"summary\":\"published\"}')"
        )
        connection.exec_driver_sql(
            "INSERT INTO objective_evidence VALUES ('evidence-1', 'collection-1', 'objective-1', 1, "
            "'{\"evidence_id\":\"evidence-1\",\"source_refs\":[\"source-1\"]}')"
        )
        connection.exec_driver_sql(
            "INSERT INTO objective_findings VALUES ('finding-1', 'collection-1', 'objective-1', 1, 2, "
            "'{\"finding_id\":\"finding-1\",\"evidence_ids\":[\"evidence-1\"]}')"
        )
        connection.exec_driver_sql("INSERT INTO finding_feedback_records VALUES ('review-1', 'finding-1')")
        _upgrade(connection, "20260908_0055")
        payload = connection.exec_driver_sql("SELECT payload FROM objective_analyses").scalar_one()
        assert payload["evidence_records"] == [
            {"evidence_id": "evidence-1", "source_refs": ["source-1"]}
        ]
        assert payload["findings"] == [
            {"finding_id": "finding-1", "evidence_ids": ["evidence-1"], "display_rank": 2}
        ]
        assert payload["summary"] == "published"
        assert connection.exec_driver_sql("SELECT * FROM finding_feedback_records").one() == (
            "review-1", "finding-1"
        )
        assert not {"objective_evidence", "objective_findings"}.intersection(
            inspect(connection).get_table_names()
        )
