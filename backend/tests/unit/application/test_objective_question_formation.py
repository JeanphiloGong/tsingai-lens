from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from application.core.objectives.llm.structured_response import (
    StructuredOutputSaturatedError,
    StructuredResponseClient,
)
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from domain.core import PaperResearchMap


@pytest.fixture
def reading():
    factors = (("laser power",), ("scan speed",), ("laser power", "scan speed"))
    maps = tuple(
        PaperResearchMap.from_mapping(
            {
                "document_id": name,
                "doc_role": "experimental",
                "studies": [
                    {
                        "design_type": "experimental",
                        "claim_scope": "current_work",
                        "material_scope": ["Ti-6Al-4V"],
                        "process_context": ["LPBF"],
                        "relationships": [
                            {
                                "varied_factors": list(varied),
                                "outcome": "porosity",
                                "confidence": 0.8,
                                "source_refs": [
                                    {"source_kind": "block", "source_ref": "abstract"}
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        for name, varied in zip(("A", "B", "C"), factors)
    )
    texts = {
        ("A", "abstract"): "We varied laser power and measured porosity.",
        ("B", "abstract"): "We varied scan speed and measured porosity.",
        (
            "C",
            "abstract",
        ): "We jointly varied laser power and scan speed and measured porosity.",
    }
    return maps, texts


@pytest.fixture
def proposal():
    return {
        "proposals": [
            {
                "question": "How do laser power and scan speed affect porosity?",
                "material_scope": ["Ti-6Al-4V"],
                "variables": ["laser power", "scan speed"],
                "outcome": "porosity",
                "constraints": ["LPBF"],
                "reason": "Different designs inform one reading question.",
                "papers": [
                    {
                        "document_id": name,
                        "source_refs": ["abstract"],
                        "role": "inspect",
                        "reason": "Reports part of the proposed parameter scope.",
                        "limitation": (
                            "Joint factors do not establish an isolated effect."
                            if name == "C"
                            else "Does not independently study every proposed variable."
                        ),
                    }
                    for name in ("A", "B", "C")
                ],
            }
        ],
        "abstention_reason": None,
    }


def model_client(payload, *, finish_reason="stop"):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        if isinstance(payload, Exception):
            raise payload
        return SimpleNamespace(
            model="test-model",
            usage=None,
            choices=[
                SimpleNamespace(
                    finish_reason=finish_reason,
                    message=SimpleNamespace(
                        content=(
                            payload if isinstance(payload, str) else json.dumps(payload)
                        )
                    ),
                )
            ],
        )

    client = StructuredResponseClient(
        client=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
        model="test-model",
    )
    return client, requests


def form(reading, client, **kwargs):
    maps, texts = reading
    return ObjectiveCandidateService().propose_candidate_questions(
        "collection",
        paper_maps=maps,
        source_texts=texts,
        response_client=client,
        **kwargs,
    )


def test_distinct_experiments_form_one_reading_question_without_rewriting_them(
    reading, proposal
):
    before = deepcopy([m.to_record() for m in reading[0]])
    client, requests = model_client(proposal)
    result = form(reading, client)
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.objective.seed_document_ids == ("A", "B", "C")
    assert candidate.objective.variables == ("laser power", "scan speed")
    assert candidate.objective.outcomes == ("porosity",)
    assert candidate.objective.confirmation_status == "candidate"
    assert candidate.objective.active_analysis_version is None
    assert [m.to_record() for m in reading[0]] == before
    for selection, original in zip(candidate.papers, reading[0]):
        assert selection.paper_map is original
        assert selection.source_texts == (
            ("abstract", reading[1][original.document_id, "abstract"]),
        )
        assert selection.limitation
    assert len(requests) == 1
    assert (
        client.consume_last_trace()["prompt_version"]
        == "objective_question_formation.v1"
    )


def test_background_selection_survives_without_becoming_an_experimental_seed(
    reading, proposal
):
    proposal["proposals"][0]["papers"][2]["role"] = "background"
    client, _ = model_client(proposal)
    candidate = form(reading, client).candidates[0]
    assert candidate.objective.seed_document_ids == ("A", "B")
    assert candidate.papers[2].role == "background"


def test_excerpts_can_justify_inspection_without_a_complete_map(reading, proposal):
    maps = tuple(
        PaperResearchMap.from_mapping({"document_id": m.document_id})
        for m in reading[0]
    )
    client, _ = model_client(proposal)
    candidate = form((maps, reading[1]), client).candidates[0]
    assert candidate.objective.seed_document_ids == ("A", "B", "C")
    assert all(not p.paper_map.studies for p in candidate.papers)


@pytest.mark.parametrize(
    "invalid",
    ["document", "source", "duplicate_paper", "duplicate_source", "background_only"],
)
def test_invalid_selection_is_a_traced_failure_not_a_partial_candidate(
    reading, proposal, invalid
):
    papers = proposal["proposals"][0]["papers"]
    if invalid == "document":
        papers[0]["document_id"] = "unseen"
    elif invalid == "source":
        papers[0]["source_refs"] = ["unseen"]
    elif invalid == "duplicate_paper":
        papers.append(deepcopy(papers[0]))
    elif invalid == "duplicate_source":
        papers[0]["source_refs"] *= 2
    else:
        for paper in papers:
            paper["role"] = "background"
    client, requests = model_client(proposal)
    with pytest.raises(ValueError):
        form(reading, client)
    assert len(requests) == 1
    assert client.consume_last_trace()["error_type"]


def test_abstention_requires_an_explanation_and_is_not_technical_failure(reading):
    client, _ = model_client(
        {"proposals": [], "abstention_reason": "No relevant outcome in these passages."}
    )
    result = form(reading, client)
    assert not result.candidates
    assert result.abstention_reason
    client, _ = model_client({"proposals": [], "abstention_reason": None})
    with pytest.raises(ValueError):
        form(reading, client)


@pytest.mark.parametrize(
    "payload,finish,exception",
    [
        ("not json", "stop", RuntimeError),
        ("{}", "length", StructuredOutputSaturatedError),
        (TimeoutError("provider timeout"), "stop", TimeoutError),
    ],
)
def test_technical_failure_does_not_repeat_scientific_work(
    reading, payload, finish, exception
):
    client, requests = model_client(payload, finish_reason=finish)
    with pytest.raises(exception):
        form(reading, client)
    assert len(requests) == 1
    assert client.consume_last_trace()["error_type"]


def test_prompt_budget_rejects_without_silently_dropping_papers(reading, proposal):
    client, requests = model_client(proposal)
    with pytest.raises(ValueError, match="budget"):
        form(reading, client, max_prompt_tokens=1)
    assert requests == []


def test_empty_input_abstains_without_a_model_call(proposal):
    client, requests = model_client(proposal)
    result = form(((), {}), client)
    assert not result.candidates and result.abstention_reason
    assert requests == []


@pytest.mark.parametrize(
    "invalid",
    [
        "duplicate_document",
        "foreign_source",
        "empty_text",
        "missing_excerpts",
        "too_many_papers",
    ],
)
def test_invalid_input_never_reaches_the_model(reading, proposal, invalid):
    maps, texts = reading
    texts = dict(texts)
    if invalid == "duplicate_document":
        maps += (maps[0],)
    elif invalid == "foreign_source":
        texts["unseen", "abstract"] = "Not in the selected reading set."
    elif invalid == "empty_text":
        texts["A", "abstract"] = " "
    elif invalid == "missing_excerpts":
        del texts["A", "abstract"]
    else:
        maps = tuple(
            PaperResearchMap.from_mapping({"document_id": str(i)}) for i in range(13)
        )
        texts = {(m.document_id, "abstract"): "Original abstract." for m in maps}
    client, requests = model_client(proposal)
    with pytest.raises(ValueError):
        form((maps, texts), client)
    assert requests == []


def test_source_identity_is_scoped_to_its_document(reading, proposal):
    maps, texts = reading
    texts = dict(texts)
    texts["C", "c-methods"] = "Details only available in C."
    proposal["proposals"][0]["papers"][0]["source_refs"] = ["c-methods"]
    client, requests = model_client(proposal)
    with pytest.raises(ValueError, match="unavailable paper Source"):
        form((maps, texts), client)
    assert len(requests) == 1


def test_budget_disables_sdk_retries(reading, proposal):
    client, requests = model_client(proposal)
    options = []

    def with_options(**kwargs):
        options.append(kwargs)
        return client.client

    client.client.with_options = with_options
    form(reading, client, request_timeout_s=20)
    assert options == [{"timeout": 20, "max_retries": 0}]
    assert len(requests) == 1
