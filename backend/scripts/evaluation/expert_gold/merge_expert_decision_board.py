#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any


ACTION_VALUES = frozenset({"accept", "reject", "correct", "skip", ""})
LIST_FIELDS = {
    "corrected_variables": "variables",
    "corrected_mediators": "mediators",
    "corrected_outcomes": "outcomes",
    "corrected_evidence_ref_ids": "evidence_ref_ids",
}
TEXT_FIELDS = {
    "corrected_statement": "statement",
    "corrected_direction": "direction",
    "corrected_scope_summary": "scope_summary",
    "corrected_support_grade": "support_grade",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge a human-filled expert-decision-board.tsv into "
            "reviewed-findings.template.jsonl. The output is still only an "
            "import candidate; validate it with import_goal_review_decisions.py "
            "--dry-run --fail-on-warnings before writing labels."
        )
    )
    parser.add_argument("template_jsonl", help="reviewed-findings.template.jsonl path.")
    parser.add_argument("decision_board_tsv", help="Human-filled TSV decision board.")
    parser.add_argument(
        "--output-path",
        "-o",
        help="Output JSONL path. Defaults to stdout.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = merge_expert_decision_board(
        template_rows=read_jsonl(Path(args.template_jsonl)),
        board_rows=read_tsv(Path(args.decision_board_tsv)),
    )
    output = _jsonl(rows)
    if args.output_path:
        Path(args.output_path).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)


def merge_expert_decision_board(
    *,
    template_rows: list[dict[str, Any]],
    board_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    indexed = _index_template_rows(template_rows)
    merged = [dict(row) for row in template_rows]
    merged_by_key = {_row_key(row): row for row in merged}
    errors: list[str] = []
    used_keys: set[tuple[str, str, str]] = set()

    for line_number, board_row in enumerate(board_rows, start=2):
        key = _board_key(board_row)
        if not key[1] or not key[2]:
            errors.append(f"line {line_number}: goal_id and finding_id are required")
            continue
        if key not in indexed:
            errors.append(
                f"line {line_number}: finding is not present in JSONL template"
            )
            continue
        if key in used_keys:
            errors.append(f"line {line_number}: duplicate decision for finding")
            continue
        used_keys.add(key)
        target_row = merged_by_key[key]
        action = _text(board_row.get("expert_action")).lower()
        if action not in ACTION_VALUES:
            errors.append(
                f"line {line_number}: expert_action must be accept, reject, correct, or skip"
            )
            continue
        if action in {"", "skip"}:
            continue
        row_errors = _validate_action(action, target_row, board_row, line_number)
        if row_errors:
            errors.extend(row_errors)
            continue
        _apply_decision(target_row, board_row, action)

    if errors:
        raise ValueError("\n".join(errors))
    return merged


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"line {line_number} must be a JSON object")
            rows.append(payload)
    return rows


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = [
            field
            for field in ("collection_id", "goal_id", "finding_id", "expert_action")
            if field not in (reader.fieldnames or [])
        ]
        if missing:
            raise ValueError(f"decision board missing column(s): {', '.join(missing)}")
        return [
            {key: value or "" for key, value in row.items() if key is not None}
            for row in reader
        ]


def _index_template_rows(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for line_number, row in enumerate(rows, start=1):
        key = _row_key(row)
        if not key[1] or not key[2]:
            raise ValueError(
                f"template line {line_number}: goal_id and finding_id are required"
            )
        if key in indexed:
            raise ValueError(f"template line {line_number}: duplicate finding row")
        indexed[key] = row
    return indexed


def _validate_action(
    action: str,
    template_row: dict[str, Any],
    board_row: dict[str, str],
    line_number: int,
) -> list[str]:
    errors: list[str] = []
    if action == "accept" and not _accept_allowed(template_row, board_row):
        errors.append(
            f"line {line_number}: accept is blocked; use correct or reject"
        )
    if action == "reject":
        issue_type = _text(board_row.get("issue_type")).lower()
        if not issue_type:
            errors.append(f"line {line_number}: reject requires issue_type")
    if action == "correct":
        if not _text(board_row.get("corrected_statement")):
            errors.append(f"line {line_number}: correct requires corrected_statement")
        evidence_ref_ids = _split_list(board_row.get("corrected_evidence_ref_ids"))
        if not evidence_ref_ids:
            evidence_ref_ids = _split_list(board_row.get("curated_evidence_ref_ids"))
        if not evidence_ref_ids:
            errors.append(
                f"line {line_number}: correct requires corrected_evidence_ref_ids"
            )
    return errors


def _apply_decision(
    target_row: dict[str, Any],
    board_row: dict[str, str],
    action: str,
) -> None:
    target_row["action"] = action
    note = _text(board_row.get("expert_note"))
    if note:
        target_row["expert_note"] = note
    if action == "reject":
        target_row["issue_type"] = _text(board_row.get("issue_type")).lower()
        return
    if action == "correct":
        target = dict(target_row.get("suggested_target") or {})
        for source_field, target_field in TEXT_FIELDS.items():
            value = _text(board_row.get(source_field))
            if value:
                target[target_field] = value
        for source_field, target_field in LIST_FIELDS.items():
            values = _split_list(board_row.get(source_field))
            if values:
                target[target_field] = values
        target_row["suggested_target"] = target
        if target.get("evidence_ref_ids"):
            target_row["curated_evidence_ref_ids"] = list(target["evidence_ref_ids"])


def _accept_allowed(
    template_row: dict[str, Any],
    board_row: dict[str, str],
) -> bool:
    board_value = _text(board_row.get("accept_allowed")).lower()
    if board_value in {"no", "false", "0"}:
        return False
    gate = template_row.get("acceptance_gate")
    if isinstance(gate, dict):
        if gate.get("accept_allowed") is False:
            return False
        if gate.get("requires_correction") is True:
            return False
        blockers = gate.get("accept_blockers")
        if isinstance(blockers, list) and blockers:
            return False
    blocking = template_row.get("protocol_blocking_missing")
    return not (isinstance(blocking, list) and blocking)


def _board_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        _text(row.get("collection_id")),
        _text(row.get("goal_id")),
        _text(row.get("finding_id")),
    )


def _row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _text(row.get("collection_id")),
        _text(row.get("goal_id")),
        _text(row.get("finding_id")),
    )


def _split_list(value: Any) -> list[str]:
    text = _text(value)
    if not text:
        return []
    delimiter = ";" if ";" in text else ","
    return [_text(item) for item in text.split(delimiter) if _text(item)]


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


if __name__ == "__main__":
    main()
