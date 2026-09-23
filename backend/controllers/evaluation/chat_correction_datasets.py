"""Authenticated HTTP access to frozen Chat correction datasets."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response

from application.evaluation.chat_correction_dataset_service import (
    ChatCorrectionDatasetAccessError,
    ChatCorrectionDatasetInvalidError,
)
from controllers.dependencies.auth import current_user_id
from controllers.schemas.chat.session import (
    ChatCorrectionDatasetCreateRequest,
    ChatCorrectionDatasetListResponse,
    ChatCorrectionDatasetResponse,
)


router = APIRouter(prefix="/chat-correction-datasets", tags=["evaluation"])


def _service(request: Request):
    service = getattr(request.app.state, "chat_correction_dataset_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "chat_correction_dataset_unavailable",
                "message": "Chat correction dataset storage is unavailable.",
            },
        )
    return service


def _record(manifest) -> ChatCorrectionDatasetResponse:
    return ChatCorrectionDatasetResponse.model_validate(manifest.to_record())


@router.post(
    "",
    response_model=ChatCorrectionDatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Freeze owner-authorized Chat correction samples",
)
async def create_chat_correction_dataset(
    payload: ChatCorrectionDatasetCreateRequest, request: Request
) -> ChatCorrectionDatasetResponse:
    service = _service(request)
    try:
        manifest = await service.create_dataset_for_user(
            user_id=await current_user_id(request),
            collection_id=payload.collection_id,
            selections=[item.model_dump() for item in payload.items],
            paper_families=payload.paper_families,
        )
    except ChatCorrectionDatasetAccessError as exc:
        raise HTTPException(status_code=404, detail={"code": "chat_correction_dataset_not_found", "message": str(exc)}) from exc
    except (ChatCorrectionDatasetInvalidError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "chat_correction_dataset_invalid", "message": str(exc)}) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "collection_not_found", "message": str(exc)}) from exc
    return _record(manifest)


@router.get(
    "",
    response_model=ChatCorrectionDatasetListResponse,
    summary="List frozen Chat correction datasets owned by the caller",
)
async def list_chat_correction_datasets(
    request: Request,
    collection_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ChatCorrectionDatasetListResponse:
    service = _service(request)
    try:
        manifests = await service.list_datasets_for_user(
            await current_user_id(request),
            collection_id=collection_id,
            limit=limit,
            offset=offset,
        )
    except ChatCorrectionDatasetInvalidError as exc:
        raise HTTPException(status_code=409, detail={"code": "chat_correction_dataset_invalid", "message": str(exc)}) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "collection_not_found", "message": str(exc)}) from exc
    return ChatCorrectionDatasetListResponse(
        items=[_record(manifest) for manifest in manifests], limit=limit, offset=offset
    )


@router.get(
    "/{dataset_id}",
    response_model=ChatCorrectionDatasetResponse,
    summary="Read one frozen Chat correction dataset",
)
async def get_chat_correction_dataset(
    dataset_id: str, request: Request
) -> ChatCorrectionDatasetResponse:
    service = _service(request)
    try:
        manifest = await service.get_dataset_for_user(dataset_id, await current_user_id(request))
    except (ChatCorrectionDatasetInvalidError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail={"code": "chat_correction_dataset_invalid", "message": str(exc)}) from exc
    if manifest is None:
        raise HTTPException(status_code=404, detail={"code": "chat_correction_dataset_not_found", "dataset_id": dataset_id})
    return _record(manifest)


@router.get(
    "/{dataset_id}/jsonl",
    summary="Download one frozen Chat correction dataset as JSONL",
)
async def download_chat_correction_dataset(
    dataset_id: str, request: Request
) -> Response:
    service = _service(request)
    try:
        content = await service.jsonl_for_user(dataset_id, await current_user_id(request))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "chat_correction_dataset_not_found", "message": str(exc)}) from exc
    return Response(
        content=content,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{dataset_id}.jsonl"'},
    )


__all__ = ["router"]
