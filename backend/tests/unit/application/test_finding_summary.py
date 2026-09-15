from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.core.objectives.finding_summary import (
    FindingSummaryUnavailable,
    summarize_finding_evidence,
)
from domain.core import Finding


def review_input():
    finding = {
        "collection_id": "col-1",
        "objective_id": "obj-1",
        "analysis_version": 1,
        "finding_id": "finding-1",
        "statement": "Heat treatment can change 316L tensile strength.",
        "factors": ["heat treatment"],
        "outcome": "tensile strength",
        "direction": "increase",
        "assertion_strength": "associative",
        "attribution_scope": "association_only",
        "synthesis_status": "condition_dependent",
        "paper_contributions": [
            {
                "document_id": "paper-a",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["ev-a"],
            },
            {
                "document_id": "paper-b",
                "analysis_status": "analyzed",
                "contradicting_evidence_ids": ["ev-b"],
                "condition_boundary_evidence_ids": ["ev-b"],
            },
        ],
        "limitations": ["The two treatments are not identical."],
    }
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
    return Finding.from_mapping(finding).to_record(), evidence


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
        key: value for key, value in finding.items()
        if key not in {"created_by_user_id", "created_by_tool_call_id", "created_at"}
    }
    assert "supporting_evidence_ids" not in finding
    assert payload["finding"]["paper_contributions"][0]["supporting_evidence_ids"] == ["ev-a"]
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
    with pytest.raises(FindingSummaryUnavailable, match="summary_input_too_large"):
        summarize_finding_evidence(
            finding=finding, evidence=evidence, language="en", response_client=model
        )
    assert not model.calls


def test_missing_linked_evidence_does_not_generate_partial_summary():
    finding, evidence = review_input()
    model = ModelStub()
    with pytest.raises(FindingSummaryUnavailable, match="summary_evidence_incomplete"):
        summarize_finding_evidence(
            finding=finding, evidence=evidence[:1], language="en", response_client=model
        )
    assert not model.calls


def test_provider_failure_is_safe_and_does_not_modify_input():
    finding, evidence = review_input()
    original = json.dumps([finding, evidence])
    with pytest.raises(
        FindingSummaryUnavailable, match="summary_generation_failed"
    ) as error:
        summarize_finding_evidence(
            finding=finding,
            evidence=evidence,
            language="zh",
            response_client=ModelStub(fail=True),
        )
    assert "secret" not in str(error.value)
    assert json.dumps([finding, evidence]) == original


@pytest.mark.anyio
async def test_service_rechecks_published_version_after_generation(monkeypatch):
    from application.core.objectives.analysis_service import ObjectiveAnalysisService

    finding, evidence = review_input()
    service = ObjectiveAnalysisService(
        objective_repository=SimpleNamespace(
            list_evidence=AsyncMock(
                return_value=(
                    tuple(
                        SimpleNamespace(to_record=lambda record=record: record)
                        for record in evidence
                    ),
                    2,
                )
            )
        ),
        evidence_analysis_service=None,
        objective_input_service=None,
        document_profile_service=None,
    )
    service.get_finding = AsyncMock(return_value={"finding": finding})
    service._published_version = AsyncMock(
        side_effect=ValueError("requested analysis version is not published")
    )
    monkeypatch.setattr(
        "application.core.objectives.analysis_service.summarize_finding_evidence",
        lambda **kwargs: {"model": "test"},
    )
    with pytest.raises(ValueError, match="not published"):
        await service.summarize_finding(
            "col-1", "obj-1", "finding-1", analysis_version=1, language="en"
        )
    service._published_version.assert_awaited_once_with("col-1", "obj-1", 1)


@pytest.fixture
def anyio_backend():
    return "asyncio"
