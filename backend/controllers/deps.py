"""Shared singletons for controllers."""
import config as config
from graphrag.builder import GraphBuilder
from graphrag.community import CommunityManager
from graphrag.retriever import GraphRetriever
from graphrag.store import GraphStore
from services.document_manager import DocumentManager
from services.llm_client import LLMClient
from services.graphrag_service import GraphRAGService

doc_manager = DocumentManager(config.INDEX_FILE, config.DOCUMENTS_DIR)
graph_store = GraphStore(config.GRAPH_STORE_FILE)
llm_client = LLMClient(
    api_key=config.LLM_API_KEY,
    base_url=config.LLM_BASE_URL,
    model=config.LLM_MODEL,
    max_tokens=config.LLM_MAX_TOKENS,
)
graph_builder = GraphBuilder(graph_store, llm_client)
community_manager = CommunityManager(graph_store, llm_client)
graph_retriever = GraphRetriever(graph_store, llm_client)
graph_service = GraphRAGService(
    doc_manager=doc_manager,
    graph_builder=graph_builder,
    community_manager=community_manager,
    llm_client=llm_client,
    graph_retriever=graph_retriever,
)


def get_doc_manager() -> DocumentManager:
    return doc_manager


def get_graph_service() -> GraphRAGService:
    return graph_service


def get_graph_retriever() -> GraphRetriever:
    return graph_retriever
