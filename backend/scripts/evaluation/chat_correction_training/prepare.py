#!/usr/bin/env python3
"""Validate a P4 Chat correction export and prepare masked training rows.

This module intentionally has no training-framework import at module load time.
The online Lens runtime therefore remains independent from the optional training
environment.  The exported request and observations are copied into every
prepared row so an experiment can be audited back to the reviewed sample.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Protocol, Sequence


BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from domain.evaluation import (  # noqa: E402
    ChatCorrectionDatasetExclusion,
    ChatCorrectionDatasetManifest,
    ChatCorrectionDatasetRow,
    canonical_json,
    sample_digest,
)


PREPARED_SCHEMA_VERSION = "chat-correction-training.v1"
MANIFEST_SCHEMA_VERSION = "chat-correction-dataset.v1"
MASKED_LABEL = -100
DEFAULT_MAX_LENGTH = 4096
_PLACEHOLDER_CREATED_AT = "1970-01-01T00:00:00+00:00"


class PreparationError(ValueError):
    """The export cannot be used as an auditable training input."""


class ContextOverflowError(PreparationError):
    """A complete reviewed example does not fit the configured context."""


class ExportNotFoundError(PreparationError):
    """The requested JSONL export does not exist or is unreadable."""


class Tokenizer(Protocol):
    eos_token_id: int | None

    def encode(self, text: str, *, add_special_tokens: bool = False) -> Sequence[int]: ...


@dataclass(frozen=True)
class ExportBundle:
    """The verified P4 manifest and its source-line metadata."""

    manifest: ChatCorrectionDatasetManifest
    manifest_record: dict[str, Any]

    @property
    def rows(self) -> tuple[ChatCorrectionDatasetRow, ...]:
        return self.manifest.rows

    @property
    def exclusions(self) -> tuple[ChatCorrectionDatasetExclusion, ...]:
        return self.manifest.exclusions


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSON objects while retaining useful line numbers in failures."""

    if not path.is_file():
        raise ExportNotFoundError(f"P4 export does not exist: {path}")
    records: list[dict[str, Any]] = []
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        raise ExportNotFoundError(f"cannot read P4 export: {path}") from exc
    with handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise PreparationError(
                    f"invalid JSON in P4 export line {line_number}: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise PreparationError(f"P4 export line {line_number} must be an object")
            records.append(value)
    return records


def load_export(path: str | Path) -> ExportBundle:
    """Parse and verify one P4 JSONL export before any tokenization occurs."""

    records = read_jsonl(Path(path))
    manifest_records = [item for item in records if item.get("record_type") == "manifest"]
    if len(manifest_records) != 1:
        raise PreparationError("P4 export must contain exactly one manifest record")
    manifest_record = manifest_records[0]
    sample_records = [item for item in records if item.get("record_type") == "sample"]
    exclusion_records = [item for item in records if item.get("record_type") == "excluded"]
    known_types = {"manifest", "sample", "excluded"}
    unknown = sorted(
        str(item.get("record_type"))
        for item in records
        if item.get("record_type") not in known_types
    )
    if unknown:
        raise PreparationError("P4 export contains unknown record types: " + ", ".join(unknown))

    provenance = manifest_record.get("provenance")
    if not isinstance(provenance, dict):
        raise PreparationError("manifest provenance must be an object")
    owner_id = str(provenance.get("owner_id") or "").strip()
    if not owner_id:
        raise PreparationError("manifest provenance does not identify the authorized owner")
    collection_id = str(manifest_record.get("collection_id") or "").strip()
    dataset_id = str(manifest_record.get("dataset_id") or "").strip()
    digest = str(manifest_record.get("manifest_digest") or "").strip().lower()
    provenance_digest = str(manifest_record.get("provenance_digest") or "").strip().lower()
    if not collection_id or not dataset_id or len(digest) != 64:
        raise PreparationError("manifest record is missing dataset identity or digest")
    if provenance_digest != sample_digest(provenance):
        raise PreparationError("manifest provenance digest does not match its content")
    if provenance.get("schema") not in {None, MANIFEST_SCHEMA_VERSION}:
        raise PreparationError("unsupported P4 manifest schema")

    try:
        rows = tuple(ChatCorrectionDatasetRow.from_mapping(item) for item in sample_records)
        exclusions = tuple(
            ChatCorrectionDatasetExclusion.from_mapping(item) for item in exclusion_records
        )
        manifest = ChatCorrectionDatasetManifest(
            dataset_id=dataset_id,
            owner_id=owner_id,
            collection_id=collection_id,
            provenance=deepcopy(provenance),
            rows=rows,
            exclusions=exclusions,
            digest=digest,
            created_at=_PLACEHOLDER_CREATED_AT,
            schema_version=MANIFEST_SCHEMA_VERSION,
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise PreparationError(f"P4 manifest digest or row validation failed: {exc}") from exc

    if manifest.dataset_id != f"chat_dataset_{manifest.digest[:40]}":
        raise PreparationError("manifest dataset_id is inconsistent with its digest")
    _validate_partitions(manifest)
    return ExportBundle(manifest=manifest, manifest_record=deepcopy(manifest_record))


def _validate_partitions(manifest: ChatCorrectionDatasetManifest) -> None:
    if not manifest.rows:
        raise PreparationError("P4 manifest contains no accepted rows")
    by_split: dict[str, list[ChatCorrectionDatasetRow]] = {"train": [], "eval": []}
    seen_sample_ids: set[str] = set()
    seen_row_ids: set[str] = set()
    content_assignments: dict[str, str] = {}
    family_assignments: dict[str, str] = {}
    tree_assignments: dict[str, str] = {}
    for row in manifest.rows:
        split = row.split.value
        if split not in by_split:
            raise PreparationError(f"unsupported dataset split: {split}")
        if row.collection_id != manifest.collection_id:
            raise PreparationError("dataset row crosses collections")
        if row.sample_id in seen_sample_ids or row.row_id in seen_row_ids:
            raise PreparationError("dataset rows must have unique sample and row identities")
        seen_sample_ids.add(row.sample_id)
        seen_row_ids.add(row.row_id)
        if not row.input or not isinstance(row.input, dict):
            raise PreparationError(f"row {row.row_id} has no complete model request")
        if not row.observations:
            raise PreparationError(f"row {row.row_id} has no tool/message observations")
        if not row.target.strip():
            raise PreparationError(f"row {row.row_id} has an empty reviewed target")
        if not row.source_refs:
            raise PreparationError(f"row {row.row_id} has no Source references")
        if not row.paper_families:
            raise PreparationError(f"row {row.row_id} has no paper-family identity")
        by_split[split].append(row)

        content_key = sample_digest(
            {"input": row.input, "observations": list(row.observations), "target": row.target}
        )
        previous_split = content_assignments.setdefault(content_key, split)
        if previous_split != split:
            raise PreparationError("identical reviewed content leaks across train and eval")
        for family in row.paper_families:
            family_id = str(family.get("family_id") or "").strip()
            if not family_id:
                raise PreparationError(f"row {row.row_id} has an empty paper-family identity")
            previous_split = family_assignments.setdefault(family_id, split)
            if previous_split != split:
                raise PreparationError(
                    f"paper family {family_id} appears in both train and eval partitions"
                )
        tree_id = row.session_tree_id.strip()
        previous_split = tree_assignments.setdefault(tree_id, split)
        if previous_split != split:
            raise PreparationError(
                f"session tree {tree_id} appears in both train and eval partitions"
            )
    if not by_split["train"] or not by_split["eval"]:
        raise PreparationError("nonempty train and eval partitions are required")


def build_prompt(row: ChatCorrectionDatasetRow) -> str:
    """Serialize the exact reviewed request and observations without loss."""

    payload = {
        "request": deepcopy(row.input),
        "tool_observations": [deepcopy(item) for item in row.observations],
    }
    return canonical_json(payload) + "\nFINAL ANSWER:\n"


def _token_ids(tokenizer: Tokenizer, text: str, field_name: str) -> list[int]:
    try:
        values = list(tokenizer.encode(text, add_special_tokens=False))
    except Exception as exc:  # pragma: no cover - provider tokenizer-specific failures
        raise PreparationError(f"tokenizer failed while encoding {field_name}") from exc
    if any(not isinstance(value, int) or value < 0 for value in values):
        raise PreparationError(f"tokenizer returned invalid IDs for {field_name}")
    return values


def encode_row(
    row: ChatCorrectionDatasetRow,
    tokenizer: Tokenizer,
    *,
    max_length: int,
) -> dict[str, Any]:
    """Encode one row while masking every prompt token with -100."""

    if max_length <= 0:
        raise PreparationError("max_length must be positive")
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if not isinstance(eos_token_id, int) or eos_token_id < 0:
        raise PreparationError("tokenizer must expose a valid eos_token_id")
    prompt = build_prompt(row)
    prompt_ids = _token_ids(tokenizer, prompt, "prompt")
    target_ids = _token_ids(tokenizer, row.target, "target")
    target_ids.append(eos_token_id)
    total_length = len(prompt_ids) + len(target_ids)
    if total_length > max_length:
        raise ContextOverflowError(
            f"row {row.row_id} requires {total_length} tokens but max_length is {max_length}; "
            "complete evidence must be shortened by an explicit review, not silently truncated"
        )
    return {
        "schema_version": PREPARED_SCHEMA_VERSION,
        "row_id": row.row_id,
        "sample_id": row.sample_id,
        "case_id": row.case_id,
        "session_id": row.session_id,
        "collection_id": row.collection_id,
        "session_tree_id": row.session_tree_id,
        "split": row.split.value,
        "paper_family_ids": sorted({item["family_id"] for item in row.paper_families}),
        "review_digest": row.review_digest,
        "source_refs": deepcopy(list(row.source_refs)),
        "request": deepcopy(row.input),
        "observations": deepcopy(list(row.observations)),
        "target": row.target,
        "prompt": prompt,
        "prompt_token_count": len(prompt_ids),
        "target_token_count": len(target_ids),
        "input_ids": prompt_ids + target_ids,
        "labels": [MASKED_LABEL] * len(prompt_ids) + target_ids,
        "attention_mask": [1] * total_length,
    }


def prepare_rows(
    bundle: ExportBundle,
    tokenizer: Tokenizer,
    *,
    max_length: int = DEFAULT_MAX_LENGTH,
) -> tuple[dict[str, Any], ...]:
    """Prepare rows in stable sample order for deterministic experiments."""

    return tuple(
        encode_row(row, tokenizer, max_length=max_length)
        for row in sorted(
            bundle.rows,
            key=lambda item: ({"train": 0, "eval": 1}[item.split.value], item.sample_id),
        )
    )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def write_prepared(
    bundle: ExportBundle,
    rows: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    tokenizer_name: str,
    tokenizer_revision: str | None,
    max_length: int,
) -> Path:
    """Write a new immutable preparation directory and its lineage metadata."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=False)
    grouped = {"train": [], "eval": []}
    expected_row_ids = {row.row_id for row in bundle.rows}
    written_row_ids: set[str] = set()
    for row in rows:
        split = str(row.get("split") or "")
        if split not in grouped:
            raise PreparationError(f"prepared row has unsupported split: {split}")
        row_id = str(row.get("row_id") or "")
        if not row_id or row_id in written_row_ids:
            raise PreparationError("prepared rows must retain unique source row IDs")
        written_row_ids.add(row_id)
        grouped[split].append(dict(row))
    if written_row_ids != expected_row_ids:
        raise PreparationError("prepared rows do not match the verified P4 manifest")
    if not grouped["train"] or not grouped["eval"]:
        raise PreparationError("nonempty train and eval partitions are required")

    file_digests: dict[str, str] = {}
    for split in ("train", "eval"):
        path = destination / f"{split}.jsonl"
        with path.open("x", encoding="utf-8") as handle:
            for row in grouped[split]:
                handle.write(canonical_json(row) + "\n")
        file_digests[split] = _sha256_file(path)
    metadata = {
        "schema_version": PREPARED_SCHEMA_VERSION,
        "dataset_id": bundle.manifest.dataset_id,
        "dataset_digest": bundle.manifest.digest,
        "manifest_digest": bundle.manifest.digest,
        "provenance_digest": bundle.manifest.provenance_digest,
        "owner_id": bundle.manifest.owner_id,
        "collection_id": bundle.manifest.collection_id,
        "tokenizer": tokenizer_name,
        "tokenizer_revision": tokenizer_revision,
        "max_length": max_length,
        "train_count": len(grouped["train"]),
        "eval_count": len(grouped["eval"]),
        "file_digests": file_digests,
        "review_digests": sorted({row.review_digest for row in bundle.rows}),
        "source_refs": [
            deepcopy(source)
            for row in sorted(bundle.rows, key=lambda item: item.sample_id)
            for source in row.source_refs
        ],
        "exclusions": [item.to_record() for item in bundle.exclusions],
        "provenance": deepcopy(bundle.manifest.provenance),
    }
    metadata["metadata_digest"] = sample_digest(metadata)
    _write_json(destination / "manifest.json", metadata)
    return destination


def _load_tokenizer(name: str, revision: str | None, *, local_files_only: bool) -> Any:
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:  # pragma: no cover - depends on isolated environment
        raise PreparationError(
            "transformers is required for tokenization; install it in the isolated training environment"
        ) from exc
    kwargs: dict[str, Any] = {"local_files_only": local_files_only}
    if revision:
        kwargs["revision"] = revision
    try:
        return AutoTokenizer.from_pretrained(name, **kwargs)
    except Exception as exc:  # pragma: no cover - model cache/network specific
        raise PreparationError(f"tokenizer environment is unavailable: {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="P4 JSONL export")
    parser.add_argument("output", type=Path, help="new preparation directory")
    parser.add_argument("--tokenizer", help="transformers tokenizer name or local path")
    parser.add_argument("--revision", help="fixed tokenizer revision")
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="verify the P4 export without importing a training tokenizer",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = load_export(args.manifest)
    if args.validate_only:
        print(
            json.dumps(
                {
                    "status": "valid",
                    "dataset_id": bundle.manifest.dataset_id,
                    "dataset_digest": bundle.manifest.digest,
                    "train_count": sum(row.split.value == "train" for row in bundle.rows),
                    "eval_count": sum(row.split.value == "eval" for row in bundle.rows),
                    "excluded_count": len(bundle.exclusions),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return
    if not args.tokenizer:
        raise SystemExit("--tokenizer is required unless --validate-only is used")
    tokenizer = _load_tokenizer(
        args.tokenizer,
        args.revision,
        local_files_only=args.local_files_only,
    )
    rows = prepare_rows(bundle, tokenizer, max_length=args.max_length)
    destination = write_prepared(
        bundle,
        rows,
        args.output,
        tokenizer_name=args.tokenizer,
        tokenizer_revision=args.revision,
        max_length=args.max_length,
    )
    print(json.dumps({"status": "prepared", "output": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = [
    "ContextOverflowError",
    "ExportBundle",
    "PreparationError",
    "PREPARED_SCHEMA_VERSION",
    "build_prompt",
    "encode_row",
    "load_export",
    "prepare_rows",
    "read_jsonl",
    "write_prepared",
]
