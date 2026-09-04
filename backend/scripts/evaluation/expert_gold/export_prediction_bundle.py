#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha1
import json
from pathlib import Path
import sys
from typing import Any


SCHEMA_VERSION = "prediction-bundle-v0.4"
DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(DEFAULT_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_BACKEND_ROOT))

from infra.persistence.database import (  # noqa: E402
    DatabaseSettings,
    build_database_engine,
    build_session_factory,
)
from infra.persistence.postgres.document_profile_repository import (  # noqa: E402
    PostgresDocumentProfileRepository,
)
from infra.persistence.postgres.objective_repository import (  # noqa: E402
    PostgresObjectiveRepository,
)
from infra.persistence.postgres.source_artifact_repository import (  # noqa: E402
    PostgresSourceArtifactRepository,
)


DEFAULT_OUTPUT_PATH = (
    DEFAULT_BACKEND_ROOT
    / "tests"
    / "fixtures"
    / "local_expert_gold"
    / "generated"
    / "prediction_bundle.json"
)
ARTIFACT_NAMES = (
    "documents",
    "document_profiles",
    "objective_evidence",
    "objective_findings",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export published Objective results for expert-gold evaluation."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--collection-id")
    source.add_argument("--output-dir", type=Path)
    parser.add_argument("--backend-root", type=Path, default=DEFAULT_BACKEND_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    output_path = await export_prediction_bundle(
        backend_root=args.backend_root,
        collection_id=args.collection_id,
        source_output_dir=args.output_dir,
        output_path=args.output,
    )
    print(output_path)


async def export_prediction_bundle(
    *,
    backend_root: str | Path = DEFAULT_BACKEND_ROOT,
    collection_id: str | None = None,
    source_output_dir: str | Path | None = None,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    root = Path(backend_root).expanduser().resolve()
    output_dir = _resolve_source_output_dir(
        backend_root=root,
        collection_id=collection_id,
        source_output_dir=source_output_dir,
    )
    resolved_collection_id = collection_id or output_dir.parent.name
    records, missing = await _load_artifacts(resolved_collection_id)
    bundle = build_prediction_bundle(
        collection_id=resolved_collection_id,
        source_output_dir=output_dir,
        records_by_artifact=records,
        missing_artifacts=missing,
    )
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def build_prediction_bundle(
    *,
    collection_id: str,
    source_output_dir: Path,
    records_by_artifact: dict[str, list[dict[str, Any]]],
    missing_artifacts: list[str],
) -> dict[str, Any]:
    evidence = _raw_records(
        records_by_artifact.get("objective_evidence", []),
        "objective_evidence",
    )
    findings = _raw_records(
        records_by_artifact.get("objective_findings", []),
        "objective_findings",
    )
    projected = _project_objective_evidence(evidence)
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "collection_id": collection_id,
            "source_output_dir": str(source_output_dir),
            "fact_source": "published_objectives",
            "artifact_rows": {
                name: len(records_by_artifact.get(name, []))
                for name in ARTIFACT_NAMES
            },
            "missing_artifacts": list(missing_artifacts),
        },
        "papers": _convert_papers(
            records_by_artifact.get("documents", []),
            records_by_artifact.get("document_profiles", []),
        ),
        "samples": projected["samples"],
        "process_parameters": projected["process_parameters"],
        "test_conditions": projected["test_conditions"],
        "measurement_results": projected["measurement_results"],
        "comparisons": projected["comparisons"],
        "observations": projected["observations"],
        "evidence": evidence,
        "uncertainties": [
            {
                "finding_id": finding.get("finding_id"),
                "synthesis_status": finding.get("synthesis_status"),
                "attribution_scope": finding.get("attribution_scope"),
                "certainty": finding.get("certainty"),
                "limitations": finding.get("limitations", []),
                "source": finding["source"],
            }
            for finding in findings
            if finding.get("synthesis_status") != "agreement"
        ],
        "global_notes": [],
        "objective_evidence": evidence,
        "objective_findings": findings,
    }


async def _load_artifacts(
    collection_id: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    engine = build_database_engine(DatabaseSettings())
    try:
        sessions = build_session_factory(engine)
        documents = await PostgresSourceArtifactRepository(
            sessions
        ).read_collection_documents(collection_id)
        profiles = await PostgresDocumentProfileRepository(sessions).list_collection(
            collection_id
        )
        objective_repository = PostgresObjectiveRepository(sessions)
        evidence: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        for objective in await objective_repository.list_objectives(collection_id):
            version = objective.published_analysis_version
            if version is None:
                continue
            objective_evidence, _ = await objective_repository.list_evidence(
                collection_id,
                objective.objective_id,
                version,
                offset=0,
                limit=10_000,
            )
            objective_findings, _ = await objective_repository.list_findings(
                collection_id,
                objective.objective_id,
                version,
                offset=0,
                limit=10_000,
            )
            evidence.extend(item.to_record() for item in objective_evidence)
            findings.extend(item.to_record() for item in objective_findings)
    finally:
        await engine.dispose()
    records = {
        "documents": [item.to_record() for item in documents],
        "document_profiles": [item.to_record() for item in profiles],
        "objective_evidence": evidence,
        "objective_findings": findings,
    }
    return records, [name for name in ARTIFACT_NAMES if not records[name]]


def _convert_papers(
    documents: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    profiles_by_document_id = {
        str(item.get("document_id") or ""): item for item in profiles
    }
    papers: list[dict[str, Any]] = []
    for row_number, document in enumerate(documents, start=1):
        document_id = str(
            document.get("document_id") or document.get("id") or ""
        ).strip()
        profile = profiles_by_document_id.get(document_id, {})
        metadata = document.get("metadata") or {}
        papers.append(
            {
                "paper_id": document_id,
                "title": profile.get("title") or document.get("title") or "",
                "doi": metadata.get("doi"),
                "source_filename": profile.get("source_filename")
                or metadata.get("source_filename"),
                "document_type": profile.get("doc_type"),
                "source": {"artifact": "documents", "row": row_number},
            }
        )
    return papers


def _raw_records(
    records: list[dict[str, Any]],
    artifact: str,
) -> list[dict[str, Any]]:
    return [
        {**dict(record), "source": {"artifact": artifact, "row": row_number}}
        for row_number, record in enumerate(records, start=1)
    ]


def _project_objective_evidence(
    evidence_records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Project durable Objective Evidence into the generic gold vocabulary.

    The Objective Evidence model is the authoritative runtime artifact.  Gold
    evaluation still uses paper/sample/measurement/comparison records, so this
    projection keeps those views derived from the same Source-backed rows rather
    than reporting empty legacy sections.
    """

    samples: dict[tuple[str, str], dict[str, Any]] = {}
    process_parameters: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    test_conditions: dict[tuple[str, str], dict[str, Any]] = {}
    measurements: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    comparisons: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    observations: dict[tuple[str, str, str], dict[str, Any]] = {}

    for evidence in evidence_records:
        paper_id = _text(evidence.get("document_id"))
        if not paper_id:
            continue
        evidence_id = _text(evidence.get("evidence_id"))
        source = evidence.get("source") if isinstance(evidence.get("source"), dict) else {}
        evidence_ids = [value for value in (evidence_id, *_strings(evidence.get("evidence_anchor_ids"))) if value]
        context = evidence.get("scientific_context") if isinstance(evidence.get("scientific_context"), dict) else {}
        material_values = _context_values(context, "material")
        sample_labels = _sample_labels(context)
        comparison = evidence.get("comparison") if isinstance(evidence.get("comparison"), dict) else {}
        baseline_label = _text(comparison.get("baseline_label"))
        target_label = _text(comparison.get("target_label"))
        if baseline_label and target_label:
            sample_labels = list(dict.fromkeys((*sample_labels, baseline_label, target_label)))

        sample_ids = []
        for label in sample_labels:
            sample_id = _projection_id("sample", paper_id, label)
            sample_ids.append(sample_id)
            sample_key = (paper_id, _normalized_label(label))
            row = samples.setdefault(
                sample_key,
                {
                    "paper_id": paper_id,
                    "sample_id": sample_id,
                    "label_in_paper": label,
                    "sample_description": _context_description(context),
                    "material_system": material_values[0] if material_values else "",
                    "difference_type": "",
                    "difference_value": "",
                    "is_control_sample": "unknown",
                    "is_control_sample_text": "",
                    "evidence_reference": _evidence_reference(evidence),
                    "evidence_ids": [],
                    "notes": "",
                    "source": source,
                },
            )
            row["evidence_ids"] = _merge_strings(row.get("evidence_ids"), evidence_ids)
            if not row.get("sample_description"):
                row["sample_description"] = _context_description(context)
            if not row.get("material_system") and material_values:
                row["material_system"] = material_values[0]

        for attribute in _context_attributes(context, "process"):
            name = _text(attribute.get("name"))
            value = attribute.get("value")
            unit = _text(attribute.get("unit"))
            if not name or value in (None, ""):
                continue
            targets = sample_ids or [""]
            for sample_id in targets:
                key = (paper_id, sample_id, _normalized_label(name), _scalar_key(value, unit))
                row = process_parameters.setdefault(
                    key,
                    {
                        "paper_id": paper_id,
                        "sample_reference": sample_id,
                        "sample_ids": [sample_id] if sample_id else [],
                        "sample_scope": "explicit" if sample_id else "all_samples",
                        "parameter_category": "process",
                        "original_parameter_name": name,
                        "parameter_description": name,
                        "value": value,
                        "unit": unit,
                        "applies_to": sample_id,
                        "evidence_reference": _evidence_reference(evidence),
                        "evidence_ids": [],
                        "notes": "",
                        "source": source,
                    },
                )
                row["evidence_ids"] = _merge_strings(row.get("evidence_ids"), evidence_ids)

        test_attributes = _context_attributes(context, "test")
        if test_attributes:
            condition_id = _projection_id("test", paper_id, _context_description(context, section="test"))
            key = (paper_id, condition_id)
            row = test_conditions.setdefault(
                key,
                {
                    "paper_id": paper_id,
                    "test_condition_id": condition_id,
                    "sample_reference": sample_ids[0] if len(sample_ids) == 1 else "",
                    "sample_ids": sample_ids,
                    "sample_scope": "explicit" if sample_ids else "all_samples",
                    "test_type": "",
                    "test_temperature": "",
                    "strain_rate_or_frequency": "",
                    "build_orientation": "",
                    "sampling_orientation": "",
                    "surface_condition": "",
                    "test_standard": "",
                    "other_conditions": "",
                    "condition_payload": {},
                    "evidence_reference": _evidence_reference(evidence),
                    "evidence_ids": [],
                    "notes": "",
                    "source": source,
                },
            )
            for attribute in test_attributes:
                name = _text(attribute.get("name"))
                if not name:
                    continue
                row["condition_payload"][name] = attribute.get("value")
                normalized_name = _normalized_label(name)
                if normalized_name in {"method", "test", "test type", "test method"}:
                    row["test_type"] = attribute.get("value")
                elif normalized_name in {"temperature", "test temperature"}:
                    row["test_temperature"] = attribute.get("value")
                elif normalized_name in {"standard", "test standard"}:
                    row["test_standard"] = attribute.get("value")
                else:
                    row["other_conditions"] = (
                        f"{row['other_conditions']}; " if row["other_conditions"] else ""
                    ) + f"{name}={attribute.get('value')}"
            row["evidence_ids"] = _merge_strings(row.get("evidence_ids"), evidence_ids)

        result = evidence.get("reported_result") if isinstance(evidence.get("reported_result"), dict) else {}
        outcome = _text(result.get("outcome"))
        if outcome:
            unit = _text(result.get("unit"))
            target_value = result.get("target_value")
            if target_value in (None, ""):
                target_value = result.get("value")
            baseline_value = result.get("baseline_value")
            metric_key = _normalized_label(outcome)
            if baseline_label and target_label and baseline_value not in (None, "") and target_value not in (None, ""):
                for label, value in ((baseline_label, baseline_value), (target_label, target_value)):
                    sample_id = _projection_id("sample", paper_id, label)
                    _merge_measurement(
                        measurements,
                        paper_id=paper_id,
                        sample_id=sample_id,
                        metric=outcome,
                        value=value,
                        unit=unit,
                        direction=result.get("direction"),
                        evidence_ids=evidence_ids,
                        source=source,
                    )
                comparison_key = (
                    paper_id,
                    _projection_id("sample", paper_id, target_label),
                    _projection_id("sample", paper_id, baseline_label),
                    metric_key,
                    _scalar_key(target_value, unit),
                    _scalar_key(baseline_value, unit),
                )
                row = comparisons.setdefault(
                    comparison_key,
                    {
                        "paper_id": paper_id,
                        "comparison_id": _projection_id("comparison", *comparison_key),
                        "current_sample_id": comparison_key[1],
                        "baseline_reference": baseline_label,
                        "baseline_sample_ids": [comparison_key[2]],
                        "baseline_type": "source_reported",
                        "metric_name": outcome,
                        "current_value": target_value,
                        "baseline_value": baseline_value,
                        "unit": unit,
                        "direction": result.get("direction") or "unknown",
                        "direction_text": result.get("direction") or "unknown",
                        "evidence_reference": _evidence_reference(evidence),
                        "evidence_ids": [],
                        "notes": _text(evidence.get("attribution_scope")),
                        "source": source,
                    },
                )
                row["evidence_ids"] = _merge_strings(row.get("evidence_ids"), evidence_ids)
            elif sample_ids:
                _merge_measurement(
                    measurements,
                    paper_id=paper_id,
                    sample_id=sample_ids[0],
                    metric=outcome,
                    value=target_value,
                    unit=unit,
                    direction=result.get("direction"),
                    evidence_ids=evidence_ids,
                    source=source,
                )
            else:
                observation_key = (paper_id, metric_key, _text(result.get("result_text")))
                row = observations.setdefault(
                    observation_key,
                    {
                        "paper_id": paper_id,
                        "observation_id": _projection_id("observation", *observation_key),
                        "sample_reference": "",
                        "sample_ids": [],
                        "sample_scope": "all_samples",
                        "characterization_method": "",
                        "observed_object": outcome,
                        "value_or_description": result.get("value", result.get("result_text")),
                        "unit": unit,
                        "author_interpretation": result.get("result_text"),
                        "evidence_reference": _evidence_reference(evidence),
                        "evidence_ids": evidence_ids,
                        "notes": "",
                        "source": source,
                    },
                )
                row["evidence_ids"] = _merge_strings(row.get("evidence_ids"), evidence_ids)

    return {
        "samples": list(samples.values()),
        "process_parameters": list(process_parameters.values()),
        "test_conditions": list(test_conditions.values()),
        "measurement_results": list(measurements.values()),
        "comparisons": list(comparisons.values()),
        "observations": list(observations.values()),
    }


def _merge_measurement(
    records: dict[tuple[str, str, str, str, str], dict[str, Any]],
    *,
    paper_id: str,
    sample_id: str,
    metric: str,
    value: Any,
    unit: str,
    direction: Any,
    evidence_ids: list[str],
    source: dict[str, Any],
) -> None:
    key = (paper_id, sample_id, _normalized_label(metric), _scalar_key(value, unit), unit)
    row = records.setdefault(
        key,
        {
            "paper_id": paper_id,
            "result_id": _projection_id("result", *key),
            "sample_id": sample_id,
            "sample_ids": [sample_id],
            "test_condition_id": "",
            "metric_name": metric,
            "value_or_trend": value if value not in (None, "") else direction or "",
            "value_payload": value,
            "unit": unit,
            "claim_scope": "current_work",
            "claim_scope_text": "current_work",
            "source_type": "Objective Evidence",
            "evidence_reference": "",
            "evidence_ids": [],
            "notes": "",
            "source": source,
        },
    )
    row["evidence_ids"] = _merge_strings(row.get("evidence_ids"), evidence_ids)


def _context_attributes(context: dict[str, Any], section: str) -> list[dict[str, Any]]:
    value = context.get(section)
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _context_values(context: dict[str, Any], section: str) -> list[str]:
    return [_text(item.get("value")) for item in _context_attributes(context, section) if _text(item.get("value"))]


def _sample_labels(context: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    identity_names = {"sample", "sample id", "sample_id", "id", "group", "condition", "sample condition", "label", "specimen"}
    for item in _context_attributes(context, "sample"):
        name = _normalized_label(item.get("name"))
        value = _text(item.get("value"))
        if value and (name in identity_names or not labels):
            labels.append(value)
    return list(dict.fromkeys(labels))


def _context_description(context: dict[str, Any], *, section: str | None = None) -> str:
    sections = (section,) if section else ("sample", "process", "test")
    parts = []
    for name in sections:
        for item in _context_attributes(context, name):
            label = _text(item.get("name"))
            value = _text(item.get("value"))
            if label and value:
                parts.append(f"{label}={value}")
    return "; ".join(parts)


def _evidence_reference(evidence: dict[str, Any]) -> str:
    refs = evidence.get("source_refs")
    if isinstance(refs, list):
        values = [_text(item.get("source_ref")) for item in refs if isinstance(item, dict)]
        return "; ".join(value for value in values if value)
    return _text(evidence.get("source_ref"))


def _projection_id(kind: str, *values: Any) -> str:
    payload = "|".join(_text(value) for value in values)
    return f"{kind}_{sha1(payload.encode('utf-8')).hexdigest()[:20]}"


def _normalized_label(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _scalar_key(value: Any, unit: Any = "") -> str:
    return f"{_text(value)}|{_text(unit)}"


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _merge_strings(existing: Any, values: list[str]) -> list[str]:
    return list(dict.fromkeys((*_strings(existing), *values)))


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _resolve_source_output_dir(
    *,
    backend_root: Path,
    collection_id: str | None,
    source_output_dir: str | Path | None,
) -> Path:
    if source_output_dir is not None:
        return Path(source_output_dir).expanduser().resolve()
    if not collection_id:
        raise SystemExit("--collection-id or --output-dir is required")
    return backend_root / "data" / "collections" / collection_id / "output"


if __name__ == "__main__":
    asyncio.run(main_async())
