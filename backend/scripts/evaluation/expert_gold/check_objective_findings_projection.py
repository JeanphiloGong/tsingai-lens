#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib import request as request_url
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COLLECTION_ID = "col_0cc5013fdb3c"
DEFAULT_OBJECTIVE_IDS = (
    "obj_how-do-build-platform-preheating-temperature-and-build-platform-preheati_a13773ac",
    "obj_how-do-laser-power-scan-speed-heat-treatment-type-and-heat-treatment-par_f189a6ba",
    "obj_how-do-laser-power-scanning-speed-energy-density-porosity-level-and-pore_f18da72e",
    "obj_how-do-scan-strategy-rotation-angles-and-build-orientation-angles-influe_2248ccb8",
    "obj_how-do-scanning-strategy-scanning-speed-and-energy-density-affect-yield_6d508ef8",
    "obj_how-do-volumetric-energy-density-laser-power-scanning-speed-hatch-spacin_3df14419",
)
OBJECTIVE_EXPECTATIONS: dict[str, tuple[tuple[str, ...], ...]] = {
    DEFAULT_OBJECTIVE_IDS[0]: (("preheat", "build platform"), ("ductility", "elongation")),
    DEFAULT_OBJECTIVE_IDS[1]: (("heat treatment", "hip"), ("density", "microstructure")),
    DEFAULT_OBJECTIVE_IDS[2]: (("porosity", "pore"), ("pitting", "corrosion")),
    DEFAULT_OBJECTIVE_IDS[3]: (("orientation", "rotation angle"), ("yield strength",)),
    DEFAULT_OBJECTIVE_IDS[4]: (("scan", "energy density"), ("strength", "elongation")),
    DEFAULT_OBJECTIVE_IDS[5]: (("energy density", "ved"), ("fatigue", "defect")),
}
_SPACE_RE = re.compile(r"\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit published Objective Findings, exact evidence excerpts, and "
            "Source locators for materials-expert review readiness."
        )
    )
    parser.add_argument("--collection-id", default=DEFAULT_COLLECTION_ID)
    parser.add_argument("--objective-id", action="append", dest="objective_ids")
    parser.add_argument(
        "--api-base-url",
        help=(
            "Optional Lens origin such as http://localhost:5173. Set "
            "LENS_CHECK_EMAIL and LENS_CHECK_PASSWORD when login is required."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = check_objective_findings_projection(
        collection_id=args.collection_id,
        objective_ids=tuple(args.objective_ids or DEFAULT_OBJECTIVE_IDS),
        api_base_url=args.api_base_url,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "fail":
        raise SystemExit(1)


def check_objective_findings_projection(
    *,
    collection_id: str,
    objective_ids: tuple[str, ...] = DEFAULT_OBJECTIVE_IDS,
    api_base_url: str | None = None,
) -> dict[str, Any]:
    backend_root = str(DEFAULT_BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    source_index = _load_source_index(collection_id)
    cookie = _api_login_cookie(api_base_url.rstrip("/")) if api_base_url else ""
    objectives = []
    checks: list[dict[str, str]] = []
    for objective_id in objective_ids:
        payload = (
            _api_objective_bundle(
                api_base_url=api_base_url or "",
                cookie=cookie,
                collection_id=collection_id,
                objective_id=objective_id,
            )
            if api_base_url
            else _local_objective_bundle(collection_id, objective_id)
        )
        result = evaluate_objective_bundle(payload, source_index=source_index)
        objectives.append(result)
        checks.extend(result["checks"])
    return {
        "status": "fail" if any(item["status"] == "fail" for item in checks) else "pass",
        "collection_id": collection_id,
        "objective_count": len(objectives),
        "objectives": objectives,
        "checks": checks,
    }


def evaluate_objective_bundle(
    payload: dict[str, Any],
    *,
    source_index: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    objective = _mapping(payload.get("objective"))
    analysis = _mapping(payload.get("published_analysis"))
    findings = _mapping_list(payload.get("findings"))
    evidence_by_finding = {
        str(finding_id): _mapping_list(records)
        for finding_id, records in _mapping(payload.get("evidence_by_finding")).items()
    }
    objective_id = _text(objective.get("objective_id"))
    analysis_version = _int(analysis.get("analysis_version"))
    checks = [
        _check(objective_id, "objective is confirmed", objective.get("confirmation_status") == "confirmed"),
        _check(objective_id, "published analysis succeeded", analysis.get("status") == "succeeded"),
        _check(objective_id, "published analysis version is explicit", analysis_version > 0),
        _check(objective_id, "published analysis has Findings", bool(findings)),
    ]

    all_evidence: list[dict[str, Any]] = []
    for finding in findings:
        finding_id = _text(finding.get("finding_id"))
        evidence = evidence_by_finding.get(finding_id, [])
        all_evidence.extend(evidence)
        supporting_ids = set(
            _text_list(_mapping(finding.get("derivation")).get("supporting_evidence_ids"))
        )
        direct_records = [
            item
            for item in evidence
            if item.get("evidence_role") == "direct_result"
            and _text(item.get("evidence_id")) in supporting_ids
        ]
        direct_documents = {_text(item.get("document_id")) for item in direct_records}
        paper_count = _int(finding.get("paper_count"))
        level = _text(finding.get("finding_level"))
        checks.extend(
            [
                _check(
                    objective_id,
                    f"Finding {finding_id} uses the published composite identity",
                    bool(finding_id)
                    and finding.get("objective_id") == objective_id
                    and _int(finding.get("analysis_version")) == analysis_version,
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} has variables and outcomes",
                    bool(_text_list(finding.get("variables")))
                    and bool(_text_list(finding.get("outcomes"))),
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} has direct result evidence",
                    bool(direct_records),
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} paper count matches direct evidence",
                    paper_count == len(direct_documents),
                    f"paper_count={paper_count}; direct_documents={sorted(direct_documents)}",
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} level matches paper support",
                    (level == "paper" and paper_count == 1)
                    or (level == "cross_paper" and paper_count >= 2),
                    f"level={level}; paper_count={paper_count}",
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} references only returned Evidence",
                    supporting_ids
                    <= {_text(item.get("evidence_id")) for item in evidence},
                    f"supporting={sorted(supporting_ids)}; returned={sorted(_text(item.get('evidence_id')) for item in evidence)}",
                ),
            ]
        )

    source_results = [_audit_source_record(item, source_index) for item in all_evidence]
    checks.extend(
        [
            _check(
                objective_id,
                "all Evidence records have exact source locators",
                bool(all_evidence) and all(item["locator_matches"] for item in source_results),
                _failed_source_ids(source_results, "locator_matches"),
            ),
            _check(
                objective_id,
                "all Evidence excerpts match Source artifacts",
                bool(all_evidence) and all(item["excerpt_matches"] for item in source_results),
                _failed_source_ids(source_results, "excerpt_matches"),
            ),
            _check(
                objective_id,
                "all Evidence pages match Source artifacts",
                bool(all_evidence) and all(item["page_matches"] for item in source_results),
                _failed_source_ids(source_results, "page_matches"),
            ),
        ]
    )
    expected_terms = OBJECTIVE_EXPECTATIONS.get(objective_id, ())
    if expected_terms:
        finding_text = _normalized_text(" ".join(_text(item.get("statement")) for item in findings))
        missing = [
            list(group)
            for group in expected_terms
            if not any(_normalized_text(term) in finding_text for term in group)
        ]
        checks.append(
            _check(
                objective_id,
                "Findings cover the objective-specific material result",
                not missing,
                f"missing_term_groups={missing}",
            )
        )
    return {
        "objective_id": objective_id,
        "question": _text(objective.get("question")),
        "analysis_version": analysis_version,
        "finding_count": len(findings),
        "evidence_count": len(all_evidence),
        "source_audit": source_results,
        "checks": checks,
    }


def _local_objective_bundle(collection_id: str, objective_id: str) -> dict[str, Any]:
    with contextlib.redirect_stdout(io.StringIO()):
        from infra.persistence.database import (  # noqa: PLC0415
            DatabaseSettings,
            build_database_engine,
            build_session_factory,
        )
        from infra.persistence.postgres.objective_repository import (  # noqa: PLC0415
            PostgresObjectiveRepository,
        )

        engine = build_database_engine(DatabaseSettings())
        try:
            repository = PostgresObjectiveRepository(build_session_factory(engine))
            objective = repository.read_objective(collection_id, objective_id)
            if objective is None or objective.published_analysis_version is None:
                raise FileNotFoundError(
                    f"published research objective not found: {collection_id}/{objective_id}"
                )
            version = objective.published_analysis_version
            analysis = repository.read_analysis(collection_id, objective_id, version)
            findings, _ = repository.list_findings(
                collection_id, objective_id, version, offset=0, limit=500
            )
            evidence_by_finding = {}
            for finding in findings:
                evidence, _ = repository.list_evidence(
                    collection_id,
                    objective_id,
                    version,
                    finding_id=finding.finding_id,
                    offset=0,
                    limit=1000,
                )
                evidence_by_finding[finding.finding_id] = [
                    item.to_record() for item in evidence
                ]
        finally:
            engine.dispose()
    return {
        "objective": objective.to_record(),
        "published_analysis": analysis.to_record() if analysis else None,
        "findings": [item.to_record() for item in findings],
        "evidence_by_finding": evidence_by_finding,
    }


def _api_objective_bundle(
    *,
    api_base_url: str,
    cookie: str,
    collection_id: str,
    objective_id: str,
) -> dict[str, Any]:
    base = api_base_url.rstrip("/")
    state = _api_json_request(
        base,
        f"/api/v1/collections/{collection_id}/objectives/{objective_id}/analysis",
        cookie=cookie,
    )
    analysis = _mapping(state.get("published_analysis"))
    version = _int(analysis.get("analysis_version"))
    if version < 1:
        raise RuntimeError(f"Objective has no published analysis: {objective_id}")
    query = urlencode({"analysis_version": version, "offset": 0, "limit": 200})
    finding_page = _api_json_request(
        base,
        f"/api/v1/collections/{collection_id}/objectives/{objective_id}/findings?{query}",
        cookie=cookie,
    )
    findings = _mapping_list(finding_page.get("items"))
    evidence_by_finding = {}
    for finding in findings:
        finding_id = _text(finding.get("finding_id"))
        evidence_query = urlencode(
            {
                "analysis_version": version,
                "finding_id": finding_id,
                "offset": 0,
                "limit": 500,
            }
        )
        page = _api_json_request(
            base,
            f"/api/v1/collections/{collection_id}/objectives/{objective_id}/evidence?{evidence_query}",
            cookie=cookie,
        )
        evidence_by_finding[finding_id] = _mapping_list(page.get("items"))
    return {
        "objective": state.get("objective"),
        "published_analysis": analysis,
        "findings": findings,
        "evidence_by_finding": evidence_by_finding,
    }


def _load_source_index(collection_id: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    with contextlib.redirect_stdout(io.StringIO()):
        from infra.persistence.database import (  # noqa: PLC0415
            DatabaseSettings,
            build_database_engine,
            build_session_factory,
        )
        from infra.persistence.postgres.source_artifact_repository import (  # noqa: PLC0415
            PostgresSourceArtifactRepository,
        )

        engine = build_database_engine(DatabaseSettings())
        try:
            artifacts = PostgresSourceArtifactRepository(
                build_session_factory(engine)
            ).read_collection_artifacts(collection_id)
        finally:
            engine.dispose()
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for block in artifacts.blocks:
        index[(block.document_id, "text_window", block.block_id)] = {
            "text": _text(block.text)[:12_000],
            "page": getattr(block, "page", None),
        }
    for table in artifacts.tables:
        record = table.to_record()
        index[(table.document_id, "table", table.table_id)] = {
            "text": _text(
                record.get("table_markdown")
                or record.get("table_text")
                or record.get("caption_text")
            )[:12_000],
            "page": getattr(table, "page", None),
        }
    for figure in artifacts.figures:
        index[(figure.document_id, "figure", figure.figure_id)] = {
            "text": _text(getattr(figure, "caption_text", None))[:12_000],
            "page": getattr(figure, "page", None),
        }
    return index


def _audit_source_record(
    evidence: dict[str, Any],
    source_index: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    key = (
        _text(evidence.get("document_id")),
        _text(evidence.get("source_kind")),
        _text(evidence.get("source_ref")),
    )
    source = source_index.get(key)
    excerpt = _normalized_text(evidence.get("source_excerpt"))
    source_text = _normalized_text(source.get("text")) if source else ""
    pages = {_int(page) for page in evidence.get("page_numbers") or [] if _int(page) > 0}
    source_page = _int(source.get("page")) if source else 0
    return {
        "evidence_id": _text(evidence.get("evidence_id")),
        "document_id": key[0],
        "source_kind": key[1],
        "source_ref": key[2],
        "locator_matches": source is not None,
        "excerpt_matches": bool(source_text) and excerpt == source_text,
        "page_matches": source is not None
        and (not pages or source_page == 0 or source_page in pages),
    }


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
        f"{base_url}{path}", data=body, headers=headers, method=method
    )
    try:
        with request_url.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
            return (
                {"payload": data, "headers": response.headers}
                if include_headers
                else data
            )
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Lens API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Lens API request failed: {exc}") from exc


def _check(
    objective_id: str,
    name: str,
    passed: bool,
    detail: str = "",
) -> dict[str, str]:
    return {
        "status": "pass" if passed else "fail",
        "objective_id": objective_id,
        "check": name,
        "detail": detail,
    }


def _failed_source_ids(results: list[dict[str, Any]], field: str) -> str:
    return f"failed={[item['evidence_id'] for item in results if not item[field]]}"


def _normalized_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", _text(value)).casefold()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _text_list(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [text for item in values if (text := _text(item))]


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    main()
