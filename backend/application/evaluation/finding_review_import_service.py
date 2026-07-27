from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any


_ACTIONS = frozenset({"accept", "reject", "correct", "skip"})
_ISSUES = frozenset(
    {
        "evidence_not_grounded",
        "missing_evidence",
        "insufficient_evidence",
        "wrong_variable",
        "wrong_outcome",
        "wrong_direction",
        "wrong_context",
        "wrong_relation",
        "overclaim",
        "unclear_statement",
        "other",
    }
)


class FindingReviewImportService:
    """Validate and apply human decisions to published Finding versions."""

    def __init__(self, feedback_service: Any) -> None:
        if feedback_service is None:
            raise ValueError("feedback_service is required")
        self.feedback_service = feedback_service

    def import_rows(
        self,
        *,
        rows: list[dict[str, Any]],
        reviewer: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        reviewer = _human_reviewer(reviewer)
        validated: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for line_number, row in enumerate(rows, start=1):
            try:
                validated.append(self._decision(row, line_number=line_number))
            except ValueError as exc:
                errors.append({"line": line_number, "message": str(exc)})
        if errors:
            return _summary(
                status="fail",
                dry_run=dry_run,
                decisions=validated,
                errors=errors,
                written_count=0,
            )

        written_count = 0
        if not dry_run:
            for decision in validated:
                action = decision["action"]
                if action == "skip":
                    continue
                payload = dict(decision["payload"])
                if action == "correct":
                    self.feedback_service.record_curation(
                        reviewer=reviewer,
                        **payload,
                    )
                else:
                    self.feedback_service.record_feedback(
                        reviewer=reviewer,
                        **payload,
                    )
                written_count += 1
        return _summary(
            status="pass",
            dry_run=dry_run,
            decisions=validated,
            errors=[],
            written_count=written_count,
        )

    def import_jsonl_file(
        self,
        *,
        input_path: Path,
        reviewer: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.import_rows(
            rows=read_review_jsonl(input_path),
            reviewer=reviewer,
            dry_run=dry_run,
        )

    def import_decision_board_tsv(
        self,
        *,
        content: str,
        reviewer: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.import_rows(
            rows=read_decision_board_tsv(content),
            reviewer=reviewer,
            dry_run=dry_run,
        )

    def _decision(self, row: dict[str, Any], *, line_number: int) -> dict[str, Any]:
        action = _text(row.get("action") or row.get("expert_action")).lower()
        if action not in _ACTIONS:
            raise ValueError("action must be accept, reject, correct, or skip")
        identity = _identity(row)
        if action == "skip":
            return {"line": line_number, "action": action, "payload": identity}

        item = self._require_dataset_item(identity)
        if action == "accept":
            return {
                "line": line_number,
                "action": action,
                "payload": {
                    **identity,
                    "review_status": "correct",
                    "issue_type": "none",
                    "note": _optional_text(row.get("note") or row.get("expert_note")),
                },
            }
        if action == "reject":
            issue_type = _text(row.get("issue_type")).lower()
            if issue_type not in _ISSUES:
                raise ValueError("reject requires a valid issue_type")
            return {
                "line": line_number,
                "action": action,
                "payload": {
                    **identity,
                    "review_status": "incorrect",
                    "issue_type": issue_type,
                    "note": _optional_text(row.get("note") or row.get("expert_note")),
                },
            }

        target = row.get("suggested_target")
        target = dict(target) if isinstance(target, dict) else {}
        statement = _text(
            target.get("statement")
            or row.get("curated_statement")
            or row.get("corrected_statement")
        )
        if not statement:
            raise ValueError("correct requires a curated statement")
        evidence_ids = _strings(
            target.get("evidence_ids")
            or row.get("curated_evidence_ids")
            or [
                evidence.get("evidence_id")
                for evidence in item.get("evidence", [])
                if isinstance(evidence, dict)
            ]
        )
        if not evidence_ids:
            raise ValueError("correct requires at least one evidence_id")
        available_ids = {
            evidence.get("evidence_id")
            for evidence in item.get("evidence", [])
            if isinstance(evidence, dict)
        }
        if set(evidence_ids) - available_ids:
            raise ValueError("curation references evidence outside the Finding")
        return {
            "line": line_number,
            "action": action,
            "payload": {
                **identity,
                "curated_status": _text(target.get("status") or row.get("curated_status"))
                or "limited",
                "curated_statement": statement,
                "curated_evidence_ids": evidence_ids,
                "curated_support_grade": _optional_text(
                    target.get("evidence_strength")
                    or row.get("curated_support_grade")
                ),
                "curated_review_status": _optional_text(
                    target.get("review_status") or row.get("curated_review_status")
                ),
                "curated_variables": _strings(
                    target.get("variables") or row.get("curated_variables")
                ),
                "curated_mediators": _strings(
                    target.get("mediators") or row.get("curated_mediators")
                ),
                "curated_outcomes": _strings(
                    target.get("outcomes") or row.get("curated_outcomes")
                ),
                "curated_direction": _optional_text(
                    target.get("direction") or row.get("curated_direction")
                ),
                "curated_scope_summary": _optional_text(
                    target.get("scope_summary") or row.get("curated_scope_summary")
                ),
                "note": _optional_text(row.get("note") or row.get("expert_note")),
            },
        }

    def _require_dataset_item(self, identity: dict[str, Any]) -> dict[str, Any]:
        dataset = self.feedback_service.export_dataset(
            collection_id=identity["collection_id"],
            objective_id=identity["objective_id"],
        )
        for item in dataset.get("items", []):
            if (
                item.get("analysis_version") == identity["analysis_version"]
                and item.get("finding_id") == identity["finding_id"]
            ):
                return item
        raise ValueError("Finding version is not present in the current dataset")


def read_review_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"line {line_number} must be a JSON object")
            rows.append(payload)
    return rows


def read_decision_board_tsv(content: str) -> list[dict[str, Any]]:
    return [dict(row) for row in csv.DictReader(StringIO(content), delimiter="\t")]


def _identity(row: dict[str, Any]) -> dict[str, Any]:
    if "claim_id" in row:
        raise ValueError("claim_id is not part of the Finding review contract")
    collection_id = _text(row.get("collection_id"))
    objective_id = _text(row.get("objective_id"))
    finding_id = _text(row.get("finding_id"))
    try:
        analysis_version = int(row.get("analysis_version") or 0)
    except (TypeError, ValueError):
        analysis_version = 0
    if not collection_id or not objective_id or analysis_version < 1 or not finding_id:
        raise ValueError(
            "collection_id, objective_id, analysis_version, and finding_id are required"
        )
    return {
        "collection_id": collection_id,
        "objective_id": objective_id,
        "analysis_version": analysis_version,
        "finding_id": finding_id,
    }


def _human_reviewer(value: str) -> str:
    reviewer = _text(value)
    if not reviewer:
        raise ValueError("reviewer is required")
    normalized = reviewer.lower()
    if normalized.startswith("ai-reviewer") or normalized.startswith("agent-"):
        raise ValueError("reviewer must be a human expert id")
    return reviewer


def _summary(
    *,
    status: str,
    dry_run: bool,
    decisions: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    written_count: int,
) -> dict[str, Any]:
    counts = {action: 0 for action in sorted(_ACTIONS)}
    for decision in decisions:
        counts[decision["action"]] += 1
    return {
        "status": status,
        "dry_run": dry_run,
        "total_rows": len(decisions) + len(errors),
        "written_count": written_count,
        "skipped_count": counts["skip"],
        "counts": counts,
        "errors": errors,
        "warnings": [],
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    return _text(value) or None


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    for item in values:
        text = _text(item)
        if text and text not in result:
            result.append(text)
    return result


__all__ = ["FindingReviewImportService", "read_decision_board_tsv", "read_review_jsonl"]
