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


def test_source_tree_cutover_preserves_table_and_reference_provenance(
    postgres_sync_engine,
):
    reset_postgres_schema(postgres_sync_engine)
    with postgres_sync_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE collections (collection_id VARCHAR(64) PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE documents (document_id VARCHAR(64) PRIMARY KEY)"
        )
        connection.exec_driver_sql("INSERT INTO collections VALUES ('collection-1')")
        connection.exec_driver_sql("INSERT INTO documents VALUES ('document-1')")
        definitions = {
            "source_documents": "source_document_id TEXT, collection_id TEXT, document_order INTEGER, title TEXT, text TEXT, creation_date TEXT, metadata_json JSONB",
            "source_blocks": "source_document_id TEXT, block_id TEXT, block_type TEXT, text TEXT, block_order INTEGER, page INTEGER, heading_path TEXT, heading_level INTEGER",
            "source_tables": "source_document_id TEXT, table_id TEXT, table_order INTEGER, caption_text TEXT, caption_block_id TEXT, page INTEGER, heading_path TEXT, header_row_count INTEGER, column_headers JSONB, table_matrix JSONB, metadata_json JSONB",
            "source_reference_entries": "source_document_id TEXT, reference_id TEXT, raw_reference TEXT, reference_index TEXT, title TEXT, authors_text TEXT, year INTEGER, doi TEXT, source_block_id TEXT, page INTEGER, confidence FLOAT, metadata_json JSONB",
            "source_reference_mentions": "source_document_id TEXT, mention_id TEXT, reference_id TEXT, citation_marker TEXT, context_text TEXT, source_block_id TEXT, page INTEGER, confidence FLOAT, metadata_json JSONB",
            "source_reference_resolutions": "resolution_id TEXT, reference_id TEXT, provider TEXT, status TEXT, resolved_title TEXT, resolved_authors_text TEXT, resolved_year INTEGER, resolved_venue TEXT, resolved_doi TEXT, resolved_url TEXT, open_access_url TEXT, confidence FLOAT, metadata_json JSONB",
            "source_reference_candidates": "candidate_id TEXT, reference_id TEXT, status TEXT, relevance_score FLOAT, relevance_reason TEXT, cited_by_document_id TEXT, mention_count INTEGER, representative_context TEXT, resolved_doi TEXT, resolved_url TEXT, open_access_url TEXT, metadata_json JSONB",
        }
        for name, columns in definitions.items():
            connection.exec_driver_sql(f"CREATE TABLE {name} ({columns})")
        rows = {
            "source_documents": dict(
                source_document_id="document-1",
                collection_id="collection-1",
                document_order=3,
                title="LPBF porosity",
                text="Power and porosity [1].",
                metadata_json={"source_parser": "legacy-pdf", "parser_version": "v1"},
            ),
            "source_blocks": dict(
                source_document_id="document-1",
                block_id="block-1",
                block_type="paragraph",
                text="Power and porosity [1].",
                block_order=1,
                page=2,
                heading_path="Results",
            ),
            "source_tables": dict(
                source_document_id="document-1",
                table_id="table-1",
                table_order=1,
                caption_text="Power versus porosity",
                page=2,
                heading_path="Results",
                header_row_count=1,
                column_headers=["Power (W)", "Porosity (%)"],
                table_matrix=[["Power (W)", "Porosity (%)"], ["200", "0.4"]],
                metadata_json={"table_label": "Table 1"},
            ),
            "source_reference_entries": dict(
                source_document_id="document-1",
                reference_id="reference-1",
                raw_reference="Smith. LPBF. 2024.",
                reference_index="1",
                title="LPBF",
                authors_text="Smith",
                year=2024,
                source_block_id="block-1",
                page=2,
                confidence=0.9,
                metadata_json={"marker": "[1]"},
            ),
            "source_reference_mentions": dict(
                source_document_id="document-1",
                mention_id="mention-1",
                reference_id="reference-1",
                citation_marker="[1]",
                context_text="Power and porosity [1].",
                source_block_id="block-1",
                page=2,
                confidence=0.8,
                metadata_json={},
            ),
            "source_reference_resolutions": dict(
                resolution_id="resolution-1",
                reference_id="reference-1",
                provider="crossref",
                status="resolved",
                resolved_title="LPBF",
                resolved_year=2024,
                confidence=0.95,
                metadata_json={},
            ),
            "source_reference_candidates": dict(
                candidate_id="candidate-1",
                reference_id="reference-1",
                status="candidate",
                relevance_score=0.7,
                cited_by_document_id="document-1",
                mention_count=1,
                representative_context="Power and porosity [1].",
                metadata_json={},
            ),
        }
        for name, row in rows.items():
            table = Table(name, MetaData(), autoload_with=connection)
            connection.execute(table.insert().values(**row))
        _upgrade(connection, "20260908_0043")
        saved = (
            connection.exec_driver_sql(
                "SELECT artifact_json, tree_json FROM document_sources"
            )
            .mappings()
            .one()
        )
        artifact, tree = saved["artifact_json"], saved["tree_json"]
        assert artifact["document"]["document_order"] == 3
        assert artifact["tables"][0]["table_matrix"][1] == ["200", "0.4"]
        assert artifact["references"]["mentions"][0]["source_block_id"] == "block-1"
        assert artifact["references"]["resolutions"][0]["resolved_year"] == 2024
        assert artifact["references"]["candidates"][0]["mention_count"] == 1
        assert tree["nodes"]["node_document-1_table_table-1"]["page_start"] == 2
        assert (
            tree["reference_records"]["reference-1"]["raw_reference"]
            == "Smith. LPBF. 2024."
        )
        assert not set(definitions).intersection(inspect(connection).get_table_names())


def test_empty_postgres_database_replays_all_model_boundary_migrations(
    postgres_sync_engine,
):
    from alembic import command

    reset_postgres_schema(postgres_sync_engine)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    with postgres_sync_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        head = ScriptDirectory.from_config(config).get_current_head()
        assert MigrationContext.configure(connection).get_current_revision() == head
        assert set(inspect(connection).get_table_names()) == set(
            Base.metadata.tables
        ) | {"alembic_version"}
