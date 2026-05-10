from __future__ import annotations

from application.goal.session_service import GoalSessionService
from application.source.collection_service import CollectionService
from infra.persistence.factory import build_goal_session_repository


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


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


def _service(
    tmp_path, content: str = "draft answer"
) -> tuple[GoalSessionService, CollectionService]:
    collection_service = CollectionService(tmp_path / "collections")
    service = GoalSessionService(
        collection_service=collection_service,
        research_view_service=_MaterialResearchViewService(),
        workspace_service=_FakeWorkspaceService(),
        comparison_service=_EmptyComparisonService(),
        paper_facts_service=_EmptyPaperFactsService(),
        goal_session_repository=build_goal_session_repository(tmp_path / "lens.sqlite"),
        llm_client=_FakeLLMClient(content),
        model="fake-model",
    )
    return service, collection_service


def test_goal_session_persists_explicit_context(tmp_path):
    service, collection_service = _service(tmp_path)
    collection = collection_service.create_collection("Session Collection")

    session = service.create_session(
        collection_id=collection["collection_id"],
        focused_material_id="mat-316l",
        goal_text="Compare strength and ductility.",
        answer_mode="hybrid",
    )
    loaded = service.get_session(session["session_id"])

    assert loaded["collection_id"] == collection["collection_id"]
    assert loaded["focused_material_id"] == "mat-316l"
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
    )

    updated = service.update_session(
        session["session_id"],
        focused_material_id=None,
        focused_paper_id=None,
    )

    assert updated["focused_material_id"] is None
    assert updated["focused_paper_id"] is None


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
        tmp_path, content="S001 hardness is supported by [E02]."
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
