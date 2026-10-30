from __future__ import annotations

import json
from typing import Mapping
from unittest.mock import AsyncMock

import pytest

from application.evaluation.finding_feedback_service import parse_curated_finding
from controllers.core import finding_review_routes
from controllers.core.finding_review_routes import finding_review_router as router
from controllers.dependencies.auth import get_current_user_id
from controllers.exception_router import (
    general_exception_handler,
    http_exception_handler,
    project_exception_handler,
    request_validation_handler,
)
from domain.core import Finding, ObjectiveEvidence
from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    FINDING_ASSERTION_STRENGTHS,
    FINDING_ORIGINS,
    FINDING_SYNTHESIS_STATUSES,
    PAPER_CONTRIBUTION_STATUSES,
    Finding,
    FindingMechanismRelation,
    FindingPaperContribution,
    datetime,
)
from domain.core.research_objective import (
    ObjectiveEvidence,
    PreparedDocumentInput,
)
from domain.core.scientific_fact import (
    SCIENTIFIC_CONTEXT_SCOPES,
    SCIENTIFIC_RESULT_DIRECTIONS,
    ScientificAttribute,
    ScientificComparison,
    ScientificContext,
    ScientificResult,
    ScientificVariable,
)
from domain.evaluation import (
    FindingCuration,
    FindingFeedback,
)
from domain.evaluation.records import FindingFeedbackDecisionError
from exceptions import (
    ProjectException,
    RequestInvalidException,
    ResourceConflictException,
)
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from repositories.objective_repository import (
    ExecutionStats,
    ObjectiveAnalysis,
)
from starlette.exceptions import HTTPException as StarletteHTTPException


class _Service:
    def __init__(self) -> None:
        self.authoring_kwargs = None

    async def create_selection_version(self, **kwargs):
        from application.core.objectives.finding_authoring_service import (
            FindingAuthoringResult,
        )

        self.authoring_kwargs = kwargs
        if not kwargs["selection_ids"] and kwargs["abstention_reason"] is None:
            from exceptions import RequestInvalidException
            raise RequestInvalidException("Finding requires an experiment selection")
        analysis = ObjectiveAnalysis(
            collection_id=kwargs["collection_id"] or "",
            objective_id=kwargs["objective_id"] or "",
            analysis_version=int(2),
            document_inputs=(
                PreparedDocumentInput(
                    document_id="paper-1", preparation_fingerprint="fingerprint-1"
                ),
            ),
            pipeline_version="test.v1",
            model_name="model-1",
            prompt_versions={str(key): str(value) for key, value in dict({}).items()},
            stats=ExecutionStats(duration_ms=None, model_usage=(), prompt_versions={}),
            status="succeeded",
            phase="completed",
            processed_document_count=int(1),
            total_document_count=int(1),
            origin="hybrid",
            scientific_record_source="authored_snapshot",
            source_analysis_version=1,
            created_by_user_id=kwargs["created_by_user_id"],
            abstention_reason=kwargs.get("abstention_reason"),
            abstention_note=(
                "\n".join(kwargs.get("limitations", ()))
                if kwargs.get("abstention_reason")
                else None
            ),
        )
        finding = Finding(
            collection_id=_finding_record().get("collection_id", None) or "",
            objective_id=_finding_record().get("objective_id", None) or "",
            analysis_version=2,
            finding_id="finding-manual-1",
            statement=_finding_record().get("statement", None) or "",
            factors=tuple(_finding_record().get("factors", None) or ()),
            outcome=_finding_record().get("outcome", None) or "",
            direction=_finding_record().get("direction", None),
            assertion_strength=_finding_record().get("assertion_strength", None),
            attribution_scope=_finding_record().get("attribution_scope", None),
            synthesis_status=_finding_record().get("synthesis_status", None),
            certainty=_finding_record().get("certainty", None),
            display_rank=_finding_record().get("display_rank", None),
            mechanisms=tuple(
                (
                    FindingMechanismRelation(
                        source_term=item.get("source_term") or "",
                        relation_type=item.get("relation_type") or "",
                        target_term=item.get("target_term") or "",
                        direction=item.get("direction"),
                        assertion_strength=item.get("assertion_strength"),
                        supporting_evidence_ids=tuple(
                            item.get("supporting_evidence_ids") or ()
                        ),
                    )
                    for item in tuple(
                        (
                            dict(item)
                            for item in (
                                _finding_record().get("mechanisms", None)
                                if isinstance(
                                    _finding_record().get("mechanisms", None),
                                    (list, tuple),
                                )
                                else ()
                            )
                            if isinstance(item, Mapping)
                        )
                    )
                )
            ),
            scientific_context=ScientificContext(
                material=tuple(
                    (
                        ScientificAttribute(
                            name=attribute.get("name") or "",
                            value=(
                                attribute.get("value")
                                if attribute.get("value") is not None
                                else ""
                            ),
                            unit=attribute.get("unit"),
                            context_scope=attribute.get("context_scope"),
                            applies_to_outcomes=tuple(
                                attribute.get("applies_to_outcomes") or ()
                            ),
                        )
                        for attribute in (
                            (
                                dict(_finding_record().get("scientific_context", None))
                                if isinstance(
                                    _finding_record().get("scientific_context", None),
                                    Mapping,
                                )
                                else {}
                            ).get("material")
                            if isinstance(
                                (
                                    dict(
                                        _finding_record().get(
                                            "scientific_context", None
                                        )
                                    )
                                    if isinstance(
                                        _finding_record().get(
                                            "scientific_context", None
                                        ),
                                        Mapping,
                                    )
                                    else {}
                                ).get("material"),
                                (list, tuple),
                            )
                            else ()
                        )
                        if isinstance(attribute, Mapping)
                    )
                ),
                sample=tuple(
                    (
                        ScientificAttribute(
                            name=attribute.get("name") or "",
                            value=(
                                attribute.get("value")
                                if attribute.get("value") is not None
                                else ""
                            ),
                            unit=attribute.get("unit"),
                            context_scope=attribute.get("context_scope"),
                            applies_to_outcomes=tuple(
                                attribute.get("applies_to_outcomes") or ()
                            ),
                        )
                        for attribute in (
                            (
                                dict(_finding_record().get("scientific_context", None))
                                if isinstance(
                                    _finding_record().get("scientific_context", None),
                                    Mapping,
                                )
                                else {}
                            ).get("sample")
                            if isinstance(
                                (
                                    dict(
                                        _finding_record().get(
                                            "scientific_context", None
                                        )
                                    )
                                    if isinstance(
                                        _finding_record().get(
                                            "scientific_context", None
                                        ),
                                        Mapping,
                                    )
                                    else {}
                                ).get("sample"),
                                (list, tuple),
                            )
                            else ()
                        )
                        if isinstance(attribute, Mapping)
                    )
                ),
                process=tuple(
                    (
                        ScientificAttribute(
                            name=attribute.get("name") or "",
                            value=(
                                attribute.get("value")
                                if attribute.get("value") is not None
                                else ""
                            ),
                            unit=attribute.get("unit"),
                            context_scope=attribute.get("context_scope"),
                            applies_to_outcomes=tuple(
                                attribute.get("applies_to_outcomes") or ()
                            ),
                        )
                        for attribute in (
                            (
                                dict(_finding_record().get("scientific_context", None))
                                if isinstance(
                                    _finding_record().get("scientific_context", None),
                                    Mapping,
                                )
                                else {}
                            ).get("process")
                            if isinstance(
                                (
                                    dict(
                                        _finding_record().get(
                                            "scientific_context", None
                                        )
                                    )
                                    if isinstance(
                                        _finding_record().get(
                                            "scientific_context", None
                                        ),
                                        Mapping,
                                    )
                                    else {}
                                ).get("process"),
                                (list, tuple),
                            )
                            else ()
                        )
                        if isinstance(attribute, Mapping)
                    )
                ),
                test=tuple(
                    (
                        ScientificAttribute(
                            name=attribute.get("name") or "",
                            value=(
                                attribute.get("value")
                                if attribute.get("value") is not None
                                else ""
                            ),
                            unit=attribute.get("unit"),
                            context_scope=attribute.get("context_scope"),
                            applies_to_outcomes=tuple(
                                attribute.get("applies_to_outcomes") or ()
                            ),
                        )
                        for attribute in (
                            (
                                dict(_finding_record().get("scientific_context", None))
                                if isinstance(
                                    _finding_record().get("scientific_context", None),
                                    Mapping,
                                )
                                else {}
                            ).get("test")
                            if isinstance(
                                (
                                    dict(
                                        _finding_record().get(
                                            "scientific_context", None
                                        )
                                    )
                                    if isinstance(
                                        _finding_record().get(
                                            "scientific_context", None
                                        ),
                                        Mapping,
                                    )
                                    else {}
                                ).get("test"),
                                (list, tuple),
                            )
                            else ()
                        )
                        if isinstance(attribute, Mapping)
                    )
                ),
            ),
            limitations=tuple(
                (list(kwargs.get("limitations", ())) or ["Supported by one paper."])
                or ()
            ),
            paper_contributions=tuple(
                (
                    FindingPaperContribution(
                        document_id=item.get("document_id") or "",
                        analysis_status=item.get("analysis_status"),
                        supporting_evidence_ids=tuple(
                            item.get("supporting_evidence_ids") or ()
                        ),
                        contradicting_evidence_ids=tuple(
                            item.get("contradicting_evidence_ids") or ()
                        ),
                        context_evidence_ids=tuple(
                            item.get("context_evidence_ids") or ()
                        ),
                        condition_boundary_evidence_ids=tuple(
                            item.get("condition_boundary_evidence_ids") or ()
                        ),
                    )
                    for item in tuple(
                        (
                            dict(item)
                            for item in (
                                _finding_record().get("paper_contributions", None)
                                if isinstance(
                                    _finding_record().get("paper_contributions", None),
                                    (list, tuple),
                                )
                                else ()
                            )
                            if isinstance(item, Mapping)
                        )
                    )
                )
            ),
            origin="hybrid" if kwargs.get("parent_finding_id") else "human_authored",
            source_analysis_version=1,
            parent_finding_id=kwargs.get("parent_finding_id"),
            created_by_user_id=kwargs["created_by_user_id"],
            created_by_tool_call_id=_finding_record().get(
                "created_by_tool_call_id", None
            ),
            created_at=datetime.fromisoformat("2026-09-01T00:00:00+00:00"),
            warnings=tuple(_finding_record().get("warnings", None) or ()),
            selection_ids=tuple(_finding_record().get("selection_ids", None) or ()),
            comparison_group_ids=tuple(
                _finding_record().get("comparison_group_ids", None) or ()
            ),
        )
        return FindingAuthoringResult(
            analysis=analysis,
            finding=None if kwargs.get("abstention_reason") else finding,
        )

    async def record_feedback(self, *, user_id: str, **kwargs):
        assert user_id == "user-researcher"
        try:
            return FindingFeedback(
                **{
                    "note": None,
                    "reviewer": None,
                    "feedback_id": "feedback-1",
                    **kwargs,
                    "created_at": "2026-07-22T00:00:00+00:00",
                }
            )
        except FindingFeedbackDecisionError as exc:
            raise RequestInvalidException(
                str(exc), data={"code": "finding_feedback_invalid"}
            ) from exc

    async def list_feedback(self, **kwargs):
        if kwargs["analysis_version"] != 1:
            raise ResourceConflictException(
                "review must reference the published analysis version",
                data={"code": "analysis_version_not_published"},
            )
        return (
            await self.record_feedback(
                **kwargs,
                review_status="correct",
                issue_type="none",
            ),
        )

    async def record_curation(self, *, user_id: str, **kwargs):
        return FindingCuration(
            curation_id="curation-1",
            **kwargs,
            updated_at="2026-07-22T00:00:00+00:00",
        )

    async def list_curations(self, **kwargs):
        if kwargs["analysis_version"] != 1:
            raise ResourceConflictException(
                "review must reference the published analysis version",
                data={"code": "analysis_version_not_published"},
            )
        return (
            await self.record_curation(
                **kwargs,
                curated_status="limited",
                curated_finding=parse_curated_finding(
                    _finding_record("Narrower expert statement.")
                ),
            ),
        )

    async def export_dataset(self, **kwargs):
        return _dataset(kwargs["collection_id"], kwargs["objective_id"])

    async def export_collection_dataset(self, **kwargs):
        return _dataset(kwargs["collection_id"], None)

    async def export_gold_draft(self, **kwargs):
        return {
            "gold_id": "gold-1",
            "collection_id": kwargs["collection_id"],
            "version": "objective_finding_dataset.v2",
            "target_layer": "core",
            "metric_profile": "objective_findings_v1",
            "items": [],
        }


def _dataset(collection_id: str, objective_id: str | None) -> dict:
    finding = _finding_record()
    evidence = _evidence_record()
    return {
        "schema_version": "objective_finding_dataset.v2",
        "collection_id": collection_id,
        "objective_id": objective_id,
        "items": [
            {
                "sample_id": "sample-1",
                "objective_id": objective_id or "obj-1",
                "analysis_version": 1,
                "finding_id": "finding-1",
                "research_objective": "How does temperature affect strength?",
                "document_ids": ["paper-1"],
                "label_status": "gold",
                "dataset_use_status": "training_ready",
                "finding_fingerprint": "finding.v2:abc",
                "evidence_fingerprint": "evidence.v2:def",
                "system_prediction": finding,
                "expert_target": None,
                "training_target": finding,
                "evidence": [evidence],
                "training_schema_version": "objective_finding_training.v2",
                "training_prompt_version": "objective_finding_training_prompt.v2",
                "training_messages": [
                    {
                        "role": "user",
                        "content": "Evidence: At 500 C, strength reached 620 MPa.",
                    },
                    {"role": "assistant", "content": "{}"},
                ],
                "metadata": {"analysis_version": 1},
            }
        ],
        "warnings": [],
    }


def _finding_record(statement: str = "Temperature affects strength.") -> dict:
    expected_finding = Finding(
        collection_id="col-1",
        objective_id="obj-1",
        analysis_version=1,
        finding_id="finding-1",
        statement=statement or "",
        factors=("temperature",),
        outcome="strength",
        direction="increase",
        assertion_strength="associative",
        attribution_scope="isolated_effect",
        synthesis_status="insufficient_confirmation",
        certainty=0.5,
        display_rank=0,
        mechanisms=(),
        scientific_context=ScientificContext(),
        limitations=("Supported by one paper.",),
        paper_contributions=(
            FindingPaperContribution(
                document_id="paper-1",
                analysis_status="analyzed",
                supporting_evidence_ids=("evidence-1",),
            ),
        ),
    )
    return {
        "collection_id": expected_finding.collection_id,
        "objective_id": expected_finding.objective_id,
        "analysis_version": expected_finding.analysis_version,
        "finding_id": expected_finding.finding_id,
        "statement": expected_finding.statement,
        "factors": list(expected_finding.factors),
        "outcome": expected_finding.outcome,
        "direction": expected_finding.direction,
        "assertion_strength": expected_finding.assertion_strength,
        "attribution_scope": expected_finding.attribution_scope,
        "synthesis_status": expected_finding.synthesis_status,
        "certainty": expected_finding.certainty,
        "display_rank": expected_finding.display_rank,
        "mechanisms": [
            {
                "source_term": mechanism.source_term,
                "relation_type": mechanism.relation_type,
                "target_term": mechanism.target_term,
                "direction": mechanism.direction,
                "assertion_strength": mechanism.assertion_strength,
                "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
            }
            for mechanism in expected_finding.mechanisms
        ],
        "scientific_context": {
            "material": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in expected_finding.scientific_context.material
            ],
            "sample": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in expected_finding.scientific_context.sample
            ],
            "process": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in expected_finding.scientific_context.process
            ],
            "test": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in expected_finding.scientific_context.test
            ],
        },
        "limitations": list(expected_finding.limitations),
        "paper_contributions": [
            {
                "document_id": contribution.document_id,
                "analysis_status": contribution.analysis_status,
                "supporting_evidence_ids": list(contribution.supporting_evidence_ids),
                "contradicting_evidence_ids": list(
                    contribution.contradicting_evidence_ids
                ),
                "context_evidence_ids": list(contribution.context_evidence_ids),
                "condition_boundary_evidence_ids": list(
                    contribution.condition_boundary_evidence_ids
                ),
            }
            for contribution in expected_finding.paper_contributions
        ],
        "origin": expected_finding.origin,
        "source_analysis_version": expected_finding.source_analysis_version,
        "parent_finding_id": expected_finding.parent_finding_id,
        "created_by_user_id": expected_finding.created_by_user_id,
        "created_by_tool_call_id": expected_finding.created_by_tool_call_id,
        "created_at": (
            expected_finding.created_at.isoformat()
            if expected_finding.created_at
            else None
        ),
        **(
            {"selection_ids": list(expected_finding.selection_ids)}
            if expected_finding.selection_ids
            else {}
        ),
        **(
            {"comparison_group_ids": list(expected_finding.comparison_group_ids)}
            if expected_finding.comparison_group_ids
            else {}
        ),
        **(
            {"warnings": list(expected_finding.warnings)}
            if expected_finding.warnings
            else {}
        ),
    }


def _evidence_record() -> dict:
    expected_objective_evidence = ObjectiveEvidence(
        collection_id="col-1",
        objective_id="obj-1",
        analysis_version=1,
        evidence_id="evidence-1",
        document_id="paper-1",
        source_kind="text_window",
        source_ref="block-7",
        source_excerpt="At 500 C, strength reached 620 MPa.",
        page_numbers=(7,),
        related_source_refs=(),
        evidence_role="direct_result",
        selection_status="extracted",
        selection_reason=None,
        changed_variables=(
            ScientificVariable(
                name="temperature", baseline_value=400, target_value=500, unit="C"
            ),
        ),
        comparison=ScientificComparison(
            baseline_label="400 C",
            target_label="500 C",
            axis_names=("temperature",),
            comparable=True,
        ),
        reported_result=ScientificResult(
            outcome="strength",
            value=None,
            unit=None,
            direction="increase",
            result_text="Strength reached 620 MPa.",
        ),
        attribution_scope="isolated_effect",
        scientific_context=ScientificContext(),
        resolution_status="resolved",
        failure_reason=None,
        confidence=0.9,
    )
    return {
        "collection_id": expected_objective_evidence.collection_id,
        "objective_id": expected_objective_evidence.objective_id,
        "analysis_version": expected_objective_evidence.analysis_version,
        "evidence_id": expected_objective_evidence.evidence_id,
        "document_id": expected_objective_evidence.document_id,
        "source_kind": expected_objective_evidence.source_kind,
        "source_ref": expected_objective_evidence.source_ref,
        "source_excerpt": expected_objective_evidence.source_excerpt,
        "page_numbers": list(expected_objective_evidence.page_numbers),
        "evidence_role": expected_objective_evidence.evidence_role,
        "selection_status": expected_objective_evidence.selection_status,
        "selection_reason": expected_objective_evidence.selection_reason,
        "evidence_status": expected_objective_evidence.evidence_status,
        "evidence_status_reason": expected_objective_evidence.evidence_status_reason,
        "changed_variables": [
            {
                "name": variable.name,
                "baseline_value": variable.baseline_value,
                "target_value": variable.target_value,
                "unit": variable.unit,
            }
            for variable in expected_objective_evidence.changed_variables
        ],
        "comparison": (
            {
                "baseline_label": expected_objective_evidence.comparison.baseline_label,
                "target_label": expected_objective_evidence.comparison.target_label,
                "axis_names": list(expected_objective_evidence.comparison.axis_names),
                "comparable": expected_objective_evidence.comparison.comparable,
                "incomparability_reasons": list(
                    expected_objective_evidence.comparison.incomparability_reasons
                ),
            }
            if expected_objective_evidence.comparison
            else None
        ),
        "reported_result": (
            {
                "outcome": expected_objective_evidence.reported_result.outcome,
                "value": expected_objective_evidence.reported_result.value,
                "baseline_value": expected_objective_evidence.reported_result.baseline_value,
                "target_value": expected_objective_evidence.reported_result.target_value,
                "unit": expected_objective_evidence.reported_result.unit,
                "direction": expected_objective_evidence.reported_result.direction,
                "result_text": expected_objective_evidence.reported_result.result_text,
                "result_kind": expected_objective_evidence.reported_result.result_kind,
            }
            if expected_objective_evidence.reported_result
            else None
        ),
        "attribution_scope": expected_objective_evidence.attribution_scope,
        "scientific_context": {
            "material": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in expected_objective_evidence.scientific_context.material
            ],
            "sample": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in expected_objective_evidence.scientific_context.sample
            ],
            "process": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in expected_objective_evidence.scientific_context.process
            ],
            "test": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in expected_objective_evidence.scientific_context.test
            ],
        },
        "resolution_status": expected_objective_evidence.resolution_status,
        "failure_reason": expected_objective_evidence.failure_reason,
        "confidence": expected_objective_evidence.confidence,
        "origin": expected_objective_evidence.origin,
        "source_analysis_version": expected_objective_evidence.source_analysis_version,
        "supersedes_evidence_id": expected_objective_evidence.supersedes_evidence_id,
        "superseded_by_evidence_id": expected_objective_evidence.superseded_by_evidence_id,
        "created_by_user_id": expected_objective_evidence.created_by_user_id,
        "created_by_tool_call_id": expected_objective_evidence.created_by_tool_call_id,
        "created_at": (
            expected_objective_evidence.created_at.isoformat()
            if expected_objective_evidence.created_at is not None
            else None
        ),
        "authoring_note": expected_objective_evidence.authoring_note,
        **(
            {"warnings": list(expected_objective_evidence.warnings)}
            if expected_objective_evidence.warnings
            else {}
        ),
        **(
            {
                "related_source_refs": [
                    dict(item)
                    for item in expected_objective_evidence.related_source_refs
                ]
            }
            if expected_objective_evidence.related_source_refs
            or expected_objective_evidence.related_source_refs_explicit
            else {}
        ),
    }


def _client(service: _Service | None = None) -> TestClient:
    app = FastAPI()
    app.add_exception_handler(ProjectException, project_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    resolved = service or _Service()
    finding_review_routes.finding_feedback_service = resolved
    finding_review_routes.finding_authoring_service = resolved
    app.dependency_overrides[get_current_user_id] = lambda: "user-researcher"
    app.include_router(router)
    return TestClient(app)


def test_author_finding_api_rejects_legacy_evidence_bindings() -> None:
    response = _client().post(
        "/collections/col-1/objectives/obj-1/findings",
        json={
            "source_analysis_version": 1,
            "supporting_evidence_ids": ["evidence-1"],
            "contradicting_evidence_ids": [],
            "context_evidence_ids": [],
            "condition_boundary_evidence_ids": [],
        },
    )
    assert response.status_code == 200
    assert response.json()["code"] == 200100


def test_author_finding_api_requires_experiment_selection() -> None:
    response = _client().post(
        "/collections/col-1/objectives/obj-1/findings",
        json={
            "source_analysis_version": 1,
            "selection_ids": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == 200100


def test_author_finding_api_preserves_parent_and_limitations() -> None:
    service = _Service()
    response = _client(service).post(
        "/collections/col-1/objectives/obj-1/findings",
        json={
            "source_analysis_version": 1,
            "selection_ids": ["selection-1"],
            "parent_finding_id": "finding-1",
            "limitations": ["Only the tested material is supported."],
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["finding"]["parent_finding_id"] == "finding-1"
    assert response.json()["data"]["finding"]["limitations"] == [
        "Only the tested material is supported."
    ]


def test_author_finding_api_records_abstention_without_placeholder() -> None:
    response = _client().post(
        "/collections/col-1/objectives/obj-1/findings",
        json={
            "source_analysis_version": 1,
            "abstention_reason": "insufficient_evidence",
            "limitations": ["The second paper has no comparable measurement."],
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["finding"] is None
    assert (
        response.json()["data"]["analysis"]["abstention_note"]
        == "The second paper has no comparable measurement."
    )


def test_author_evidence_api_is_removed() -> None:
    response = _client().post(
        "/collections/col-1/objectives/obj-1/evidence",
        json={"source_analysis_version": 1},
    )
    assert response.status_code == 200
    assert response.json()["code"] == 200201


def test_feedback_api_requires_explicit_analysis_version() -> None:
    response = _client().post(
        "/collections/col-1/objectives/obj-1/findings/finding-1/feedback",
        json={
            "analysis_version": 1,
            "review_status": "correct",
            "issue_type": "none",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["analysis_version"] == 1
    assert "claim_id" not in response.json()["data"]


def test_feedback_api_rejects_inconsistent_status_and_issue() -> None:
    client = _client()

    correct_with_issue = client.post(
        "/collections/col-1/objectives/obj-1/findings/finding-1/feedback",
        json={
            "analysis_version": 1,
            "review_status": "correct",
            "issue_type": "evidence_not_grounded",
        },
    )
    partial_without_issue = client.post(
        "/collections/col-1/objectives/obj-1/findings/finding-1/feedback",
        json={
            "analysis_version": 1,
            "review_status": "partial",
            "issue_type": "none",
        },
    )

    assert correct_with_issue.status_code == 200
    assert correct_with_issue.json()["code"] == 200100
    assert partial_without_issue.status_code == 200
    assert partial_without_issue.json()["code"] == 200100


def test_curation_api_uses_finding_evidence_ids() -> None:
    response = _client().put(
        "/collections/col-1/objectives/obj-1/findings/finding-1/curation",
        json={
            "analysis_version": 1,
            "curated_status": "limited",
            "curated_finding": _finding_record("Narrower expert statement."),
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["curated_finding"]["paper_contributions"][0][
        "supporting_evidence_ids"
    ] == ["evidence-1"]


@pytest.mark.parametrize("timestamp, expected", [
    (None, None),
    ("2026-09-01T12:30:00Z", "2026-09-01T12:30:00+00:00"),
    ("2026-09-01T12:30:00+08:00", "2026-09-01T12:30:00+08:00"),
])
def test_curation_timestamp_is_parsed_by_request_and_preserves_json(timestamp, expected):
    payload = {
        "analysis_version": 1,
        "curated_finding": {**_finding_record(), "created_at": timestamp},
    }
    parsed = finding_review_routes.FindingCurationCreateRequest.model_validate(payload)
    assert parsed.curated_finding.created_at == (
        datetime.fromisoformat(expected) if expected is not None else None
    )

    response = _client().put(
        "/collections/col-1/objectives/obj-1/findings/finding-1/curation", json=payload,
    )

    assert response.json()["code"] == 200
    assert response.json()["data"]["curated_finding"]["created_at"] == expected


def test_curation_invalid_timestamp_stops_at_request_boundary_without_writing():
    service = _Service()
    service.record_curation = AsyncMock()

    response = _client(service).put(
        "/collections/col-1/objectives/obj-1/findings/finding-1/curation",
        json={
            "analysis_version": 1,
            "curated_finding": {**_finding_record(), "created_at": "not-a-date"},
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == 200100
    assert response.json()["data"]["errors"][0]["loc"] == [
        "body", "curated_finding", "created_at",
    ]
    service.record_curation.assert_not_awaited()


def test_curation_api_rejects_retired_finding_fields() -> None:
    curated_finding = _finding_record("Narrower expert statement.")
    curated_finding["finding_level"] = "paper"

    response = _client().put(
        "/collections/col-1/objectives/obj-1/findings/finding-1/curation",
        json={
            "analysis_version": 1,
            "curated_status": "limited",
            "curated_finding": curated_finding,
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == 200100


def test_curation_api_rejects_missing_canonical_finding_fields() -> None:
    curated_finding = _finding_record("Narrower expert statement.")
    curated_finding.pop("scientific_context")
    curated_finding["paper_contributions"][0].pop("context_evidence_ids")

    response = _client().put(
        "/collections/col-1/objectives/obj-1/findings/finding-1/curation",
        json={
            "analysis_version": 1,
            "curated_status": "limited",
            "curated_finding": curated_finding,
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == 200100


def test_review_gets_reject_stale_analysis_version() -> None:
    client = _client()

    feedback = client.get(
        "/collections/col-1/objectives/obj-1/findings/finding-1/feedback",
        params={"analysis_version": 2},
    )
    curations = client.get(
        "/collections/col-1/objectives/obj-1/findings/finding-1/curation",
        params={"analysis_version": 2},
    )

    assert feedback.status_code == 200
    assert feedback.json()["code"] == 200204
    assert curations.status_code == 200
    assert curations.json()["code"] == 200204


def test_training_jsonl_contains_messages_and_versioned_metadata() -> None:
    response = _client().get(
        "/collections/col-1/objectives/obj-1/finding-dataset",
        params={"format": "training_jsonl"},
    )

    assert response.status_code == 200
    row = response.json()
    assert "At 500 C" in row["messages"][0]["content"]
    assert row["metadata"]["analysis_version"] == 1


def test_training_jsonl_excludes_non_training_ready_samples() -> None:
    class _RejectedDatasetService(_Service):
        async def export_dataset(self, **kwargs):
            payload = await super().export_dataset(**kwargs)
            payload["items"][0]["label_status"] = "rejected"
            payload["items"][0]["dataset_use_status"] = "rejected"
            return payload

    response = _client(_RejectedDatasetService()).get(
        "/collections/col-1/objectives/obj-1/finding-dataset",
        params={"format": "training_jsonl"},
    )

    assert response.status_code == 200
    assert response.text == ""


def test_llamafactory_alpaca_jsonl_maps_training_messages_and_keeps_lineage() -> None:
    response = _client().get(
        "/collections/col-1/objectives/obj-1/finding-dataset",
        params={"format": "llamafactory_alpaca"},
    )

    assert response.status_code == 200
    row = json.loads(response.text)
    assert row["instruction"].startswith("Evidence: At 500 C")
    assert row["input"] == ""
    assert json.loads(row["output"]) == {}
    assert row["metadata"]["analysis_version"] == 1


def test_llamafactory_alpaca_jsonl_excludes_non_training_ready_samples() -> None:
    class _RejectedDatasetService(_Service):
        async def export_dataset(self, **kwargs):
            payload = await super().export_dataset(**kwargs)
            payload["items"][0]["dataset_use_status"] = "rejected"
            return payload

    response = _client(_RejectedDatasetService()).get(
        "/collections/col-1/objectives/obj-1/finding-dataset",
        params={"format": "llamafactory_alpaca"},
    )

    assert response.status_code == 200
    assert response.text == ""
