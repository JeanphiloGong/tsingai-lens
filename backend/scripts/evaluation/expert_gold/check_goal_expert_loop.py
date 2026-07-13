#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlencode


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COLLECTION_ID = "col_0cc5013fdb3c"
DEFAULT_GOAL_IDS = (
    "goal_0914003ad572",
    "goal_1a7a26d850b9",
    "goal_399171646354",
    "goal_061c9c049e69",
    "goal_6bf7d2c1030e",
    "goal_3037e425673a",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check the three-layer Lens goal loop: expert findings review, "
            "dataset accumulation, and experiment-planning readiness."
        )
    )
    parser.add_argument(
        "--collection-id",
        default=DEFAULT_COLLECTION_ID,
        help="Collection id to check.",
    )
    parser.add_argument(
        "--goal-id",
        action="append",
        dest="goal_ids",
        help="Goal id to check. May repeat. Defaults to the local 6-goal 316L set.",
    )
    parser.add_argument(
        "--api-base-url",
        help=(
            "Optional running Lens API or frontend origin to check, for example "
            "http://localhost:5173. Set LENS_CHECK_EMAIL and "
            "LENS_CHECK_PASSWORD when login is required."
        ),
    )
    parser.add_argument(
        "--require-all-training-ready",
        action="store_true",
        help=(
            "Fail unless every checked goal has at least one training-ready "
            "sample with valid fine-tuning messages."
        ),
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help=(
            "Fail unless every checked goal is training/message-ready and no "
            "review candidates remain."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format. JSON is stable for automation; text is for human review loops.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = check_goal_expert_loop(
        collection_id=args.collection_id,
        goal_ids=tuple(args.goal_ids or DEFAULT_GOAL_IDS),
        api_base_url=args.api_base_url,
        require_all_training_ready=args.require_all_training_ready,
        require_complete=args.require_complete,
    )
    if args.format == "text":
        print(render_text_summary(summary))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "fail":
        raise SystemExit(1)


def check_goal_expert_loop(
    *,
    collection_id: str,
    goal_ids: tuple[str, ...] = DEFAULT_GOAL_IDS,
    api_base_url: str | None = None,
    require_all_training_ready: bool = False,
    require_complete: bool = False,
) -> dict[str, Any]:
    findings_module = _load_sibling_module(
        "check_goal_findings_projection.py",
        "check_goal_findings_projection",
    )
    dataset_module = _load_sibling_module(
        "check_goal_dataset_quality.py",
        "check_goal_dataset_quality",
    )
    findings = findings_module.check_goal_findings_projection(
        collection_id=collection_id,
        goal_ids=goal_ids,
        api_base_url=api_base_url,
    )
    dataset = dataset_module.check_goal_dataset_quality(
        collection_id=collection_id,
        goal_ids=goal_ids,
        api_base_url=api_base_url,
        require_training_ready=require_all_training_ready,
    )
    layers = {
        "expert_review": _expert_review_layer(findings),
        "dataset_accumulation": _dataset_layer(
            dataset,
            require_all_training_ready=require_all_training_ready,
        ),
        "experiment_design": _experiment_layer(dataset),
    }
    goals = _goal_rollup(findings, dataset, collection_id=collection_id)
    completion = _completion_summary(goals)
    status = (
        "fail"
        if any(layer["status"] == "fail" for layer in layers.values())
        or (require_complete and completion["status"] != "complete")
        else "pass"
    )
    return {
        "status": status,
        "completion_status": completion["status"],
        "collection_id": collection_id,
        "goal_count": len(goal_ids),
        "require_all_training_ready": require_all_training_ready,
        "require_complete": require_complete,
        "layers": layers,
        "remaining_work": completion["remaining_work"],
        "findings_status": findings["status"],
        "dataset_status": dataset["status"],
        "goals": goals,
    }


def _load_sibling_module(filename: str, module_name: str):
    script_path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _expert_review_layer(findings: dict[str, Any]) -> dict[str, Any]:
    goals = _mapping_list(findings.get("goals"))
    primary_count = sum(int(goal.get("primary_finding_count") or 0) for goal in goals)
    direct_evidence_count = sum(int(goal.get("direct_evidence_count") or 0) for goal in goals)
    return {
        "status": "pass" if findings.get("status") == "pass" else "fail",
        "primary_finding_count": primary_count,
        "direct_evidence_count": direct_evidence_count,
        "requirement": (
            "Findings are expert-readable, direct evidence resolves, and source "
            "quotes/hrefs are present."
        ),
    }


def _dataset_layer(
    dataset: dict[str, Any],
    *,
    require_all_training_ready: bool,
) -> dict[str, Any]:
    goals = _mapping_list(dataset.get("goals"))
    active_goal_count = sum(1 for goal in goals if int(goal.get("item_count") or 0) > 0)
    training_ready_goal_count = sum(
        1 for goal in goals if int(goal.get("training_ready_count") or 0) > 0
    )
    message_ready_goal_count = sum(
        1 for goal in goals if int(goal.get("training_message_ready_count") or 0) > 0
    )
    minimum_training_ready_met = (
        message_ready_goal_count == len(goals)
        if require_all_training_ready
        else message_ready_goal_count > 0
    )
    status = "pass" if dataset.get("status") == "pass" and minimum_training_ready_met else "fail"
    return {
        "status": status,
        "active_goal_count": active_goal_count,
        "training_ready_goal_count": training_ready_goal_count,
        "training_message_ready_goal_count": message_ready_goal_count,
        "requirement": (
            "Goals export active review samples; training-ready samples expose "
            "valid fine-tuning messages when expert labels exist."
        ),
    }


def _experiment_layer(dataset: dict[str, Any]) -> dict[str, Any]:
    goals = _mapping_list(dataset.get("goals"))
    eligible_goal_ids = [
        str(goal.get("goal_id"))
        for goal in goals
        if int(goal.get("training_message_ready_count") or 0) > 0
    ]
    return {
        "status": "pass" if eligible_goal_ids else "fail",
        "eligible_goal_ids": eligible_goal_ids,
        "requirement": (
            "At least one goal has training-ready, message-ready findings that "
            "Goal Copilot can use for traceable protocol drafts."
        ),
    }


def _goal_rollup(
    findings: dict[str, Any],
    dataset: dict[str, Any],
    *,
    collection_id: str,
) -> list[dict[str, Any]]:
    dataset_by_goal = {
        str(goal.get("goal_id")): goal for goal in _mapping_list(dataset.get("goals"))
    }
    rows = []
    for goal in _mapping_list(findings.get("goals")):
        goal_id = str(goal.get("goal_id"))
        dataset_goal = dataset_by_goal.get(goal_id, {})
        rows.append(
            {
                "goal_id": goal_id,
                "collection_id": collection_id,
                "question": _text(goal.get("question")),
                "review_url": _goal_review_url(collection_id, goal_id),
                "training_ready_url": _goal_training_ready_url(collection_id, goal_id),
                "next_review_finding_id": (
                    _text(dataset_goal.get("next_review_finding_id"))
                    if int(dataset_goal.get("review_candidate_count") or 0) > 0
                    else ""
                ),
                "primary_finding_count": int(goal.get("primary_finding_count") or 0),
                "direct_evidence_count": int(goal.get("direct_evidence_count") or 0),
                "dataset_item_count": int(dataset_goal.get("item_count") or 0),
                "training_ready_count": int(dataset_goal.get("training_ready_count") or 0),
                "training_message_ready_count": int(
                    dataset_goal.get("training_message_ready_count") or 0
                ),
                "review_candidate_count": int(dataset_goal.get("review_candidate_count") or 0),
                "by_error_category": dict(_mapping(dataset_goal.get("by_error_category"))),
            }
        )
    return rows


def _completion_summary(goals: list[dict[str, Any]]) -> dict[str, Any]:
    total_goals = len(goals)
    goals_without_training_ready = [
        str(goal.get("goal_id"))
        for goal in goals
        if int(goal.get("training_ready_count") or 0) == 0
    ]
    goals_without_training_messages = [
        str(goal.get("goal_id"))
        for goal in goals
        if int(goal.get("training_message_ready_count") or 0) == 0
    ]
    pending_goals = [
        {
            "goal_id": str(goal.get("goal_id")),
            "question": _text(goal.get("question")),
            "review_candidate_count": int(goal.get("review_candidate_count") or 0),
            "training_ready_count": int(goal.get("training_ready_count") or 0),
            "training_message_ready_count": int(
                goal.get("training_message_ready_count") or 0
            ),
            "next_action": _pending_goal_action(goal),
            "href": _pending_goal_href(goal),
            "next_review_finding_id": _text(goal.get("next_review_finding_id")),
        }
        for goal in goals
        if (
            int(goal.get("review_candidate_count") or 0) > 0
            or int(goal.get("training_ready_count") or 0) == 0
            or int(goal.get("training_message_ready_count") or 0) == 0
        )
    ]
    review_candidate_count = sum(int(goal.get("review_candidate_count") or 0) for goal in goals)
    by_error_category: dict[str, int] = {}
    for goal in goals:
        for category, count in _mapping(goal.get("by_error_category")).items():
            if category in {"none", "unreviewed"}:
                continue
            by_error_category[str(category)] = by_error_category.get(str(category), 0) + int(
                count or 0
            )
    completed = (
        total_goals > 0
        and not goals_without_training_ready
        and not goals_without_training_messages
        and review_candidate_count == 0
    )
    return {
        "status": "complete" if completed else "incomplete",
        "remaining_work": {
            "review_candidate_count": review_candidate_count,
            "goals_without_training_ready": goals_without_training_ready,
            "goals_without_training_messages": goals_without_training_messages,
            "pending_goals": pending_goals,
            "by_error_category": dict(
                sorted(
                    by_error_category.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
        },
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def render_text_summary(summary: dict[str, Any]) -> str:
    remaining_work = _mapping(summary.get("remaining_work"))
    lines = [
        f"Lens expert loop: {summary.get('status')} ({summary.get('completion_status')})",
        f"Collection: {summary.get('collection_id')}",
        "",
        "Layers:",
    ]
    for key, layer in _mapping(summary.get("layers")).items():
        layer_mapping = _mapping(layer)
        lines.append(f"- {key}: {layer_mapping.get('status')}")
    lines.extend(
        [
            "",
            "Remaining work:",
            f"- review candidates: {int(remaining_work.get('review_candidate_count') or 0)}",
            f"- goals without training-ready samples: {len(_list(remaining_work.get('goals_without_training_ready')))}",
            f"- goals without training messages: {len(_list(remaining_work.get('goals_without_training_messages')))}",
        ]
    )
    error_categories = _mapping(remaining_work.get("by_error_category"))
    if error_categories:
        lines.append("- error categories:")
        for category, count in error_categories.items():
            lines.append(f"  - {category}: {count}")
    pending_goals = _mapping_list(remaining_work.get("pending_goals"))
    if pending_goals:
        lines.extend(["", "Pending goals:"])
        for index, goal in enumerate(pending_goals, start=1):
            lines.extend(
                [
                    f"{index}. {_text(goal.get('question')) or _text(goal.get('goal_id'))}",
                    f"   action: {_text(goal.get('next_action'))}",
                    (
                        "   counts: "
                        f"review={int(goal.get('review_candidate_count') or 0)}, "
                        f"training_ready={int(goal.get('training_ready_count') or 0)}, "
                        f"messages={int(goal.get('training_message_ready_count') or 0)}"
                    ),
                    f"   open: {_text(goal.get('href'))}",
                ]
            )
    return "\n".join(lines)


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _goal_review_url(
    collection_id: str,
    goal_id: str,
    *,
    finding_id: str = "",
) -> str:
    params = {"review": "queue"}
    if finding_id:
        params["finding_id"] = finding_id
    return f"/collections/{collection_id}/goals/{goal_id}?{urlencode(params)}"


def _goal_training_ready_url(collection_id: str, goal_id: str) -> str:
    return f"/collections/{collection_id}/goals/{goal_id}?review=training_ready"


def _pending_goal_action(goal: dict[str, Any]) -> str:
    if int(goal.get("review_candidate_count") or 0) > 0:
        return "review_candidates"
    if int(goal.get("training_ready_count") or 0) == 0:
        return "accept_reject_or_correct_findings"
    if int(goal.get("training_message_ready_count") or 0) == 0:
        return "inspect_training_messages"
    return "open_goal"


def _pending_goal_href(goal: dict[str, Any]) -> str:
    if _pending_goal_action(goal) == "inspect_training_messages":
        return _text(goal.get("training_ready_url"))
    finding_id = _text(goal.get("next_review_finding_id"))
    if finding_id:
        return _goal_review_url(
            _text(goal.get("collection_id")),
            _text(goal.get("goal_id")),
            finding_id=finding_id,
        )
    return _text(goal.get("review_url"))


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


if __name__ == "__main__":
    main()
