from __future__ import annotations

from retrieval.config.models.vector_store_schema_config import VectorStoreSchemaConfig
from retrieval.vector_stores.base import VectorStoreDocument
from retrieval.vector_stores.lancedb import LanceDBVectorStore


class _FakeTable:
    def __init__(self) -> None:
        self.index_created = False

    def create_index(self, **kwargs):  # noqa: ANN003, ARG002
        self.index_created = True


class _FakeDB:
    def __init__(self) -> None:
        self.dropped: list[tuple[str, bool]] = []
        self.created: list[tuple[str, str | None]] = []
        self.table_lookup = ["default-entity-description"]
        self.table = _FakeTable()

    def table_names(self) -> list[str]:
        return self.table_lookup

    def open_table(self, name: str):
        raise ValueError(f"Table '{name}' was not found")

    def drop_table(self, name: str, namespace=None, ignore_missing: bool = False):  # noqa: ANN001
        self.dropped.append((name, ignore_missing))

    def create_table(self, name: str, data=None, mode: str | None = None, schema=None):  # noqa: ANN001
        self.created.append((name, mode))
        return self.table


def test_lancedb_connect_recovers_from_stale_table(monkeypatch):
    fake_db = _FakeDB()

    monkeypatch.setattr(
        "retrieval.vector_stores.lancedb.lancedb.connect",
        lambda db_uri: fake_db,
    )

    store = LanceDBVectorStore(
        vector_store_schema_config=VectorStoreSchemaConfig(
            index_name="default-entity-description"
        )
    )

    store.connect(db_uri="/tmp/fake-lancedb")

    assert fake_db.dropped == [("default-entity-description", True)]
    assert store.document_collection is None

    store.load_documents(
        [
            VectorStoreDocument(
                id="doc-1",
                text="entity description",
                vector=[0.1, 0.2],
                attributes={"title": "entity"},
            )
        ],
        overwrite=True,
    )

    assert fake_db.created == [("default-entity-description", "overwrite")]
    assert fake_db.table.index_created is True
