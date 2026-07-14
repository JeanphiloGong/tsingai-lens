from __future__ import annotations

import pytest

from domain.goal import GoalMessageRecord, GoalSessionRecord, GoalSourceLink
from domain.goal.session import normalize_answer_mode


def test_goal_session_record_requires_collection_and_normalizes_context() -> None:
    session = GoalSessionRecord.create(
        session_id="gs_123",
        user_id="local-user",
        collection_id=" col_123 ",
        focused_material_id=" mat-316l ",
        focused_paper_id="",
        focused_objective_id=" obj_lpbf ",
        goal_text="  compare strength  ",
        goal_brief_json={"target": "316L"},
        answer_mode="GROUNDED",
        collection_data_version="v1",
        now_iso="2026-05-10T00:00:00+00:00",
    )

    assert session.collection_id == "col_123"
    assert session.focused_material_id == "mat-316l"
    assert session.focused_paper_id is None
    assert session.focused_objective_id == "obj_lpbf"
    assert session.goal_text == "compare strength"
    assert session.answer_mode == "grounded"
    assert session.to_record()["goal_brief_json"] == {"target": "316L"}


def test_goal_session_record_updates_chat_state_after_answer() -> None:
    session = GoalSessionRecord.create(
        session_id="gs_123",
        user_id="local-user",
        collection_id="col_123",
        now_iso="2026-05-10T00:00:00+00:00",
    )
    assistant_message = GoalMessageRecord.assistant(
        message_id="msg_1",
        session_id="gs_123",
        content="Answer",
        source_mode="collection_grounded",
        used_evidence_ids=["E01", "E01", "E02"],
        review_gate="protocol_ready_findings",
        source_links=[
            {
                "kind": "evidence",
                "label": "Source 1",
                "href": "/collections/col_123/documents/doc-a?evidence_id=E01",
            }
        ],
        created_at="2026-05-10T00:01:00+00:00",
    )

    updated = session.after_assistant_message(
        user_message="What supports this?",
        assistant_message=assistant_message,
        material_ids=["mat-316l", "mat-316l"],
        paper_ids=["paper-a"],
        collection_data_version="v2",
        updated_at="2026-05-10T00:01:00+00:00",
        max_summary_chars=1600,
    )

    assert updated.last_evidence_ids == ("E01", "E02")
    assert assistant_message.review_gate == "protocol_ready_findings"
    assert updated.last_material_ids == ("mat-316l",)
    assert updated.last_paper_ids == ("paper-a",)
    assert "collection_grounded" in updated.rolling_summary
    assert updated.collection_data_version == "v2"


def test_goal_message_record_keeps_general_answers_unlinked() -> None:
    message = GoalMessageRecord.assistant(
        message_id="msg_1",
        session_id="gs_123",
        content="General background",
        source_mode="general_fallback",
        used_evidence_ids=["E01"],
        source_links=[
            {
                "kind": "evidence",
                "label": "Source 1",
                "href": "/collections/col_123/evidence?evidence_id=E01",
            }
        ],
        warnings=["no_collection_evidence_found"],
        review_gate="protocol_ready_findings",
        created_at="2026-05-10T00:01:00+00:00",
    )

    assert message.used_evidence_ids == ()
    assert message.source_links == ()
    assert message.review_gate is None
    assert message.to_record()["used_evidence_ids"] == []
    assert message.to_record()["source_links"] == []
    assert message.to_record()["review_gate"] is None


def test_goal_message_record_serializes_user_and_source_links() -> None:
    user_message = GoalMessageRecord.user(
        message_id="msg_u",
        session_id="gs_123",
        content="Hello",
        created_at="2026-05-10T00:00:00+00:00",
    )
    source_link = GoalSourceLink.from_mapping(
        {
            "kind": "document",
            "label": "Paper 1",
            "href": "/collections/col_123/documents/doc-a",
        }
    )

    assert user_message.to_record() == {
        "message_id": "msg_u",
        "session_id": "gs_123",
        "role": "user",
        "content": "Hello",
        "created_at": "2026-05-10T00:00:00+00:00",
    }
    assert source_link.to_record() == {
        "kind": "document",
        "label": "Paper 1",
        "href": "/collections/col_123/documents/doc-a",
    }


def test_goal_domain_rejects_invalid_modes() -> None:
    with pytest.raises(ValueError, match="answer_mode"):
        normalize_answer_mode("decision")

    with pytest.raises(ValueError, match="source_mode"):
        GoalMessageRecord.assistant(
            message_id="msg_1",
            session_id="gs_123",
            content="Answer",
            source_mode="unsupported",
            created_at="2026-05-10T00:01:00+00:00",
        )
