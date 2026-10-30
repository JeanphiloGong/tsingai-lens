"""Maintained task-specific feedback dataset endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal
from urllib.parse import quote

from application.feedback import dataset_export_service, dataset_service
from application.feedback.dataset_service import DatasetSampleDetail
from controllers.dependencies.auth import get_current_user_id
from controllers.feedback.task_dataset_schemas import (
    DatasetCollectionItemResponse,
    DatasetCollectionRequest,
    DatasetCollectionResponse,
    DatasetExportIssueResponse,
    DatasetExportListResponse,
    DatasetExportPreviewRequest,
    DatasetExportPreviewResponse,
    DatasetExportPreviewRowResponse,
    DatasetExportPublishRequest,
    DatasetExportSummaryResponse,
    DatasetSampleDetailResponse,
    DatasetSampleListResponse,
    DatasetSampleRevisionResponse,
    DatasetSampleSourceCaseResponse,
    DatasetSampleSummaryResponse,
    PreferenceRevisionContentRequest,
    SampleActionRequest,
    SampleConfirmRequest,
    SampleRevisionUpdateRequest,
    SftRevisionContentRequest,
    TaskDatasetCreateRequest,
    TaskDatasetListResponse,
    TaskDatasetResponse,
)
from domain.feedback.dataset_export import ExportPreview
from domain.feedback.sample_revision import (
    EvaluationRevisionContent,
    PreferenceRevisionContent,
    SampleRevision,
    SftRevisionContent,
)
from exceptions import RequestInvalidException
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response
from repositories.feedback_dataset_repository import StoredDataset
from utils.response import ApiResponse, make_api_response

feedback_dataset_router = APIRouter(
    prefix="/feedback-datasets", tags=["feedback-workbench"]
)


def _revision_response(
    revision: SampleRevision | None,
) -> DatasetSampleRevisionResponse | None:
    if revision is None:
        return None
    return DatasetSampleRevisionResponse(
        revision_id=revision.revision_id,
        sample_id=revision.sample_id,
        revision_no=revision.revision_no,
        author_kind=revision.author_kind,
        content=asdict(revision.content),
        content_digest=revision.content_digest,
        input_digest=revision.input_digest,
        construction_spec_version=revision.construction_spec_version,
        provenance=revision.provenance,
        created_at=revision.created_at,
        created_by=revision.created_by,
        job_id=revision.job_id,
    )


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
        sample=DatasetSampleSummaryResponse.model_validate(
            detail.sample, from_attributes=True
        ),
        source_case=source_case,
        current_revision=_revision_response(detail.current_revision),
        confirmed_revision=_revision_response(detail.confirmed_revision),
    )


def _preview_response(preview: ExportPreview) -> DatasetExportPreviewResponse:
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
                schema_version=member.content.schema_version,
                target_preview=getattr(member.content, "target", "")[:240],
                response_a_preview=getattr(member.content, "response_a", "")[:240],
                response_b_preview=getattr(member.content, "response_b", "")[:240],
                reference_preview=getattr(member.content, "reference", "")[:240],
                human_preference=getattr(member.content, "human_preference", None),
                evidence_count=len(member.content.evidence),
                issue_codes=issue_codes.get(member.sample_id, []),
            )
        )
    return DatasetExportPreviewResponse(
        preview_id=preview.preview_id,
        dataset_id=preview.dataset_id,
        requested_count=preview.requested_count,
        exportable_count=preview.exportable_count,
        issues=[
            DatasetExportIssueResponse.model_validate(issue, from_attributes=True)
            for issue in preview.issues
        ],
        sample_rows=rows,
        preview_digest=preview.preview_digest,
        created_at=preview.created_at,
        expires_at=preview.expires_at,
    )


def _dataset_response(record: StoredDataset) -> TaskDatasetResponse:
    return TaskDatasetResponse(
        **asdict(record.dataset),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@feedback_dataset_router.post(
    "", response_model=ApiResponse[TaskDatasetResponse], status_code=200
)
async def create_feedback_dataset(
    payload: TaskDatasetCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    record = await dataset_service.create_dataset_for_user(
        user_id=user_id,
        collection_id=payload.collection_id,
        name=payload.name,
        task_type=payload.task_type,
        construction_spec=payload.construction_spec,
    )
    return make_api_response(data=_dataset_response(record))


@feedback_dataset_router.get("", response_model=ApiResponse[TaskDatasetListResponse])
async def list_feedback_datasets(
    user_id: Annotated[str, Depends(get_current_user_id)],
    collection_id: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Response:
    datasets = await dataset_service.list_dataset_records_for_user(
        user_id=user_id,
        collection_id=collection_id,
        limit=limit,
        offset=offset,
    )
    return make_api_response(
        data=TaskDatasetListResponse(
            items=[_dataset_response(item) for item in datasets],
            limit=limit,
            offset=offset,
        )
    )


@feedback_dataset_router.get(
    "/{dataset_id}", response_model=ApiResponse[TaskDatasetResponse]
)
async def get_feedback_dataset(
    dataset_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    record = await dataset_service.read_dataset_record_for_user(
        user_id=user_id,
        dataset_id=dataset_id,
    )
    return make_api_response(data=_dataset_response(record))


@feedback_dataset_router.post(
    "/{dataset_id}/export-previews",
    response_model=ApiResponse[DatasetExportPreviewResponse],
)
async def preview_feedback_dataset_export(
    dataset_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    payload: DatasetExportPreviewRequest | None = None,
) -> Response:
    preview = await dataset_export_service.preview_for_user(
        user_id=user_id,
        dataset_id=dataset_id,
        sample_ids=payload.sample_ids if payload else None,
    )
    return make_api_response(data=_preview_response(preview))


@feedback_dataset_router.post(
    "/{dataset_id}/exports",
    response_model=ApiResponse[DatasetExportSummaryResponse],
    status_code=200,
)
async def publish_feedback_dataset_export(
    dataset_id: str,
    payload: DatasetExportPublishRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=128
    ),
) -> Response:
    export = await dataset_export_service.publish_for_user(
        user_id=user_id,
        dataset_id=dataset_id,
        preview_id=payload.preview_id,
        preview_digest=payload.preview_digest,
        allow_partial=payload.allow_partial,
        idempotency_key=idempotency_key,
    )
    return make_api_response(
        data=DatasetExportSummaryResponse(
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


@feedback_dataset_router.get(
    "/{dataset_id}/exports", response_model=ApiResponse[DatasetExportListResponse]
)
async def list_feedback_dataset_exports(
    dataset_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Response:
    result = await dataset_export_service.list_for_user(
        user_id=user_id,
        dataset_id=dataset_id,
        limit=limit,
        offset=offset,
    )
    return make_api_response(
        data=DatasetExportListResponse(
            items=[
                DatasetExportSummaryResponse.model_validate(item, from_attributes=True)
                for item in result.items
            ],
            limit=result.limit,
            offset=result.offset,
        )
    )


@feedback_dataset_router.get("/{dataset_id}/exports/{export_id}/download")
async def download_feedback_dataset_export(
    dataset_id: str,
    export_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    format: Literal["json", "jsonl", "provenance", "manifest"] = Query(default="jsonl"),
) -> Response:
    export, payload, media_type, filename = (
        await dataset_export_service.download_for_user(
            user_id=user_id,
            dataset_id=dataset_id,
            export_id=export_id,
            format=format,
        )
    )
    dataset_name = export.manifest.get("dataset_name") or dataset_id
    download_name = f"{dataset_name}-v{export.export_no}-{filename}"
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(download_name, safe='')}",
            "X-Manifest-Digest": export.manifest_digest,
            "X-Content-Digest": export.content_digest,
        },
    )


@feedback_dataset_router.get(
    "/{dataset_id}/samples", response_model=ApiResponse[DatasetSampleListResponse]
)
async def list_dataset_samples(
    dataset_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    status_filter: str | None = Query(
        default=None, alias="status", min_length=1, max_length=32
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Response:
    result = await dataset_service.list_dataset_samples_for_user(
        user_id=user_id,
        dataset_id=dataset_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return make_api_response(
        data=DatasetSampleListResponse(
            items=[
                DatasetSampleSummaryResponse.model_validate(item, from_attributes=True)
                for item in result.items
            ],
            total=result.total,
            limit=result.limit,
            offset=result.offset,
        )
    )


@feedback_dataset_router.get(
    "/{dataset_id}/samples/{sample_id}",
    response_model=ApiResponse[DatasetSampleDetailResponse],
)
async def get_dataset_sample(
    dataset_id: str,
    sample_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    result = await dataset_service.get_dataset_sample_for_user(
        user_id=user_id,
        dataset_id=dataset_id,
        sample_id=sample_id,
    )
    return make_api_response(data=_detail_response(result))


@feedback_dataset_router.patch(
    "/{dataset_id}/samples/{sample_id}",
    response_model=ApiResponse[DatasetSampleSummaryResponse],
)
async def update_dataset_sample(
    dataset_id: str,
    sample_id: str,
    payload: SampleRevisionUpdateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    try:
        value = payload.content
        messages = tuple(
            {"role": item.role, "content": item.content} for item in value.messages
        )
        context = tuple(
            {
                "document_title": item.document_title,
                "text": item.text,
            }
            for item in value.context
        )
        evidence = tuple(
            {
                "document_title": item.document_title,
                "text": item.text,
            }
            for item in value.evidence
        )
        if isinstance(value, SftRevisionContentRequest):
            content = SftRevisionContent(
                schema_version=value.schema_version,
                messages=messages,
                context=context,
                target=value.target,
                evidence=evidence,
            )
        elif isinstance(value, PreferenceRevisionContentRequest):
            content = PreferenceRevisionContent(
                schema_version=value.schema_version,
                messages=messages,
                context=context,
                response_a=value.response_a,
                response_b=value.response_b,
                suggested_preference=value.suggested_preference,
                rationale=value.rationale,
                evidence=evidence,
                human_preference=value.human_preference,
            )
        else:
            content = EvaluationRevisionContent(
                schema_version=value.schema_version,
                messages=messages,
                context=context,
                reference=value.reference,
                criteria=tuple(value.criteria),
                evaluation_mode=value.evaluation_mode,
                evidence=evidence,
            )
    except ValueError as exc:
        raise RequestInvalidException(
            str(exc), data={"code": "sample_content_invalid"}
        ) from exc
    result = await dataset_service.update_dataset_sample(
        user_id=user_id,
        dataset_id=dataset_id,
        sample_id=sample_id,
        expected_revision_id=payload.expected_revision_id,
        expected_generation=payload.expected_generation,
        content=content,
    )
    return make_api_response(
        data=DatasetSampleSummaryResponse.model_validate(result, from_attributes=True)
    )


@feedback_dataset_router.post(
    "/{dataset_id}/samples/{sample_id}/confirm",
    response_model=ApiResponse[DatasetSampleSummaryResponse],
)
async def confirm_dataset_sample(
    dataset_id: str,
    sample_id: str,
    payload: SampleConfirmRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    result = await dataset_service.confirm_dataset_sample(
        user_id=user_id,
        dataset_id=dataset_id,
        sample_id=sample_id,
        expected_revision_id=payload.expected_revision_id,
    )
    return make_api_response(
        data=DatasetSampleSummaryResponse.model_validate(result, from_attributes=True)
    )


@feedback_dataset_router.post(
    "/{dataset_id}/samples/{sample_id}/actions",
    response_model=ApiResponse[DatasetSampleSummaryResponse],
)
async def act_on_dataset_sample(
    dataset_id: str,
    sample_id: str,
    payload: SampleActionRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=128
    ),
) -> Response:
    result = await dataset_service.apply_dataset_sample_action_for_user(
        user_id=user_id,
        dataset_id=dataset_id,
        sample_id=sample_id,
        action=payload.action,
        expected_revision_id=payload.expected_revision_id,
        reason=payload.reason,
        idempotency_key=idempotency_key,
    )
    return make_api_response(
        data=DatasetSampleSummaryResponse.model_validate(result, from_attributes=True)
    )


@feedback_dataset_router.post(
    "/{dataset_id}/collections",
    response_model=ApiResponse[DatasetCollectionResponse],
    status_code=200,
)
async def collect_feedback_cases(
    dataset_id: str,
    payload: DatasetCollectionRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    result = await dataset_service.collect_dataset_cases_for_user(
        user_id=user_id,
        dataset_id=dataset_id,
        source_case_ids=tuple(payload.source_case_ids),
    )
    return make_api_response(
        data=DatasetCollectionResponse(
            operation_id=result.operation_id,
            created_count=result.created_count,
            existing_count=result.existing_count,
            items=[
                DatasetCollectionItemResponse(
                    sample_id=item.sample.sample_id,
                    source_case_id=item.sample.source_case_id,
                    status=item.sample.status,
                    job_id=(
                        item.job.job_id
                        if item.job is not None
                        else item.sample.active_job_id
                    ),
                )
                for item in result.items
            ],
        )
    )


__all__ = ["feedback_dataset_router"]
