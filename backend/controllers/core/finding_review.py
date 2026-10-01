from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from controllers.dependencies.auth import current_user_id
from controllers.schemas.core.research_objectives import (
    FindingResponse,
    ObjectiveAnalysisStateResponse,
    ObjectiveEvidenceResponse,
)

FindingReviewStatus = Literal["correct", "incorrect", "partial", "unclear"]
FindingIssueType = Literal[
    "none",
    "evidence_not_grounded",
    "missing_evidence",
    "insufficient_evidence",
    "wrong_factor",
    "wrong_outcome",
    "wrong_direction",
    "wrong_context",
    "wrong_mechanism",
    "wrong_attribution",
    "wrong_synthesis",
    "overclaim",
    "unclear_statement",
    "other",
]
FindingStatus = Literal["supported", "limited", "conflicted", "unsupported"]
FindingDatasetLabelStatus = Literal["candidate", "silver", "gold", "rejected"]
FindingDatasetUseStatus = Literal["training_ready", "review_candidate", "rejected"]
FindingAbstentionReason = Literal[
    "no_comparable_evidence",
    "no_grounded_evidence",
    "insufficient_evidence",
]


class FindingAuthoringCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_analysis_version: int = Field(..., ge=1)
    selection_ids: list[str] = Field(default_factory=list, max_length=100)
    comparison_group_ids: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    parent_finding_id: str | None = Field(default=None, max_length=128)
    abstention_reason: FindingAbstentionReason | None = None

    @model_validator(mode="after")
    def validate_authoring_mode(self) -> "FindingAuthoringCreateRequest":
        if any(len(value.strip()) > 1000 for value in self.limitations):
            raise ValueError("Finding limitations cannot exceed 1000 characters")
        selected = self.selection_ids + self.comparison_group_ids
        if any(not value.strip() or len(value) > 128 for value in selected):
            raise ValueError(
                "experiment reference IDs must be non-empty and at most 128 characters"
            )
        if self.abstention_reason is not None:
            if selected or self.parent_finding_id is not None:
                raise ValueError("abstention cannot contain experiment selections")
            if not any(value.strip() for value in self.limitations):
                raise ValueError("abstention requires an explanation")
            return self
        if not self.selection_ids:
            raise ValueError("Finding requires at least one experiment selection")
        return self


class FindingAuthoringResponse(BaseModel):
    analysis: ObjectiveAnalysisStateResponse
    finding: FindingResponse | None = None
    abstention_reason: FindingAbstentionReason | None = None


class FindingFeedbackCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_version: int = Field(..., ge=1)
    review_status: FindingReviewStatus
    issue_type: FindingIssueType = Field(default="none")
    note: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_decision(self) -> "FindingFeedbackCreateRequest":
        if self.review_status == "correct" and self.issue_type != "none":
            raise ValueError("correct feedback cannot report an issue")
        if self.review_status in {"incorrect", "partial"} and self.issue_type == "none":
            raise ValueError(f"{self.review_status} feedback requires an issue")
        return self


class FindingFeedbackResponse(BaseModel):
    feedback_id: str
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    review_status: FindingReviewStatus
    issue_type: FindingIssueType
    note: str | None = None
    reviewer: str | None = None
    created_at: str


class FindingFeedbackListResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    items: list[FindingFeedbackResponse] = Field(default_factory=list)


class FindingCurationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_version: int = Field(..., ge=1)
    curated_status: FindingStatus = Field(default="limited")
    curated_finding: FindingResponse
    note: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=120)


class FindingCurationResponse(BaseModel):
    curation_id: str
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    curated_status: FindingStatus
    curated_finding: FindingResponse
    note: str | None = None
    reviewer: str | None = None
    updated_at: str


class FindingCurationListResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    items: list[FindingCurationResponse] = Field(default_factory=list)


class FindingDatasetSampleResponse(BaseModel):
    sample_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    research_objective: str
    document_ids: list[str] = Field(default_factory=list)
    label_status: FindingDatasetLabelStatus
    dataset_use_status: FindingDatasetUseStatus
    finding_fingerprint: str
    evidence_fingerprint: str
    system_prediction: FindingResponse
    expert_target: FindingResponse | None = None
    training_target: FindingResponse
    evidence: list[ObjectiveEvidenceResponse] = Field(default_factory=list)
    training_schema_version: str
    training_prompt_version: str
    training_messages: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FindingDatasetResponse(BaseModel):
    schema_version: str
    collection_id: str
    objective_id: str | None = None
    items: list[FindingDatasetSampleResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FindingGoldDraftResponse(BaseModel):
    gold_id: str
    collection_id: str
    version: str
    target_layer: str
    metric_profile: str
    items: list[dict[str, Any]] = Field(default_factory=list)


router = APIRouter(prefix="/collections", tags=["finding-review"])


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
        result = (
            await request.app.state.finding_authoring_service.create_selection_version(
                collection_id=collection_id,
                objective_id=objective_id,
                source_analysis_version=payload.source_analysis_version,
                created_by_user_id=await current_user_id(request),
                selection_ids=tuple(payload.selection_ids),
                comparison_group_ids=tuple(payload.comparison_group_ids),
                parent_finding_id=payload.parent_finding_id,
                limitations=tuple(payload.limitations),
                abstention_reason=payload.abstention_reason,
            )
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
    return FindingFeedbackResponse.model_validate(feedback, from_attributes=True)


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
        items=[
            FindingFeedbackResponse.model_validate(item, from_attributes=True)
            for item in records
        ],
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
    return FindingCurationResponse.model_validate(curation, from_attributes=True)


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
        items=[
            FindingCurationResponse.model_validate(item, from_attributes=True)
            for item in records
        ],
    )


@router.get(
    "/{collection_id}/objectives/{objective_id}/finding-dataset",
    summary="Export one Objective Finding dataset",
)
async def export_objective_finding_dataset(
    collection_id: str,
    objective_id: str,
    request: Request,
    format: str = Query(
        default="json",
        pattern="^(json|training_jsonl|llamafactory_alpaca)$",
    ),
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
    format: str = Query(
        default="json",
        pattern="^(json|training_jsonl|llamafactory_alpaca)$",
    ),
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
    if format == "llamafactory_alpaca":
        body = "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in _llamafactory_alpaca_rows(payload)
        )
        return Response(
            content=f"{body}\n" if body else "",
            media_type="application/x-ndjson",
        )
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


def _llamafactory_alpaca_rows(payload: dict):
    """Project Lens training rows into LlamaFactory's Alpaca contract."""

    for item in payload["items"]:
        if item["dataset_use_status"] != "training_ready":
            continue
        messages = item["training_messages"]
        instruction = next(
            (
                message["content"]
                for message in messages
                if message.get("role") == "user" and message.get("content")
            ),
            None,
        )
        output = next(
            (
                message["content"]
                for message in messages
                if message.get("role") == "assistant" and message.get("content")
            ),
            None,
        )
        if not instruction or not output:
            continue
        yield {
            "instruction": instruction,
            "input": "",
            "output": output,
            "metadata": item["metadata"],
        }
