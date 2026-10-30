from __future__ import annotations

from application.core.objectives.analysis import analysis_record_source

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.core.objectives.finding_summary import (
    FindingSummaryUnavailable,
    summarize_finding_evidence,
)
from domain.core.research_objective import ObjectiveEvidence
from domain.core import Finding
from domain.core.finding import (
    Finding,
    FindingPaperContribution,
)
from domain.core.scientific_fact import (
    ScientificContext,
    ScientificResult,
)
from exceptions import ResourceConflictException


def review_input():
    finding = Finding(
        collection_id="col-1",
        objective_id="obj-1",
        analysis_version=1,
        finding_id="finding-1",
        statement="Heat treatment can change 316L tensile strength.",
        factors=("heat treatment",),
        outcome="tensile strength",
        direction="increase",
        assertion_strength="associative",
        attribution_scope="association_only",
        synthesis_status="condition_dependent",
        certainty=0.0,
        display_rank=0,
        mechanisms=(),
        scientific_context=ScientificContext(),
        limitations=("The two treatments are not identical.",),
        paper_contributions=(
            FindingPaperContribution(
                document_id="paper-a",
                analysis_status="analyzed",
                supporting_evidence_ids=("ev-a",),
            ),
            FindingPaperContribution(
                document_id="paper-b",
                analysis_status="analyzed",
                contradicting_evidence_ids=("ev-b",),
                condition_boundary_evidence_ids=("ev-b",),
            ),
        ),
    )
    evidence = [
        {
            "evidence_id": "ev-a",
            "document_id": "paper-a",
            "source_kind": "table",
            "source_ref": "table-7",
            "page_numbers": [7],
            "source_excerpt": "After annealing, tensile strength was 620 MPa.",
            "reported_result": {"value": 620, "unit": "MPa"},
            "scientific_context": {"material": [{"name": "alloy", "value": "316L"}]},
        },
        {
            "evidence_id": "ev-b",
            "document_id": "paper-b",
            "source_kind": "text_block",
            "source_ref": "results-2",
            "page_numbers": [5],
            "source_excerpt": "A different treatment decreased tensile strength.",
            "comparison": {
                "incomparability_reasons": ["Different treatment conditions"]
            },
        },
    ]
    return {
        "collection_id": finding.collection_id,
        "objective_id": finding.objective_id,
        "analysis_version": finding.analysis_version,
        "finding_id": finding.finding_id,
        "statement": finding.statement,
        "factors": list(finding.factors),
        "outcome": finding.outcome,
        "direction": finding.direction,
        "assertion_strength": finding.assertion_strength,
        "attribution_scope": finding.attribution_scope,
        "synthesis_status": finding.synthesis_status,
        "certainty": finding.certainty,
        "display_rank": finding.display_rank,
        "mechanisms": [
            {
                "source_term": mechanism.source_term,
                "relation_type": mechanism.relation_type,
                "target_term": mechanism.target_term,
                "direction": mechanism.direction,
                "assertion_strength": mechanism.assertion_strength,
                "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
            }
            for mechanism in finding.mechanisms
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
                for attribute in finding.scientific_context.material
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
                for attribute in finding.scientific_context.sample
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
                for attribute in finding.scientific_context.process
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
                for attribute in finding.scientific_context.test
            ],
        },
        "limitations": list(finding.limitations),
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
            for contribution in finding.paper_contributions
        ],
        "origin": finding.origin,
        "source_analysis_version": finding.source_analysis_version,
        "parent_finding_id": finding.parent_finding_id,
        "created_by_user_id": finding.created_by_user_id,
        "created_by_tool_call_id": finding.created_by_tool_call_id,
        "created_at": finding.created_at.isoformat() if finding.created_at else None,
        **(
            {"selection_ids": list(finding.selection_ids)}
            if finding.selection_ids
            else {}
        ),
        **(
            {"comparison_group_ids": list(finding.comparison_group_ids)}
            if finding.comparison_group_ids
            else {}
        ),
        **({"warnings": list(finding.warnings)} if finding.warnings else {}),
    }, evidence


class ModelStub:
    model = "test-model"

    def __init__(self, *, citation="evidence:ev-a", tokens=1000, fail=False):
        self.citation, self.tokens, self.fail = citation, tokens, fail
        self.calls = []

    def estimate_prompt_tokens(self, **kwargs):
        return self.tokens

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("provider secret error")
        return kwargs["response_model"].model_validate(
            {
                "text": "Paper A reports 620 MPa after annealing. Paper B has an opposite trend under different conditions, so this is not a direct contradiction.",
                "citation_ids": [self.citation, "evidence:ev-b", "finding:finding-1"],
            }
        )


def test_summary_returns_one_paragraph_with_exact_citations():
    finding, evidence = review_input()
    model = ModelStub()
    result = summarize_finding_evidence(
        finding=finding, evidence=evidence, language="en", response_client=model
    )
    assert model.calls[0]["response_model"].__name__ == "FindingSummaryModelOutput"
    payload = json.loads(model.calls[0]["user_prompt"])
    assert payload["evidence"] == evidence
    assert payload["finding"] == {
        key: value
        for key, value in finding.items()
        if key not in {"created_by_user_id", "created_by_tool_call_id", "created_at"}
    }
    assert "supporting_evidence_ids" not in finding
    assert payload["finding"]["paper_contributions"][0]["supporting_evidence_ids"] == [
        "ev-a"
    ]
    assert result["text"].startswith("Paper A reports 620 MPa")
    assert "\n" not in result["text"]
    assert not {"basis", "differences", "limitations", "counts"}.intersection(result)
    assert "one paragraph" in model.calls[0]["system_prompt"]
    assert result["model"] == "test-model"
    assert {ref["id"] for ref in result["references"]} == {
        "evidence:ev-a",
        "evidence:ev-b",
        "finding:finding-1",
    }
    assert result["references"][1]["source_ref"] == "table-7"
    assert finding["analysis_version"] == 1


@pytest.mark.parametrize(
    "citation", ["evidence:other-finding", "https://untrusted.example", ""]
)
def test_summary_rejects_invented_or_empty_citations(citation):
    finding, evidence = review_input()
    with pytest.raises(FindingSummaryUnavailable):
        summarize_finding_evidence(
            finding=finding,
            evidence=evidence,
            language="en",
            response_client=ModelStub(citation=citation),
        )


def test_large_input_is_not_silently_truncated():
    finding, evidence = review_input()
    model = ModelStub(tokens=50000)
    with pytest.raises(FindingSummaryUnavailable) as error:
        summarize_finding_evidence(
            finding=finding, evidence=evidence, language="en", response_client=model
        )
    assert error.value.data["code"] == "summary_input_too_large"
    assert not model.calls


def test_missing_linked_evidence_does_not_generate_partial_summary():
    finding, evidence = review_input()
    model = ModelStub()
    with pytest.raises(FindingSummaryUnavailable) as error:
        summarize_finding_evidence(
            finding=finding, evidence=evidence[:1], language="en", response_client=model
        )
    assert error.value.data["code"] == "summary_evidence_incomplete"
    assert not model.calls


def test_provider_failure_is_safe_and_does_not_modify_input():
    finding, evidence = review_input()
    original = json.dumps([finding, evidence])
    with pytest.raises(FindingSummaryUnavailable) as error:
        summarize_finding_evidence(
            finding=finding,
            evidence=evidence,
            language="zh",
            response_client=ModelStub(fail=True),
        )
    assert error.value.data["code"] == "summary_generation_failed"
    assert "secret" not in str(error.value)
    assert json.dumps([finding, evidence]) == original


@pytest.mark.anyio
async def test_service_rechecks_published_version_after_generation(monkeypatch):
    from application.core.objectives import (
        analysis_service as objective_analysis_service,
    )

    finding, evidence = review_input()
    records = tuple(
        ObjectiveEvidence(
            collection_id="col-1", objective_id="obj-1", analysis_version=1,
            evidence_id=item["evidence_id"], document_id=item["document_id"],
            source_kind=item["source_kind"], source_ref=item["source_ref"],
            source_excerpt=item["source_excerpt"], page_numbers=tuple(item["page_numbers"]),
            related_source_refs=(), evidence_role="direct_result",
            selection_status="extracted", selection_reason=None,
            changed_variables=(), comparison=None,
            reported_result=ScientificResult(
                outcome="tensile strength", result_text=item["source_excerpt"],
                value=item.get("reported_result", {}).get("value"),
                unit="MPa", direction="unknown",
            ),
            attribution_scope="descriptive_only", scientific_context=ScientificContext(),
            resolution_status="resolved", failure_reason=None, confidence=0.8,
        )
        for item in evidence
    )
    objective_analysis_service.ObjectiveRepo = SimpleNamespace(
        read_analysis=AsyncMock(return_value=SimpleNamespace(
            status="succeeded", origin="human_authored", scientific_record_source="authored_snapshot",
        )),
        list_evidence=AsyncMock(return_value=(records, 2)),
    )
    analysis_record_source.ObjectiveRepo = objective_analysis_service.ObjectiveRepo
    objective_analysis_service.experiment_analysis_service = None
    objective_analysis_service.objective_input_service = None
    objective_analysis_service.document_profile_service = None
    service = objective_analysis_service
    monkeypatch.setattr(
        service, "get_finding", AsyncMock(return_value={"finding": finding})
    )
    monkeypatch.setattr(
        service,
        "_published_version",
        AsyncMock(
            side_effect=ResourceConflictException(
                "requested analysis version is not published",
                data={"code": "analysis_version_not_published"},
            )
        ),
    )
    monkeypatch.setattr(
        "application.core.objectives.analysis_service.summarize_finding_evidence",
        lambda **kwargs: {"model": "test"},
    )
    with pytest.raises(
        ResourceConflictException, match="published analysis has changed"
    ):
        runtime = service.ObjectiveAnalysisService()
        runtime._summary_client = ModelStub()
        await runtime.summarize_finding(
            "col-1",
            "obj-1",
            "finding-1",
            analysis_version=1,
            language="en",
            user_id="user-1",
        )
    service._published_version.assert_awaited_once_with("col-1", "obj-1", 1)


@pytest.fixture
def anyio_backend():
    return "asyncio"
