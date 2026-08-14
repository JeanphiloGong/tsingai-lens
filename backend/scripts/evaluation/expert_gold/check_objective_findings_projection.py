#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime
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
from urllib.parse import urlencode


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_SPACE_RE = re.compile(r"\s+")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_NUMBER_RE = re.compile(
    r"(?<![\w.])[-+]?(?:\d+(?:[.,]\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![\w.])"
)
_MULTIPLICATION_SCIENTIFIC_RE = re.compile(
    r"(?<![\w.])([-+]?(?:\d+(?:[.,]\d*)?|\.\d+))\s*[x×]\s*"
    r"10\s*(?:\^|\*\*)?\s*([-+⁻⁺]?[0-9⁰¹²³⁴⁵⁶⁷⁸⁹]+)(?![\w.])",
    re.IGNORECASE,
)
_OPPOSING_DIRECTIONS = {
    "increase": {"decrease", "no_change"},
    "decrease": {"increase", "no_change"},
    "improve": {"worsen", "no_change"},
    "worsen": {"improve", "no_change"},
    "no_change": {"increase", "decrease", "improve", "worsen"},
}
_TABLE_SYMBOL_AXES = {
    "alpha": "build orientation alpha angle",
    "beta": "build orientation beta angle",
    "theta": "scan strategy rotation angle",
    "ved": "volumetric energy density",
}
_TABLE_SAMPLE_HEADERS = {
    "case",
    "id",
    "no",
    "sample",
    "sample id",
    "sample no",
    "sample number",
    "specimen",
    "specimen id",
}
_RESULT_QUALIFIERS = {"experiment", "experimental", "model", "prediction"}


def load_acceptance_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("acceptance manifest must be a JSON object")
    if payload.get("schema_version") != "objective_finding_material_acceptance.v1":
        raise ValueError("unsupported acceptance manifest schema_version")
    documents = _mapping_list(payload.get("documents"))
    document_hashes = {_text(item.get("sha256")) for item in documents}
    paper_ids = {_text(item.get("paper_id")) for item in documents}
    if (
        len(documents) != 6
        or len(document_hashes) != len(documents)
        or len(paper_ids) != len(documents)
        or any(_SHA256_RE.fullmatch(digest) is None for digest in document_hashes)
    ):
        raise ValueError(
            "acceptance manifest requires exactly six papers with unique documents"
        )
    objectives = _mapping_list(payload.get("objectives"))
    objective_keys = {_text(item.get("key")) for item in objectives}
    if (
        len(objectives) < 3
        or "" in objective_keys
        or len(objective_keys) != len(objectives)
    ):
        if len(objectives) < 3:
            raise ValueError("acceptance manifest requires at least three objectives")
        raise ValueError("acceptance manifest requires unique objectives")
    if any(
        not item.get("question_term_groups") or not item.get("expected_term_groups")
        for item in objectives
    ):
        raise ValueError("acceptance objectives require question and result terms")
    statuses = set(_text_list(payload.get("required_review_statuses")))
    if statuses != {"correct", "partial", "incorrect"}:
        raise ValueError("acceptance manifest requires correct, partial, and incorrect")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit published Objective Findings, exact evidence excerpts, and "
            "Source locators for materials-expert review readiness."
        )
    )
    parser.add_argument("--collection-id", required=True)
    parser.add_argument(
        "--objective-id",
        action="append",
        dest="objective_ids",
        required=True,
        help="Repeat for every Objective included in the expert acceptance run.",
    )
    parser.add_argument(
        "--api-base-url",
        help=(
            "Optional Lens origin such as http://localhost:5173. Set "
            "LENS_CHECK_EMAIL and LENS_CHECK_PASSWORD when login is required."
        ),
    )
    parser.add_argument(
        "--acceptance-manifest",
        type=Path,
        required=True,
        help="Approved papers, Objectives, and review decisions for this run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = load_acceptance_manifest(args.acceptance_manifest)
    summary = check_objective_findings_projection(
        collection_id=args.collection_id,
        objective_ids=tuple(args.objective_ids),
        api_base_url=args.api_base_url,
        acceptance_manifest=manifest,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["verdict"] != "pass":
        raise SystemExit(1)


def check_objective_findings_projection(
    *,
    collection_id: str,
    objective_ids: tuple[str, ...],
    api_base_url: str | None = None,
    acceptance_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not collection_id.strip():
        raise ValueError("collection_id is required")
    if not objective_ids:
        raise ValueError("at least one objective_id is required")
    if acceptance_manifest is None:
        raise ValueError("acceptance_manifest is required for real expert acceptance")
    if len(set(objective_ids)) < 3:
        raise ValueError("at least three objective_ids are required for real acceptance")
    backend_root = str(DEFAULT_BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    manifest_objectives: list[dict[str, Any]] = []
    expected_document_ids: set[str] | None = None
    required_review_statuses: set[str] = set()
    manifest_objectives = _mapping_list(acceptance_manifest["objectives"])
    expected_document_ids = _resolve_manifest_document_ids(
        collection_id,
        _mapping_list(acceptance_manifest["documents"]),
    )
    required_review_statuses = set(acceptance_manifest["required_review_statuses"])
    source_index = _load_source_index(collection_id)
    cookie = _api_login_cookie(api_base_url.rstrip("/")) if api_base_url else ""
    objectives = []
    checks: list[dict[str, str]] = []
    matched_objective_keys: set[str] = set()
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
        expectation = (
            _manifest_objective_for_question(
                _text(_mapping(payload.get("objective")).get("question")),
                manifest_objectives,
            )
            if manifest_objectives
            else {}
        )
        expectation_key = _text(expectation.get("key"))
        if expectation_key in matched_objective_keys:
            raise ValueError(
                "real acceptance requires distinct acceptance objectives; "
                f"duplicate manifest key: {expectation_key}"
            )
        matched_objective_keys.add(expectation_key)
        result = evaluate_objective_bundle(
            payload,
            source_index=source_index,
            expected_document_ids=expected_document_ids,
            expected_term_groups=expectation.get("expected_term_groups"),
        )
        objectives.append(result)
        checks.extend(result["checks"])
    if required_review_statuses:
        checks.append(
            _required_review_status_check(
                required=required_review_statuses,
                objectives=objectives,
            )
        )
    return {
        "verdict": _combined_verdict(
            [item["verdict"] for item in objectives]
            + [_checks_verdict(checks[-1:]) if required_review_statuses else "pass"]
        ),
        "collection_id": collection_id,
        "acceptance_schema_version": acceptance_manifest.get("schema_version"),
        "objective_count": len(objectives),
        "objectives": objectives,
        "checks": checks,
    }


def evaluate_objective_bundle(
    payload: dict[str, Any],
    *,
    source_index: dict[tuple[str, str, str], dict[str, Any]],
    expected_document_ids: set[str] | None = None,
    expected_term_groups: list[list[str]] | None = None,
) -> dict[str, Any]:
    objective = _mapping(payload.get("objective"))
    analysis = _mapping(payload.get("published_analysis"))
    paper_contributions = _mapping_list(payload.get("paper_contributions"))
    findings = _mapping_list(payload.get("findings"))
    evidence_by_finding = {
        str(finding_id): _mapping_list(records)
        for finding_id, records in _mapping(payload.get("evidence_by_finding")).items()
    }
    feedback_by_finding = {
        str(finding_id): _mapping_list(records)
        for finding_id, records in _mapping(payload.get("feedback_by_finding")).items()
    }
    curations_by_finding = {
        str(finding_id): _mapping_list(records)
        for finding_id, records in _mapping(payload.get("curations_by_finding")).items()
    }
    dataset_by_finding = {
        _text(item.get("finding_id")): item
        for item in _mapping_list(payload.get("dataset_items"))
    }
    training_rows = _mapping_list(payload.get("training_jsonl_rows"))
    collection_id = _text(objective.get("collection_id"))
    objective_id = _text(objective.get("objective_id"))
    analysis_version = _int(analysis.get("analysis_version"))
    processed_document_count = _int(analysis.get("processed_document_count"))
    total_document_count = _int(analysis.get("total_document_count"))
    contribution_documents = {
        _text(item.get("document_id")) for item in paper_contributions
    }
    terminal_contributions = [
        item
        for item in paper_contributions
        if item.get("analysis_status") in {"analyzed", "excluded"}
    ]
    checks = [
        _check(
            objective_id,
            "objective is confirmed",
            objective.get("confirmation_status") == "confirmed",
            blocker=True,
        ),
        _check(
            objective_id,
            "published analysis succeeded",
            analysis.get("status") == "succeeded",
            blocker=True,
        ),
        _check(
            objective_id,
            "published analysis version is explicit",
            analysis_version > 0,
            blocker=True,
        ),
        _check(
            objective_id,
            "published analysis uses the Objective composite identity",
            bool(collection_id)
            and analysis.get("collection_id") == collection_id
            and analysis.get("objective_id") == objective_id
            and analysis_version > 0,
            blocker=True,
        ),
        _check(
            objective_id,
            "published analysis has Findings",
            bool(findings),
            blocker=True,
        ),
        _check(
            objective_id,
            "analysis traversed every candidate paper",
            total_document_count > 0
            and processed_document_count == total_document_count,
            f"processed={processed_document_count}; total={total_document_count}",
            blocker=True,
        ),
        _check(
            objective_id,
            "analysis has one terminal PaperContribution per candidate paper",
            len(contribution_documents) == total_document_count
            and len(terminal_contributions) == total_document_count,
            (
                f"documents={sorted(contribution_documents)}; "
                f"statuses={[item.get('analysis_status') for item in paper_contributions]}"
            ),
            blocker=True,
        ),
    ]
    if expected_document_ids is not None:
        checks.append(
            _check(
                objective_id,
                "analysis covers the approved paper set",
                contribution_documents == expected_document_ids
                and total_document_count == len(expected_document_ids),
                (
                    f"expected={sorted(expected_document_ids)}; "
                    f"actual={sorted(contribution_documents)}"
                ),
                blocker=True,
            )
        )

    all_evidence: list[dict[str, Any]] = []
    for finding in findings:
        finding_id = _text(finding.get("finding_id"))
        evidence = evidence_by_finding.get(finding_id, [])
        all_evidence.extend(evidence)
        contributions = _mapping_list(finding.get("paper_contributions"))
        referenced_ids = {
            evidence_id
            for contribution in contributions
            for field in (
                "supporting_evidence_ids",
                "contradicting_evidence_ids",
                "context_evidence_ids",
                "condition_boundary_evidence_ids",
            )
            for evidence_id in _text_list(contribution.get(field))
        }
        direct_ids = {
            evidence_id
            for contribution in contributions
            for field in ("supporting_evidence_ids", "contradicting_evidence_ids")
            for evidence_id in _text_list(contribution.get(field))
        }
        direct_records = [
            item
            for item in evidence
            if item.get("evidence_role")
            in {"direct_result", "contradictory_result"}
            and _text(item.get("evidence_id")) in direct_ids
        ]
        direct_document_by_id = {
            _text(item.get("evidence_id")): _text(item.get("document_id"))
            for item in direct_records
        }
        factor_keys = {
            _table_header_key(item) for item in _text_list(finding.get("factors"))
        }
        direct_factor_sets = [
            {
                _table_header_key(variable.get("name"))
                for variable in _mapping_list(item.get("changed_variables"))
            }
            for item in direct_records
        ]
        supporting_ids = {
            evidence_id
            for contribution in contributions
            for evidence_id in _text_list(
                contribution.get("supporting_evidence_ids")
            )
        }
        contradicting_ids = direct_ids - supporting_ids
        supporting_scopes = {
            _text(item.get("attribution_scope"))
            for item in direct_records
            if _text(item.get("evidence_id")) in supporting_ids
        }
        expected_attribution = _finding_attribution_scope(
            factor_count=len(factor_keys),
            evidence_scopes=supporting_scopes,
        )
        has_coupled_variables = any(
            len(_mapping_list(item.get("changed_variables"))) > 1
            for item in direct_records
        )
        direct_result_issues = _direct_result_issues(
            finding,
            direct_records,
            supporting_ids=supporting_ids,
            contradicting_ids=contradicting_ids,
        )
        experiment_binding_issues = _experiment_binding_issues(direct_records)
        sample_state_issues = _sample_state_confounding_issues(direct_records)
        direct_documents = {_text(item.get("document_id")) for item in direct_records}
        bound_direct_documents = {
            _text(contribution.get("document_id"))
            for contribution in contributions
            if any(
                evidence_id in direct_ids
                for evidence_id in (
                    _text_list(contribution.get("supporting_evidence_ids"))
                    + _text_list(contribution.get("contradicting_evidence_ids"))
                )
            )
        }
        direct_bindings_match = all(
            direct_document_by_id.get(evidence_id)
            == _text(contribution.get("document_id"))
            for contribution in contributions
            for field in ("supporting_evidence_ids", "contradicting_evidence_ids")
            for evidence_id in _text_list(contribution.get(field))
        )
        synthesis_status = _text(finding.get("synthesis_status"))
        synthesis_issues = _synthesis_status_issues(
            synthesis_status=synthesis_status,
            contributions=contributions,
            evidence=evidence,
            direct_records=direct_records,
            supporting_ids=supporting_ids,
            contradicting_ids=contradicting_ids,
        )
        statement_issues = _finding_statement_issues(
            finding,
            [
                item
                for item in direct_records
                if _text(item.get("evidence_id")) in supporting_ids
            ],
        )
        checks.extend(
            [
                _check(
                    objective_id,
                    f"Finding {finding_id} uses the published composite identity",
                    bool(finding_id)
                    and finding.get("collection_id") == collection_id
                    and finding.get("objective_id") == objective_id
                    and _int(finding.get("analysis_version")) == analysis_version,
                    blocker=True,
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} Evidence uses the published composite identity",
                    bool(evidence)
                    and all(
                        item.get("collection_id") == collection_id
                        and item.get("objective_id") == objective_id
                        and _int(item.get("analysis_version")) == analysis_version
                        for item in evidence
                    ),
                    blocker=True,
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} has factors and one outcome",
                    bool(_text_list(finding.get("factors")))
                    and bool(_text(finding.get("outcome"))),
                    blocker=True,
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} has direct result evidence",
                    bool(direct_records),
                    blocker=True,
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} direct paper bindings match Evidence",
                    bound_direct_documents == direct_documents
                    and direct_bindings_match,
                    f"bindings={sorted(bound_direct_documents)}; evidence={sorted(direct_documents)}",
                    blocker=True,
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} synthesis matches direct paper support",
                    synthesis_status == "insufficient_confirmation"
                    or len(direct_documents) >= 2,
                    f"synthesis_status={synthesis_status}; direct_documents={sorted(direct_documents)}",
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} synthesis status matches Evidence roles",
                    not synthesis_issues,
                    f"issues={synthesis_issues}",
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} references only returned Evidence",
                    referenced_ids
                    <= {_text(item.get("evidence_id")) for item in evidence},
                    f"referenced={sorted(referenced_ids)}; returned={sorted(_text(item.get('evidence_id')) for item in evidence)}",
                    blocker=True,
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} factors cover every direct Evidence changed variable",
                    bool(direct_factor_sets)
                    and all(factor_keys == item for item in direct_factor_sets),
                    f"factors={sorted(factor_keys)}; evidence={direct_factor_sets}",
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} attribution matches direct Evidence",
                    _text(finding.get("attribution_scope")) == expected_attribution,
                    (
                        f"finding={_text(finding.get('attribution_scope'))}; "
                        f"expected={expected_attribution}; evidence={sorted(supporting_scopes)}"
                    ),
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} does not overclaim coupled variables",
                    not has_coupled_variables
                    or (
                        finding.get("assertion_strength") != "causal"
                        and finding.get("attribution_scope") != "isolated_effect"
                    ),
                    (
                        f"assertion={finding.get('assertion_strength')}; "
                        f"attribution={finding.get('attribution_scope')}"
                    ),
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} outcome and direction match direct Evidence",
                    not direct_result_issues,
                    f"issues={direct_result_issues}",
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} values and experiment groups match source text",
                    not experiment_binding_issues,
                    f"issues={experiment_binding_issues}",
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} statement values bind to one supporting Evidence",
                    not statement_issues,
                    f"issues={statement_issues}",
                ),
                _check(
                    objective_id,
                    f"Finding {finding_id} excludes sample-state confounding",
                    not sample_state_issues,
                    f"issues={sample_state_issues}",
                ),
            ]
        )
        expected_label, expected_use, expected_target = _expected_dataset_status(
            feedback_by_finding.get(finding_id, []),
            curations_by_finding.get(finding_id, []),
        )
        dataset_item = dataset_by_finding.get(finding_id)
        if "dataset_items" in payload:
            checks.append(
                _check(
                    objective_id,
                    f"Finding {finding_id} latest expert event controls dataset status",
                    dataset_item is not None
                    and dataset_item.get("label_status") == expected_label
                    and dataset_item.get("dataset_use_status") == expected_use
                    and dataset_item.get("expert_target") == expected_target,
                    (
                        f"expected=({expected_label}, {expected_use}); "
                        f"actual=({(dataset_item or {}).get('label_status')}, "
                        f"{(dataset_item or {}).get('dataset_use_status')})"
                    ),
                )
            )

    if "training_jsonl_rows" in payload:
        training_issues = _training_export_issues(
            dataset_items=_mapping_list(payload.get("dataset_items")),
            training_rows=training_rows,
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
            evidence_by_finding=evidence_by_finding,
        )
        checks.append(
            _check(
                objective_id,
                "training_jsonl contains exactly the latest training-ready Findings",
                not training_issues,
                f"issues={training_issues}",
                blocker=True,
            )
        )

    source_results = [_audit_source_record(item, source_index) for item in all_evidence]
    checks.extend(
        [
            _check(
                objective_id,
                "all Evidence records have exact source locators",
                bool(all_evidence)
                and all(item["locator_matches"] for item in source_results),
                _failed_source_ids(source_results, "locator_matches"),
                blocker=True,
            ),
            _check(
                objective_id,
                "all Evidence excerpts match Source artifacts",
                bool(all_evidence)
                and all(item["excerpt_matches"] for item in source_results),
                _failed_source_ids(source_results, "excerpt_matches"),
                blocker=True,
            ),
            _check(
                objective_id,
                "all Evidence pages match Source artifacts",
                bool(all_evidence)
                and all(item["page_matches"] for item in source_results),
                _failed_source_ids(source_results, "page_matches"),
                blocker=True,
            ),
            _check(
                objective_id,
                "all table Evidence values bind to the named experiment rows",
                bool(all_evidence)
                and all(item["table_binding_matches"] for item in source_results),
                _failed_source_ids(source_results, "table_binding_matches"),
            ),
        ]
    )
    if expected_term_groups:
        finding_text = _normalized_text(
            " ".join(
                " ".join(
                    [
                        _text(item.get("statement")),
                        *_text_list(item.get("factors")),
                        _text(item.get("outcome")),
                    ]
                )
                for item in findings
            )
        )
        missing = [
            group
            for group in expected_term_groups
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
    review_statuses = sorted(
        {
            _text(item.get("review_status"))
            for records in feedback_by_finding.values()
            for item in records
            if _text(item.get("review_status"))
        }
    )
    return {
        "verdict": _checks_verdict(checks),
        "objective_id": objective_id,
        "question": _text(objective.get("question")),
        "analysis_version": analysis_version,
        "finding_count": len(findings),
        "evidence_count": len(all_evidence),
        "review_statuses": review_statuses,
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
        from infra.persistence.postgres.finding_review_repository import (  # noqa: PLC0415
            PostgresFindingReviewRepository,
        )
        from application.evaluation import FindingFeedbackService  # noqa: PLC0415

        engine = build_database_engine(DatabaseSettings())
        try:
            session_factory = build_session_factory(engine)
            repository = PostgresObjectiveRepository(session_factory)
            review_repository = PostgresFindingReviewRepository(session_factory)
            feedback_service = FindingFeedbackService(
                review_repository=review_repository,
                objective_repository=repository,
            )
            objective = repository.read_objective(collection_id, objective_id)
            if objective is None or objective.published_analysis_version is None:
                raise FileNotFoundError(
                    f"published research objective not found: {collection_id}/{objective_id}"
                )
            version = objective.published_analysis_version
            analysis = repository.read_analysis(collection_id, objective_id, version)
            paper_contributions = repository.list_contributions(
                collection_id, objective_id, version
            )
            findings, _ = repository.list_findings(
                collection_id, objective_id, version, offset=0, limit=500
            )
            evidence_by_finding = {}
            feedback_by_finding = {}
            curations_by_finding = {}
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
                feedback_by_finding[finding.finding_id] = [
                    item.to_record()
                    for item in review_repository.list_feedback(
                        collection_id, objective_id, version, finding.finding_id
                    )
                ]
                curations_by_finding[finding.finding_id] = [
                    item.to_record()
                    for item in review_repository.list_curations(
                        collection_id, objective_id, version, finding.finding_id
                    )
                ]
            dataset = feedback_service.export_dataset(
                collection_id=collection_id,
                objective_id=objective_id,
            )
        finally:
            engine.dispose()
    return {
        "objective": objective.to_record(),
        "published_analysis": analysis.to_record() if analysis else None,
        "paper_contributions": [item.to_record() for item in paper_contributions],
        "findings": [item.to_record() for item in findings],
        "evidence_by_finding": evidence_by_finding,
        "feedback_by_finding": feedback_by_finding,
        "curations_by_finding": curations_by_finding,
        "dataset_items": dataset["items"],
        "training_jsonl_rows": [
            {
                "messages": item["training_messages"],
                "metadata": item["metadata"],
            }
            for item in dataset["items"]
            if item.get("dataset_use_status") == "training_ready"
            and item.get("training_messages")
        ],
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
    paper_contributions = (
        _mapping_list(findings[0].get("paper_contributions")) if findings else []
    )
    evidence_by_finding = {}
    feedback_by_finding = {}
    curations_by_finding = {}
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
        review_query = urlencode({"analysis_version": version})
        feedback_page = _api_json_request(
            base,
            (
                f"/api/v1/collections/{collection_id}/objectives/{objective_id}/"
                f"findings/{finding_id}/feedback?{review_query}"
            ),
            cookie=cookie,
        )
        feedback_by_finding[finding_id] = _mapping_list(feedback_page.get("items"))
        curation_page = _api_json_request(
            base,
            (
                f"/api/v1/collections/{collection_id}/objectives/{objective_id}/"
                f"findings/{finding_id}/curation?{review_query}"
            ),
            cookie=cookie,
        )
        curations_by_finding[finding_id] = _mapping_list(curation_page.get("items"))
    dataset = _api_json_request(
        base,
        f"/api/v1/collections/{collection_id}/objectives/{objective_id}/finding-dataset",
        cookie=cookie,
    )
    training_rows = _api_jsonl_request(
        base,
        (
            f"/api/v1/collections/{collection_id}/objectives/{objective_id}/"
            "finding-dataset?format=training_jsonl"
        ),
        cookie=cookie,
    )
    return {
        "objective": state.get("objective"),
        "published_analysis": analysis,
        "paper_contributions": paper_contributions,
        "findings": findings,
        "evidence_by_finding": evidence_by_finding,
        "feedback_by_finding": feedback_by_finding,
        "curations_by_finding": curations_by_finding,
        "dataset_items": _mapping_list(dataset.get("items")),
        "training_jsonl_rows": training_rows,
    }


def _load_source_index(
    collection_id: str,
) -> dict[tuple[str, str, str], dict[str, Any]]:
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
            documents = PostgresSourceArtifactRepository(
                build_session_factory(engine)
            ).read_collection_documents(collection_id)
        finally:
            engine.dispose()
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for block in (item for document in documents for item in document.blocks):
        index[(block.document_id, "text_window", block.block_id)] = {
            "text": _text(block.text)[:12_000],
            "page": getattr(block, "page", None),
        }
    for table in (item for document in documents for item in document.tables):
        record = table.to_record()
        index[(table.document_id, "table", table.table_id)] = {
            "text": _text(
                record.get("table_markdown")
                or record.get("table_text")
                or record.get("caption_text")
            )[:12_000],
            "page": getattr(table, "page", None),
            "rows": record.get("table_matrix") or [],
        }
    for figure in (item for document in documents for item in document.figures):
        index[(figure.document_id, "figure", figure.figure_id)] = {
            "text": _text(getattr(figure, "caption_text", None))[:12_000],
            "page": getattr(figure, "page", None),
        }
    return index


def _resolve_manifest_document_ids(
    collection_id: str,
    documents: list[dict[str, Any]],
) -> set[str]:
    expected_hashes = {_text(item.get("sha256")) for item in documents}
    with contextlib.redirect_stdout(io.StringIO()):
        from sqlalchemy import select  # noqa: PLC0415

        from infra.persistence.database import (  # noqa: PLC0415
            DatabaseSettings,
            build_database_engine,
            build_session_factory,
        )
        from infra.persistence.postgres.models.build import (  # noqa: PLC0415
            CollectionActiveBuild,
        )
        from infra.persistence.postgres.models.document import (  # noqa: PLC0415
            DocumentVersion,
        )
        from infra.persistence.postgres.models.source import (  # noqa: PLC0415
            SourceDocument,
        )

        engine = build_database_engine(DatabaseSettings())
        try:
            with build_session_factory(engine)() as session:
                rows = session.execute(
                    select(SourceDocument.source_document_id, DocumentVersion.sha256)
                    .join(
                        DocumentVersion,
                        DocumentVersion.document_version_id
                        == SourceDocument.document_version_id,
                    )
                    .join(
                        CollectionActiveBuild,
                        (CollectionActiveBuild.collection_id == collection_id)
                        & (CollectionActiveBuild.build_id == SourceDocument.build_id),
                    )
                    .where(
                        SourceDocument.collection_id == collection_id,
                        DocumentVersion.sha256.in_(expected_hashes),
                    )
                ).all()
        finally:
            engine.dispose()
    document_ids_by_hash: dict[str, set[str]] = {}
    for document_id, digest in rows:
        document_ids_by_hash.setdefault(str(digest), set()).add(str(document_id))
    unresolved = {
        digest: sorted(document_ids_by_hash.get(digest, set()))
        for digest in expected_hashes
        if len(document_ids_by_hash.get(digest, set())) != 1
    }
    if unresolved:
        raise RuntimeError(
            "acceptance papers must resolve exactly once in the active Source build: "
            f"{unresolved}"
        )
    return {
        next(iter(document_ids_by_hash[digest])) for digest in expected_hashes
    }


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
    related_sources: dict[str, dict[str, Any]] = {}
    related_locators_match = True
    related_pages_match = True
    for ref in _mapping_list(evidence.get("related_source_refs")):
        source_ref = _text(ref.get("source_ref"))
        source_kind = _text(ref.get("source_kind"))
        if not source_ref or not source_kind:
            related_locators_match = False
            related_pages_match = False
            continue
        related_source = source_index.get((key[0], source_kind, source_ref))
        if related_source is None:
            related_locators_match = False
            related_pages_match = False
            continue
        related_sources[source_ref] = related_source
        related_pages_match = related_pages_match and (
            _int(ref.get("page")) > 0
            and _int(ref.get("page")) == _int(related_source.get("page"))
        )
    table_sources = {key[2]: source, **related_sources} if source else {}
    raw_excerpt = _text(evidence.get("source_excerpt"))
    excerpt = _normalized_text(raw_excerpt)
    source_text = _normalized_text(source.get("text")) if source else ""
    excerpt_matches = bool(source_text) and excerpt == source_text
    if key[1] == "table" and source is not None:
        excerpt_matches = (
            _composite_table_excerpt_matches_refs(
                raw_excerpt,
                evidence=evidence,
                sources=table_sources,
            )
            if len(table_sources) > 1
            else _table_excerpt_matches_source(raw_excerpt, source)
        )
    pages = {
        _int(page) for page in evidence.get("page_numbers") or [] if _int(page) > 0
    }
    source_page = _int(source.get("page")) if source else 0
    table_binding_matches = True
    if (
        evidence.get("source_kind") == "table"
        and evidence.get("evidence_role")
        in {"direct_result", "contradictory_result"}
    ):
        table_binding_matches = (
            _composite_table_evidence_binding_matches(evidence, table_sources)
            if len(table_sources) > 1
            else _table_evidence_binding_matches(evidence, source)
        )
    return {
        "evidence_id": _text(evidence.get("evidence_id")),
        "document_id": key[0],
        "source_kind": key[1],
        "source_ref": key[2],
        "locator_matches": source is not None and related_locators_match,
        "excerpt_matches": excerpt_matches,
        "page_matches": source is not None
        and bool(pages)
        and source_page > 0
        and pages == {source_page}
        and related_pages_match,
        "table_binding_matches": table_binding_matches,
    }


def _table_excerpt_matches_source(
    excerpt: str,
    source: dict[str, Any],
) -> bool:
    excerpt_lines = _normalized_lines(excerpt)
    source_lines = _normalized_lines(source.get("text"))
    if source_lines and excerpt_lines == source_lines:
        return True
    rows = [
        [_text(cell) for cell in row]
        for row in source.get("rows") or []
        if isinstance(row, list)
    ]
    if len(rows) < 2:
        return False
    headers = rows[0]
    canonical_rows = {
        _normalized_text(
            " | ".join(
                f"{header}: {row[index]}"
                for index, header in enumerate(headers)
                if index < len(row)
            )
        )
        for row in rows[1:]
    }
    excerpt_rows = set(excerpt_lines)
    return bool(excerpt_rows) and excerpt_rows <= canonical_rows


def _composite_table_excerpt_matches_refs(
    excerpt: str,
    *,
    evidence: dict[str, Any],
    sources: dict[str, dict[str, Any]],
) -> bool:
    expected_rows: set[str] = set()
    for ref in _mapping_list(evidence.get("related_source_refs")):
        source_ref = _text(ref.get("source_ref"))
        row_index = _int(ref.get("row_index"))
        source = sources.get(source_ref)
        rows = [
            [_text(cell) for cell in row]
            for row in (source or {}).get("rows") or []
            if isinstance(row, list)
        ]
        if row_index <= 0 or row_index >= len(rows):
            return False
        headers = rows[0]
        row = rows[row_index]
        expected_rows.add(
            _normalized_text(
                " | ".join(
                    f"{header}: {row[index]}"
                    for index, header in enumerate(headers)
                    if index < len(row)
                )
            )
        )
    return bool(expected_rows) and set(_normalized_lines(excerpt)) == expected_rows


def _composite_table_evidence_binding_matches(
    evidence: dict[str, Any],
    sources: dict[str, dict[str, Any]],
) -> bool:
    row_indexes_by_source: dict[str, list[int]] = {}
    for ref in _mapping_list(evidence.get("related_source_refs")):
        source_ref = _text(ref.get("source_ref"))
        row_index = _int(ref.get("row_index"))
        if source_ref not in sources or row_index <= 0:
            continue
        indexes = row_indexes_by_source.setdefault(source_ref, [])
        if row_index not in indexes:
            indexes.append(row_index)

    endpoint_rows: list[tuple[list[str], list[str], list[str]]] = []
    for source_ref, row_indexes in row_indexes_by_source.items():
        rows = [
            [_text(cell) for cell in row]
            for row in sources[source_ref].get("rows") or []
            if isinstance(row, list)
        ]
        if len(row_indexes) != 2 or any(index >= len(rows) for index in row_indexes):
            continue
        endpoint_rows.append(
            (rows[0], rows[row_indexes[0]], rows[row_indexes[1]])
        )
    if not endpoint_rows:
        return False

    comparison = _mapping(evidence.get("comparison"))
    if not any(
        _row_contains_value(baseline_row, comparison.get("baseline_label"))
        and _row_contains_value(target_row, comparison.get("target_label"))
        for _headers, baseline_row, target_row in endpoint_rows
    ):
        return False

    for variable in _mapping_list(evidence.get("changed_variables")):
        if not any(
            _table_variable_values_bind(
                variable,
                headers=headers,
                baseline_row=baseline_row,
                target_row=target_row,
            )
            for headers, baseline_row, target_row in endpoint_rows
        ):
            return False

    reported_result = _mapping(evidence.get("reported_result"))
    return any(
        any(
            index < len(target_row)
            and _value_matches_cell(reported_result.get("value"), target_row[index])
            for index, header in enumerate(headers)
            if _table_header_is_result(
                _table_header_key(header), reported_result.get("outcome")
            )
        )
        for headers, _baseline_row, target_row in endpoint_rows
    )


def _table_variable_values_bind(
    variable: dict[str, Any],
    *,
    headers: list[str],
    baseline_row: list[str],
    target_row: list[str],
) -> bool:
    variable_columns = [
        index
        for index, header in enumerate(headers)
        if _table_factor_matches_header(
            variable.get("name"), _table_header_key(header)
        )
    ]
    return bool(variable_columns) and any(
        index < len(baseline_row)
        and index < len(target_row)
        and _value_matches_cell(variable.get("baseline_value"), baseline_row[index])
        and _value_matches_cell(variable.get("target_value"), target_row[index])
        for index in variable_columns
    )


def _table_evidence_binding_matches(
    evidence: dict[str, Any], source: dict[str, Any] | None
) -> bool:
    if source is None:
        return False
    rows = [
        [_text(cell) for cell in row]
        for row in source.get("rows") or []
        if isinstance(row, list)
    ]
    comparison = _mapping(evidence.get("comparison"))
    if not rows or not comparison:
        return False
    exact_rows = _table_comparison_rows(evidence, rows)
    if exact_rows is not None:
        baseline_row, target_row, result_columns = exact_rows
        return _table_row_values_bind(
            evidence,
            headers=rows[0],
            baseline_row=baseline_row,
            target_row=target_row,
        ) and _table_row_delta_is_explained(
            evidence,
            headers=rows[0],
            baseline_row=baseline_row,
            target_row=target_row,
            result_columns=result_columns,
        )
    return _table_named_comparison_rows_bind(evidence, rows)


def _table_comparison_rows(
    evidence: dict[str, Any],
    rows: list[list[str]],
) -> tuple[list[str], list[str], set[int]] | None:
    row_indexes: list[int] = []
    result_columns: set[int] = set()
    for ref in _mapping_list(evidence.get("related_source_refs")):
        row_index = _int(ref.get("row_index"))
        col_index = _int(ref.get("col_index"))
        if 0 < row_index < len(rows) and row_index not in row_indexes:
            row_indexes.append(row_index)
        if 0 <= col_index < len(rows[0]):
            result_columns.add(col_index)
    if len(row_indexes) != 2:
        return None
    return rows[row_indexes[0]], rows[row_indexes[1]], result_columns


def _table_row_values_bind(
    evidence: dict[str, Any],
    *,
    headers: list[str],
    baseline_row: list[str],
    target_row: list[str],
) -> bool:
    for variable in _mapping_list(evidence.get("changed_variables")):
        variable_columns = [
            index
            for index, header in enumerate(headers)
            if _table_factor_matches_header(
                variable.get("name"), _table_header_key(header)
            )
        ]
        if not variable_columns:
            return False
        if not any(
            index < len(baseline_row)
            and _value_matches_cell(variable.get("baseline_value"), baseline_row[index])
            for index in variable_columns
        ):
            return False
        if not any(
            index < len(target_row)
            and _value_matches_cell(variable.get("target_value"), target_row[index])
            for index in variable_columns
        ):
            return False
    reported_result = _mapping(evidence.get("reported_result"))
    result_columns = [
        index
        for index, header in enumerate(headers)
        if _table_header_is_result(
            _table_header_key(header), reported_result.get("outcome")
        )
    ]
    return bool(result_columns) and any(
        index < len(target_row)
        and _value_matches_cell(reported_result.get("value"), target_row[index])
        for index in result_columns
    )


def _table_named_comparison_rows_bind(
    evidence: dict[str, Any], rows: list[list[str]]
) -> bool:
    if len(rows) < 2:
        return False
    headers = rows[0]
    comparison = _mapping(evidence.get("comparison"))
    baseline_rows = [
        row
        for row in rows[1:]
        if _row_contains_value(row, comparison.get("baseline_label"))
    ]
    target_rows = [
        row
        for row in rows[1:]
        if _row_contains_value(row, comparison.get("target_label"))
    ]
    return any(
        _table_row_values_bind(
            evidence,
            headers=headers,
            baseline_row=baseline_row,
            target_row=target_row,
        )
        for baseline_row in baseline_rows
        for target_row in target_rows
    )


def _table_row_delta_is_explained(
    evidence: dict[str, Any],
    *,
    headers: list[str],
    baseline_row: list[str],
    target_row: list[str],
    result_columns: set[int],
) -> bool:
    variables = _mapping_list(evidence.get("changed_variables"))
    outcome = _mapping(evidence.get("reported_result")).get("outcome")
    reasons = " ".join(
        _text_list(_mapping(evidence.get("comparison")).get("incomparability_reasons"))
    )
    for index, header in enumerate(headers):
        if index >= len(baseline_row) or index >= len(target_row):
            continue
        baseline_value = baseline_row[index]
        target_value = target_row[index]
        if _normalized_text(baseline_value) == _normalized_text(target_value):
            continue
        header_key = _table_header_key(header)
        if (
            index in result_columns
            or _table_header_is_result(header_key, outcome)
        ):
            continue
        if header_key in _TABLE_SAMPLE_HEADERS and _sample_values_are_opaque_identifiers(
            baseline_value,
            target_value,
        ):
            continue
        if any(
            _table_factor_matches_header(variable.get("name"), header_key)
            and _value_matches_cell(variable.get("baseline_value"), baseline_value)
            and _value_matches_cell(variable.get("target_value"), target_value)
            for variable in variables
        ):
            continue
        if header_key and header_key in _normalized_term(reasons):
            continue
        return False
    return True


def _table_header_key(value: Any) -> str:
    text = _text(value).casefold().translate(str.maketrans({"α": "alpha", "β": "beta", "θ": "theta", "ɵ": "theta"}))
    text = re.sub(r"\s*(?:\[[^\]]*\]|\([^)]*\))\s*$", "", text).strip()
    normalized = _normalized_term(text)
    return _TABLE_SYMBOL_AXES.get(normalized, normalized)


def _table_factor_matches_header(factor: Any, header_key: str) -> bool:
    factor_tokens = set(_normalized_term(factor).split())
    header_tokens = set(header_key.split())
    return bool(
        factor_tokens
        and header_tokens
        and (factor_tokens <= header_tokens or header_tokens <= factor_tokens)
    )


def _table_header_is_result(header_key: str, outcome: Any) -> bool:
    header_tokens = set(header_key.split()) - _RESULT_QUALIFIERS
    outcome_tokens = set(_normalized_term(outcome).split()) - _RESULT_QUALIFIERS
    return bool(
        header_tokens
        and outcome_tokens
        and (header_tokens <= outcome_tokens or outcome_tokens <= header_tokens)
    )


def _row_contains_value(row: list[str], value: Any) -> bool:
    return any(_value_matches_cell(value, cell) for cell in row)


def _value_matches_cell(value: Any, cell: Any) -> bool:
    expected = _normalized_text(value)
    actual = _normalized_text(cell)
    expected_numbers = set(_numbers(value))
    if expected_numbers:
        return expected_numbers <= set(_numbers(cell))
    return bool(expected and expected == actual)


def _sample_values_are_opaque_identifiers(*values: Any) -> bool:
    normalized = [
        re.sub(r"[^a-z0-9]+", "", _text(value).casefold()) for value in values
    ]
    return bool(normalized) and all(
        value and re.fullmatch(r"[a-z]?\d+|[a-z]", value)
        for value in normalized
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


def _api_jsonl_request(
    base_url: str,
    path: str,
    *,
    cookie: str = "",
) -> list[dict[str, Any]]:
    headers = {"Cookie": cookie} if cookie else {}
    api_request = request_url.Request(
        f"{base_url}{path}", headers=headers, method="GET"
    )
    try:
        with request_url.urlopen(api_request, timeout=60) as response:
            lines = response.read().decode("utf-8").splitlines()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Lens API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Lens API request failed: {exc}") from exc
    return _mapping_list(json.loads(line) for line in lines if line.strip())


def _check(
    objective_id: str,
    name: str,
    passed: bool,
    detail: str = "",
    *,
    blocker: bool = False,
) -> dict[str, Any]:
    return {
        "status": "pass" if passed else "fail",
        "objective_id": objective_id,
        "check": name,
        "detail": detail,
        "blocker": blocker,
    }


def _checks_verdict(checks: list[dict[str, Any]]) -> str:
    failed = [item for item in checks if item["status"] == "fail"]
    if any(item["blocker"] for item in failed):
        return "fail"
    return "partial" if failed else "pass"


def _combined_verdict(verdicts: list[str]) -> str:
    if "fail" in verdicts:
        return "fail"
    return "partial" if "partial" in verdicts else "pass"


def _manifest_objective_for_question(
    question: str,
    objectives: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_question = _normalized_text(question)
    matches = [
        item
        for item in objectives
        if all(
            any(_normalized_text(term) in normalized_question for term in group)
            for group in item.get("question_term_groups") or []
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            "acceptance manifest must match exactly one Objective for question: "
            f"{question}"
        )
    return matches[0]


def _required_review_status_check(
    *, required: set[str], objectives: list[dict[str, Any]]
) -> dict[str, Any]:
    observed = {
        status
        for objective in objectives
        for status in objective.get("review_statuses") or []
    }
    missing = sorted(required - observed)
    return _check(
        "*",
        "correct, partial, and incorrect expert feedback are persisted",
        not missing,
        f"missing={missing}; observed={sorted(observed)}",
        blocker=True,
    )


def _synthesis_status_issues(
    *,
    synthesis_status: str,
    contributions: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    direct_records: list[dict[str, Any]],
    supporting_ids: set[str],
    contradicting_ids: set[str],
) -> list[str]:
    supporting_documents = {
        _text(item.get("document_id"))
        for item in direct_records
        if _text(item.get("evidence_id")) in supporting_ids
    }
    contradicting_documents = {
        _text(item.get("document_id"))
        for item in direct_records
        if _text(item.get("evidence_id")) in contradicting_ids
    }
    direct_documents = supporting_documents | contradicting_documents
    boundary_ids = {
        evidence_id
        for contribution in contributions
        for evidence_id in _text_list(
            contribution.get("condition_boundary_evidence_ids")
        )
    }
    evidence_by_id = {_text(item.get("evidence_id")): item for item in evidence}
    valid_boundary_ids = {
        evidence_id
        for evidence_id in boundary_ids
        if (record := evidence_by_id.get(evidence_id)) is not None
        and record.get("evidence_role")
        in {"direct_result", "contradictory_result"}
        and evidence_id in supporting_ids | contradicting_ids
    }
    if synthesis_status == "insufficient_confirmation":
        return [] if len(direct_documents) < 2 else ["two direct papers require synthesis"]
    if synthesis_status == "agreement":
        issues = []
        if len(supporting_documents) < 2:
            issues.append("agreement requires two supporting papers")
        if contradicting_documents:
            issues.append("agreement cannot contain contradictory direct Evidence")
        if boundary_ids:
            issues.append("agreement cannot contain a condition boundary")
        return issues
    if synthesis_status == "conflict":
        issues = []
        if not supporting_documents or not contradicting_documents:
            issues.append("conflict requires supporting and opposing direct Evidence")
        if len(direct_documents) < 2:
            issues.append("conflict requires two direct papers")
        if boundary_ids:
            issues.append("condition-boundary Evidence requires condition_dependent")
        return issues
    if synthesis_status == "condition_dependent":
        issues = []
        if len(direct_documents) < 2:
            issues.append("condition dependence requires two direct papers")
        if not boundary_ids:
            issues.append("condition dependence requires boundary Evidence")
        elif valid_boundary_ids != boundary_ids:
            issues.append("condition boundary must be opposing direct Evidence")
        elif not _direct_results_have_disjoint_context_boundary(
            direct_records,
            supporting_ids=supporting_ids,
            contradicting_ids=contradicting_ids,
        ):
            issues.append(
                "condition boundary requires the same context attribute with "
                "disjoint values in different opposing papers"
            )
        return issues
    return [f"unsupported synthesis status: {synthesis_status}"]


def _direct_results_have_disjoint_context_boundary(
    direct_records: list[dict[str, Any]],
    *,
    supporting_ids: set[str],
    contradicting_ids: set[str],
) -> bool:
    supporting = [
        item
        for item in direct_records
        if _text(item.get("evidence_id")) in supporting_ids
    ]
    contradicting = [
        item
        for item in direct_records
        if _text(item.get("evidence_id")) in contradicting_ids
    ]
    supporting_documents = {_text(item.get("document_id")) for item in supporting}
    contradicting_documents = {
        _text(item.get("document_id")) for item in contradicting
    }
    if (
        not supporting_documents
        or not contradicting_documents
        or not supporting_documents.isdisjoint(contradicting_documents)
    ):
        return False

    def values(records: list[dict[str, Any]]) -> dict[tuple[str, str, str], set[str]]:
        result: dict[tuple[str, str, str], set[str]] = {}
        for record in records:
            context = _mapping(record.get("scientific_context"))
            for section in ("material", "sample", "process", "test"):
                for attribute in _mapping_list(context.get(section)):
                    key = (
                        section,
                        _normalized_term(attribute.get("name")),
                        _normalized_term(attribute.get("unit")),
                    )
                    result.setdefault(key, set()).add(
                        _normalized_text(attribute.get("value"))
                    )
        return result

    supporting_values = values(supporting)
    contradicting_values = values(contradicting)
    return any(
        supporting_values[key]
        and contradicting_values[key]
        and supporting_values[key].isdisjoint(contradicting_values[key])
        for key in set(supporting_values) & set(contradicting_values)
    )


def _finding_statement_issues(
    finding: dict[str, Any],
    supporting_evidence: list[dict[str, Any]],
) -> list[str]:
    statement_numbers = set(_numbers(finding.get("statement")))
    if not statement_numbers:
        return []
    for evidence in supporting_evidence:
        evidence_numbers = set(_numbers(evidence.get("source_excerpt")))
        if statement_numbers <= evidence_numbers:
            return []
    return [
        "statement numbers do not occur together in one supporting structured result"
    ]


def _training_export_issues(
    *,
    dataset_items: list[dict[str, Any]],
    training_rows: list[dict[str, Any]],
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    evidence_by_finding: dict[str, list[dict[str, Any]]],
) -> list[str]:
    issues: list[str] = []
    expected = {
        _text(item.get("finding_id")): item
        for item in dataset_items
        if item.get("dataset_use_status") == "training_ready"
    }
    actual: dict[str, dict[str, Any]] = {}
    for row in training_rows:
        metadata = _mapping(row.get("metadata"))
        finding_id = _text(metadata.get("finding_id"))
        if not finding_id or finding_id in actual:
            issues.append("training_jsonl has a missing or duplicate finding_id")
            continue
        actual[finding_id] = row
        if (
            metadata.get("collection_id") != collection_id
            or metadata.get("objective_id") != objective_id
            or _int(metadata.get("analysis_version")) != analysis_version
        ):
            issues.append(f"{finding_id}: training metadata identity differs")
        messages = _mapping_list(row.get("messages"))
        if len(messages) != 2 or any(not _text(item.get("content")) for item in messages):
            issues.append(f"{finding_id}: training messages are incomplete")
            continue
        if [item.get("role") for item in messages] != ["user", "assistant"]:
            issues.append(f"{finding_id}: training roles must be user then assistant")
        user_content = _normalized_text(messages[0].get("content"))
        missing_excerpts = [
            _text(evidence.get("evidence_id"))
            for evidence in evidence_by_finding.get(finding_id, [])
            if (excerpt := _normalized_text(evidence.get("source_excerpt")))
            and excerpt not in user_content
        ]
        if missing_excerpts:
            issues.append(
                f"{finding_id}: user prompt omits Evidence {missing_excerpts}"
            )
    if set(actual) != set(expected):
        issues.append(
            f"training IDs differ: expected={sorted(expected)}; actual={sorted(actual)}"
        )
    for finding_id in set(actual) & set(expected):
        item = expected[finding_id]
        expected_messages = _mapping_list(item.get("training_messages"))
        if not expected_messages:
            issues.append(f"{finding_id}: training-ready dataset item has no messages")
        if _mapping_list(actual[finding_id].get("messages")) != expected_messages:
            issues.append(f"{finding_id}: JSONL messages differ from the JSON dataset")
        if _mapping(actual[finding_id].get("metadata")) != _mapping(
            item.get("metadata")
        ):
            issues.append(f"{finding_id}: JSONL metadata differs from the JSON dataset")
        messages = _mapping_list(actual[finding_id].get("messages"))
        if len(messages) != 2:
            continue
        try:
            assistant_target = json.loads(_text(messages[1].get("content")))
        except json.JSONDecodeError:
            issues.append(f"{finding_id}: assistant message is not valid JSON")
            continue
        if assistant_target != item.get("training_target"):
            issues.append(f"{finding_id}: assistant JSON differs from training_target")
    return issues


def _direct_result_issues(
    finding: dict[str, Any],
    evidence_records: list[dict[str, Any]],
    *,
    supporting_ids: set[str],
    contradicting_ids: set[str],
) -> list[str]:
    issues: list[str] = []
    outcome = _normalized_term(finding.get("outcome"))
    direction = _text(finding.get("direction"))
    for evidence in evidence_records:
        evidence_id = _text(evidence.get("evidence_id"))
        result = _mapping(evidence.get("reported_result"))
        result_direction = _text(result.get("direction"))
        if _normalized_term(result.get("outcome")) != outcome:
            issues.append(f"{evidence_id}: outcome differs from Finding")
        if evidence.get("attribution_scope") == "not_attributable":
            issues.append(f"{evidence_id}: non-attributable Evidence supports Finding")
        if evidence_id in supporting_ids and result_direction != direction:
            issues.append(f"{evidence_id}: support direction differs from Finding")
        if evidence_id in contradicting_ids and result_direction not in (
            _OPPOSING_DIRECTIONS.get(direction) or set()
        ):
            issues.append(f"{evidence_id}: contradiction does not oppose Finding")
    if finding.get("assertion_strength") == "causal" and finding.get(
        "attribution_scope"
    ) != "isolated_effect":
        issues.append("causal assertion lacks isolated-effect Evidence")
    return issues


def _experiment_binding_issues(
    evidence_records: list[dict[str, Any]],
) -> list[str]:
    issues: list[str] = []
    for evidence in evidence_records:
        evidence_id = _text(evidence.get("evidence_id"))
        excerpt = _text(evidence.get("source_excerpt"))
        for variable in _mapping_list(evidence.get("changed_variables")):
            for field in ("baseline_value", "target_value"):
                value = variable.get(field)
                if _numbers(value) and not _numbers_grounded(value, excerpt):
                    issues.append(
                        f"{evidence_id}: {variable.get('name')} {field}={value!r} "
                        "is absent from source"
                    )
        result_value = _mapping(evidence.get("reported_result")).get("value")
        if _numbers(result_value) and not _numbers_grounded(result_value, excerpt):
            issues.append(
                f"{evidence_id}: result value={result_value!r} is absent from source"
            )
    return issues


def _sample_state_confounding_issues(
    evidence_records: list[dict[str, Any]],
) -> list[str]:
    issues: list[str] = []
    for evidence in evidence_records:
        if evidence.get("attribution_scope") not in {
            "isolated_effect",
            "joint_effect",
        }:
            continue
        source = _normalized_term(evidence.get("source_excerpt"))
        if "as slm" not in source or "hip slm" not in source:
            continue
        factors = {
            _normalized_term(item.get("name"))
            for item in _mapping_list(evidence.get("changed_variables"))
        }
        if not any(
            term in factor
            for factor in factors
            for term in ("heat treatment", "hip", "post process", "sample state")
        ):
            issues.append(
                f"{_text(evidence.get('evidence_id'))}: "
                "as-SLM/HIP-SLM comparison omits treatment state"
            )
    return issues


def _numbers_grounded(value: Any, source: str) -> bool:
    expected = _numbers(value)
    actual = _numbers(source)
    return bool(expected) and all(number in actual for number in expected)


def _numbers(value: Any) -> tuple[Decimal, ...]:
    result: list[Decimal] = []
    source = _text(value).replace("−", "-")
    for match in _MULTIPLICATION_SCIENTIFIC_RE.finditer(source):
        try:
            coefficient = _decimal_number(match.group(1))
            exponent = int(
                match.group(2).translate(
                    str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
                )
            )
            number = coefficient * (Decimal(10) ** exponent)
        except (InvalidOperation, ValueError):
            continue
        if number not in result:
            result.append(number)
    source = _MULTIPLICATION_SCIENTIFIC_RE.sub(" ", source)
    for token in _NUMBER_RE.findall(source):
        try:
            number = _decimal_number(token)
        except InvalidOperation:
            continue
        if number not in result:
            result.append(number)
    return tuple(result)


def _decimal_number(token: str) -> Decimal:
    normalized = token.strip()
    if "," in normalized and "." not in normalized:
        integer, fraction = normalized.rsplit(",", 1)
        normalized = (
            f"{integer}.{fraction}"
            if 0 < len(fraction) <= 2
            else normalized.replace(",", "")
        )
    else:
        normalized = normalized.replace(",", "")
    return Decimal(normalized)


def _failed_source_ids(results: list[dict[str, Any]], field: str) -> str:
    return f"failed={[item['evidence_id'] for item in results if not item[field]]}"


def _finding_attribution_scope(
    *, factor_count: int, evidence_scopes: set[str]
) -> str:
    if "descriptive_only" in evidence_scopes:
        return "descriptive_only"
    if "association_only" in evidence_scopes:
        return "association_only"
    if factor_count == 1 and evidence_scopes == {"isolated_effect"}:
        return "isolated_effect"
    if factor_count >= 2 and evidence_scopes == {"joint_effect"}:
        return "joint_effect"
    return "association_only"


def _expected_dataset_status(
    feedback: list[dict[str, Any]],
    curations: list[dict[str, Any]],
) -> tuple[str, str, dict[str, Any] | None]:
    events = [
        (_event_time(item.get("created_at")), 0, "feedback", item)
        for item in feedback
    ]
    events.extend(
        (_event_time(item.get("updated_at")), 1, "curation", item)
        for item in curations
    )
    if not events:
        return "candidate", "review_candidate", None
    _, _, kind, latest = max(events, key=lambda item: (item[0], item[1]))
    if kind == "curation":
        if latest.get("curated_status") == "unsupported":
            return "rejected", "rejected", latest.get("curated_finding")
        return "gold", "training_ready", latest.get("curated_finding")
    if latest.get("review_status") == "correct":
        return "gold", "training_ready", None
    if latest.get("review_status") == "incorrect":
        return "rejected", "rejected", None
    return "silver", "review_candidate", None


def _event_time(value: Any) -> datetime:
    text = _text(value)
    if not text:
        return datetime.min
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _normalized_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", _text(value)).casefold()


def _normalized_lines(value: Any) -> tuple[str, ...]:
    return tuple(
        normalized
        for line in _text(value).splitlines()
        if (normalized := _normalized_text(line))
    )


def _normalized_term(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", _text(value).casefold()))


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
