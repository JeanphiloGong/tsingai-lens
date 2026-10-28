from __future__ import annotations

import json
from typing import Mapping

from application.core.objectives.analysis.experiment_query_service import (
    objective_evidence_response,
)
from application.evaluation.finding_feedback_service import parse_curated_finding
from controllers.core.finding_review import router
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
)
from domain.core.finding import _certainty as finding_certainty
from domain.core.finding import _choice as finding_choice
from domain.core.finding import _non_negative_int as finding_non_negative_int
from domain.core.finding import _strings as finding_strings
from domain.core.finding import _text as finding_text
from domain.core.finding import (
    datetime,
)
from domain.core.research_objective import (
    ObjectiveEvidence,
    PreparedDocumentInput,
    _text,
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
from domain.core.scientific_fact import _choice as scientific_choice
from domain.core.scientific_fact import _scientific_scalar as scientific_scalar
from domain.core.scientific_fact import _terms as scientific_terms
from domain.core.scientific_fact import _text as scientific_text
from domain.evaluation import (
    FindingCuration,
    FindingFeedback,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from repositories.objective_repository import (
    ExecutionStats,
    ObjectiveAnalysis,
)


class _Service:
    def __init__(self) -> None:
        self.authoring_kwargs = None

    async def create_selection_version(self, **kwargs):
        from application.core.objectives.finding_authoring_service import (
            FindingAuthoringResult,
        )

        self.authoring_kwargs = kwargs
        analysis = ObjectiveAnalysis(
            collection_id=_text(kwargs["collection_id"]) or "",
            objective_id=_text(kwargs["objective_id"]) or "",
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
            created_by_user_id=_text(kwargs["created_by_user_id"]),
            abstention_reason=_text(kwargs.get("abstention_reason")),
            abstention_note=_text(
                "\n".join(kwargs.get("limitations", ()))
                if kwargs.get("abstention_reason")
                else None
            ),
        )
        finding = Finding(
            collection_id=finding_text(_finding_record().get("collection_id", None))
            or "",
            objective_id=finding_text(_finding_record().get("objective_id", None))
            or "",
            analysis_version=2,
            finding_id="finding-manual-1",
            statement=finding_text(_finding_record().get("statement", None)) or "",
            factors=finding_strings(_finding_record().get("factors", None)),
            outcome=finding_text(_finding_record().get("outcome", None)) or "",
            direction=finding_choice(
                _finding_record().get("direction", None),
                SCIENTIFIC_RESULT_DIRECTIONS,
                "unknown",
            ),
            assertion_strength=finding_choice(
                _finding_record().get("assertion_strength", None),
                FINDING_ASSERTION_STRENGTHS,
                "descriptive",
            ),
            attribution_scope=finding_choice(
                _finding_record().get("attribution_scope", None),
                EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
                "descriptive_only",
            ),
            synthesis_status=finding_choice(
                _finding_record().get("synthesis_status", None),
                FINDING_SYNTHESIS_STATUSES,
                "insufficient_confirmation",
            ),
            certainty=finding_certainty(_finding_record().get("certainty", None)),
            display_rank=finding_non_negative_int(
                _finding_record().get("display_rank", None)
            ),
            mechanisms=tuple(
                (
                    FindingMechanismRelation(
                        source_term=finding_text(item.get("source_term")) or "",
                        relation_type=finding_text(item.get("relation_type")) or "",
                        target_term=finding_text(item.get("target_term")) or "",
                        direction=finding_text(item.get("direction")),
                        assertion_strength=finding_choice(
                            item.get("assertion_strength"),
                            FINDING_ASSERTION_STRENGTHS,
                            "descriptive",
                        ),
                        supporting_evidence_ids=finding_strings(
                            item.get("supporting_evidence_ids")
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
                            name=scientific_text(attribute.get("name")) or "",
                            value=(
                                scientific_scalar(attribute.get("value"))
                                if scientific_scalar(attribute.get("value")) is not None
                                else ""
                            ),
                            unit=scientific_text(attribute.get("unit")),
                            context_scope=scientific_choice(
                                attribute.get("context_scope"),
                                SCIENTIFIC_CONTEXT_SCOPES,
                                "unknown",
                            ),
                            applies_to_outcomes=scientific_terms(
                                attribute.get("applies_to_outcomes")
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
                            name=scientific_text(attribute.get("name")) or "",
                            value=(
                                scientific_scalar(attribute.get("value"))
                                if scientific_scalar(attribute.get("value")) is not None
                                else ""
                            ),
                            unit=scientific_text(attribute.get("unit")),
                            context_scope=scientific_choice(
                                attribute.get("context_scope"),
                                SCIENTIFIC_CONTEXT_SCOPES,
                                "unknown",
                            ),
                            applies_to_outcomes=scientific_terms(
                                attribute.get("applies_to_outcomes")
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
                            name=scientific_text(attribute.get("name")) or "",
                            value=(
                                scientific_scalar(attribute.get("value"))
                                if scientific_scalar(attribute.get("value")) is not None
                                else ""
                            ),
                            unit=scientific_text(attribute.get("unit")),
                            context_scope=scientific_choice(
                                attribute.get("context_scope"),
                                SCIENTIFIC_CONTEXT_SCOPES,
                                "unknown",
                            ),
                            applies_to_outcomes=scientific_terms(
                                attribute.get("applies_to_outcomes")
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
                            name=scientific_text(attribute.get("name")) or "",
                            value=(
                                scientific_scalar(attribute.get("value"))
                                if scientific_scalar(attribute.get("value")) is not None
                                else ""
                            ),
                            unit=scientific_text(attribute.get("unit")),
                            context_scope=scientific_choice(
                                attribute.get("context_scope"),
                                SCIENTIFIC_CONTEXT_SCOPES,
                                "unknown",
                            ),
                            applies_to_outcomes=scientific_terms(
                                attribute.get("applies_to_outcomes")
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
            limitations=finding_strings(
                list(kwargs.get("limitations", ())) or ["Supported by one paper."]
            ),
            paper_contributions=tuple(
                (
                    FindingPaperContribution(
                        document_id=finding_text(item.get("document_id")) or "",
                        analysis_status=finding_choice(
                            item.get("analysis_status"),
                            PAPER_CONTRIBUTION_STATUSES,
                            "pending",
                        ),
                        supporting_evidence_ids=finding_strings(
                            item.get("supporting_evidence_ids")
                        ),
                        contradicting_evidence_ids=finding_strings(
                            item.get("contradicting_evidence_ids")
                        ),
                        context_evidence_ids=finding_strings(
                            item.get("context_evidence_ids")
                        ),
                        condition_boundary_evidence_ids=finding_strings(
                            item.get("condition_boundary_evidence_ids")
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
            origin=finding_choice(
                "hybrid" if kwargs.get("parent_finding_id") else "human_authored",
                FINDING_ORIGINS,
                "system_generated",
            ),
            source_analysis_version=1,
            parent_finding_id=finding_text(kwargs.get("parent_finding_id")),
            created_by_user_id=finding_text(kwargs["created_by_user_id"]),
            created_by_tool_call_id=finding_text(
                _finding_record().get("created_by_tool_call_id", None)
            ),
            created_at=datetime.fromisoformat("2026-09-01T00:00:00+00:00"),
            warnings=finding_strings(_finding_record().get("warnings", None)),
            selection_ids=finding_strings(_finding_record().get("selection_ids", None)),
            comparison_group_ids=finding_strings(
                _finding_record().get("comparison_group_ids", None)
            ),
        )
        return FindingAuthoringResult(
            analysis=analysis,
            finding=None if kwargs.get("abstention_reason") else finding,
        )

    async def record_feedback(self, **kwargs):
        return FindingFeedback(**{
            "note": None,
            "reviewer": None,
            "feedback_id": "feedback-1",
            **kwargs,
            "created_at": "2026-07-22T00:00:00+00:00",
        })

    async def list_feedback(self, **kwargs):
        if kwargs["analysis_version"] != 1:
            raise ValueError("review must reference the published analysis version")
        return (
            await self.record_feedback(
                **kwargs,
                review_status="correct",
                issue_type="none",
            ),
        )

    async def record_curation(self, **kwargs):
        return FindingCuration(
            curation_id="curation-1",
            **kwargs,
            updated_at="2026-07-22T00:00:00+00:00",
        )

    async def list_curations(self, **kwargs):
        if kwargs["analysis_version"] != 1:
            raise ValueError("review must reference the published analysis version")
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
        statement=finding_text(statement) or "",
        factors=("temperature",),
        outcome="strength",
        direction="increase",
        assertion_strength="associative",
        attribution_scope=finding_choice(
            "isolated_effect",
            EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
            "descriptive_only",
        ),
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
    return objective_evidence_response(
        ObjectiveEvidence(
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
    )


def _client(service: _Service | None = None) -> TestClient:
    app = FastAPI()
    resolved = service or _Service()
    app.state.finding_feedback_service = resolved
    app.state.finding_authoring_service = resolved

    @app.middleware("http")
    async def authenticated(request, call_next):
        request.state.current_user = {
            "user_id": "user-researcher",
            "email": "researcher@example.com",
        }
        return await call_next(request)

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
    assert response.status_code == 422


def test_author_finding_api_requires_experiment_selection() -> None:
    response = _client().post(
        "/collections/col-1/objectives/obj-1/findings",
        json={
            "source_analysis_version": 1,
            "selection_ids": [],
        },
    )

    assert response.status_code == 422


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
    assert response.status_code == 201
    assert response.json()["finding"]["parent_finding_id"] == "finding-1"
    assert response.json()["finding"]["limitations"] == [
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
    assert response.status_code == 201
    assert response.json()["finding"] is None
    assert (
        response.json()["analysis"]["abstention_note"]
        == "The second paper has no comparable measurement."
    )


def test_author_evidence_api_is_removed() -> None:
    response = _client().post(
        "/collections/col-1/objectives/obj-1/evidence",
        json={"source_analysis_version": 1},
    )
    assert response.status_code == 404


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
    assert response.json()["analysis_version"] == 1
    assert "claim_id" not in response.json()


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

    assert correct_with_issue.status_code == 422
    assert partial_without_issue.status_code == 422


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
    assert response.json()["curated_finding"]["paper_contributions"][0][
        "supporting_evidence_ids"
    ] == ["evidence-1"]


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

    assert response.status_code == 422


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

    assert response.status_code == 422


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

    assert feedback.status_code == 409
    assert curations.status_code == 409


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
