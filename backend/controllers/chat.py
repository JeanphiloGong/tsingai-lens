import logging

from fastapi import APIRouter, Depends, HTTPException

from controllers.deps.documents import get_chat_service
from controllers.schemas import QueryResponse
from services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/query", response_model=QueryResponse, summary="图谱问答")
async def query_documents(payload: dict, chat_svc: ChatService = Depends(get_chat_service)) -> QueryResponse:
    query = payload.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="Missing query")
    mode = payload.get("mode", "optimize")
    top_k_cards = int(payload.get("top_k_cards", 5))
    max_edges = int(payload.get("max_edges", 80))
    result = chat_svc.query(query=query, mode=mode, top_k_cards=top_k_cards, max_edges=max_edges)
    return QueryResponse(answer=result.answer, sources=result.sources)
