#!/usr/bin/env python3
"""Validate and materialize an immutable feedback dataset for offline work."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable


PREPARED_SCHEMA_VERSION = "feedback-offline-prepared.v1"
TOKENIZER_NAME = "lens-whitespace-v1"
TOKENIZER_VERSION = 1
DATASET_TYPES = {"evaluation", "sft", "preference"}
SPLITS = {"train", "eval"}
TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class SnapshotValidationError(ValueError):
    """Raised when a frozen snapshot cannot safely enter an offline run."""


@dataclass(frozen=True)
class _ValidatedSnapshot:
    snapshot: dict[str, Any]
    rows: tuple[dict[str, Any], ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a P5 dataset snapshot and create a deterministic offline "
            "experiment directory."
        )
    )
    parser.add_argument("snapshot_path", type=Path, help="P5 snapshot detail JSON path.")
    parser.add_argument("output_dir", type=Path, help="Directory for prepared artifacts.")
    parser.add_argument("--revision", help="Source revision to record in the artifact.")
    parser.add_argument("--seed", type=int, default=0, help="Deterministic experiment seed.")
    parser.add_argument(
        "--max-input-tokens",
        type=int,
        default=4096,
        help="Maximum untruncated context token count per row.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = prepare_snapshot(
        snapshot_path=args.snapshot_path,
        output_dir=args.output_dir,
        revision=args.revision,
        seed=args.seed,
        max_input_tokens=args.max_input_tokens,
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


def prepare_snapshot(
    *,
    snapshot_path: str | Path,
    output_dir: str | Path,
    revision: str | None = None,
    seed: int = 0,
    max_input_tokens: int = 4096,
) -> dict[str, Any]:
    """Validate one immutable snapshot and write its offline representation.

    The function intentionally accepts the detail response produced by the P5
    snapshot endpoint, rather than a loose JSONL export.  The detail response
    carries the manifest and provenance needed to prove what was evaluated.
    """

    if seed < 0:
        raise SnapshotValidationError("seed_invalid")
    if max_input_tokens < 1:
        raise SnapshotValidationError("max_input_tokens_invalid")
    source = Path(snapshot_path).expanduser().resolve()
    if not source.is_file():
        raise SnapshotValidationError(f"snapshot_not_found:{source}")
    snapshot = _read_json_object(source, error_prefix="snapshot")
    validated = _validate_snapshot(snapshot, max_input_tokens=max_input_tokens)
    revision_value = (revision or os.environ.get("LENS_REVISION") or _git_revision()).strip()
    if not revision_value:
        revision_value = "unknown"

    prepared_rows = [
        _prepare_row(row, dataset_type=str(snapshot["dataset_type"]), max_input_tokens=max_input_tokens)
        for row in validated.rows
    ]
    prepared_rows.sort(key=lambda row: (str(row["split"]), str(row["row_id"])))
    split_rows = {
        split: [row for row in prepared_rows if row["split"] == split]
        for split in ("train", "eval")
    }
    rows_digest = _digest(prepared_rows)
    prepared = {
        "schema_version": PREPARED_SCHEMA_VERSION,
        "snapshot": {
            "dataset_id": snapshot["dataset_id"],
            "dataset_type": snapshot["dataset_type"],
            "collection_id": snapshot["collection_id"],
            "manifest_digest": snapshot["manifest_digest"],
            "provenance_digest": snapshot["provenance_digest"],
            "content_digest": snapshot["content_digest"],
        },
        "revision": revision_value,
        "seed": seed,
        "tokenizer": {
            "name": TOKENIZER_NAME,
            "version": TOKENIZER_VERSION,
            "template": "messages-then-target",
        },
        "max_input_tokens": max_input_tokens,
        "counts": {split: len(rows) for split, rows in split_rows.items()},
        "rows_digest": rows_digest,
        "files": {
            "train": "train.jsonl",
            "eval": "eval.jsonl",
            "snapshot": "snapshot.json",
        },
        "status": "ready",
    }

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    _write_json(destination / "snapshot.json", snapshot)
    _write_json(destination / "prepared.json", prepared)
    for split, rows in split_rows.items():
        _write_jsonl(destination / f"{split}.jsonl", rows)
    return prepared


def load_prepared(prepared_dir: str | Path) -> dict[str, Any]:
    """Read and re-check a prepared directory before an experiment consumes it."""

    directory = Path(prepared_dir).expanduser().resolve()
    prepared = _read_json_object(directory / "prepared.json", error_prefix="prepared")
    if prepared.get("schema_version") != PREPARED_SCHEMA_VERSION:
        raise SnapshotValidationError("prepared_schema_invalid")
    files = prepared.get("files")
    if not isinstance(files, dict):
        raise SnapshotValidationError("prepared_files_missing")
    snapshot_filename = files.get("snapshot")
    if not isinstance(snapshot_filename, str) or Path(snapshot_filename).name != snapshot_filename:
        raise SnapshotValidationError("prepared_snapshot_file_invalid")
    snapshot = _read_json_object(directory / snapshot_filename, error_prefix="prepared_snapshot")
    max_input_tokens = prepared.get("max_input_tokens")
    if not isinstance(max_input_tokens, int) or max_input_tokens < 1:
        raise SnapshotValidationError("prepared_max_input_tokens_invalid")
    validated = _validate_snapshot(snapshot, max_input_tokens=max_input_tokens)
    expected_snapshot = prepared.get("snapshot")
    if not isinstance(expected_snapshot, dict):
        raise SnapshotValidationError("prepared_snapshot_metadata_missing")
    for field in ("dataset_id", "dataset_type", "manifest_digest", "provenance_digest", "content_digest"):
        if expected_snapshot.get(field) != snapshot.get(field):
            raise SnapshotValidationError(f"prepared_snapshot_{field}_mismatch")
    rows_by_split: dict[str, list[dict[str, Any]]] = {}
    for split in ("train", "eval"):
        filename = files.get(split)
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise SnapshotValidationError("prepared_file_name_invalid")
        rows_by_split[split] = _read_jsonl(directory / filename, error_prefix=f"prepared_{split}")
        expected_count = (prepared.get("counts") or {}).get(split)
        if expected_count != len(rows_by_split[split]):
            raise SnapshotValidationError(f"prepared_{split}_count_mismatch")
    all_rows = rows_by_split["train"] + rows_by_split["eval"]
    if _digest(sorted(all_rows, key=lambda row: (str(row.get("split")), str(row.get("row_id"))))) != prepared.get(
        "rows_digest"
    ):
        raise SnapshotValidationError("prepared_rows_digest_mismatch")
    prepared_ids = {(str(row.get("row_id")), str(row.get("split"))) for row in all_rows}
    snapshot_ids = {(str(row.get("row_id")), str(row.get("split"))) for row in validated.rows}
    if prepared_ids != snapshot_ids:
        raise SnapshotValidationError("prepared_snapshot_rows_mismatch")
    result = dict(prepared)
    result["rows_by_split"] = rows_by_split
    return result


def tokenize(text: str) -> list[str]:
    """Tokenize deterministically for protocol accounting, not model training."""

    return TOKEN_PATTERN.findall(text)


def _validate_snapshot(snapshot: dict[str, Any], *, max_input_tokens: int) -> _ValidatedSnapshot:
    required = {
        "dataset_id",
        "owner_id",
        "collection_id",
        "dataset_type",
        "rows",
        "exclusions",
        "provenance",
        "manifest",
        "manifest_digest",
        "provenance_digest",
        "content_digest",
    }
    missing = sorted(required - set(snapshot))
    if missing:
        raise SnapshotValidationError("snapshot_fields_missing:" + ",".join(missing))
    dataset_type = snapshot["dataset_type"]
    if dataset_type not in DATASET_TYPES:
        raise SnapshotValidationError("dataset_type_invalid")
    rows = snapshot["rows"]
    exclusions = snapshot["exclusions"]
    provenance = snapshot["provenance"]
    manifest = snapshot["manifest"]
    if not isinstance(rows, list) or not isinstance(exclusions, list):
        raise SnapshotValidationError("snapshot_rows_invalid")
    if not isinstance(provenance, dict) or not isinstance(manifest, dict):
        raise SnapshotValidationError("snapshot_metadata_invalid")
    if snapshot["provenance_digest"] != _digest(provenance):
        raise SnapshotValidationError("provenance_digest_mismatch")
    if manifest.get("manifest_digest") != snapshot["manifest_digest"]:
        raise SnapshotValidationError("manifest_digest_mismatch")
    if manifest.get("content_digest") != snapshot["content_digest"]:
        raise SnapshotValidationError("manifest_content_digest_mismatch")
    if manifest.get("row_count") != len(rows) or manifest.get("excluded_count") != len(exclusions):
        raise SnapshotValidationError("manifest_count_mismatch")
    manifest_basis = {
        key: manifest.get(key)
        for key in (
            "schema_version",
            "owner_id",
            "collection_id",
            "dataset_type",
            "rows",
            "exclusions",
            "provenance_digest",
        )
    }
    if _digest(manifest_basis) != snapshot["manifest_digest"]:
        raise SnapshotValidationError("manifest_digest_mismatch")
    content = _jsonl_bytes(rows)
    if hashlib.sha256(content).hexdigest() != snapshot["content_digest"]:
        raise SnapshotValidationError("content_digest_mismatch")

    validated_rows: list[dict[str, Any]] = []
    row_ids: set[str] = set()
    case_ids: set[tuple[str, str]] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise SnapshotValidationError("row_invalid")
        row = dict(raw)
        row_id = str(row.get("row_id") or "").strip()
        case_id = str(row.get("case_id") or "").strip()
        split = row.get("split")
        if not row_id or row_id in row_ids:
            raise SnapshotValidationError("row_id_invalid")
        if not case_id or (case_id, str(split)) in case_ids:
            raise SnapshotValidationError("case_split_duplicate")
        if split not in SPLITS:
            raise SnapshotValidationError("split_invalid")
        row_ids.add(row_id)
        case_ids.add((case_id, str(split)))
        expected_row_digest = row.get("content_digest")
        row_basis = dict(row)
        row_basis.pop("content_digest", None)
        row_basis.pop("row_id", None)
        if expected_row_digest != _digest(row_basis):
            raise SnapshotValidationError(f"row_content_digest_mismatch:{row_id}")
        if row.get("record_type") != dataset_type:
            raise SnapshotValidationError(f"row_type_mismatch:{row_id}")
        _validate_row_shape(row, dataset_type=dataset_type, row_id=row_id, max_input_tokens=max_input_tokens)
        validated_rows.append(row)
    _validate_split_isolation(validated_rows)
    return _ValidatedSnapshot(snapshot=snapshot, rows=tuple(validated_rows))


def _validate_row_shape(
    row: dict[str, Any], *, dataset_type: str, row_id: str, max_input_tokens: int
) -> None:
    source_refs = row.get("source_refs")
    if not isinstance(source_refs, list) or any(not str(item).strip() for item in source_refs):
        raise SnapshotValidationError(f"source_refs_invalid:{row_id}")
    if dataset_type == "evaluation":
        input_text = _text(row.get("input"))
        if not input_text:
            raise SnapshotValidationError(f"input_missing:{row_id}")
        if len(tokenize(input_text)) > max_input_tokens:
            raise SnapshotValidationError(f"context_overflow:{row_id}")
        if not isinstance(row.get("evidence"), list) or not isinstance(row.get("criteria"), list):
            raise SnapshotValidationError(f"evaluation_fields_invalid:{row_id}")
        return
    if dataset_type == "sft":
        messages = row.get("messages")
        target = _text(row.get("target"))
        if not isinstance(messages, list) or not messages or not target:
            raise SnapshotValidationError(f"sft_fields_invalid:{row_id}")
        prompt = _messages_text(messages)
        if len(tokenize(prompt) + tokenize(target)) > max_input_tokens:
            raise SnapshotValidationError(f"context_overflow:{row_id}")
        return
    prompt = row.get("prompt")
    chosen = _text(row.get("chosen"))
    rejected = _text(row.get("rejected"))
    if not isinstance(prompt, list) or not prompt or not chosen or not rejected or chosen == rejected:
        raise SnapshotValidationError(f"preference_fields_invalid:{row_id}")
    if len(tokenize(_messages_text(prompt)) + tokenize(chosen) + tokenize(rejected)) > max_input_tokens:
        raise SnapshotValidationError(f"context_overflow:{row_id}")


def _prepare_row(row: dict[str, Any], *, dataset_type: str, max_input_tokens: int) -> dict[str, Any]:
    prepared = dict(row)
    if dataset_type == "evaluation":
        prepared["input_tokens"] = tokenize(_text(row["input"]))
        prepared["token_count"] = len(prepared["input_tokens"])
    elif dataset_type == "sft":
        prompt_tokens = tokenize(_messages_text(row["messages"]))
        target_tokens = tokenize(_text(row["target"]))
        prepared["tokens"] = prompt_tokens + ["<target>"] + target_tokens
        prepared["loss_mask"] = [0] * (len(prompt_tokens) + 1) + [1] * len(target_tokens)
        prepared["token_count"] = len(prepared["tokens"])
    else:
        prompt_tokens = tokenize(_messages_text(row["prompt"]))
        chosen_tokens = tokenize(_text(row["chosen"]))
        rejected_tokens = tokenize(_text(row["rejected"]))
        prepared["prompt_tokens"] = prompt_tokens
        prepared["chosen_tokens"] = chosen_tokens
        prepared["rejected_tokens"] = rejected_tokens
        prepared["token_count"] = len(prompt_tokens) + max(len(chosen_tokens), len(rejected_tokens))
    if prepared["token_count"] > max_input_tokens and dataset_type != "preference":
        raise SnapshotValidationError(f"context_overflow:{row['row_id']}")
    return prepared


def _validate_split_isolation(rows: Iterable[dict[str, Any]]) -> None:
    seen: dict[str, set[str]] = {}
    for row in rows:
        split = str(row["split"])
        values = list(row.get("paper_family_keys") or [])
        session_tree_id = row.get("session_tree_id")
        if session_tree_id:
            values.append(f"session:{session_tree_id}")
        for value in values:
            key = str(value).strip()
            if key:
                seen.setdefault(key, set()).add(split)
    leaked = sorted(key for key, splits in seen.items() if len(splits) > 1)
    if leaked:
        raise SnapshotValidationError("split_leakage:" + ",".join(leaked))


def _messages_text(messages: list[Any]) -> str:
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            raise SnapshotValidationError("message_invalid")
        role = _text(message.get("role"))
        content = _text(message.get("content"))
        if not role or not content:
            raise SnapshotValidationError("message_invalid")
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _read_json_object(path: Path, *, error_prefix: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SnapshotValidationError(f"{error_prefix}_not_found:{path}") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotValidationError(f"{error_prefix}_malformed_json:{exc.lineno}") from exc
    if not isinstance(value, dict):
        raise SnapshotValidationError(f"{error_prefix}_object_required")
    return value


def _read_jsonl(path: Path, *, error_prefix: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise SnapshotValidationError(f"{error_prefix}_not_found:{path}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SnapshotValidationError(f"{error_prefix}_malformed_json:{line_number}") from exc
        if not isinstance(value, dict):
            raise SnapshotValidationError(f"{error_prefix}_row_invalid:{line_number}")
        rows.append(value)
    return rows


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_bytes(_jsonl_bytes(rows))


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _git_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


if __name__ == "__main__":
    main()


__all__ = [
    "PREPARED_SCHEMA_VERSION",
    "SnapshotValidationError",
    "load_prepared",
    "prepare_snapshot",
    "tokenize",
]
