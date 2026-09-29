from __future__ import annotations

import hashlib
import json

from scripts.migrate_feedback_task_datasets import (
    MIGRATION_VERSION,
    build_plan_from_records,
    legacy_row_to_content,
    stable_id,
)


def _evidence() -> list[dict[str, str]]:
    return [{"document_title": "文献 B", "text": "图注记录预热温度为 200 C。"}]


def _messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": "比较文献 A、B 的预热条件。"}]


def test_legacy_sft_row_becomes_readable_revision_content() -> None:
    content, errors = legacy_row_to_content(
        "sft",
        {"messages": _messages(), "target": "文献 B 的图注记录 200 C。", "evidence": _evidence()},
    )

    assert errors == ()
    assert content is not None
    assert content["schema_version"] == "literature-sft.v1"
    assert content["context"] == _evidence()
    assert content["evidence"] == _evidence()
    assert content["target"] == "文献 B 的图注记录 200 C。"


def test_legacy_preference_row_never_carries_old_accept_as_human_label() -> None:
    content, errors = legacy_row_to_content(
        "preference",
        {
            "messages": _messages(),
            "chosen": "基于图注的回答。",
            "rejected": "原回答。",
            "evidence": _evidence(),
            "human_preference": "a",
        },
    )

    assert errors == ()
    assert content is not None
    assert content["response_a"] == "基于图注的回答。"
    assert content["response_b"] == "原回答。"
    assert content["suggested_preference"] is None
    assert content["human_preference"] is None


def test_legacy_evaluation_row_requires_criteria_and_preserves_reference() -> None:
    content, errors = legacy_row_to_content(
        "evaluation",
        {
            "messages": _messages(),
            "reference": "应说明图注中的 200 C。",
            "criteria": ["必须引用可读图注证据"],
            "evidence": _evidence(),
        },
    )

    assert errors == ()
    assert content is not None
    assert content["schema_version"] == "literature-evaluation.v1"
    assert content["reference"] == "应说明图注中的 200 C。"
    assert content["criteria"] == ["必须引用可读图注证据"]
    assert content["evaluation_mode"] == "reference"


def test_incomplete_legacy_row_enters_missing_input() -> None:
    content, errors = legacy_row_to_content(
        "sft",
        {"messages": _messages(), "target": "", "evidence": _evidence()},
    )

    assert content is None
    assert errors == ("legacy_target_missing",)


def test_plan_uses_legacy_ascii_digest_and_stable_new_identities() -> None:
    row = {
        "messages": _messages(),
        "target": "文献 B 的图注记录 200 C。",
        "evidence": _evidence(),
    }
    legacy_digest = hashlib.sha256(
        json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    snapshots = [
        {
            "dataset_id": "dataset_old_snapshot",
            "owner_id": "user-1",
            "collection_id": "collection-1",
            "dataset_type": "sft",
            "rows": [row],
            "provenance": {"items": [{"case_id": "case-1", "row_digest": legacy_digest}]},
            "created_at": "2026-09-28T00:00:00+00:00",
        }
    ]
    cases = [{"case_id": "case-1", "collection_id": "collection-1", "status": "accepted"}]

    first = build_plan_from_records(snapshots=snapshots, cases=cases, annotations=(), reviews=(), now="2026-09-29T00:00:00+00:00")
    second = build_plan_from_records(snapshots=snapshots, cases=cases, annotations=(), reviews=(), now="2026-09-29T00:00:00+00:00")

    assert first.items[0].content is not None
    assert first.items[0].status == "needs_confirmation"
    assert first.items[0].missing_reasons == ()
    assert first.items[0].dataset_id == second.items[0].dataset_id
    assert first.items[0].sample_id == second.items[0].sample_id
    assert first.items[0].revision_id == second.items[0].revision_id
    assert first.items[0].dataset_id != "dataset_old_snapshot"
    assert first.items[0].sample_id != "dataset_old_snapshot"
    assert first.summary()["legacy_snapshot_count"] == 1
    assert first.summary()["sample_candidates"] == 1
    assert first.run_id != second.run_id
    assert stable_id("fdset_mig", "dataset_old_snapshot") == first.datasets[0].dataset_id


def test_plan_deduplicates_same_snapshot_item() -> None:
    row = {"messages": _messages(), "target": "回答", "evidence": _evidence()}
    snapshot = {
        "dataset_id": "old",
        "owner_id": "user-1",
        "collection_id": "collection-1",
        "dataset_type": "sft",
        "rows": [row],
        "provenance": {"items": [{"case_id": "case-1"}, {"case_id": "case-1"}]},
    }
    plan = build_plan_from_records(
        snapshots=(snapshot,),
        cases=({"case_id": "case-1", "collection_id": "collection-1"},),
        annotations=(),
        reviews=(),
        now="2026-09-29T00:00:00+00:00",
    )

    assert len(plan.items) == 1
    assert plan.items[0].import_key.startswith(f"{MIGRATION_VERSION}:")
