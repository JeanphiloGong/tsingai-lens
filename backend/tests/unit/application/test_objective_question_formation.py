from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.capabilities.objective_candidate import (
    CreateObjectiveCandidateCapability,
    CreateObjectiveCandidateToolRequest,
)
from application.core.objectives import (
    objective_authoring_service,
    objective_candidate_service,
)
from application.core.objectives.llm.structured_response import (
    StructuredOutputSaturatedError,
    StructuredResponseClient,
)
from application.core.structured_extraction.json_support import StructuredOutputError
from domain.core import PaperResearchMap
from domain.core.research_objective import (
    PaperResearchSourceRef,
    build_paper_research_relationship,
    build_paper_research_scope,
)
from pydantic import ValidationError


@pytest.fixture
def reading():
    factors = (("laser power",), ("scan speed",), ("laser power", "scan speed"))
    maps = tuple(
        PaperResearchMap(
            document_id=name,
            doc_role="experimental",
            studies=(
                build_paper_research_scope(
                    document_id=name,
                    design_type="experimental",
                    claim_scope="current_work",
                    experiment_label=None,
                    material_scope=("Ti-6Al-4V",),
                    process_context=("LPBF",),
                    relationships=(
                        build_paper_research_relationship(
                            document_id=name,
                            varied_factors=varied,
                            outcome="porosity",
                            source_refs=(
                                PaperResearchSourceRef(
                                    source_kind="block", source_ref="abstract"
                                ),
                            ),
                            confidence=0.8,
                        ),
                    ),
                    confidence=0.0,
                ),
            ),
            evidence_density="unknown",
            confidence=0.0,
            warnings=(),
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
    client.client.with_options = lambda **kwargs: client.client
    return client, requests


def form(reading, client, **kwargs):
    maps, texts = reading
    return objective_candidate_service.propose_candidate_questions(
        "collection",
        paper_maps=maps,
        source_texts=texts,
        response_client=client,
        **kwargs,
    )


@pytest.mark.parametrize("field", ["variables", "outcomes", "seed_document_ids"])
def test_candidate_request_rejects_blank_scope_or_document_identity(field):
    payload = {
        "question": "How does laser power affect porosity?",
        "variables": ["laser power"],
        "outcomes": ["porosity"],
        field: ["   "],
    }
    with pytest.raises(ValidationError):
        CreateObjectiveCandidateToolRequest.model_validate(payload)


def test_candidate_request_preserves_paper_id_case_through_actual_authoring():
    repository = SimpleNamespace(
        create_authored_candidate=AsyncMock(
            side_effect=lambda objective, **kwargs: objective
        ),
    )
    objective_authoring_service.collection_service = SimpleNamespace(
        get_collection_for_user=AsyncMock(), get_document=AsyncMock()
    )
    objective_authoring_service.ObjectiveRepo = repository
    capability = CreateObjectiveCandidateCapability(
        objective_authoring_service=objective_authoring_service,
    )
    request = CreateObjectiveCandidateToolRequest.model_validate(
        {
            "question": " How does laser power affect porosity? ",
            "material_scope": [" Ti-6Al-4V ", "ti-6al-4v"],
            "variables": ["laser power", "Laser power"],
            "outcomes": ["porosity"],
            "constraints": ["LPBF", "lpbf"],
            "seed_document_ids": ["Paper-A", "paper-a", "Paper-A"],
            "excluded_document_ids": ["Paper-B", "paper-b", "Paper-B"],
        }
    )

    result = asyncio.run(
        capability.execute(
            CapabilityExecutionContext(
                session_id="chat-1",
                user_id="user-1",
                collection_id="col-1",
                tool_call_id="call-1",
            ),
            request,
        )
    )

    assert result.status.value == "succeeded"
    objective = repository.create_authored_candidate.call_args.args[0]
    assert objective.objective_id == "obj_how-does-laser-power-affect-porosity_e63c4889"
    assert objective.material_scope == ("Ti-6Al-4V",)
    assert objective.variables == ("laser power",)
    assert objective.constraints == ("LPBF",)
    assert objective.seed_document_ids == ("Paper-A", "paper-a")
    assert objective.excluded_document_ids == ("Paper-B", "paper-b")
    assert objective.origin == "chat_assisted"
    assert objective.created_by_user_id == "user-1"
    assert objective.created_by_tool_call_id == "call-1"
    assert objective.active_analysis_version is None
    assert objective.confirmation_status == "candidate"


def test_distinct_experiments_form_one_reading_question_without_rewriting_them(
    reading, proposal
):
    before = deepcopy(reading[0])
    client, requests = model_client(proposal)
    result = form(reading, client)
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.objective.seed_document_ids == ("A", "B", "C")
    assert candidate.objective.variables == ("laser power", "scan speed")
    assert candidate.objective.outcomes == ("porosity",)
    assert candidate.objective.confirmation_status == "candidate"
    assert candidate.objective.active_analysis_version is None
    assert reading[0] == before
    for selection, original in zip(candidate.papers, reading[0]):
        assert selection.paper_map is original
        assert selection.source_texts == (
            ("abstract", reading[1][original.document_id, "abstract"]),
        )
        assert selection.limitation
    assert len(requests) == 1
    assert (
        client.consume_last_trace()["prompt_version"]
        == "objective_question_formation.v2"
    )


def test_reading_question_preserves_case_distinct_paper_selections(reading, proposal):
    maps, texts = reading
    renamed = replace(
        maps[1],
        document_id="a",
        studies=tuple(replace(study, document_id="a") for study in maps[1].studies),
    )
    renamed_texts = {
        ("a" if document_id == "B" else document_id, source_ref): text
        for (document_id, source_ref), text in texts.items()
    }
    proposal["proposals"][0]["papers"][1]["document_id"] = "a"
    client, _ = model_client(proposal)

    result = form(((maps[0], renamed, maps[2]), renamed_texts), client)

    candidate = result.candidates[0]
    assert candidate.objective.seed_document_ids == ("A", "a", "C")
    assert tuple(paper.paper_map.document_id for paper in candidate.papers) == (
        "A",
        "a",
        "C",
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
        PaperResearchMap(
            document_id=m.document_id,
            doc_role="uncertain",
            studies=(),
            evidence_density="unknown",
            confidence=0.0,
            warnings=(),
        )
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


def test_prompt_treats_research_interest_as_scope_not_permission_to_change_topic(
    reading,
):
    interest = "How does laser power affect corrosion current density in Ti-6Al-4V?"
    gap = "The supplied passages report porosity, not corrosion current density."
    client, requests = model_client({"proposals": [], "abstention_reason": gap})
    result = form(reading, client, research_interest=interest)
    assert result.candidates == ()
    assert result.abstention_reason == gap
    messages = requests[0]["messages"]
    input_payload, _ = json.JSONDecoder().raw_decode(messages[1]["content"])
    assert input_payload["research_interest"] == interest
    # Guards prompt policy; live replay, not this stub, checks model compliance.
    prompt = " ".join(messages[0]["content"].split())
    assert "Keep the requested material, process and outcome scope" in prompt
    assert "even when the substitution is explicitly disclosed" in prompt
    assert '"proposals": []' in prompt


def test_prompt_scopes_limitations_to_observed_comparisons(reading, proposal):
    client, requests = model_client(proposal)
    form(reading, client)
    prompt = " ".join(requests[0]["messages"][0]["content"].split())
    assert "Scope each limitation to the inspected comparison" in prompt
    assert "missing context is an open check, not a paper-wide verdict" in prompt
    assert "within-series contrasts" in prompt
    assert "C cannot by itself establish an isolated power effect" not in prompt


@pytest.mark.parametrize(
    "payload,finish,exception",
    [
        ("not json", "stop", StructuredOutputError),
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
            PaperResearchMap(
                document_id=str(i),
                doc_role="uncertain",
                studies=(),
                evidence_density="unknown",
                confidence=0.0,
                warnings=(),
            )
            for i in range(13)
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
