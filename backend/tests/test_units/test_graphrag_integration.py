import glob
from pathlib import Path

from graphrag.builder import GraphBuilder
from graphrag.community import CommunityManager
from graphrag.retriever import GraphRetriever
from graphrag.store import GraphStore
from ingest.loader import load_file
from ingest.chunker import chunk_pages


class FakeLLM:
    def __init__(self):
        self.chats = []

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        # simple heuristic: if it's extraction, return one triple; otherwise echo
        if "三元组" in user or "抽取" in user:
            return '[{"head":"Laser","head_type":"Equipment","relation":"uses","tail":"Material","tail_type":"Material","confidence":0.9}]'
        return "mocked answer"

    def summarize(self, text: str) -> str:
        return "summary"


def test_graphrag_pipeline_with_sample_pdf(tmp_path):
    # choose first pdf in test files
    data_dir = Path(__file__).resolve().parents[2] / "data" / "test_file"
    pdf_files = glob.glob(str(data_dir / "*.pdf"))
    assert pdf_files, "No test PDFs found"
    sample = Path(pdf_files[0])

    pages, _ = load_file(sample)
    chunked = chunk_pages(pages[:2])  # limit to first few pages for speed

    store_path = tmp_path / "graph.json"
    store = GraphStore(store_path)
    llm = FakeLLM()
    builder = GraphBuilder(store, llm)
    builder.ingest_chunks(chunked[:8], doc_id="doc-1", source=sample.name)

    community_manager = CommunityManager(store, llm)
    community_manager.rebuild(max_communities=3)

    retriever = GraphRetriever(store, llm)
    result = retriever.answer(query="laser", mode="optimize", top_k_cards=2, max_edges=10)

    assert "answer" in result
    assert isinstance(result["sources"], list)
    assert store.list_nodes(), "Graph should have nodes after ingest"
