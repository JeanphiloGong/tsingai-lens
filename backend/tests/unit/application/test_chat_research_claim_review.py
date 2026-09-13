from __future__ import annotations

import json

import pytest

from application.chat import CapabilityRegistry, ModelToolCall, ModelTurn, ResearchAgentRunner
from application.chat.context_builder import ChatModelContext
from domain.chat import ChatMessage, ToolRisk
from tests.unit.application.test_research_agent_runner import _Capability, _Model, _context


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _report(category=None, reason="", reference="request", field_path="", candidate_path="/content"):
    return ModelTurn(content=json.dumps({"checks": [
        {
            "category": kind,
            "verdict": "revise" if kind == category else "not_applicable",
            "candidate_path": candidate_path if kind == category else "",
            "reason": reason if kind == category else "No assertion of this kind.",
            "basis": [{"reference": reference, "field_path": field_path}] if kind == category else [],
        }
        for kind in ("paper_scope", "measurement_identity", "gap_scope")
    ]}))


class _ReviewModel:
    def __init__(self, *turns):
        self.turns = iter(turns)
        self.contexts = []

    async def respond(self, *, context, tool_specs, text_delta_callback=None, **kwargs):
        self.contexts.append(context)
        turn = next(self.turns)
        if isinstance(turn, Exception):
            raise turn
        if text_delta_callback is not None:
            text_delta_callback(turn.content)
        return turn


def _messages(request):
    return (ChatMessage.user(message_id="u1", session_id="chat-1", content=request,
                             created_at="2026-09-09T00:00:00Z"),)


@pytest.mark.anyio
async def test_working_notes_still_trigger_review_but_cannot_be_its_evidence():
    from application.chat.agent_runner import _RunProgress
    model = _ReviewModel(ModelTurn(content="The previous comparison needs an exact Source recheck."), _report())
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()))
    context = ChatModelContext(_messages("Correct the old comparison."),
                               working_summary="UNVERIFIED_NOTES: all papers agree, source-A needs re-reading.")
    await runner._respond(context, (), _RunProgress(runner.limits), None)
    assert len(model.contexts) == 2
    review = model.contexts[1].research_review
    assert review is not None
    assert "UNVERIFIED_NOTES" not in json.dumps(review)


@pytest.mark.anyio
async def test_finding_review_can_return_to_source_reading_before_producing_the_draft():
    from application.chat.agent_runner import _RunProgress
    from application.chat.capabilities.document_sources import ReadSourceArguments

    draft = ModelTurn(tool_calls=(ModelToolCall("create_finding_draft", {"statement": "All treatments improve ductility."}),))
    read = ModelTurn(content="Unverified draft preamble", tool_calls=(ModelToolCall("read_source", {
        "document_id": "paper-1", "source_kind": "text_window", "source_ref": "results-3",
    }),))
    model = _ReviewModel(
        _report("paper_scope", "The available result section must resolve the treatment comparison.",
                candidate_path="/tool_calls/0/arguments/statement"), read,
    )
    reader = _Capability("read_source", ToolRisk.READ, ReadSourceArguments)
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((reader,)))
    chunks = []
    result = await runner._review_research_turn(
        draft, ChatModelContext(_messages("Check the treatment conditions and correct this Finding.")),
        (reader.spec,), _RunProgress(runner.limits), chunks.append,
    )
    assert result.tool_calls == read.tool_calls
    assert result.content == ""
    assert reader.executed_arguments == []
    assert chunks == []
    assert len(model.contexts) == 2


@pytest.mark.anyio
async def test_finding_draft_is_checked_before_it_is_recorded_and_finishes_without_rewriting():
    from application.chat.capabilities.finding_authoring import CreateFindingDraftCapability

    arguments = {"draft_id": "correction", "objective_id": "objective-1", "source_analysis_version": 1,
                 "statement": "All three papers report reduced elongation.", "assertion_strength": "descriptive",
                 "supporting_evidence_ids": ["evidence-1"], "limitations": ["The other two papers remain unchecked."]}
    corrected = {**arguments, "statement": "The inspected result reports reduced elongation under its stated treatment."}

    class Model(_Model):
        reviews = 0

        async def respond(self, **kwargs):
            if kwargs["context"].research_review is not None:
                self.reviews += 1
                return (_report("paper_scope", "Only one result supports the treatment comparison.",
                                candidate_path="/tool_calls/0/arguments/statement") if self.reviews == 1 else _report())
            return await super().respond(**kwargs)

    model = Model(ModelTurn(tool_calls=(ModelToolCall("create_finding_draft", arguments),)),
                  ModelTurn(tool_calls=(ModelToolCall("create_finding_draft", corrected),)))
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((CreateFindingDraftCapability(),)))
    result = await runner.run_turn(context=_context(), previous_messages=(),
                                   user_message="Draft a correction of the elongation conclusion. Do not save.")
    assert result.status == "completed"
    assert model.reviews == 2
    drafts = [item for item in result.tool_results if "draft" in item.data]
    assert len(drafts) == 1 and drafts[0].data["draft"]["statement"] == corrected["statement"]
    assert "not been saved or published" in result.messages[-1].content
    assert result.pending_approval is None
    assert not model.turns


@pytest.mark.anyio
async def test_exhausted_reading_is_available_to_claim_review_and_answer_repair():
    from application.chat.agent_runner import _RunProgress

    model = _ReviewModel(
        _report("paper_scope", "Keep the original body check unresolved."),
        ModelTurn(content="The abstract reports improvement; no body section is prepared here."),
        _report(),
    )
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()))
    result = await runner._review_research_turn(
        ModelTurn(content="The paper never reports a decrease."),
        ChatModelContext(_messages("Recheck this Finding and its original conditions.")),
        (), _RunProgress(runner.limits), None, finalizing=True,
    )
    assert "no body section is prepared" in result.content
    assert "reading allowance" in model.contexts[0].research_review["coverage"]
    assert "reading allowance is exhausted" in model.contexts[1].messages[-1].content
    assert "return the necessary read" not in model.contexts[1].messages[-1].content
    assert not result.tool_calls


@pytest.mark.anyio
@pytest.mark.parametrize(("category", "research_request", "bad", "good"), [
    ("paper_scope", "A and B report a decrease; C does not report a worsening condition.",
     "All three report a decrease.", "A and B report a decrease; C is unresolved."),
    ("measurement_identity", "Draft a question about ultimate tensile strength.",
     "Measure yield strength instead.", "Measure ultimate tensile strength."),
    ("gap_scope", "Only the current collection was inspected.",
     "Nobody has ever tested this.", "The inspected collection does not establish this."),
])
async def test_specific_feedback_repairs_claim_before_any_text_is_emitted(category, research_request, bad, good):
    from application.chat.agent_runner import _RunProgress

    model = _ReviewModel(_report(category, "The candidate exceeds its basis."),
                         ModelTurn(content=good), _report())
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()))
    chunks = []
    result = await runner._review_research_turn(
        ModelTurn(content=bad), ChatModelContext(_messages(research_request)), (),
        _RunProgress(runner.limits), chunks.append,
    )
    assert result.content == good
    assert chunks == []
    assert bad in model.contexts[1].messages[-1].content
    assert "exceeds its basis" in model.contexts[1].messages[-1].content
    assert model.contexts[0].research_review is not None
    assert model.contexts[1].research_review is None


@pytest.mark.anyio
async def test_runner_executes_only_corrected_draft_and_never_streams_rejected_content():
    from application.chat.capabilities.objective_proposal import ProposeObjectiveDraftsArguments

    bad_outcome = "ultimate tensile strength or yield strength"
    bad = ModelTurn(content="I will substitute yield strength.", tool_calls=(ModelToolCall(
        "propose_objective_drafts", {"drafts": [{
            "question": "How does energy input affect ultimate tensile strength?",
            "variables": ["energy input"], "outcomes": [bad_outcome],
        }]},
    ),))
    corrected_args = {"drafts": [{
        "question": "How does energy input affect ultimate tensile strength?",
        "variables": ["energy input"], "outcomes": ["ultimate tensile strength"],
    }]}
    request_text = "Draft a question about ultimate tensile strength. Do not save."

    class Model(_Model):
        reviews = 0

        async def respond(self, **kwargs):
            if kwargs["context"].research_review is not None:
                self.reviews += 1
                if self.reviews == 1:
                    return _report("measurement_identity", "Keep the requested tensile measurement.",
                                   candidate_path="/tool_calls/0/arguments/drafts/0/outcomes/0")
                return _report()
            return await super().respond(**kwargs)

    model = Model(bad, ModelTurn(tool_calls=(ModelToolCall("propose_objective_drafts", corrected_args),)),
                  ModelTurn(content="The unsaved question concerns ultimate tensile strength."))
    draft = _Capability("propose_objective_drafts", ToolRisk.DRAFT, ProposeObjectiveDraftsArguments)
    writer = _Capability("create_objective_candidate", ToolRisk.WRITE)
    chunks = []
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((draft, writer))).run_turn(
        context=_context(), previous_messages=(), user_message=request_text, text_delta_callback=chunks.append,
    )
    assert result.status == "completed"
    assert len(draft.executed_arguments) == 1
    assert draft.executed_arguments[0]["drafts"][0]["outcomes"] == ["ultimate tensile strength"]
    assert writer.executed_arguments == []
    assert result.pending_approval is None
    assert "yield strength" not in "".join(chunks)
    assert model.reviews == 3  # rejected draft, corrected draft, final explanation


@pytest.mark.anyio
@pytest.mark.parametrize("token_limit", [100, 200])
async def test_correction_usage_cannot_bypass_budget_before_second_review(token_limit):
    from dataclasses import replace

    from application.chat import AgentRunLimits, ModelUsage
    from application.chat.capabilities.objective_proposal import ProposeObjectiveDraftsArguments

    def proposal(outcome, tokens):
        return ModelTurn(tool_calls=(ModelToolCall("propose_objective_drafts", {"drafts": [{
            "question": "How does energy input affect ultimate tensile strength?",
            "variables": ["energy input"], "outcomes": [outcome],
        }]}),), usage=ModelUsage(tokens, 0, tokens))

    class Model(_Model):
        reviews = 0

        async def respond(self, **kwargs):
            if kwargs["context"].research_review is not None:
                self.reviews += 1
                report = _report("measurement_identity", "Keep ultimate tensile strength.",
                                 candidate_path="/tool_calls/0/arguments/drafts/0/outcomes/0") if self.reviews == 1 else _report()
                tokens = 60 if self.reviews == 1 else 10
                return replace(report, usage=ModelUsage(tokens, 0, tokens))
            return await super().respond(**kwargs)

    model = Model(proposal("yield strength", 30), proposal("ultimate tensile strength", 60),
                  ModelTurn(content="The unsaved draft retains ultimate tensile strength."))
    draft = _Capability("propose_objective_drafts", ToolRisk.DRAFT, ProposeObjectiveDraftsArguments)
    chunks = []
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry((draft,)),
        limits=AgentRunLimits(max_model_tokens=token_limit),
    ).run_turn(context=_context(), previous_messages=(),
               user_message="Draft a question about ultimate tensile strength. Do not save.",
               text_delta_callback=chunks.append)
    assert "yield strength" not in "".join(chunks)
    assert result.pending_approval is None
    if token_limit == 100:
        assert result.status == "failed"
        assert result.error_code == "research_review_unavailable"
        assert draft.executed_arguments == []
        assert model.reviews == 1
    else:
        assert result.status == "completed"
        assert model.reviews == 3
        assert draft.executed_arguments[0]["drafts"][0]["outcomes"] == ["ultimate tensile strength"]


@pytest.mark.anyio
async def test_runner_withholds_repeated_scope_error_and_preserves_successful_read():
    request_text = "Compare these papers."
    bad = "Every paper reports a decrease."
    read = _Capability("read_source", ToolRisk.READ, result_data={
        "document_id": "paper-C", "source_ref": "results", "source_kind": "text_window",
        "source_digest": "current", "content_truncated": False,
        "content": "Elongation improved; no worsening condition was reported.",
    })

    class Model(_Model):
        async def respond(self, **kwargs):
            if kwargs["context"].research_review is not None:
                observation = next(item for item in kwargs["context"].research_review["observations"] if item["kind"] == "read_source")
                return _report("paper_scope", "Paper C does not report the claimed decrease.",
                               reference=observation["reference"], field_path="/content")
            return await super().respond(**kwargs)

    model = Model(ModelTurn(tool_calls=(ModelToolCall("read_source", {}),)),
                  ModelTurn(content=bad), ModelTurn(content=bad))
    chunks = []
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((read,))).run_turn(
        context=_context(), previous_messages=(), user_message=request_text, text_delta_callback=chunks.append,
    )
    assert result.status == "failed"
    assert result.error_code == "research_claim_unresolved"
    assert "paper-C:results" in result.messages[-1].content
    assert bad not in "".join(chunks)
    assert any(item.data.get("content") == read.result_data["content"] for item in result.tool_results)


@pytest.mark.anyio
async def test_review_uses_original_request_instead_of_internal_stage_instruction():
    from application.chat.agent_runner import _RunProgress

    model = _ReviewModel(_report())
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()))
    messages = (*_messages("Keep the tensile-strength question."), ChatMessage.user(
        message_id="stage", session_id="chat-1", content="Internal stage instruction.",
        created_at="2026-09-09T00:00:01Z",
    ))
    await runner._review_research_turn(ModelTurn(content="The question is retained."),
                                       ChatModelContext(messages, active_user_message_id="u1"), (),
                                       _RunProgress(runner.limits), None)
    assert model.contexts[0].research_review["request"] == "Keep the tensile-strength question."
    assert not any("Internal stage instruction." in item["fields"].values() for item in model.contexts[0].research_review["observations"])


@pytest.mark.anyio
async def test_invalid_measurement_is_repaired_in_structured_draft_arguments():
    from application.chat.agent_runner import _RunProgress

    request = "Draft a question about ultimate tensile strength."
    bad = ModelTurn(tool_calls=(ModelToolCall(name="propose_objective_drafts", arguments={
        "drafts": [{"outcomes": ["ultimate tensile strength or yield strength"]}],
    }),))
    good = ModelTurn(tool_calls=(ModelToolCall(name="propose_objective_drafts", arguments={
        "drafts": [{"outcomes": ["ultimate tensile strength"]}],
    }),))
    model = _ReviewModel(_report("measurement_identity", "Two distinct measurements occupy one outcome.",
                                 candidate_path="/tool_calls/0/arguments/drafts/0/outcomes/0"),
                         good, _report())
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()))
    result = await runner._review_research_turn(bad, ChatModelContext(_messages(request)), (),
                                               _RunProgress(runner.limits), None)
    assert result.tool_calls[0].arguments["drafts"][0]["outcomes"] == ["ultimate tensile strength"]


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["repeated", "invented_reference", "invented_field", "invalid_json", "timeout"])
async def test_unresolved_or_unverifiable_review_cannot_release_candidate(failure):
    from application.chat.agent_runner import _RunProgress
    from application.chat.model import ModelResponseError

    request = "Only the current collection was inspected."
    bad = "Nobody has ever tested this."
    issue = _report("gap_scope", "Collection coverage is not global coverage.")
    responses = {
        "repeated": (issue, ModelTurn(content=bad), issue),
        "invented_reference": (_report("gap_scope", "Unsupported.", reference="missing"),),
        "invented_field": (_report("gap_scope", "Unsupported.", field_path="/missing"),),
        "invalid_json": (ModelTurn(content="looks fine"),),
        "timeout": (TimeoutError("private provider detail"),),
    }
    runner = ResearchAgentRunner(model=_ReviewModel(*responses[failure]), capabilities=CapabilityRegistry(()))
    chunks = []
    with pytest.raises(ModelResponseError) as error:
        await runner._review_research_turn(ModelTurn(content=bad), ChatModelContext(_messages(request)), (),
                                           _RunProgress(runner.limits), chunks.append)
    assert error.value.reason in {"research_claim_unresolved", "research_review_unavailable"}
    assert "private provider" not in str(error.value)
    assert chunks == []


@pytest.mark.parametrize("basis_mode", ["independent", "candidate_only", "unknown_path"])
def test_review_candidate_references_require_independent_support(basis_mode):
    from application.chat.model import ResearchClaimReview

    request = "Study ultimate tensile strength."
    candidate = "Study yield strength."
    body = json.loads(_report("measurement_identity", "Preserve the requested measurement.").content)
    check = body["checks"][1]
    check["basis"].append({"reference": "candidate", "field_path": "/content"})
    if basis_mode == "candidate_only":
        check["basis"] = check["basis"][1:]
    if basis_mode == "unknown_path":
        check["candidate_path"] = "/missing"
    if basis_mode == "independent":
        report = ResearchClaimReview.model_validate(body)
        args = (report, {"/content": candidate}, {
            "request": {"kind": "user_request", "data": request},
            "candidate": {"kind": "unexecuted_proposal", "data": {"content": candidate}},
        })
        ResearchAgentRunner._validate_research_review(*args)
    else:
        with pytest.raises(ValueError):
            report = ResearchClaimReview.model_validate(body)
            ResearchAgentRunner._validate_research_review(report, {"/content": candidate}, {
                "request": {"kind": "user_request", "data": request},
            })


def test_review_selects_observed_structured_coverage_without_copying_a_count():
    from application.chat.model import ResearchClaimReview

    report = ResearchClaimReview.model_validate_json(_report(
        "gap_scope", "No cross-paper comparison is established.", reference="quality",
        field_path="/comparable_evidence_count",
    ).content)
    fields = {"/content": "Nobody has ever validated this result."}
    observations = {"quality": {"kind": "assess_objective_quality", "data": {"comparable_evidence_count": 0}}}
    ResearchAgentRunner._validate_research_review(report, fields, observations)
    assert ResearchAgentRunner._review_observations_for_model(observations)[0]["fields"] == {"/comparable_evidence_count": "0"}
    report.checks[2].basis[0].field_path = "/invented_count"
    with pytest.raises(ValueError):
        ResearchAgentRunner._validate_research_review(report, fields, observations)


def test_observation_fields_preserve_empty_null_and_zero_without_inventing_missing_fields():
    fields = ResearchAgentRunner._review_candidate_fields({
        "evidence": [], "value": None, "count": 0, "metadata": {},
    })
    assert fields == {"/evidence": "[]", "/value": "null", "/count": "0", "/metadata": "{}"}
    assert "/not_reported" not in fields


def test_review_can_cite_paper_contributions_as_an_observed_object_list():
    from application.chat.model import ResearchClaimReview

    papers = [{"document_id": "paper-a", "supporting_evidence_ids": ["evidence-a"]},
              {"document_id": "paper-b", "supporting_evidence_ids": []}]
    observations = {"finding-read": {"kind": "inspect_published_finding", "data": {
        "finding": {"paper_contributions": papers},
    }}}
    report = ResearchClaimReview.model_validate_json(_report(
        "paper_scope", "Only one of the two papers has supporting evidence.",
        reference="finding-read", field_path="/finding/paper_contributions",
    ).content)
    rendered = ResearchAgentRunner._review_observations_for_model(observations)
    assert json.loads(rendered[0]["fields"]["/finding/paper_contributions"]) == papers
    ResearchAgentRunner._validate_research_review(report, {"/content": "Both papers agree."}, observations)
    report.checks[0].basis[0].field_path = "/finding/paper_contributions/2"
    with pytest.raises(ValueError):
        ResearchAgentRunner._validate_research_review(report, {"/content": "Both papers agree."}, observations)


@pytest.mark.anyio
async def test_invalid_review_references_are_distinguished_from_provider_failure():
    from application.chat.agent_runner import _RunProgress
    from application.chat.model import ModelResponseError

    invalid = _report("paper_scope", "Check scope.", reference="missing-observation")
    model = _ReviewModel(invalid, invalid)
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()))
    with pytest.raises(ModelResponseError) as error:
        await runner._review_research_turn(
            ModelTurn(content="All papers agree."), ChatModelContext(_messages("Check the papers.")),
            (), _RunProgress(runner.limits), None,
        )
    assert error.value.reason == "research_review_invalid"
    assert len(model.contexts) == 2


def test_review_can_cite_an_observed_evidence_list_or_its_exact_member():
    from application.chat.model import ResearchClaimReview

    observed = {"finding": {"supporting_evidence_ids": ["evidence-1"]}}
    fields = ResearchAgentRunner._review_candidate_fields(observed)
    assert json.loads(fields["/finding/supporting_evidence_ids"]) == ["evidence-1"]
    assert fields["/finding/supporting_evidence_ids/0"] == "evidence-1"
    report = ResearchClaimReview.model_validate_json(_report(
        "paper_scope", "Only one supporting result was returned.", reference="read",
        field_path="/finding/supporting_evidence_ids",
    ).content)
    ResearchAgentRunner._validate_research_review(report, {"/content": "All papers agree."}, {
        "read": {"kind": "inspect_published_finding", "data": observed},
    })


@pytest.mark.anyio
async def test_invalid_review_reference_is_repaired_before_scientific_correction():
    from application.chat.agent_runner import _RunProgress

    model = _ReviewModel(
        _report("gap_scope", "Unsupported.", field_path="/missing"),
        _report("gap_scope", "Limit the claim to the inspected collection."),
        ModelTurn(content="The inspected collection does not establish this result."), _report(),
    )
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()))
    result = await runner._review_research_turn(
        ModelTurn(content="Nobody has ever tested this."),
        ChatModelContext(_messages("Only this collection was inspected.")), (),
        _RunProgress(runner.limits), None,
    )
    assert "inspected collection" in result.content
    assert model.contexts[1].research_review["validation_feedback"]
    assert model.contexts[1].research_review["candidate"] == model.contexts[0].research_review["candidate"]
    assert model.contexts[2].research_review is None


@pytest.mark.anyio
@pytest.mark.parametrize("replacement", [
    ModelTurn(content="I saved the corrected question."),
    ModelTurn(tool_calls=(ModelToolCall("create_objective_candidate", {}),)),
])
async def test_draft_correction_cannot_drop_proposal_or_replace_it_with_a_write(replacement):
    from application.chat.agent_runner import _RunProgress
    from application.chat.model import ModelResponseError

    request = "Draft a question about ultimate tensile strength."
    candidate = ModelTurn(tool_calls=(ModelToolCall("propose_objective_drafts", {
        "drafts": [{"outcomes": ["yield strength"]}],
    }),))
    model = _ReviewModel(_report("measurement_identity", "Preserve the measurement.",
                                 candidate_path="/tool_calls/0/arguments/drafts/0/outcomes/0"), replacement)
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()))
    with pytest.raises(ModelResponseError) as error:
        await runner._review_research_turn(candidate, ChatModelContext(_messages(request)), (),
                                           _RunProgress(runner.limits), None)
    assert error.value.reason == "research_review_unavailable"
