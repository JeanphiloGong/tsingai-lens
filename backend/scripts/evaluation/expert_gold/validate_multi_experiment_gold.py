#!/usr/bin/env python3
"""Validate the paper-local multi-experiment expert-gold sidecar.

The nine CSV tables remain the canonical fact tables.  This validator checks
the small JSON sidecar that gives those facts their experiment/relationship
boundaries and preserves the provenance needed to abstain safely.  It is
deliberately independent from ``validate_expert_gold.py`` so a malformed
sidecar cannot make an otherwise valid CSV bundle look valid.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_DIR = (
    DEFAULT_BACKEND_ROOT / "tests" / "fixtures" / "expert_gold" / "p004_multi_experiment"
)

MANIFEST_FILE = "manifest.json"
SOURCES_FILE = "sources.json"
EXPERIMENTS_FILE = "experiments.json"
RELATIONS_FILE = "relations.json"
DISPOSITION_FILE = "expected_disposition.json"
REVISIONS_FILE = "revisions.json"
REQUIRED_FILES = (
    MANIFEST_FILE,
    SOURCES_FILE,
    EXPERIMENTS_FILE,
    RELATIONS_FILE,
    DISPOSITION_FILE,
    REVISIONS_FILE,
)
SCHEMA_VERSION = "multi_experiment_gold.v1"
# The P004 fixture uses a version per sidecar.  Keep the generic version as a
# supported authoring form for small fixtures and tests, but reject arbitrary
# versions instead of silently accepting an incompatible contract.
EXPECTED_SCHEMA_VERSIONS: dict[str, set[str]] = {
    MANIFEST_FILE: {SCHEMA_VERSION, "paper_experiment_gold.v1"},
    SOURCES_FILE: {SCHEMA_VERSION, "paper_experiment_sources.v1"},
    EXPERIMENTS_FILE: {SCHEMA_VERSION, "paper_experiment_archive.v1"},
    RELATIONS_FILE: {SCHEMA_VERSION, "paper_experiment_relations.v1"},
    DISPOSITION_FILE: {
        SCHEMA_VERSION,
        "paper_experiment_disposition.v1",
        "paper_experiment_expected_disposition.v1",
    },
    REVISIONS_FILE: {
        SCHEMA_VERSION,
        "paper_experiment_revisions.v1",
        "paper_experiment_revision.v1",
    },
}
_HASH_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    file: str
    path: str | None
    message: str

    @property
    def table(self) -> str:
        """Compatibility name used by the CSV validator's report shape."""

        return self.file

    @property
    def row(self) -> None:
        return None


@dataclass
class ValidationReport:
    input_dir: str
    file_counts: dict[str, int] = field(default_factory=dict)
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def table_counts(self) -> dict[str, int]:
        """Compatibility alias for callers that consume expert-gold reports."""

        return self.file_counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_dir": self.input_dir,
            "schema_version": SCHEMA_VERSION,
            "ok": self.ok,
            "file_counts": self.file_counts,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [asdict(issue) for issue in self.errors],
            "warnings": [asdict(issue) for issue in self.warnings],
        }


@dataclass(frozen=True)
class _Record:
    kind: str
    identifier: str
    paper_id: str
    value: Mapping[str, Any]
    file: str
    path: str


@dataclass
class _Context:
    manifest: Mapping[str, Any]
    sources: dict[str, _Record] = field(default_factory=dict)
    experiments: dict[str, _Record] = field(default_factory=dict)
    series: dict[str, _Record] = field(default_factory=dict)
    samples: dict[str, _Record] = field(default_factory=dict)
    conditions: dict[str, _Record] = field(default_factory=dict)
    outcomes: dict[str, _Record] = field(default_factory=dict)
    factors: dict[str, _Record] = field(default_factory=dict)
    results: dict[str, _Record] = field(default_factory=dict)
    observations: dict[str, _Record] = field(default_factory=dict)
    comparisons: dict[str, _Record] = field(default_factory=dict)
    relations: dict[str, _Record] = field(default_factory=dict)
    revisions: dict[str, _Record] = field(default_factory=dict)
    paper_ids: set[str] = field(default_factory=set)
    default_paper_id: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a multi-experiment expert-gold JSON sidecar."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Folder containing manifest.json and the five sidecar JSON files.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = validate_multi_experiment_gold(args.input)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_report(report))
    raise SystemExit(0 if report.ok else 1)


def validate_multi_experiment_gold(
    input_dir: str | Path = DEFAULT_INPUT_DIR,
) -> ValidationReport:
    """Validate one sidecar directory and return a structured report.

    Validation is intentionally accumulated rather than fail-fast: an expert
    annotator should see all broken links in one run.  JSON syntax and missing
    required files are reported first; semantic checks run with whatever data
    could be loaded safely.
    """

    root = Path(input_dir).expanduser().resolve()
    report = ValidationReport(input_dir=str(root))
    if not root.is_dir():
        _error(report, "input", None, f"input directory not found: {root}")
        return report

    documents: dict[str, Any] = {}
    for filename in REQUIRED_FILES:
        document = _read_json(root / filename, filename, report)
        if document is not _MISSING:
            documents[filename] = document
            report.file_counts[filename] = _record_count(document)
    if MANIFEST_FILE not in documents:
        return report

    manifest = documents[MANIFEST_FILE]
    context = _build_context(manifest, documents, report)
    _validate_schema_versions(documents, report)
    _validate_manifest(manifest, context, report)
    _validate_document_paper_ids(documents, context, report)
    _validate_entity_paper_ids(context, report)
    _validate_experiments(documents.get(EXPERIMENTS_FILE), context, report)
    _validate_relations(documents.get(RELATIONS_FILE), context, report)
    _validate_disposition(documents.get(DISPOSITION_FILE), context, report)
    _validate_revisions(documents.get(REVISIONS_FILE), context, report)
    return report


# Short alias useful to callers that use the other evaluator's API.
validate = validate_multi_experiment_gold


def render_report(report: ValidationReport) -> str:
    lines = [
        "# Multi-Experiment Expert Gold Validation",
        "",
        f"Input: {report.input_dir}",
        f"Status: {'ok' if report.ok else 'failed'}",
        "",
        "## Files",
    ]
    for filename in REQUIRED_FILES:
        lines.append(f"- {filename}: {report.file_counts.get(filename, 0)}")
    lines.extend(
        [
            "",
            f"Errors: {len(report.errors)}",
            f"Warnings: {len(report.warnings)}",
        ]
    )
    if report.errors:
        lines.extend(["", "## Errors", *_render_issues(report.errors)])
    if report.warnings:
        lines.extend(["", "## Warnings", *_render_issues(report.warnings)])
    return "\n".join(lines)


def _render_issues(issues: Iterable[ValidationIssue]) -> list[str]:
    return [
        f"- {issue.file}{(':' + issue.path) if issue.path else ''}: {issue.message}"
        for issue in issues
    ]


_MISSING = object()


def _read_json(path: Path, filename: str, report: ValidationReport) -> Any:
    if not path.is_file():
        _error(report, filename, None, "required JSON file is missing")
        return _MISSING
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        _error(report, filename, None, f"invalid JSON: {exc}")
        return _MISSING


def _record_count(document: Any) -> int:
    if isinstance(document, list):
        return len(document)
    if isinstance(document, Mapping):
        for key in (
            "papers",
            "sources",
            "experiments",
            "relations",
            "dispositions",
            "expected_disposition",
            "revisions",
        ):
            value = document.get(key)
            if isinstance(value, list):
                return len(value)
        return 1
    return 0


def _build_context(
    manifest: Any,
    documents: Mapping[str, Any],
    report: ValidationReport,
) -> _Context:
    context = _Context(manifest=manifest if isinstance(manifest, Mapping) else {})
    context.paper_ids.update(_manifest_paper_ids(manifest, report))
    if len(context.paper_ids) == 1:
        context.default_paper_id = next(iter(context.paper_ids))

    source_records = _as_records(
        documents.get(SOURCES_FILE), "sources", SOURCES_FILE, report
    )
    for index, value in enumerate(source_records):
        _register(
            context.sources,
            _make_record("source", value, context, SOURCES_FILE, f"sources[{index}]", report),
            report,
        )

    experiment_document = documents.get(EXPERIMENTS_FILE)
    experiment_records = _as_records(
        experiment_document, "experiments", EXPERIMENTS_FILE, report
    )
    # Definitions may be kept at the file root or inside each experiment.
    for index, value in enumerate(experiment_records):
        if not isinstance(value, Mapping):
            _error(report, EXPERIMENTS_FILE, f"experiments[{index}]", "record must be an object")
            continue
        path = f"experiments[{index}]"
        paper_id = _paper_id(value) or context.default_paper_id
        experiment_id = _id(value, "experiment_id", "id", "series_id")
        if not experiment_id:
            _error(report, EXPERIMENTS_FILE, path, "experiment requires experiment_id (or series_id)")
        else:
            record = _Record("experiment", experiment_id, paper_id, value, EXPERIMENTS_FILE, path)
            _register(context.experiments, record, report)
            # A series is the paper-local experimental boundary.  If no
            # separate series id exists, the experiment id is its series id.
            series_id = _id(value, "series_id", "experiment_id", "id")
            if series_id:
                _register(
                    context.series,
                    _Record("series", series_id, paper_id, value, EXPERIMENTS_FILE, path),
                    report,
                )
        _collect_nested_definitions(context, value, path, paper_id, report)

    if isinstance(experiment_document, Mapping):
        _collect_root_definitions(context, experiment_document, report)

    relation_records = _as_records(
        documents.get(RELATIONS_FILE), "relations", RELATIONS_FILE, report
    )
    for index, value in enumerate(relation_records):
        if not isinstance(value, Mapping):
            _error(report, RELATIONS_FILE, f"relations[{index}]", "record must be an object")
            continue
        relation_id = _id(value, "relationship_id", "relation_id", "id")
        if not relation_id:
            _error(report, RELATIONS_FILE, f"relations[{index}]", "relation requires relationship_id")
            continue
        _register(
            context.relations,
            _Record(
                "relation",
                relation_id,
                _paper_id(value) or context.default_paper_id,
                value,
                RELATIONS_FILE,
                f"relations[{index}]",
            ),
            report,
        )

    revision_records = _as_records(
        documents.get(REVISIONS_FILE), "revisions", REVISIONS_FILE, report
    )
    for index, value in enumerate(revision_records):
        if not isinstance(value, Mapping):
            _error(report, REVISIONS_FILE, f"revisions[{index}]", "record must be an object")
            continue
        revision_id = _id(value, "revision_id", "id")
        if not revision_id:
            _error(report, REVISIONS_FILE, f"revisions[{index}]", "revision requires revision_id")
            continue
        _register(
            context.revisions,
            _Record(
                "revision",
                revision_id,
                _paper_id(value) or context.default_paper_id,
                value,
                REVISIONS_FILE,
                f"revisions[{index}]",
            ),
            report,
        )
    return context


def _validate_schema_versions(documents: Mapping[str, Any], report: ValidationReport) -> None:
    manifest = documents.get(MANIFEST_FILE)
    if not isinstance(manifest, Mapping):
        _error(report, MANIFEST_FILE, None, "manifest must be a JSON object")
    elif manifest.get("schema_version") not in EXPECTED_SCHEMA_VERSIONS[MANIFEST_FILE]:
        _error(
            report,
            MANIFEST_FILE,
            "schema_version",
            "schema_version is not supported",
        )
    for filename, document in documents.items():
        if filename == MANIFEST_FILE or not isinstance(document, Mapping):
            continue
        version = document.get("schema_version")
        if version is not None and version not in EXPECTED_SCHEMA_VERSIONS[filename]:
            _error(report, filename, "schema_version", "schema_version is not supported")


def _validate_manifest(manifest: Any, context: _Context, report: ValidationReport) -> None:
    if not isinstance(manifest, Mapping):
        return
    if not context.paper_ids:
        _error(report, MANIFEST_FILE, "papers", "manifest must define at least one paper_id")
    for index, paper_id in enumerate(sorted(context.paper_ids)):
        if not _nonempty_string(paper_id):
            _error(report, MANIFEST_FILE, f"papers[{index}]", "paper_id must be non-empty")
    declared_hashes = _manifest_hashes(manifest)
    for paper_id, value in declared_hashes.items():
        if not _HASH_RE.fullmatch(value):
            _error(report, MANIFEST_FILE, f"papers[{paper_id}].sha256", "must be a SHA-256 hash")


def _validate_document_paper_ids(
    documents: Mapping[str, Any], context: _Context, report: ValidationReport
) -> None:
    for filename, document in documents.items():
        if filename == MANIFEST_FILE or not isinstance(document, Mapping):
            continue
        paper_id = _paper_id(document)
        if paper_id and paper_id not in context.paper_ids:
            _error(
                report,
                filename,
                "paper_id",
                f"unknown paper_id: {paper_id}",
            )


def _validate_entity_paper_ids(context: _Context, report: ValidationReport) -> None:
    indexes = (
        context.sources,
        context.experiments,
        context.series,
        context.samples,
        context.conditions,
        context.outcomes,
        context.factors,
        context.results,
        context.observations,
        context.comparisons,
    )
    for index in indexes:
        for record in index.values():
            if not record.paper_id:
                _error(report, record.file, record.path, f"{record.kind} paper_id is required")
            elif record.paper_id not in context.paper_ids:
                _error(report, record.file, record.path, f"unknown paper_id: {record.paper_id}")


def _validate_experiments(
    document: Any,
    context: _Context,
    report: ValidationReport,
) -> None:
    if document is None:
        return
    records = _as_records(document, "experiments", EXPERIMENTS_FILE, report)
    for index, value in enumerate(records):
        if not isinstance(value, Mapping):
            continue
        path = f"experiments[{index}]"
        paper_id = _paper_id(value) or context.default_paper_id
        _check_paper(report, EXPERIMENTS_FILE, path, paper_id, context.paper_ids)
        experiment_id = _id(value, "experiment_id", "id", "series_id")
        if experiment_id and experiment_id in context.experiments:
            if _status(value):
                _validate_status_constraints(value, EXPERIMENTS_FILE, path, report)
            for source_id in _string_refs(value.get("evidence_ids")):
                _validate_entity_ref(
                    source_id,
                    context.sources,
                    paper_id,
                    "source",
                    EXPERIMENTS_FILE,
                    path,
                    report,
                )
            _validate_ref_list(
                value,
                ("sample_ids", "samples"),
                context.samples,
                paper_id,
                "sample",
                EXPERIMENTS_FILE,
                path,
                report,
            )
            _validate_ref_list(
                value,
                ("condition_ids", "conditions"),
                context.conditions,
                paper_id,
                "condition",
                EXPERIMENTS_FILE,
                path,
                report,
            )
            _validate_ref_list(
                value,
                ("outcome_ids", "outcomes"),
                context.outcomes,
                paper_id,
                "outcome",
                EXPERIMENTS_FILE,
                path,
                report,
            )
            _validate_ref_list(
                value,
                ("factor_ids", "factors", "varied_factor_ids", "varied_factors"),
                context.factors,
                paper_id,
                "factor",
                EXPERIMENTS_FILE,
                path,
                report,
                required=False,
            )

            _validate_ref_list(
                value,
                ("result_ids", "results", "measurement_ids", "measurements"),
                context.results,
                paper_id,
                "result",
                EXPERIMENTS_FILE,
                path,
                report,
                required=False,
            )
            _validate_ref_list(
                value,
                ("observation_ids", "observations"),
                context.observations,
                paper_id,
                "observation",
                EXPERIMENTS_FILE,
                path,
                report,
                required=False,
            )

    if isinstance(document, Mapping):
        _validate_archive_definitions(document, context, report)


def _validate_relations(
    document: Any,
    context: _Context,
    report: ValidationReport,
) -> None:
    if document is None:
        return
    records = _as_records(document, "relations", RELATIONS_FILE, report)
    for index, relation in enumerate(records):
        if not isinstance(relation, Mapping):
            continue
        path = f"relations[{index}]"
        relation_id = _id(relation, "relationship_id", "relation_id", "id")
        paper_id = _paper_id(relation) or context.default_paper_id
        _check_paper(report, RELATIONS_FILE, path, paper_id, context.paper_ids)
        if not relation_id:
            continue

        if not _status(relation):
            _error(report, RELATIONS_FILE, f"{path}.status", "relation status is required")

        series_id = _id(relation, "series_id", "experiment_id", "series", "experiment")
        if not series_id:
            _error(report, RELATIONS_FILE, path, "relation requires series_id")
        else:
            _validate_entity_ref(
                series_id,
                context.series,
                paper_id,
                "series",
                RELATIONS_FILE,
                path,
                report,
            )
            series = context.series.get(series_id)
            if series is not None:
                _validate_relation_membership(relation, series.value, path, report)

        factor_keys = (
            "factor_ids",
            "factor_refs",
            "factors",
            "varied_factor_ids",
            "varied_factors",
        )
        if any(key in relation for key in factor_keys):
            _validate_relation_refs(
                relation,
                factor_keys,
                context.factors,
                paper_id,
                "factor",
                RELATIONS_FILE,
                path,
                report,
            )
        else:
            _validate_named_factors(relation, RELATIONS_FILE, path, report)
        _validate_relation_refs(
            relation,
            ("result_ids", "result_refs", "results", "outcome_ids", "outcomes"),
            context.results,
            paper_id,
            "result",
            RELATIONS_FILE,
            path,
            report,
        )
        if _status(relation) == "technical_failure" and _string_refs(
            relation.get("result_ids")
        ):
            _error(
                report,
                RELATIONS_FILE,
                f"{path}.result_ids",
                "technical failure cannot produce scientific results",
            )
        _validate_relation_refs(
            relation,
            ("outcome_ids", "outcomes"),
            context.outcomes,
            paper_id,
            "outcome",
            RELATIONS_FILE,
            path,
            report,
            required=False,
        )
        _validate_relation_refs(
            relation,
            ("baseline_sample_ids", "sample_ids"),
            context.samples,
            paper_id,
            "sample",
            RELATIONS_FILE,
            path,
            report,
            required=False,
        )
        _validate_relation_refs(
            relation,
            ("target_sample_ids",),
            context.samples,
            paper_id,
            "sample",
            RELATIONS_FILE,
            path,
            report,
            required=False,
        )
        _validate_relation_refs(
            relation,
            ("observation_ids", "observations"),
            context.observations,
            paper_id,
            "observation",
            RELATIONS_FILE,
            path,
            report,
            required=False,
        )

        source_refs = relation.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            _error(report, RELATIONS_FILE, f"{path}.source_refs", "must be a non-empty list")
        else:
            for source_index, source_ref in enumerate(source_refs):
                source_path = f"{path}.source_refs[{source_index}]"
                if not isinstance(source_ref, Mapping):
                    _error(report, RELATIONS_FILE, source_path, "must be an object with source_id and supports")
                    continue
                source_id = _id(source_ref, "source_id", "evidence_id", "id")
                if not source_id:
                    _error(report, RELATIONS_FILE, source_path, "source_id is required")
                else:
                    _validate_entity_ref(
                        source_id,
                        context.sources,
                        paper_id,
                        "source",
                        RELATIONS_FILE,
                        source_path,
                        report,
                    )
                supports = source_ref.get("supports")
                if not _nonempty_sequence(supports) or any(
                    not _nonempty_string(item) for item in supports
                ):
                    _error(
                        report,
                        RELATIONS_FILE,
                        f"{source_path}.supports",
                        "supports must be non-empty",
                    )

        if _status(relation) == "conflict":
            source_ids = [
                _id(item, "source_id", "evidence_id", "id")
                for item in source_refs
                if isinstance(item, Mapping)
            ] if isinstance(source_refs, list) else []
            if len(set(source_ids)) < 2:
                _error(
                    report,
                    RELATIONS_FILE,
                    f"{path}.source_refs",
                    "conflict status requires at least two distinct source references",
                )

        _validate_status_constraints(relation, RELATIONS_FILE, path, report)
        _validate_attribution(relation, RELATIONS_FILE, path, report)


def _validate_disposition(
    document: Any,
    context: _Context,
    report: ValidationReport,
) -> None:
    if document is None:
        return
    if not isinstance(document, Mapping):
        _error(report, DISPOSITION_FILE, None, "must be a JSON object")
        return

    paper_records = _records_from_keys(
        document,
        ("papers", "dispositions", "expected_disposition", "paper_dispositions"),
    )
    seen_papers: set[str] = set()
    for index, item in enumerate(paper_records):
        if not isinstance(item, Mapping):
            _error(report, DISPOSITION_FILE, f"papers[{index}]", "record must be an object")
            continue
        path = f"papers[{index}]"
        paper_id = _paper_id(item) or context.default_paper_id
        _check_paper(report, DISPOSITION_FILE, path, paper_id, context.paper_ids)
        if paper_id in seen_papers:
            _error(report, DISPOSITION_FILE, path, f"duplicate paper disposition: {paper_id}")
        seen_papers.add(paper_id)
        disposition = _value(item, "evidence_disposition", "disposition", "status")
        coverage = item.get("coverage")
        if not isinstance(coverage, Mapping):
            _error(report, DISPOSITION_FILE, f"{path}.coverage", "must be an object")
        else:
            _validate_coverage(coverage, disposition, DISPOSITION_FILE, path, report)
        if disposition not in _ALLOWED_DISPOSITIONS:
            _error(report, DISPOSITION_FILE, f"{path}.disposition", f"unknown disposition: {disposition!r}")

    if paper_records:
        for paper_id in sorted(context.paper_ids - seen_papers):
            _error(
                report,
                DISPOSITION_FILE,
                "papers",
                f"missing disposition for paper_id: {paper_id}",
            )

    # A compact single-paper form is also accepted when the producer places
    # paper_id/evidence_disposition directly at the document root.
    if not paper_records and _paper_id(document):
        _validate_disposition({"papers": [document]}, context, report)

    guard = document.get("technical_failure_guard")
    if guard is not None:
        if not isinstance(guard, Mapping):
            _error(report, DISPOSITION_FILE, "technical_failure_guard", "must be an object")
        else:
            expected_failed = guard.get("expected_failed_source_count_when_injected")
            if not isinstance(expected_failed, int) or expected_failed < 1:
                _error(
                    report,
                    DISPOSITION_FILE,
                    "technical_failure_guard.expected_failed_source_count_when_injected",
                    "must be a positive integer",
                )
            expected_disposition = guard.get("expected_disposition_when_injected")
            if expected_disposition not in {"extraction_failed", "technical_failure"}:
                _error(
                    report,
                    DISPOSITION_FILE,
                    "technical_failure_guard.expected_disposition_when_injected",
                    "must be extraction_failed or technical_failure",
                )
            if not _nonempty_string(guard.get("rule")):
                _error(report, DISPOSITION_FILE, "technical_failure_guard.rule", "must be non-empty")

    relation_records = _records_from_keys(
        document,
        ("relationships", "relations", "expected_relationships", "abstentions"),
    )
    _validate_expected_findings(document, context, report)
    seen_abstentions: set[str] = set()
    for index, item in enumerate(relation_records):
        if not isinstance(item, Mapping):
            _error(report, DISPOSITION_FILE, f"relationships[{index}]", "record must be an object")
            continue
        path = f"relationships[{index}]"
        relation_id = _id(item, "relationship_id", "relation_id", "id")
        if not relation_id or relation_id not in context.relations:
            _error(report, DISPOSITION_FILE, path, f"unknown relationship_id: {relation_id!r}")
        abstention_id = _id(item, "abstention_id")
        if abstention_id:
            if abstention_id in seen_abstentions:
                _error(report, DISPOSITION_FILE, path, f"duplicate abstention_id: {abstention_id}")
            seen_abstentions.add(abstention_id)
        decision = _value(item, "decision", "expected_decision")
        if decision == "abstain":
            reason = _value(item, "reason", "abstention_reason")
            if not _nonempty_string(reason):
                _error(report, DISPOSITION_FILE, f"{path}.reason", "abstention requires a reason")
            if item.get("finding_ids") not in (None, [], ()):
                _error(report, DISPOSITION_FILE, f"{path}.finding_ids", "abstention cannot emit findings")


def _validate_expected_findings(
    document: Mapping[str, Any], context: _Context, report: ValidationReport
) -> None:
    findings = document.get("expected_findings")
    if findings is None:
        return
    if not isinstance(findings, list):
        _error(report, DISPOSITION_FILE, "expected_findings", "must be a list")
        return
    seen: set[str] = set()
    for index, finding in enumerate(findings):
        path = f"expected_findings[{index}]"
        if not isinstance(finding, Mapping):
            _error(report, DISPOSITION_FILE, path, "record must be an object")
            continue
        finding_id = _id(finding, "finding_id", "id")
        if not finding_id:
            _error(report, DISPOSITION_FILE, path, "finding_id is required")
        elif finding_id in seen:
            _error(report, DISPOSITION_FILE, path, f"duplicate finding_id: {finding_id}")
        else:
            seen.add(finding_id)
        for key, index_map, kind in (
            ("relation_ids", context.relations, "relationship"),
            ("source_ids", context.sources, "source"),
        ):
            for identifier in _string_refs(finding.get(key)):
                _validate_entity_ref(
                    identifier,
                    index_map,
                    context.default_paper_id,
                    kind,
                    DISPOSITION_FILE,
                    path,
                    report,
                )
        decision = _value(finding, "decision", "expected_decision")
        if decision not in {
            "conditional_finding",
            "association_only",
            "abstain",
            "resolved",
            "partial",
        }:
            _error(report, DISPOSITION_FILE, f"{path}.decision", f"unknown finding decision: {decision!r}")


def _validate_coverage(
    coverage: Mapping[str, Any],
    disposition: Any,
    filename: str,
    path: str,
    report: ValidationReport,
) -> None:
    routed = _count(coverage, "routed_source_count", "routed", "routed_sources")
    extracted = _count(coverage, "extracted_source_count", "extracted", "extracted_sources")
    comparable = _count(
        coverage,
        "comparable_evidence_count",
        "comparable",
        "comparable_evidence",
    )
    failed = _count(coverage, "failed_source_count", "failed", "failed_sources")
    uninspected = _count(
        coverage,
        "uninspected_source_count",
        "uninspected",
        "uninspected_sources",
    )
    values = {
        "routed_source_count": routed,
        "extracted_source_count": extracted,
        "comparable_evidence_count": comparable,
        "failed_source_count": failed,
        "uninspected_source_count": uninspected,
    }
    for name, value in values.items():
        if value is None:
            _error(report, filename, f"{path}.coverage.{name}", "must be a non-negative integer")
        elif value < 0:
            _error(report, filename, f"{path}.coverage.{name}", "must be non-negative")
    if any(value is None or value < 0 for value in values.values()):
        return
    if extracted > routed:
        _error(report, filename, f"{path}.coverage", "extracted sources cannot exceed routed sources")
    if comparable > extracted:
        _error(report, filename, f"{path}.coverage", "comparable evidence cannot exceed extracted sources")
    if failed > routed:
        _error(report, filename, f"{path}.coverage", "failed sources cannot exceed routed sources")
    if uninspected > routed:
        _error(report, filename, f"{path}.coverage", "uninspected sources cannot exceed routed sources")
    if extracted + failed + uninspected > routed:
        _error(report, filename, f"{path}.coverage", "coverage categories exceed routed sources")

    for ids_key, expected_count, label in (
        ("inspected_source_ids", extracted, "extracted"),
        ("failed_source_ids", failed, "failed"),
        ("uninspected_source_ids", uninspected, "uninspected"),
    ):
        ids = coverage.get(ids_key)
        if ids is None:
            continue
        if not isinstance(ids, list) or any(not _nonempty_string(item) for item in ids):
            _error(report, filename, f"{path}.coverage.{ids_key}", "must be a list of non-empty IDs")
        elif len(set(ids)) != len(ids):
            _error(report, filename, f"{path}.coverage.{ids_key}", "IDs must be unique")
        elif len(ids) != expected_count:
            _error(
                report,
                filename,
                f"{path}.coverage.{ids_key}",
                f"{label} source ID count must equal {label}_source_count",
            )

    if disposition in {"coverage_incomplete", "incomplete"} and uninspected == 0:
        _error(report, filename, f"{path}.coverage", "coverage_incomplete requires uninspected sources")
    if disposition in {"extraction_failed", "technical_failure"} and failed == 0:
        _error(report, filename, f"{path}.coverage", "extraction_failed requires failed sources")
    if disposition in {"extraction_failed", "technical_failure"}:
        technical_failures = coverage.get("technical_failures")
        if not _nonempty_sequence(technical_failures):
            _error(
                report,
                filename,
                f"{path}.coverage.technical_failures",
                "extraction_failed requires technical failure details",
            )
    if disposition in {"comparable_evidence", "resolved"} and comparable == 0:
        _error(report, filename, f"{path}.coverage", "comparable_evidence requires comparable evidence")
    if disposition in {"no_comparable_evidence", "not_comparable"} and comparable != 0:
        _error(report, filename, f"{path}.coverage", "no_comparable_evidence cannot have comparable evidence")


def _validate_revisions(
    document: Any,
    context: _Context,
    report: ValidationReport,
) -> None:
    if document is None:
        return
    records = _as_records(document, "revisions", REVISIONS_FILE, report)
    for index, revision in enumerate(records):
        if not isinstance(revision, Mapping):
            continue
        path = f"revisions[{index}]"
        paper_id = _paper_id(revision) or context.default_paper_id
        _check_paper(report, REVISIONS_FILE, path, paper_id, context.paper_ids)
        entity_type = _value(revision, "entity_type", "scope_type", "kind")
        entity_id = _id(revision, "entity_id", "scope_id", "target_id")
        if not _nonempty_string(entity_type) or not _nonempty_string(entity_id):
            _error(report, REVISIONS_FILE, path, "revision requires entity_type and entity_id")
        supersedes = _value(revision, "supersedes_revision_id", "supersedes")
        if supersedes in (None, ""):
            current_sources = _provenance_source_ids(revision)
            if not current_sources:
                _error(
                    report,
                    REVISIONS_FILE,
                    f"{path}.source_provenance",
                    "revision must preserve source provenance",
                )
            for source_id in current_sources:
                if source_id not in context.sources:
                    _error(
                        report,
                        REVISIONS_FILE,
                        f"{path}.source_provenance",
                        f"unknown source_id: {source_id}",
                    )
            _validate_provenance_hashes(revision, path, report)
            _check_revision_manifest_hashes(revision, paper_id, context, path, report)
            continue
        if isinstance(supersedes, Mapping):
            supersedes = _id(supersedes, "revision_id", "id")
        if supersedes not in context.revisions:
            _error(report, REVISIONS_FILE, f"{path}.supersedes", f"unknown revision: {supersedes!r}")
            continue
        previous = context.revisions[supersedes]
        if (
            _value(previous.value, "entity_type", "scope_type", "kind") != entity_type
            or _id(previous.value, "entity_id", "scope_id", "target_id") != entity_id
            or previous.paper_id != paper_id
        ):
            _error(report, REVISIONS_FILE, f"{path}.supersedes", "superseded revision has a different scope")
        current_sources = _provenance_source_ids(revision)
        previous_sources = _provenance_source_ids(previous.value)
        if not current_sources:
            _error(report, REVISIONS_FILE, f"{path}.source_provenance", "revision must preserve source provenance")
        if previous_sources and current_sources and current_sources != previous_sources:
            _error(report, REVISIONS_FILE, f"{path}.source_provenance", "source provenance changed across revision")
        for source_id in current_sources:
            if source_id not in context.sources:
                _error(report, REVISIONS_FILE, f"{path}.source_provenance", f"unknown source_id: {source_id}")
        _validate_provenance_hashes(revision, path, report)
        _check_revision_manifest_hashes(revision, paper_id, context, path, report)

    _validate_revision_cycles(context, report)


def _validate_revision_cycles(context: _Context, report: ValidationReport) -> None:
    graph: dict[str, str] = {}
    for revision_id, record in context.revisions.items():
        target = _value(record.value, "supersedes_revision_id", "supersedes")
        if isinstance(target, Mapping):
            target = _id(target, "revision_id", "id")
        if isinstance(target, str) and target in context.revisions:
            graph[revision_id] = target
    for start in graph:
        seen: set[str] = set()
        current = start
        while current in graph:
            if current in seen:
                _error(report, REVISIONS_FILE, start, "revision supersedes chain contains a cycle")
                break
            seen.add(current)
            current = graph[current]


def _validate_status_constraints(
    record: Mapping[str, Any], filename: str, path: str, report: ValidationReport
) -> None:
    status = _status(record)
    reason = _value(record, "reason", "status_reason", "abstention_reason")
    unknown_fields = record.get("unknown_fields")
    conflict_group = _value(record, "conflict_group", "conflict_group_id")
    if status == "unknown":
        if not _nonempty_string(reason):
            _error(report, filename, f"{path}.reason", "unknown status requires a reason")
        if not _nonempty_sequence(unknown_fields):
            _error(report, filename, f"{path}.unknown_fields", "unknown status requires unknown_fields")
    elif status == "conflict":
        if not _nonempty_string(reason):
            _error(report, filename, f"{path}.reason", "conflict status requires a reason")
        if not _nonempty_string(conflict_group):
            _error(report, filename, f"{path}.conflict_group", "conflict status requires conflict_group")
    elif status in {"not_comparable", "non_comparable", "abstain"}:
        if not _nonempty_string(reason) and not _nonempty_sequence(unknown_fields):
            _error(
                report,
                filename,
                f"{path}.reason",
                "non-comparable status requires a reason or unknown_fields",
            )
    elif status == "technical_failure":
        if not _nonempty_string(reason):
            _error(report, filename, f"{path}.reason", "technical_failure requires a reason")
        if not record.get("technical_failure") and not record.get("failure_detail"):
            _error(report, filename, path, "technical_failure requires failure detail")
    elif status not in {"", "resolved", "partial", "pending", "planned"}:
        _error(report, filename, f"{path}.status", f"unknown status: {status!r}")


def _validate_attribution(
    record: Mapping[str, Any], filename: str, path: str, report: ValidationReport
) -> None:
    scope = _value(record, "attribution_scope", "attribution")
    allowed_scopes = {
        "",
        "association_only",
        "descriptive_only",
        "partial",
        "not_comparable",
        "joint_effect",
        "isolated_effect",
        "causal",
    }
    if scope not in allowed_scopes:
        _error(report, filename, f"{path}.attribution_scope", f"unknown attribution scope: {scope!r}")
        return
    # P004 records use factor_names because treatment arms (furnace HT and
    # HIP) are levels of one intervention dimension rather than separate
    # causal interventions.  Validate presence here; ID-based annotations get
    # the stricter cardinality checks below.
    if "factor_names" in record and not any(
        key in record
        for key in ("factor_ids", "factor_refs", "factors", "varied_factor_ids", "varied_factors")
    ):
        _validate_named_factors(record, filename, path, report)
        names = record.get("factor_names")
        if scope == "joint_effect" and (not isinstance(names, list) or len(names) < 2):
            _error(report, filename, f"{path}.attribution_scope", "joint_effect requires at least two factor names")
        if scope == "causal" and (not isinstance(names, list) or len(names) != 1):
            _error(report, filename, f"{path}.attribution_scope", "causal attribution requires one factor name")
        if scope == "isolated_effect" and (not isinstance(names, list) or not names):
            _error(report, filename, f"{path}.attribution_scope", "isolated_effect requires a factor name")
        return
    if scope == "isolated_effect":
        factors = _extract_ref_values(record, ("factor_ids", "factor_refs", "factors", "varied_factors"))
        if len(factors) != 1:
            _error(report, filename, f"{path}.attribution_scope", "isolated_effect requires exactly one factor")
    elif scope == "joint_effect":
        factors = _extract_ref_values(record, ("factor_ids", "factor_refs", "factors", "varied_factors"))
        if len(factors) < 2:
            _error(report, filename, f"{path}.attribution_scope", "joint_effect requires at least two factors")
    elif scope == "causal":
        factors = _extract_ref_values(record, ("factor_ids", "factor_refs", "factors", "varied_factors"))
        if len(factors) != 1:
            _error(report, filename, f"{path}.attribution_scope", "causal attribution requires one factor")


def _validate_named_factors(
    record: Mapping[str, Any], filename: str, path: str, report: ValidationReport
) -> None:
    names = record.get("factor_names")
    if not _nonempty_sequence(names) or any(not _nonempty_string(name) for name in names):
        _error(report, filename, f"{path}.factor_names", "must be a non-empty list of names")


def _validate_relation_membership(
    relation: Mapping[str, Any],
    series: Mapping[str, Any],
    path: str,
    report: ValidationReport,
) -> None:
    """Prevent a relation from borrowing results from another series."""

    for relation_key, series_keys, kind in (
        ("result_ids", ("result_ids", "measurement_ids"), "result"),
        ("outcome_ids", ("outcome_ids",), "outcome"),
        ("baseline_sample_ids", ("sample_ids",), "sample"),
        ("target_sample_ids", ("sample_ids",), "sample"),
    ):
        relation_ids = _string_refs(relation.get(relation_key))
        if not relation_ids:
            continue
        series_ids: set[str] = set()
        for key in series_keys:
            series_ids.update(_string_refs(series.get(key)))
        if not series_ids:
            continue
        for identifier in relation_ids:
            if identifier not in series_ids:
                _error(
                    report,
                    RELATIONS_FILE,
                    path,
                    f"{kind} {identifier} is not listed in relation series",
                )


def _validate_archive_definitions(
    document: Mapping[str, Any], context: _Context, report: ValidationReport
) -> None:
    """Check references in the shared sample/condition/measurement archive."""

    document_paper_id = _paper_id(document) or context.default_paper_id

    def check_source_list(value: Mapping[str, Any], path: str) -> None:
        for source_id in _string_refs(value.get("source_ids")):
            _validate_entity_ref(
                source_id,
                context.sources,
                document_paper_id,
                "source",
                EXPERIMENTS_FILE,
                path,
                report,
            )

    for key, kind, index in (
        ("samples", "sample", context.samples),
        ("conditions", "condition", context.conditions),
        ("outcomes", "outcome", context.outcomes),
        ("measurements", "measurement", context.results),
        ("observations", "observation", context.observations),
    ):
        values = document.get(key)
        if not isinstance(values, list):
            continue
        for position, value in enumerate(values):
            if not isinstance(value, Mapping):
                continue
            path = f"{key}[{position}]"
            check_source_list(value, path)
            if kind in {"measurement", "observation"} and _status(value):
                _validate_status_constraints(value, EXPERIMENTS_FILE, path, report)
            if kind == "measurement":
                for ref_key, ref_index, ref_kind in (
                    ("sample_id", context.samples, "sample"),
                    ("condition_id", context.conditions, "condition"),
                    ("outcome_id", context.outcomes, "outcome"),
                ):
                    ref = value.get(ref_key)
                    if isinstance(ref, str) and ref.strip():
                        _validate_entity_ref(
                            ref.strip(),
                            ref_index,
                            document_paper_id,
                            ref_kind,
                            EXPERIMENTS_FILE,
                            path,
                            report,
                        )
                    else:
                        _error(report, EXPERIMENTS_FILE, f"{path}.{ref_key}", "reference is required")
                replicate_count = value.get("replicate_count_reported")
                if replicate_count is not None and (
                    isinstance(replicate_count, bool)
                    or not isinstance(replicate_count, int)
                    or replicate_count < 0
                ):
                    _error(
                        report,
                        EXPERIMENTS_FILE,
                        f"{path}.replicate_count_reported",
                        "must be a non-negative integer when reported",
                    )
                if _status(value) == "conflict" and len(set(_string_refs(value.get("source_ids")))) < 2:
                    _error(
                        report,
                        EXPERIMENTS_FILE,
                        f"{path}.source_ids",
                        "conflict status requires at least two source ids",
                    )
                if _status(value) == "technical_failure" and value.get("value") is not None:
                    _error(
                        report,
                        EXPERIMENTS_FILE,
                        f"{path}.value",
                        "technical failure cannot carry a scientific result",
                    )
            elif kind == "observation":
                condition_id = value.get("condition_id")
                if isinstance(condition_id, str) and condition_id.strip():
                    _validate_entity_ref(
                        condition_id.strip(),
                        context.conditions,
                        document_paper_id,
                        "condition",
                        EXPERIMENTS_FILE,
                        path,
                        report,
                    )
                for sample_id in _string_refs(value.get("sample_ids")):
                    _validate_entity_ref(
                        sample_id,
                        context.samples,
                        document_paper_id,
                        "sample",
                        EXPERIMENTS_FILE,
                        path,
                        report,
                    )
                outcome_id = value.get("outcome_id")
                if isinstance(outcome_id, str) and outcome_id.strip():
                    _validate_entity_ref(
                        outcome_id.strip(),
                        context.outcomes,
                        document_paper_id,
                        "outcome",
                        EXPERIMENTS_FILE,
                        path,
                        report,
                    )
            elif kind == "condition":
                for sample_id in _string_refs(value.get("scope_sample_ids")):
                    _validate_entity_ref(
                        sample_id,
                        context.samples,
                        document_paper_id,
                        "sample",
                        EXPERIMENTS_FILE,
                        path,
                        report,
                    )


def _string_refs(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _validate_relation_refs(
    record: Mapping[str, Any],
    keys: Sequence[str],
    index: Mapping[str, _Record],
    paper_id: str,
    kind: str,
    filename: str,
    path: str,
    report: ValidationReport,
    *,
    required: bool = True,
) -> None:
    values, key = _first_present_refs(record, keys)
    if not values:
        if not required:
            return
        _error(report, filename, f"{path}.{key or keys[0]}", f"relation requires {kind} references")
        return
    for value in values:
        identifier = _ref_id(value)
        if not identifier:
            _error(report, filename, f"{path}.{key}", f"{kind} reference must contain an id")
            continue
        _validate_entity_ref(identifier, index, paper_id, kind, filename, path, report)


def _validate_ref_list(
    record: Mapping[str, Any],
    keys: Sequence[str],
    index: Mapping[str, _Record],
    paper_id: str,
    kind: str,
    filename: str,
    path: str,
    report: ValidationReport,
    *,
    required: bool = True,
) -> None:
    values, key = _first_present_refs(record, keys)
    if not values:
        if required:
            _error(
                report,
                filename,
                f"{path}.{key or keys[0]}",
                f"must contain at least one {kind} id",
            )
        return
    for value in values:
        identifier = _ref_id(value)
        if not identifier:
            _error(report, filename, f"{path}.{key}", f"{kind} reference must contain an id")
            continue
        _validate_entity_ref(identifier, index, paper_id, kind, filename, path, report)


def _validate_entity_ref(
    identifier: str,
    index: Mapping[str, _Record],
    paper_id: str,
    kind: str,
    filename: str,
    path: str,
    report: ValidationReport,
) -> None:
    record = index.get(identifier)
    if record is None:
        _error(report, filename, path, f"unknown {kind} id: {identifier}")
    elif paper_id and record.paper_id and record.paper_id != paper_id:
        _error(report, filename, path, f"{kind} {identifier} belongs to paper {record.paper_id}, not {paper_id}")


def _collect_root_definitions(context: _Context, document: Mapping[str, Any], report: ValidationReport) -> None:
    document_paper_id = _paper_id(document) or context.default_paper_id
    for key, kind, index in (
        ("samples", "sample", context.samples),
        ("conditions", "condition", context.conditions),
        ("outcomes", "outcome", context.outcomes),
        ("factors", "factor", context.factors),
        ("results", "result", context.results),
        ("measurements", "result", context.results),
        ("observations", "observation", context.observations),
        ("comparisons", "comparison", context.comparisons),
    ):
        for position, value in enumerate(_as_records(document.get(key), key, EXPERIMENTS_FILE, report)):
            if isinstance(value, Mapping):
                identifier = _id(
                    value,
                    f"{kind}_id",
                    "measurement_id" if kind == "result" else "",
                    "observation_id" if kind == "observation" else "",
                    "id",
                    "result_id" if kind == "result" else "",
                )
                if identifier:
                    _register(
                        index,
                        _Record(
                            kind,
                            identifier,
                            _paper_id(value) or document_paper_id,
                            value,
                            EXPERIMENTS_FILE,
                            f"{key}[{position}]",
                        ),
                        report,
                    )


def _collect_nested_definitions(
    context: _Context,
    experiment: Mapping[str, Any],
    path: str,
    paper_id: str,
    report: ValidationReport,
) -> None:
    for key, kind, index in (
        ("samples", "sample", context.samples),
        ("conditions", "condition", context.conditions),
        ("outcomes", "outcome", context.outcomes),
        ("factors", "factor", context.factors),
        ("results", "result", context.results),
        ("measurements", "result", context.results),
        ("observations", "observation", context.observations),
        ("comparisons", "comparison", context.comparisons),
    ):
        values = experiment.get(key)
        if not isinstance(values, list):
            continue
        for position, value in enumerate(values):
            if isinstance(value, Mapping):
                identifier = _id(
                    value,
                    f"{kind}_id",
                    "measurement_id" if kind == "result" else "",
                    "observation_id" if kind == "observation" else "",
                    "id",
                    "result_id" if kind == "result" else "",
                )
                if not identifier:
                    _error(report, EXPERIMENTS_FILE, f"{path}.{key}[{position}]", f"{kind} requires an id")
                    continue
                record_value = dict(value)
                record_value.setdefault("paper_id", paper_id)
                _register(
                    index,
                    _Record(
                        kind,
                        identifier,
                        _paper_id(record_value) or context.default_paper_id,
                        record_value,
                        EXPERIMENTS_FILE,
                        f"{path}.{key}[{position}]",
                    ),
                    report,
                )


def _register(index: dict[str, _Record], record: _Record | None, report: ValidationReport) -> None:
    if record is None:
        return
    if not record.identifier:
        return
    previous = index.get(record.identifier)
    if previous is not None:
        _error(
            report,
            record.file,
            record.path,
            f"duplicate {record.kind} id {record.identifier}; first seen at {previous.path}",
        )
    else:
        index[record.identifier] = record


def _make_record(
    kind: str,
    value: Any,
    context: _Context,
    filename: str,
    path: str,
    report: ValidationReport,
) -> _Record | None:
    if not isinstance(value, Mapping):
        _error(report, filename, path, "record must be an object")
        return None
    identifier = _id(value, f"{kind}_id", "source_id", "id", "evidence_id")
    if not identifier:
        _error(report, filename, path, f"{kind} requires an id")
        return None
    paper_id = _paper_id(value) or context.default_paper_id
    _check_paper(report, filename, path, paper_id, context.paper_ids)
    return _Record(kind, identifier, paper_id, value, filename, path)


def _manifest_paper_ids(manifest: Any, report: ValidationReport) -> set[str]:
    if not isinstance(manifest, Mapping):
        return set()
    values = _records_from_keys(manifest, ("papers", "documents"))
    root_paper_id = _paper_id(manifest)
    listed_paper_ids = {
        _paper_id(value) for value in values if isinstance(value, Mapping) and _paper_id(value)
    }
    if root_paper_id and listed_paper_ids and root_paper_id not in listed_paper_ids:
        _error(
            report,
            MANIFEST_FILE,
            "paper_id",
            "root paper_id does not match the papers list",
        )
    elif root_paper_id and not listed_paper_ids:
        values = [*values, manifest]
    if not values and root_paper_id:
        values = [manifest]
    result: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            _error(report, MANIFEST_FILE, f"papers[{index}]", "paper record must be an object")
            continue
        paper_id = _paper_id(value)
        if not paper_id:
            _error(report, MANIFEST_FILE, f"papers[{index}]", "paper_id is required")
            continue
        if paper_id in result:
            _error(report, MANIFEST_FILE, f"papers[{index}]", f"duplicate paper_id: {paper_id}")
        result.add(paper_id)
    return result


def _manifest_hashes(manifest: Mapping[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for item in _records_from_keys(manifest, ("papers", "documents")):
        if not isinstance(item, Mapping):
            continue
        paper_id = _paper_id(item)
        value = _value(item, "sha256", "source_hash", "document_sha256")
        if paper_id and isinstance(value, str):
            hashes[paper_id] = value
    # A single-paper manifest commonly keeps the reviewed PDF hash at the
    # document root instead of repeating it under ``papers``.
    paper_id = _paper_id(manifest)
    root_hash = _value(manifest, "pdf_sha256", "sha256", "source_hash", "document_sha256")
    if paper_id and isinstance(root_hash, str):
        hashes.setdefault(paper_id, root_hash)
    return hashes


def _validate_provenance_hashes(
    revision: Mapping[str, Any], path: str, report: ValidationReport
) -> None:
    values = _value(revision, "source_hash", "source_sha256")
    if values is None:
        values = revision.get("source_hashes")
    if values is None:
        provenance = revision.get("source_provenance")
        if isinstance(provenance, Mapping):
            values = _value(provenance, "sha256", "source_hash")
        elif isinstance(provenance, list):
            values = [
                _value(item, "sha256", "source_hash")
                for item in provenance
                if isinstance(item, Mapping)
            ]
    if values is None:
        return
    if isinstance(values, str):
        values = [values]
    if isinstance(values, list):
        values = [
            _value(value, "sha256", "source_hash") if isinstance(value, Mapping) else value
            for value in values
        ]
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not _HASH_RE.fullmatch(value) for value in values
    ):
        _error(report, REVISIONS_FILE, f"{path}.source_hash", "must contain SHA-256 hashes")


def _check_revision_manifest_hashes(
    revision: Mapping[str, Any],
    paper_id: str,
    context: _Context,
    path: str,
    report: ValidationReport,
) -> None:
    declared = _manifest_hashes(context.manifest).get(paper_id)
    if not declared:
        return
    values = _provenance_hash_values(revision)
    if values and declared not in values:
        _error(
            report,
            REVISIONS_FILE,
            f"{path}.source_hash",
            "revision source hash does not match manifest provenance",
        )


def _provenance_hash_values(value: Mapping[str, Any]) -> list[str]:
    hashes = _value(value, "source_hash", "source_sha256")
    if hashes is None:
        hashes = value.get("source_hashes")
    if hashes is None:
        provenance = value.get("source_provenance")
        if isinstance(provenance, Mapping):
            hashes = _value(provenance, "sha256", "source_hash")
        elif isinstance(provenance, list):
            hashes = [
                _value(item, "sha256", "source_hash")
                for item in provenance
                if isinstance(item, Mapping)
            ]
    if isinstance(hashes, str):
        return [hashes]
    if isinstance(hashes, list):
        return [
            item
            for value in hashes
            for item in [
                _value(value, "sha256", "source_hash") if isinstance(value, Mapping) else value
            ]
            if isinstance(item, str)
        ]
    return []


def _provenance_source_ids(value: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for key in ("source_id", "evidence_id"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            result.add(candidate.strip())
    for key in ("source_ids", "evidence_ids"):
        candidates = value.get(key)
        if isinstance(candidates, list):
            result.update(str(item).strip() for item in candidates if str(item).strip())
    for key in ("source_refs", "source_provenance"):
        candidates = value.get(key)
        if isinstance(candidates, Mapping):
            candidates = [candidates]
        if isinstance(candidates, list):
            for item in candidates:
                if isinstance(item, Mapping):
                    candidate = _id(item, "source_id", "evidence_id", "id")
                    if candidate:
                        result.add(candidate)
                elif isinstance(item, str) and item.strip():
                    result.add(item.strip())
    return result


def _as_records(document: Any, key: str, filename: str, report: ValidationReport) -> list[Any]:
    if document is None:
        return []
    if isinstance(document, list):
        return document
    if isinstance(document, Mapping):
        value = document.get(key)
        if value is None and key == "dispositions":
            value = document.get("papers")
        if isinstance(value, list):
            return value
        if value is None:
            return []
        _error(report, filename, key, "must be a list")
        return []
    _error(report, filename, None, "must be a JSON object or list")
    return []


def _records_from_keys(document: Mapping[str, Any], keys: Sequence[str]) -> list[Any]:
    for key in keys:
        value = document.get(key)
        if isinstance(value, list):
            return value
    return []


def _first_present_refs(record: Mapping[str, Any], keys: Sequence[str]) -> tuple[list[Any], str | None]:
    for key in keys:
        if key not in record:
            continue
        value = record[key]
        if isinstance(value, list):
            return value, key
        if isinstance(value, str) and value.strip():
            return [value], key
        if isinstance(value, Mapping):
            return [value], key
        return [], key
    return [], None


def _extract_ref_values(record: Mapping[str, Any], keys: Sequence[str]) -> list[Any]:
    values, _ = _first_present_refs(record, keys)
    return values


def _ref_id(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return _id(value, "factor_id", "result_id", "outcome_id", "sample_id", "condition_id", "id")
    return ""


def _id(value: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        if not key:
            continue
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _paper_id(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    for key in ("paper_id", "document_id", "study_id"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _value(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    return None


def _status(value: Mapping[str, Any]) -> str:
    candidate = _value(value, "status", "resolution_status")
    return candidate.strip().lower() if isinstance(candidate, str) else ""


def _check_paper(
    report: ValidationReport,
    filename: str,
    path: str,
    paper_id: str,
    paper_ids: set[str],
) -> None:
    if not paper_id:
        _error(report, filename, f"{path}.paper_id", "paper_id is required")
    elif paper_id not in paper_ids:
        _error(report, filename, f"{path}.paper_id", f"unknown paper_id: {paper_id}")


def _count(value: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key not in value:
            continue
        candidate = value[key]
        if isinstance(candidate, bool):
            return None
        if isinstance(candidate, int):
            return candidate
        return None
    return None


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple, set)) and bool(value)


def _error(report: ValidationReport, filename: str, path: str | None, message: str) -> None:
    report.errors.append(ValidationIssue("error", filename, path, message))


_ALLOWED_DISPOSITIONS = {
    "comparable_evidence",
    "partial_evidence",
    "no_comparable_evidence",
    "coverage_incomplete",
    "extraction_failed",
    "technical_failure",
    "not_comparable",
    "incomplete",
    "resolved",
}


if __name__ == "__main__":
    main()
