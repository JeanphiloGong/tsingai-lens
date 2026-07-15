#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
from decimal import Decimal, InvalidOperation
import io
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib import request as request_url
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse


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

EXPERT_USE_STATUSES = {
    "paper_level_finding",
    "scoped_expert_finding",
    "review_candidate",
    "evidence_repair_needed",
}
GENERALIZATION_STATUSES = {
    "paper_level_only",
    "cross_paper_candidate",
    "scoped_cross_paper",
    "evidence_repair_needed",
    "conflict_review_needed",
}

GOAL_EXPERT_EXPECTATIONS: dict[str, dict[str, list[list[str]]]] = {
    "goal_0914003ad572": {
        "finding_terms": [
            ["preheating", "build platform"],
            ["ductility"],
            ["150", "°c"],
            ["14"],
            ["the authors attributed"],
        ],
        "evidence_terms": [
            ["preheating", "build platform"],
            ["ductility"],
            ["150", "°c"],
            ["14"],
            ["gnd"],
        ],
    },
    "goal_1a7a26d850b9": {
        "finding_terms": [
            ["heat treatment"],
            ["density"],
            ["microstructure"],
            ["1100"],
            ["0.5"],
            ["100 mpa"],
            ["1.5"],
            ["no superiority"],
            ["pore reduction"],
            ["do not isolate treatment type"],
        ],
        "evidence_terms": [
            ["heat treatment"],
            ["density"],
            ["cellular microstructure"],
            ["dislocation"],
            ["no superiority"],
            ["pore reduction"],
        ],
        "required_condition_evidence_sets": [
            [
                "furnace-type",
                "1100",
                "0.5 h",
                "hot isostatic pressing",
                "100 mpa",
                "1.5 h",
            ],
        ],
        "required_primary_finding_sets": [
            ["heat treatment increased density", "recrystallization"],
            ["no superiority", "furnace ht", "hip", "pore reduction"],
        ],
    },
    "goal_399171646354": {
        "finding_terms": [
            ["coupled slm process conditions with observed porosity level"],
            ["pitting corrosion"],
            ["passive film"],
            ["condition-level association"],
            ["97.83", "99.5", "99.26"],
            ["124.7", "199.7", "355.4"],
            ["fixed energy density", "100", "layer thickness", "20"],
            ["not monotonic with relative density"],
            ["not an isolated porosity effect"],
        ],
        "forbidden_primary_terms": [
            "Lower porosity in SLM 316L increased pitting potential",
        ],
        "evidence_terms": [
            ["porosity"],
            ["pitting corrosion"],
            ["pitting potential"],
            ["passive film"],
            ["corrosion rate"],
        ],
        "required_condition_evidence_sets": [
            [
                "laser power",
                "scan speed",
                "layer thickness",
                "energy density",
            ],
        ],
    },
    "goal_061c9c049e69": {
        "finding_terms": [
            ["α and β build orientation angles"],
            ["scan strategy rotation angle"],
            ["yield strength"],
            ["texture", "crystallographic"],
            ["334.2"],
            ["351.9"],
            ["363.1"],
            ["do not uniformly satisfy"],
        ],
        "evidence_terms": [
            ["yield strength"],
            ["yield strength prediction"],
            ["yield strength experiment"],
            ["334.2"],
            ["351.9"],
            ["363.1"],
        ],
        "comparison_terms": [
            ["α=0°", "α=0"],
            ["β=0°", "β=0"],
            ["α=45°", "α=45"],
            ["β=22.5°", "β=22.5"],
            ["θ=0°", "θ=0"],
            ["θ=45°", "θ=45"],
            ["334.2"],
            ["351.9"],
            ["363.1"],
            ["yield strength"],
        ],
        "required_primary_finding_sets": [
            [
                "α and β build orientation angles",
                "fixed scan strategy rotation angle",
                "334.2",
                "363.1",
            ],
            [
                "scan strategy rotation angle",
                "fixed build orientation",
                "334.2",
                "351.9",
            ],
        ],
        "require_table_direct_evidence_per_primary_finding": True,
    },
    "goal_6bf7d2c1030e": {
        "finding_terms": [
            ["coupled SLM parameter sets"],
            ["scanning speed"],
            ["scan strategy"],
            ["hatch spacing"],
            ["energy density"],
            ["do not isolate a scanning-speed effect"],
            "elongation",
            ["yield strength"],
            ["ultimate tensile strength"],
        ],
        "forbidden_primary_terms": [
            (
                "scanning speed -> yield strength, ultimate tensile strength, "
                "and elongation"
            ),
            "Increasing scanning speed from 0.167 to 0.175",
            "Yield Strength 236.65-462.02 MPa",
            "Ultimate Tensile Strength 375.13-584.44 MPa",
            "Elongation 7.21-41.9%",
            "Yield Strength 148.36-462.02 MPa",
            "Ultimate Tensile Strength 178.37-584.44 MPa",
            "Elongation 1.17-41.9%",
        ],
        "evidence_terms": [
            ["higher scanning speed"],
            ["densification"],
            ["microstructure"],
            ["mechanical properties"],
            ["yield strength"],
            ["ultimate tensile strength"],
            ["elongation"],
        ],
        "required_direct_evidence_sets": [
            [
                "mechanical properties",
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "mpa",
                "%",
                "236.65",
                "375.13",
                "7.21",
            ],
        ],
        "required_condition_evidence_sets": [
            [
                "hatch",
                "scan strategy",
                "scanning speed",
                "energy density",
            ],
        ],
    },
    "goal_3037e425673a": {
        "finding_terms": [
            [
                "coupled pbf-lb parameter sets grouped by volumetric energy "
                "density"
            ],
            ["defect"],
            ["fatigue strength"],
            ["340"],
            ["450"],
            ["470"],
            ["fat50 was non-monotonic"],
            ["93"],
            ["82"],
            ["97"],
            ["wrought 316l (256 mpa)"],
            ["laser power"],
            ["scanning speed"],
            ["hatch spacing"],
            ["layer thickness remained fixed"],
            ["does not isolate a ved-only effect"],
        ],
        "evidence_terms": [
            ["increasing ved"],
            ["defect"],
            ["fatigue strength"],
            ["340"],
            ["450"],
            ["470"],
            ["93"],
            ["82"],
            ["97"],
            ["256"],
        ],
        "required_condition_evidence_sets": [
            [
                "varying",
                "scanning speed",
                "laser power",
                "50.8",
                "79.4",
                "84.3",
            ],
        ],
    },
}

GOAL_REVIEW_QUEUE_AXIS_EXPECTATIONS: dict[str, list[list[str]]] = {
    "goal_1a7a26d850b9": [
        ["scan speed", "scanning speed"],
    ],
}
GOAL_REVIEW_QUEUE_EXPERT_EXPECTATIONS: dict[str, dict[str, list[list[str]]]] = {
    "goal_1a7a26d850b9": {
        "finding_terms": [
            ["scan speed", "scanning speed"],
            ["density"],
        ],
        "evidence_terms": [
            ["scan speed"],
            ["density"],
            ["98.70"],
            ["93.67"],
        ],
        "warning_terms": [
            ["review_candidate"],
            ["missing_mechanism_evidence"],
        ],
    },
}
GOAL_PRIMARY_WARNING_EXPECTATIONS: dict[str, list[list[str]]] = {
    "goal_0914003ad572": [
        ["author_attributed_mechanism"],
    ],
    "goal_399171646354": [
        ["paper_level_association"],
        ["process_conditions_not_isolated"],
        ["porosity_response_not_monotonic"],
    ],
    "goal_1a7a26d850b9": [
        ["heat_treatment_parameters_not_isolated"],
        ["single_variable_effect_not_isolated"],
    ],
    "goal_061c9c049e69": [
        ["model_validation_finding"],
        ["author_summary_table_mismatch"],
    ],
    "goal_6bf7d2c1030e": [
        ["non_single_variable_table_comparison"],
        ["single_variable_effect_not_isolated"],
    ],
    "goal_3037e425673a": [
        ["process_conditions_not_isolated"],
        ["single_variable_effect_not_isolated"],
    ],
}
GOAL_AXIS_SEMANTIC_EXPECTATIONS: dict[str, dict[str, list[str]]] = {
    "goal_061c9c049e69": {
        "required": [
            "scan strategy rotation angle",
            "α build orientation angle",
            "β build orientation angle",
        ],
        "forbidden": ["β ->", "β scan strategy rotation angle"],
    },
}
GOAL_ALL_FINDING_FORBIDDEN_TERMS: dict[str, list[str]] = {
    "goal_1a7a26d850b9": [
        "laser power from 100 to 120 decreased density from 98.70 % to 98.45 %",
    ],
    "goal_061c9c049e69": [
        "scan strategy rotation angle and build orientation -> yield strength",
        "β build orientation angle remained at 0°",
        "prediction deviations were generally below 5%",
        "yield strength prediction from 310.48 mpa",
        "prediction from 310.48 mpa to 314.37 mpa",
    ],
    "goal_6bf7d2c1030e": [
        "scan speed is associated with mechanical properties",
        "scanning speed is associated with mechanical properties",
        "multi-axis table contrast",
        "table-row comparison changes",
    ],
}
GOAL_ALL_FINDING_REQUIRED_TERMS: dict[str, list[list[str]]] = {
    "goal_3037e425673a": [
        ["volumetric energy density", "50.8", "79.4", "fatigue strength"],
    ],
}
GOAL_MIN_PRIMARY_AXIS_COVERAGE: dict[str, dict[str, int]] = {
    "goal_0914003ad572": {"variables": 2, "properties": 2},
    "goal_1a7a26d850b9": {"variables": 3, "properties": 2},
    "goal_399171646354": {"variables": 1, "properties": 1},
    "goal_061c9c049e69": {"variables": 2, "properties": 2},
    "goal_6bf7d2c1030e": {"variables": 3, "properties": 3},
    "goal_3037e425673a": {"variables": 1, "properties": 1},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check confirmed-goal research understanding findings for "
            "materials-expert review readiness."
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
            "http://localhost:5173. When set, the script reads analysis payloads "
            "over HTTP instead of local application services. Set "
            "LENS_CHECK_EMAIL and LENS_CHECK_PASSWORD when login is required."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = check_goal_findings_projection(
        collection_id=args.collection_id,
        goal_ids=tuple(args.goal_ids or DEFAULT_GOAL_IDS),
        api_base_url=args.api_base_url,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "fail":
        raise SystemExit(1)


def check_goal_findings_projection(
    *,
    collection_id: str,
    goal_ids: tuple[str, ...] = DEFAULT_GOAL_IDS,
    api_base_url: str | None = None,
) -> dict[str, Any]:
    backend_root = str(DEFAULT_BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

    source_index = build_source_artifact_index(collection_id)
    goal_summaries = []
    checks: list[dict[str, str]] = []
    for goal_id in goal_ids:
        response = (
            fetch_goal_analysis_payload_from_api(
                api_base_url=api_base_url,
                collection_id=collection_id,
                goal_id=goal_id,
            )
            if api_base_url
            else _local_goal_analysis_payload(collection_id, goal_id)
        )
        goal_summary = evaluate_goal_analysis_payload(
            response,
            source_index=source_index,
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


def _local_goal_analysis_payload(collection_id: str, goal_id: str) -> dict[str, Any]:
    with contextlib.redirect_stdout(io.StringIO()):
        from application.pipeline.goal_analysis.service import (  # noqa: PLC0415
            GoalAnalysisPipelineService,
        )
        from controllers.core.goal_analysis import _analysis_response  # noqa: PLC0415

        service = GoalAnalysisPipelineService()
        payload = service.get_goal_analysis(collection_id, goal_id)
        return _analysis_response(collection_id, payload).model_dump(mode="json")


def fetch_goal_analysis_payload_from_api(
    *,
    api_base_url: str,
    collection_id: str,
    goal_id: str,
) -> dict[str, Any]:
    base_url = api_base_url.rstrip("/")
    cookie = _api_login_cookie(base_url)
    return _api_json_request(
        base_url,
        f"/api/v1/collections/{collection_id}/goals/{goal_id}/analysis",
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


def build_source_artifact_index(collection_id: str) -> dict[str, Any]:
    with contextlib.redirect_stdout(io.StringIO()):
        from infra.persistence.factory import (  # noqa: PLC0415
            build_source_artifact_repository,
        )

        artifacts = build_source_artifact_repository().read_collection_artifacts(
            collection_id
        )
    documents = {
        document.document_id
        for document in artifacts.documents
        if document.document_id
    }
    sources: dict[str, dict[str, str]] = {}
    for block in artifacts.blocks:
        if block.block_id:
            sources[block.block_id] = {
                "kind": "block",
                "document_id": block.document_id,
                "page": _source_page(block.page),
                "text": block.text,
            }
    for table in artifacts.tables:
        if table.table_id:
            table_text_parts = [
                table.caption_text or "",
                " ".join(table.column_headers),
                " ".join(" ".join(row) for row in table.table_matrix),
            ]
            sources[table.table_id] = {
                "kind": "table",
                "document_id": table.document_id,
                "page": _source_page(table.page),
                "text": " ".join(part for part in table_text_parts if part),
            }
    for figure in artifacts.figures:
        if figure.figure_id:
            sources[figure.figure_id] = {
                "kind": "figure",
                "document_id": figure.document_id,
                "page": _source_page(figure.page),
                "text": figure.caption_text or "",
            }
    return {"documents": documents, "sources": sources}


def evaluate_goal_analysis_payload(
    payload: dict[str, Any],
    *,
    source_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    goal = payload.get("goal") if isinstance(payload.get("goal"), dict) else {}
    goal_id = str(goal.get("goal_id") or "")
    question = _source_page(goal.get("question"))
    understanding = payload.get("understanding") or {}
    presentation = understanding.get("presentation") or {}
    primary_findings = _dict_rows(presentation.get("primary_findings"))
    review_findings = _dict_rows(presentation.get("review_queue_findings"))
    summary = (
        presentation.get("summary")
        if isinstance(presentation.get("summary"), dict)
        else {}
    )
    evidence_items = {
        str(item.get("evidence_ref_id") or ""): item
        for item in _dict_rows(presentation.get("evidence_items"))
        if item.get("evidence_ref_id")
    }
    direct_evidence_ids = [
        evidence_id
        for finding in primary_findings
        for evidence_id in _direct_evidence_ids(finding)
    ]
    review_evidence_ids = [
        evidence_id
        for finding in review_findings
        for evidence_id in _direct_evidence_ids(finding)
    ]
    referenced_evidence_ids = {
        *[
            evidence_id
            for finding in [*primary_findings, *review_findings]
            for evidence_id in _finding_evidence_bundle_ids(finding)
        ],
    }
    unreferenced_evidence_ids = [
        evidence_id
        for evidence_id in evidence_items
        if evidence_id not in referenced_evidence_ids
    ]
    resolved_direct_evidence = [
        evidence_items[evidence_id]
        for evidence_id in direct_evidence_ids
        if evidence_id in evidence_items
    ]
    resolved_condition_evidence = [
        evidence_items[evidence_id]
        for finding in primary_findings
        for evidence_id in _finding_evidence_role_ids(finding, "condition_context")
        if evidence_id in evidence_items
    ]
    review_expectation = GOAL_REVIEW_QUEUE_EXPERT_EXPECTATIONS.get(goal_id)
    target_findings = review_findings if review_expectation else primary_findings
    target_evidence_ids = review_evidence_ids if review_expectation else direct_evidence_ids
    resolved_target_evidence = [
        evidence_items[evidence_id]
        for evidence_id in target_evidence_ids
        if evidence_id in evidence_items
    ]
    traceable_evidence_ids = _dedupe_strings(
        [
            *direct_evidence_ids,
            *review_evidence_ids,
        ]
    )
    traceable_evidence = [
        evidence_items[evidence_id]
        for evidence_id in traceable_evidence_ids
        if evidence_id in evidence_items
    ]
    table_audit = _table_audit_summary(
        traceable_evidence,
        source_index=source_index,
    )
    endpoint_audit = _finding_table_endpoint_summary(
        [*primary_findings, *review_findings],
        evidence_items=evidence_items,
        source_index=source_index,
    )
    duplicate_source_targets = _duplicate_finding_evidence_source_targets(
        [*primary_findings, *review_findings],
        evidence_items=evidence_items,
    )
    duplicate_bundle_ref_ids = _duplicate_finding_bundle_ref_ids(
        [*primary_findings, *review_findings],
    )
    boundary_findings = [*primary_findings, *review_findings]
    boundary = _finding_boundary_summary(
        boundary_findings,
        direct_evidence_by_finding=[
            _direct_evidence_ids(finding) for finding in boundary_findings
        ],
    )
    scope_noise_failures = _finding_scope_noise_failures(boundary_findings)
    symbol_scope_failures = _finding_symbol_scope_failures(boundary_findings)
    axis_coverage = _axis_coverage_summary(summary.get("axis_coverage"))
    axis_coverage_requirement = GOAL_MIN_PRIMARY_AXIS_COVERAGE.get(goal_id, {})
    variable_primary_count = axis_coverage["variables"].get("primary", 0) + axis_coverage[
        "variables"
    ].get("mechanism", 0)
    property_primary_count = axis_coverage["properties"].get("primary", 0) + axis_coverage[
        "properties"
    ].get("mechanism", 0)
    checks = [
        _check(
            goal_id,
            "expert findings or review targets are available",
            bool(target_findings),
            (
                f"primary={len(primary_findings)}; "
                f"review_queue={len(review_findings)}"
            ),
        ),
        _check(
            goal_id,
            "understanding state is not empty when findings exist",
            not target_findings or understanding.get("state") != "empty",
            f"state={understanding.get('state')}",
        ),
        _check(
            goal_id,
            "expert findings or review targets have direct evidence ids",
            all(_direct_evidence_ids(finding) for finding in target_findings),
            f"direct_evidence_ids={len(target_evidence_ids)}",
        ),
        _check(
            goal_id,
            "direct evidence ids resolve to presentation evidence items",
            len(resolved_target_evidence) == len(target_evidence_ids),
            (
                f"resolved={len(resolved_target_evidence)}; "
                f"expected={len(target_evidence_ids)}"
            ),
        ),
        _check(
            goal_id,
            "direct evidence items include quote and href",
            bool(resolved_target_evidence)
            and len(resolved_target_evidence) == len(target_evidence_ids)
            and all(
                item.get("quote") and item.get("href")
                for item in resolved_target_evidence
            ),
            f"items={len(resolved_target_evidence)}",
        ),
        _check(
            goal_id,
            "table direct evidence exposes relevant rows and columns",
            not table_audit["failures"],
            _table_audit_detail(table_audit),
        ),
        _check(
            goal_id,
            "table direct evidence covers statement numeric endpoints",
            not endpoint_audit["failures"],
            _table_audit_detail(endpoint_audit),
        ),
        _check(
            goal_id,
            "presentation evidence only contains referenced finding evidence",
            not unreferenced_evidence_ids,
            _unreferenced_evidence_detail(unreferenced_evidence_ids),
        ),
        _check(
            goal_id,
            "summary evidence count matches visible finding evidence",
            _int_value(summary.get("evidence_count")) == len(evidence_items),
            (
                f"summary={_int_value(summary.get('evidence_count'))}; "
                f"visible={len(evidence_items)}"
            ),
        ),
        _check(
            goal_id,
            "summary finding counts match visible findings",
            _int_value(summary.get("primary_finding_count")) == len(primary_findings)
            and _int_value(summary.get("review_queue_finding_count"))
            == len(review_findings)
            and _int_value(summary.get("review_queue_count"))
            == len(review_findings),
            (
                "primary_summary="
                f"{_int_value(summary.get('primary_finding_count'))}; "
                f"primary_visible={len(primary_findings)}; "
                "review_summary="
                f"{_int_value(summary.get('review_queue_finding_count'))}; "
                f"review_queue_summary={_int_value(summary.get('review_queue_count'))}; "
                f"review_visible={len(review_findings)}"
            ),
        ),
        _check(
            goal_id,
            "presentation evidence text excludes replacement characters",
            "\ufffd" not in json.dumps(presentation, ensure_ascii=False),
            "replacement_char_present="
            + str("\ufffd" in json.dumps(presentation, ensure_ascii=False)),
        ),
        _check(
            goal_id,
            "finding evidence does not duplicate source targets",
            not duplicate_source_targets,
            _duplicate_source_target_detail(duplicate_source_targets),
        ),
        _check(
            goal_id,
            "finding evidence bundles do not repeat ref ids",
            not duplicate_bundle_ref_ids,
            _duplicate_ref_id_detail(duplicate_bundle_ref_ids),
        ),
        _check(
            goal_id,
            "expert findings and review targets include expert use status",
            not boundary["missing_expert_use_status"]
            and not boundary["invalid_expert_use_status"],
            _boundary_detail(
                missing=boundary["missing_expert_use_status"],
                invalid=boundary["invalid_expert_use_status"],
            ),
        ),
        _check(
            goal_id,
            "expert findings and review targets include generalization status",
            not boundary["missing_generalization_status"]
            and not boundary["invalid_generalization_status"],
            _boundary_detail(
                missing=boundary["missing_generalization_status"],
                invalid=boundary["invalid_generalization_status"],
            ),
        ),
        _check(
            goal_id,
            "expert findings and review targets include generalization note",
            not boundary["missing_generalization_note"],
            _boundary_detail(missing=boundary["missing_generalization_note"]),
        ),
        _check(
            goal_id,
            "expert findings and review targets include evidence gap summary",
            not boundary["missing_evidence_gap_summary"],
            _boundary_detail(missing=boundary["missing_evidence_gap_summary"]),
        ),
        _check(
            goal_id,
            "single-paper findings and review targets are labeled as paper-level only",
            not boundary["single_paper_status_failures"],
            _boundary_detail(invalid=boundary["single_paper_status_failures"]),
        ),
        _check(
            goal_id,
            "multi-paper findings and review targets are labeled as cross-paper",
            not boundary["multi_paper_status_failures"],
            _boundary_detail(invalid=boundary["multi_paper_status_failures"]),
        ),
        _check(
            goal_id,
            "findings and review targets without direct evidence are labeled for repair",
            not boundary["missing_evidence_status_failures"],
            _boundary_detail(invalid=boundary["missing_evidence_status_failures"]),
        ),
        _check(
            goal_id,
            "finding scope summaries exclude parser and sample-label noise",
            not scope_noise_failures,
            _scope_noise_detail(scope_noise_failures),
        ),
        _check(
            goal_id,
            "symbol-axis findings keep title and scope aligned",
            not symbol_scope_failures,
            _symbol_scope_detail(symbol_scope_failures),
        ),
        _check(
            goal_id,
            "goal coverage exposes requested variable axes",
            axis_coverage["variables"].get("total", 0) > 0,
            _axis_coverage_detail(axis_coverage["variables"], required=1),
        ),
        _check(
            goal_id,
            "goal coverage exposes requested property axes",
            axis_coverage["properties"].get("total", 0) > 0,
            _axis_coverage_detail(axis_coverage["properties"], required=1),
        ),
        _check(
            goal_id,
            "primary findings cover enough requested variable axes",
            variable_primary_count
            >= int(axis_coverage_requirement.get("variables", 1)),
            _axis_coverage_detail(
                axis_coverage["variables"],
                required=int(axis_coverage_requirement.get("variables", 1)),
            ),
        ),
        _check(
            goal_id,
            "primary findings cover enough requested property axes",
            property_primary_count
            >= int(axis_coverage_requirement.get("properties", 1)),
            _axis_coverage_detail(
                axis_coverage["properties"],
                required=int(axis_coverage_requirement.get("properties", 1)),
            ),
        ),
    ]
    if source_index is not None:
        source_resolution = _resolve_direct_evidence_sources(
            traceable_evidence,
            source_index=source_index,
        )
        checks.extend(
            [
                _check(
                    goal_id,
                    "direct evidence hrefs resolve to source artifacts",
                    not source_resolution["target_failures"],
                    _source_resolution_detail(
                        source_resolution["target_failures"],
                        total=len(traceable_evidence),
                    ),
                ),
                _check(
                    goal_id,
                    "direct evidence quotes overlap resolved source artifacts",
                    not source_resolution["quote_failures"],
                    _source_resolution_detail(
                        source_resolution["quote_failures"],
                        total=len(traceable_evidence),
                    ),
                ),
            ]
        )
    expectation = GOAL_EXPERT_EXPECTATIONS.get(goal_id)
    if expectation:
        finding_text = _combined_text(primary_findings)
        evidence_text = _combined_text(resolved_direct_evidence, keys=("quote", "source_text"))
        missing_finding_terms = _missing_term_groups(
            finding_text,
            expectation.get("finding_terms") or [],
        )
        missing_evidence_terms = _missing_term_groups(
            evidence_text,
            expectation.get("evidence_terms") or [],
        )
        missing_direct_evidence_sets = _missing_direct_evidence_sets(
            resolved_direct_evidence,
            expectation.get("required_direct_evidence_sets") or [],
        )
        missing_condition_evidence_sets = _missing_direct_evidence_sets(
            resolved_condition_evidence,
            expectation.get("required_condition_evidence_sets") or [],
        )
        missing_comparison_terms = _missing_term_groups(
            _combined_text(primary_findings, keys=("comparison_summary",)),
            expectation.get("comparison_terms") or [],
        )
        missing_distinct_finding_sets = _missing_distinct_finding_sets(
            primary_findings,
            expectation.get("required_primary_finding_sets") or [],
        )
        missing_table_finding_ids = [
            str(finding.get("finding_id") or "unknown")
            for finding in primary_findings
            if not any(
                str(evidence_items.get(evidence_id, {}).get("source_kind") or "")
                .lower()
                .endswith("table")
                for evidence_id in _direct_evidence_ids(finding)
            )
        ]
        checks.extend(
            [
                _check(
                    goal_id,
                    "primary findings match goal-specific expert expectations",
                    not missing_finding_terms,
                    _missing_terms_detail(missing_finding_terms),
                ),
                _check(
                    goal_id,
                    "direct evidence quotes cover goal-specific source claims",
                    not missing_evidence_terms and not missing_direct_evidence_sets,
                    _missing_terms_detail(
                        [*missing_evidence_terms, *missing_direct_evidence_sets]
                    ),
                ),
            ]
        )
        if expectation.get("comparison_terms"):
            checks.append(
                _check(
                    goal_id,
                    "primary finding comparison summary preserves expert comparison",
                    not missing_comparison_terms,
                    _missing_terms_detail(missing_comparison_terms),
                )
            )
        if expectation.get("required_condition_evidence_sets"):
            checks.append(
                _check(
                    goal_id,
                    "condition evidence preserves confounded process settings",
                    not missing_condition_evidence_sets,
                    _missing_terms_detail(missing_condition_evidence_sets),
                )
            )
        if expectation.get("required_primary_finding_sets"):
            checks.append(
                _check(
                    goal_id,
                    "primary findings preserve distinct expert comparisons",
                    not missing_distinct_finding_sets,
                    _missing_terms_detail(missing_distinct_finding_sets),
                )
            )
        if expectation.get("require_table_direct_evidence_per_primary_finding"):
            checks.append(
                _check(
                    goal_id,
                    "each primary finding cites direct table evidence",
                    bool(primary_findings) and not missing_table_finding_ids,
                    (
                        "all primary findings cite table evidence"
                        if not missing_table_finding_ids
                        else "missing="
                        + json.dumps(missing_table_finding_ids, ensure_ascii=False)
                    ),
                )
            )
        forbidden_terms = [
            term.lower()
            for term in expectation.get("forbidden_primary_terms") or []
            if term
        ]
        finding_claim_text = _combined_text(
            primary_findings,
            keys=("title", "statement", "variables", "mediators", "outcomes"),
        )
        forbidden_hits = [
            term
            for term in forbidden_terms
            if term in finding_claim_text
        ]
        if forbidden_terms:
            checks.append(
                _check(
                    goal_id,
                    "primary findings avoid over-specific unsupported terms",
                    not forbidden_hits,
                    (
                        "none"
                        if not forbidden_hits
                        else "forbidden=" + json.dumps(forbidden_hits)
                    ),
                )
            )
    primary_warning_expectation = GOAL_PRIMARY_WARNING_EXPECTATIONS.get(goal_id)
    if primary_warning_expectation:
        primary_warning_text = _combined_text(
            primary_findings,
            keys=("warnings", "review_reasons"),
        )
        missing_primary_warning_terms = _missing_term_groups(
            primary_warning_text,
            primary_warning_expectation,
        )
        checks.append(
            _check(
                goal_id,
                "primary findings preserve required expert review warnings",
                not missing_primary_warning_terms,
                _missing_terms_detail(missing_primary_warning_terms),
            )
        )
    axis_semantic_expectation = GOAL_AXIS_SEMANTIC_EXPECTATIONS.get(goal_id)
    if axis_semantic_expectation:
        axis_text = _combined_text(
            [*primary_findings, *review_findings],
            keys=("title", "statement", "variables", "comparison_summary"),
        )
        missing_axis_terms = [
            term
            for term in axis_semantic_expectation.get("required", [])
            if term.lower() not in axis_text
        ]
        forbidden_axis_terms = [
            term
            for term in axis_semantic_expectation.get("forbidden", [])
            if term.lower() in axis_text
        ]
        checks.append(
            _check(
                goal_id,
                "angle symbols preserve expert axis semantics",
                not missing_axis_terms and not forbidden_axis_terms,
                _axis_semantics_detail(missing_axis_terms, forbidden_axis_terms),
            )
        )
    all_finding_text = _combined_text(
        [*primary_findings, *review_findings],
        keys=("title", "statement", "variables", "outcomes", "comparison_summary"),
    )
    forbidden_all_terms = [
        term
        for term in GOAL_ALL_FINDING_FORBIDDEN_TERMS.get(goal_id, [])
        if term.lower() in all_finding_text
    ]
    if goal_id in GOAL_ALL_FINDING_FORBIDDEN_TERMS:
        checks.append(
            _check(
                goal_id,
                "all expert findings avoid goal-specific noise rows",
                not forbidden_all_terms,
                (
                    "none"
                    if not forbidden_all_terms
                    else "forbidden=" + json.dumps(forbidden_all_terms)
                ),
            )
        )
    required_all_terms = GOAL_ALL_FINDING_REQUIRED_TERMS.get(goal_id, [])
    if required_all_terms:
        missing_all_terms = _missing_term_groups(
            all_finding_text,
            required_all_terms,
        )
        checks.append(
            _check(
                goal_id,
                "all expert findings preserve context-valued comparisons",
                not missing_all_terms,
                _missing_terms_detail(missing_all_terms),
            )
        )
    if review_expectation:
        resolved_review_evidence = [
            evidence_items[evidence_id]
            for evidence_id in review_evidence_ids
            if evidence_id in evidence_items
        ]
        review_text = _combined_text(review_findings)
        review_evidence_text = _combined_text(
            resolved_review_evidence,
            keys=("quote", "source_text"),
        )
        review_warning_text = _combined_text(
            review_findings,
            keys=("expert_use_status", "warnings", "review_reasons"),
        )
        missing_review_finding_terms = _missing_term_groups(
            review_text,
            review_expectation.get("finding_terms") or [],
        )
        missing_review_evidence_terms = _missing_term_groups(
            review_evidence_text,
            review_expectation.get("evidence_terms") or [],
        )
        missing_review_warning_terms = _missing_term_groups(
            review_warning_text,
            review_expectation.get("warning_terms") or [],
        )
        checks.extend(
            [
                _check(
                    goal_id,
                    "review queue preserves model-validation finding",
                    bool(review_findings) and not missing_review_finding_terms,
                    _missing_terms_detail(missing_review_finding_terms),
                ),
                _check(
                    goal_id,
                    "review queue evidence covers model-validation source claims",
                    bool(resolved_review_evidence)
                    and not missing_review_evidence_terms,
                    _missing_terms_detail(missing_review_evidence_terms),
                ),
                _check(
                    goal_id,
                    "review queue marks model-validation finding for expert review",
                    not missing_review_warning_terms,
                    _missing_terms_detail(missing_review_warning_terms),
                ),
            ]
        )
    review_queue_axis_expectation = GOAL_REVIEW_QUEUE_AXIS_EXPECTATIONS.get(goal_id)
    if review_queue_axis_expectation:
        review_queue_axis_text = _combined_text(
            review_findings,
            keys=("title", "statement", "variables", "outcomes", "comparison_summary"),
        )
        missing_review_axis_terms = _missing_term_groups(
            review_queue_axis_text,
            review_queue_axis_expectation,
        )
        checks.append(
            _check(
                goal_id,
                "review queue preserves goal-specific table axes",
                bool(review_findings) and not missing_review_axis_terms,
                _missing_terms_detail(missing_review_axis_terms),
            )
        )
    return {
        "goal_id": goal_id,
        "question": question,
        "state": understanding.get("state"),
        "primary_finding_count": len(primary_findings),
        "review_queue_finding_count": len(review_findings),
        "direct_evidence_count": len(direct_evidence_ids),
        "primary_titles": [
            str(finding.get("title") or "") for finding in primary_findings
        ],
        "checks": checks,
    }


def _combined_text(
    records: list[dict[str, Any]],
    *,
    keys: tuple[str, ...] = (
        "title",
        "statement",
        "variables",
        "mediators",
        "outcomes",
        "scope_summary",
    ),
) -> str:
    parts: list[str] = []
    for record in records:
        for key in keys:
            value = record.get(key)
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            elif value is not None:
                parts.append(str(value))
    return re.sub(r"(?<=\w)-\s+(?=\w)", "", " ".join(parts)).lower()


def _finding_boundary_summary(
    findings: list[dict[str, Any]],
    *,
    direct_evidence_by_finding: list[list[str]],
) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {
        "missing_expert_use_status": [],
        "invalid_expert_use_status": [],
        "missing_generalization_status": [],
        "invalid_generalization_status": [],
        "missing_generalization_note": [],
        "missing_evidence_gap_summary": [],
        "single_paper_status_failures": [],
        "multi_paper_status_failures": [],
        "missing_evidence_status_failures": [],
    }
    for index, finding in enumerate(findings):
        finding_label = _finding_label(finding, index=index)
        expert_use_status = str(finding.get("expert_use_status") or "").strip()
        generalization_status = str(
            finding.get("generalization_status") or ""
        ).strip()
        if not expert_use_status:
            summary["missing_expert_use_status"].append(finding_label)
        elif expert_use_status not in EXPERT_USE_STATUSES:
            summary["invalid_expert_use_status"].append(
                f"{finding_label}: {expert_use_status}"
            )
        if not generalization_status:
            summary["missing_generalization_status"].append(finding_label)
        elif generalization_status not in GENERALIZATION_STATUSES:
            summary["invalid_generalization_status"].append(
                f"{finding_label}: {generalization_status}"
            )
        if not str(finding.get("generalization_note") or "").strip():
            summary["missing_generalization_note"].append(finding_label)
        if not str(finding.get("evidence_gap_summary") or "").strip():
            summary["missing_evidence_gap_summary"].append(finding_label)

        direct_evidence_ids = (
            direct_evidence_by_finding[index]
            if index < len(direct_evidence_by_finding)
            else []
        )
        paper_count = _int_value(finding.get("paper_count"))
        if direct_evidence_ids and paper_count <= 1:
            review_reasons = {
                str(reason)
                for reason in finding.get("review_reasons") or []
                if str(reason)
            }
            review_status = str(finding.get("review_status") or "").strip()
            valid_single_paper_expert_status = expert_use_status in {
                "paper_level_finding",
                "review_candidate",
            }
            valid_review_candidate = (
                expert_use_status != "review_candidate"
                or review_status == "needs_review"
                or any("review" in reason for reason in review_reasons)
            )
            if (
                not valid_single_paper_expert_status
                or generalization_status != "paper_level_only"
                or not valid_review_candidate
            ):
                summary["single_paper_status_failures"].append(
                    (
                        f"{finding_label}: paper_count={paper_count}, "
                        f"expert_use_status={expert_use_status or '<missing>'}, "
                        "generalization_status="
                        f"{generalization_status or '<missing>'}"
                    )
                )
        if direct_evidence_ids and paper_count > 1:
            review_reasons = {
                str(reason)
                for reason in finding.get("review_reasons") or []
                if str(reason)
            }
            upgrade_actions = {
                str(action)
                for action in finding.get("upgrade_actions") or []
                if str(action)
            }
            evidence_gap_summary = str(finding.get("evidence_gap_summary") or "")
            stale_single_paper_markers = []
            if expert_use_status == "paper_level_finding":
                stale_single_paper_markers.append("expert_use_status")
            if generalization_status == "paper_level_only":
                stale_single_paper_markers.append("generalization_status")
            if "single_paper_evidence" in review_reasons:
                stale_single_paper_markers.append("single_paper_evidence")
            if "needs_cross_paper_confirmation" in review_reasons:
                stale_single_paper_markers.append("needs_cross_paper_confirmation")
            if "add_cross_paper_evidence" in upgrade_actions:
                stale_single_paper_markers.append("add_cross_paper_evidence")
            if "independent cross-paper confirmation" in evidence_gap_summary:
                stale_single_paper_markers.append("evidence_gap_summary")
            if stale_single_paper_markers:
                summary["multi_paper_status_failures"].append(
                    (
                        f"{finding_label}: paper_count={paper_count}, stale="
                        + ",".join(stale_single_paper_markers)
                    )
                )
        if not direct_evidence_ids and (
            expert_use_status != "evidence_repair_needed"
            or generalization_status != "evidence_repair_needed"
        ):
            summary["missing_evidence_status_failures"].append(
                (
                    f"{finding_label}: expert_use_status="
                    f"{expert_use_status or '<missing>'}, "
                    "generalization_status="
                    f"{generalization_status or '<missing>'}"
                )
            )
    return summary


def _finding_label(finding: dict[str, Any], *, index: int) -> str:
    return (
        str(finding.get("finding_id") or "").strip()
        or str(finding.get("title") or "").strip()
        or f"finding[{index}]"
    )


def _finding_scope_noise_failures(findings: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for index, finding in enumerate(findings):
        scope_summary = str(finding.get("scope_summary") or "").strip()
        if not scope_summary:
            continue
        lowered = scope_summary.lower()
        if (
            re.search(r"\b\d+(?:\.\d+)*\.?\s+conclusions?\b", lowered)
            or "conclusions and future study" in lowered
            or re.search(r"\(\s*\d+/\s*(?:,|$)", scope_summary)
        ):
            failures.append(f"{_finding_label(finding, index=index)}: {scope_summary}")
    return failures


def _finding_symbol_scope_failures(findings: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    symbol_axes = {
        "α build orientation angle",
        "β build orientation angle",
        "scan strategy rotation angle",
    }
    for index, finding in enumerate(findings):
        variables = [
            str(value)
            for value in finding.get("variables") or []
            if str(value) in symbol_axes
        ]
        comparison = finding.get("comparison_summary") or {}
        if isinstance(comparison, dict) and str(comparison.get("variable") or "") in symbol_axes:
            variables.append(str(comparison.get("variable")))
        variables = list(dict.fromkeys(variables))
        if not variables:
            continue
        controlled_axes = {
            str(condition.get("axis") or "")
            for condition in _dict_rows(comparison.get("controlled_conditions"))
        }
        scope_summary = str(finding.get("scope_summary") or "")
        missing = [axis for axis in variables if axis not in scope_summary]
        forbidden = [
            axis
            for axis in symbol_axes
            if axis not in variables
            and axis not in controlled_axes
            and axis in scope_summary
        ]
        if missing or forbidden:
            failures.append(
                (
                    f"{_finding_label(finding, index=index)}: "
                    f"missing={missing}, forbidden={forbidden}, scope={scope_summary}"
                )
            )
    return failures


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _boundary_detail(
    *,
    missing: list[str] | None = None,
    invalid: list[str] | None = None,
) -> str:
    parts = []
    if missing:
        parts.append("missing=" + json.dumps(missing, ensure_ascii=False))
    if invalid:
        parts.append("invalid=" + json.dumps(invalid, ensure_ascii=False))
    return "; ".join(parts) if parts else "all primary findings include valid boundary"


def _scope_noise_detail(failures: list[str]) -> str:
    return "none" if not failures else json.dumps(failures, ensure_ascii=False)


def _symbol_scope_detail(failures: list[str]) -> str:
    return "none" if not failures else json.dumps(failures, ensure_ascii=False)


def _missing_term_groups(text: str, term_groups: list[list[str]]) -> list[list[str]]:
    missing: list[list[str]] = []
    for terms in term_groups:
        normalized_terms = [term.lower() for term in terms]
        if not any(term in text for term in normalized_terms):
            missing.append(terms)
    return missing


def _missing_direct_evidence_sets(
    evidence_items: list[dict[str, Any]],
    required_sets: list[list[str]],
) -> list[list[str]]:
    missing: list[list[str]] = []
    item_texts = [
        _combined_text([item], keys=("quote", "source_text", "title", "source_label"))
        for item in evidence_items
    ]
    for terms in required_sets:
        normalized_terms = [term.lower() for term in terms if term]
        if not any(
            all(term in item_text for term in normalized_terms)
            for item_text in item_texts
        ):
            missing.append(terms)
    return missing


def _missing_distinct_finding_sets(
    findings: list[dict[str, Any]],
    required_sets: list[list[str]],
) -> list[list[str]]:
    finding_texts = [
        _combined_text(
            [finding],
            keys=("title", "statement", "variables", "comparison_summary"),
        )
        for finding in findings
    ]
    used_indexes: set[int] = set()
    missing: list[list[str]] = []
    for terms in required_sets:
        normalized_terms = [term.lower() for term in terms if term]
        match = next(
            (
                index
                for index, finding_text in enumerate(finding_texts)
                if index not in used_indexes
                and all(term in finding_text for term in normalized_terms)
            ),
            None,
        )
        if match is None:
            missing.append(terms)
        else:
            used_indexes.add(match)
    return missing


def _missing_terms_detail(missing: list[list[str]]) -> str:
    if not missing:
        return "all required term groups present"
    return "missing=" + json.dumps(missing, ensure_ascii=False)


def _axis_semantics_detail(missing: list[str], forbidden: list[str]) -> str:
    detail: dict[str, list[str]] = {}
    if missing:
        detail["missing"] = missing
    if forbidden:
        detail["forbidden"] = forbidden
    return "ok" if not detail else json.dumps(detail, ensure_ascii=False)


def _direct_evidence_ids(finding: dict[str, Any]) -> list[str]:
    bundle = finding.get("evidence_bundle") or {}
    if not isinstance(bundle, dict):
        bundle = {}
    direct_ids = [
        str(item)
        for item in bundle.get("direct_result") or []
        if str(item)
    ]
    if direct_ids:
        return direct_ids
    return [
        str(item)
        for item in finding.get("evidence_ref_ids") or []
        if str(item)
    ]


def _finding_evidence_role_ids(finding: dict[str, Any], role: str) -> list[str]:
    bundle = finding.get("evidence_bundle") or {}
    if not isinstance(bundle, dict):
        return []
    return [str(item) for item in bundle.get(role) or [] if str(item)]


def _finding_evidence_bundle_ids(finding: dict[str, Any]) -> list[str]:
    bundle = finding.get("evidence_bundle") or {}
    if isinstance(bundle, dict):
        return _dedupe_strings(
            [
                str(item)
                for value in bundle.values()
                if isinstance(value, list)
                for item in value
                if str(item)
            ]
        )
    return [
        str(item)
        for item in finding.get("evidence_ref_ids") or []
        if str(item)
    ]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _resolve_direct_evidence_sources(
    evidence_items: list[dict[str, Any]],
    *,
    source_index: dict[str, Any],
) -> dict[str, list[str]]:
    documents = set(source_index.get("documents") or set())
    sources = source_index.get("sources") or {}
    target_failures: list[str] = []
    quote_failures: list[str] = []
    for item in evidence_items:
        evidence_id = str(item.get("evidence_ref_id") or "")
        href_target = _parse_evidence_href(str(item.get("href") or ""))
        document_id = (
            href_target.get("document_id")
            or str(item.get("document_id") or "")
        )
        source_ref = (
            href_target.get("source_ref")
            or str(item.get("source_ref") or "")
        )
        page = href_target.get("page") or _source_page(item.get("page"))
        source = sources.get(source_ref)
        target_errors: list[str] = []
        if not document_id or document_id not in documents:
            target_errors.append("document")
        if not source:
            target_errors.append("source_ref")
        else:
            source_document_id = str(source.get("document_id") or "")
            source_page = _source_page(source.get("page"))
            if source_document_id and document_id != source_document_id:
                target_errors.append("document_mismatch")
            if page and source_page and page != source_page:
                target_errors.append("page_mismatch")
        if target_errors:
            target_failures.append(
                f"{evidence_id or source_ref}: {','.join(target_errors)}"
            )
            continue
        source_text = str(source.get("text") or "")
        quote = str(item.get("quote") or item.get("source_text") or "")
        if not _quote_overlaps_source(quote, source_text):
            quote_failures.append(evidence_id or source_ref)
    return {
        "target_failures": target_failures,
        "quote_failures": quote_failures,
    }


def _table_audit_summary(
    evidence_items: list[dict[str, Any]],
    *,
    source_index: dict[str, Any] | None,
) -> dict[str, Any]:
    audited_count = 0
    failures: list[str] = []
    for item in evidence_items:
        if not _is_table_evidence(item, source_index=source_index):
            continue
        audited_count += 1
        evidence_id = str(item.get("evidence_ref_id") or item.get("source_ref") or "")
        audit = item.get("table_audit")
        if not isinstance(audit, dict):
            failures.append(f"{evidence_id}: missing table_audit")
            continue
        columns = [
            str(column).strip()
            for column in audit.get("columns") or []
            if str(column).strip()
        ]
        relevant_rows = _dict_rows(audit.get("relevant_rows"))
        rows_with_cells = [
            row
            for row in relevant_rows
            if any(str(cell).strip() for cell in row.get("cells") or [])
        ]
        row_indexes = [
            row.get("row_index")
            for row in rows_with_cells
            if isinstance(row.get("row_index"), int)
        ]
        if not columns:
            failures.append(f"{evidence_id}: missing columns")
        if not rows_with_cells:
            failures.append(f"{evidence_id}: missing relevant_rows")
        if len(row_indexes) != len(set(row_indexes)):
            failures.append(f"{evidence_id}: duplicate row_index")
    return {"audited_count": audited_count, "failures": failures}


def _finding_table_endpoint_summary(
    findings: list[dict[str, Any]],
    *,
    evidence_items: dict[str, dict[str, Any]],
    source_index: dict[str, Any] | None,
) -> dict[str, Any]:
    audited_count = 0
    failures: list[str] = []
    for finding in findings:
        endpoints = _statement_numeric_endpoint_terms(
            str(finding.get("statement") or "")
        )
        if not endpoints:
            continue
        table_items = [
            item
            for evidence_id in _direct_evidence_ids(finding)
            if (item := evidence_items.get(evidence_id))
            and _is_table_evidence(item, source_index=source_index)
        ]
        if not table_items:
            continue
        audited_count += 1
        row_text = _combined_table_audit_row_text(table_items)
        missing = [
            endpoint
            for endpoint in endpoints
            if not _numeric_endpoint_present(row_text, endpoint)
        ]
        if missing:
            finding_id = str(finding.get("finding_id") or finding.get("title") or "")
            failures.append(
                f"{finding_id or 'finding'}: missing endpoint rows "
                + json.dumps(missing, ensure_ascii=False)
            )
    return {"audited_count": audited_count, "failures": failures}


def _statement_numeric_endpoint_terms(statement: str) -> list[str]:
    endpoints: list[str] = []
    for match in re.finditer(
        r"\bfrom\s+([-+]?\d+(?:\.\d+)?)",
        statement,
        flags=re.IGNORECASE,
    ):
        trailing = statement[match.end() : match.end() + 120]
        observed_match = re.search(
            r"\bto\s+([-+]?\d+(?:\.\d+)?)",
            trailing,
            flags=re.IGNORECASE,
        )
        if not observed_match:
            continue
        endpoints.extend([match.group(1), observed_match.group(1)])
    for match in re.finditer(
        r"(?P<values>[-+]?\d+(?:\.\d+)?(?:\s*,\s*[-+]?\d+(?:\.\d+)?)*"
        r"(?:\s*,?\s+and\s+[-+]?\d+(?:\.\d+)?)?)\s*"
        r"(?:(?:mpa|μm|um)\b|%(?!\w))",
        statement,
        flags=re.IGNORECASE,
    ):
        values = re.findall(r"[-+]?\d+(?:\.\d+)?", match.group("values"))
        if len(values) > 1:
            endpoints.extend(values)
    return _dedupe_strings(endpoints)


def _combined_table_audit_row_text(evidence_items: list[dict[str, Any]]) -> str:
    row_texts: list[str] = []
    for item in evidence_items:
        audit = item.get("table_audit")
        if not isinstance(audit, dict):
            continue
        for row in _dict_rows(audit.get("relevant_rows")):
            row_texts.append(
                " | ".join(
                    str(cell).strip()
                    for cell in row.get("cells") or []
                    if str(cell).strip()
                )
            )
    return _normalize_match_text(" ".join(row_texts))


def _numeric_endpoint_present(row_text: str, endpoint: str) -> bool:
    for term in _numeric_endpoint_match_terms(endpoint):
        if term and re.search(rf"(?<!\d){re.escape(term)}(?!\d)", row_text):
            return True
    endpoint_number = _decimal_value(endpoint)
    if endpoint_number is None:
        return False
    return any(
        candidate == endpoint_number
        for candidate in (
            _decimal_value(match.group(0))
            for match in re.finditer(r"[-+]?\d+(?:\.\d+)?", row_text)
        )
    )


def _decimal_value(value: str) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _numeric_endpoint_match_terms(value: str) -> list[str]:
    number = str(value).strip()
    terms = [number]
    if "." in number:
        terms.append(number.rstrip("0").rstrip("."))
    elif number:
        terms.append(f"{number}.0")
    return _dedupe_strings([term for term in terms if term])


def _is_table_evidence(
    item: dict[str, Any],
    *,
    source_index: dict[str, Any] | None,
) -> bool:
    source_kind = str(item.get("source_kind") or "").strip().lower()
    if source_kind == "table":
        return True
    if source_kind and source_kind != "unknown":
        return False
    if source_index is None:
        return False
    href_target = _parse_evidence_href(str(item.get("href") or ""))
    source_ref = (
        href_target.get("source_ref")
        or str(item.get("source_ref") or "")
    )
    source = (source_index.get("sources") or {}).get(source_ref)
    return isinstance(source, dict) and str(source.get("kind") or "") == "table"


def _table_audit_detail(summary: dict[str, Any]) -> str:
    failures = summary.get("failures") or []
    if failures:
        return "failures=" + json.dumps(failures, ensure_ascii=False)
    return f"audited={int(summary.get('audited_count') or 0)}"


def _parse_evidence_href(href: str) -> dict[str, str]:
    if not href:
        return {}
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    path_parts = [unquote(part) for part in parsed.path.split("/") if part]
    document_id = ""
    if "documents" in path_parts:
        document_index = path_parts.index("documents") + 1
        if document_index < len(path_parts):
            document_id = path_parts[document_index]
    return {
        "document_id": document_id,
        "source_ref": (query.get("source_ref") or [""])[0],
        "page": (query.get("page") or [""])[0],
    }


def _duplicate_finding_evidence_source_targets(
    findings: list[dict[str, Any]],
    *,
    evidence_items: dict[str, dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    for index, finding in enumerate(findings, start=1):
        seen: set[str] = set()
        duplicates: list[str] = []
        for evidence_id in _direct_evidence_ids(finding):
            item = evidence_items.get(evidence_id)
            if not item:
                continue
            target = _evidence_source_target_key(item)
            if not target:
                continue
            if target in seen:
                duplicates.append(target)
            else:
                seen.add(target)
        if duplicates:
            failures.append(
                f"{_finding_label(finding, index=index)}: "
                + json.dumps(list(dict.fromkeys(duplicates)), ensure_ascii=False)
            )
    return failures


def _duplicate_finding_bundle_ref_ids(findings: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for index, finding in enumerate(findings, start=1):
        bundle = finding.get("evidence_bundle") or {}
        if not isinstance(bundle, dict):
            continue
        seen: set[str] = set()
        duplicates: list[str] = []
        direct_ref_ids = {str(ref) for ref in bundle.get("direct_result", [])}
        for role, value in bundle.items():
            if not isinstance(value, list):
                continue
            for item in value:
                ref_id = str(item)
                if not ref_id:
                    continue
                if role == "mechanism" and ref_id in direct_ref_ids:
                    continue
                if ref_id in seen:
                    duplicates.append(ref_id)
                else:
                    seen.add(ref_id)
        if duplicates:
            failures.append(
                f"{_finding_label(finding, index=index)}: "
                + json.dumps(list(dict.fromkeys(duplicates)), ensure_ascii=False)
            )
    return failures


def _evidence_source_target_key(item: dict[str, Any]) -> str:
    parsed_href = _parse_evidence_href(str(item.get("href") or ""))
    document_id = str(item.get("document_id") or parsed_href.get("document_id") or "")
    source_ref = str(item.get("source_ref") or parsed_href.get("source_ref") or "")
    page = _source_page(item.get("page") or parsed_href.get("page"))
    if not (document_id or source_ref):
        return ""
    return "|".join((document_id, source_ref, page))


def _duplicate_source_target_detail(failures: list[str]) -> str:
    if not failures:
        return "none"
    return "duplicates=" + json.dumps(failures, ensure_ascii=False)


def _duplicate_ref_id_detail(failures: list[str]) -> str:
    if not failures:
        return "none"
    return "duplicates=" + json.dumps(failures, ensure_ascii=False)


def _axis_coverage_summary(value: Any) -> dict[str, dict[str, int]]:
    summary = {
        "variables": {
            "total": 0,
            "primary": 0,
            "mechanism": 0,
            "review_queue": 0,
            "context": 0,
            "missing": 0,
        },
        "properties": {
            "total": 0,
            "primary": 0,
            "mechanism": 0,
            "review_queue": 0,
            "context": 0,
            "missing": 0,
        },
    }
    if not isinstance(value, dict):
        return summary
    for key in ("variables", "properties"):
        for row in _dict_rows(value.get(key)):
            status = str(row.get("status") or "")
            if status not in summary[key]:
                status = "missing"
            summary[key]["total"] += 1
            summary[key][status] += 1
    return summary


def _axis_coverage_detail(counts: dict[str, int], *, required: int) -> str:
    primary_ready = int(counts.get("primary", 0)) + int(counts.get("mechanism", 0))
    return (
        f"total={int(counts.get('total', 0))}; "
        f"primary_or_mechanism={primary_ready}; required={required}; "
        f"primary={int(counts.get('primary', 0))}; "
        f"mechanism={int(counts.get('mechanism', 0))}; "
        f"review_queue={int(counts.get('review_queue', 0))}; "
        f"context={int(counts.get('context', 0))}; "
        f"missing={int(counts.get('missing', 0))}"
    )


def _unreferenced_evidence_detail(evidence_ids: list[str]) -> str:
    if not evidence_ids:
        return "none"
    preview = evidence_ids[:10]
    detail = {
        "count": len(evidence_ids),
        "preview": preview,
    }
    return "unreferenced=" + json.dumps(detail, ensure_ascii=False)


def _quote_overlaps_source(quote: str, source_text: str) -> bool:
    normalized_quote = _normalize_match_text(quote)
    normalized_source = _normalize_match_text(source_text)
    if not normalized_quote or not normalized_source:
        return False
    if normalized_quote[:120] and normalized_quote[:120] in normalized_source:
        return True
    quote_tokens = _match_tokens(normalized_quote)
    source_tokens = _match_tokens(normalized_source)
    if not quote_tokens or not source_tokens:
        return False
    overlap = len(quote_tokens & source_tokens)
    return overlap / max(1, min(len(quote_tokens), 60)) >= 0.45


def _match_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.split(r"\s+", text)
        if token and (len(token) >= 3 or token.isdigit())
    }


def _normalize_match_text(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^0-9a-zA-Z%°.+\-/]+", " ", str(text).lower()),
    ).strip()


def _source_resolution_detail(failures: list[str], *, total: int) -> str:
    if not failures:
        return f"resolved={total}"
    return "failures=" + json.dumps(failures, ensure_ascii=False)


def _source_page(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _check(goal_id: str, name: str, passed: bool, detail: str) -> dict[str, str]:
    return {
        "status": "pass" if passed else "fail",
        "goal_id": goal_id,
        "name": name,
        "detail": detail,
    }


if __name__ == "__main__":
    main()
