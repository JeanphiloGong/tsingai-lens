"""Maintained task-specific feedback dataset endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from application.feedback.dataset_service import (
    DatasetSampleDetail,
    FeedbackDatasetConflict,
    FeedbackDatasetError,
    FeedbackDatasetService,
)
from controllers.dependencies.auth import current_user_id
from controllers.schemas.task_datasets import (
    DatasetCollectionItemResponse,
    DatasetCollectionRequest,
    DatasetCollectionResponse,
    DatasetSampleDetailResponse,
    DatasetSampleListResponse,
    DatasetSampleRevisionResponse,
    DatasetSampleSourceCaseResponse,
    DatasetSampleSummaryResponse,
    SampleConfirmRequest,
    SampleActionRequest,
    SampleRevisionUpdateRequest,
    TaskDatasetCreateRequest,
    TaskDatasetListResponse,
    TaskDatasetResponse,
)


router = APIRouter(prefix="/feedback-datasets", tags=["feedback-workbench"])


def _service(request: Request) -> FeedbackDatasetService:
    service = getattr(request.app.state, "feedback_dataset_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "feedback_datasets_unavailable",
                "message": "feedback datasets are not configured",
            },
        )
    return service


def _sample_response(sample: object) -> DatasetSampleSummaryResponse:
    return DatasetSampleSummaryResponse.model_validate(sample.to_record())  # type: ignore[attr-defined]


def _revision_response(revision: object | None) -> DatasetSampleRevisionResponse | None:
    if revision is None:
        return None
    return DatasetSampleRevisionResponse.model_validate(revision.to_record())  # type: ignore[attr-defined]


def _detail_response(detail: DatasetSampleDetail) -> DatasetSampleDetailResponse:
    snapshot = dict(detail.source_case.context_snapshot or {})
    source_case = DatasetSampleSourceCaseResponse(
        case_id=detail.source_case.case_id,
        collection_id=detail.source_case.collection_id,
        session_id=detail.source_case.session_id,
        anchor_message_id=detail.source_case.anchor_message_id,
        status=detail.source_case.status,
        question=str(snapshot.get("question") or ""),
        answer=str(snapshot.get("answer") or ""),
        requested_scope=list(snapshot.get("requested_scope") or ()),
        inspected_sources=list(snapshot.get("inspected_sources") or ()),
        omitted_candidates=list(snapshot.get("omitted_candidates") or ()),
        gaps=[str(item) for item in (snapshot.get("gaps") or ())],
        context_snapshot=snapshot,
    )
    return DatasetSampleDetailResponse(
        sample=_sample_response(detail.sample),
        source_case=source_case,
        current_revision=_revision_response(detail.current_revision),
        confirmed_revision=_revision_response(detail.confirmed_revision),
    )


@router.post("", response_model=TaskDatasetResponse, status_code=status.HTTP_201_CREATED)
async def create_feedback_dataset(
    payload: TaskDatasetCreateRequest,
    request: Request,
) -> TaskDatasetResponse:
    try:
        dataset = await _service(request).create_for_user(
            user_id=await current_user_id(request),
            collection_id=payload.collection_id,
            name=payload.name,
            task_type=payload.task_type,
            construction_spec=payload.construction_spec,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="collection not found") from exc
    except FeedbackDatasetError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return TaskDatasetResponse.model_validate(dataset.to_record())


@router.get("", response_model=TaskDatasetListResponse)
async def list_feedback_datasets(
    request: Request,
    collection_id: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TaskDatasetListResponse:
    try:
        datasets = await _service(request).list_for_user(
            user_id=await current_user_id(request),
            collection_id=collection_id,
            limit=limit,
            offset=offset,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="collection not found") from exc
    except FeedbackDatasetError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return TaskDatasetListResponse(
        items=[TaskDatasetResponse.model_validate(item.to_record()) for item in datasets],
        limit=limit,
        offset=offset,
    )


@router.get("/{dataset_id}", response_model=TaskDatasetResponse)
async def get_feedback_dataset(
    dataset_id: str,
    request: Request,
) -> TaskDatasetResponse:
    try:
        dataset = await _service(request).read_for_user(
            user_id=await current_user_id(request),
            dataset_id=dataset_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset not found") from exc
    return TaskDatasetResponse.model_validate(dataset.to_record())


@router.get("/{dataset_id}/samples", response_model=DatasetSampleListResponse)
async def list_dataset_samples(
    dataset_id: str,
    request: Request,
    status_filter: str | None = Query(default=None, alias="status", min_length=1, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DatasetSampleListResponse:
    try:
        result = await _service(request).list_samples_for_user(
            user_id=await current_user_id(request),
            dataset_id=dataset_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset not found") from exc
    except FeedbackDatasetError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return DatasetSampleListResponse(
        items=[_sample_response(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get(
    "/{dataset_id}/samples/{sample_id}",
    response_model=DatasetSampleDetailResponse,
)
async def get_dataset_sample(
    dataset_id: str,
    sample_id: str,
    request: Request,
) -> DatasetSampleDetailResponse:
    try:
        result = await _service(request).read_sample_for_user(
            user_id=await current_user_id(request),
            dataset_id=dataset_id,
            sample_id=sample_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset sample not found") from exc
    except FeedbackDatasetError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return _detail_response(result)


@router.patch(
    "/{dataset_id}/samples/{sample_id}",
    response_model=DatasetSampleSummaryResponse,
)
async def update_dataset_sample(
    dataset_id: str,
    sample_id: str,
    payload: SampleRevisionUpdateRequest,
    request: Request,
) -> DatasetSampleSummaryResponse:
    try:
        result = await _service(request).update_sft_sample(
            user_id=await current_user_id(request),
            dataset_id=dataset_id,
            sample_id=sample_id,
            expected_revision_id=payload.expected_revision_id,
            content=payload.content.model_dump(mode="json"),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset sample not found") from exc
    except FeedbackDatasetConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": str(exc), "message": "sample has a newer revision"},
        ) from exc
    except FeedbackDatasetError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return _sample_response(result)


@router.post(
    "/{dataset_id}/samples/{sample_id}/confirm",
    response_model=DatasetSampleSummaryResponse,
)
async def confirm_dataset_sample(
    dataset_id: str,
    sample_id: str,
    payload: SampleConfirmRequest,
    request: Request,
) -> DatasetSampleSummaryResponse:
    try:
        result = await _service(request).confirm_sft_sample(
            user_id=await current_user_id(request),
            dataset_id=dataset_id,
            sample_id=sample_id,
            expected_revision_id=payload.expected_revision_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset sample not found") from exc
    except FeedbackDatasetConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": str(exc), "message": "sample has a newer revision"},
        ) from exc
    except FeedbackDatasetError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return _sample_response(result)


@router.post(
    "/{dataset_id}/samples/{sample_id}/actions",
    response_model=DatasetSampleSummaryResponse,
)
async def act_on_dataset_sample(
    dataset_id: str,
    sample_id: str,
    payload: SampleActionRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
) -> DatasetSampleSummaryResponse:
    try:
        result = await _service(request).apply_sample_action_for_user(
            user_id=await current_user_id(request),
            dataset_id=dataset_id,
            sample_id=sample_id,
            action=payload.action,
            expected_revision_id=payload.expected_revision_id,
            reason=payload.reason,
            idempotency_key=idempotency_key,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset sample not found") from exc
    except FeedbackDatasetConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": str(exc), "message": "sample changed; reload and retry"},
        ) from exc
    except FeedbackDatasetError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return _sample_response(result)


@router.post(
    "/{dataset_id}/collections",
    response_model=DatasetCollectionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def collect_feedback_cases(
    dataset_id: str,
    payload: DatasetCollectionRequest,
    request: Request,
) -> DatasetCollectionResponse:
    try:
        result = await _service(request).collect_cases_for_user(
            user_id=await current_user_id(request),
            dataset_id=dataset_id,
            source_case_ids=tuple(payload.source_case_ids),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset or feedback case not found") from exc
    except FeedbackDatasetError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return DatasetCollectionResponse(
        operation_id=result.operation_id,
        created_count=result.created_count,
        existing_count=result.existing_count,
        items=[
            DatasetCollectionItemResponse(
                sample_id=item.sample.sample_id,
                source_case_id=item.sample.source_case_id,
                status=item.sample.status,
                job_id=item.job.job_id if item.job is not None else item.sample.active_job_id,
            )
            for item in result.items
        ],
    )


__all__ = ["router"]
