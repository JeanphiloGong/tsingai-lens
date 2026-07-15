#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlencode
from urllib import request as request_url
from urllib.error import HTTPError, URLError


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
PLAN_LIST_PATH = "/api/v1/collections/{collection_id}/goals/{goal_id}/experiment-plans"
PLAN_DETAIL_PATH = f"{PLAN_LIST_PATH}/{{plan_id}}"
GOAL_SESSION_PATH = "/api/v1/goal-sessions"
GOAL_SESSION_MESSAGE_PATH = f"{GOAL_SESSION_PATH}/{{session_id}}/messages"
PLAN_ROUTE_SPECS = (
    ("list experiment plans", PLAN_LIST_PATH, "get"),
    ("create experiment plan", PLAN_LIST_PATH, "post"),
    ("update experiment plan", PLAN_DETAIL_PATH, "patch"),
)
GOAL_COPILOT_ROUTE_SPECS = (
    ("create goal copilot session", GOAL_SESSION_PATH, "post"),
    ("post goal copilot message", GOAL_SESSION_MESSAGE_PATH, "post"),
)
RUNTIME_ROUTE_SPECS = (*GOAL_COPILOT_ROUTE_SPECS, *PLAN_ROUTE_SPECS)
BACKEND_PYTHON = "./.venv/bin/python"


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
        "--runtime-write-check",
        action="store_true",
        help=(
            "When --api-base-url is set, create and update a goal-scoped smoke "
            "experiment plan to verify saving works. This writes runtime data."
        ),
    )
    parser.add_argument(
        "--expert-satisfaction-gate",
        action="store_true",
        help=(
            "Final acceptance gate for the three-layer goal loop. Fails unless "
            "all checked goals are complete, all training exports are ready, "
            "and --api-base-url can pass the experiment-plan write smoke check."
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
        runtime_write_check=args.runtime_write_check,
        expert_satisfaction_gate=args.expert_satisfaction_gate,
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
    runtime_write_check: bool = False,
    expert_satisfaction_gate: bool = False,
    require_all_training_ready: bool = False,
    require_complete: bool = False,
) -> dict[str, Any]:
    effective_require_all_training_ready = (
        require_all_training_ready or expert_satisfaction_gate
    )
    effective_require_complete = require_complete or expert_satisfaction_gate
    effective_runtime_write_check = runtime_write_check or expert_satisfaction_gate
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
        require_training_ready=effective_require_all_training_ready,
    )
    runtime_goal_id = _runtime_write_goal_id(dataset, goal_ids)
    runtime_contract = _runtime_contract_layer(
        api_base_url,
        collection_id=collection_id,
        goal_id=runtime_goal_id,
        runtime_write_check=effective_runtime_write_check,
    )
    layers = {
        "expert_review": _expert_review_layer(findings),
        "dataset_accumulation": _dataset_layer(
            dataset,
            require_all_training_ready=effective_require_all_training_ready,
        ),
        "experiment_design": _experiment_layer(
            dataset,
            runtime_contract,
            require_all_goals_protocol_ready=expert_satisfaction_gate,
            require_runtime_write=effective_runtime_write_check,
        ),
    }
    goals = _goal_rollup(findings, dataset, collection_id=collection_id)
    completion = _completion_summary(goals)
    expert_satisfaction = _expert_satisfaction_summary(
        layers,
        completion["remaining_work"],
        expert_satisfaction_gate=expert_satisfaction_gate,
    )
    status = (
        "fail"
        if any(layer["status"] == "fail" for layer in layers.values())
        or (effective_require_complete and completion["status"] != "complete")
        else "pass"
    )
    return {
        "status": status,
        "completion_status": completion["status"],
        "collection_id": collection_id,
        "goal_count": len(goal_ids),
        "expert_satisfaction_gate": expert_satisfaction_gate,
        "require_all_training_ready": effective_require_all_training_ready,
        "require_complete": effective_require_complete,
        "layers": layers,
        "expert_satisfaction": expert_satisfaction,
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
    protocol_ready_goal_count = sum(
        1 for goal in goals if int(goal.get("protocol_ready_count") or 0) > 0
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
        "protocol_ready_goal_count": protocol_ready_goal_count,
        "requirement": (
            "Goals export active review samples; training-ready samples expose "
            "valid fine-tuning messages when expert labels exist."
        ),
    }


def _experiment_layer(
    dataset: dict[str, Any],
    runtime_contract: dict[str, Any],
    *,
    require_all_goals_protocol_ready: bool = False,
    require_runtime_write: bool = False,
) -> dict[str, Any]:
    goals = _mapping_list(dataset.get("goals"))
    eligible_goal_ids = [
        str(goal.get("goal_id"))
        for goal in goals
        if int(goal.get("protocol_ready_count") or 0) > 0
    ]
    runtime_status = _text(runtime_contract.get("status")) or "not_checked"
    runtime_ready = runtime_status == "pass" or (
        runtime_status == "not_checked" and not require_runtime_write
    )
    if require_runtime_write and not bool(runtime_contract.get("runtime_write_check")):
        runtime_ready = False
    protocol_ready = (
        len(eligible_goal_ids) == len(goals) and len(goals) > 0
        if require_all_goals_protocol_ready
        else bool(eligible_goal_ids)
    )
    return {
        "status": "pass" if protocol_ready and runtime_ready else "fail",
        "eligible_goal_ids": eligible_goal_ids,
        "requires_all_goals_protocol_ready": require_all_goals_protocol_ready,
        "requires_runtime_write": require_runtime_write,
        "runtime_write_scope": (
            "manual_experiment_plan_smoke"
            if require_runtime_write
            else "route_contract_only"
        ),
        "copilot_save_contract": {
            "review_gate": "protocol_ready_findings",
            "requires_source_message_id": True,
            "requires_collection_grounded_answer": True,
            "requires_auditable_source_links": True,
            "requires_used_evidence_ids": True,
            "requires_protocol_draft_structure": True,
        },
        "runtime_contract": runtime_contract,
        "requirement": (
            "At least one goal has training-ready findings with protocol design "
            "inputs that Goal Copilot can use for traceable protocol drafts, and "
            "the running API exposes goal-session and goal-scoped experiment-plan "
            "routes. Pass --runtime-write-check to verify manual plan persistence "
            "against a running API; service tests cover the stricter Goal Copilot "
            "source-message save contract."
        ),
    }


def _runtime_contract_layer(
    api_base_url: str | None,
    *,
    collection_id: str,
    goal_id: str,
    runtime_write_check: bool,
) -> dict[str, Any]:
    if not api_base_url:
        return {
            "status": "not_checked",
            "api_base_url": "",
            "goal_id": goal_id,
            "runtime_write_check": runtime_write_check,
            "checks": [],
            "requirement": "Pass --api-base-url to verify running API routes.",
        }
    base_url = api_base_url.rstrip("/")
    try:
        cookie = _api_login_cookie(base_url)
        paths = _fetch_openapi_paths(base_url, cookie=cookie)
    except RuntimeError as exc:
        return {
            "status": "fail",
            "api_base_url": base_url,
            "goal_id": goal_id,
            "checks": [],
            "error": str(exc),
            "requirement": "Running API exposes goal-session and experiment-plan routes.",
        }
    checks = _runtime_route_checks(paths)
    diagnostic = (
        _source_experiment_plan_route_diagnostic()
        if any(check["status"] == "fail" for check in checks)
        else {}
    )
    if runtime_write_check and all(check["status"] == "pass" for check in checks):
        checks.extend(
            _experiment_plan_write_checks(
                base_url,
                collection_id=collection_id,
                goal_id=goal_id,
                cookie=cookie,
            )
        )
    elif runtime_write_check:
        checks.append(
            {
                "name": "write smoke experiment plan",
                "path": PLAN_LIST_PATH,
                "method": "post/patch",
                "status": "skipped",
                "detail": "runtime route checks failed; smoke write was not attempted",
            }
        )
    result = {
        "status": "pass"
        if all(check["status"] in {"pass", "skipped"} for check in checks)
        and not any(check["status"] == "fail" for check in checks)
        else "fail",
        "api_base_url": base_url,
        "goal_id": goal_id,
        "runtime_write_check": runtime_write_check,
        "checks": checks,
        "requirement": (
            "Running API exposes goal-session and goal experiment-plan routes and, "
            "when --runtime-write-check is set, accepts create/update manual "
            "experiment-plan smoke writes."
        ),
    }
    if diagnostic:
        result["diagnostic"] = diagnostic
    return result


def _runtime_write_goal_id(dataset: dict[str, Any], goal_ids: tuple[str, ...]) -> str:
    for goal in _mapping_list(dataset.get("goals")):
        if int(goal.get("protocol_ready_count") or 0) <= 0:
            continue
        goal_id = _text(goal.get("goal_id"))
        if goal_id:
            return goal_id
    return goal_ids[0] if goal_ids else ""


def _experiment_plan_route_checks(paths: dict[str, Any]) -> list[dict[str, str]]:
    return _route_checks(paths, PLAN_ROUTE_SPECS)


def _runtime_route_checks(paths: dict[str, Any]) -> list[dict[str, str]]:
    return _route_checks(paths, RUNTIME_ROUTE_SPECS)


def _route_checks(
    paths: dict[str, Any],
    specs: tuple[tuple[str, str, str], ...],
) -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "path": path,
            "method": method,
            "status": "pass" if method in _mapping(paths.get(path)) else "fail",
        }
        for name, path, method in specs
    ]


def _source_experiment_plan_route_diagnostic() -> dict[str, Any]:
    try:
        source_paths = _local_openapi_paths()
    except Exception as exc:  # pragma: no cover - defensive runtime diagnostic
        return {
            "code": "source_route_check_unavailable",
            "detail": f"Could not inspect local source app routes: {exc}",
        }
    source_checks = _runtime_route_checks(source_paths)
    if all(check["status"] == "pass" for check in source_checks):
        return {
            "code": "running_api_not_current_backend",
            "detail": (
                "Local source app exposes goal-session and experiment-plan routes, "
                "but the running API does not. Restart or update the backend "
                "process, or point --api-base-url to the current Lens app."
            ),
            "source_checks": source_checks,
        }
    return {
        "code": "source_routes_missing",
        "detail": (
            "Local source app also does not expose all goal-session and "
            "experiment-plan routes; fix source route registration before "
            "checking runtime writes."
        ),
        "source_checks": source_checks,
    }


def _local_openapi_paths() -> dict[str, Any]:
    backend_root = str(DEFAULT_BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from main import app  # noqa: PLC0415

    return _mapping(app.openapi().get("paths"))


def _api_login_cookie(base_url: str) -> str:
    email = os.getenv("LENS_CHECK_EMAIL")
    password = os.getenv("LENS_CHECK_PASSWORD")
    if not email and not password:
        return ""
    if not email or not password:
        raise RuntimeError(
            "set both LENS_CHECK_EMAIL and LENS_CHECK_PASSWORD for API checks"
        )
    response = _api_json_request(
        base_url,
        "/api/v1/auth/login",
        method="POST",
        payload={"email": email, "password": password},
        include_headers=True,
    )
    headers = response["headers"]
    cookie = str(headers.get("Set-Cookie") or headers.get("set-cookie") or "")
    if not cookie:
        raise RuntimeError("POST /api/v1/auth/login did not return Set-Cookie")
    return cookie.split(";", 1)[0]


def _fetch_openapi_paths(api_base_url: str, *, cookie: str = "") -> dict[str, Any]:
    payload = _api_json_request(
        api_base_url,
        "/api/openapi.json",
        cookie=cookie,
    )
    paths = _mapping(payload.get("paths"))
    if not paths:
        raise RuntimeError("GET /api/openapi.json returned no paths")
    return paths


def _experiment_plan_write_checks(
    base_url: str,
    *,
    collection_id: str,
    goal_id: str,
    cookie: str,
) -> list[dict[str, Any]]:
    if not collection_id or not goal_id:
        return [
            {
                "name": "write smoke experiment plan",
                "path": "",
                "method": "post",
                "status": "fail",
                "detail": "collection_id and goal_id are required",
            }
        ]
    plan_list_path = f"/api/v1/collections/{collection_id}/goals/{goal_id}/experiment-plans"
    smoke_content = (
        "Hypothesis: Lens runtime smoke check validates editable experiment "
        "plan storage.\n\n"
        "Variable matrix: compare the current saved draft before and after the "
        "runtime smoke update.\n\n"
        "Measurements: confirm the API returns a plan id and updated status.\n\n"
        "Controls: run only against an operator-selected authenticated API.\n\n"
        "Risks and limits: this smoke draft is archived immediately after "
        "creation."
    )
    create_payload = {
        "title": "Lens runtime smoke protocol",
        "content": smoke_content,
        "source_links": [],
        "metadata": {"source": "expert_loop_runtime_smoke"},
    }
    try:
        created = _api_json_request(
            base_url,
            plan_list_path,
            method="POST",
            payload=create_payload,
            cookie=cookie,
        )
        plan_id = _text(created.get("plan_id"))
        if not plan_id:
            raise RuntimeError("POST experiment plan returned no plan_id")
        _api_json_request(
            base_url,
            f"{plan_list_path}/{plan_id}",
            method="PATCH",
            payload={
                "title": "Lens runtime smoke protocol",
                "content": smoke_content
                + "\n\nRisks and limits: archived after write verification.",
                "status": "archived",
            },
            cookie=cookie,
        )
    except RuntimeError as exc:
        return [
            {
                "name": "write smoke experiment plan",
                "path": plan_list_path,
                "method": "post/patch",
                "status": "fail",
                "detail": str(exc),
            }
        ]
    return [
        {
            "name": "write smoke experiment plan",
            "path": plan_list_path,
            "method": "post/patch",
            "status": "pass",
            "detail": "created and archived smoke plan",
        }
    ]


def _api_json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    cookie: str = "",
    include_headers: bool = False,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    request = request_url.Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with request_url.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
            if include_headers:
                return {"payload": data, "headers": response.headers}
            return data
    except HTTPError as exc:
        raise RuntimeError(
            f"{method} {path} failed: {exc.code} {exc.reason}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc


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
                "next_review_action": (
                    dict(_mapping(dataset_goal.get("next_review_action")))
                    if int(dataset_goal.get("review_candidate_count") or 0) > 0
                    else {}
                ),
                "primary_finding_count": int(goal.get("primary_finding_count") or 0),
                "direct_evidence_count": int(goal.get("direct_evidence_count") or 0),
                "dataset_item_count": int(dataset_goal.get("item_count") or 0),
                "training_ready_count": int(dataset_goal.get("training_ready_count") or 0),
                "training_message_ready_count": int(
                    dataset_goal.get("training_message_ready_count") or 0
                ),
                "protocol_ready_count": int(dataset_goal.get("protocol_ready_count") or 0),
                "review_candidate_count": int(dataset_goal.get("review_candidate_count") or 0),
                "by_error_category": dict(_mapping(dataset_goal.get("by_error_category"))),
                "by_review_reason": dict(_mapping(dataset_goal.get("by_review_reason"))),
                "by_system_warning": dict(_mapping(dataset_goal.get("by_system_warning"))),
                "by_review_candidate_reason": dict(
                    _mapping(dataset_goal.get("by_review_candidate_reason"))
                ),
                "by_review_candidate_warning": dict(
                    _mapping(dataset_goal.get("by_review_candidate_warning"))
                ),
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
    goals_without_protocol_ready = [
        str(goal.get("goal_id"))
        for goal in goals
        if int(goal.get("protocol_ready_count") or 0) == 0
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
            "protocol_ready_count": int(goal.get("protocol_ready_count") or 0),
            "next_action": _pending_goal_action(goal),
            "next_review_action": dict(_mapping(goal.get("next_review_action"))),
            "href": _pending_goal_href(goal),
            "next_review_finding_id": _text(goal.get("next_review_finding_id")),
        }
        for goal in goals
        if (
            int(goal.get("review_candidate_count") or 0) > 0
            or int(goal.get("training_ready_count") or 0) == 0
            or int(goal.get("training_message_ready_count") or 0) == 0
            or int(goal.get("protocol_ready_count") or 0) == 0
        )
    ]
    protocol_ready_goals = [
        {
            "goal_id": str(goal.get("goal_id")),
            "question": _text(goal.get("question")),
            "training_ready_count": int(goal.get("training_ready_count") or 0),
            "training_message_ready_count": int(
                goal.get("training_message_ready_count") or 0
            ),
            "protocol_ready_count": int(goal.get("protocol_ready_count") or 0),
            "assistant_url": _goal_assistant_url(
                str(goal.get("collection_id") or ""),
                str(goal.get("goal_id") or ""),
            ),
            "training_ready_url": _text(goal.get("training_ready_url")),
        }
        for goal in goals
        if int(goal.get("protocol_ready_count") or 0) > 0
    ]
    review_candidate_count = sum(int(goal.get("review_candidate_count") or 0) for goal in goals)
    by_error_category: dict[str, int] = {}
    by_review_reason: dict[str, int] = {}
    by_system_warning: dict[str, int] = {}
    for goal in goals:
        for category, count in _mapping(goal.get("by_error_category")).items():
            if category in {"none", "unreviewed"}:
                continue
            by_error_category[str(category)] = by_error_category.get(str(category), 0) + int(
                count or 0
            )
        review_reason_source = _review_risk_source(
            goal,
            candidate_key="by_review_candidate_reason",
            all_key="by_review_reason",
        )
        system_warning_source = _review_risk_source(
            goal,
            candidate_key="by_review_candidate_warning",
            all_key="by_system_warning",
        )
        for reason, count in review_reason_source.items():
            by_review_reason[str(reason)] = by_review_reason.get(str(reason), 0) + int(
                count or 0
            )
        for warning, count in system_warning_source.items():
            by_system_warning[str(warning)] = by_system_warning.get(str(warning), 0) + int(
                count or 0
            )
    completed = (
        total_goals > 0
        and not goals_without_training_ready
        and not goals_without_training_messages
        and not goals_without_protocol_ready
        and review_candidate_count == 0
    )
    return {
        "status": "complete" if completed else "incomplete",
        "remaining_work": {
            "review_candidate_count": review_candidate_count,
            "goals_without_training_ready": goals_without_training_ready,
            "goals_without_training_messages": goals_without_training_messages,
            "goals_without_protocol_ready": goals_without_protocol_ready,
            "pending_goals": pending_goals,
            "protocol_ready_goals": protocol_ready_goals,
            "by_error_category": dict(
                sorted(
                    by_error_category.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
            "by_review_reason": dict(
                sorted(
                    by_review_reason.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
            "by_system_warning": dict(
                sorted(
                    by_system_warning.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
        },
    }


def _expert_satisfaction_summary(
    layers: dict[str, dict[str, Any]],
    remaining_work: dict[str, Any],
    *,
    expert_satisfaction_gate: bool,
) -> dict[str, Any]:
    review_candidates = int(remaining_work.get("review_candidate_count") or 0)
    missing_training = len(_list(remaining_work.get("goals_without_training_ready")))
    missing_messages = len(_list(remaining_work.get("goals_without_training_messages")))
    missing_protocol = len(_list(remaining_work.get("goals_without_protocol_ready")))
    criteria = [
        _criterion(
            "expert_review",
            "Expert review usable",
            "Findings are clear, evidence is jumpable, and rows can be accepted, rejected, or corrected.",
            _mapping(layers.get("expert_review")).get("status") == "pass",
            (
                "Review candidates are available for human accept, reject, or correct decisions."
                if review_candidates
                else "Expert review queue is clear."
            ),
        ),
        _criterion(
            "dataset_accumulation",
            "Dataset accumulation usable",
            "Human labels enter training_ready and exportable messages for every checked goal.",
            _mapping(layers.get("dataset_accumulation")).get("status") == "pass"
            and missing_training == 0
            and missing_messages == 0,
            (
                "Import human-confirmed accept, reject, or correct decisions, then rerun dataset export checks."
                if missing_training or missing_messages
                else "Training-ready dataset exports are available."
            ),
        ),
        _criterion(
            "experiment_design",
            "Experiment design usable",
            "Goal Copilot can consume curated Findings and save traceable protocol drafts.",
            _mapping(layers.get("experiment_design")).get("status") == "pass"
            and missing_protocol == 0
            and (not expert_satisfaction_gate or _runtime_write_verified(layers)),
            _experiment_design_next_step(
                layers,
                missing_protocol=missing_protocol,
                expert_satisfaction_gate=expert_satisfaction_gate,
            ),
        ),
    ]
    return {
        "status": "satisfied" if all(item["satisfied"] for item in criteria) else "blocked",
        "criteria": criteria,
    }


def _criterion(
    key: str,
    title: str,
    requirement: str,
    satisfied: bool,
    next_step: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "requirement": requirement,
        "satisfied": satisfied,
        "status": "satisfied" if satisfied else "blocked",
        "next_step": next_step,
    }


def _runtime_write_verified(layers: dict[str, dict[str, Any]]) -> bool:
    experiment = _mapping(layers.get("experiment_design"))
    runtime_contract = _mapping(experiment.get("runtime_contract"))
    return (
        bool(experiment.get("requires_runtime_write"))
        and bool(runtime_contract.get("runtime_write_check"))
        and _text(runtime_contract.get("status")) == "pass"
    )


def _experiment_design_next_step(
    layers: dict[str, dict[str, Any]],
    *,
    missing_protocol: int,
    expert_satisfaction_gate: bool,
) -> str:
    if missing_protocol:
        return "Review or correct findings until every checked goal has protocol-ready inputs."
    if expert_satisfaction_gate and not _runtime_write_verified(layers):
        return "Run the expert gate with --api-base-url against the current backend so experiment-plan saving is smoke-tested."
    return "Protocol-ready curated Findings and experiment-plan saving are available."


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _review_risk_source(
    goal: dict[str, Any],
    *,
    candidate_key: str,
    all_key: str,
) -> dict[str, Any]:
    if int(goal.get("review_candidate_count") or 0) <= 0:
        return {}
    candidate_counts = _mapping(goal.get(candidate_key))
    if candidate_counts or candidate_key in goal:
        return candidate_counts
    return _mapping(goal.get(all_key))


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
        if key == "experiment_design":
            write_scope = _text(layer_mapping.get("runtime_write_scope"))
            if write_scope:
                lines.append(f"  runtime write scope: {write_scope}")
            copilot_contract = _mapping(layer_mapping.get("copilot_save_contract"))
            review_gate = _text(copilot_contract.get("review_gate"))
            if review_gate:
                lines.append(f"  copilot save contract: review_gate={review_gate}")
            runtime_contract = _mapping(layer_mapping.get("runtime_contract"))
            runtime_status = _text(runtime_contract.get("status"))
            if runtime_status and runtime_status != "not_checked":
                lines.append(f"  runtime contract: {runtime_status}")
                runtime_error = _text(runtime_contract.get("error"))
                if runtime_error:
                    lines.append(f"  runtime error: {runtime_error}")
                diagnostic = _mapping(runtime_contract.get("diagnostic"))
                if diagnostic:
                    lines.append(
                        "  runtime diagnostic: "
                        f"{_text(diagnostic.get('code'))}: {_text(diagnostic.get('detail'))}"
                    )
                failed_checks = [
                    check
                    for check in _mapping_list(runtime_contract.get("checks"))
                    if _text(check.get("status")) in {"fail", "skipped"}
                ]
                for check in failed_checks:
                    detail = _text(check.get("detail"))
                    if detail:
                        label = (
                            "runtime check skipped"
                            if _text(check.get("status")) == "skipped"
                            else "runtime check failed"
                        )
                        lines.append(f"  {label}: {_text(check.get('name'))}: {detail}")
                    else:
                        lines.append(
                            "  missing route: "
                            f"{_text(check.get('method')).upper()} {_text(check.get('path'))}"
                        )
    lines.extend(
        [
            "",
            "Remaining work:",
            f"- review candidates: {int(remaining_work.get('review_candidate_count') or 0)}",
            f"- goals without training-ready samples: {len(_list(remaining_work.get('goals_without_training_ready')))}",
            f"- goals without training messages: {len(_list(remaining_work.get('goals_without_training_messages')))}",
            f"- goals without protocol-ready inputs: {len(_list(remaining_work.get('goals_without_protocol_ready')))}",
        ]
    )
    error_categories = _mapping(remaining_work.get("by_error_category"))
    if error_categories:
        lines.append("- error categories:")
        for category, count in error_categories.items():
            lines.append(f"  - {category}: {count}")
    review_reasons = _mapping(remaining_work.get("by_review_reason"))
    if review_reasons:
        lines.append("- review priorities:")
        for reason, count in review_reasons.items():
            lines.append(f"  - {reason}: {count}")
    system_warnings = _mapping(remaining_work.get("by_system_warning"))
    if system_warnings:
        lines.append("- system warnings:")
        for warning, count in system_warnings.items():
            lines.append(f"  - {warning}: {count}")
    diagnosis = _gate_diagnosis(remaining_work)
    if diagnosis:
        lines.extend(["", "Gate diagnosis:"])
        lines.extend(f"- {item}" for item in diagnosis)
    expert_satisfaction = _mapping(summary.get("expert_satisfaction"))
    criteria = _mapping_list(expert_satisfaction.get("criteria"))
    if criteria:
        lines.extend(
            [
                "",
                f"Expert satisfaction: {_text(expert_satisfaction.get('status'))}",
            ]
        )
        for item in criteria:
            lines.extend(
                [
                    f"- {_text(item.get('title'))}: {_text(item.get('status'))}",
                    f"  requirement: {_text(item.get('requirement'))}",
                    f"  next: {_text(item.get('next_step'))}",
                ]
            )
    pending_goals = _mapping_list(remaining_work.get("pending_goals"))
    protocol_ready_goals = _mapping_list(remaining_work.get("protocol_ready_goals"))
    if protocol_ready_goals:
        lines.extend(["", "Protocol-ready goals:"])
        for index, goal in enumerate(protocol_ready_goals, start=1):
            lines.extend(
                [
                    f"{index}. {_text(goal.get('question')) or _text(goal.get('goal_id'))}",
                    (
                        "   counts: "
                        f"training_ready={int(goal.get('training_ready_count') or 0)}, "
                        f"messages={int(goal.get('training_message_ready_count') or 0)}, "
                        f"protocol={int(goal.get('protocol_ready_count') or 0)}"
                    ),
                    f"   ai chat: {_text(goal.get('assistant_url'))}",
                    f"   review inputs: {_text(goal.get('training_ready_url'))}",
                ]
            )
    if pending_goals:
        lines.extend(["", "Pending goals:"])
        for index, goal in enumerate(pending_goals, start=1):
            lines.extend(
                [
                    f"{index}. {_text(goal.get('question')) or _text(goal.get('goal_id'))}",
                    f"   action: {_text(goal.get('next_action'))}",
                ]
            )
            review_action_label = _text(
                _mapping(goal.get("next_review_action")).get("label")
            )
            if review_action_label:
                lines.append(f"   review action: {review_action_label}")
            lines.extend(
                [
                    (
                        "   counts: "
                        f"review={int(goal.get('review_candidate_count') or 0)}, "
                        f"training_ready={int(goal.get('training_ready_count') or 0)}, "
                        f"messages={int(goal.get('training_message_ready_count') or 0)}, "
                        f"protocol={int(goal.get('protocol_ready_count') or 0)}"
                    ),
                    f"   open: {_text(goal.get('href'))}",
                ]
            )
    next_commands = _next_step_commands(summary)
    if next_commands:
        lines.extend(["", "Next commands:"])
        lines.extend(f"- {command}" for command in next_commands)
    return "\n".join(lines)


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _gate_diagnosis(remaining_work: dict[str, Any]) -> list[str]:
    review_candidates = int(remaining_work.get("review_candidate_count") or 0)
    missing_training = len(_list(remaining_work.get("goals_without_training_ready")))
    missing_messages = len(_list(remaining_work.get("goals_without_training_messages")))
    missing_protocol = len(_list(remaining_work.get("goals_without_protocol_ready")))
    if not any((review_candidates, missing_training, missing_messages, missing_protocol)):
        return []
    if review_candidates:
        return [
            (
                f"{review_candidates} finding(s) still need expert accept, reject, "
                "or correct decisions before the dataset can become training-ready."
            ),
            (
                "Do not rerun goal analysis for this state; export the decision "
                "workspace or browser decision board, fill expert-decision-board.tsv "
                "or the JSONL template, then dry-run and import human-confirmed "
                "decisions. The browser import can accept a filled TSV board directly."
            ),
        ]
    if missing_training:
        return [
            (
                f"{missing_training} goal(s) have no training-ready finding after review. "
                "Check whether every remaining finding was rejected or corrected without usable evidence."
            )
        ]
    if missing_messages:
        return [
            (
                f"{missing_messages} goal(s) have training-ready findings but no exportable "
                "training messages. Inspect training-ready samples for missing target fields or evidence text."
            )
        ]
    return [
        (
            f"{missing_protocol} goal(s) have training messages but no protocol-ready "
            "inputs. Inspect variables, outcomes, direction or scope, and evidence refs."
        )
    ]


def _next_step_commands(summary: dict[str, Any]) -> list[str]:
    if _text(summary.get("completion_status")) == "complete":
        return []
    collection_id = _text(summary.get("collection_id")) or DEFAULT_COLLECTION_ID
    review_href = _first_pending_goal_href(summary)
    commands = [
        (
            "Browser: open the goal review page"
            + (f" at {review_href}" if review_href else "")
        ),
        (
            "Browser: download Decision board TSV, fill expert_action/issue_type/"
            "corrected_* columns, paste it into Reviewed decisions, then run Dry run "
            "and Import decisions."
        ),
        "Offline CLI:",
        (
            f"{BACKEND_PYTHON} scripts/evaluation/expert_gold/prepare_goal_review_workspace.py "
            f"--collection-id {collection_id}"
        ),
        (
            f"{BACKEND_PYTHON} scripts/evaluation/expert_gold/merge_expert_decision_board.py "
            "<workspace>/reviewed-findings.template.jsonl "
            "<workspace>/expert-decision-board.tsv "
            "--output-path <workspace>/reviewed-findings.from-board.jsonl"
        ),
        (
            f"{BACKEND_PYTHON} scripts/evaluation/expert_gold/import_goal_review_decisions.py "
            "<workspace>/reviewed-findings.from-board.jsonl "
            "--reviewer <human-reviewer> --dry-run --fail-on-warnings --format text"
        ),
        (
            f"{BACKEND_PYTHON} scripts/evaluation/expert_gold/import_goal_review_decisions.py "
            "<workspace>/reviewed-findings.from-board.jsonl "
            "--reviewer <human-reviewer> --format text"
        ),
    ]
    commands.extend(_training_export_commands(collection_id))
    return commands


def _training_export_commands(collection_id: str) -> list[str]:
    return [
        (
            f"{BACKEND_PYTHON} scripts/evaluation/expert_gold/check_goal_dataset_quality.py "
            f"--collection-id {collection_id} --format messages-jsonl "
            "--require-training-ready"
        ),
        (
            f"{BACKEND_PYTHON} scripts/evaluation/expert_gold/check_goal_dataset_quality.py "
            f"--collection-id {collection_id} --format training-jsonl "
            "--require-training-ready"
        ),
    ]


def _first_pending_goal_href(summary: dict[str, Any]) -> str:
    remaining = _mapping(summary.get("remaining_work"))
    for goal in _mapping_list(remaining.get("pending_goals")):
        href = _text(goal.get("href"))
        if href:
            return href
    return ""


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


def _goal_assistant_url(collection_id: str, goal_id: str) -> str:
    if not collection_id or not goal_id:
        return ""
    return f"/collections/{collection_id}/assistant?goal_id={goal_id}"


def _pending_goal_action(goal: dict[str, Any]) -> str:
    if int(goal.get("review_candidate_count") or 0) > 0:
        return "review_candidates"
    if int(goal.get("training_ready_count") or 0) == 0:
        return "accept_reject_or_correct_findings"
    if int(goal.get("training_message_ready_count") or 0) == 0:
        return "inspect_training_messages"
    if int(goal.get("protocol_ready_count") or 0) == 0:
        return "inspect_protocol_inputs"
    return "open_goal"


def _pending_goal_href(goal: dict[str, Any]) -> str:
    if _pending_goal_action(goal) in {
        "inspect_training_messages",
        "inspect_protocol_inputs",
    }:
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
