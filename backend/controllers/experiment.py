import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from controllers.deps.documents import get_chat_service
from controllers.schemas import QueryResponse, SourceItem
from services.chat_service import ChatService

router = APIRouter(prefix="/experiment", tags=["experiment"])
logger = logging.getLogger(__name__)
MAX_SOURCES = 20


class ExperimentPlanRequest(BaseModel):
    goal: str = Field(..., description="实验/优化目标")
    doc_ids: Optional[List[str]] = Field(default=None, description="可选的文档ID列表，用于引导检索")
    mode: str = Field(default="optimize", description="检索模式，默认为optimize")
    top_k_cards: int = Field(default=5, ge=1, description="社区卡片数量")
    max_edges: int = Field(default=80, ge=1, description="图边数量上限")


def _limit_sources(raw_sources) -> List[SourceItem]:
    sources: List[SourceItem] = []
    for s in raw_sources:
        if len(sources) >= MAX_SOURCES:
            break
        if isinstance(s, SourceItem):
            sources.append(s)
        elif isinstance(s, dict):
            sources.append(SourceItem(**s))
        else:
            sources.append(SourceItem(**s.__dict__))
    return sources


def _build_query(goal: str, doc_ids: Optional[List[str]]) -> str:
    if doc_ids:
        return f"基于文档ID {', '.join(doc_ids)}，针对目标：{goal}，给出实验方案（步骤、材料、评估指标、预期风险与验证方式）。"
    return f"针对目标：{goal}，给出实验方案（步骤、材料、评估指标、预期风险与验证方式）。"


@router.post("/plan-graph", response_model=QueryResponse, summary="基于图谱的实验方案")
async def plan_with_graph(payload: ExperimentPlanRequest, chat_svc: ChatService = Depends(get_chat_service)) -> QueryResponse:
    logger.info(
        "实验方案请求（图谱），goal=%s，doc_ids=%s，mode=%s，top_k_cards=%s，max_edges=%s",
        payload.goal,
        payload.doc_ids,
        payload.mode,
        payload.top_k_cards,
        payload.max_edges,
    )
    if not payload.goal:
        raise HTTPException(status_code=400, detail="Missing goal")
    query_text = _build_query(payload.goal, payload.doc_ids)
    result = chat_svc.query(
        query=query_text,
        mode=payload.mode,
        top_k_cards=payload.top_k_cards,
        max_edges=payload.max_edges,
    )
    sources = _limit_sources(result.sources)
    logger.info("实验方案（图谱）完成，answer_len=%s，sources返回=%s", len(result.answer), len(sources))
    return QueryResponse(answer=result.answer, sources=sources)


@router.post("/plan-direct", response_model=QueryResponse, summary="直连生成实验方案")
async def plan_direct(payload: ExperimentPlanRequest, chat_svc: ChatService = Depends(get_chat_service)) -> QueryResponse:
    """
    使用 retriever 的 direct 模式（如果可用）或指定 mode，无需大量图遍历。
    """
    logger.info(
        "实验方案请求（直连），goal=%s，doc_ids=%s，mode=%s，top_k_cards=%s，max_edges=%s",
        payload.goal,
        payload.doc_ids,
        payload.mode,
        payload.top_k_cards,
        payload.max_edges,
    )
    if not payload.goal:
        raise HTTPException(status_code=400, detail="Missing goal")
    query_text = _build_query(payload.goal, payload.doc_ids)
    # 推荐用 direct 模式，若 retriever 不支持则沿用传入值
    mode = payload.mode or "direct"
    result = chat_svc.query(
        query=query_text,
        mode=mode,
        top_k_cards=payload.top_k_cards,
        max_edges=payload.max_edges,
    )
    sources = _limit_sources(result.sources)
    logger.info("实验方案（直连）完成，answer_len=%s，sources返回=%s", len(result.answer), len(sources))
    return QueryResponse(answer=result.answer, sources=sources)
