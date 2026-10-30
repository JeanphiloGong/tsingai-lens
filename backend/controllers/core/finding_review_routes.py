from __future__ import annotations

import json
from dataclasses import asdict
from typing import Annotated, Any, Literal

from application.core.objectives import finding_authoring_service
from application.evaluation import finding_feedback_service
from application.evaluation.finding_feedback_service import finding_training_rows
from controllers.dependencies.auth import get_current_user_id
from controllers.schemas.core.research_objectives import (
    FindingResponse,
    ObjectiveAnalysisStateResponse,
    ObjectiveEvidenceAttributeResponse,
    ObjectiveEvidenceResponse,
    analysis_state_response,
)
from domain.core.finding import (
    Finding,
    FindingMechanismRelation,
    FindingPaperContribution,
)
from domain.core.scientific_fact import ScientificAttribute, ScientificContext
from exceptions import RequestInvalidException
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from utils.response import ApiResponse, make_api_response

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
    def validate_text_lengths(self) -> "FindingAuthoringCreateRequest":
        if any(len(value.strip()) > 1000 for value in self.limitations):
            raise ValueError("Finding limitations cannot exceed 1000 characters")
        selected = self.selection_ids + self.comparison_group_ids
        if any(not value.strip() or len(value) > 128 for value in selected):
            raise ValueError(
                "experiment reference IDs must be non-empty and at most 128 characters"
            )
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


finding_review_router = APIRouter(prefix="/collections", tags=["finding-review"])


@finding_review_router.post(
    "/{collection_id}/objectives/{objective_id}/findings",
    response_model=ApiResponse[FindingAuthoringResponse],
    status_code=200,
    summary="Create a researcher-authored Finding version",
)
async def create_finding_version(
    collection_id: str,
    objective_id: str,
    payload: FindingAuthoringCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    result = await finding_authoring_service.create_selection_version(
        collection_id=collection_id,
        objective_id=objective_id,
        source_analysis_version=payload.source_analysis_version,
        created_by_user_id=user_id,
        selection_ids=tuple(payload.selection_ids),
        comparison_group_ids=tuple(payload.comparison_group_ids),
        parent_finding_id=payload.parent_finding_id,
        limitations=tuple(payload.limitations),
        abstention_reason=payload.abstention_reason,
    )
    finding = None
    if result.finding is not None:
        finding = FindingResponse(
            **{
                **asdict(result.finding),
                "created_at": (
                    result.finding.created_at.isoformat()
                    if result.finding.created_at
                    else None
                ),
            }
        )
    return make_api_response(
        data=FindingAuthoringResponse(
            analysis=analysis_state_response(result.analysis),
            finding=finding,
            abstention_reason=result.analysis.abstention_reason,
        )
    )


@finding_review_router.post(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}/feedback",
    response_model=ApiResponse[FindingFeedbackResponse],
    summary="Record Finding feedback",
)
async def record_finding_feedback(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    payload: FindingFeedbackCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    feedback = await finding_feedback_service.record_feedback(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=payload.analysis_version,
        finding_id=finding_id,
        review_status=payload.review_status,
        issue_type=payload.issue_type,
        note=payload.note,
        reviewer=payload.reviewer,
        user_id=user_id,
    )
    return make_api_response(
        data=FindingFeedbackResponse.model_validate(feedback, from_attributes=True)
    )


@finding_review_router.get(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}/feedback",
    response_model=ApiResponse[FindingFeedbackListResponse],
    summary="List Finding feedback",
)
async def list_finding_feedback(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    analysis_version: int = Query(..., ge=1),
) -> Response:
    records = await finding_feedback_service.list_feedback(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
        finding_id=finding_id,
        user_id=user_id,
    )
    return make_api_response(
        data=FindingFeedbackListResponse(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
            finding_id=finding_id,
            items=[
                FindingFeedbackResponse.model_validate(item, from_attributes=True)
                for item in records
            ],
        )
    )


@finding_review_router.put(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}/curation",
    response_model=ApiResponse[FindingCurationResponse],
    summary="Curate a Finding",
)
async def record_finding_curation(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    payload: FindingCurationCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    try:
        value = payload.curated_finding
        candidate = Finding(
            collection_id=value.collection_id,
            objective_id=value.objective_id,
            analysis_version=value.analysis_version,
            finding_id=value.finding_id,
            statement=value.statement,
            factors=tuple(value.factors),
            outcome=value.outcome,
            direction=value.direction,
            assertion_strength=value.assertion_strength,
            attribution_scope=value.attribution_scope,
            synthesis_status=value.synthesis_status,
            certainty=value.certainty,
            display_rank=value.display_rank,
            mechanisms=tuple(
                FindingMechanismRelation(
                    source_term=item.source_term,
                    relation_type=item.relation_type,
                    target_term=item.target_term,
                    direction=item.direction,
                    assertion_strength=item.assertion_strength,
                    supporting_evidence_ids=tuple(item.supporting_evidence_ids),
                )
                for item in value.mechanisms
            ),
            scientific_context=ScientificContext(
                material=_review_context_attributes(value.scientific_context.material),
                sample=_review_context_attributes(value.scientific_context.sample),
                process=_review_context_attributes(value.scientific_context.process),
                test=_review_context_attributes(value.scientific_context.test),
            ),
            limitations=tuple(value.limitations),
            paper_contributions=tuple(
                FindingPaperContribution(
                    document_id=item.document_id,
                    analysis_status=item.analysis_status,
                    supporting_evidence_ids=tuple(item.supporting_evidence_ids),
                    contradicting_evidence_ids=tuple(item.contradicting_evidence_ids),
                    context_evidence_ids=tuple(item.context_evidence_ids),
                    condition_boundary_evidence_ids=tuple(
                        item.condition_boundary_evidence_ids
                    ),
                )
                for item in value.paper_contributions
            ),
            selection_ids=tuple(value.selection_ids),
            comparison_group_ids=tuple(value.comparison_group_ids),
            origin=value.origin,
            source_analysis_version=value.source_analysis_version,
            parent_finding_id=value.parent_finding_id,
            created_by_user_id=value.created_by_user_id,
            created_by_tool_call_id=value.created_by_tool_call_id,
            created_at=value.created_at,
            warnings=tuple(value.warnings),
        )
    except ValueError as exc:
        raise RequestInvalidException(
            str(exc), data={"code": "curation_invalid"}
        ) from exc
    curation = await finding_feedback_service.record_curation(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=payload.analysis_version,
        finding_id=finding_id,
        curated_status=payload.curated_status,
        curated_finding=candidate,
        note=payload.note,
        reviewer=payload.reviewer,
        user_id=user_id,
    )
    return make_api_response(
        data=FindingCurationResponse.model_validate(curation, from_attributes=True)
    )


@finding_review_router.get(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}/curation",
    response_model=ApiResponse[FindingCurationListResponse],
    summary="List Finding curations",
)
async def list_finding_curations(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    analysis_version: int = Query(..., ge=1),
) -> Response:
    records = await finding_feedback_service.list_curations(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
        finding_id=finding_id,
        user_id=user_id,
    )
    return make_api_response(
        data=FindingCurationListResponse(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
            finding_id=finding_id,
            items=[
                FindingCurationResponse.model_validate(item, from_attributes=True)
                for item in records
            ],
        )
    )


@finding_review_router.get(
    "/{collection_id}/objectives/{objective_id}/finding-dataset",
    summary="Export one Objective Finding dataset",
    response_model=ApiResponse[FindingDatasetResponse],
    responses={
        200: {"content": {"application/x-ndjson": {"schema": {"type": "string"}}}}
    },
)
async def export_objective_finding_dataset(
    collection_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    format: str = Query(
        default="json",
        pattern="^(json|training_jsonl|llamafactory_alpaca)$",
    ),
    label_status: str | None = Query(default=None),
    dataset_use_status: str | None = Query(default=None),
):
    payload = await finding_feedback_service.export_dataset(
        collection_id=collection_id,
        objective_id=objective_id,
        label_status=label_status,
        dataset_use_status=dataset_use_status,
        user_id=user_id,
    )
    return _dataset_response(payload, format)


@finding_review_router.get(
    "/{collection_id}/finding-dataset",
    summary="Export the collection Finding dataset",
    response_model=ApiResponse[FindingDatasetResponse],
    responses={
        200: {"content": {"application/x-ndjson": {"schema": {"type": "string"}}}}
    },
)
async def export_collection_finding_dataset(
    collection_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    format: str = Query(
        default="json",
        pattern="^(json|training_jsonl|llamafactory_alpaca)$",
    ),
    label_status: str | None = Query(default=None),
    dataset_use_status: str | None = Query(default=None),
):
    payload = await finding_feedback_service.export_collection_dataset(
        collection_id=collection_id,
        label_status=label_status,
        dataset_use_status=dataset_use_status,
        user_id=user_id,
    )
    return _dataset_response(payload, format)


@finding_review_router.get(
    "/{collection_id}/finding-gold-draft",
    response_model=ApiResponse[FindingGoldDraftResponse],
    summary="Export expert-confirmed Finding gold draft",
)
async def export_finding_gold_draft(
    collection_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await finding_feedback_service.export_gold_draft(
        collection_id=collection_id, user_id=user_id
    )
    return make_api_response(data=FindingGoldDraftResponse(**payload))


def _dataset_response(payload: dict, format: str):
    if format == "json":
        return make_api_response(data=FindingDatasetResponse(**payload))
    body = "\n".join(
        json.dumps(row, ensure_ascii=False)
        for row in finding_training_rows(payload, format)
    )
    return Response(
        content=f"{body}\n" if body else "",
        media_type="application/x-ndjson",
    )


def _review_context_attributes(
    values: list[ObjectiveEvidenceAttributeResponse],
) -> tuple[ScientificAttribute, ...]:
    return tuple(
        ScientificAttribute(
            name=item.name,
            value=item.value,
            unit=item.unit,
            context_scope=item.context_scope,
            applies_to_outcomes=tuple(item.applies_to_outcomes),
        )
        for item in values
    )
