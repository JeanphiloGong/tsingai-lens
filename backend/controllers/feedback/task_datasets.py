"""Maintained task-specific feedback dataset endpoints."""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status

from application.feedback.dataset_export_service import (
    DatasetExportError,
    FeedbackDatasetExportService,
)
from application.repositories.feedback_dataset_export_repository import DatasetExportSummary
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
    DatasetExportIssueResponse,
    DatasetExportListResponse,
    DatasetExportPreviewResponse,
    DatasetExportPreviewRowResponse,
    DatasetExportPublishRequest,
    DatasetExportSummaryResponse,
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


def _export_service(request: Request) -> FeedbackDatasetExportService:
    service = getattr(request.app.state, "feedback_dataset_export_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "feedback_dataset_exports_unavailable",
                "message": "feedback dataset exports are not configured",
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


def _preview_response(preview) -> DatasetExportPreviewResponse:
    issue_codes: dict[str, list[str]] = {}
    for issue in preview.issues:
        issue_codes.setdefault(issue.sample_id, []).append(issue.code)
    rows: list[DatasetExportPreviewRowResponse] = []
    for member in preview.members:
        question = next(
            (
                item["content"]
                for item in member.content.messages
                if item["role"] == "user"
            ),
            "",
        )
        rows.append(
            DatasetExportPreviewRowResponse(
                sample_id=member.sample_id,
                question=question,
                target_preview=member.content.target[:240],
                evidence_count=len(member.content.evidence),
                issue_codes=issue_codes.get(member.sample_id, []),
            )
        )
    return DatasetExportPreviewResponse(
        preview_id=preview.preview_id,
        dataset_id=preview.dataset_id,
        requested_count=preview.requested_count,
        exportable_count=preview.exportable_count,
        issues=[DatasetExportIssueResponse(**issue.to_record()) for issue in preview.issues],
        sample_rows=rows,
        preview_digest=preview.preview_digest,
        created_at=preview.created_at,
        expires_at=preview.expires_at,
    )


def _export_summary_response(summary) -> DatasetExportSummaryResponse:
    return DatasetExportSummaryResponse(
        export_id=summary.export_id,
        dataset_id=summary.dataset_id,
        export_no=summary.export_no,
        schema_version=summary.schema_version,
        row_count=summary.row_count,
        content_digest=summary.content_digest,
        provenance_digest=summary.provenance_digest,
        manifest_digest=summary.manifest_digest,
        created_at=summary.created_at,
    )


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    return (cleaned or "dataset-export")[:100]


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


@router.post(
    "/{dataset_id}/export-previews",
    response_model=DatasetExportPreviewResponse,
)
async def preview_feedback_dataset_export(
    dataset_id: str,
    request: Request,
) -> DatasetExportPreviewResponse:
    try:
        preview = await _export_service(request).preview_for_user(
            user_id=await current_user_id(request), dataset_id=dataset_id
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset not found") from exc
    except (DatasetExportError, FeedbackDatasetError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return _preview_response(preview)


@router.post(
    "/{dataset_id}/exports",
    response_model=DatasetExportSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_feedback_dataset_export(
    dataset_id: str,
    payload: DatasetExportPublishRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
) -> DatasetExportSummaryResponse:
    try:
        export = await _export_service(request).publish_for_user(
            user_id=await current_user_id(request),
            dataset_id=dataset_id,
            preview_id=payload.preview_id,
            preview_digest=payload.preview_digest,
            allow_partial=payload.allow_partial,
            idempotency_key=idempotency_key,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset or preview not found") from exc
    except DatasetExportError as exc:
        code = str(exc)
        status_code = 409 if "stale" in code or "conflict" in code or "expired" in code else 422
        raise HTTPException(
            status_code=status_code,
            detail={"code": code, "message": code},
        ) from exc
    return _export_summary_response(
        DatasetExportSummary(
            export_id=export.export_id,
            dataset_id=export.dataset_id,
            export_no=export.export_no,
            schema_version=export.schema_version,
            row_count=export.row_count,
            content_digest=export.content_digest,
            provenance_digest=export.provenance_digest,
            manifest_digest=export.manifest_digest,
            created_at=export.created_at,
        )
    )


@router.get("/{dataset_id}/exports", response_model=DatasetExportListResponse)
async def list_feedback_dataset_exports(
    dataset_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DatasetExportListResponse:
    try:
        result = await _export_service(request).list_for_user(
            user_id=await current_user_id(request),
            dataset_id=dataset_id,
            limit=limit,
            offset=offset,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset not found") from exc
    except DatasetExportError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return DatasetExportListResponse(
        items=[_export_summary_response(item) for item in result.items],
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/{dataset_id}/exports/{export_id}/download")
async def download_feedback_dataset_export(
    dataset_id: str,
    export_id: str,
    request: Request,
    format: Literal["json", "jsonl", "provenance"] = Query(default="jsonl"),
) -> Response:
    try:
        export, payload, media_type, filename = await _export_service(request).download_for_user(
            user_id=await current_user_id(request),
            dataset_id=dataset_id,
            export_id=export_id,
            format=format,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset export not found") from exc
    except DatasetExportError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    dataset_name = _safe_filename(str(export.manifest.get("dataset_name") or dataset_id))
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{dataset_name}-v{export.export_no}-{filename}"',
            "X-Manifest-Digest": export.manifest_digest,
            "X-Content-Digest": export.content_digest,
        },
    )


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
