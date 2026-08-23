from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_ACTIONS = frozenset({"accept", "reject", "correct", "skip"})
_ISSUES = frozenset(
    {
        "evidence_not_grounded",
        "missing_evidence",
        "insufficient_evidence",
        "wrong_factor",
        "wrong_outcome",
        "wrong_direction",
        "wrong_context",
        "wrong_mechanism",
        "wrong_attribution",
        "wrong_synthesis",
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

    async def import_rows(
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
                validated.append(
                    await self._decision(row, line_number=line_number)
                )
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
                    await self.feedback_service.record_curation(
                        reviewer=reviewer,
                        **payload,
                    )
                else:
                    await self.feedback_service.record_feedback(
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

    async def import_jsonl_file(
        self,
        *,
        input_path: Path,
        reviewer: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return await self.import_rows(
            rows=read_review_jsonl(input_path),
            reviewer=reviewer,
            dry_run=dry_run,
        )

    async def _decision(
        self,
        row: dict[str, Any],
        *,
        line_number: int,
    ) -> dict[str, Any]:
        if "expert_action" in row or "expert_note" in row:
            raise ValueError("expert_action and expert_note are not review JSONL fields")
        action = _text(row.get("action")).lower()
        if action not in _ACTIONS:
            raise ValueError("action must be accept, reject, correct, or skip")
        identity = _identity(row)
        if action == "skip":
            return {"line": line_number, "action": action, "payload": identity}

        if action == "accept":
            await self._require_dataset_item(identity)
            return {
                "line": line_number,
                "action": action,
                "payload": {
                    **identity,
                    "review_status": "correct",
                    "issue_type": "none",
                    "note": _optional_text(row.get("note")),
                },
            }
        if action == "reject":
            await self._require_dataset_item(identity)
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
                    "note": _optional_text(row.get("note")),
                },
            }

        curated_finding = row.get("curated_finding")
        if not isinstance(curated_finding, dict):
            raise ValueError("correct requires one complete curated_finding")
        candidate = await self.feedback_service.validate_curation(
            **identity,
            curated_finding=curated_finding,
        )
        curated_status = _text(row.get("curated_status")) or "limited"
        if curated_status not in {"supported", "limited", "conflicted", "unsupported"}:
            raise ValueError("correct requires a valid curated_status")
        return {
            "line": line_number,
            "action": action,
            "payload": {
                **identity,
                "curated_status": curated_status,
                "curated_finding": candidate.to_record(),
                "note": _optional_text(row.get("note")),
            },
        }

    async def _require_dataset_item(
        self,
        identity: dict[str, Any],
    ) -> dict[str, Any]:
        dataset = await self.feedback_service.export_dataset(
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


__all__ = ["FindingReviewImportService", "read_review_jsonl"]
