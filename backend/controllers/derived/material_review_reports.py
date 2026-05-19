from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, Response

from application.core.research_view_aggregation_service import (
    ResearchViewMaterialNotFoundError,
    ResearchViewNotReadyError,
)
from application.derived.material_review_report_service import (
    MaterialReviewReportNotFoundError,
    MaterialReviewReportNotReadyError,
    MaterialReviewReportService,
)
from controllers.schemas.derived.material_review_report import (
    MaterialReviewReportRequest,
    MaterialReviewReportResponse,
)


router = APIRouter(prefix="/collections", tags=["material-review-reports"])
material_review_report_service = MaterialReviewReportService()


def _research_view_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "research_view_not_ready",
        "message": "The collection does not have research-view inputs yet. Finish indexing first.",
        "collection_id": collection_id,
    }


def _material_not_found_detail(exc: ResearchViewMaterialNotFoundError) -> dict[str, str | None]:
    return {
        "code": "research_view_material_not_found",
        "message": str(exc),
        "collection_id": exc.collection_id,
        "document_id": exc.document_id,
        "material_id": exc.material_id,
    }


def _report_not_found_detail(
    exc: MaterialReviewReportNotFoundError,
) -> dict[str, str]:
    return {
        "code": "material_review_report_not_found",
        "message": str(exc),
        "collection_id": exc.collection_id,
        "material_id": exc.material_id,
    }


def _report_not_ready_detail(
    exc: MaterialReviewReportNotReadyError,
) -> dict[str, str]:
    return {
        "code": "material_review_report_not_ready",
        "message": str(exc),
        "collection_id": exc.collection_id,
        "material_id": exc.material_id,
        "status": exc.status,
    }


def _generate_report_background(
    collection_id: str,
    material_id: str,
    request: MaterialReviewReportRequest,
) -> None:
    material_review_report_service.generate_review_report(
        collection_id,
        material_id,
        language=request.language,
        report_type=request.report_type,
        include_appendix=request.include_appendix,
        force_regenerate=False,
    )


@router.post(
    "/{collection_id}/materials/{material_id}/review-report",
    response_model=MaterialReviewReportResponse,
    summary="生成材料综述论文草稿",
)
async def create_material_review_report(
    collection_id: str,
    material_id: str,
    request: MaterialReviewReportRequest,
    background_tasks: BackgroundTasks,
) -> MaterialReviewReportResponse:
    try:
        payload = material_review_report_service.request_review_report(
            collection_id,
            material_id,
            language=request.language,
            report_type=request.report_type,
            include_appendix=request.include_appendix,
            force_regenerate=request.force_regenerate,
        )
    except ResearchViewMaterialNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_material_not_found_detail(exc)) from exc
    except ResearchViewNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_research_view_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if payload.get("status") == "generating":
        background_tasks.add_task(
            _generate_report_background,
            collection_id,
            material_id,
            request,
        )
    return MaterialReviewReportResponse(**payload)


@router.get(
    "/{collection_id}/materials/{material_id}/review-report",
    response_model=MaterialReviewReportResponse,
    summary="查询材料综述论文草稿状态",
)
async def get_material_review_report(
    collection_id: str,
    material_id: str,
) -> MaterialReviewReportResponse:
    try:
        payload = material_review_report_service.get_review_report_status(
            collection_id,
            material_id,
        )
    except MaterialReviewReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_report_not_found_detail(exc)) from exc
    return MaterialReviewReportResponse(**payload)


@router.get(
    "/{collection_id}/materials/{material_id}/review-report.md",
    summary="读取材料综述论文草稿 Markdown",
)
async def get_material_review_report_markdown(
    collection_id: str,
    material_id: str,
) -> Response:
    try:
        markdown = material_review_report_service.get_review_markdown(
            collection_id,
            material_id,
        )
    except MaterialReviewReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_report_not_found_detail(exc)) from exc
    except MaterialReviewReportNotReadyError as exc:
        raise HTTPException(status_code=409, detail=_report_not_ready_detail(exc)) from exc
    return Response(content=markdown, media_type="text/markdown; charset=utf-8")


@router.get(
    "/{collection_id}/materials/{material_id}/review-report.pdf",
    summary="下载材料综述论文草稿 PDF",
)
async def get_material_review_report_pdf(
    collection_id: str,
    material_id: str,
) -> FileResponse:
    try:
        path = material_review_report_service.get_review_pdf_path(
            collection_id,
            material_id,
        )
    except MaterialReviewReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_report_not_found_detail(exc)) from exc
    except MaterialReviewReportNotReadyError as exc:
        raise HTTPException(status_code=409, detail=_report_not_ready_detail(exc)) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
    )
