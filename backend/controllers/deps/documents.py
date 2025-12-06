from config import (
        DOCUMENTS_DIR,
        GRAPH_STORE_FILE,
        INDEX_FILE,
        LLM_API_KEY,
        LLM_BASE_URL,
        LLM_MAX_TOKENS,
        LLM_MODEL,
        )
from graphrag.retriever import GraphRetriever
from graphrag.store import GraphStore
from graphrag.builder import GraphBuilder
from graphrag.community import CommunityManager

from repositories.document import JsonDocumentTable

from services.file_service import FileService
from services.graphrag_service import GraphService
from services.workflows import IngestionWorkflow
from services.llm_client import LLMClient
from services.chat_service import ChatService


graph_store = GraphStore(GRAPH_STORE_FILE)
llm_client = LLMClient(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    model=LLM_MODEL,
    max_tokens=LLM_MAX_TOKENS,
)

graph_builder = GraphBuilder(graph_store, llm_client)
community_manager = CommunityManager(graph_store, llm_client)
graph_retriever = GraphRetriever(graph_store, llm_client)

file_service = FileService(JsonDocumentTable(INDEX_FILE, DOCUMENTS_DIR), DOCUMENTS_DIR)
graph_service = GraphService(graph_builder, community_manager)
ingest_workflow = IngestionWorkflow(
    file_service,
    graph_service,
    llm_client,
)
chat_service = ChatService(graph_retriever)

def get_graph_retriever() -> GraphRetriever:
    return graph_retriever

def get_file_service() -> FileService:
    return file_service

def get_ingestion_workflow() -> IngestionWorkflow:
    return ingest_workflow

def get_chat_service() -> ChatService:
    return chat_service
