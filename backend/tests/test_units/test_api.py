import json
from typing import List, Tuple

import pytest

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False

if not FASTAPI_AVAILABLE:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

import config as config
from main import app
from controllers import deps
from services.document_manager import DocumentManager


class DummyGraphBuilder:
    def __init__(self):
        self.ingest_calls: List[Tuple[List[Tuple[str, dict]], str, str]] = []

    def ingest_chunks(self, chunked, doc_id: str, source: str):
        self.ingest_calls.append((list(chunked), doc_id, source))


class DummyCommunityManager:
    def __init__(self):
        self.rebuild_calls = 0

    def rebuild(self):
        self.rebuild_calls += 1

    @property
    def store(self):
        return deps.graph_store


class DummyGraphRetriever:
    def __init__(self):
        self.calls: List[dict] = []

    def answer(self, query: str, mode: str = "optimize", top_k_cards: int = 5, max_edges: int = 80):
        self.calls.append({"query": query, "mode": mode, "top_k_cards": top_k_cards, "max_edges": max_edges})
        return {"answer": f"A:{query}", "sources": [{"doc_id": "d1", "page": 1}]}


class DummyLLM:
    def __init__(self):
        self.summaries: List[str] = []

    def summarize(self, text: str) -> str:
        self.summaries.append(text)
        return "summary text"

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        return "chat"


@pytest.fixture()
def api_client(monkeypatch, tmp_path):
    if not FASTAPI_AVAILABLE:
        pytest.skip("fastapi not installed")
    # patch ingest helpers
    monkeypatch.setattr("ingest.loader.load_file", lambda path: ([(1, "loaded text")], []))
    monkeypatch.setattr("ingest.chunker.chunk_pages", lambda pages: [("chunk-1", {"page": 1, "chunk_id": 0})])
    monkeypatch.setattr("graph.keywords.extract_keywords", lambda text: ["kw1", "kw2"])

    config.DOCUMENTS_DIR = tmp_path / "docs"
    config.GRAPH_STORE_FILE = tmp_path / "graph_store.json"
    config.INDEX_FILE = tmp_path / "index.json"

    doc_manager = DocumentManager(index_file=config.INDEX_FILE, documents_dir=config.DOCUMENTS_DIR)
    graph_builder = DummyGraphBuilder()
    graph_retriever = DummyGraphRetriever()
    community_manager = DummyCommunityManager()
    llm = DummyLLM()

    deps.graph_store.path = config.GRAPH_STORE_FILE
    deps.graph_store.graph.clear()

    deps.doc_manager = doc_manager
    deps.graph_builder = graph_builder
    deps.graph_retriever = graph_retriever
    deps.community_manager = community_manager
    deps.llm_client = llm

    client = TestClient(app)
    return client, doc_manager, graph_builder, graph_retriever, llm, community_manager


def test_health(api_client):
    client, _, _, _, _, _ = api_client
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_list_documents(api_client):
    client, doc_manager, _, _, _, _ = api_client
    doc_manager.register(original_filename="a.txt", stored_filename="a.txt", doc_id="doc-a")

    resp = client.get("/documents")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["id"] == "doc-a"


def test_upload_document_builds_graph_and_meta(api_client):
    client, doc_manager, builder, _, llm, community_manager = api_client
    files = {"file": ("sample.txt", b"hello", "text/plain")}
    data = {"tags": "t1, t2", "metadata": json.dumps({"lang": "en"})}

    resp = client.post("/documents", files=files, data=data)
    assert resp.status_code == 200
    payload = resp.json()

    assert "id" in payload
    doc_id = payload["id"]
    assert payload["keywords"] == ["kw1", "kw2"]
    assert "nodes" in payload["graph"]
    assert payload["summary"] == "summary text"
    assert builder.ingest_calls, "graph builder should be invoked"
    assert community_manager.rebuild_calls == 1
    assert llm.summaries, "summarize should be called"

    record = doc_manager.get(doc_id)
    assert record is not None
    meta_path = config.DOCUMENTS_DIR / f"{doc_id}_meta.json"
    assert meta_path.exists()
    saved_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved_meta["keywords"] == ["kw1", "kw2"]
    assert "graph" in saved_meta


def test_get_document_returns_record_and_meta(api_client):
    client, doc_manager, _, _, _ = api_client
    doc_id = doc_manager.register(original_filename="a.txt", stored_filename="a.txt", doc_id="doc-1")
    meta_path = config.DOCUMENTS_DIR / f"{doc_id}_meta.json"
    meta_path.write_text(json.dumps({"keywords": ["k"], "graph": {"nodes": []}}), encoding="utf-8")

    resp = client.get(f"/documents/{doc_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["record"]["id"] == doc_id
    assert body["meta"]["keywords"] == ["k"]


def test_get_document_not_found(api_client):
    client, _, _, _, _, _ = api_client
    resp = client.get("/documents/missing")
    assert resp.status_code == 404


def test_keywords_and_graph_endpoints(api_client):
    client, doc_manager, _, _, _, _ = api_client
    doc_id = doc_manager.register(original_filename="b.txt", stored_filename="b.txt", doc_id="doc-2")
    meta_path = config.DOCUMENTS_DIR / f"{doc_id}_meta.json"
    meta_path.write_text(json.dumps({"keywords": ["k1"], "graph": {"g": 1}, "mindmap": {"m": 1}}), encoding="utf-8")

    kw_resp = client.get(f"/documents/{doc_id}/keywords")
    assert kw_resp.status_code == 200
    assert kw_resp.json() == {"keywords": ["k1"]}

    graph_resp = client.get(f"/documents/{doc_id}/graph")
    assert graph_resp.status_code == 200
    assert graph_resp.json() == {"graph": {"g": 1}, "mindmap": {"m": 1}}


def test_keywords_not_found_returns_404(api_client):
    client, _, _, _, _, _ = api_client
    resp = client.get("/documents/missing/keywords")
    assert resp.status_code == 404


def test_graph_not_found_returns_404(api_client):
    client, _, _, _, _, _ = api_client
    resp = client.get("/documents/missing/graph")
    assert resp.status_code == 404


def test_query_requires_query_param(api_client):
    client, _, _, _, _, _ = api_client
    resp = client.post("/query", json={})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Missing query"


def test_query_returns_answer_and_sources(api_client):
    client, _, _, retriever, _, _ = api_client
    resp = client.post("/query", json={"query": "what", "mode": "methods", "top_k_cards": 2, "max_edges": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "A:what"
    assert len(body["sources"]) == 1
    assert retriever.calls == [{"query": "what", "mode": "methods", "top_k_cards": 2, "max_edges": 5}]
