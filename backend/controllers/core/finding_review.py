from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from controllers.dependencies.auth import current_user_id
from controllers.schemas.core.finding_review import (
    EvidenceAuthoringCreateRequest,
    EvidenceAuthoringResponse,
    FindingAuthoringCreateRequest,
    FindingAuthoringResponse,
    FindingCurationCreateRequest,
    FindingCurationListResponse,
    FindingCurationResponse,
    FindingFeedbackCreateRequest,
    FindingFeedbackListResponse,
    FindingFeedbackResponse,
    FindingDatasetResponse,
    FindingGoldDraftResponse,
)


router = APIRouter(prefix="/collections", tags=["finding-review"])


@router.post(
    "/{collection_id}/objectives/{objective_id}/evidence",
    response_model=EvidenceAuthoringResponse,
    status_code=201,
    summary="Create a researcher-confirmed Evidence version",
)
async def create_evidence_version(
    collection_id: str,
    objective_id: str,
    payload: EvidenceAuthoringCreateRequest,
    request: Request,
) -> EvidenceAuthoringResponse:
    try:
        result = await request.app.state.evidence_authoring_service.create_version(
            collection_id=collection_id,
            objective_id=objective_id,
            source_analysis_version=payload.source_analysis_version,
            document_id=payload.document_id,
            source_kind=payload.source_kind,
            source_ref=payload.source_ref,
            source_excerpt=payload.source_excerpt,
            evidence_role=payload.evidence_role,
            changed_variables=tuple(
                item.model_dump() for item in payload.changed_variables
            ),
            comparison=(payload.comparison.model_dump() if payload.comparison else None),
            reported_result=(
                payload.reported_result.model_dump() if payload.reported_result else None
            ),
            attribution_scope=payload.attribution_scope,
            scientific_context=payload.scientific_context.model_dump(),
            supersedes_evidence_id=payload.supersedes_evidence_id,
            authoring_note=payload.authoring_note,
            created_by_user_id=await current_user_id(request),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return EvidenceAuthoringResponse(
        analysis=result.analysis.to_record(),
        evidence={
            **result.evidence.to_record(),
            "supports_finding": result.evidence.supports_finding,
        },
    )


@router.post(
    "/{collection_id}/objectives/{objective_id}/findings",
    response_model=FindingAuthoringResponse,
    status_code=201,
    summary="Create a researcher-authored Finding version",
)
async def create_finding_version(
    collection_id: str,
    objective_id: str,
    payload: FindingAuthoringCreateRequest,
    request: Request,
) -> FindingAuthoringResponse:
    try:
        result = await request.app.state.finding_authoring_service.create_version(
            collection_id=collection_id,
            objective_id=objective_id,
            source_analysis_version=payload.source_analysis_version,
            statement=payload.statement,
            assertion_strength=payload.assertion_strength,
            supporting_evidence_ids=tuple(payload.supporting_evidence_ids),
            contradicting_evidence_ids=tuple(payload.contradicting_evidence_ids),
            context_evidence_ids=tuple(payload.context_evidence_ids),
            condition_boundary_evidence_ids=tuple(
                payload.condition_boundary_evidence_ids
            ),
            limitations=tuple(payload.limitations),
            parent_finding_id=payload.parent_finding_id,
            abstention_reason=payload.abstention_reason,
            created_by_user_id=await current_user_id(request),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FindingAuthoringResponse(
        analysis=result.analysis.to_record(),
        finding=(result.finding.to_record() if result.finding is not None else None),
        abstention_reason=result.analysis.abstention_reason,
    )


@router.post(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}/feedback",
    response_model=FindingFeedbackResponse,
    summary="Record Finding feedback",
)
async def record_finding_feedback(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    payload: FindingFeedbackCreateRequest,
    request: Request,
) -> FindingFeedbackResponse:
    try:
        feedback = await request.app.state.finding_feedback_service.record_feedback(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=payload.analysis_version,
            finding_id=finding_id,
            review_status=payload.review_status,
            issue_type=payload.issue_type,
            note=payload.note,
            reviewer=payload.reviewer,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FindingFeedbackResponse(**feedback.to_record())


@router.get(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}/feedback",
    response_model=FindingFeedbackListResponse,
    summary="List Finding feedback",
)
async def list_finding_feedback(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    request: Request,
    analysis_version: int = Query(..., ge=1),
) -> FindingFeedbackListResponse:
    try:
        records = await request.app.state.finding_feedback_service.list_feedback(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
            finding_id=finding_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FindingFeedbackListResponse(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
        finding_id=finding_id,
        items=[FindingFeedbackResponse(**item.to_record()) for item in records],
    )


@router.put(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}/curation",
    response_model=FindingCurationResponse,
    summary="Curate a Finding",
)
async def record_finding_curation(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    payload: FindingCurationCreateRequest,
    request: Request,
) -> FindingCurationResponse:
    try:
        curation = await request.app.state.finding_feedback_service.record_curation(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=payload.analysis_version,
            finding_id=finding_id,
            curated_status=payload.curated_status,
            curated_finding=payload.curated_finding.model_dump(),
            note=payload.note,
            reviewer=payload.reviewer,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FindingCurationResponse(**curation.to_record())


@router.get(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}/curation",
    response_model=FindingCurationListResponse,
    summary="List Finding curations",
)
async def list_finding_curations(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    request: Request,
    analysis_version: int = Query(..., ge=1),
) -> FindingCurationListResponse:
    try:
        records = await request.app.state.finding_feedback_service.list_curations(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
            finding_id=finding_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FindingCurationListResponse(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
        finding_id=finding_id,
        items=[FindingCurationResponse(**item.to_record()) for item in records],
    )


@router.get(
    "/{collection_id}/objectives/{objective_id}/finding-dataset",
    summary="Export one Objective Finding dataset",
)
async def export_objective_finding_dataset(
    collection_id: str,
    objective_id: str,
    request: Request,
    format: str = Query(default="json", pattern="^(json|training_jsonl)$"),
    label_status: str | None = Query(default=None),
    dataset_use_status: str | None = Query(default=None),
):
    try:
        payload = await request.app.state.finding_feedback_service.export_dataset(
            collection_id=collection_id,
            objective_id=objective_id,
            label_status=label_status,
            dataset_use_status=dataset_use_status,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _dataset_response(payload, format)


@router.get(
    "/{collection_id}/finding-dataset",
    summary="Export the collection Finding dataset",
)
async def export_collection_finding_dataset(
    collection_id: str,
    request: Request,
    format: str = Query(default="json", pattern="^(json|training_jsonl)$"),
    label_status: str | None = Query(default=None),
    dataset_use_status: str | None = Query(default=None),
):
    payload = await request.app.state.finding_feedback_service.export_collection_dataset(
        collection_id=collection_id,
        label_status=label_status,
        dataset_use_status=dataset_use_status,
    )
    return _dataset_response(payload, format)


@router.get(
    "/{collection_id}/finding-gold-draft",
    response_model=FindingGoldDraftResponse,
    summary="Export expert-confirmed Finding gold draft",
)
async def export_finding_gold_draft(
    collection_id: str,
    request: Request,
) -> FindingGoldDraftResponse:
    payload = await request.app.state.finding_feedback_service.export_gold_draft(
        collection_id=collection_id,
    )
    return FindingGoldDraftResponse(**payload)


def _dataset_response(payload: dict, format: str):
    if format == "json":
        return FindingDatasetResponse(**payload)
    body = "\n".join(
        json.dumps(
            {"messages": item["training_messages"], "metadata": item["metadata"]},
            ensure_ascii=False,
        )
        for item in payload["items"]
        if item["dataset_use_status"] == "training_ready"
        and item["training_messages"]
    )
    return Response(
        content=f"{body}\n" if body else "",
        media_type="application/x-ndjson",
    )
