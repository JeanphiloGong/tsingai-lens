#!/usr/bin/env python3
"""Run an explicitly authorized, offline Chat correction experiment.

The experiment is deliberately separate from Lens online execution.  It reads
the immutable preparation directory produced by ``prepare.py``, evaluates the
same held-out rows before and after a bounded update, and records enough
lineage to rebuild the report without treating loss as scientific correctness.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sys
from typing import Any, Callable, Mapping, Sequence


BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from domain.evaluation import canonical_json, sample_digest  # noqa: E402
from scripts.evaluation.chat_correction_training.prepare import (  # noqa: E402
    MASKED_LABEL,
    PREPARED_SCHEMA_VERSION,
)


REPORT_SCHEMA_VERSION = "chat-correction-training-report.v1"
DEFAULT_SEED = 17
DEFAULT_MAX_STEPS = 24
DEFAULT_LEARNING_RATE = 1e-3
DEFAULT_MAX_NEW_TOKENS = 64


class ExperimentError(ValueError):
    """The prepared data or experiment contract is invalid."""


class ExperimentNotRun(ExperimentError):
    """The requested experiment could not run for an explicit prerequisite reason."""


@dataclass(frozen=True)
class PreparedBundle:
    metadata: dict[str, Any]
    train: tuple[dict[str, Any], ...]
    eval: tuple[dict[str, Any], ...]

    @property
    def dataset_digest(self) -> str:
        return str(self.metadata["dataset_digest"])

    @property
    def manifest_digest(self) -> str:
        return str(self.metadata["manifest_digest"])


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"cannot read JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ExperimentError(f"JSON artifact must be an object: {path}")
    return value


def _file_digest(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_rows(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.is_file():
        raise ExperimentError(f"prepared partition is missing: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ExperimentError(f"invalid prepared JSON on {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise ExperimentError(f"prepared row must be an object on {path}:{line_number}")
            rows.append(value)
    return tuple(rows)


def load_prepared(path: str | Path) -> PreparedBundle:
    """Load and validate the immutable output of ``prepare.py``."""

    root = Path(path)
    metadata = _read_json(root / "manifest.json")
    if metadata.get("schema_version") != PREPARED_SCHEMA_VERSION:
        raise ExperimentError("unsupported prepared data schema")
    for field in ("dataset_digest", "manifest_digest", "provenance_digest", "dataset_id"):
        value = str(metadata.get(field) or "").strip()
        if not value:
            raise ExperimentError(f"prepared metadata is missing {field}")
    if metadata["dataset_digest"] != metadata["manifest_digest"]:
        raise ExperimentError("prepared dataset and manifest digests disagree")
    metadata_digest = str(metadata.get("metadata_digest") or "")
    unsigned_metadata = deepcopy(metadata)
    unsigned_metadata.pop("metadata_digest", None)
    if not metadata_digest or metadata_digest != sample_digest(unsigned_metadata):
        raise ExperimentError("prepared metadata digest does not match its content")
    partitions = {split: _read_rows(root / f"{split}.jsonl") for split in ("train", "eval")}
    recorded_digests = metadata.get("file_digests")
    if not isinstance(recorded_digests, dict):
        raise ExperimentError("prepared metadata is missing partition file digests")
    for split, rows in partitions.items():
        path_value = root / f"{split}.jsonl"
        if recorded_digests.get(split) != _file_digest(path_value):
            raise ExperimentError(f"prepared {split} partition digest does not match metadata")
        if not rows:
            raise ExperimentError("nonempty train and eval partitions are required")
        for row in rows:
            _validate_prepared_row(row, split)
    _validate_partition_isolation(partitions["train"], partitions["eval"])
    return PreparedBundle(
        metadata=deepcopy(metadata),
        train=partitions["train"],
        eval=partitions["eval"],
    )


def _validate_prepared_row(row: Mapping[str, Any], expected_split: str) -> None:
    required = (
        "row_id",
        "sample_id",
        "session_id",
        "session_tree_id",
        "split",
        "paper_family_ids",
        "review_digest",
        "source_refs",
        "request",
        "observations",
        "target",
        "input_ids",
        "labels",
        "attention_mask",
    )
    missing = [field for field in required if field not in row]
    if missing:
        raise ExperimentError("prepared row is missing: " + ", ".join(missing))
    if row["split"] != expected_split:
        raise ExperimentError("prepared row is stored in the wrong partition")
    if not str(row["target"]).strip():
        raise ExperimentError("prepared row has an empty final target")
    if not isinstance(row["request"], dict) or not isinstance(row["observations"], list):
        raise ExperimentError("prepared row lost the complete request or observations")
    if not row["observations"]:
        raise ExperimentError("prepared row has no observations")
    if not isinstance(row["source_refs"], list) or not row["source_refs"]:
        raise ExperimentError("prepared row has no Source references")
    families = row["paper_family_ids"]
    if not isinstance(families, list) or not families or any(not str(item).strip() for item in families):
        raise ExperimentError("prepared row has no paper-family identity")
    input_ids = row["input_ids"]
    labels = row["labels"]
    attention_mask = row["attention_mask"]
    if not isinstance(input_ids, list) or not isinstance(labels, list) or not isinstance(attention_mask, list):
        raise ExperimentError("prepared token fields must be lists")
    if not input_ids or len(input_ids) != len(labels) or len(input_ids) != len(attention_mask):
        raise ExperimentError("prepared token fields must have equal nonzero lengths")
    if any(not isinstance(value, int) or value < 0 for value in input_ids):
        raise ExperimentError("prepared input_ids contain an invalid token")
    if any(
        not isinstance(value, int)
        or (value != MASKED_LABEL and value < 0)
        for value in labels
    ):
        raise ExperimentError("prepared labels contain an invalid token")
    first_target = next((index for index, value in enumerate(labels) if value != MASKED_LABEL), None)
    if first_target is None:
        raise ExperimentError("prepared row masks the final target completely")
    if any(value != MASKED_LABEL for value in labels[:first_target]):
        raise ExperimentError("prompt labels must be masked with -100")
    if any(value == MASKED_LABEL for value in labels[first_target:]):
        raise ExperimentError("only the prompt prefix may use -100 labels")
    if any(value != 1 for value in attention_mask):
        raise ExperimentError("prepared attention mask must mark every retained token")


def _validate_partition_isolation(
    train: Sequence[Mapping[str, Any]], eval_rows: Sequence[Mapping[str, Any]]
) -> None:
    train_families = {str(item) for row in train for item in row["paper_family_ids"]}
    eval_families = {str(item) for row in eval_rows for item in row["paper_family_ids"]}
    overlap = train_families & eval_families
    if overlap:
        raise ExperimentError("paper families leak across train/eval: " + ", ".join(sorted(overlap)))
    train_trees = {str(row["session_tree_id"]) for row in train}
    eval_trees = {str(row["session_tree_id"]) for row in eval_rows}
    overlap = train_trees & eval_trees
    if overlap:
        raise ExperimentError("session trees leak across train/eval: " + ", ".join(sorted(overlap)))
    train_content = {_content_key(row) for row in train}
    eval_content = {_content_key(row) for row in eval_rows}
    if train_content & eval_content:
        raise ExperimentError("identical request/observation/target content leaks across partitions")


def _content_key(row: Mapping[str, Any]) -> str:
    return sample_digest(
        {
            "request": row["request"],
            "observations": row["observations"],
            "target": row["target"],
        }
    )


def _lineage(bundle: PreparedBundle) -> dict[str, Any]:
    source_refs: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    review_digests: set[str] = set()
    for row in (*bundle.train, *bundle.eval):
        review_digests.add(str(row["review_digest"]))
        for source in row["source_refs"]:
            key = canonical_json(source)
            if key not in seen_sources:
                seen_sources.add(key)
                source_refs.append(deepcopy(source))
    return {
        "dataset_id": bundle.metadata["dataset_id"],
        "dataset_digest": bundle.dataset_digest,
        "manifest_digest": bundle.manifest_digest,
        "provenance_digest": bundle.metadata["provenance_digest"],
        "review_digests": sorted(review_digests),
        "source_refs": source_refs,
        "exclusions": deepcopy(bundle.metadata.get("exclusions") or []),
        "train_row_ids": [str(row["row_id"]) for row in bundle.train],
        "eval_row_ids": [str(row["row_id"]) for row in bundle.eval],
        "eval_partition_digest": sample_digest(
            [
                {
                    "row_id": row["row_id"],
                    "content": _content_key(row),
                }
                for row in bundle.eval
            ]
        ),
    }


def _safe_authorization(authorization: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(authorization, Mapping):
        return None
    return {
        "scope": str(authorization.get("scope") or ""),
        "dataset_digest": str(authorization.get("dataset_digest") or ""),
        "approved_by": str(authorization.get("approved_by") or ""),
        "approved_at": str(authorization.get("approved_at") or ""),
    }


def authorization_from_metadata(bundle: PreparedBundle) -> dict[str, Any] | None:
    value = (bundle.metadata.get("provenance") or {}).get("training_authorization")
    return deepcopy(value) if isinstance(value, dict) else None


def validate_authorization(
    bundle: PreparedBundle,
    authorization: Mapping[str, Any] | None,
) -> None:
    if not isinstance(authorization, Mapping):
        raise ExperimentNotRun("training authorization is absent")
    if str(authorization.get("dataset_digest") or "") != bundle.dataset_digest:
        raise ExperimentNotRun("training authorization does not name this dataset digest")
    if not str(authorization.get("approved_by") or "").strip():
        raise ExperimentNotRun("training authorization has no approver")
    if not str(authorization.get("approved_at") or "").strip():
        raise ExperimentNotRun("training authorization has no approval timestamp")
    if str(authorization.get("scope") or "") != "chat_correction_training":
        raise ExperimentNotRun("training authorization scope is not chat_correction_training")


def _validate_model_context(model: Any, bundle: PreparedBundle) -> None:
    config = getattr(model, "config", None)
    limits = [
        getattr(config, "max_position_embeddings", None),
        getattr(config, "n_positions", None),
    ]
    limits = [int(value) for value in limits if isinstance(value, int) and value > 0]
    if not limits:
        return
    limit = min(limits)
    longest = max(
        len(row["input_ids"]) for row in (*bundle.train, *bundle.eval)
    )
    if longest > limit:
        raise ExperimentError(
            f"prepared context length {longest} exceeds model context limit {limit}; "
            "review and re-prepare the sample instead of truncating it"
        )


def _tensor_batch(torch_module: Any, row: Mapping[str, Any], device: str) -> dict[str, Any]:
    return {
        "input_ids": torch_module.tensor([row["input_ids"]], dtype=torch_module.long, device=device),
        "attention_mask": torch_module.tensor(
            [row["attention_mask"]], dtype=torch_module.long, device=device
        ),
        "labels": torch_module.tensor([row["labels"]], dtype=torch_module.long, device=device),
    }


def evaluate_model(
    model: Any,
    tokenizer: Any,
    rows: Sequence[Mapping[str, Any]],
    *,
    torch_module: Any,
    device: str,
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
) -> dict[str, Any]:
    """Evaluate loss and a deterministic sample without changing model state."""

    if not rows:
        raise ExperimentError("cannot evaluate an empty partition")
    model.eval()
    losses: list[float] = []
    generations: list[dict[str, Any]] = []
    with torch_module.no_grad():
        for row in rows:
            batch = _tensor_batch(torch_module, row, device)
            output = model(**batch)
            loss = getattr(output, "loss", None)
            if loss is None:
                raise ExperimentError("model did not return a masked loss")
            loss_value = float(loss.detach().cpu())
            if not loss_value == loss_value or loss_value in {float("inf"), float("-inf")}:
                raise ExperimentError("model returned a non-finite loss")
            losses.append(loss_value)
            generation = _generate_one(
                model,
                tokenizer,
                row,
                torch_module=torch_module,
                device=device,
                max_new_tokens=max_new_tokens,
            )
            generations.append(generation)
    return {
        "mean_target_loss": sum(losses) / len(losses),
        "row_count": len(rows),
        "generations": generations,
    }


def _generate_one(
    model: Any,
    tokenizer: Any,
    row: Mapping[str, Any],
    *,
    torch_module: Any,
    device: str,
    max_new_tokens: int,
) -> dict[str, Any]:
    first_target = next(index for index, value in enumerate(row["labels"]) if value != MASKED_LABEL)
    prefix = torch_module.tensor(
        [row["input_ids"][:first_target]], dtype=torch_module.long, device=device
    )
    try:
        generated = model.generate(
            prefix,
            attention_mask=torch_module.ones_like(prefix),
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=getattr(tokenizer, "eos_token_id", None),
        )
        generated_ids = generated[0]
        if len(generated_ids) >= first_target:
            generated_ids = generated_ids[first_target:]
        values = generated_ids.tolist() if hasattr(generated_ids, "tolist") else generated_ids
        text = tokenizer.decode(values, skip_special_tokens=True)
        return {"row_id": row["row_id"], "text": str(text)}
    except Exception as exc:  # generation is diagnostic; loss remains authoritative
        return {"row_id": row["row_id"], "text": "", "error": type(exc).__name__}


def train_limited(
    model: Any,
    rows: Sequence[Mapping[str, Any]],
    *,
    torch_module: Any,
    device: str,
    max_steps: int,
    learning_rate: float,
) -> int:
    if not rows:
        raise ExperimentError("cannot train on an empty partition")
    if max_steps <= 0:
        raise ExperimentError("max_steps must be positive")
    if learning_rate <= 0:
        raise ExperimentError("learning_rate must be positive")
    parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    if not parameters:
        raise ExperimentError("model has no trainable parameters")
    optimizer = torch_module.optim.AdamW(parameters, lr=learning_rate)
    model.train()
    for step in range(max_steps):
        batch = _tensor_batch(torch_module, rows[step % len(rows)], device)
        optimizer.zero_grad(set_to_none=True)
        output = model(**batch)
        loss = getattr(output, "loss", None)
        if loss is None:
            raise ExperimentError("model did not return a training loss")
        loss.backward()
        optimizer.step()
    return max_steps


def set_seed(seed: int, torch_module: Any) -> None:
    random.seed(seed)
    torch_module.manual_seed(seed)
    if getattr(torch_module, "cuda", None) is not None and torch_module.cuda.is_available():
        torch_module.cuda.manual_seed_all(seed)


def _report_digest(payload: Mapping[str, Any]) -> str:
    return sample_digest(payload)


def build_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic report with a self-checking digest."""

    report = deepcopy(dict(payload))
    report["schema_version"] = REPORT_SCHEMA_VERSION
    report.pop("report_digest", None)
    report["report_digest"] = _report_digest(report)
    return report


def write_report(path: str | Path, report: Mapping[str, Any]) -> Path:
    destination = Path(path)
    destination.write_text(canonical_json(report) + "\n", encoding="utf-8")
    return destination


def load_report(path: str | Path) -> dict[str, Any]:
    report = _read_json(Path(path))
    digest = str(report.pop("report_digest", ""))
    if not digest or digest != _report_digest(report):
        raise ExperimentError("experiment report digest is invalid")
    report["report_digest"] = digest
    return report


def _new_output_dir(path: str | Path) -> Path:
    destination = Path(path)
    if destination.exists():
        if any(destination.iterdir()):
            raise ExperimentError(f"experiment output already contains files: {destination}")
    else:
        destination.mkdir(parents=True)
    return destination


def _not_run_report(
    bundle: PreparedBundle,
    output_dir: Path,
    *,
    reason: str,
    model_name: str,
    revision: str | None,
    seed: int,
    authorization: Mapping[str, Any] | None,
) -> dict[str, Any]:
    report = build_report(
        {
            "status": "not_run",
            "not_run_reason": reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": {"name": model_name, "revision": revision},
            "seed": seed,
            "authorization": _safe_authorization(authorization),
            "lineage": _lineage(bundle),
            "train_count": len(bundle.train),
            "eval_count": len(bundle.eval),
            "limitations": [
                "No model update or online deployment was performed.",
                "Loss and generated text are engineering diagnostics, not scientific correctness.",
            ],
        }
    )
    write_report(output_dir / "report.json", report)
    return report


def run_experiment(
    prepared_dir: str | Path,
    output_dir: str | Path,
    *,
    model_name: str,
    revision: str | None,
    authorization: Mapping[str, Any] | None = None,
    seed: int = DEFAULT_SEED,
    max_steps: int = DEFAULT_MAX_STEPS,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
    device: str = "cpu",
    local_files_only: bool = True,
    loader: Callable[..., tuple[Any, Any, Any]] | None = None,
) -> dict[str, Any]:
    """Run one isolated experiment or write an explicit ``not_run`` report."""

    bundle = load_prepared(prepared_dir)
    destination = _new_output_dir(output_dir)
    effective_authorization = authorization or authorization_from_metadata(bundle)
    try:
        validate_authorization(bundle, effective_authorization)
    except ExperimentNotRun as exc:
        return _not_run_report(
            bundle,
            destination,
            reason=str(exc),
            model_name=model_name,
            revision=revision,
            seed=seed,
            authorization=effective_authorization,
        )
    if not revision:
        return _not_run_report(
            bundle,
            destination,
            reason="a fixed model revision is required",
            model_name=model_name,
            revision=revision,
            seed=seed,
            authorization=effective_authorization,
        )
    if max_steps <= 0:
        raise ExperimentError("max_steps must be positive")
    try:
        if loader is None:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            def default_loader(**kwargs: Any) -> tuple[Any, Any, Any]:
                tokenizer = AutoTokenizer.from_pretrained(
                    kwargs["model_name"],
                    revision=kwargs["revision"],
                    local_files_only=kwargs["local_files_only"],
                )
                model = AutoModelForCausalLM.from_pretrained(
                    kwargs["model_name"],
                    revision=kwargs["revision"],
                    local_files_only=kwargs["local_files_only"],
                )
                return torch, tokenizer, model

            loader = default_loader
        torch_module, tokenizer, model = loader(
            model_name=model_name,
            revision=revision,
            local_files_only=local_files_only,
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return _not_run_report(
            bundle,
            destination,
            reason=f"model environment unavailable ({type(exc).__name__})",
            model_name=model_name,
            revision=revision,
            seed=seed,
            authorization=effective_authorization,
        )

    set_seed(seed, torch_module)
    try:
        model.to(device)
    except (RuntimeError, ValueError) as exc:
        return _not_run_report(
            bundle,
            destination,
            reason=f"model device is unavailable ({type(exc).__name__})",
            model_name=model_name,
            revision=revision,
            seed=seed,
            authorization=effective_authorization,
        )
    _validate_model_context(model, bundle)
    before = evaluate_model(
        model,
        tokenizer,
        bundle.eval,
        torch_module=torch_module,
        device=device,
        max_new_tokens=max_new_tokens,
    )
    steps = train_limited(
        model,
        bundle.train,
        torch_module=torch_module,
        device=device,
        max_steps=max_steps,
        learning_rate=learning_rate,
    )
    after = evaluate_model(
        model,
        tokenizer,
        bundle.eval,
        torch_module=torch_module,
        device=device,
        max_new_tokens=max_new_tokens,
    )
    model_dir = destination / "model"
    model.save_pretrained(model_dir)
    tokenizer.save_pretrained(model_dir)

    reload_model = model.__class__.from_pretrained(model_dir, local_files_only=True)
    reload_tokenizer = tokenizer.__class__.from_pretrained(model_dir, local_files_only=True)
    reload_model.to(device)
    reloaded = evaluate_model(
        reload_model,
        reload_tokenizer,
        bundle.eval,
        torch_module=torch_module,
        device=device,
        max_new_tokens=max_new_tokens,
    )
    reload_matches = abs(
        float(reloaded["mean_target_loss"]) - float(after["mean_target_loss"])
    ) <= 1e-4
    if not reload_matches:
        raise ExperimentError("reloaded weights do not reproduce the trained evaluation")

    report = build_report(
        {
            "status": "completed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": {
                "name": model_name,
                "revision": revision,
                "model_artifact": "model",
            },
            "tokenizer": {
                "name": model_name,
                "revision": revision,
                "artifact": "model",
            },
            "seed": seed,
            "device": device,
            "training": {
                "max_steps": max_steps,
                "steps_completed": steps,
                "learning_rate": learning_rate,
            },
            "authorization": _safe_authorization(effective_authorization),
            "lineage": _lineage(bundle),
            "train_count": len(bundle.train),
            "eval_count": len(bundle.eval),
            "baseline": before,
            "after_training": after,
            "reload": {
                "status": "passed",
                "matches_after_training": reload_matches,
                "mean_target_loss": reloaded["mean_target_loss"],
            },
            "limitations": [
                "This is an offline engineering experiment, not online learning.",
                "Loss and generated text do not establish scientific correctness or research improvement.",
                "Source and review lineage must be inspected before any product decision.",
            ],
        }
    )
    write_report(destination / "report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path, help="directory written by prepare.py")
    parser.add_argument("output", type=Path, help="new experiment output directory")
    parser.add_argument("--model", required=True, dest="model_name")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--authorization-file", type=Path)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--learning-rate", type=float, default=DEFAULT_LEARNING_RATE)
    parser.add_argument("--max-new-tokens", type=int, default=DEFAULT_MAX_NEW_TOKENS)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--allow-download", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    authorization = _read_json(args.authorization_file) if args.authorization_file else None
    report = run_experiment(
        args.prepared,
        args.output,
        model_name=args.model_name,
        revision=args.revision,
        authorization=authorization,
        seed=args.seed,
        max_steps=args.max_steps,
        learning_rate=args.learning_rate,
        max_new_tokens=args.max_new_tokens,
        device=args.device,
        local_files_only=not args.allow_download,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = [
    "ExperimentError",
    "ExperimentNotRun",
    "PreparedBundle",
    "build_report",
    "evaluate_model",
    "load_prepared",
    "load_report",
    "run_experiment",
    "train_limited",
    "validate_authorization",
    "write_report",
]
