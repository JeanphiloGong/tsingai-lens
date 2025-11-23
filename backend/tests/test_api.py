import json
from typing import List, Tuple

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from backend import main
from backend.services.document_manager import DocumentManager


class DummyVectorService:
    def __init__(self):
        self.add_calls: List[Tuple[List[str], List[dict]]] = []
        self.search_calls: List[Tuple[str, int]] = []

    def add_texts(self, texts, metadatas=None):
        self.add_calls.append((list(texts), list(metadatas or [])))

    def similarity_search(self, query: str, k: int = 4):
        self.search_calls.append((query, k))
        return [Document(page_content="context", metadata={"source": "file.txt"})]


class DummyLLM:
    def __init__(self):
        self.summaries: List[str] = []
        self.chat_calls: List[dict] = []

    def summarize(self, text: str) -> str:
        self.summaries.append(text)
        return "summary text"

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        self.chat_calls.append({"system": system, "user": user, "temperature": temperature})
        return "final answer"


@pytest.fixture()
def api_client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "load_file", lambda path: ("loaded text", []))
    monkeypatch.setattr(main, "chunk_text", lambda text: [f"{text}-chunk"])
    monkeypatch.setattr(main, "extract_keywords", lambda text: ["kw1", "kw2"])
    monkeypatch.setattr(main, "build_graph", lambda text: {"graph": "raw"})
    monkeypatch.setattr(main, "to_graph_data", lambda data: {"nodes": [1]})
    monkeypatch.setattr(main, "graph_to_mindmap", lambda data: {"mindmap": True})
    monkeypatch.setattr(main, "answer_question", lambda query, docs, llm: {"answer": f"A:{query}", "context": "ctx"})

    main.settings.documents_dir = tmp_path / "docs"
    main.settings.vector_store_dir = tmp_path / "vector"
    main.settings.index_file = tmp_path / "index.json"

    doc_manager = DocumentManager(index_file=main.settings.index_file, documents_dir=main.settings.documents_dir)
    vector = DummyVectorService()
    llm = DummyLLM()

    main.doc_manager = doc_manager
    main.vector_service = vector
    main.llm_client = llm

    client = TestClient(main.app)
    return client, doc_manager, vector, llm


def test_health(api_client):
    client, _, _, _ = api_client
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_list_documents(api_client):
    client, doc_manager, _, _ = api_client
    doc_manager.register(original_filename="a.txt", stored_filename="a.txt", doc_id="doc-a")

    resp = client.get("/documents")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["id"] == "doc-a"


def test_upload_document_creates_meta_and_vectors(api_client):
    client, doc_manager, vector, _ = api_client
    files = {"file": ("sample.txt", b"hello", "text/plain")}
    data = {"tags": "t1, t2", "metadata": json.dumps({"lang": "en"})}

    resp = client.post("/documents", files=files, data=data)
    assert resp.status_code == 200
    payload = resp.json()

    assert "id" in payload
    doc_id = payload["id"]
    assert payload["keywords"] == ["kw1", "kw2"]
    assert payload["graph"] == {"nodes": [1]}
    assert payload["mindmap"] == {"mindmap": True}
    assert payload["summary"] == "summary text"

    record = doc_manager.get(doc_id)
    assert record is not None
    assert vector.add_calls, "vector service should receive chunks"
    meta_path = main.settings.documents_dir / f"{doc_id}_meta.json"
    assert meta_path.exists()
    saved_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved_meta["keywords"] == ["kw1", "kw2"]
    assert saved_meta["graph"] == {"nodes": [1]}


def test_get_document_returns_record_and_meta(api_client):
    client, doc_manager, _, _ = api_client
    doc_id = doc_manager.register(original_filename="a.txt", stored_filename="a.txt", doc_id="doc-1")
    main.write_meta(doc_id, {"keywords": ["k"], "graph": {"nodes": []}})

    resp = client.get(f"/documents/{doc_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["record"]["id"] == doc_id
    assert body["meta"]["keywords"] == ["k"]


def test_get_document_not_found(api_client):
    client, _, _, _ = api_client
    resp = client.get("/documents/missing")
    assert resp.status_code == 404


def test_keywords_and_graph_endpoints(api_client):
    client, doc_manager, _, _ = api_client
    doc_id = doc_manager.register(original_filename="b.txt", stored_filename="b.txt", doc_id="doc-2")
    main.write_meta(doc_id, {"keywords": ["k1"], "graph": {"g": 1}, "mindmap": {"m": 1}})

    kw_resp = client.get(f"/documents/{doc_id}/keywords")
    assert kw_resp.status_code == 200
    assert kw_resp.json() == {"keywords": ["k1"]}

    graph_resp = client.get(f"/documents/{doc_id}/graph")
    assert graph_resp.status_code == 200
    assert graph_resp.json() == {"graph": {"g": 1}, "mindmap": {"m": 1}}


def test_keywords_not_found_returns_404(api_client):
    client, _, _, _ = api_client
    resp = client.get("/documents/missing/keywords")
    assert resp.status_code == 404


def test_graph_not_found_returns_404(api_client):
    client, _, _, _ = api_client
    resp = client.get("/documents/missing/graph")
    assert resp.status_code == 404


def test_query_requires_query_param(api_client):
    client, _, _, _ = api_client
    resp = client.post("/query", json={})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Missing query"


def test_query_returns_answer_and_sources(api_client):
    client, _, vector, _ = api_client
    resp = client.post("/query", json={"query": "what", "top_k": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "A:what"
    assert len(body["sources"]) == 1
    assert vector.search_calls == [("what", 2)]
