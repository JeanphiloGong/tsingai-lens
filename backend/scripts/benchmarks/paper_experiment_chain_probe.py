#!/usr/bin/env python3
"""Run the paper-experiment chain on one fixed real Ti-6Al-4V paper.

This is an opt-in live acceptance probe. It parses the supplied PDF with the
active Docling path and sends every model-backed judgment through the configured
provider. It contains no recorded model response or synthetic scientific fact.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

import pandas as pd
from _common import (
    DEFAULT_BACKEND_ROOT,
    add_runtime_arguments,
    build_openai_client,
    display_base_url,
    ensure_backend_root_on_path,
    resolve_runtime,
    write_json_output,
)
from dotenv import dotenv_values

ensure_backend_root_on_path(DEFAULT_BACKEND_ROOT)

from application.core.document_profiles.extraction import DocumentProfileExtractor
from application.core.document_profiles.service import DocumentProfileService
from application.core.objectives.analysis.diagnostics import (
    capture_analysis_diagnostics,
)
from application.core.objectives.analysis.evidence_materialization import (
    materialize_evidence,
)
from application.core.objectives.analysis.evidence_routing import route_sources
from application.core.objectives.analysis.finding_synthesis import (
    FindingAssertionJudge,
    FindingSynthesisService,
)
from application.core.objectives.analysis.paper_experiment import (
    assemble_paper_experiments,
    reconstruct_paper_experiments,
)
from application.core.objectives.analysis.source_extraction import (
    ObjectiveSourceExtractor,
    extract_and_validate_source_facts,
)
from application.core.objectives.analysis.source_screening import (
    ObjectiveSourceScreener,
    screen_sources,
)
from application.core.objectives.discovery.paper_understanding.workflow import (
    PaperResearchMapExtractor,
)
from application.core.objectives.llm.structured_response import StructuredResponseClient
from application.core.objectives.objective_analysis_service import (
    ObjectiveExperimentAnalysisService,
)
from application.core.objectives.paper_research_map_service import (
    PaperResearchMapService,
)
from application.core.paper_facts.extraction import PaperFactsExtractor
from domain.core import (
    DocumentProfile,
    ObjectiveAnalysis,
    PreparedDocumentInput,
    ResearchObjective,
)
from infra.llm.usage import capture_llm_usage
from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.runtime.parsers.docling_pdf import (
    build_pdf_bundle,
    build_pdf_converter,
)

SCENARIO_ID = "cao-2017-ti64-density"
EXPECTED_PDF_SHA256 = "c5b1a451f081444414c2766efd13c8119af4b5722ce549ad4d64b0b7dfedfef9"
# These are source-grounded acceptance invariants from the pinned PDF, not
# model responses. The probe still obtains the table and every interpretation
# from the live Docling/provider path before comparing against them.
EXPECTED_TABLE_ROWS = (
    ("S1", 900.0, 98.0),
    ("S", 1000.0, 98.5),
    ("M1", 700.0, 98.5),
    ("M", 800.0, 99.2),
    ("M2", 850.0, 99.1),
    ("P", 350.0, 99.6),
    ("P1", 400.0, 99.5),
    ("P2", 500.0, 98.7),
)


class RecordingStructuredResponseClient(StructuredResponseClient):
    """Retain each production response trace during this one live probe."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.traces: list[dict[str, Any]] = []
        self._trace_lock = Lock()

    def complete(self, **kwargs: Any) -> Any:
        try:
            return super().complete(**kwargs)
        finally:
            trace = self.peek_last_trace()
            if trace:
                with self._trace_lock:
                    self.traces.append(deepcopy(trace))


class RecordingPaperFactsExtractor(PaperFactsExtractor):
    """Retain every table-repair trace instead of only the latest call."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.traces: list[dict[str, Any]] = []

    def repair_table_matrix(self, payload: dict[str, Any]) -> Any:
        try:
            return super().repair_table_matrix(payload)
        finally:
            if self.last_trace:
                self.traces.append(deepcopy(self.last_trace))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf",
        type=Path,
        required=True,
        help="The fixed Cao 2017 Ti-6Al-4V PDF; its SHA-256 is verified.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        required=True,
        help="JSON report path. The report includes prompts, outputs, and lineage.",
    )
    parser.add_argument(
        "--extraction-mode",
        choices=("json_text", "provider_parse"),
        help="Core structured-output mode; defaults to env or production default.",
    )
    add_runtime_arguments(
        parser,
        include_temperature=False,
        include_max_completion_tokens=False,
        default_timeout_s=300.0,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime = resolve_runtime(args, allow_placeholder_api_key=False)
    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")
    pdf_bytes = pdf_path.read_bytes()
    source_hash = sha256(pdf_bytes).hexdigest()
    if source_hash != EXPECTED_PDF_SHA256:
        raise SystemExit(
            "Unexpected PDF content. The live probe is pinned to the reviewed "
            f"Cao 2017 source hash {EXPECTED_PDF_SHA256}; received {source_hash}."
        )

    env_values = (
        dotenv_values(runtime.env_file) if runtime.env_file is not None else {}
    )
    extraction_mode = (
        args.extraction_mode
        or str(env_values.get("CORE_LLM_EXTRACTION_MODE") or "").strip()
        or "provider_parse"
    )
    report: dict[str, Any] = {
        "script": Path(__file__).name,
        "scenario_id": SCENARIO_ID,
        "status": "running",
        "stage": "source_parsing",
        "input": {
            "pdf": str(pdf_path),
            "sha256": source_hash,
            "expected_sha256": EXPECTED_PDF_SHA256,
        },
        "runtime": {
            "model": runtime.model,
            "base_url": display_base_url(runtime.base_url),
            "timeout_s": runtime.timeout_s,
            "reasoning_effort": runtime.reasoning_effort,
            "extraction_mode": extraction_mode,
        },
        "boundary": (
            "Real PDF, active Docling parser, and configured live model. The "
            "research Objective is fixed as researcher input; no model output or "
            "scientific result is scripted. No database writes are performed."
        ),
    }
    write_json_output(args.summary_output, report)
    started_at = perf_counter()
    response_client: RecordingStructuredResponseClient | None = None
    profile_extractor: DocumentProfileExtractor | None = None
    paper_facts_extractor: RecordingPaperFactsExtractor | None = None
    profile_trace: dict[str, Any] | None = None
    usage = None
    diagnostics = None
    try:
        document = _parse_pdf(
            backend_root=runtime.backend_root,
            pdf_path=pdf_path,
            pdf_bytes=pdf_bytes,
        )
        report["source"] = _source_payload(document)
        report["stage"] = "live_analysis"
        write_json_output(args.summary_output, report)

        client = build_openai_client(runtime)
        response_client = RecordingStructuredResponseClient(
            client=client,
            model=runtime.model,
            extraction_mode=extraction_mode,
        )
        response_client.reasoning_effort = runtime.reasoning_effort
        profile_extractor = DocumentProfileExtractor(
            client=client,
            model=runtime.model,
            extraction_mode="json_text",
        )
        profile_extractor.reasoning_effort = runtime.reasoning_effort
        paper_facts_extractor = RecordingPaperFactsExtractor(
            client=client,
            model=runtime.model,
            extraction_mode=extraction_mode,
        )
        paper_facts_extractor.reasoning_effort = runtime.reasoning_effort

        with capture_llm_usage() as usage, capture_analysis_diagnostics() as diagnostics:
            profile = _build_live_profile(
                document=document,
                source_filename=pdf_path.name,
                extractor=profile_extractor,
            )
            profile_trace = profile_extractor.consume_last_trace()
            paper_map = PaperResearchMapService().build_document_paper_map(
                "col-live-ti64",
                document=document,
                profile=profile,
                document_tree=None,
                paper_map_extractor=PaperResearchMapExtractor(response_client),
            )
            objective = _objective(document.document_id)
            analysis = ObjectiveAnalysis(
                collection_id=objective.collection_id,
                objective_id=objective.objective_id,
                analysis_version=1,
                document_inputs=(
                    PreparedDocumentInput(
                        document_id=document.document_id,
                        preparation_fingerprint=source_hash,
                    ),
                ),
                pipeline_version="paper-experiment-live-probe.v1",
                model_name=runtime.model,
                prompt_versions={},
                status="running",
                phase="finding_synthesis",
                total_document_count=1,
            )
            blocks_by_document_id = {document.document_id: list(document.blocks)}
            tables_by_document_id = {document.document_id: list(document.tables)}
            figures_by_document_id = {document.document_id: list(document.figures)}
            table_cells_by_document_id = {
                document.document_id: list(document.table_cells)
            }
            frames = screen_sources(
                collection_id=objective.collection_id,
                source_screener=ObjectiveSourceScreener(response_client),
                objectives=(objective,),
                paper_maps=(paper_map,),
                documents=(document,),
                profiles_by_document_id={document.document_id: profile},
                blocks_by_document_id=blocks_by_document_id,
                tables_by_document_id=tables_by_document_id,
                document_trees_by_document_id={},
            )
            routes = route_sources(
                collection_id=objective.collection_id,
                objectives=(objective,),
                objective_paper_frames=frames,
                blocks_by_document_id=blocks_by_document_id,
                tables_by_document_id=tables_by_document_id,
                document_trees_by_document_id={},
            )
            read_audits = []
            extracted = extract_and_validate_source_facts(
                collection_id=objective.collection_id,
                read_audits=read_audits,
                source_extractor=ObjectiveSourceExtractor(response_client),
                paper_facts_extractor=paper_facts_extractor,
                objectives=(objective,),
                objective_paper_frames=frames,
                objective_evidence_routes=routes,
                blocks_by_document_id=blocks_by_document_id,
                tables_by_document_id=tables_by_document_id,
                figures_by_document_id=figures_by_document_id,
                document_trees_by_document_id={},
                table_cells_by_document_id=table_cells_by_document_id,
            )
            reconstructed = reconstruct_paper_experiments(
                collection_id=objective.collection_id,
                source_facts=extracted,
                objectives=(objective,),
                document_contexts=(
                    ObjectiveExperimentAnalysisService._document_contexts_for_experiments(
                        blocks_by_document_id=blocks_by_document_id,
                        tables_by_document_id=tables_by_document_id,
                        figures_by_document_id=figures_by_document_id,
                    )
                ),
            )
            experiments = assemble_paper_experiments(
                collection_id=objective.collection_id,
                document_id=document.document_id,
                source_facts=reconstructed,
            )
            evidence, contributions = materialize_evidence(
                collection_id=objective.collection_id,
                analysis=analysis,
                objective=objective,
                experiments=experiments,
                technical_audits=tuple(read_audits),
                paper_maps=(paper_map,),
                frames=frames,
                routes=routes,
                blocks_by_document_id=blocks_by_document_id,
                tables_by_document_id=tables_by_document_id,
                figures_by_document_id=figures_by_document_id,
                document_trees_by_document_id={},
            )
            report.update(
                {
                    "stage": "finding_synthesis",
                    "profile": profile.to_record(),
                    "paper_map": paper_map.to_record(),
                    "objective": objective.to_record(),
                    "frames": [item.to_record() for item in frames],
                    "routes": [item.to_record() for item in routes],
                    "source_read_audits": [
                        _source_read_audit_record(item) for item in read_audits
                    ],
                    "source_observations": [
                        item.to_record() for item in reconstructed
                    ],
                    "paper_experiments": [
                        item.to_record() for item in experiments
                    ],
                    "objective_evidence": [item.to_record() for item in evidence],
                    "paper_contributions": [
                        item.to_record() for item in contributions
                    ],
                    "model_traces": {
                        "document_profile": [profile_trace] if profile_trace else [],
                        "objective_pipeline": response_client.traces,
                        "table_repair": deepcopy(paper_facts_extractor.traces),
                    },
                }
            )
            write_json_output(args.summary_output, report)
            findings = FindingSynthesisService(
                assertion_judge=FindingAssertionJudge(response_client)
            ).synthesize(
                collection_id=objective.collection_id,
                objective=objective,
                analysis=analysis,
                contributions=contributions,
                evidence_records=evidence,
            )

        elapsed_s = perf_counter() - started_at
        execution_stats = usage.execution_stats(
            duration_ms=round(elapsed_s * 1000)
        ).to_record()
        report.update(
            {
                "profile": profile.to_record(),
                "paper_map": paper_map.to_record(),
                "objective": objective.to_record(),
                "frames": [item.to_record() for item in frames],
                "routes": [item.to_record() for item in routes],
                "source_read_audits": [
                    _source_read_audit_record(item) for item in read_audits
                ],
                "source_observations": [item.to_record() for item in reconstructed],
                "paper_experiments": [item.to_record() for item in experiments],
                "objective_evidence": [item.to_record() for item in evidence],
                "paper_contributions": [item.to_record() for item in contributions],
                "findings": [item.to_record() for item in findings],
                "diagnostics": list(diagnostics.records),
                "execution_stats": execution_stats,
                "model_traces": {
                    "document_profile": [profile_trace] if profile_trace else [],
                    "objective_pipeline": response_client.traces,
                    "table_repair": paper_facts_extractor.traces,
                },
            }
        )
        report["checks"] = _acceptance_checks(
            report=report,
            document=document,
            profile=profile,
            paper_map=paper_map,
            routes=routes,
            audits=read_audits,
            observations=reconstructed,
            experiments=experiments,
            evidence=evidence,
            findings=findings,
        )
        report["status"] = (
            "pass" if all(item["passed"] for item in report["checks"]) else "fail"
        )
        report["stage"] = "completed"
    except Exception as exc:
        if usage is not None:
            report["execution_stats"] = usage.execution_stats(
                duration_ms=round((perf_counter() - started_at) * 1000)
            ).to_record()
        if diagnostics is not None:
            report["diagnostics"] = list(diagnostics.records)
        if response_client is not None:
            report["model_traces"] = {
                "document_profile": [
                    profile_trace or profile_extractor.last_trace
                ] if profile_trace or (
                    profile_extractor is not None and profile_extractor.last_trace
                ) else [],
                "objective_pipeline": response_client.traces,
                "table_repair": paper_facts_extractor.traces
                if paper_facts_extractor is not None
                else [],
            }
        report.update(
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "elapsed_s": round(perf_counter() - started_at, 3),
            }
        )
        write_json_output(args.summary_output, report)
        raise

    write_json_output(args.summary_output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "summary_output": str(args.summary_output.expanduser().resolve()),
                "request_count": sum(
                    item.get("request_count", 0)
                    for item in report["execution_stats"].get("model_usage", [])
                ),
                "source_observation_count": len(report["source_observations"]),
                "paper_experiment_count": len(report["paper_experiments"]),
                "objective_evidence_count": len(report["objective_evidence"]),
                "finding_count": len(report["findings"]),
                "failed_checks": [
                    item["name"] for item in report["checks"] if not item["passed"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "pass" else 1


def _parse_pdf(*, backend_root: Path, pdf_path: Path, pdf_bytes: bytes):
    document_id = f"paper_{sha256(pdf_bytes).hexdigest()[:12]}"
    bundle = build_pdf_bundle(
        row=pd.Series(
            {
                "id": document_id,
                "title": pdf_path.name,
                "source_path": str(pdf_path),
                "source_type": "pdf",
                "metadata": {"benchmark_scenario": SCENARIO_ID},
            }
        ),
        payload=pdf_bytes,
        config=SourceRuntimeConfig(root_dir=str(backend_root)),
        converter=build_pdf_converter(),
    )
    documents = bundle.to_documents()
    if len(documents) != 1:
        raise RuntimeError(f"expected one parsed document, received {len(documents)}")
    return documents[0]


def _build_live_profile(*, document: Any, source_filename: str, extractor: Any):
    # Reuse the production selection rules without invoking persistence services.
    profile_service = object.__new__(DocumentProfileService)
    payload = profile_service._build_document_profile_payload(
        title=document.title,
        source_filename=source_filename,
        full_text=document.text,
        blocks=list(document.blocks),
    )
    extracted = extractor.extract_document_profile(payload)
    return DocumentProfile.from_mapping(
        {
            "document_id": document.document_id,
            "title": document.title,
            "doc_type": extracted.doc_type,
            "profile_warnings": extracted.profile_warnings,
            "confidence": extracted.confidence,
        }
    )


def _objective(document_id: str) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "col-live-ti64",
            "objective_id": "obj-cao-laser-power-density",
            "question": (
                "Within each reported SLM strategy for Ti-6Al-4V, how does laser "
                "power affect relative density when the other listed process "
                "parameters are fixed?"
            ),
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["relative density"],
            "constraints": [
                "Compare rows only within the same reported SLM strategy.",
                "Layer thickness, scan speed, and hatch spacing must match within a comparison.",
                "Do not pool Speed, Intermediate, and Performance strategies.",
            ],
            "requested_comparator": "lower versus higher laser power within one strategy",
            "seed_document_ids": [document_id],
            "confidence": 1.0,
            "reason": "Fixed researcher-defined live acceptance question for Cao 2017 Table II.",
            "confirmation_status": "confirmed",
        }
    )


def _source_payload(document: Any) -> dict[str, Any]:
    return {
        "document_id": document.document_id,
        "title": document.title,
        "text_chars": len(document.text),
        "block_count": len(document.blocks),
        "table_count": len(document.tables),
        "table_cell_count": len(document.table_cells),
        "tables": [table.to_record() for table in document.tables],
    }


def _table_fact_fidelity_check(document: Any) -> dict[str, Any]:
    density_tables = tuple(
        table
        for table in document.tables
        if "relative density" in str(table.caption_text or "").casefold()
    )
    headers = tuple(
        str(header).strip()
        for table in density_tables
        for header in table.column_headers
    )
    rows = tuple(row for table in density_tables for row in table.table_matrix)

    def reviewed_row(sample: str, power: float, density: float) -> dict[str, Any]:
        sample_key = "".join(character for character in sample.casefold() if character.isalnum())
        power_text = f"{power:g}"
        density_text = f"{density:g}"
        matched_row = next(
            (
                list(row)
                for row in rows
                if row
                and (
                    (first_key := "".join(
                        character
                        for character in str(row[0]).casefold()
                        if character.isalnum()
                    ))
                    == sample_key
                    or first_key.endswith(sample_key)
                )
                and power_text in row
                and density_text in row
            ),
            None,
        )
        return {
            "sample": sample,
            "power_w": power,
            "relative_density_percent": density,
            "matched_row": matched_row,
        }

    reviewed_rows = [reviewed_row(*row) for row in EXPECTED_TABLE_ROWS]
    normalized_headers = tuple(" ".join(header.casefold().split()) for header in headers)
    power_header_present = any("p (w)" in header for header in normalized_headers)
    density_header_present = any(
        "relative density" in header and "%" in header
        for header in normalized_headers
    )
    return {
        "acceptance_target": "A_table_fact_fidelity",
        "name": "table_preserves_reviewed_headers_units_and_rows",
        "passed": bool(density_tables)
        and power_header_present
        and density_header_present
        and all(item["matched_row"] is not None for item in reviewed_rows),
        "detail": {
            "headers": list(headers),
            "power_header_present": power_header_present,
            "density_percent_header_present": density_header_present,
            "reviewed_rows": reviewed_rows,
        },
    }


def _experiment_binding_check(
    *,
    observations: Any,
    experiments: Any,
    evidence: Any,
) -> dict[str, Any]:
    expected_values = sorted(density for _, _, density in EXPECTED_TABLE_ROWS)
    evidence_by_id = {item.evidence_id: item for item in evidence}
    derived_ids = {
        observation.observation_id
        for experiment in experiments
        for observation in experiment.source_observations
        if observation.derived_from_observation_ids
    }
    binding_rows: list[dict[str, Any]] = []
    for experiment in experiments:
        variants = {item.variant_id for item in experiment.sample_variants}
        conditions = {
            item.test_condition_id for item in experiment.test_conditions
        }
        source_ids = {
            item.observation_id for item in experiment.source_observations
        }
        for measurement in experiment.measurements:
            if (
                not isinstance(measurement.value_payload.get("value"), (int, float))
                or measurement.property_normalized.casefold() != "relative density"
            ):
                continue
            projected = evidence_by_id.get(measurement.result_id)
            sample_bound = measurement.variant_id in variants
            test_bound = measurement.test_condition_id in conditions
            fully_bound = bool(sample_bound and test_bound)
            source_lineage_bound = bool(
                projected is not None
                and projected.source_ref
                and any(
                    str(ref.get("source_kind") or "") == projected.source_kind
                    and str(ref.get("source_ref") or "") == projected.source_ref
                    for ref in projected.related_source_refs
                )
            )
            binding_rows.append(
                {
                    "measurement_id": measurement.result_id,
                    "value": float(measurement.value_payload["value"]),
                    "unit": measurement.unit,
                    "source_observation_bound": measurement.result_id in source_ids,
                    "source_lineage_bound": source_lineage_bound,
                    "sample_bound": sample_bound,
                    "test_bound": test_bound,
                    "derived_measurement": measurement.result_id in derived_ids,
                    "experiment_status": experiment.status,
                    "evidence_status": (
                        projected.evidence_status if projected is not None else None
                    ),
                    "selection_status": (
                        projected.selection_status if projected is not None else None
                    ),
                    "resolution_status": (
                        projected.resolution_status if projected is not None else None
                    ),
                    "binding_disposition": (
                        "complete" if fully_bound else "needs_context"
                    ),
                }
            )
    measurement_values = sorted(item["value"] for item in binding_rows)
    table_result_observations = tuple(
        item
        for item in observations
        if item.source_kind == "table"
        and not item.derived_from_observation_ids
        and item.reported_result is not None
        and item.reported_result.outcome.casefold() == "relative density"
        and isinstance(item.reported_result.value, (int, float))
    )
    bindings_are_honest = all(
        item["source_observation_bound"]
        and item["source_lineage_bound"]
        and item["sample_bound"]
        and not item["derived_measurement"]
        and item["unit"] == "%"
        and (
            item["test_bound"]
            or (
                item["experiment_status"] == "incomplete"
                and item["evidence_status"] == "needs_context"
                and item["selection_status"] == "candidate"
                and item["resolution_status"] == "unresolved"
            )
        )
        for item in binding_rows
    )
    return {
        "acceptance_target": "B_experiment_binding",
        "name": "measurements_have_valid_or_explicitly_incomplete_bindings",
        "passed": measurement_values == expected_values
        and len(table_result_observations) == len(EXPECTED_TABLE_ROWS)
        and bindings_are_honest,
        "detail": {
            "expected_measurements": expected_values,
            "actual_measurements": measurement_values,
            "table_result_count": len(table_result_observations),
            "binding_rows": binding_rows,
            "binding_complete": bool(binding_rows)
            and all(item["binding_disposition"] == "complete" for item in binding_rows),
        },
    }


def _comparison_eligibility_check(
    *,
    document_id: str,
    experiments: Any,
    evidence: Any,
    findings: Any,
) -> dict[str, Any]:
    objective = _objective(document_id)
    evidence_by_id = {item.evidence_id: item for item in evidence}
    comparison_rows: list[dict[str, Any]] = []
    for experiment in experiments:
        for observation in experiment.source_observations:
            if (
                not observation.derived_from_observation_ids
                or observation.reported_result is None
                or observation.reported_result.outcome.casefold()
                != "relative density"
            ):
                continue
            comparison_status = experiment.comparison_status(
                objective, *observation.derived_from_observation_ids
            )
            projected = evidence_by_id.get(observation.observation_id)
            strategy = next(
                (
                    str(attribute.value)
                    for attribute in observation.scientific_context.sample
                    if attribute.name.casefold() == "strategy"
                ),
                "",
            )
            evidence_status = (
                projected.evidence_status if projected is not None else None
            )
            synthesis_eligible = bool(
                projected is not None
                and FindingSynthesisService.is_synthesizable_result_evidence(
                    objective, projected
                )
            )
            comparison_rows.append(
                {
                    "observation_id": observation.observation_id,
                    "parent_measurement_ids": list(
                        observation.derived_from_observation_ids
                    ),
                    "strategy": strategy,
                    "changed_variables": [
                        variable.name for variable in observation.changed_variables
                    ],
                    "comparison_status": comparison_status,
                    "evidence_status": evidence_status,
                    "synthesis_eligible": synthesis_eligible,
                }
            )
    expected_strategy_counts = {"Speed": 1, "Intermediate": 2, "Performance": 2}
    strategy_counts = _count(item["strategy"] for item in comparison_rows)
    comparison_shapes_are_preserved = (
        strategy_counts == expected_strategy_counts
        and all(
            {name.casefold() for name in item["changed_variables"]}
            == {"laser power"}
            for item in comparison_rows
        )
    )
    eligibility_is_consistent = all(
        (
            item["evidence_status"] == "comparable"
            and item["synthesis_eligible"]
        )
        if item["comparison_status"] == "comparable"
        else (
            item["evidence_status"] != "comparable"
            and not item["synthesis_eligible"]
        )
        for item in comparison_rows
    )
    comparable_evidence_ids = {
        item.evidence_id
        for item in evidence
        if item.evidence_status == "comparable"
        and FindingSynthesisService.is_synthesizable_result_evidence(
            objective, item
        )
    }
    finding_claim_evidence_ids = {
        evidence_id
        for finding in findings
        for contribution in finding.paper_contributions
        for evidence_id in (
            *contribution.supporting_evidence_ids,
            *contribution.contradicting_evidence_ids,
        )
    }
    finding_lineage_is_consistent = (
        finding_claim_evidence_ids <= comparable_evidence_ids
        and (bool(findings) if comparable_evidence_ids else not findings)
    )
    return {
        "acceptance_target": "C_comparison_eligibility",
        "name": "comparisons_and_findings_require_complete_bindings",
        "passed": bool(comparison_rows)
        and comparison_shapes_are_preserved
        and eligibility_is_consistent
        and finding_lineage_is_consistent,
        "detail": {
            "comparison_rows": comparison_rows,
            "strategy_counts": strategy_counts,
            "comparable_evidence_ids": sorted(comparable_evidence_ids),
            "finding_claim_evidence_ids": sorted(finding_claim_evidence_ids),
            "finding_count": len(findings),
        },
    }


def _acceptance_checks(
    *,
    report: dict[str, Any],
    document: Any,
    profile: Any,
    paper_map: Any,
    routes: Any,
    audits: Any,
    observations: Any,
    experiments: Any,
    evidence: Any,
    findings: Any,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    checks.append(_table_fact_fidelity_check(document))
    add(
        "live_profile_classifies_primary_experiment",
        profile.doc_type == "experimental",
        profile.to_record(),
    )
    add(
        "live_paper_map_retains_current_work",
        paper_map.doc_role == "experimental"
        and any(study.claim_scope == "current_work" for study in paper_map.studies),
        {
            "doc_role": paper_map.doc_role,
            "map_status": paper_map.map_status,
            "study_count": len(paper_map.studies),
        },
    )
    comparable_evidence_count = sum(
        item.evidence_status == "comparable" for item in evidence
    )
    checks.append(
        _live_model_boundary_check(
            report=report, comparable_evidence_count=comparable_evidence_count
        )
    )
    add(
        "screening_routes_real_sources",
        any(route.extractable and route.source_kind == "table" for route in routes),
        [route.to_record() for route in routes],
    )
    result_source_keys = {
        (item.source_kind, item.source_ref)
        for item in observations
        if item.reported_result is not None
        and item.source_kind == "table"
        and item.reported_result.outcome.casefold() == "relative density"
    }
    result_audits = [
        audit
        for audit in audits
        if (audit.source_kind, audit.source_ref) in result_source_keys
    ]
    add(
        "result_source_reads_have_no_technical_failure",
        bool(result_source_keys)
        and not any(audit.failed for audit in result_audits),
        {
            "result_source_keys": sorted(result_source_keys),
            "audits": [_source_read_audit_record(audit) for audit in result_audits],
            "irrelevant_source_failures": [
                _source_read_audit_record(audit)
                for audit in audits
                if audit.failed and audit not in result_audits
            ],
        },
    )
    checks.append(
        _experiment_binding_check(
            observations=observations,
            experiments=experiments,
            evidence=evidence,
        )
    )
    checks.append(
        _comparison_eligibility_check(
            document_id=document.document_id,
            experiments=experiments,
            evidence=evidence,
            findings=findings,
        )
    )
    return checks


def _live_model_boundary_check(
    *, report: dict[str, Any], comparable_evidence_count: int
) -> dict[str, Any]:
    stats = report["execution_stats"]
    prompt_versions = stats.get("prompt_versions", {})
    required_tasks = {
        "document_profile",
        "paper_map",
        "objective_paper_frame",
        "objective_evidence_extraction",
    }
    if comparable_evidence_count:
        required_tasks.add("finding_synthesis")
    # A registered task without a trace is also an incomplete live run.
    required_tasks.update(prompt_versions)
    expected_model = str(report["runtime"]["model"])
    traces = [
        (group, index, trace)
        for group, group_traces in report.get("model_traces", {}).items()
        if isinstance(group_traces, list)
        for index, trace in enumerate(group_traces)
    ]
    invalid_traces = [
        {"group": group, "index": index, "task_type": trace.get("task_type")}
        if isinstance(trace, dict)
        else {"group": group, "index": index, "task_type": None}
        for group, index, trace in traces
        if not isinstance(trace, dict)
        or trace.get("trace_status") != "available"
        or str(trace.get("model") or "") != expected_model
        or not str(trace.get("raw_output") or "").strip()
    ]
    live_tasks = {
        str(trace["task_type"])
        for _, _, trace in traces
        if isinstance(trace, dict)
        and trace.get("task_type")
        and trace.get("trace_status") == "available"
        and str(trace.get("model") or "") == expected_model
        and str(trace.get("raw_output") or "").strip()
    }
    model_usage = stats.get("model_usage", [])
    request_count = sum(item.get("request_count", 0) for item in model_usage)
    usage_complete = (
        stats.get("unreported_request_count") == 0
        and bool(model_usage)
        and all(
            item.get("model_name") == expected_model
            and item.get("unreported_request_count") == 0
            for item in model_usage
        )
        and request_count >= len(traces)
    )
    return {
        "name": "all_scientific_model_boundaries_used_live_provider",
        "passed": bool(
            required_tasks <= set(prompt_versions)
            and required_tasks <= live_tasks
            and traces
            and not invalid_traces
            and usage_complete
        ),
        "detail": {
            "required": sorted(required_tasks),
            "observed": sorted(prompt_versions),
            "live_trace_tasks": sorted(live_tasks),
            "invalid_traces": invalid_traces,
            "request_count": request_count,
            "recorded_trace_count": len(traces),
            "unreported_request_count": stats.get("unreported_request_count"),
            "model_usage": model_usage,
        },
    }


def _count(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def _source_read_audit_record(audit: Any) -> dict[str, Any]:
    return {
        "collection_id": audit.collection_id,
        "objective_id": audit.objective_id,
        "document_id": audit.document_id,
        "source_kind": audit.source_kind,
        "source_ref": audit.source_ref,
        "disposition": audit.disposition,
        "reason": audit.reason,
        "role": audit.role,
        "context_fields": list(audit.context_fields),
    }


if __name__ == "__main__":
    raise SystemExit(main())
