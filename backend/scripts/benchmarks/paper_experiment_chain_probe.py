#!/usr/bin/env python3
"""Run the paper-experiment chain on one fixed real Ti-6Al-4V paper.

This is an opt-in live acceptance probe. It parses the supplied PDF with the
active Docling path and sends every model-backed judgment through the configured
provider. It contains no recorded model response or synthetic scientific fact.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

import pandas as pd
from dotenv import dotenv_values

from _common import (
    DEFAULT_BACKEND_ROOT,
    add_runtime_arguments,
    build_openai_client,
    display_base_url,
    ensure_backend_root_on_path,
    resolve_runtime,
    write_json_output,
)

ensure_backend_root_on_path(DEFAULT_BACKEND_ROOT)

from application.core.document_profiles.extraction import DocumentProfileExtractor
from application.core.document_profiles.service import DocumentProfileService
from application.core.objectives.analysis.diagnostics import capture_analysis_diagnostics
from application.core.objectives.analysis.evidence_materialization import materialize_evidence
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
from application.core.objectives.llm.structured_response import StructuredResponseClient
from application.core.objectives.objective_analysis_service import (
    ObjectiveEvidenceAnalysisService,
)
from application.core.objectives.paper_research_map_service import (
    PaperResearchMapService,
)
from application.core.objectives.discovery.paper_understanding.workflow import (
    PaperResearchMapExtractor,
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
                    ObjectiveEvidenceAnalysisService._document_contexts_for_evidence(
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

    table_text = "\n".join(
        str(table.to_record().get("table_markdown") or "")
        for table in document.tables
        if "relative density" in str(table.caption_text or "").casefold()
    )
    expected_rows_present = [
        {
            "sample": sample,
            "power_w": power,
            "relative_density_percent": density,
            "present": all(
                token in table_text
                for token in (sample, f"{power:g}", f"{density:g}")
            ),
        }
        for sample, power, density in EXPECTED_TABLE_ROWS
    ]
    add(
        "parsed_table_preserves_reviewed_rows",
        bool(table_text) and all(item["present"] for item in expected_rows_present),
        expected_rows_present,
    )
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
    density_evidence = tuple(
        item
        for item in evidence
        if item.source_kind == "table"
        and item.reported_result is not None
        and item.reported_result.outcome.casefold() == "relative density"
    )
    related_lineage_ok = bool(density_evidence) and all(
        item.related_source_refs
        and any(
            str(ref.get("source_kind") or "") == item.source_kind
            and str(ref.get("source_ref") or "") == item.source_ref
            for ref in item.related_source_refs
        )
        for item in density_evidence
    )
    add(
        "source_observations_keep_related_source_lineage",
        related_lineage_ok,
        {
            "observation_count": len(observations),
            "density_evidence_count": len(density_evidence),
            "related_source_ref_counts": [
                len(item.related_source_refs) for item in density_evidence
            ],
            "source_refs": sorted(
                {
                    (item.source_kind, item.source_ref)
                    for item in observations
                }
            ),
        },
    )
    density_measurements = [
        item
        for experiment in experiments
        for item in experiment.measurements
        if isinstance(item.value_payload.get("value"), (int, float))
        and item.property_normalized.casefold() == "relative density"
    ]
    measurement_values = sorted(float(item.value_payload["value"]) for item in density_measurements)
    expected_values = sorted(density for _, _, density in EXPECTED_TABLE_ROWS)
    table_result_observations = [
        item
        for item in observations
        if item.source_kind == "table"
        and not item.derived_from_observation_ids
        and item.reported_result is not None
        and item.reported_result.outcome.casefold() == "relative density"
        and isinstance(item.reported_result.value, (int, float))
    ]
    add(
        "paper_experiment_binds_samples_tests_and_measurements",
        measurement_values == expected_values
        and len(table_result_observations) == len(EXPECTED_TABLE_ROWS)
        and any(experiment.sample_variants for experiment in experiments)
        and any(experiment.test_conditions for experiment in experiments)
        and all(
            item.variant_id is not None and item.test_condition_id is not None
            for item in density_measurements
        ),
        {
            "expected_measurements": expected_values,
            "actual_measurements": measurement_values,
            "table_result_count": len(table_result_observations),
            "statuses": [item.status for item in experiments],
            "sample_variant_count": sum(len(item.sample_variants) for item in experiments),
            "test_condition_count": sum(len(item.test_conditions) for item in experiments),
        },
    )
    comparable_observations = [
        item
        for experiment in experiments
        for item in experiment.source_observations
        if item.derived_from_observation_ids
        and item.reported_result is not None
        and item.reported_result.outcome.casefold() == "relative density"
        and experiment.comparison_status(
            _objective(document.document_id), *item.derived_from_observation_ids
        )
        == "comparable"
    ]
    expected_strategy_comparison_counts = {
        "Speed": 1,
        "Intermediate": 2,
        "Performance": 2,
    }
    comparison_strategies = [
        next(
            (
                str(attribute.value)
                for attribute in item.scientific_context.sample
                if attribute.name.casefold() == "strategy"
            ),
            "",
        )
        for item in comparable_observations
    ]
    strategy_counts = _count(comparison_strategies)
    add(
        "comparisons_change_only_laser_power",
        len(comparable_observations) == sum(expected_strategy_comparison_counts.values())
        and strategy_counts == expected_strategy_comparison_counts
        and all(
            {variable.name.casefold() for variable in item.changed_variables}
            == {"laser power"}
            for item in comparable_observations
        ),
        [item.to_record() for item in comparable_observations],
    )
    add(
        "objective_evidence_is_source_traceable",
        bool(evidence)
        and any(item.evidence_status == "comparable" for item in evidence)
        and all(item.source_ref and item.related_source_refs for item in evidence),
        {
            "count": len(evidence),
            "status_counts": _count(item.evidence_status for item in evidence),
        },
    )
    evidence_ids = {item.evidence_id for item in evidence}
    finding_evidence_ids = {
        evidence_id
        for finding in findings
        for contribution in finding.paper_contributions
        for evidence_id in (
            *contribution.supporting_evidence_ids,
            *contribution.contradicting_evidence_ids,
            *contribution.context_evidence_ids,
            *contribution.condition_boundary_evidence_ids,
        )
    }
    finding_required = comparable_evidence_count > 0
    add(
        "finding_preserves_published_evidence_lineage",
        (
            not finding_required
            or (
                bool(findings)
                and bool(finding_evidence_ids)
                and finding_evidence_ids <= evidence_ids
            )
        ),
        {
            "finding_required": finding_required,
            "finding_count": len(findings),
            "finding_evidence_ids": sorted(finding_evidence_ids),
            "disposition": (
                "validated_with_comparable_evidence"
                if finding_required
                else "not_required_without_comparable_evidence"
            ),
        },
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
