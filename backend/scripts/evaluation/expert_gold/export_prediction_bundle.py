#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

import pandas as pd


SCHEMA_VERSION = "prediction-bundle-v0.1"
DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(DEFAULT_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_BACKEND_ROOT))

from infra.persistence.sqlite import (  # noqa: E402
    SqliteCoreFactRepository,
    SqliteSourceArtifactRepository,
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
    "objective_evidence_units",
    "objective_logic_chains",
    "evidence_anchors",
    "method_facts",
    "sample_variants",
    "test_conditions",
    "baseline_references",
    "measurement_results",
    "characterization_observations",
    "structure_features",
    "comparable_results",
    "collection_comparable_results",
    "pairwise_comparison_relations",
    "comparison_rows",
)

PROCESS_UNIT_SUFFIXES = (
    ("laser_power_w", "W"),
    ("scan_speed_mm_s", "mm/s"),
    ("layer_thickness_um", "um"),
    ("hatch_spacing_um", "um"),
    ("spot_size_um", "um"),
    ("energy_density_j_mm3", "J/mm3"),
    ("preheat_temperature_c", "C"),
    ("oxygen_level_ppm", "ppm"),
    ("strain_rate_s-1", "s^-1"),
    ("frequency_hz", "Hz"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export built system artifacts into a prediction bundle aligned "
            "with the expert gold bundle."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--collection-id",
        help="Collection id under <backend-root>/data/collections/<collection-id>.",
    )
    source.add_argument(
        "--output-dir",
        type=Path,
        help="Direct collection output directory; collection id is inferred from its parent.",
    )
    parser.add_argument(
        "--backend-root",
        type=Path,
        default=DEFAULT_BACKEND_ROOT,
        help="Backend root. Defaults to the repo-local backend directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=(
            "Output JSON path. Defaults to "
            "tests/fixtures/local_expert_gold/generated/prediction_bundle.json."
        ),
    )
    parser.add_argument(
        "--fact-source",
        choices=("paper_facts", "objective_first"),
        default="paper_facts",
        help=(
            "Semantic fact family to export. Use objective_first to project "
            "ObjectiveEvidenceUnit records into the gold-aligned bundle."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = export_prediction_bundle(
        backend_root=args.backend_root,
        collection_id=args.collection_id,
        source_output_dir=args.output_dir,
        output_path=args.output,
        fact_source=args.fact_source,
    )
    print(output_path)


def export_prediction_bundle(
    *,
    backend_root: str | Path = DEFAULT_BACKEND_ROOT,
    collection_id: str | None = None,
    source_output_dir: str | Path | None = None,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    fact_source: str = "paper_facts",
) -> Path:
    root = Path(backend_root).expanduser().resolve()
    output_dir = _resolve_source_output_dir(
        backend_root=root,
        collection_id=collection_id,
        source_output_dir=source_output_dir,
    )
    resolved_collection_id = collection_id or output_dir.parent.name

    records_by_artifact, missing_artifacts = _load_artifacts(
        backend_root=root,
        collection_id=resolved_collection_id,
        db_path=_resolve_repository_db_path(
            backend_root=root,
            source_output_dir=output_dir,
        ),
    )
    bundle = build_prediction_bundle(
        collection_id=resolved_collection_id,
        source_output_dir=output_dir,
        records_by_artifact=records_by_artifact,
        missing_artifacts=missing_artifacts,
        fact_source=fact_source,
    )
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(_json_safe(bundle), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def build_prediction_bundle(
    *,
    collection_id: str | None,
    source_output_dir: Path,
    records_by_artifact: dict[str, list[dict[str, Any]]],
    missing_artifacts: list[str],
    fact_source: str = "paper_facts",
) -> dict[str, Any]:
    resolved_collection_id = collection_id or _infer_collection_id(records_by_artifact)
    papers = _convert_papers(
        records_by_artifact["documents"],
        records_by_artifact["document_profiles"],
        records_by_artifact=records_by_artifact,
    )
    if fact_source == "objective_first":
        objective_units = records_by_artifact["objective_evidence_units"]
        samples = _convert_objective_samples(objective_units)
        process_parameters = _convert_objective_process_parameters(objective_units)
        test_conditions = _convert_objective_test_conditions(objective_units)
        measurement_results = _convert_objective_measurement_results(objective_units)
        comparisons = _convert_objective_comparisons(objective_units)
        observations = _convert_objective_observations(objective_units)
        evidence = _convert_objective_evidence(objective_units)
    else:
        samples = _convert_samples(records_by_artifact["sample_variants"])
        process_parameters = _convert_process_parameters(
            records_by_artifact["method_facts"],
            records_by_artifact["sample_variants"],
        )
        test_conditions = _convert_test_conditions(
            records_by_artifact["test_conditions"]
        )
        measurement_results = _convert_measurement_results(
            records_by_artifact["measurement_results"]
        )
        comparisons = _convert_comparisons(
            records_by_artifact["pairwise_comparison_relations"],
            records_by_artifact["comparison_rows"],
            records_by_artifact["baseline_references"],
        )
        observations = _convert_observations(
            records_by_artifact["characterization_observations"]
        )
        evidence = _convert_evidence(records_by_artifact["evidence_anchors"])
    bundle: dict[str, Any] = {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "collection_id": resolved_collection_id,
            "source_output_dir": str(source_output_dir),
            "fact_source": fact_source,
            "artifact_rows": {
                name: len(records)
                for name, records in records_by_artifact.items()
            },
            "missing_artifacts": missing_artifacts,
        },
        "papers": papers,
        "samples": samples,
        "process_parameters": process_parameters,
        "test_conditions": test_conditions,
        "measurement_results": measurement_results,
        "comparisons": comparisons,
        "observations": observations,
        "evidence": evidence,
        "uncertainties": [],
        "global_notes": [],
        "objective_evidence_units": _raw_records(
            records_by_artifact["objective_evidence_units"],
            "objective_evidence_units",
        ),
        "objective_logic_chains": _raw_records(
            records_by_artifact["objective_logic_chains"],
            "objective_logic_chains",
        ),
        "baseline_references": _raw_records(
            records_by_artifact["baseline_references"],
            "baseline_references",
        ),
        "method_facts": _raw_records(records_by_artifact["method_facts"], "method_facts"),
        "structure_features": _raw_records(
            records_by_artifact["structure_features"],
            "structure_features",
        ),
        "comparable_results": _raw_records(
            records_by_artifact["comparable_results"],
            "comparable_results",
        ),
        "collection_comparable_results": _raw_records(
            records_by_artifact["collection_comparable_results"],
            "collection_comparable_results",
        ),
        "pairwise_comparison_relations": _raw_records(
            records_by_artifact["pairwise_comparison_relations"],
            "pairwise_comparison_relations",
        ),
        "comparison_rows": _raw_records(
            records_by_artifact["comparison_rows"],
            "comparison_rows",
        ),
    }
    return bundle


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


def _load_artifacts(
    *,
    backend_root: Path,
    collection_id: str,
    db_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    source_artifacts = SqliteSourceArtifactRepository(
        db_path
    ).read_collection_artifacts(collection_id)
    core_facts = SqliteCoreFactRepository(db_path).read_collection_facts(collection_id)
    records_by_artifact: dict[str, list[dict[str, Any]]] = {
        "documents": [record.to_record() for record in source_artifacts.documents],
        "document_profiles": [
            record.to_record() for record in core_facts.document_profiles
        ],
        "objective_evidence_units": [
            record.to_record() for record in core_facts.objective_evidence_units
        ],
        "objective_logic_chains": [
            record.to_record() for record in core_facts.objective_logic_chains
        ],
        "evidence_anchors": [
            record.to_record() for record in core_facts.evidence_anchors
        ],
        "method_facts": [record.to_record() for record in core_facts.method_facts],
        "sample_variants": [
            record.to_record() for record in core_facts.sample_variants
        ],
        "test_conditions": [
            record.to_record() for record in core_facts.test_conditions
        ],
        "baseline_references": [
            record.to_record() for record in core_facts.baseline_references
        ],
        "measurement_results": [
            record.to_record() for record in core_facts.measurement_results
        ],
        "characterization_observations": [
            record.to_record() for record in core_facts.characterization_observations
        ],
        "structure_features": [
            record.to_record() for record in core_facts.structure_features
        ],
        "comparable_results": [
            record.to_record() for record in core_facts.comparable_results
        ],
        "collection_comparable_results": [
            record.to_record() for record in core_facts.collection_comparable_results
        ],
        "pairwise_comparison_relations": [
            record.to_record() for record in core_facts.pairwise_comparison_relations
        ],
        "comparison_rows": [
            record.to_record() for record in core_facts.comparison_rows
        ],
    }
    missing_artifacts = [
        name for name in ARTIFACT_NAMES if not records_by_artifact.get(name)
    ]
    return records_by_artifact, missing_artifacts


def _resolve_repository_db_path(
    *,
    backend_root: Path,
    source_output_dir: Path,
) -> Path:
    for candidate_dir in (source_output_dir, *source_output_dir.parents):
        run_scoped_db = candidate_dir / "lens.sqlite"
        if run_scoped_db.is_file() and run_scoped_db.stat().st_size > 0:
            return run_scoped_db
    return backend_root / "data" / "lens.sqlite"


def _convert_papers(
    documents: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    *,
    records_by_artifact: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    document_lookup = {
        _document_id(row): (row_number, row)
        for row_number, row in _rows_with_numbers(documents)
        if _document_id(row)
    }
    profile_lookup = {
        _text(row, "document_id", "id"): (row_number, row)
        for row_number, row in _rows_with_numbers(profiles)
        if _text(row, "document_id", "id")
    }
    paper_ids = list(
        dict.fromkeys(
            [
                *document_lookup.keys(),
                *profile_lookup.keys(),
                *_document_ids_from_records(records_by_artifact.values()),
            ]
        )
    )

    records: list[dict[str, Any]] = []
    for paper_id in paper_ids:
        document_row_number, document = document_lookup.get(paper_id, (None, {}))
        profile_row_number, profile = profile_lookup.get(paper_id, (None, {}))
        source = (
            _source("document_profiles", profile_row_number)
            if profile_row_number is not None
            else _source("documents", document_row_number)
        )
        records.append(
            {
                "paper_id": paper_id,
                "title": _text(profile, "title") or _text(document, "title", "name"),
                "doi": _text(document, "doi") or _text(profile, "doi"),
                "source_filename": _text(profile, "source_filename")
                or _text(document, "source_filename", "filename"),
                "document_type": _text(profile, "doc_type", "document_type"),
                "material_system": _profile_material_system(profile),
                "process_type": _profile_process_type(profile),
                "research_goal": _profile_payload_text(profile, "research_goal"),
                "main_variables": _profile_payload_text(profile, "main_variables"),
                "target_properties": _profile_payload_text(profile, "target_properties"),
                "confidence": _first_value(profile, "confidence"),
                "source": source,
            }
        )
    return records


def _convert_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        records.append(
            {
                "paper_id": _text(row, "document_id"),
                "sample_id": _text(row, "variant_id"),
                "label_in_paper": _text(row, "variant_label"),
                "sample_description": _text(row, "variant_label"),
                "material_system": _material_system_text(row),
                "host_material_system": _first_value(row, "host_material_system"),
                "difference_type": _text(row, "variable_axis_type"),
                "difference_value": _first_value(row, "variable_value"),
                "is_control_sample": "",
                "evidence_ids": _string_list(row.get("source_anchor_ids")),
                "structure_feature_ids": _string_list(row.get("structure_feature_ids")),
                "confidence": _first_value(row, "confidence"),
                "epistemic_status": _text(row, "epistemic_status"),
                "source": _source("sample_variants", row_number),
            }
        )
    return records


def _convert_process_parameters(
    method_rows: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(sample_rows):
        context = _dict_value(row.get("process_context"))
        for key, value in context.items():
            if not _present(value):
                continue
            records.append(
                {
                    "paper_id": _text(row, "document_id"),
                    "sample_reference": _text(row, "variant_id"),
                    "sample_ids": [_text(row, "variant_id")]
                    if _text(row, "variant_id")
                    else [],
                    "sample_scope": "single_sample",
                    "parameter_category": "process_context",
                    "original_parameter_name": key,
                    "parameter_description": key,
                    "value": value,
                    "unit": _infer_process_unit(key),
                    "applies_to": _text(row, "variant_label"),
                    "evidence_ids": _string_list(row.get("source_anchor_ids")),
                    "confidence": _first_value(row, "confidence"),
                    "epistemic_status": _text(row, "epistemic_status"),
                    "source": _source("sample_variants", row_number),
                }
            )

    for row_number, row in _rows_with_numbers(method_rows):
        payload = _dict_value(row.get("method_payload"))
        if not payload:
            records.append(
                {
                    "paper_id": _text(row, "document_id"),
                    "sample_reference": "",
                    "sample_ids": [],
                    "sample_scope": "",
                    "parameter_category": _text(row, "method_role"),
                    "original_parameter_name": _text(row, "method_name"),
                    "parameter_description": _text(row, "method_name"),
                    "value": _text(row, "method_name"),
                    "unit": "",
                    "applies_to": _text(row, "method_role"),
                    "evidence_ids": _string_list(row.get("evidence_anchor_ids")),
                    "confidence": _first_value(row, "confidence"),
                    "epistemic_status": _text(row, "epistemic_status"),
                    "source": _source("method_facts", row_number),
                }
            )
            continue
        for key, value in payload.items():
            if not _present(value):
                continue
            records.append(
                {
                    "paper_id": _text(row, "document_id"),
                    "sample_reference": "",
                    "sample_ids": [],
                    "sample_scope": "",
                    "parameter_category": _text(row, "method_role"),
                    "original_parameter_name": key,
                    "parameter_description": key,
                    "value": value,
                    "unit": _infer_process_unit(key),
                    "applies_to": _text(row, "method_name"),
                    "evidence_ids": _string_list(row.get("evidence_anchor_ids")),
                    "confidence": _first_value(row, "confidence"),
                    "epistemic_status": _text(row, "epistemic_status"),
                    "source": _source("method_facts", row_number),
                }
            )
    return records


def _convert_test_conditions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        payload = _dict_value(row.get("condition_payload"))
        records.append(
            {
                "paper_id": _text(row, "document_id"),
                "test_condition_id": _text(row, "test_condition_id"),
                "sample_reference": "",
                "sample_ids": [],
                "sample_scope": _text(row, "scope_level"),
                "test_type": _text(row, "property_type", "template_type")
                or _payload_text(payload, "test_method"),
                "test_temperature": _payload_text(
                    payload,
                    "test_temperature_c",
                    "temperature_c",
                    "temperature",
                ),
                "strain_rate_or_frequency": _payload_text(
                    payload,
                    "strain_rate_s-1",
                    "strain_rate",
                    "frequency_hz",
                    "frequency",
                ),
                "build_orientation": _payload_text(payload, "build_orientation"),
                "sampling_orientation": _payload_text(
                    payload,
                    "sample_orientation",
                    "loading_direction",
                ),
                "surface_condition": _payload_text(payload, "surface_condition"),
                "test_standard": _payload_text(payload, "test_standard"),
                "other_conditions": _remaining_payload(
                    payload,
                    excluded={
                        "test_method",
                        "test_temperature_c",
                        "temperature_c",
                        "temperature",
                        "strain_rate_s-1",
                        "strain_rate",
                        "frequency_hz",
                        "frequency",
                        "build_orientation",
                        "sample_orientation",
                        "loading_direction",
                        "surface_condition",
                        "test_standard",
                    },
                ),
                "condition_payload": payload,
                "condition_completeness": _text(row, "condition_completeness"),
                "missing_fields": _string_list(row.get("missing_fields")),
                "evidence_ids": _string_list(row.get("evidence_anchor_ids")),
                "confidence": _first_value(row, "confidence"),
                "epistemic_status": _text(row, "epistemic_status"),
                "source": _source("test_conditions", row_number),
            }
        )
    return records


def _convert_measurement_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        value_payload = _first_value(row, "value_payload")
        records.append(
            {
                "paper_id": _text(row, "document_id"),
                "result_id": _text(row, "result_id"),
                "sample_id": _text(row, "variant_id"),
                "sample_ids": [_text(row, "variant_id")]
                if _text(row, "variant_id")
                else [],
                "test_condition_id": _text(row, "test_condition_id"),
                "metric_name": _text(row, "property_normalized"),
                "value_or_trend": _summarize_value_payload(value_payload),
                "unit": _text(row, "unit"),
                "claim_scope": _text(row, "claim_scope"),
                "data_source": _text(row, "result_source_type"),
                "baseline_id": _text(row, "baseline_id"),
                "value_payload": value_payload,
                "result_type": _text(row, "result_type"),
                "evidence_ids": _string_list(row.get("evidence_anchor_ids")),
                "structure_feature_ids": _string_list(row.get("structure_feature_ids")),
                "characterization_observation_ids": _string_list(
                    row.get("characterization_observation_ids")
                ),
                "traceability_status": _text(row, "traceability_status"),
                "epistemic_status": _text(row, "epistemic_status"),
                "source": _source("measurement_results", row_number),
            }
        )
    return records


def _convert_comparisons(
    pairwise_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if pairwise_rows:
        return [
            {
                "paper_id": _text(row, "document_id"),
                "comparison_id": _text(row, "relation_id"),
                "current_sample_id": _text(row, "current_variant_id"),
                "baseline_reference": _text(row, "reference_variant_id"),
                "baseline_sample_ids": [_text(row, "reference_variant_id")]
                if _text(row, "reference_variant_id")
                else [],
                "comparison_type": "pairwise_sample_relation",
                "comparison_axis": _text(row, "comparison_axis"),
                "comparison_metric": _text(row, "property_normalized"),
                "metric_name": _text(row, "property_normalized"),
                "current_value": _first_value(row, "current_value"),
                "baseline_value": _first_value(row, "reference_value"),
                "unit": _text(row, "unit"),
                "change_direction": _text(row, "direction"),
                "direction": _text(row, "direction"),
                "result_summary": "",
                "comparability_status": "",
                "comparability_warnings": [],
                "evidence_ids": _string_list(row.get("evidence_anchor_ids")),
                "anchor_ids": _string_list(row.get("evidence_anchor_ids")),
                "relation_payload": _first_value(row, "relation_payload"),
                "source": _source("pairwise_comparison_relations", row_number),
            }
            for row_number, row in _rows_with_numbers(pairwise_rows)
        ]

    if comparison_rows:
        return [
            {
                "paper_id": _text(row, "source_document_id", "document_id"),
                "comparison_id": _text(row, "row_id"),
                "current_sample_id": _text(row, "variant_id"),
                "baseline_reference": _text(row, "baseline_reference"),
                "baseline_sample_ids": [],
                "comparison_type": "projected_comparison_row",
                "comparison_metric": _text(row, "property_normalized"),
                "current_value": _first_value(row, "value"),
                "baseline_value": "",
                "unit": _text(row, "unit"),
                "change_direction": "",
                "result_summary": _text(row, "result_summary"),
                "comparability_status": _text(row, "comparability_status"),
                "comparability_warnings": _string_list(
                    row.get("comparability_warnings")
                ),
                "evidence_ids": _string_list(row.get("supporting_evidence_ids")),
                "anchor_ids": _string_list(row.get("supporting_anchor_ids")),
                "source": _source("comparison_rows", row_number),
            }
            for row_number, row in _rows_with_numbers(comparison_rows)
        ]

    return [
        {
            "paper_id": _text(row, "document_id"),
            "comparison_id": _text(row, "baseline_id"),
            "current_sample_id": "",
            "baseline_reference": _text(row, "baseline_label"),
            "baseline_sample_ids": [_text(row, "variant_id")]
            if _text(row, "variant_id")
            else [],
            "comparison_type": _text(row, "baseline_type"),
            "comparison_metric": "",
            "current_value": "",
            "baseline_value": "",
            "unit": "",
            "change_direction": "",
            "result_summary": "",
            "comparability_status": "",
            "comparability_warnings": [],
            "evidence_ids": _string_list(row.get("evidence_anchor_ids")),
            "anchor_ids": _string_list(row.get("evidence_anchor_ids")),
            "source": _source("baseline_references", row_number),
        }
        for row_number, row in _rows_with_numbers(baseline_rows)
    ]


def _convert_observations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        records.append(
            {
                "paper_id": _text(row, "document_id"),
                "observation_id": _text(row, "observation_id"),
                "sample_id": _text(row, "variant_id"),
                "sample_ids": [_text(row, "variant_id")]
                if _text(row, "variant_id")
                else [],
                "characterization_method": _text(row, "characterization_type"),
                "observed_object": _text(row, "characterization_type"),
                "value_or_description": _first_value(row, "observed_value")
                if _present(_first_value(row, "observed_value"))
                else _text(row, "observation_text"),
                "unit": _text(row, "observed_unit"),
                "author_interpretation": _text(row, "observation_text"),
                "condition_context": _first_value(row, "condition_context"),
                "evidence_ids": _string_list(row.get("evidence_anchor_ids")),
                "confidence": _first_value(row, "confidence"),
                "epistemic_status": _text(row, "epistemic_status"),
                "source": _source("characterization_observations", row_number),
            }
        )
    return records


def _convert_objective_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    samples: dict[str, dict[str, Any]] = {}
    for row in rows:
        sample_context = _dict_value(row.get("sample_context"))
        if not sample_context:
            continue
        document_id = _text(row, "document_id")
        sample_id = _objective_sample_id(document_id, sample_context)
        if not sample_id or sample_id in samples:
            continue
        samples[sample_id] = {
            "paper_id": document_id,
            "sample_id": sample_id,
            "label_in_paper": _objective_sample_label(sample_context),
            "sample_description": _objective_sample_description(sample_context),
            "material_system": _payload_text(
                _dict_value(row.get("material_system")),
                "material",
                "normalized",
                "composition",
            ),
            "host_material_system": _first_value(row, "material_system"),
            "difference_type": "",
            "difference_value": "",
            "is_control_sample": "",
            "evidence_ids": _objective_evidence_ids(row),
            "structure_feature_ids": [],
            "confidence": _first_value(row, "confidence"),
            "epistemic_status": _text(row, "resolution_status"),
            "source": _source("objective_evidence_units", None),
        }
    return list(samples.values())


def _convert_objective_process_parameters(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        process_context = _dict_value(row.get("process_context"))
        sample_context = _dict_value(row.get("sample_context"))
        sample_id = _objective_sample_id(_text(row, "document_id"), sample_context)
        for key, value in process_context.items():
            if not _present(value):
                continue
            records.append(
                {
                    "paper_id": _text(row, "document_id"),
                    "sample_reference": sample_id,
                    "sample_ids": [sample_id] if sample_id else [],
                    "sample_scope": "single_sample" if sample_id else "",
                    "parameter_category": "objective_process_context",
                    "original_parameter_name": key,
                    "parameter_description": key,
                    "value": value,
                    "unit": _infer_process_unit(key),
                    "applies_to": _objective_sample_label(sample_context),
                    "evidence_ids": _objective_evidence_ids(row),
                    "confidence": _first_value(row, "confidence"),
                    "epistemic_status": _text(row, "resolution_status"),
                    "source": _source("objective_evidence_units", row_number),
                }
            )
    return records


def _convert_objective_test_conditions(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        if _text(row, "unit_kind") != "test_condition":
            continue
        payload = _dict_value(row.get("test_condition")) or _dict_value(
            row.get("resolved_condition")
        )
        records.append(
            {
                "paper_id": _text(row, "document_id"),
                "test_condition_id": _text(row, "evidence_unit_id"),
                "sample_reference": "",
                "sample_ids": [],
                "sample_scope": "",
                "test_type": _text(row, "property_normalized")
                or _payload_text(payload, "test_type", "test_method", "method"),
                "test_temperature": _payload_text(payload, "test_temperature_c"),
                "strain_rate_or_frequency": _payload_text(
                    payload,
                    "strain_rate_s-1",
                    "strain_rate",
                    "frequency_hz",
                    "frequency",
                ),
                "build_orientation": _payload_text(payload, "build_orientation"),
                "sampling_orientation": _payload_text(
                    payload,
                    "sample_orientation",
                    "loading_direction",
                ),
                "surface_condition": _payload_text(payload, "surface_condition"),
                "test_standard": _payload_text(payload, "test_standard", "standard"),
                "other_conditions": _remaining_payload(
                    payload,
                    excluded={
                        "test_type",
                        "test_method",
                        "method",
                        "test_temperature_c",
                        "strain_rate_s-1",
                        "strain_rate",
                        "frequency_hz",
                        "frequency",
                        "build_orientation",
                        "sample_orientation",
                        "loading_direction",
                        "surface_condition",
                        "test_standard",
                        "standard",
                    },
                ),
                "condition_payload": payload,
                "condition_completeness": _text(row, "resolution_status"),
                "missing_fields": [],
                "evidence_ids": _objective_evidence_ids(row),
                "confidence": _first_value(row, "confidence"),
                "epistemic_status": _text(row, "resolution_status"),
                "source": _source("objective_evidence_units", row_number),
            }
        )
    return records


def _convert_objective_measurement_results(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        if _text(row, "unit_kind") != "measurement":
            continue
        sample_context = _dict_value(row.get("sample_context"))
        value_payload = _first_value(row, "value_payload")
        records.append(
            {
                "paper_id": _text(row, "document_id"),
                "result_id": _text(row, "evidence_unit_id"),
                "sample_id": _objective_sample_id(_text(row, "document_id"), sample_context),
                "sample_ids": [
                    _objective_sample_id(_text(row, "document_id"), sample_context)
                ]
                if _objective_sample_id(_text(row, "document_id"), sample_context)
                else [],
                "test_condition_id": _objective_test_condition_reference(row),
                "metric_name": _text(row, "property_normalized"),
                "value_or_trend": _summarize_value_payload(value_payload),
                "unit": _text(row, "unit"),
                "claim_scope": "objective",
                "data_source": "objective_evidence_unit",
                "baseline_id": _objective_baseline_reference(row),
                "value_payload": value_payload,
                "result_type": "scalar" if _objective_numeric_value(row) is not None else "",
                "evidence_ids": _objective_evidence_ids(row),
                "structure_feature_ids": [],
                "characterization_observation_ids": [],
                "traceability_status": _text(row, "resolution_status"),
                "epistemic_status": _text(row, "resolution_status"),
                "source": _source("objective_evidence_units", row_number),
            }
        )
    return records


def _convert_objective_comparisons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        if _text(row, "unit_kind") != "comparison":
            continue
        sample_context = _dict_value(row.get("sample_context"))
        baseline_context = _dict_value(row.get("baseline_context"))
        value_payload = _dict_value(row.get("value_payload"))
        current_sample_id = _objective_sample_id(_text(row, "document_id"), sample_context)
        baseline_sample_id = _objective_sample_id(
            _text(row, "document_id"),
            _objective_baseline_sample_context(baseline_context),
        )
        records.append(
            {
                "paper_id": _text(row, "document_id"),
                "comparison_id": _text(row, "evidence_unit_id"),
                "current_sample_id": current_sample_id,
                "baseline_reference": baseline_sample_id
                or _payload_text(baseline_context, "label", "sample", "sample_id"),
                "baseline_sample_ids": [baseline_sample_id]
                if baseline_sample_id
                else [],
                "comparison_type": "objective_evidence_unit",
                "comparison_axis": _payload_text(
                    value_payload,
                    "comparison_axis",
                    "changed_process_axis",
                    "axis",
                ),
                "comparison_metric": _text(row, "property_normalized"),
                "metric_name": _text(row, "property_normalized"),
                "current_value": _first_present_value(
                    value_payload,
                    "current_value",
                    "value",
                ),
                "baseline_value": _first_present_value(
                    baseline_context,
                    "baseline_value",
                    "reference_value",
                    "value",
                ),
                "unit": _text(row, "unit"),
                "change_direction": _payload_text(value_payload, "direction"),
                "direction": _payload_text(value_payload, "direction"),
                "result_summary": _text(row, "interpretation"),
                "comparability_status": _text(row, "resolution_status"),
                "comparability_warnings": [],
                "evidence_ids": _objective_evidence_ids(row),
                "anchor_ids": _objective_evidence_ids(row),
                "relation_payload": value_payload,
                "source": _source("objective_evidence_units", row_number),
            }
        )
    return records


def _convert_objective_observations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        if _text(row, "unit_kind") != "characterization":
            continue
        sample_context = _dict_value(row.get("sample_context"))
        value_payload = _dict_value(row.get("value_payload"))
        records.append(
            {
                "paper_id": _text(row, "document_id"),
                "observation_id": _text(row, "evidence_unit_id"),
                "sample_id": _objective_sample_id(_text(row, "document_id"), sample_context),
                "sample_ids": [
                    _objective_sample_id(_text(row, "document_id"), sample_context)
                ]
                if _objective_sample_id(_text(row, "document_id"), sample_context)
                else [],
                "characterization_method": _text(row, "property_normalized"),
                "observed_object": _text(row, "property_normalized"),
                "value_or_description": _summarize_value_payload(value_payload)
                or _text(row, "interpretation"),
                "unit": _text(row, "unit"),
                "author_interpretation": _text(row, "interpretation"),
                "condition_context": _first_value(row, "resolved_condition"),
                "evidence_ids": _objective_evidence_ids(row),
                "confidence": _first_value(row, "confidence"),
                "epistemic_status": _text(row, "resolution_status"),
                "source": _source("objective_evidence_units", row_number),
            }
        )
    return records


def _convert_objective_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        for source_ref in _normalize_value(row.get("source_refs")) or []:
            if not isinstance(source_ref, dict):
                continue
            evidence_id = _objective_source_ref_id(source_ref)
            if not evidence_id or evidence_id in records_by_id:
                continue
            records_by_id[evidence_id] = {
                "paper_id": _text(row, "document_id"),
                "evidence_id": evidence_id,
                "evidence_type": _text(source_ref, "source_kind"),
                "page": _first_value(source_ref, "page"),
                "section": "",
                "figure_or_table": _text(source_ref, "source_ref"),
                "quote_or_cell": "",
                "supports": _text(row, "evidence_unit_id"),
                "locator_type": _text(source_ref, "source_kind"),
                "locator_confidence": _text(row, "resolution_status"),
                "deep_link": "",
                "block_id": _text(source_ref, "source_ref")
                if _text(source_ref, "source_kind") == "text_window"
                else "",
                "snippet_id": "",
                "source": _source("objective_evidence_units", None),
            }
    return list(records_by_id.values())


def _convert_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        records.append(
            {
                "paper_id": _text(row, "document_id"),
                "evidence_id": _text(row, "anchor_id"),
                "evidence_type": _text(row, "source_type", "locator_type"),
                "page": _first_value(row, "page"),
                "section": _text(row, "section_id"),
                "figure_or_table": _text(row, "figure_or_table"),
                "quote_or_cell": _text(row, "quote", "quote_span"),
                "supports": "",
                "locator_type": _text(row, "locator_type"),
                "locator_confidence": _text(row, "locator_confidence"),
                "deep_link": _text(row, "deep_link"),
                "block_id": _text(row, "block_id"),
                "snippet_id": _text(row, "snippet_id"),
                "source": _source("evidence_anchors", row_number),
            }
        )
    return records


def _raw_records(rows: list[dict[str, Any]], artifact: str) -> list[dict[str, Any]]:
    return [
        {**row, "source": _source(artifact, row_number)}
        for row_number, row in _rows_with_numbers(rows)
    ]


def _objective_sample_id(document_id: str, sample_context: dict[str, Any]) -> str:
    label = _objective_sample_label(sample_context)
    key = _objective_sample_key(sample_context)
    if not key and not label:
        return ""
    suffix = key or label
    return f"obj-sample-{document_id}-{suffix}"


def _objective_sample_label(sample_context: dict[str, Any]) -> str:
    for key in (
        "sample_number",
        "Sample number",
        "Sample Number",
        "ID",
        "Sample ID",
        "sample ID",
        "sample_id",
        "sample",
        "sample_label",
        "label",
    ):
        value = sample_context.get(key)
        if _present(value):
            text = str(value).strip()
            if text.isdigit():
                return f"Sample {int(text)}"
            return text
    for value in sample_context.values():
        candidate = _objective_sample_label_candidate(value)
        if candidate:
            return candidate
    return ""


def _objective_sample_description(sample_context: dict[str, Any]) -> str:
    for key in ("label", "sample_label", "sample"):
        value = sample_context.get(key)
        if _present(value):
            return str(value).strip()
    label = _objective_sample_label(sample_context)
    if label:
        return label
    return json.dumps(sample_context, ensure_ascii=False, sort_keys=True)


def _objective_sample_key(sample_context: dict[str, Any]) -> str:
    label = _objective_sample_label(sample_context)
    if label:
        return label.lower().replace(" ", "-")
    return ""


def _objective_sample_label_candidate(value: Any) -> str:
    if not _present(value):
        return ""
    text = str(value).strip()
    match = re.search(r"\b([LMH])\s*-\s*VED\b", text, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1).upper()}-VED"
    if re.fullmatch(r"wrought\s+316l", text, flags=re.IGNORECASE):
        return "Wrought 316L"
    return ""


def _objective_evidence_ids(row: dict[str, Any]) -> list[str]:
    evidence_ids = _string_list(row.get("evidence_anchor_ids"))
    if evidence_ids:
        return evidence_ids
    source_refs = _normalize_value(row.get("source_refs")) or []
    if not isinstance(source_refs, list):
        return []
    return [
        evidence_id
        for source_ref in source_refs
        if isinstance(source_ref, dict)
        if (evidence_id := _objective_source_ref_id(source_ref))
    ]


def _objective_source_ref_id(source_ref: dict[str, Any]) -> str:
    source_kind = _text(source_ref, "source_kind")
    source_ref_value = _text(source_ref, "source_ref")
    if not source_kind or not source_ref_value:
        return ""
    return f"objective-source:{source_kind}:{source_ref_value}"


def _objective_test_condition_reference(row: dict[str, Any]) -> str:
    test_condition = _dict_value(row.get("test_condition"))
    resolved_condition = _dict_value(row.get("resolved_condition"))
    return (
        _payload_text(test_condition, "test_condition_id", "condition_id")
        or _payload_text(resolved_condition, "test_condition_id", "condition_id")
    )


def _objective_baseline_reference(row: dict[str, Any]) -> str:
    baseline_context = _dict_value(row.get("baseline_context"))
    return _payload_text(
        baseline_context,
        "baseline_id",
        "reference_id",
        "baseline_sample_id",
        "reference_sample_id",
    )


def _objective_baseline_sample_context(
    baseline_context: dict[str, Any],
) -> dict[str, Any]:
    for key in (
        "sample_context",
        "baseline_sample_context",
        "reference_sample_context",
    ):
        value = baseline_context.get(key)
        if isinstance(value, dict):
            return value
    sample_id = _payload_text(
        baseline_context,
        "baseline_sample_id",
        "reference_sample_id",
        "sample_id",
    )
    sample_label = _payload_text(
        baseline_context,
        "baseline_sample_label",
        "reference_sample_label",
        "label",
        "sample",
    )
    return {
        key: value
        for key, value in {
            "sample_id": sample_id,
            "label": sample_label,
        }.items()
        if value
    }


def _objective_numeric_value(row: dict[str, Any]) -> float | None:
    value_payload = _dict_value(row.get("value_payload"))
    for key in ("value", "numeric_value"):
        value = value_payload.get(key)
        if _present(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _first_present_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if _present(value):
            return value
    return ""


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
        converted = value.tolist()
        if converted is not value:
            return _normalize_value(converted)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if (text.startswith("{") and text.endswith("}")) or (
            text.startswith("[") and text.endswith("]")
        ):
            for parser in (json.loads, ast.literal_eval):
                try:
                    return _normalize_value(parser(text))
                except (ValueError, SyntaxError, json.JSONDecodeError, TypeError):
                    continue
        return text
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _json_safe(value: Any) -> Any:
    value = _normalize_value(value)
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _rows_with_numbers(rows: list[dict[str, Any]]):
    yield from enumerate(rows, start=1)


def _source(artifact: str, row_number: int | None) -> dict[str, Any]:
    return {
        "artifact": artifact,
        "row": row_number,
    }


def _document_id(row: dict[str, Any]) -> str:
    return _text(row, "id", "paper_id", "document_id", "source_document_id")


def _document_ids_from_records(groups: list[list[dict[str, Any]]]) -> list[str]:
    values: list[str] = []
    for rows in groups:
        for row in rows:
            document_id = _document_id(row)
            if document_id:
                values.append(document_id)
    return values


def _infer_collection_id(records_by_artifact: dict[str, list[dict[str, Any]]]) -> str | None:
    for records in records_by_artifact.values():
        for row in records:
            collection_id = _text(row, "collection_id")
            if collection_id:
                return collection_id
    return None


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if _present(value):
            return value
    return None


def _text(row: dict[str, Any], *keys: str) -> str:
    value = _first_value(row, *keys)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _string_list(value: Any) -> list[str]:
    value = _normalize_value(value)
    if value is None:
        return []
    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if item is not None and str(item).strip()
        ]
    text = str(value).strip()
    if not text:
        return []
    return [text]


def _dict_value(value: Any) -> dict[str, Any]:
    value = _normalize_value(value)
    if isinstance(value, dict):
        return value
    return {}


def _payload_text(payload: dict[str, Any], *keys: str) -> str:
    return _text(payload, *keys)


def _remaining_payload(payload: dict[str, Any], *, excluded: set[str]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in excluded and _present(value)
    }


def _profile_payload(profile: dict[str, Any]) -> dict[str, Any]:
    return _dict_value(profile.get("profile_payload"))


def _profile_payload_text(profile: dict[str, Any], key: str) -> str:
    return _payload_text(_profile_payload(profile), key)


def _profile_material_system(profile: dict[str, Any]) -> str:
    payload = _profile_payload(profile)
    return _payload_text(payload, "material_system", "materials", "alloy")


def _profile_process_type(profile: dict[str, Any]) -> str:
    payload = _profile_payload(profile)
    return _payload_text(payload, "process_type", "process", "manufacturing_process")


def _material_system_text(row: dict[str, Any]) -> str:
    host = _dict_value(row.get("host_material_system"))
    return (
        _payload_text(host, "composition", "material_system", "family")
        or _text(row, "composition")
    )


def _summarize_value_payload(value: Any) -> Any:
    payload = _normalize_value(value)
    if isinstance(payload, dict):
        for key in ("source_value_text", "summary", "value", "numeric_value"):
            if _present(payload.get(key)):
                return payload[key]
        return payload
    return payload


def _infer_process_unit(name: str) -> str:
    normalized = str(name or "").strip().lower()
    for suffix, unit in PROCESS_UNIT_SUFFIXES:
        if normalized == suffix or normalized.endswith(f"_{suffix}"):
            return unit
    return ""


if __name__ == "__main__":
    main()
