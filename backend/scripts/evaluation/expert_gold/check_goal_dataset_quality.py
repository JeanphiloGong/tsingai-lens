#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check confirmed-goal research-understanding dataset samples for "
            "evaluation and fine-tuning readiness."
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
            "http://localhost:5173. When set, the script reads dataset payloads "
            "over HTTP instead of local application services. Set "
            "LENS_CHECK_EMAIL and LENS_CHECK_PASSWORD when login is required."
        ),
    )
    parser.add_argument(
        "--require-training-ready",
        action="store_true",
        help=(
            "Fail unless each checked goal has at least one training-ready "
            "sample. By default the script only requires reviewable active "
            "samples."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = check_goal_dataset_quality(
        collection_id=args.collection_id,
        goal_ids=tuple(args.goal_ids or DEFAULT_GOAL_IDS),
        api_base_url=args.api_base_url,
        require_training_ready=args.require_training_ready,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "fail":
        raise SystemExit(1)


def check_goal_dataset_quality(
    *,
    collection_id: str,
    goal_ids: tuple[str, ...] = DEFAULT_GOAL_IDS,
    api_base_url: str | None = None,
    require_training_ready: bool = False,
) -> dict[str, Any]:
    backend_root = str(DEFAULT_BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

    cookie = _api_login_cookie(api_base_url.rstrip("/")) if api_base_url else ""
    goal_summaries = []
    checks: list[dict[str, str]] = []
    for goal_id in goal_ids:
        dataset = (
            fetch_goal_dataset_from_api(
                api_base_url=api_base_url.rstrip("/"),
                collection_id=collection_id,
                goal_id=goal_id,
                cookie=cookie,
            )
            if api_base_url
            else _local_goal_dataset(collection_id, goal_id)
        )
        goal_summary = evaluate_goal_dataset_payload(
            dataset,
            require_training_ready=require_training_ready,
        )
        goal_summary["goal_id"] = goal_id
        goal_summaries.append(goal_summary)
        checks.extend(goal_summary["checks"])

    return {
        "status": "fail"
        if any(check["status"] == "fail" for check in checks)
        else "pass",
        "collection_id": collection_id,
        "goal_count": len(goal_ids),
        "goals": goal_summaries,
        "checks": checks,
    }


def _local_goal_dataset(collection_id: str, goal_id: str) -> dict[str, Any]:
    from application.evaluation import ResearchUnderstandingFeedbackService  # noqa: PLC0415

    return ResearchUnderstandingFeedbackService().export_dataset(
        collection_id=collection_id,
        scope_type="goal",
        scope_id=goal_id,
    )


def fetch_goal_dataset_from_api(
    *,
    api_base_url: str,
    collection_id: str,
    goal_id: str,
    cookie: str,
) -> dict[str, Any]:
    return _api_json_request(
        api_base_url,
        (
            f"/api/v1/collections/{collection_id}/research-understanding/dataset"
            f"?scope_type=goal&scope_id={goal_id}"
        ),
        cookie=cookie,
    )


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


def evaluate_goal_dataset_payload(
    dataset: dict[str, Any],
    *,
    require_training_ready: bool = False,
) -> dict[str, Any]:
    goal_id = str(dataset.get("scope_id") or "")
    quality = _mapping(dataset.get("quality_summary"))
    warning_counts = _mapping(quality.get("warning_counts"))
    items = _mapping_list(dataset.get("items"))
    training_ready_items = [
        item for item in items if _text(item.get("dataset_use_status")) == "training_ready"
    ]
    active_items = [
        item
        for item in items
        if _text(item.get("dataset_use_status")) in {"training_ready", "review_candidate"}
    ]
    checks = [
        _check(
            goal_id,
            "dataset exports at least one sample",
            bool(items),
            f"items={len(items)}",
        ),
        _check(
            goal_id,
            "dataset has at least one active sample",
            bool(active_items),
            (
                f"training_ready={len(training_ready_items)}; "
                f"review_candidate={len(active_items) - len(training_ready_items)}"
            ),
        ),
        _check(
            goal_id,
            "dataset has no unavailable or failed traces",
            not warning_counts.get("unavailable_trace")
            and not warning_counts.get("failed_trace"),
            (
                f"unavailable_trace={warning_counts.get('unavailable_trace', 0)}; "
                f"failed_trace={warning_counts.get('failed_trace', 0)}"
            ),
        ),
        _check(
            goal_id,
            "active samples include text input blocks",
            all(_has_text_input_block(item) for item in active_items),
            _sample_failure_detail(
                item for item in active_items if not _has_text_input_block(item)
            ),
        ),
        _check(
            goal_id,
            "active samples include traceable training evidence",
            all(_has_traceable_training_evidence(item) for item in active_items),
            _sample_failure_detail(
                item
                for item in active_items
                if not _has_traceable_training_evidence(item)
            ),
        ),
        _check(
            goal_id,
            "training-ready samples include expert target",
            all(_mapping(item.get("expert_target")) for item in training_ready_items),
            _sample_failure_detail(
                item
                for item in training_ready_items
                if not _mapping(item.get("expert_target"))
            ),
        ),
    ]
    if require_training_ready:
        checks.insert(
            2,
            _check(
                goal_id,
                "dataset has at least one training-ready sample",
                bool(training_ready_items),
                f"training_ready={len(training_ready_items)}",
            ),
        )
    return {
        "goal_id": goal_id,
        "item_count": len(items),
        "training_ready_count": len(training_ready_items),
        "review_candidate_count": len(
            [
                item
                for item in items
                if _text(item.get("dataset_use_status")) == "review_candidate"
            ]
        ),
        "by_error_category": dict(_mapping(quality.get("by_error_category"))),
        "by_trace_status": dict(_mapping(quality.get("by_trace_status"))),
        "warning_counts": dict(warning_counts),
        "checks": checks,
    }


def _has_text_input_block(item: dict[str, Any]) -> bool:
    return any(_text(block.get("text")) for block in _mapping_list(item.get("input_blocks")))


def _has_traceable_training_evidence(item: dict[str, Any]) -> bool:
    refs = _mapping_list(item.get("training_evidence_refs"))
    return bool(refs) and all(
        _text(ref.get("source_ref"))
        and _text(ref.get("href"))
        and (_text(ref.get("quote")) or _text(ref.get("source_text")))
        for ref in refs
    )


def _sample_failure_detail(items: Any) -> str:
    failures = [
        _text(item.get("sample_id")) or _text(item.get("finding_id")) or "unknown"
        for item in items
    ]
    if not failures:
        return "none"
    return "samples=" + json.dumps(failures[:10], ensure_ascii=False)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _check(goal_id: str, name: str, passed: bool, detail: str) -> dict[str, str]:
    return {
        "status": "pass" if passed else "fail",
        "goal_id": goal_id,
        "name": name,
        "detail": detail,
    }


if __name__ == "__main__":
    main()
