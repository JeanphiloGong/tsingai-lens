import json
from types import SimpleNamespace

import pytest

from backend.services.document_manager import DocumentManager
from backend.services import llm_client as llm_module
from backend.services import vector_service as vector_module


def test_document_manager_register_get_list_and_path(tmp_path):
    index_file = tmp_path / "index.json"
    docs_dir = tmp_path / "docs"
    manager = DocumentManager(index_file=index_file, documents_dir=docs_dir)

    doc_id = manager.register(
        original_filename="paper.pdf",
        stored_filename="stored.pdf",
        tags=["science"],
        metadata={"author": "Ada"},
        doc_id="doc-1",
    )

    assert doc_id == "doc-1"
    loaded = manager.get(doc_id)
    assert loaded["original_filename"] == "paper.pdf"
    assert loaded["tags"] == ["science"]
    assert manager.list() == [loaded]
    assert manager.path_for(doc_id) == docs_dir / "stored.pdf"
    assert json.loads(index_file.read_text(encoding="utf-8"))[doc_id]["filename"] == "stored.pdf"


def test_document_manager_path_for_missing(tmp_path):
    manager = DocumentManager(index_file=tmp_path / "index.json", documents_dir=tmp_path / "docs")
    with pytest.raises(FileNotFoundError):
        manager.path_for("missing-id")


def test_vector_service_loads_existing_index(monkeypatch, tmp_path):
    called = {}

    class FakeFAISS:
        @classmethod
        def load_local(cls, path, embedding, allow_dangerous_deserialization=False):
            called["path"] = path
            return cls()

    monkeypatch.setattr(vector_module, "FAISS", FakeFAISS)
    monkeypatch.setattr(vector_module.VectorService, "_init_embedding", lambda self: object())

    store_dir = tmp_path / "vector"
    store_dir.mkdir(parents=True)
    (store_dir / "index.faiss").write_bytes(b"data")

    service = vector_module.VectorService(store_dir=store_dir, embedding_model="dummy")

    assert isinstance(service.vs, FakeFAISS)
    assert called["path"] == str(store_dir)


def test_vector_service_add_and_search(monkeypatch, tmp_path):
    class FakeFAISS:
        def __init__(self, docs=None):
            self.docs = docs or []
            self.saved_path = None

        @classmethod
        def from_documents(cls, docs, embedding):
            return cls(list(docs))

        def add_documents(self, docs):
            self.docs.extend(docs)

        def save_local(self, path):
            self.saved_path = path

        def similarity_search(self, query, k=4):
            return self.docs[:k]

    monkeypatch.setattr(vector_module, "FAISS", FakeFAISS)
    monkeypatch.setattr(vector_module.VectorService, "_init_embedding", lambda self: object())

    service = vector_module.VectorService(store_dir=tmp_path / "vector", embedding_model="dummy")
    assert service.vs is None

    service.add_texts(["a", "b"], metadatas=[{"idx": 1}, {"idx": 2}])
    assert isinstance(service.vs, FakeFAISS)
    assert len(service.vs.docs) == 2
    assert service.vs.saved_path == str(service.store_dir)

    results = service.similarity_search("query", k=1)
    assert len(results) == 1
    assert results[0].metadata["idx"] == 1


def test_vector_service_similarity_search_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(vector_module.VectorService, "_init_embedding", lambda self: object())
    service = vector_module.VectorService(store_dir=tmp_path / "vector", embedding_model="dummy")
    assert service.similarity_search("anything") == []


def test_llm_client_chat_and_summarize(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="mocked"))])

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.chat = FakeChat()

    monkeypatch.setattr(llm_module, "OpenAI", FakeOpenAI)
    client = llm_module.LLMClient(api_key="k", base_url="http://fake", model="gpt-test", max_tokens=123)

    chat_result = client.chat(system="sys", user="who?", temperature=0.5)
    assert chat_result == "mocked"
    assert captured["model"] == "gpt-test"
    assert captured["temperature"] == 0.5
    assert captured["max_tokens"] == 123

    called = {}

    def fake_chat(system: str, user: str, temperature: float = 0.3) -> str:
        called["system"] = system
        called["user"] = user
        called["temperature"] = temperature
        return "summary"

    client.chat = fake_chat
    summary = client.summarize("content here")
    assert summary == "summary"
    assert "content here" in called["user"]
    assert called["system"].startswith("你是科研助手")
