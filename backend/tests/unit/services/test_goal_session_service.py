from __future__ import annotations

from openai import APIConnectionError

from application.core.comparison_service import ComparisonRowsNotReadyError
from application.core.semantic_build.paper_facts_service import PaperFactsNotReadyError
from application.evaluation import ResearchUnderstandingFeedbackService
from application.goal.experiment_plan_service import ExperimentPlanService
from application.goal.session_service import GoalSessionService
from application.source.collection_service import CollectionService
from domain.core.research_understanding import ResearchUnderstanding
from infra.persistence.factory import build_goal_session_repository
from infra.persistence.sqlite import (
    SqliteEvaluationRepository,
    SqliteExperimentPlanRepository,
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


class _FakeWorkspaceService:
    def get_workspace_overview(self, collection_id: str) -> dict:
        return {
            "collection": {"collection_id": collection_id},
            "status_summary": "ready",
            "links": {},
        }


class _EmptyComparisonService:
    def list_comparison_rows(self, collection_id: str, limit: int = 10) -> dict:
        return {"collection_id": collection_id, "items": [], "total": 0, "limit": limit}


class _EmptyPaperFactsService:
    def list_evidence_cards(self, collection_id: str, limit: int = 10) -> dict:
        return {"collection_id": collection_id, "items": [], "total": 0, "limit": limit}


class _NotReadyComparisonService:
    def list_comparison_rows(self, collection_id: str, limit: int = 10) -> dict:
        raise ComparisonRowsNotReadyError(collection_id)


class _NotReadyPaperFactsService:
    def list_evidence_cards(self, collection_id: str, limit: int = 10) -> dict:
        raise PaperFactsNotReadyError(collection_id)


class _EvidencePaperFactsService:
    def list_evidence_cards(self, collection_id: str, limit: int = 10) -> dict:
        return {
            "collection_id": collection_id,
            "items": [
                {
                    "evidence_id": "ev_unreviewed_fact",
                    "document_id": "paper-unreviewed",
                    "claim": "Unreviewed fact should not drive protocol design.",
                }
            ],
            "total": 1,
            "limit": limit,
        }


class _MaterialResearchViewService:
    def get_collection_research_view(self, collection_id: str) -> dict:
        return {"collection_id": collection_id, "state": "ready", "materials": []}

    def get_collection_material_research_view(
        self,
        collection_id: str,
        material_id: str,
    ) -> dict:
        return {
            "collection_id": collection_id,
            "material_id": material_id,
            "canonical_name": "316L stainless steel",
            "sample_matrix": {
                "rows": [
                    {
                        "sample_id": "S001",
                        "values": {
                            "hardness": {
                                "display_value": "215.6 HV",
                                "evidence_refs": [
                                    {
                                        "evidence_ref_id": "E02",
                                        "document_id": "paper-a",
                                    }
                                ],
                            }
                        },
                        "evidence_refs": [
                            {
                                "evidence_ref_id": "E01",
                                "document_id": "paper-a",
                            }
                        ],
                    }
                ]
            },
        }


class _EmptyResearchObjectiveService:
    def list_objective_workspaces(self, collection_id: str) -> dict:
        return {
            "collection_id": collection_id,
            "state": "empty",
            "readiness": {
                "objectives_ready": False,
                "frames_ready": False,
                "routes_ready": False,
                "evidence_units_ready": False,
                "logic_chain_ready": False,
            },
            "objectives": [],
            "warnings": [],
        }

    def get_objective_research_view(self, collection_id: str, objective_id: str) -> dict:
        return {
            "collection_id": collection_id,
            "state": "empty",
            "objective": {
                "objective_id": objective_id,
                "question": objective_id,
                "material_scope": [],
                "process_axes": [],
                "property_axes": [],
                "comparison_intent": None,
                "confidence": 0.0,
            },
            "objective_context": None,
            "readiness": {
                "objectives_ready": False,
                "frames_ready": False,
                "routes_ready": False,
                "evidence_units_ready": False,
                "logic_chain_ready": False,
            },
            "paper_frames": [],
            "evidence_routes": [],
            "evidence_units": [],
            "logic_chain": None,
            "existing_comparison_rows": [],
            "warnings": [],
        }


class _TrainingReadyResearchUnderstandingFeedbackService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def export_dataset(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(dict(kwargs))
        if kwargs["scope_type"] != "goal":
            return {
                "collection_id": kwargs["collection_id"],
                "scope_type": kwargs["scope_type"],
                "scope_id": kwargs["scope_id"],
                "dataset_use_status_filter": kwargs["dataset_use_status"],
                "item_count": 0,
                "items": [],
                "warnings": [],
            }
        return {
            "collection_id": kwargs["collection_id"],
            "scope_type": "goal",
            "scope_id": kwargs["scope_id"],
            "dataset_use_status_filter": kwargs["dataset_use_status"],
            "item_count": 2,
            "items": [
                {
                    "finding_id": "finding_preheat_ductility",
                    "claim_id": "claim_preheat_ductility",
                    "finding_fingerprint": "finding.v1:preheat-ductility",
                    "protocol_source_fingerprint": "protocol-source.v1:preheat-ductility",
                    "label_status": "gold",
                    "dataset_use_status": "training_ready",
                    "system_prediction": {
                        "statement": "Preheating the build platform to 150 C increases LPBF 316L ductility by about 14%.",
                        "variables": ["build platform preheating temperature"],
                        "mediators": ["microstructure", "GND density"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                        "scope_summary": "LPBF 316L stainless steel",
                        "support_grade": "strong",
                        "generalization_status": "paper_level_only",
                        "generalization_note": (
                            "Accepted as a source-backed paper-level finding; "
                            "design validation instead of treating it as a "
                            "cross-paper conclusion."
                        ),
                    },
                    "expert_target": {
                        "statement": "150 C preheating improves LPBF 316L ductility through microstructure/GND changes.",
                        "variables": ["build platform preheating temperature"],
                        "mediators": ["microstructure", "GND density"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                        "scope_summary": "LPBF 316L stainless steel",
                        "support_grade": "strong",
                        "generalization_status": "paper_level_only",
                        "generalization_note": (
                            "Accepted as a source-backed paper-level finding; "
                            "design validation instead of treating it as a "
                            "cross-paper conclusion."
                        ),
                    },
                    "protocol_readiness": {"status": "protocol_ready"},
                    "training_evidence_refs": [
                        {
                            "evidence_ref_id": "ev_preheat_ductility",
                            "document_id": "paper-preheat",
                            "page": 7,
                            "source_kind": "paragraph",
                            "source_ref": "Results",
                            "training_source_text": "The sample preheated at 150 C shows a 14% improvement in ductility.",
                        }
                    ],
                },
                {
                    "finding_id": "finding_review_candidate",
                    "label_status": "silver",
                    "dataset_use_status": "review_candidate",
                    "system_prediction": {
                        "statement": "Review-only finding should not be used for protocol design.",
                    },
                    "training_evidence_refs": [
                        {
                            "evidence_ref_id": "ev_review_candidate",
                            "document_id": "paper-review",
                            "training_source_text": "This text still needs review.",
                        }
                    ],
                },
            ],
            "warnings": [],
        }


class _EmptyTrainingReadyResearchUnderstandingFeedbackService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def export_dataset(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(dict(kwargs))
        return {
            "collection_id": kwargs["collection_id"],
            "scope_type": kwargs["scope_type"],
            "scope_id": kwargs["scope_id"],
            "dataset_use_status_filter": kwargs["dataset_use_status"],
            "item_count": 0,
            "items": [],
            "warnings": [],
        }


class _ProtocolIneligibleTrainingReadyResearchUnderstandingFeedbackService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def export_dataset(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(dict(kwargs))
        return {
            "collection_id": kwargs["collection_id"],
            "scope_type": "goal",
            "scope_id": kwargs["scope_id"],
            "dataset_use_status_filter": kwargs["dataset_use_status"],
            "item_count": 5,
            "items": [
                {
                    "finding_id": "finding_missing_protocol_inputs",
                    "label_status": "gold",
                    "dataset_use_status": "training_ready",
                    "expert_target": {
                        "statement": "This accepted text lacks variables and outcomes for protocol design.",
                        "support_grade": "strong",
                    },
                    "training_evidence_refs": [
                        {
                            "evidence_ref_id": "ev_missing_inputs",
                            "document_id": "paper-missing-inputs",
                            "training_source_text": "Accepted text without actionable protocol fields.",
                        }
                    ],
                },
                {
                    "finding_id": "finding_unsupported",
                    "label_status": "gold",
                    "dataset_use_status": "training_ready",
                    "system_prediction": {
                        "statement": "Claim rejected by expert support status.",
                    },
                    "expert_target": {
                        "statement": "Preheating does not have sufficient support for ductility improvement.",
                        "status": "unsupported",
                        "support_grade": "strong",
                    },
                    "training_evidence_refs": [
                        {
                            "evidence_ref_id": "ev_unsupported",
                            "document_id": "paper-unsupported",
                            "training_source_text": "The reviewed evidence does not support the claimed improvement.",
                        }
                    ],
                },
                {
                    "finding_id": "finding_conflict",
                    "label_status": "gold",
                    "dataset_use_status": "training_ready",
                    "expert_target": {
                        "statement": "VED effects conflict across the available papers.",
                        "status": "conflicted",
                        "support_grade": "partial",
                    },
                    "training_evidence_refs": [
                        {
                            "evidence_ref_id": "ev_conflict",
                            "document_id": "paper-conflict",
                            "training_source_text": "Conflicting results were reported.",
                        }
                    ],
                },
                {
                    "finding_id": "finding_insufficient",
                    "label_status": "gold",
                    "dataset_use_status": "training_ready",
                    "expert_target": {
                        "statement": "Evidence remains insufficient for a protocol decision.",
                        "status": "limited",
                        "support_grade": "insufficient",
                    },
                    "training_evidence_refs": [
                        {
                            "evidence_ref_id": "ev_insufficient",
                            "document_id": "paper-insufficient",
                            "training_source_text": "Only background context was available.",
                        }
                    ],
                },
                {
                    "finding_id": "finding_protocol_blocked",
                    "label_status": "gold",
                    "dataset_use_status": "training_ready",
                    "expert_target": {
                        "statement": (
                            "Preheating improves ductility but the protocol input "
                            "remains incomplete."
                        ),
                        "status": "supported",
                        "support_grade": "strong",
                        "variables": ["build platform preheating temperature"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                    },
                    "protocol_readiness": {
                        "status": "needs_correction",
                        "blocking_missing": ["training_messages"],
                    },
                    "training_evidence_refs": [
                        {
                            "evidence_ref_id": "ev_protocol_blocked",
                            "document_id": "paper-protocol-blocked",
                            "training_source_text": (
                                "The evidence is traceable but the protocol message "
                                "is incomplete."
                            ),
                        }
                    ],
                },
            ],
            "warnings": [],
        }


class _SingleUnderstandingRepository:
    backend_name = "fake"

    def __init__(self, understanding: ResearchUnderstanding) -> None:
        self.understanding = understanding

    def read_research_understanding(
        self,
        collection_id: str,  # noqa: ARG002
        scope_type: str,  # noqa: ARG002
        scope_id: str,  # noqa: ARG002
    ):
        return self.understanding

    def list_research_understandings(
        self,
        collection_id: str,  # noqa: ARG002
        scope_type: str | None = None,  # noqa: ARG002
    ):
        return (self.understanding,)


class _PassthroughResearchUnderstandingProjectionService:
    def with_presentation(self, understanding):
        return understanding.to_record()


class _ObjectiveResearchService(_EmptyResearchObjectiveService):
    def list_objective_workspaces(self, collection_id: str) -> dict:
        return {
            "collection_id": collection_id,
            "state": "ready",
            "readiness": {
                "objectives_ready": True,
                "frames_ready": True,
                "routes_ready": True,
                "evidence_units_ready": True,
                "logic_chain_ready": True,
            },
            "objectives": [
                {
                    "objective_id": "obj_lpbf_strength",
                    "question": "How does LPBF energy density affect 316L strength?",
                    "material_scope": ["316L stainless steel"],
                    "process_axes": ["energy density", "scan strategy"],
                    "property_axes": ["yield strength", "elongation"],
                    "comparison_intent": "Compare LPBF process windows against mechanical response.",
                    "confidence": 0.87,
                    "state": "ready",
                    "paper_frame_count": 1,
                    "evidence_route_count": 1,
                    "evidence_unit_count": 1,
                    "logic_chain_count": 1,
                }
            ],
            "warnings": [],
        }

    def get_objective_research_view(self, collection_id: str, objective_id: str) -> dict:
        return {
            "collection_id": collection_id,
            "state": "ready",
            "objective": {
                "objective_id": objective_id,
                "question": "How does LPBF energy density affect 316L strength?",
                "material_scope": ["316L stainless steel"],
                "process_axes": ["energy density", "scan strategy"],
                "property_axes": ["yield strength", "elongation"],
                "comparison_intent": "Compare LPBF process windows against mechanical response.",
                "confidence": 0.87,
            },
            "objective_context": {
                "objective_id": objective_id,
                "question": "How does LPBF energy density affect 316L strength?",
                "material_scope": ["316L stainless steel"],
                "variable_process_axes": ["energy density"],
                "process_context_axes": ["scan strategy"],
                "target_property_axes": ["yield strength", "elongation"],
                "excluded_property_axes": [],
                "routing_hints": [],
                "extraction_guidance": {"focus": "mechanical evidence"},
                "confidence": 0.84,
            },
            "readiness": {
                "objectives_ready": True,
                "frames_ready": True,
                "routes_ready": True,
                "evidence_units_ready": True,
                "logic_chain_ready": True,
            },
            "paper_frames": [
                {
                    "frame_id": "frame_1",
                    "objective_id": objective_id,
                    "document_id": "paper-a",
                    "title": "LPBF 316L process window",
                    "source_filename": "p001.pdf",
                    "relevance": "high",
                    "paper_role": "primary_experiment",
                    "background": "16 LPBF samples compare energy density and scan strategy.",
                    "material_match": ["316L stainless steel"],
                    "changed_variables": ["energy density", "scan strategy"],
                    "measured_property_scope": ["yield strength", "elongation"],
                    "test_environment_scope": [],
                    "relevant_sections": ["Results"],
                    "relevant_tables": ["Table 3"],
                    "excluded_tables": [],
                }
            ],
            "evidence_routes": [],
            "evidence_units": [
                {
                    "evidence_unit_id": "oeu_strength",
                    "objective_id": objective_id,
                    "document_id": "paper-a",
                    "unit_kind": "measurement",
                    "property_normalized": "yield strength",
                    "material_system": {"name": "316L stainless steel"},
                    "sample_context": {"sample_id": "S014"},
                    "process_context": {"energy_density": "100 J/mm3"},
                    "resolved_condition": {},
                    "test_condition": {},
                    "value_payload": {"value": 448, "unit": "MPa"},
                    "unit": "MPa",
                    "baseline_context": {},
                    "interpretation": None,
                    "source_refs": [
                        {
                            "document_id": "paper-a",
                            "evidence_id": "ev_strength",
                            "page": 8,
                            "source_kind": "table",
                            "source_ref": "Table 3",
                        }
                    ],
                    "evidence_anchor_ids": ["anc_strength"],
                    "join_keys": {},
                    "resolution_status": "resolved",
                    "confidence": 0.91,
                }
            ],
            "logic_chain": {
                "logic_chain_id": "chain_strength",
                "objective_id": objective_id,
                "chain_scope": "objective",
                "document_id": None,
                "question": "How does LPBF energy density affect 316L strength?",
                "evidence_unit_ids": ["oeu_strength"],
                "chain_payload": {
                    "steps": [
                        {"step_role": "process", "label": "LPBF energy density"},
                        {"step_role": "performance", "label": "yield strength"},
                    ]
                },
                "summary": "LPBF energy density and scan strategy shape strength and ductility.",
                "confidence": 0.88,
            },
            "existing_comparison_rows": [],
            "warnings": [],
        }


def _service(
    tmp_path,
    content: str = "draft answer",
    research_objective_service=None,
    research_understanding_feedback_service=None,
    comparison_service=None,
    paper_facts_service=None,
) -> tuple[GoalSessionService, CollectionService]:
    collection_service = CollectionService(tmp_path / "collections")
    service = GoalSessionService(
        collection_service=collection_service,
        research_view_service=_MaterialResearchViewService(),
        workspace_service=_FakeWorkspaceService(),
        comparison_service=comparison_service or _EmptyComparisonService(),
        paper_facts_service=paper_facts_service or _EmptyPaperFactsService(),
        research_objective_service=research_objective_service
        or _EmptyResearchObjectiveService(),
        research_understanding_feedback_service=research_understanding_feedback_service,
        goal_session_repository=build_goal_session_repository(tmp_path / "lens.sqlite"),
        llm_client=_FakeLLMClient(content),
        model="fake-model",
    )
    return service, collection_service


def _service_with_llm_client(
    tmp_path,
    llm_client,
    research_objective_service=None,
    research_understanding_feedback_service=None,
    comparison_service=None,
    paper_facts_service=None,
) -> tuple[GoalSessionService, CollectionService]:
    collection_service = CollectionService(tmp_path / "collections")
    service = GoalSessionService(
        collection_service=collection_service,
        research_view_service=_MaterialResearchViewService(),
        workspace_service=_FakeWorkspaceService(),
        comparison_service=comparison_service or _EmptyComparisonService(),
        paper_facts_service=paper_facts_service or _EmptyPaperFactsService(),
        research_objective_service=research_objective_service
        or _EmptyResearchObjectiveService(),
        research_understanding_feedback_service=research_understanding_feedback_service,
        goal_session_repository=build_goal_session_repository(tmp_path / "lens.sqlite"),
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
        focused_goal_id="goal_lpbf_strength",
        goal_text="Compare strength and ductility.",
        answer_mode="hybrid",
    )
    loaded = service.get_session(session["session_id"])

    assert loaded["collection_id"] == collection["collection_id"]
    assert loaded["focused_material_id"] == "mat-316l"
    assert loaded["focused_objective_id"] == "obj_lpbf_strength"
    assert loaded["focused_goal_id"] == "goal_lpbf_strength"
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
    assert response["source_mode"] == "general_fallback"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []


def test_goal_session_update_can_clear_focus(tmp_path):
    service, collection_service = _service(tmp_path)
    collection = collection_service.create_collection("Session Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_material_id="mat-316l",
        focused_paper_id="paper-a",
        focused_objective_id="obj_lpbf_strength",
        focused_goal_id="goal_lpbf_strength",
    )

    updated = service.update_session(
        session["session_id"],
        focused_material_id=None,
        focused_paper_id=None,
        focused_objective_id=None,
        focused_goal_id=None,
    )

    assert updated["focused_material_id"] is None
    assert updated["focused_paper_id"] is None
    assert updated["focused_objective_id"] is None
    assert updated["focused_goal_id"] is None


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


def test_hybrid_message_uses_general_fallback_when_collection_has_no_context(tmp_path):
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
    loaded = service.get_session(session["session_id"])

    assert response["source_mode"] == "general_fallback"
    assert response["used_evidence_ids"] == []
    assert response["answer"].startswith("The current collection does not contain")
    assert "not collection evidence" in loaded["rolling_summary"]
    assert service.llm_client.chat.completions.calls[0]["model"] == "fake-model"


def test_material_page_context_scopes_grounded_answer(tmp_path):
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

    assert response["source_mode"] == "collection_grounded"
    assert set(response["used_evidence_ids"]) == {"E01", "E02"}
    assert {link["href"] for link in response["source_links"]} == {
        f"/collections/{collection['collection_id']}/documents/paper-a?evidence_id=E02",
        f"/collections/{collection['collection_id']}/documents/paper-a?evidence_id=E01",
    }
    assert all(link["label"].startswith("Source ") for link in response["source_links"])
    assert all("document_id" not in link for link in response["source_links"])
    assert loaded["focused_material_id"] == "mat-316l"
    assert set(loaded["last_evidence_ids"]) == {"E01", "E02"}
    prompt_messages = service.llm_client.chat.completions.calls[0]["messages"]
    assert "Cite source link labels" in prompt_messages[0]["content"]
    assert "Source links:" in prompt_messages[1]["content"]


def test_objective_context_is_available_to_grounded_chat(tmp_path):
    service, collection_service = _service(
        tmp_path,
        content="The objective is supported by [Source 1].",
        research_objective_service=_ObjectiveResearchService(),
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

    assert response["source_mode"] == "collection_grounded"
    assert response["used_evidence_ids"] == ["ev_strength"]
    assert response["source_links"] == [
        {
            "kind": "evidence",
            "label": "Source 1",
            "href": (
                f"/collections/{collection['collection_id']}/documents/"
                "paper-a?evidence_id=ev_strength"
            ),
        }
    ]
    assert loaded["focused_objective_id"] == "obj_lpbf_strength"
    assert loaded["last_paper_ids"] == ["paper-a"]
    prompt = service.llm_client.chat.completions.calls[0]["messages"][1]["content"]
    assert "focused_objective_id: obj_lpbf_strength" in prompt
    assert "objective_research_view" in prompt
    assert "LPBF energy density and scan strategy shape strength" in prompt
    assert "oeu_strength" in prompt


def test_goal_chat_downgrades_uncited_grounded_answer(tmp_path):
    service, collection_service = _service(
        tmp_path,
        content="The objective is supported by the collection evidence.",
        research_objective_service=_ObjectiveResearchService(),
    )
    collection = collection_service.create_collection("Uncited Objective Collection")
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
    assert "goal_copilot_missing_source_citation" in response["warnings"]
    assert "do not treat it as a traceable collection conclusion" in response["answer"]
    assert loaded["last_evidence_ids"] == []


def test_goal_chat_uses_protocol_ready_findings_for_protocol_context(tmp_path):
    feedback_service = _TrainingReadyResearchUnderstandingFeedbackService()
    service, collection_service = _service(
        tmp_path,
        content=(
            "<think>Use hidden reasoning and unreviewed facts.</think>\n"
            "Use the accepted preheating finding for the next protocol [Source 1]."
        ),
        research_understanding_feedback_service=feedback_service,
        paper_facts_service=_EvidencePaperFactsService(),
    )
    collection = collection_service.create_collection("Goal Finding Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_goal_id="goal_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Design the next experiment from reviewed findings.",
        page_context={"goal_id": "goal_preheat"},
    )
    loaded = service.get_session(session["session_id"])

    assert response["source_mode"] == "collection_grounded"
    assert response["review_gate"] == "protocol_ready_findings"
    assert "<think>" not in response["answer"]
    assert response["used_evidence_ids"] == ["ev_preheat_ductility"]
    assert response["source_finding_refs"] == [
        {
            "finding_id": "finding_preheat_ductility",
            "finding_fingerprint": "finding.v1:preheat-ductility",
            "protocol_source_fingerprint": "protocol-source.v1:preheat-ductility",
            "evidence_ref_ids": ["ev_preheat_ductility"],
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
    assert loaded["focused_goal_id"] == "goal_preheat"
    assert service.list_messages(session["session_id"])["items"][-1]["review_gate"] == (
        "protocol_ready_findings"
    )
    assert service.list_messages(session["session_id"])["items"][-1][
        "source_finding_refs"
    ] == response["source_finding_refs"]
    assert feedback_service.calls == [
        {
            "collection_id": collection["collection_id"],
            "scope_type": "goal",
            "scope_id": "goal_preheat",
            "dataset_use_status": "training_ready",
        }
    ]
    prompt_messages = service.llm_client.chat.completions.calls[0]["messages"]
    assert "curated protocol-ready findings first" in prompt_messages[0]["content"]
    assert "Protocol draft requirements" in prompt_messages[0]["content"]
    assert "Hypothesis" in prompt_messages[0]["content"]
    assert "Variable matrix" in prompt_messages[0]["content"]
    assert "Measurements" in prompt_messages[0]["content"]
    assert "Controls" in prompt_messages[0]["content"]
    assert "Risks or limits" in prompt_messages[0]["content"]
    assert "Do not collapse protocol answers into one paragraph" in prompt_messages[0]["content"]
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
    assert "curated_research_findings" in prompt
    assert "150 C preheating improves LPBF 316L ductility" in prompt
    assert "The sample preheated at 150 C shows a 14% improvement" in prompt
    assert "paper_level_only" in prompt
    assert "design validation instead of treating it as a cross-paper conclusion" in prompt
    assert "ev_unreviewed_fact" not in prompt
    assert "paper-unreviewed" not in prompt
    assert "ev_preheat_ductility" not in prompt
    assert "finding_review_candidate" not in prompt


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
            "Compare ambient and preheated builds while the expert selects the levels."
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
        research_understanding_feedback_service=(
            _TrainingReadyResearchUnderstandingFeedbackService()
        ),
        paper_facts_service=_EvidencePaperFactsService(),
    )
    collection = collection_service.create_collection("Repair Protocol Contract")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_goal_id="goal_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Design the next experiment from reviewed findings.",
        page_context={"goal_id": "goal_preheat"},
    )

    assert response["source_mode"] == "collection_grounded"
    assert "150 C preheating improves LPBF 316L ductility" in response["answer"]
    assert (
        "- Source-backed: Observed relation: build platform preheating temperature "
        "-> ductility; mediator: microstructure, GND density; direction: increase; "
        "scope: LPBF 316L stainless steel. [Source 1]"
    ) in response["answer"]
    assert "- Source-backed: Reported outcome: ductility. [Source 1]" in (
        response["answer"]
    )
    assert "- Proposed design choice: Compare ambient and preheated builds" in (
        response["answer"]
    )
    assert "\nSource-backed:\n" not in response["answer"]
    assert response["review_gate"] == "protocol_ready_findings"
    assert response["warnings"] == []
    assert len(llm_client.chat.completions.calls) == 1
    assert len(llm_client.beta.chat.completions.calls) == 1
    parse_call = llm_client.beta.chat.completions.calls[0]
    assert parse_call["response_format"].__name__ == "_StructuredProtocolDraft"
    repair_prompt = parse_call["messages"][1]["content"]
    assert "Repair the protocol as structured data" in repair_prompt
    assert "Normalize the protocol into the required evidence/design fields" in (
        repair_prompt
    )
    assert invalid_draft.strip() in repair_prompt


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
        research_understanding_feedback_service=(
            _TrainingReadyResearchUnderstandingFeedbackService()
        ),
        paper_facts_service=_EvidencePaperFactsService(),
    )
    collection = collection_service.create_collection("Reject Invalid Protocol")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_goal_id="goal_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Design the next experiment from reviewed findings.",
        page_context={"goal_id": "goal_preheat"},
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
        "proposed_variable_manipulations": [
            "Compare low and moderate VED levels."
        ],
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
        research_understanding_feedback_service=(
            _TrainingReadyResearchUnderstandingFeedbackService()
        ),
        paper_facts_service=_EvidencePaperFactsService(),
    )
    collection = collection_service.create_collection("Reject Impossible VED Protocol")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_goal_id="goal_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Design the next experiment from reviewed findings.",
        page_context={"goal_id": "goal_preheat"},
    )

    assert response["source_mode"] == "collection_limited"
    assert response["review_gate"] is None
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "goal_copilot_protocol_contract_invalid" in response["warnings"]
    assert "could not verify the protocol draft contract" in response["answer"]


def test_reviewed_finding_drives_traceable_experiment_plan(tmp_path):
    understanding = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-reviewed",
                "goal_id": "goal_reviewed",
                "title": "How does preheating affect ductility?",
            },
            "claims": [
                {
                    "claim_id": "claim_preheat",
                    "claim_type": "finding",
                    "statement": "Preheating improves ductility.",
                    "status": "supported",
                    "evidence_ref_ids": ["ev_preheat"],
                    "context_ids": ["ctx_lpbf"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "ev_preheat",
                    "source_kind": "text",
                    "document_id": "paper-preheat",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-preheat"},
                    "traceability_status": "direct",
                    "evidence_role": "direct_result",
                    "quote": "Preheating increased ductility by 14% in LPBF 316L.",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_lpbf",
                    "label": "LPBF 316L",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "LPBF"},
                    "test_condition": {"temperature": "room"},
                    "property_scope": ["ductility"],
                    "limitations": [],
                }
            ],
            "presentation": {
                "findings": [
                    {
                        "finding_id": "finding_preheat",
                        "claim_id": "claim_preheat",
                        "title": "preheating -> ductility",
                        "statement": "Preheating improves ductility.",
                        "variables": ["preheating"],
                        "mediators": ["microstructure"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                        "scope_summary": "LPBF 316L",
                        "support_grade": "partial",
                        "review_status": "needs_review",
                        "generalization_status": "paper_level_only",
                        "generalization_note": (
                            "Evidence comes from one paper; use this as a traceable "
                            "paper-level finding, not a cross-paper conclusion."
                        ),
                        "paper_count": 1,
                        "evidence_count": 1,
                        "evidence_bundle": {"direct_result": ["ev_preheat"]},
                        "evidence_ref_ids": ["ev_preheat"],
                        "context_ids": ["ctx_lpbf"],
                    }
                ],
                "evidence_items": [
                    {
                        "evidence_ref_id": "ev_preheat",
                        "document_id": "paper-preheat",
                        "title": "P001 Results",
                        "source_label": "P001 p.7",
                        "source_kind": "text",
                        "source_ref": "blk-preheat",
                        "page": "7",
                        "quote": "Preheating increased ductility by 14%.",
                        "source_text": (
                            "The sample preheated at 150 C shows a 14% "
                            "improvement in ductility."
                        ),
                        "traceability_status": "direct",
                        "evidence_role": "direct_result",
                    }
                ],
                "context_summaries": [
                    {
                        "context_id": "ctx_lpbf",
                        "label": "LPBF 316L",
                        "material_scope": ["316L stainless steel"],
                        "property_scope": ["ductility"],
                        "process_summary": "LPBF",
                        "test_summary": "room temperature",
                    }
                ],
            },
            "model_traces": [],
        }
    )
    feedback_service = ResearchUnderstandingFeedbackService(
        evaluation_repository=SqliteEvaluationRepository(tmp_path / "lens.sqlite"),
        core_fact_repository=_SingleUnderstandingRepository(understanding),
        research_understanding_service=(
            _PassthroughResearchUnderstandingProjectionService()
        ),
    )
    protocol_candidate = (
            "Hypothesis: 150 C preheating improves LPBF 316L ductility "
            "through microstructure changes [Source 1].\n"
            "Variable matrix: compare 25 C and 150 C build-platform "
            "preheating.\n"
            "Measurements: elongation and microstructure.\n"
            "Controls: keep LPBF alloy, powder, and scan parameters fixed.\n"
            "Risks or limits: current evidence is one LPBF 316L finding."
        )
    structured_protocol = {
        "proposed_variable_manipulations": [
            "Compare ambient and preheated conditions selected by the expert."
        ],
        "proposed_measurements": [
            "The expert selects a validated microstructure method."
        ],
        "proposed_controls": [
            "Keep alloy, powder, and scan parameters fixed."
        ],
        "design_risks": ["Uncontrolled scan parameters can confound preheating effects."],
    }
    service, collection_service = _service_with_llm_client(
        tmp_path,
        _StructuredRepairLLMClient(protocol_candidate, structured_protocol),
        research_understanding_feedback_service=feedback_service,
        paper_facts_service=_EvidencePaperFactsService(),
    )
    collection = collection_service.create_collection("Reviewed Goal Collection")
    collection_id = collection["collection_id"]
    feedback_service.record_curation(
        collection_id=collection_id,
        scope_type="goal",
        scope_id="goal_reviewed",
        finding_id="finding_preheat",
        claim_id="claim_preheat",
        curated_claim_type="finding",
        curated_status="supported",
        curated_statement=(
            "150 C preheating improves LPBF 316L ductility through "
            "microstructure changes."
        ),
        curated_support_grade="partial",
        curated_review_status="accepted",
        curated_variables=["preheating"],
        curated_mediators=["microstructure"],
        curated_outcomes=["ductility"],
        curated_direction="increase",
        curated_scope_summary="LPBF 316L",
        curated_evidence_ref_ids=["ev_preheat"],
        curated_context_ids=["ctx_lpbf"],
        reviewer="materials-expert",
    )

    dataset = feedback_service.export_dataset(
        collection_id=collection_id,
        scope_type="goal",
        scope_id="goal_reviewed",
        dataset_use_status="training_ready",
    )
    session = service.create_session(
        collection_id=collection_id,
        focused_goal_id="goal_reviewed",
        answer_mode="hybrid",
        user_id="expert-a",
    )
    response = service.post_message(
        session["session_id"],
        message="Draft a protocol from reviewed findings.",
        page_context={"goal_id": "goal_reviewed"},
    )
    plan_service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=service.goal_session_repository,
    )
    plan = plan_service.create_plan(
        collection_id=collection_id,
        goal_id="goal_reviewed",
        title="Preheating validation protocol",
        content=response["answer"],
        source_message_id=response["message_id"],
        source_links=response["source_links"],
        metadata={"source": "goal_copilot"},
        created_by="expert-a",
    )

    assert dataset["item_count"] == 1
    assert dataset["items"][0]["label_status"] == "gold"
    assert dataset["items"][0]["dataset_use_status"] == "training_ready"
    assert dataset["items"][0]["protocol_readiness"]["status"] == "protocol_ready"
    assert dataset["quality_summary"]["protocol_ready_sample_count"] == 1
    assert len(dataset["items"][0]["training_messages"]) == 2
    assert response["source_mode"] == "collection_grounded"
    assert response["review_gate"] == "protocol_ready_findings"
    assert "- Proposed design choice: Compare ambient and preheated conditions" in (
        response["answer"]
    )
    assert response["used_evidence_ids"] == ["ev_preheat"]
    assert response["source_links"] == [
        {
            "kind": "evidence",
            "label": "Source 1",
            "href": (
                f"/collections/{collection_id}/documents/"
                "paper-preheat?evidence_id=ev_preheat"
            ),
        }
    ]
    prompt = service.llm_client.chat.completions.calls[0]["messages"][1]["content"]
    assert "curated_research_findings" in prompt
    assert "microstructure changes" in prompt
    assert "ev_preheat" not in prompt
    assert plan.metadata["review_gate"] == "protocol_ready_findings"
    assert plan.metadata["used_evidence_ids"] == ["ev_preheat"]
    assert plan.source_links[0]["href"].endswith("evidence_id=ev_preheat")


def test_goal_chat_suppresses_backbone_readiness_warnings_when_curated_findings_exist(
    tmp_path,
):
    service, collection_service = _service(
        tmp_path,
        content="Use the accepted preheating finding for the next protocol [Source 1].",
        research_understanding_feedback_service=(
            _TrainingReadyResearchUnderstandingFeedbackService()
        ),
        comparison_service=_NotReadyComparisonService(),
        paper_facts_service=_NotReadyPaperFactsService(),
    )
    collection = collection_service.create_collection("Curated Warning Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_goal_id="goal_preheat",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Design the next experiment from reviewed findings.",
        page_context={"goal_id": "goal_preheat"},
    )

    assert response["source_mode"] == "collection_grounded"
    assert response["used_evidence_ids"] == ["ev_preheat_ductility"]
    assert "comparison_rows_not_ready" not in response["warnings"]
    assert "evidence_cards_not_ready" not in response["warnings"]
    assert "curated_research_findings_empty" not in response["warnings"]


def test_goal_chat_warns_when_focused_scope_has_no_protocol_ready_findings(tmp_path):
    feedback_service = _EmptyTrainingReadyResearchUnderstandingFeedbackService()
    service, collection_service = _service(
        tmp_path,
        content="Use the collection evidence cautiously [Source 1].",
        research_objective_service=_ObjectiveResearchService(),
        research_understanding_feedback_service=feedback_service,
    )
    collection = collection_service.create_collection("Unreviewed Goal Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_goal_id="goal_unreviewed",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Draft an experiment plan.",
        page_context={"goal_id": "goal_unreviewed"},
    )

    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "curated_research_findings_empty" in response["warnings"]
    assert "goal_copilot_missing_source_citation" in response["warnings"]
    assert feedback_service.calls == [
        {
            "collection_id": collection["collection_id"],
            "scope_type": "goal",
            "scope_id": "goal_unreviewed",
            "dataset_use_status": "training_ready",
        }
    ]


def test_goal_chat_excludes_training_ready_findings_that_are_not_protocol_ready(tmp_path):
    feedback_service = _ProtocolIneligibleTrainingReadyResearchUnderstandingFeedbackService()
    service, collection_service = _service(
        tmp_path,
        content="No reviewed actionable findings are available.",
        research_understanding_feedback_service=feedback_service,
        paper_facts_service=_EvidencePaperFactsService(),
    )
    collection = collection_service.create_collection("Non Actionable Findings")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_goal_id="goal_non_actionable",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Draft a protocol from reviewed findings.",
        page_context={"goal_id": "goal_non_actionable"},
    )

    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "curated_research_findings_empty" in response["warnings"]
    assert "goal_copilot_missing_source_citation" in response["warnings"]
    prompt = service.llm_client.chat.completions.calls[0]["messages"][1]["content"]
    assert "curated_research_findings" not in prompt
    assert "ev_missing_inputs" not in prompt
    assert "ev_unsupported" not in prompt
    assert "ev_conflict" not in prompt
    assert "ev_insufficient" not in prompt
    assert "ev_protocol_blocked" not in prompt


def test_goal_chat_returns_limited_response_when_llm_is_unavailable(tmp_path):
    llm_client = _FailingLLMClient()
    service, collection_service = _service_with_llm_client(
        tmp_path,
        llm_client,
        research_objective_service=_ObjectiveResearchService(),
    )
    collection = collection_service.create_collection("Unavailable Model Collection")
    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_objective_id="obj_lpbf_strength",
        answer_mode="hybrid",
    )

    response = service.post_message(
        session["session_id"],
        message="Draft an experiment plan.",
        page_context={"objective_id": "obj_lpbf_strength"},
    )

    assert response["source_mode"] == "collection_limited"
    assert response["used_evidence_ids"] == []
    assert response["source_links"] == []
    assert "goal_copilot_model_unavailable" in response["warnings"]
    assert "curated_research_findings_empty" in response["warnings"]
    assert "model is currently unavailable" in response["answer"]
    assert len(llm_client.chat.completions.calls) == 1
