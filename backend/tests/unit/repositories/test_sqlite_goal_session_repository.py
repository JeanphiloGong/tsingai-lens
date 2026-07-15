from __future__ import annotations

from infra.persistence.sqlite import SqliteGoalSessionRepository


def _session_record() -> dict:
    return {
        "session_id": "gs_demo",
        "user_id": "local-user",
        "collection_id": "col_demo",
        "focused_material_id": "mat-316l",
        "focused_paper_id": None,
        "focused_objective_id": "obj_lpbf",
        "focused_goal_id": "goal_lpbf",
        "goal_text": "Compare strength and ductility.",
        "goal_brief_json": {"objective": "compare"},
        "answer_mode": "hybrid",
        "rolling_summary": "",
        "last_evidence_ids": [],
        "last_material_ids": [],
        "last_paper_ids": [],
        "collection_data_version": "v1",
        "created_at": "2026-05-10T00:00:00+00:00",
        "updated_at": "2026-05-10T00:00:00+00:00",
    }


def test_sqlite_goal_session_repository_round_trips_sessions_and_messages(tmp_path):
    repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    session = _session_record()

    repository.write_session(session)
    repository.write_messages(
        session["session_id"],
        [
            {
                "message_id": "msg_user",
                "session_id": session["session_id"],
                "role": "user",
                "content": "What evidence supports hardness?",
                "created_at": "2026-05-10T00:00:01+00:00",
            },
            {
                "message_id": "msg_assistant",
                "session_id": session["session_id"],
                "role": "assistant",
                "content": "Hardness is supported by [Source 1].",
                "answer": "Hardness is supported by [Source 1].",
                "source_mode": "collection_grounded",
                "used_evidence_ids": ["E01"],
                "warnings": [],
                "links": {"workspace": "/collections/col_demo"},
                "review_gate": "protocol_ready_findings",
                "source_links": [
                    {
                        "kind": "evidence",
                        "label": "Source 1",
                        "href": "/collections/col_demo/documents/paper-a?evidence_id=E01",
                    }
                ],
                "source_finding_refs": [
                    {
                        "finding_id": "finding-1",
                        "finding_fingerprint": "finding.v1:abc",
                        "protocol_source_fingerprint": "protocol-source.v1:def",
                        "evidence_ref_ids": ["E01"],
                    }
                ],
                "created_at": "2026-05-10T00:00:02+00:00",
            },
        ],
    )

    assert repository.read_session(session["session_id"]) == session
    messages = repository.read_messages(session["session_id"])
    assert [message["message_id"] for message in messages] == [
        "msg_user",
        "msg_assistant",
    ]
    assert messages[1]["answer"] == "Hardness is supported by [Source 1]."
    assert messages[1]["used_evidence_ids"] == ["E01"]
    assert messages[1]["review_gate"] == "protocol_ready_findings"
    assert messages[1]["source_links"][0]["label"] == "Source 1"
    assert messages[1]["source_finding_refs"] == [
        {
            "finding_id": "finding-1",
            "finding_fingerprint": "finding.v1:abc",
            "protocol_source_fingerprint": "protocol-source.v1:def",
            "evidence_ref_ids": ["E01"],
        }
    ]
    context = repository.read_message_context("msg_assistant")
    assert context is not None
    assert context["session"]["focused_goal_id"] == "goal_lpbf"
    assert context["message"]["message_id"] == "msg_assistant"
    assert context["message"]["review_gate"] == "protocol_ready_findings"
    assert context["message"]["source_links"][0]["href"].endswith("evidence_id=E01")


def test_sqlite_goal_session_repository_replaces_message_history(tmp_path):
    repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    session = _session_record()
    repository.write_session(session)

    repository.write_messages(
        session["session_id"],
        [
            {
                "message_id": "msg_old",
                "session_id": session["session_id"],
                "role": "user",
                "content": "Old question",
                "created_at": "2026-05-10T00:00:01+00:00",
            }
        ],
    )
    repository.write_messages(
        session["session_id"],
        [
            {
                "message_id": "msg_new",
                "session_id": session["session_id"],
                "role": "user",
                "content": "New question",
                "created_at": "2026-05-10T00:00:03+00:00",
            }
        ],
    )

    assert repository.read_messages(session["session_id"]) == [
        {
            "message_id": "msg_new",
            "session_id": session["session_id"],
            "role": "user",
            "content": "New question",
            "created_at": "2026-05-10T00:00:03+00:00",
        }
    ]
