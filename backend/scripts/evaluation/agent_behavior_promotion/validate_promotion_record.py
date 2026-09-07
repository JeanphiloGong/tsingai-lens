#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)


RECORD_SCHEMA_VERSION = "agent_behavior_promotion.v1"
REPORT_SCHEMA_VERSION = "agent_behavior_promotion_evaluation.v1"
Fingerprint = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]


class PromotionRecordError(ValueError):
    """Raised when a promotion record cannot be evaluated safely."""


class RecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ArtifactRef(RecordModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def require_portable_relative_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("artifact path must use portable '/' separators")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value in {"", "."}:
            raise ValueError("artifact path must stay below the record directory")
        return value


class BehaviorCandidate(RecordModel):
    behavior_id: str = Field(min_length=1, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    behavior_version: str = Field(min_length=1)
    research_action: str = Field(min_length=20)
    scientific_invariant: str = Field(min_length=20)
    target_fast_path_stage: str = Field(min_length=1)
    excluded_shortcuts: list[str] = Field(min_length=1)

    @field_validator("excluded_shortcuts")
    @classmethod
    def require_unique_shortcuts(cls, values: list[str]) -> list[str]:
        return _require_unique_nonempty(values, "excluded_shortcuts")


class OriginTrajectory(RecordModel):
    recorded_at: datetime
    artifact: ArtifactRef
    paper_fingerprints: list[Fingerprint] = Field(min_length=1)
    tool_call_ids: list[str] = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    judgment_refs: list[str] = Field(min_length=1)

    @field_validator(
        "paper_fingerprints",
        "tool_call_ids",
        "source_refs",
        "evidence_ids",
        "judgment_refs",
    )
    @classmethod
    def require_unique_lineage(cls, values: list[str], info) -> list[str]:
        return _require_unique_nonempty(values, info.field_name)


class AcceptanceBounds(RecordModel):
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    minimum_expert_gold_papers: int = Field(ge=1)
    minimum_fresh_papers: int = Field(ge=1)
    minimum_recall: float = Field(ge=0.0, le=1.0)
    maximum_scientific_error_rate: float = Field(ge=0.0, le=1.0)
    maximum_technical_failure_rate: float = Field(ge=0.0, le=1.0)
    maximum_total_tokens_per_paper: int = Field(ge=0)
    maximum_model_calls_per_paper: float = Field(ge=0.0)

    @field_validator("approved_by")
    @classmethod
    def require_human_approver(cls, value: str) -> str:
        return _require_human_id(value)


class DatasetEvidence(RecordModel):
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    cohort: Literal["expert_gold", "fresh_papers"]
    sealed_at: datetime
    artifact: ArtifactRef

    @field_validator("sealed_at")
    @classmethod
    def require_aware_sealed_at(cls, value: datetime) -> datetime:
        _require_aware(value, "sealed_at")
        return value


class EvaluationMetrics(RecordModel):
    expected_relevant_items: int = Field(ge=1)
    recalled_relevant_items: int = Field(ge=0)
    evaluated_decisions: int = Field(ge=1)
    scientific_errors: int = Field(ge=0)
    technical_failures: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    unreported_model_calls: int = Field(ge=0)

    @model_validator(mode="after")
    def require_consistent_counts(self) -> EvaluationMetrics:
        if self.recalled_relevant_items > self.expected_relevant_items:
            raise ValueError(
                "recalled_relevant_items cannot exceed expected_relevant_items"
            )
        if self.scientific_errors > self.evaluated_decisions:
            raise ValueError("scientific_errors cannot exceed evaluated_decisions")
        if self.unreported_model_calls > self.model_calls:
            raise ValueError("unreported_model_calls cannot exceed model_calls")
        return self


class ExpertReview(RecordModel):
    reviewer_id: str = Field(min_length=1)
    reviewed_at: datetime
    decision: Literal["accepted", "needs_revision", "rejected"]
    artifact: ArtifactRef

    @field_validator("reviewer_id")
    @classmethod
    def require_human_reviewer(cls, value: str) -> str:
        return _require_human_id(value)


class EvaluationRun(RecordModel):
    run_id: str = Field(min_length=1)
    started_at: datetime
    completed_at: datetime
    implementation_revision: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    runtime_contract_fingerprint: Fingerprint
    model: str = Field(min_length=1)
    dataset: DatasetEvidence
    trajectory_artifact: ArtifactRef
    evaluation_report_artifact: ArtifactRef
    paper_fingerprints: list[Fingerprint] = Field(min_length=1)
    metrics: EvaluationMetrics
    expert_review: ExpertReview

    @field_validator("paper_fingerprints")
    @classmethod
    def require_unique_papers(cls, values: list[str]) -> list[str]:
        return _require_unique_nonempty(values, "paper_fingerprints")

    @model_validator(mode="after")
    def require_ordered_run_timestamps(self) -> EvaluationRun:
        _require_aware(self.started_at, "started_at")
        _require_aware(self.completed_at, "completed_at")
        _require_aware(self.expert_review.reviewed_at, "expert_review.reviewed_at")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.expert_review.reviewed_at < self.completed_at:
            raise ValueError("expert review cannot precede run completion")
        if self.metrics.technical_failures > len(self.paper_fingerprints):
            raise ValueError("technical_failures cannot exceed evaluated paper count")
        return self


class Evaluations(RecordModel):
    expert_gold: EvaluationRun
    fresh_papers: EvaluationRun


class PromotionRequest(RecordModel):
    requested_by: str = Field(min_length=1)
    requested_at: datetime
    target: Literal["fast_path"]

    @field_validator("requested_by")
    @classmethod
    def require_human_requester(cls, value: str) -> str:
        return _require_human_id(value)


class PromotionRecord(RecordModel):
    schema_version: Literal[RECORD_SCHEMA_VERSION]
    candidate: BehaviorCandidate
    origin_trajectory: OriginTrajectory
    acceptance_bounds: AcceptanceBounds
    evaluations: Evaluations
    promotion_request: PromotionRequest

    @model_validator(mode="after")
    def require_aware_record_timestamps(self) -> PromotionRecord:
        _require_aware(self.origin_trajectory.recorded_at, "recorded_at")
        _require_aware(self.acceptance_bounds.approved_at, "approved_at")
        _require_aware(self.promotion_request.requested_at, "requested_at")
        return self


def promotion_record_json_schema() -> dict[str, Any]:
    return PromotionRecord.model_json_schema()


def evaluate_promotion_record(record_path: str | Path) -> dict[str, Any]:
    path = Path(record_path).expanduser().resolve()
    record = _load_record(path)
    reasons: list[dict[str, str]] = []

    for field_path, artifact in _artifact_refs(record):
        reason = _verify_artifact(path.parent, field_path, artifact)
        if reason is not None:
            reasons.append(reason)

    gold = record.evaluations.expert_gold
    fresh = record.evaluations.fresh_papers
    bounds = record.acceptance_bounds

    if bounds.approved_at > min(gold.started_at, fresh.started_at):
        reasons.append(
            _reason(
                "acceptance_bounds_not_preregistered",
                "acceptance_bounds.approved_at",
                "Acceptance bounds must be approved before either evaluation starts.",
            )
        )

    if gold.dataset.sealed_at > record.origin_trajectory.recorded_at:
        reasons.append(
            _reason(
                "expert_gold_not_fixed_before_behavior",
                "evaluations.expert_gold.dataset.sealed_at",
                "Expert Gold must be frozen before the behavior's origin trajectory.",
            )
        )

    gold_papers = set(gold.paper_fingerprints)
    fresh_papers = set(fresh.paper_fingerprints)
    development_papers = set(record.origin_trajectory.paper_fingerprints)
    if gold_papers & fresh_papers:
        reasons.append(
            _reason(
                "fresh_papers_overlap_expert_gold",
                "evaluations.fresh_papers.paper_fingerprints",
                "Fresh-paper evaluation must not reuse an expert Gold paper.",
            )
        )
    if development_papers & fresh_papers:
        reasons.append(
            _reason(
                "fresh_papers_overlap_development_papers",
                "evaluations.fresh_papers.paper_fingerprints",
                "Fresh-paper evaluation must not reuse a behavior-development paper.",
            )
        )

    if (
        gold.implementation_revision,
        gold.runtime_contract_fingerprint,
        gold.model,
    ) != (
        fresh.implementation_revision,
        fresh.runtime_contract_fingerprint,
        fresh.model,
    ):
        reasons.append(
            _reason(
                "evaluation_runtime_mismatch",
                "evaluations",
                "Gold and fresh-paper evaluations must replay the same revision, "
                "runtime contract, and model.",
            )
        )

    latest_review = max(
        gold.expert_review.reviewed_at,
        fresh.expert_review.reviewed_at,
    )
    if record.promotion_request.requested_at < latest_review:
        reasons.append(
            _reason(
                "promotion_requested_before_human_review",
                "promotion_request.requested_at",
                "Promotion may be requested only after both human reviews complete.",
            )
        )

    cohort_results: dict[str, dict[str, Any]] = {}
    for name, run, minimum_papers in (
        ("expert_gold", gold, bounds.minimum_expert_gold_papers),
        ("fresh_papers", fresh, bounds.minimum_fresh_papers),
    ):
        cohort_reasons: list[dict[str, str]] = []
        if run.dataset.cohort != name:
            cohort_reasons.append(
                _reason(
                    "dataset_cohort_mismatch",
                    f"evaluations.{name}.dataset.cohort",
                    f"{name} cannot be relabelled from another evaluation cohort.",
                )
            )
        if run.dataset.sealed_at > run.started_at:
            cohort_reasons.append(
                _reason(
                    "dataset_not_sealed_before_evaluation",
                    f"evaluations.{name}.dataset.sealed_at",
                    f"{name} must be sealed before its evaluation starts.",
                )
            )
        if len(run.paper_fingerprints) < minimum_papers:
            cohort_reasons.append(
                _reason(
                    "paper_count_below_minimum",
                    f"evaluations.{name}.paper_fingerprints",
                    f"{name} has fewer than its pre-registered minimum papers.",
                )
            )
        if run.expert_review.decision != "accepted":
            cohort_reasons.append(
                _reason(
                    "human_review_not_accepted",
                    f"evaluations.{name}.expert_review.decision",
                    f"{name} has not been accepted by its human expert reviewer.",
                )
            )

        observed = _observed_metrics(run)
        checks = (
            (
                "recall_below_minimum",
                "recall",
                observed["recall"] < bounds.minimum_recall,
            ),
            (
                "scientific_error_rate_above_maximum",
                "scientific_error_rate",
                observed["scientific_error_rate"]
                > bounds.maximum_scientific_error_rate,
            ),
            (
                "technical_failure_rate_above_maximum",
                "technical_failure_rate",
                observed["technical_failure_rate"]
                > bounds.maximum_technical_failure_rate,
            ),
            (
                "total_tokens_per_paper_above_maximum",
                "total_tokens_per_paper",
                observed["total_tokens_per_paper"]
                > bounds.maximum_total_tokens_per_paper,
            ),
            (
                "model_calls_per_paper_above_maximum",
                "model_calls_per_paper",
                observed["model_calls_per_paper"]
                > bounds.maximum_model_calls_per_paper,
            ),
        )
        for code, metric, failed in checks:
            if failed:
                cohort_reasons.append(
                    _reason(
                        code,
                        f"evaluations.{name}.metrics.{metric}",
                        f"{name} {metric} does not meet its pre-registered boundary.",
                    )
                )
        if run.metrics.unreported_model_calls:
            cohort_reasons.append(
                _reason(
                    "cost_observation_incomplete",
                    f"evaluations.{name}.metrics.unreported_model_calls",
                    f"{name} has model calls without token usage.",
                )
            )
        reasons.extend(cohort_reasons)
        cohort_results[name] = {
            "status": "pass" if not cohort_reasons else "fail",
            "run_id": run.run_id,
            "implementation_revision": run.implementation_revision,
            "runtime_contract_fingerprint": run.runtime_contract_fingerprint,
            "model": run.model,
            "dataset": {
                "dataset_id": run.dataset.dataset_id,
                "dataset_version": run.dataset.dataset_version,
                "cohort": run.dataset.cohort,
                "sealed_at": run.dataset.sealed_at.isoformat(),
                "sha256": run.dataset.artifact.sha256,
            },
            "observed": observed,
            "human_review": run.expert_review.decision,
        }

    for name in cohort_results:
        cohort_prefix = f"evaluations.{name}"
        if any(
            reason["path"] == "evaluations" or reason["path"].startswith(cohort_prefix)
            for reason in reasons
        ):
            cohort_results[name]["status"] = "fail"

    verdict = "eligible_for_maintainer_review" if not reasons else "blocked"
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "record": {
            "path": str(path),
            "sha256": _sha256(path),
        },
        "behavior_id": record.candidate.behavior_id,
        "behavior_version": record.candidate.behavior_version,
        "target": record.promotion_request.target,
        "verdict": verdict,
        "promotion_applied": False,
        "acceptance_bounds": record.acceptance_bounds.model_dump(mode="json"),
        "cohorts": cohort_results,
        "blocking_reasons": reasons,
        "next_action": (
            "A maintainer may review the generalized behavior and its implementation; "
            "this gate does not modify Fast Path."
            if verdict == "eligible_for_maintainer_review"
            else "Resolve every blocking reason and rerun both locked evaluations."
        ),
    }


def _load_record(path: Path) -> PromotionRecord:
    if not path.is_file():
        raise PromotionRecordError(f"promotion record not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionRecordError(f"invalid promotion record: {exc}") from exc
    try:
        return PromotionRecord.model_validate(payload)
    except ValidationError as exc:
        raise PromotionRecordError(f"invalid promotion record: {exc}") from exc


def _artifact_refs(record: PromotionRecord) -> list[tuple[str, ArtifactRef]]:
    refs = [("origin_trajectory.artifact", record.origin_trajectory.artifact)]
    for name, run in (
        ("expert_gold", record.evaluations.expert_gold),
        ("fresh_papers", record.evaluations.fresh_papers),
    ):
        refs.extend(
            (
                (f"evaluations.{name}.dataset.artifact", run.dataset.artifact),
                (f"evaluations.{name}.trajectory_artifact", run.trajectory_artifact),
                (
                    f"evaluations.{name}.evaluation_report_artifact",
                    run.evaluation_report_artifact,
                ),
                (
                    f"evaluations.{name}.expert_review.artifact",
                    run.expert_review.artifact,
                ),
            )
        )
    return refs


def _verify_artifact(
    record_dir: Path,
    field_path: str,
    artifact: ArtifactRef,
) -> dict[str, str] | None:
    path = record_dir.joinpath(*PurePosixPath(artifact.path).parts)
    try:
        resolved_path = path.resolve(strict=True)
    except OSError:
        return _reason(
            "artifact_missing",
            field_path,
            f"Locked evaluation artifact does not exist: {artifact.path}",
        )
    resolved_record_dir = record_dir.resolve()
    if not resolved_path.is_relative_to(resolved_record_dir):
        return _reason(
            "artifact_outside_record_directory",
            field_path,
            f"Locked evaluation artifact escapes the record directory: {artifact.path}",
        )
    if not resolved_path.is_file():
        return _reason(
            "artifact_missing",
            field_path,
            f"Locked evaluation artifact is not a file: {artifact.path}",
        )
    if _sha256(resolved_path) != artifact.sha256:
        return _reason(
            "artifact_digest_mismatch",
            field_path,
            f"Locked evaluation artifact changed after it was recorded: {artifact.path}",
        )
    return None


def _observed_metrics(run: EvaluationRun) -> dict[str, int | float]:
    metrics = run.metrics
    paper_count = len(run.paper_fingerprints)
    return {
        "paper_count": paper_count,
        "recall": _ratio(
            metrics.recalled_relevant_items,
            metrics.expected_relevant_items,
        ),
        "scientific_error_rate": _ratio(
            metrics.scientific_errors,
            metrics.evaluated_decisions,
        ),
        "technical_failure_rate": _ratio(
            metrics.technical_failures,
            paper_count,
        ),
        "total_tokens_per_paper": _ratio(
            metrics.input_tokens + metrics.output_tokens,
            paper_count,
        ),
        "model_calls_per_paper": _ratio(metrics.model_calls, paper_count),
    }


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reason(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _require_unique_nonempty(values: list[str], field_name: str) -> list[str]:
    if any(not str(value).strip() for value in values):
        raise ValueError(f"{field_name} entries must not be empty")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} entries must be unique")
    return values


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")


def _require_human_id(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("ai-reviewer") or normalized.startswith("agent-"):
        raise ValueError("reviewer must be a human expert id")
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate whether a generalized Agent research behavior has the "
            "locked evidence required for Fast Path maintainer review."
        )
    )
    parser.add_argument("record_path", nargs="?", type=Path)
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    parser.add_argument(
        "--print-schema",
        action="store_true",
        help="Print the machine-readable promotion-record JSON Schema and exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.print_schema:
        print(json.dumps(promotion_record_json_schema(), ensure_ascii=False, indent=2))
        return
    if args.record_path is None:
        raise SystemExit("record_path is required unless --print-schema is used")
    try:
        report = evaluate_promotion_record(args.record_path)
    except PromotionRecordError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["verdict"] != "eligible_for_maintainer_review":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
