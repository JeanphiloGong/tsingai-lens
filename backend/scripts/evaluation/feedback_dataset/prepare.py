#!/usr/bin/env python3
"""Validate a published DatasetExport for an offline experiment.

The online feedback workbench publishes three immutable files: a model-facing
data file, a provenance sidecar, and a manifest. This module is the boundary
between that release and an offline experiment. It never reads the legacy
DatasetSnapshot shape and it never writes back to online state.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable


PREPARED_SCHEMA_VERSION = "feedback-offline-prepared.v4"
EXPORT_MANIFEST_SCHEMA_VERSION = "feedback-dataset-export-manifest.v1"
TOKENIZER_NAME = "lens-whitespace-v1"
TOKENIZER_VERSION = 1
DATASET_TYPES = {"evaluation", "sft", "preference"}
SPLITS = {"train", "eval"}
TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
TASK_SCHEMA_TO_TYPE = {
    "literature-sft.v1": "sft",
    "literature-preference.v1": "preference",
    "literature-evaluation.v1": "evaluation",
}

# These identities belong in the provenance sidecar, never in model-facing
# rows. ``row_id`` is added only inside the private experiment directory.
_INTERNAL_ROW_FIELDS = frozenset(
    {
        "row_id",
        "case_id",
        "session_id",
        "review_id",
        "annotation_digest",
        "source_ref",
        "source_refs",
        "document_id",
        "document_ids",
        "paper_family_keys",
        "paper_families",
        "session_tree_id",
        "content_digest",
        "revision_id",
        "sample_id",
        "source_case_id",
        "input_digest",
        "locator",
        "page",
        "heading_path",
        "block_id",
    }
)


class SnapshotValidationError(ValueError):
    """Raised when a published export cannot safely enter an offline run."""


@dataclass(frozen=True)
class _ValidatedExport:
    manifest: dict[str, Any]
    rows: tuple[dict[str, Any], ...]
    provenance: tuple[dict[str, Any], ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a DatasetExport directory and create a deterministic "
            "offline experiment directory."
        )
    )
    parser.add_argument(
        "export_path",
        type=Path,
        help="Export directory, manifest.json, or data.jsonl file.",
    )
    parser.add_argument("output_dir", type=Path, help="Directory for prepared artifacts.")
    parser.add_argument("--manifest", type=Path, help="Manifest sidecar when export_path is data.jsonl.")
    parser.add_argument("--provenance", type=Path, help="Provenance sidecar when it is outside the export directory.")
    parser.add_argument("--revision", help="Source revision to record in the artifact.")
    parser.add_argument("--experiment-plan", type=Path, help="Reviewed experiment selection and split JSON.")
    parser.add_argument("--seed", type=int, default=0, help="Deterministic experiment seed.")
    parser.add_argument(
        "--max-input-tokens",
        type=int,
        default=4096,
        help="Maximum untruncated input token count per row.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = prepare_export(
        export_path=args.export_path,
        output_dir=args.output_dir,
        manifest_path=args.manifest,
        provenance_path=args.provenance,
        revision=args.revision,
        seed=args.seed,
        max_input_tokens=args.max_input_tokens,
        experiment_plan_path=args.experiment_plan,
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


def prepare_export(
    *,
    export_path: str | Path,
    output_dir: str | Path,
    manifest_path: str | Path | None = None,
    provenance_path: str | Path | None = None,
    revision: str | None = None,
    seed: int = 0,
    max_input_tokens: int = 4096,
    experiment_plan_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate a published export and write a reproducible experiment directory."""

    if seed < 0:
        raise SnapshotValidationError("seed_invalid")
    if max_input_tokens < 1:
        raise SnapshotValidationError("max_input_tokens_invalid")
    validated = _read_export_bundle(
        export_path=Path(export_path),
        manifest_path=Path(manifest_path) if manifest_path is not None else None,
        provenance_path=Path(provenance_path) if provenance_path is not None else None,
    )
    plan = (
        _read_json_object(Path(experiment_plan_path), error_prefix="experiment_plan")
        if experiment_plan_path is not None
        else None
    )
    experiment_rows, plan = _experiment_rows(validated, plan)
    revision_value = (revision or os.environ.get("LENS_REVISION") or _git_revision()).strip()
    if not revision_value:
        revision_value = "unknown"

    dataset_type = str(validated.manifest["dataset_type"])
    prepared_rows = _materialize_prepared_rows(
        experiment_rows,
        dataset_type=dataset_type,
        max_input_tokens=max_input_tokens,
    )
    split_rows = {
        split: [row for row in prepared_rows if row["split"] == split]
        for split in ("train", "eval")
    }
    rows_digest = _digest(prepared_rows)
    prepared_body = {
        "schema_version": PREPARED_SCHEMA_VERSION,
        "export": _export_metadata(validated.manifest),
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
        "experiment_plan_digest": _digest(plan),
        "experiment_mode": plan["mode"],
        "files": {
            "train": "train.jsonl",
            "eval": "eval.jsonl",
            "manifest": "export-manifest.json",
            "data": "export-data.jsonl",
            "provenance": "export-provenance.jsonl",
            "experiment_plan": "experiment-plan.json",
        },
        "status": "ready",
    }
    prepared = {**prepared_body, "prepared_digest": _digest(prepared_body)}

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    _write_json(destination / "export-manifest.json", validated.manifest)
    _write_jsonl(destination / "export-data.jsonl", validated.rows)
    _write_jsonl(destination / "export-provenance.jsonl", validated.provenance)
    _write_json(destination / "experiment-plan.json", plan)
    _write_json(destination / "prepared.json", prepared)
    for split, rows in split_rows.items():
        _write_jsonl(destination / f"{split}.jsonl", rows)
    return prepared


def prepare_snapshot(
    *,
    snapshot_path: str | Path,
    output_dir: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Keep the old Python function name without accepting old snapshot data."""

    return prepare_export(export_path=snapshot_path, output_dir=output_dir, **kwargs)


def load_prepared(prepared_dir: str | Path) -> dict[str, Any]:
    """Read and re-check a prepared directory before an experiment consumes it."""

    directory = Path(prepared_dir).expanduser().resolve()
    prepared = _read_json_object(directory / "prepared.json", error_prefix="prepared")
    if prepared.get("schema_version") != PREPARED_SCHEMA_VERSION:
        raise SnapshotValidationError("prepared_schema_invalid")
    prepared_digest = prepared.get("prepared_digest")
    if not isinstance(prepared_digest, str) or len(prepared_digest) != 64:
        raise SnapshotValidationError("prepared_digest_missing")
    prepared_basis = dict(prepared)
    prepared_basis.pop("prepared_digest", None)
    if _digest(prepared_basis) != prepared_digest:
        raise SnapshotValidationError("prepared_digest_mismatch")
    files = prepared.get("files")
    if not isinstance(files, dict):
        raise SnapshotValidationError("prepared_files_missing")
    for key in ("manifest", "data", "provenance", "experiment_plan"):
        filename = files.get(key)
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise SnapshotValidationError("prepared_file_name_invalid")
    max_input_tokens = prepared.get("max_input_tokens")
    if not isinstance(max_input_tokens, int) or max_input_tokens < 1:
        raise SnapshotValidationError("prepared_max_input_tokens_invalid")
    validated = _read_export_bundle(
        export_path=directory / files["manifest"],
        manifest_path=directory / files["manifest"],
        provenance_path=directory / files["provenance"],
        data_path=directory / files["data"],
    )
    plan = _read_json_object(directory / files["experiment_plan"], error_prefix="experiment_plan")
    if _digest(plan) != prepared.get("experiment_plan_digest"):
        raise SnapshotValidationError("experiment_plan_digest_mismatch")
    experiment_rows, _ = _experiment_rows(validated, plan)
    if prepared.get("experiment_mode") != plan.get("mode"):
        raise SnapshotValidationError("experiment_mode_mismatch")
    if prepared.get("export") != _export_metadata(validated.manifest):
        raise SnapshotValidationError("prepared_export_metadata_mismatch")

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
    expected_rows = _materialize_prepared_rows(
        experiment_rows,
        dataset_type=str(validated.manifest["dataset_type"]),
        max_input_tokens=max_input_tokens,
    )
    if sorted(all_rows, key=lambda row: (str(row.get("split")), str(row.get("row_id")))) != expected_rows:
        raise SnapshotValidationError("prepared_export_rows_mismatch")
    result = dict(prepared)
    result["rows_by_split"] = rows_by_split
    return result


def tokenize(text: str) -> list[str]:
    """Tokenize deterministically for protocol accounting, not model training."""

    return TOKEN_PATTERN.findall(text)


def _read_export_bundle(
    *,
    export_path: Path,
    manifest_path: Path | None,
    provenance_path: Path | None,
    data_path: Path | None = None,
) -> _ValidatedExport:
    source = export_path.expanduser().resolve()
    if not source.exists():
        raise SnapshotValidationError(f"export_not_found:{source}")

    inline_rows: list[dict[str, Any]] | None = None
    inline_provenance: list[dict[str, Any]] | None = None
    base = source.parent
    if source.is_dir():
        manifest_file = (manifest_path or source / "manifest.json").resolve()
        manifest = _read_json_object(manifest_file, error_prefix="manifest")
        base = manifest_file.parent
    elif source.suffix.lower() == ".jsonl":
        data_path = source
        manifest_file = (manifest_path or source.parent / "manifest.json").resolve()
        manifest = _read_json_object(manifest_file, error_prefix="manifest")
        base = manifest_file.parent
    elif source.suffix.lower() == ".json":
        raw = _read_json_object(source, error_prefix="export")
        if isinstance(raw.get("manifest"), dict):
            manifest = dict(raw["manifest"])
            inline_rows = raw.get("rows") if isinstance(raw.get("rows"), list) else None
            inline_provenance = raw.get("provenance") if isinstance(raw.get("provenance"), list) else None
        elif "manifest_schema_version" in raw:
            manifest = raw
        else:
            # DatasetExport.to_record() has no rows and is not an offline
            # bundle. Legacy DatasetSnapshot data is rejected at this boundary.
            raise SnapshotValidationError("export_manifest_schema_invalid")
        base = source.parent
    else:
        raise SnapshotValidationError("export_path_invalid")

    validated_manifest = _validate_manifest(manifest)
    if inline_rows is not None:
        rows = tuple(dict(row) for row in inline_rows if isinstance(row, dict))
    else:
        filename = (data_path or base / str(validated_manifest["main_file"])).resolve()
        rows = tuple(_read_data_file(filename))
    if inline_provenance is not None:
        provenance = tuple(dict(item) for item in inline_provenance if isinstance(item, dict))
    else:
        filename = (provenance_path or base / str(validated_manifest["provenance_file"])).resolve()
        provenance = tuple(_read_jsonl(filename, error_prefix="provenance"))
    return _validate_export_contents(validated_manifest, rows, provenance)


def _validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("manifest_schema_version") != EXPORT_MANIFEST_SCHEMA_VERSION:
        raise SnapshotValidationError("export_manifest_schema_invalid")
    schema_version = manifest.get("schema_version")
    dataset_type = manifest.get("dataset_type")
    if schema_version not in TASK_SCHEMA_TO_TYPE or dataset_type != TASK_SCHEMA_TO_TYPE[schema_version]:
        raise SnapshotValidationError("export_task_schema_invalid")
    for field in ("dataset_id", "export_id", "collection_id", "main_file", "provenance_file"):
        if not isinstance(manifest.get(field), str) or not str(manifest[field]).strip():
            raise SnapshotValidationError(f"export_manifest_{field}_invalid")
    for field in ("main_file", "provenance_file"):
        if Path(str(manifest[field])).name != str(manifest[field]):
            raise SnapshotValidationError("export_manifest_file_invalid")
    if not isinstance(manifest.get("export_no"), int) or manifest["export_no"] < 1:
        raise SnapshotValidationError("export_manifest_export_no_invalid")
    if not isinstance(manifest.get("row_count"), int) or manifest["row_count"] < 1:
        raise SnapshotValidationError("export_manifest_row_count_invalid")
    for field in (
        "member_digest",
        "preview_digest",
        "content_digest",
        "provenance_digest",
        "manifest_digest",
    ):
        if not _is_sha256(manifest.get(field)):
            raise SnapshotValidationError(f"export_manifest_{field}_invalid")
    supplied_digest = manifest["manifest_digest"]
    basis = dict(manifest)
    basis.pop("manifest_digest", None)
    if _digest(basis) != supplied_digest:
        raise SnapshotValidationError("export_manifest_digest_mismatch")
    return dict(manifest)


def _validate_export_contents(
    manifest: dict[str, Any], rows: tuple[dict[str, Any], ...], provenance: tuple[dict[str, Any], ...]
) -> _ValidatedExport:
    if len(rows) != manifest["row_count"]:
        raise SnapshotValidationError("export_row_count_mismatch")
    if len(provenance) != len(rows):
        raise SnapshotValidationError("export_provenance_count_mismatch")
    content_bytes = _jsonl_bytes(rows)
    if hashlib.sha256(content_bytes).hexdigest() != manifest["content_digest"]:
        raise SnapshotValidationError("export_content_digest_mismatch")
    if _digest(list(provenance)) != manifest["provenance_digest"]:
        raise SnapshotValidationError("export_provenance_digest_mismatch")
    seen_keys: set[str] = set()
    for index, (row, item) in enumerate(zip(rows, provenance, strict=True), start=1):
        if not isinstance(row, dict):
            raise SnapshotValidationError(f"export_row_invalid:{index}")
        forbidden = _first_internal_field(row)
        if forbidden is not None:
            raise SnapshotValidationError(f"row_internal_field:{forbidden}")
        if not isinstance(item, dict):
            raise SnapshotValidationError(f"export_provenance_item_invalid:{index}")
        row_key = str(item.get("row_key") or "")
        if not _is_sha256(row_key) or row_key in seen_keys:
            raise SnapshotValidationError(f"export_provenance_row_key_invalid:{index}")
        seen_keys.add(row_key)
        if item.get("row_digest") != _digest(row):
            raise SnapshotValidationError(f"export_provenance_row_digest_mismatch:{index}")
        for key in ("sample_id", "source_case_id", "revision_id"):
            if not str(item.get(key) or "").strip():
                raise SnapshotValidationError(f"export_provenance_{key}_missing:{index}")
        _validate_row_shape(
            row,
            dataset_type=str(manifest["dataset_type"]),
            row_id=f"row_{index}",
            max_input_tokens=10**9,
        )
    return _ValidatedExport(manifest=dict(manifest), rows=rows, provenance=provenance)


def _export_metadata(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: manifest[key]
        for key in (
            "manifest_schema_version",
            "schema_version",
            "dataset_type",
            "dataset_id",
            "collection_id",
            "export_id",
            "export_no",
            "row_count",
            "content_digest",
            "provenance_digest",
            "manifest_digest",
        )
    }


def _validate_row_shape(
    row: dict[str, Any], *, dataset_type: str, row_id: str, max_input_tokens: int
) -> None:
    _validate_readable_items(row.get("context"), field="context", row_id=row_id)
    _validate_evidence(row.get("evidence"), row_id=row_id)
    if dataset_type == "evaluation":
        messages = row.get("messages")
        if not isinstance(messages, list) or not messages:
            raise SnapshotValidationError(f"evaluation_messages_invalid:{row_id}")
        _messages_text(messages)
        criteria = row.get("criteria")
        if not isinstance(criteria, list) or not any(_text(item) for item in criteria):
            raise SnapshotValidationError(f"evaluation_criteria_invalid:{row_id}")
        mode = str(row.get("evaluation_mode") or "")
        if mode not in {"reference", "rubric"}:
            raise SnapshotValidationError(f"evaluation_mode_invalid:{row_id}")
        if mode == "reference" and not _text(row.get("reference")):
            raise SnapshotValidationError(f"evaluation_reference_missing:{row_id}")
        if len(tokenize(_input_text(row))) > max_input_tokens:
            raise SnapshotValidationError(f"context_overflow:{row_id}")
        return
    messages = row.get("messages")
    if not isinstance(messages, list) or not messages:
        raise SnapshotValidationError(f"messages_invalid:{row_id}")
    if dataset_type == "sft":
        prompt, target = _sft_prompt_target(row, row_id=row_id)
        if not target:
            raise SnapshotValidationError(f"sft_target_missing:{row_id}")
        if len(tokenize(_messages_text(prompt)) + tokenize(target)) > max_input_tokens:
            raise SnapshotValidationError(f"context_overflow:{row_id}")
        return
    chosen = _text(row.get("chosen"))
    rejected = _text(row.get("rejected"))
    if not chosen or not rejected or chosen == rejected:
        raise SnapshotValidationError(f"preference_fields_invalid:{row_id}")
    if len(tokenize(_messages_text(messages)) + tokenize(chosen) + tokenize(rejected)) > max_input_tokens:
        raise SnapshotValidationError(f"context_overflow:{row_id}")


def _prepare_row(
    row: dict[str, Any], *, row_id: str, dataset_type: str, max_input_tokens: int
) -> dict[str, Any]:
    prepared = {"row_id": row_id, **row}
    if dataset_type == "evaluation":
        prepared["input_tokens"] = tokenize(_input_text(row))
        prepared["token_count"] = len(prepared["input_tokens"])
    elif dataset_type == "sft":
        prompt, target = _sft_prompt_target(row, row_id=row_id)
        prompt_tokens = tokenize(_messages_text(prompt))
        target_tokens = tokenize(target)
        prepared["target"] = target
        prepared["tokens"] = prompt_tokens + ["<target>"] + target_tokens
        prepared["loss_mask"] = [0] * (len(prompt_tokens) + 1) + [1] * len(target_tokens)
        prepared["token_count"] = len(prepared["tokens"])
    else:
        prompt_tokens = tokenize(_messages_text(row["messages"]))
        chosen_tokens = tokenize(_text(row["chosen"]))
        rejected_tokens = tokenize(_text(row["rejected"]))
        prepared["prompt_tokens"] = prompt_tokens
        prepared["chosen_tokens"] = chosen_tokens
        prepared["rejected_tokens"] = rejected_tokens
        prepared["token_count"] = len(prompt_tokens) + max(len(chosen_tokens), len(rejected_tokens))
    if prepared["token_count"] > max_input_tokens and dataset_type != "preference":
        raise SnapshotValidationError(f"context_overflow:{row_id}")
    return prepared


def _materialize_prepared_rows(
    rows: Iterable[dict[str, Any]], *, dataset_type: str, max_input_tokens: int
) -> list[dict[str, Any]]:
    assignments = _assign_internal_row_ids(rows)
    prepared = [
        _prepare_row(row, row_id=row_id, dataset_type=dataset_type, max_input_tokens=max_input_tokens)
        for row, row_id in assignments
    ]
    return sorted(prepared, key=lambda row: (str(row["split"]), str(row["row_id"])))


def _assign_internal_row_ids(rows: Iterable[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    canonical = [(dict(row), _digest(row)) for row in rows]
    canonical.sort(key=lambda item: (str(item[0].get("split")), item[1], _canonical_json(item[0])))
    totals = Counter((str(row.get("split")), digest) for row, digest in canonical)
    occurrences: Counter[tuple[str, str]] = Counter()
    assignments: list[tuple[dict[str, Any], str]] = []
    for row, digest in canonical:
        key = (str(row.get("split")), digest)
        occurrences[key] += 1
        suffix = f"_{occurrences[key]:04d}" if totals[key] > 1 else ""
        assignments.append((row, f"row_{digest[:32]}{suffix}"))
    return assignments


def _validate_readable_items(value: Any, *, field: str, row_id: str) -> None:
    if not isinstance(value, list) or not value:
        raise SnapshotValidationError(f"{field}_invalid:{row_id}")
    for item in value:
        if not isinstance(item, dict):
            raise SnapshotValidationError(f"{field}_item_invalid:{row_id}")
        if not _text(item.get("document_title")) or not _text(item.get("text", item.get("quote"))):
            raise SnapshotValidationError(f"{field}_content_missing:{row_id}")
        forbidden = _first_internal_field(item)
        if forbidden is not None:
            raise SnapshotValidationError(f"{field}_internal_field:{forbidden}")


def _validate_evidence(value: Any, *, row_id: str) -> None:
    _validate_readable_items(value, field="evidence", row_id=row_id)


def _first_internal_field(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in _INTERNAL_ROW_FIELDS:
                return str(key)
            nested = _first_internal_field(child)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for child in value:
            nested = _first_internal_field(child)
            if nested is not None:
                return nested
    return None


def _sft_prompt_target(row: dict[str, Any], *, row_id: str) -> tuple[list[dict[str, Any]], str]:
    messages = row.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        raise SnapshotValidationError(f"sft_messages_invalid:{row_id}")
    parsed = []
    for item in messages:
        if not isinstance(item, dict) or not _text(item.get("role")) or not _text(item.get("content")):
            raise SnapshotValidationError(f"message_invalid:{row_id}")
        parsed.append(item)
    final = parsed[-1]
    if final.get("role") != "assistant":
        raise SnapshotValidationError(f"sft_target_message_invalid:{row_id}")
    prompt = parsed[:-1]
    if not any(item.get("role") == "user" for item in prompt):
        raise SnapshotValidationError(f"sft_user_message_missing:{row_id}")
    material = _model_input_material(row)
    if material:
        prompt.append({"role": "user", "content": material})
    return prompt, _text(final.get("content"))


def _model_input_material(row: dict[str, Any]) -> str:
    """Render readable source text into the actual SFT input prompt.

    ``context`` and ``evidence`` are model-facing text fields. Provenance
    identities are deliberately absent here and remain in the sidecar.
    Duplicate snippets are included once so storing the same passage as both
    context and supporting evidence does not double the training input.
    """

    sections: list[str] = []
    seen: set[tuple[str, str]] = set()
    for field, label in (("context", "Reference context"), ("evidence", "Supporting evidence")):
        rendered: list[str] = []
        for item in row.get(field) or ():
            if not isinstance(item, dict):
                continue
            title = _text(item.get("document_title"))
            text = _text(item.get("text", item.get("quote")))
            key = (title, text)
            if not title or not text or key in seen:
                continue
            seen.add(key)
            rendered.append(f"{title}: {text}")
        if rendered:
            sections.append(f"{label}:\n" + "\n".join(rendered))
    return "\n\n".join(sections)


def _input_text(row: dict[str, Any]) -> str:
    messages = row.get("messages")
    message_text = _messages_text(messages) if isinstance(messages, list) else ""
    context_text = "\n".join(
        _text(item.get("text", item.get("quote")))
        for item in (row.get("context") or [])
        if isinstance(item, dict)
    )
    evidence_text = "\n".join(
        _text(item.get("text", item.get("quote")))
        for item in (row.get("evidence") or [])
        if isinstance(item, dict)
    )
    return "\n".join(part for part in (message_text, context_text, evidence_text) if part)


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


def _experiment_rows(
    validated: _ValidatedExport, plan: dict[str, Any] | None
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    rows = validated.rows
    manifest_digest = validated.manifest["manifest_digest"]
    if plan is None:
        plan = {
            "schema_version": "feedback-experiment-plan.v2",
            "export_manifest_digest": manifest_digest,
            "mode": "evaluation_only",
            "rows": [{"row_digest": _digest(row), "split": "eval"} for row in rows],
            "document_groups": {},
        }
    required = {"schema_version", "export_manifest_digest", "mode", "rows", "document_groups"}
    if set(plan) != required:
        raise SnapshotValidationError("experiment_plan_fields_invalid")
    if plan["schema_version"] != "feedback-experiment-plan.v2":
        raise SnapshotValidationError("experiment_plan_schema_invalid")
    if plan["export_manifest_digest"] != manifest_digest:
        raise SnapshotValidationError("experiment_plan_export_mismatch")
    mode = plan["mode"]
    if mode not in {"evaluation_only", "train_eval"}:
        raise SnapshotValidationError("experiment_mode_invalid")
    assignments, groups = plan["rows"], plan["document_groups"]
    if not isinstance(assignments, list) or not isinstance(groups, dict):
        raise SnapshotValidationError("experiment_plan_shape_invalid")
    if any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip() for k, v in groups.items()):
        raise SnapshotValidationError("source_group_invalid")
    known = {_digest(row) for row in rows}
    selected: dict[str, dict[str, Any]] = {}
    for item in assignments:
        if not isinstance(item, dict) or not isinstance(item.get("row_digest"), str):
            raise SnapshotValidationError("experiment_assignment_invalid")
        allowed = {"row_digest", "split", "input_document_ids", "source_review_reason"}
        if set(item) - allowed:
            raise SnapshotValidationError("experiment_assignment_fields_invalid")
        digest = item["row_digest"]
        if digest not in known or digest in selected:
            raise SnapshotValidationError("experiment_row_unknown_or_duplicate")
        if item.get("split") not in SPLITS:
            raise SnapshotValidationError("experiment_split_invalid")
        if mode == "evaluation_only" and item["split"] != "eval":
            raise SnapshotValidationError("evaluation_only_train_forbidden")
        selected[digest] = item
    if not selected:
        raise SnapshotValidationError("experiment_rows_empty")
    if mode == "train_eval" and {item["split"] for item in selected.values()} != SPLITS:
        raise SnapshotValidationError("experiment_split_empty")
    if mode == "train_eval":
        isolation: list[dict[str, Any]] = []
        for row, source in zip(rows, validated.provenance, strict=True):
            digest = _digest(row)
            item = selected.get(digest)
            if item is None:
                continue
            docs = item.get("input_document_ids")
            reason = item.get("source_review_reason")
            source_docs = source.get("document_ids")
            if (
                not isinstance(docs, list)
                or not docs
                or any(not isinstance(doc, str) or not doc.strip() for doc in docs)
                or not isinstance(reason, str)
                or not reason.strip()
                or not isinstance(source_docs, list)
                or not set(source_docs).issubset(docs)
                or any(doc not in groups for doc in docs)
            ):
                raise SnapshotValidationError("source_group_unknown")
            tree = source.get("session_tree_id")
            if not isinstance(tree, str) or not tree.strip():
                raise SnapshotValidationError("session_tree_unknown")
            isolation.append(
                {
                    "split": item["split"],
                    "session_tree_id": tree,
                    "paper_family_keys": [f"document:{groups[doc]}" for doc in docs],
                }
            )
        _validate_split_isolation(isolation)
    return tuple({**row, "split": selected[_digest(row)]["split"]} for row in rows if _digest(row) in selected), plan


def _validate_split_isolation(provenance_items: Iterable[dict[str, Any]]) -> None:
    seen: dict[str, set[str]] = {}
    for item in provenance_items:
        split = str(item["split"])
        values = list(item.get("paper_family_keys") or [])
        session_tree_id = item.get("session_tree_id")
        if session_tree_id:
            values.append(f"session:{session_tree_id}")
        for value in values:
            key = str(value).strip()
            if key:
                seen.setdefault(key, set()).add(split)
    leaked = sorted(key for key, splits in seen.items() if len(splits) > 1)
    if leaked:
        raise SnapshotValidationError("split_leakage:" + ",".join(leaked))


def _read_json_object(path: Path, *, error_prefix: str) -> dict[str, Any]:
    try:
        value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SnapshotValidationError(f"{error_prefix}_not_found:{path}") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotValidationError(f"{error_prefix}_malformed_json:{exc.lineno}") from exc
    if not isinstance(value, dict):
        raise SnapshotValidationError(f"{error_prefix}_object_required")
    return value


def _read_jsonl(path: Path, *, error_prefix: str) -> list[dict[str, Any]]:
    try:
        lines = path.expanduser().resolve().read_text(encoding="utf-8").splitlines()
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


def _read_data_file(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        try:
            value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SnapshotValidationError(f"data_not_found:{path}") from exc
        except json.JSONDecodeError as exc:
            raise SnapshotValidationError(f"data_malformed_json:{exc.lineno}") from exc
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise SnapshotValidationError("data_array_required")
        return [dict(item) for item in value]
    return _read_jsonl(path, error_prefix="data")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_bytes(_jsonl_bytes(rows))


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _git_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


if __name__ == "__main__":
    main()


__all__ = [
    "EXPORT_MANIFEST_SCHEMA_VERSION",
    "PREPARED_SCHEMA_VERSION",
    "SnapshotValidationError",
    "load_prepared",
    "prepare_export",
    "prepare_snapshot",
    "tokenize",
]
