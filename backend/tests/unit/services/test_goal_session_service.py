from __future__ import annotations

from openai import APIConnectionError

from application.evaluation.finding_feedback_service import _source_snapshot_validity
from application.goal.session_service import (
    GoalSessionService,
    _StructuredProtocolDraft,
)
from tests.support.collection_service import build_test_collection_service
from tests.support.objective_workspace_repository import (
    InMemoryObjectiveWorkspaceRepository,
)


class _FakeMessage:
    def __init__(self, content: str, parsed=None) -> None:
        self.content = content
        self.parsed = parsed


class _FakeChoice:
    def __init__(self, content: str, parsed=None) -> None:
        self.message = _FakeMessage(content, parsed)


class _FakeCompletion:
    def __init__(self, content: str, parsed=None) -> None:
        self.choices = [_FakeChoice(content, parsed)]


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    def create(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        return _FakeCompletion(self.content)


class _FakeChat:
    def __init__(self, content: str) -> None:
        self.completions = _FakeCompletions(content)


class _FakeLLMClient:
    def __init__(self, content: str) -> None:
        self.chat = _FakeChat(content)


class _FakeParseCompletions:
    def __init__(self, parsed) -> None:
        self.parsed = parsed
        self.calls: list[dict] = []

    def parse(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        return _FakeCompletion("", self.parsed)


class _FakeParseChat:
    def __init__(self, parsed) -> None:
        self.completions = _FakeParseCompletions(parsed)


class _FakeBeta:
    def __init__(self, parsed) -> None:
        self.chat = _FakeParseChat(parsed)


class _StructuredRepairLLMClient:
    def __init__(self, content: str, parsed) -> None:
        self.chat = _FakeChat(content)
        self.beta = _FakeBeta(parsed)


class _FailingCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        raise APIConnectionError(request=None)


class _FailingChat:
    def __init__(self) -> None:
        self.completions = _FailingCompletions()


class _FailingLLMClient:
    def __init__(self) -> None:
        self.chat = _FailingChat()


def _reviewed_finding_item() -> dict:
    return {
        "finding_id": "finding_preheat_ductility",
        "analysis_version": 1,
        "finding_fingerprint": "finding.v2:preheat-ductility",
        "evidence_fingerprint": "evidence.v2:preheat-ductility",
        "label_status": "gold",
        "dataset_use_status": "training_ready",
        "training_target": {
            "collection_id": "collection-from-test",
            "objective_id": "obj_preheat",
            "analysis_version": 1,
            "finding_id": "finding_preheat_ductility",
            "statement": (
                "150 C preheating improves LPBF 316L ductility in the reported "
                "single-paper comparison."
            ),
            "factors": ["build platform preheating temperature"],
            "outcome": "ductility",
            "direction": "increase",
            "assertion_strength": "causal",
            "attribution_scope": "isolated_effect",
            "synthesis_status": "insufficient_confirmation",
            "certainty": 0.5,
            "display_rank": 0,
            "mechanisms": [],
            "scientific_context": {
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [],
                "process": [],
                "test": [],
            },
            "limitations": ["Only one paper directly supports this result."],
            "paper_contributions": [
                {
                    "document_id": "paper-preheat",
                    "analysis_status": "analyzed",
                    "supporting_evidence_ids": ["ev_preheat_ductility"],
                    "contradicting_evidence_ids": [],
                    "context_evidence_ids": [],
                    "condition_boundary_evidence_ids": [],
                }
            ],
        },
        "evidence": [
            {
                "evidence_id": "ev_preheat_ductility",
                "document_id": "paper-preheat",
                "page_numbers": [7],
                "source_kind": "text_window",
                "source_ref": "Results",
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "build platform preheating temperature",
                        "baseline_value": 25,
                        "target_value": 150,
                        "unit": "C",
                    }
                ],
                "comparison": {
                    "baseline_label": "25 C",
                    "target_label": "150 C",
                    "axis_names": ["build platform preheating temperature"],
                    "comparable": True,
                    "incomparability_reasons": [],
                },
                "reported_result": {
                    "outcome": "ductility",
                    "value": 14,
                    "unit": "%",
                    "direction": "increase",
                    "result_text": "Ductility improved by about 14%.",
                },
                "attribution_scope": "isolated_effect",
                "scientific_context": {
                    "material": [{"name": "alloy", "value": "316L"}],
                    "sample": [],
                    "process": [],
                    "test": [],
                },
                "source_excerpt": (
                    "The sample preheated at 150 C shows a 14% improvement in "
                    "ductility."
                ),
            }
        ],
    }


class _TrainingReadyFindingFeedbackService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.items = [
            _reviewed_finding_item(),
            {
                "finding_id": "finding_review_candidate",
                "label_status": "silver",
                "dataset_use_status": "review_candidate",
            },
        ]

    def export_dataset(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(dict(kwargs))
        return {
            "collection_id": kwargs["collection_id"],
            "objective_id": kwargs["objective_id"],
            "dataset_use_status_filter": kwargs["dataset_use_status"],
            "item_count": 2,
            "items": self.items,
            "warnings": [],
        }

    def source_snapshot_validity(self, **kwargs):  # noqa: ANN003, ANN201
        return _source_snapshot_validity(kwargs["source_findings"], self.items)


class _EmptyTrainingReadyFindingFeedbackService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def export_dataset(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(dict(kwargs))
        return {
            "collection_id": kwargs["collection_id"],
            "objective_id": kwargs["objective_id"],
            "dataset_use_status_filter": kwargs["dataset_use_status"],
            "item_count": 0,
            "items": [],
            "warnings": [],
        }


class _MalformedTrainingReadyFindingFeedbackService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def export_dataset(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(dict(kwargs))
        return {
            "collection_id": kwargs["collection_id"],
            "objective_id": kwargs["objective_id"],
            "dataset_use_status_filter": kwargs["dataset_use_status"],
            "item_count": 2,
            "items": [
                {
                    "finding_id": "finding_missing_fingerprints",
                    "label_status": "gold",
                    "dataset_use_status": "training_ready",
                    "training_target": _reviewed_finding_item()["training_target"],
                    "evidence": _reviewed_finding_item()["evidence"],
                },
                {
                    **_reviewed_finding_item(),
                    "finding_id": "finding_missing_source_excerpt",
                    "label_status": "gold",
                    "dataset_use_status": "training_ready",
                    "evidence": [
                        {
                            **_reviewed_finding_item()["evidence"][0],
                            "source_excerpt": "",
                        }
                    ],
                },
            ],
            "warnings": [],
        }


def _service(
    tmp_path,
    content: str = "draft answer",
    finding_feedback_service=None,
) -> tuple[GoalSessionService, CollectionService]:
    collection_service = build_test_collection_service(tmp_path / "collections")
    service = GoalSessionService(
        collection_service=collection_service,
        finding_feedback_service=(
            finding_feedback_service or _EmptyTrainingReadyFindingFeedbackService()
        ),
        goal_session_repository=InMemoryObjectiveWorkspaceRepository(),
        llm_client=_FakeLLMClient(content),
        model="fake-model",
    )
    return service, collection_service


def _service_with_llm_client(
    tmp_path,
    llm_client,
    finding_feedback_service=None,
) -> tuple[GoalSessionService, CollectionService]:
    collection_service = build_test_collection_service(tmp_path / "collections")
    service = GoalSessionService(
        collection_service=collection_service,
        finding_feedback_service=(
            finding_feedback_service or _EmptyTrainingReadyFindingFeedbackService()
        ),
        goal_session_repository=InMemoryObjectiveWorkspaceRepository(),
        llm_client=llm_client,
        model="fake-model",
    )
    return service, collection_service


def test_goal_session_persists_explicit_context(tmp_path):
    service, collection_service = _service(tmp_path)
    collection = collection_service.create_collection("Session Collection")

    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_material_id="mat-316l",
        focused_objective_id="obj_lpbf_strength",
        goal_text="Compare strength and ductility.",
        answer_mode="hybrid",
    )
    loaded = service.get_session(session["session_id"])

    assert loaded["collection_id"] == collection["collection_id"]
    assert loaded["focused_material_id"] == "mat-316l"
    assert loaded["focused_objective_id"] == "obj_lpbf_strength"
    assert loaded["goal_text"] == "Compare strength and ductility."
    assert loaded["answer_mode"] == "hybrid"


def test_goal_session_can_start_with_collection_only(tmp_path):
    service, collection_service = _service(tmp_path, content="General background.")
    collection = collection_service.create_collection("Minimal Session Collection")

    session = service.create_session(collection_id=collection["collection_id"])
    response = service.post_message(
        session["session_id"],
        message="What can I ask about this collection?",
    )
    loaded = service.get_session(session["session_id"])

    assert loaded["collection_id"] == collection["collection_id"]
    assert loaded["goal_text"] is None
    assert loaded["goal_brief_json"] == {}
    assert loaded["answer_mode"] == "hybrid"
    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "focused_objective_required" in response["warnings"]
    assert service.llm_client.chat.completions.calls == []


def test_goal_session_update_can_clear_focus(tmp_path):
    service, collection_service = _service(tmp_path)
    collection = collection_service.create_collection("Session Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_material_id="mat-316l",
        focused_paper_id="paper-a",
        focused_objective_id="obj_lpbf_strength",
    )

    updated = service.update_session(
        session["session_id"],
        focused_material_id=None,
        focused_paper_id=None,
        focused_objective_id=None,
    )

    assert updated["focused_material_id"] is None
    assert updated["focused_paper_id"] is None
    assert updated["focused_objective_id"] is None


def test_grounded_message_returns_limited_when_collection_has_no_context(tmp_path):
    service, collection_service = _service(tmp_path)
    collection = collection_service.create_collection("Empty Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_material_id=None,
        answer_mode="grounded",
    )

    response = service.post_message(
        session["session_id"],
        message="What trend is supported?",
    )

    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "no_collection_evidence_found" in response["warnings"]
    assert service.llm_client.chat.completions.calls == []


def test_hybrid_message_requires_a_reviewed_objective_finding(tmp_path):
    service, collection_service = _service(tmp_path, content="General LPBF background.")
    collection = collection_service.create_collection("Empty Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="What does LPBF energy density usually affect?",
    )
    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert "focused_objective_required" in response["warnings"]
    assert service.llm_client.chat.completions.calls == []


def test_material_page_context_does_not_replace_reviewed_objective_findings(tmp_path):
    service, collection_service = _service(
        tmp_path, content="S001 hardness is supported by [Source 1]."
    )
    collection = collection_service.create_collection("Material Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="What evidence supports hardness?",
        page_context={"material_id": "mat-316l"},
    )
    loaded = service.get_session(session["session_id"])

    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "focused_objective_required" in response["warnings"]
    assert loaded["focused_material_id"] == "mat-316l"
    assert loaded["last_evidence_ids"] == []
    assert service.llm_client.chat.completions.calls == []


def test_unreviewed_objective_context_is_not_used_as_grounded_evidence(tmp_path):
    service, collection_service = _service(
        tmp_path,
        content="The objective is supported by [Source 1].",
    )
    collection = collection_service.create_collection("Objective Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_lpbf_strength",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Summarize the logic chain for this objective.",
        page_context={"objective_id": "obj_lpbf_strength"},
    )
    loaded = service.get_session(session["session_id"])

    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "reviewed_findings_empty" in response["warnings"]
    assert loaded["focused_objective_id"] == "obj_lpbf_strength"
    assert loaded["last_paper_ids"] == []
    assert service.llm_client.chat.completions.calls == []


def test_goal_chat_downgrades_uncited_grounded_answer(tmp_path):
    service, collection_service = _service(
        tmp_path,
        content="The objective is supported by the collection evidence.",
        finding_feedback_service=_TrainingReadyFindingFeedbackService(),
    )
    collection = collection_service.create_collection("Uncited Objective Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Summarize the logic chain for this objective.",
        page_context={"objective_id": "obj_preheat"},
    )
    loaded = service.get_session(session["session_id"])

    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "goal_copilot_missing_source_citation" in response["warnings"]
    assert "do not treat it as a traceable collection conclusion" in response["answer"]
    assert "The objective is supported by the collection evidence." not in response["answer"]
    assert loaded["last_evidence_ids"] == []


def test_goal_chat_uses_reviewed_findings_for_protocol_context(tmp_path):
    feedback_service = _TrainingReadyFindingFeedbackService()
    service, collection_service = _service(
        tmp_path,
        content=(
            "<think>Use hidden reasoning and unreviewed facts.</think>\n"
            "Use the accepted preheating finding for the next protocol [Source 1]."
        ),
        finding_feedback_service=feedback_service,
    )
    collection = collection_service.create_collection("Goal Finding Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Design the next experiment from reviewed findings.",
        page_context={"objective_id": "obj_preheat"},
    )
    loaded = service.get_session(session["session_id"])

    assert response["source_mode"] == "collection_grounded"
    assert response["review_gate"] == "reviewed_findings"
    assert response["source_validity"] == "current"
    assert response["source_validity_reasons"] == []
    assert "<think>" not in response["answer"]
    assert response["used_evidence_ids"] == ["ev_preheat_ductility"]
    assert response["source_finding_refs"] == [
        {
            "objective_id": "obj_preheat",
            "finding_id": "finding_preheat_ductility",
            "analysis_version": 1,
            "finding_fingerprint": "finding.v2:preheat-ductility",
            "evidence_fingerprint": "evidence.v2:preheat-ductility",
            "evidence_ids": ["ev_preheat_ductility"],
        }
    ]
    assert response["source_links"] == [
        {
            "kind": "evidence",
            "label": "Source 1",
            "href": (
                f"/collections/{collection['collection_id']}/documents/"
                "paper-preheat?evidence_id=ev_preheat_ductility"
            ),
        }
    ]
    assert loaded["focused_objective_id"] == "obj_preheat"
    assert service.list_messages(session["session_id"])["items"][-1]["review_gate"] == (
        "reviewed_findings"
    )
    assert (
        service.list_messages(session["session_id"])["items"][-1]["source_finding_refs"]
        == response["source_finding_refs"]
    )
    assert feedback_service.calls == [
        {
            "collection_id": collection["collection_id"],
            "objective_id": "obj_preheat",
            "dataset_use_status": "training_ready",
        }
    ]
    prompt_messages = service.llm_client.chat.completions.calls[0]["messages"]
    assert "expert-reviewed findings first" in prompt_messages[0]["content"]
    assert "Protocol draft requirements" in prompt_messages[0]["content"]
    assert "Hypothesis" in prompt_messages[0]["content"]
    assert "Variable matrix" in prompt_messages[0]["content"]
    assert "Measurements" in prompt_messages[0]["content"]
    assert "Controls" in prompt_messages[0]["content"]
    assert "Risks or limits" in prompt_messages[0]["content"]
    assert (
        "Do not collapse protocol answers into one paragraph"
        in prompt_messages[0]["content"]
    )
    assert "operational manipulation" in prompt_messages[0]["content"]
    assert "derived or composite variable" in prompt_messages[0]["content"]
    assert "volumetric energy density" in prompt_messages[0]["content"]
    assert "every constituent parameter is fixed" in prompt_messages[0]["content"]
    assert "confounded comparison" in prompt_messages[0]["content"]
    assert "proposed design choice" in prompt_messages[0]["content"]
    assert "Source-backed:" in prompt_messages[0]["content"]
    assert "Proposed design choice:" in prompt_messages[0]["content"]
    assert "Do not leave these bullets unlabeled" in prompt_messages[0]["content"]
    assert "numeric levels, standards, sample sizes, or named methods" in (
        prompt_messages[0]["content"]
    )
    assert "Bad: change VED while laser power" in prompt_messages[0]["content"]
    assert "Good: Proposed design choice: vary laser power" in (
        prompt_messages[0]["content"]
    )
    assert "A Source-backed line must include" in prompt_messages[0]["content"]
    assert "on that same line" in prompt_messages[0]["content"]
    assert "Do not use Source-backed as a group heading" in (
        prompt_messages[0]["content"]
    )
    assert "The Hypothesis must cite" in prompt_messages[0]["content"]
    assert "Only call an operational setting Source-backed" in (
        prompt_messages[0]["content"]
    )
    assert "general domain knowledge or this boundary example" in (
        prompt_messages[0]["content"]
    )
    prompt = prompt_messages[1]["content"]
    assert "reviewed_findings" in prompt
    assert "150 C preheating improves LPBF 316L ductility" in prompt
    assert "The sample preheated at 150 C shows a 14% improvement" in prompt
    assert "insufficient_confirmation" in prompt
    assert "Only one paper directly supports this result" in prompt
    assert "ev_unreviewed_fact" not in prompt
    assert "paper-unreviewed" not in prompt
    assert "ev_preheat_ductility" not in prompt
    assert "finding_review_candidate" not in prompt


def test_goal_chat_strips_incomplete_thinking_markup(tmp_path):
    service, _ = _service(tmp_path)

    assert service._strip_thinking_blocks("</think>\nVisible answer.") == "Visible answer."
    assert (
        service._strip_thinking_blocks(
            "Hidden reasoning that must not leak.</think>\nVisible answer."
        )
        == "Visible answer."
    )
    assert (
        service._strip_thinking_blocks("Visible answer.\n<think>Hidden reasoning")
        == "Visible answer."
    )


def test_goal_chat_marks_saved_finding_snapshot_stale(tmp_path):
    feedback_service = _TrainingReadyFindingFeedbackService()
    service, collection_service = _service(
        tmp_path,
        content="Use the accepted finding [Source 1].",
        finding_feedback_service=feedback_service,
    )
    collection = collection_service.create_collection("Stale Goal Finding Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_preheat",
        answer_mode="hybrid",
    )
    response = service.post_message(
        session["session_id"],
        message="Summarize the reviewed finding.",
        page_context={"objective_id": "obj_preheat"},
    )
    assert response["source_validity"] == "current"

    feedback_service.items[0] = {
        **feedback_service.items[0],
        "finding_fingerprint": "finding.v2:changed",
    }
    saved = service.list_messages(session["session_id"])["items"][-1]

    assert saved["source_validity"] == "stale"
    assert saved["source_validity_reasons"] == ["source_finding_changed"]
    assert "source_finding_snapshot_stale" in saved["warnings"]


def test_goal_chat_repairs_protocol_contract_before_returning_grounded_answer(tmp_path):
    invalid_draft = """Hypothesis
Preheating improves ductility [Source 1].
Variable matrix
- Source-backed: Compare ambient and preheated builds [Source 1].
Measurements
- Source-backed: Ductility [Source 1].
Controls
- Proposed design choice: Hold scan parameters constant.
Risks or limits
- Design risk: Scan-parameter drift can affect the result.
"""
    repaired_protocol = {
        "proposed_variable_manipulations": [
            "Proposed design choice: Compare ambient and preheated builds while "
            "the expert selects the levels."
        ],
        "proposed_measurements": [
            "The expert selects a validated defect-characterization method."
        ],
        "proposed_controls": ["Hold scan parameters constant."],
        "design_risks": ["Scan-parameter drift can confound preheating effects."],
    }
    llm_client = _StructuredRepairLLMClient(invalid_draft, repaired_protocol)
    service, collection_service = _service_with_llm_client(
        tmp_path,
        llm_client,
        finding_feedback_service=(_TrainingReadyFindingFeedbackService()),
    )
    collection = collection_service.create_collection("Repair Protocol Contract")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Design the next experiment from reviewed findings.",
        page_context={"objective_id": "obj_preheat"},
    )

    assert response["source_mode"] == "collection_grounded"
    assert "150 C preheating improves LPBF 316L ductility" in response["answer"]
    assert (
        "- Source-backed: Observed relation: build platform preheating temperature "
        "-> ductility; direction: increase; attribution: isolated_effect. [Source 1]"
    ) in response["answer"]
    assert "- Source-backed: Reported outcome: ductility. [Source 1]" in (
        response["answer"]
    )
    assert "- Proposed design choice: Compare ambient and preheated builds" in (
        response["answer"]
    )
    assert "\nSource-backed:\n" not in response["answer"]
    assert response["review_gate"] == "reviewed_findings"
    assert response["warnings"] == []
    assert len(llm_client.chat.completions.calls) == 1
    assert len(llm_client.beta.chat.completions.calls) == 1
    parse_call = llm_client.beta.chat.completions.calls[0]
    assert parse_call["response_format"].__name__ == "_StructuredProtocolDraft"
    assert set(parse_call["response_format"].model_fields) == {
        "proposed_variable_manipulations",
        "design_risks",
    }
    repair_prompt = parse_call["messages"][1]["content"]
    assert "Repair the protocol as structured data" in repair_prompt
    assert "Normalize the protocol into the required evidence/design fields" in (
        repair_prompt
    )
    assert invalid_draft.strip() in repair_prompt


def test_protocol_renderer_replaces_ved_isolation_claim_with_mediated_boundary(
    tmp_path,
):
    service, _ = _service(tmp_path, content="unused")
    draft = _StructuredProtocolDraft(
        proposed_variable_manipulations=[
            "Vary laser power to create VED levels while holding scan speed, "
            "hatch spacing, and layer thickness fixed."
        ],
        design_risks=[
            "This protocol isolates VED by fixing its constituent parameters.",
            "Additional experiments may confirm VED-only effects.",
        ],
    )
    finding = {
        "statement": (
            "Coupled PBF-LB parameter sets grouped by VED were associated with "
            "fatigue strength."
        ),
        "factors": ["coupled PBF-LB parameter sets grouped by VED"],
        "outcome": "fatigue strength",
        "direction": "associated",
        "attribution_scope": "association_only",
        "synthesis_status": "insufficient_confirmation",
        "limitations": ["Treat as single-paper evidence."],
        "evidence": [{"evidence_source": "Source 1"}],
    }

    answer = service._render_protocol_draft(
        draft,
        allowed_source_labels={"Source 1"},
        reviewed_findings=[finding],
    )

    assert "isolates VED by fixing" not in answer
    assert "confirm VED-only effects" not in answer
    assert (
        "Changing one or more VED constituents estimates the selected "
        "constituent-mediated path; it does not isolate a universal VED-only effect."
    ) in answer
    assert service._protocol_contract_is_valid(answer) is True


def test_protocol_renderer_drops_unattributed_source_details_from_proposals(
    tmp_path,
):
    service, _ = _service(tmp_path, content="unused")
    draft = _StructuredProtocolDraft.model_validate(
        {
            "proposed_variable_manipulations": [
                "Vary laser power to create VED levels while holding scan speed, "
                "hatch spacing, and layer thickness fixed."
            ],
            "proposed_measurements": [
                "Measure maximum defect length by LCSM.",
                "Measure fatigue strength at 10⁴ cycles.",
            ],
            "proposed_controls": ["Use 316L on the same PBF-LB machine."],
            "design_risks": ["Review uncontrolled process interactions."],
        }
    )
    finding = {
        "statement": "Coupled VED parameter sets were associated with fatigue strength.",
        "factors": ["coupled parameter sets grouped by VED"],
        "outcome": "fatigue strength",
        "direction": "associated",
        "attribution_scope": "association_only",
        "synthesis_status": "insufficient_confirmation",
        "limitations": ["Treat as single-paper evidence."],
        "evidence": [{"evidence_source": "Source 1"}],
    }

    answer = service._render_protocol_draft(
        draft,
        allowed_source_labels={"Source 1"},
        reviewed_findings=[finding],
    )

    assert "Proposed design choice: Measure maximum defect length by LCSM" not in answer
    assert (
        "Proposed design choice: Measure fatigue strength at 10⁴ cycles" not in answer
    )
    assert "Proposed design choice: Use 316L on the same PBF-LB machine" not in answer
    assert (
        "Proposed design choice: The expert selects validated methods for the "
        "source-backed outcomes."
    ) in answer
    assert (
        "Proposed design choice: The expert defines controls for non-manipulated "
        "material, process, and test variables."
    ) in answer
    assert service._protocol_contract_is_valid(answer) is True


def test_protocol_renderer_does_not_delegate_measurements_or_controls_to_model(
    tmp_path,
):
    service, _ = _service(tmp_path, content="unused")
    draft = _StructuredProtocolDraft.model_validate(
        {
            "proposed_variable_manipulations": [
                "Vary laser power to create VED levels while holding scan speed, "
                "hatch spacing, and layer thickness fixed."
            ],
            "proposed_measurements": ["Measure any convenient material response."],
            "proposed_controls": [
                "Keep nozzle height, lens calibration, and chamber pressure constant."
            ],
            "design_risks": ["Review uncontrolled process interactions."],
        }
    )
    finding = {
        "statement": "Coupled VED parameter sets were associated with fatigue strength.",
        "factors": ["coupled parameter sets grouped by VED"],
        "outcome": "fatigue strength",
        "direction": "associated",
        "attribution_scope": "association_only",
        "synthesis_status": "insufficient_confirmation",
        "limitations": ["Treat as single-paper evidence."],
        "evidence": [{"evidence_source": "Source 1"}],
    }

    answer = service._render_protocol_draft(
        draft,
        allowed_source_labels={"Source 1"},
        reviewed_findings=[finding],
    )

    assert "any convenient material response" not in answer
    assert "nozzle height" not in answer
    assert "lens calibration" not in answer
    assert "chamber pressure" not in answer
    assert (
        "Proposed design choice: The expert selects validated methods for the "
        "source-backed outcomes."
    ) in answer
    assert (
        "Proposed design choice: Keep the VED constituents identified as fixed "
        "in the Variable matrix unchanged across conditions."
    ) in answer
    assert service._protocol_contract_is_valid(answer) is True


def test_protocol_renderer_falls_back_from_unsafe_ved_variable_choice(tmp_path):
    service, _ = _service(tmp_path, content="unused")
    draft = _StructuredProtocolDraft(
        proposed_variable_manipulations=[
            "Vary laser power at 190 W for 316L PBF-LB while holding scan speed, "
            "hatch spacing, and layer thickness fixed."
        ],
        design_risks=["Review interactions among process parameters."],
    )
    finding = {
        "statement": "Coupled VED parameter sets were associated with fatigue strength.",
        "factors": ["coupled parameter sets grouped by VED"],
        "outcome": "fatigue strength",
        "direction": "associated",
        "attribution_scope": "association_only",
        "synthesis_status": "insufficient_confirmation",
        "limitations": ["Treat as single-paper evidence."],
        "evidence": [{"evidence_source": "Source 1"}],
    }

    answer = service._render_protocol_draft(
        draft,
        allowed_source_labels={"Source 1"},
        reviewed_findings=[finding],
    )

    assert "190 W" not in answer
    assert "Proposed design choice: Vary laser power to create VED levels" in answer
    assert "holding scan speed, hatch spacing, and layer thickness fixed" in answer
    assert "the expert selects the levels" in answer
    assert service._protocol_contract_is_valid(answer) is True


def test_goal_chat_limits_protocol_when_repair_still_violates_contract(tmp_path):
    invalid_draft = """Hypothesis
VED improves fatigue strength [Source 1].
Variable matrix
Source-backed:
- Vary laser power while other parameters are fixed.
Measurements
- ASTM E466 fatigue testing
Controls
- Scan speed
Risks or limits
- Confounding
"""
    invalid_protocol = {
        "proposed_variable_manipulations": ["Vary laser power by 10 percent."],
        "proposed_measurements": [
            "Select a fatigue test method. Source-backed: use LCSM."
        ],
        "proposed_controls": ["Hold scan speed constant."],
        "design_risks": ["Constituent-parameter drift can confound VED."],
    }
    llm_client = _StructuredRepairLLMClient(invalid_draft, invalid_protocol)
    service, collection_service = _service_with_llm_client(
        tmp_path,
        llm_client,
        finding_feedback_service=(_TrainingReadyFindingFeedbackService()),
    )
    collection = collection_service.create_collection("Reject Invalid Protocol")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Design the next experiment from reviewed findings.",
        page_context={"objective_id": "obj_preheat"},
    )

    assert response["source_mode"] == "collection_limited"
    assert response["review_gate"] is None
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "goal_copilot_protocol_contract_invalid" in response["warnings"]
    assert "could not verify the protocol draft contract" in response["answer"]
    assert len(llm_client.chat.completions.calls) == 1
    assert len(llm_client.beta.chat.completions.calls) == 1


def test_goal_chat_limits_ved_protocol_without_an_operational_constituent(
    tmp_path,
):
    draft = """Hypothesis
VED improves fatigue strength [Source 1].
Variable matrix
- Proposed design choice: Compare low and moderate VED levels.
Measurements
- Proposed design choice: Measure fatigue strength.
Controls
- Proposed design choice: Hold laser power, scan speed, hatch spacing, and layer thickness constant.
Risks or limits
- Design risk: Constituent-parameter drift can confound VED.
"""
    repaired_protocol = {
        "proposed_variable_manipulations": ["Compare low and moderate VED levels."],
        "proposed_measurements": ["Measure fatigue strength."],
        "proposed_controls": [
            "Hold laser power, scan speed, hatch spacing, and layer thickness constant."
        ],
        "design_risks": ["Constituent-parameter drift can confound VED."],
    }
    llm_client = _StructuredRepairLLMClient(draft, repaired_protocol)
    service, collection_service = _service_with_llm_client(
        tmp_path,
        llm_client,
        finding_feedback_service=(_TrainingReadyFindingFeedbackService()),
    )
    collection = collection_service.create_collection("Reject Impossible VED Protocol")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Design the next experiment from reviewed findings.",
        page_context={"objective_id": "obj_preheat"},
    )

    assert response["source_mode"] == "collection_limited"
    assert response["review_gate"] is None
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "goal_copilot_protocol_contract_invalid" in response["warnings"]
    assert "could not verify the protocol draft contract" in response["answer"]


def test_goal_chat_suppresses_backbone_readiness_warnings_when_reviewed_findings_exist(
    tmp_path,
):
    service, collection_service = _service(
        tmp_path,
        content="Use the accepted preheating finding for the next protocol [Source 1].",
        finding_feedback_service=(_TrainingReadyFindingFeedbackService()),
    )
    collection = collection_service.create_collection("Curated Warning Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Design the next experiment from reviewed findings.",
        page_context={"objective_id": "obj_preheat"},
    )

    assert response["source_mode"] == "collection_grounded"
    assert response["used_evidence_ids"] == ["ev_preheat_ductility"]
    assert "comparison_rows_not_ready" not in response["warnings"]
    assert "evidence_cards_not_ready" not in response["warnings"]
    assert "reviewed_findings_empty" not in response["warnings"]


def test_goal_chat_warns_when_focused_scope_has_no_reviewed_findings(tmp_path):
    feedback_service = _EmptyTrainingReadyFindingFeedbackService()
    service, collection_service = _service(
        tmp_path,
        content="Use the collection evidence cautiously [Source 1].",
        finding_feedback_service=feedback_service,
    )
    collection = collection_service.create_collection("Unreviewed Goal Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_unreviewed",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Draft an experiment plan.",
        page_context={"objective_id": "obj_unreviewed"},
    )

    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "reviewed_findings_empty" in response["warnings"]
    assert "no_collection_evidence_found" in response["warnings"]
    assert service.llm_client.chat.completions.calls == []
    assert feedback_service.calls == [
        {
            "collection_id": collection["collection_id"],
            "objective_id": "obj_unreviewed",
            "dataset_use_status": "training_ready",
        }
    ]


def test_goal_chat_excludes_malformed_training_ready_findings(tmp_path):
    feedback_service = _MalformedTrainingReadyFindingFeedbackService()
    service, collection_service = _service(
        tmp_path,
        content="No reviewed actionable findings are available.",
        finding_feedback_service=feedback_service,
    )
    collection = collection_service.create_collection("Non Actionable Findings")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_non_actionable",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Draft a protocol from reviewed findings.",
        page_context={"objective_id": "obj_non_actionable"},
    )

    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "reviewed_findings_empty" in response["warnings"]
    assert "no_collection_evidence_found" in response["warnings"]
    assert service.llm_client.chat.completions.calls == []


def test_goal_chat_returns_limited_response_when_llm_is_unavailable(tmp_path):
    llm_client = _FailingLLMClient()
    service, collection_service = _service_with_llm_client(
        tmp_path,
        llm_client,
        finding_feedback_service=_TrainingReadyFindingFeedbackService(),
    )
    collection = collection_service.create_collection("Unavailable Model Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Draft an experiment plan.",
        page_context={"objective_id": "obj_preheat"},
    )

    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "goal_copilot_model_unavailable" in response["warnings"]
    assert "reviewed_findings_empty" not in response["warnings"]
    assert "model is currently unavailable" in response["answer"]
    assert len(llm_client.chat.completions.calls) == 1
