#!/usr/bin/env python3
"""Run the PaperExperiment chain against a manifest of real papers.

This is an opt-in, read-only live acceptance probe.  Each case supplies a real
PDF and a researcher-defined Objective.  All model-backed judgments go through
the configured provider; no scientific answer or model response is recorded in
the script.  The probe is intentionally separate from production orchestration
so it can compare experimental papers, reviews, and incomplete documents
without changing collection state.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
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

ensure_backend_root_on_path(DEFAULT_BACKEND_ROOT)

from application.core.document_profiles.extraction import DocumentProfileExtractor
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
from application.core.objectives.objective_analysis_service import (
    ObjectiveExperimentAnalysisService,
)
from application.core.objectives.paper_research_map_service import (
    PaperResearchMapService,
)
from domain.core import (
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

# Reuse only benchmark helpers.  These helpers do not contain fixed scientific
# expectations; the fixed Cao probe keeps its own stricter regression checks.
from paper_experiment_chain_probe import (  # noqa: E402
    RecordingPaperFactsExtractor,
    RecordingStructuredResponseClient,
    _build_live_profile,
    _source_read_audit_record,
    _source_payload,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario-file",
        type=Path,
        required=True,
        help="JSON manifest containing a `cases` list with real PDF paths and Objectives.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        required=True,
        help="JSON report path containing one result per case.",
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
    manifest_path = args.scenario_file.expanduser().resolve()
    summary_path = args.summary_output.expanduser().resolve()
    if manifest_path == summary_path:
        raise SystemExit("--summary-output must be different from --scenario-file")
    manifest = _load_manifest(manifest_path)
    env_extraction_mode = _manifest_extraction_mode(manifest)
    extraction_mode = args.extraction_mode or env_extraction_mode or "provider_parse"
    report: dict[str, Any] = {
        "script": Path(__file__).name,
        "status": "running",
        "manifest": str(manifest_path),
        "runtime": {
            "model": runtime.model,
            "base_url": display_base_url(runtime.base_url),
            "timeout_s": runtime.timeout_s,
            "reasoning_effort": runtime.reasoning_effort,
            "extraction_mode": extraction_mode,
        },
        "boundary": (
            "Real PDFs, active Docling parsing, and configured live model. "
            "Objectives come from the manifest as researcher input. No database writes."
        ),
        "cases": [],
    }
    write_json_output(summary_path, report)

    client = build_openai_client(runtime)
    case_failures = 0
    for case in manifest["cases"]:
        case_report = _run_case(
            case=case,
            runtime=runtime,
            client=client,
            extraction_mode=extraction_mode,
        )
        report["cases"].append(case_report)
        case_failures += case_report["status"] != "pass"
        write_json_output(summary_path, report)

    report["status"] = "pass" if case_failures == 0 else "fail"
    report["case_count"] = len(report["cases"])
    report["failed_case_count"] = case_failures
    write_json_output(summary_path, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "summary_output": str(summary_path),
                "case_count": report["case_count"],
                "failed_case_count": report["failed_case_count"],
                "cases": [
                    {
                        "case_id": item.get("case_id"),
                        "status": item.get("status"),
                        "paper_experiment_count": item.get("paper_experiment_count", 0),
                        "objective_evidence_count": item.get("objective_evidence_count", 0),
                        "finding_count": item.get("finding_count", 0),
                        "failed_checks": [
                            check["name"]
                            for check in item.get("checks", [])
                            if not check.get("passed")
                        ],
                    }
                    for item in report["cases"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "pass" else 1


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise SystemExit("scenario file must contain a `cases` list")
    if not payload["cases"]:
        raise SystemExit("scenario file must contain at least one case")
    for index, case in enumerate(payload["cases"]):
        if not isinstance(case, dict):
            raise SystemExit(f"cases[{index}] must be an object")
        for field in ("case_id", "pdf", "objective", "expected_doc_role"):
            if not str(case.get(field) or "").strip():
                raise SystemExit(f"cases[{index}] is missing `{field}`")
        if case["expected_doc_role"] not in {"experimental", "review", "unknown"}:
            raise SystemExit(
                f"cases[{index}].expected_doc_role must be experimental, review, or unknown"
            )
        if not isinstance(case["objective"], dict):
            raise SystemExit(f"cases[{index}].objective must be an object")
    return payload


def _manifest_extraction_mode(manifest: dict[str, Any]) -> str | None:
    value = manifest.get("extraction_mode")
    return str(value).strip() if value else None


def _run_case(
    *,
    case: dict[str, Any],
    runtime: Any,
    client: Any,
    extraction_mode: str,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    pdf_path = Path(str(case["pdf"])).expanduser().resolve()
    report: dict[str, Any] = {
        "case_id": case_id,
        "status": "running",
        "expected_doc_role": case["expected_doc_role"],
        "input": {"pdf": str(pdf_path)},
        "objective_input": case["objective"],
    }
    started_at = perf_counter()
    response_client: RecordingStructuredResponseClient | None = None
    profile_extractor: DocumentProfileExtractor | None = None
    paper_facts_extractor: RecordingPaperFactsExtractor | None = None
    profile_trace: dict[str, Any] | None = None
    usage = None
    diagnostics = None
    try:
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        pdf_bytes = pdf_path.read_bytes()
        source_hash = sha256(pdf_bytes).hexdigest()
        document = _parse_pdf(
            backend_root=runtime.backend_root,
            pdf_path=pdf_path,
            pdf_bytes=pdf_bytes,
            scenario_id=case_id,
        )
        report["input"].update(
            {"sha256": source_hash, "source": _source_payload(document)}
        )
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

        collection_id = f"col-live-material-{case_id}"
        objective = _objective(
            document_id=document.document_id,
            collection_id=collection_id,
            objective_payload=case["objective"],
            case_id=case_id,
        )
        with capture_llm_usage() as usage, capture_analysis_diagnostics() as diagnostics:
            profile = _build_live_profile(
                document=document,
                source_filename=pdf_path.name,
                extractor=profile_extractor,
            )
            profile_trace = profile_extractor.consume_last_trace()
            paper_map = PaperResearchMapService().build_document_paper_map(
                collection_id,
                document=document,
                profile=profile,
                document_tree=None,
                paper_map_extractor=PaperResearchMapExtractor(response_client),
            )
            analysis = ObjectiveAnalysis(
                collection_id=collection_id,
                objective_id=objective.objective_id,
                analysis_version=1,
                document_inputs=(
                    PreparedDocumentInput(
                        document_id=document.document_id,
                        preparation_fingerprint=source_hash,
                    ),
                ),
                pipeline_version="paper-experiment-material-suite.v1",
                model_name=runtime.model,
                prompt_versions={},
                status="running",
                phase="finding_synthesis",
                total_document_count=1,
            )
            blocks = {document.document_id: list(document.blocks)}
            tables = {document.document_id: list(document.tables)}
            figures = {document.document_id: list(document.figures)}
            table_cells = {document.document_id: list(document.table_cells)}
            frames = screen_sources(
                collection_id=collection_id,
                source_screener=ObjectiveSourceScreener(response_client),
                objectives=(objective,),
                paper_maps=(paper_map,),
                documents=(document,),
                profiles_by_document_id={document.document_id: profile},
                blocks_by_document_id=blocks,
                tables_by_document_id=tables,
                document_trees_by_document_id={},
            )
            routes = route_sources(
                collection_id=collection_id,
                objectives=(objective,),
                objective_paper_frames=frames,
                blocks_by_document_id=blocks,
                tables_by_document_id=tables,
                document_trees_by_document_id={},
            )
            read_audits: list[Any] = []
            extracted = extract_and_validate_source_facts(
                collection_id=collection_id,
                read_audits=read_audits,
                source_extractor=ObjectiveSourceExtractor(response_client),
                paper_facts_extractor=paper_facts_extractor,
                objectives=(objective,),
                objective_paper_frames=frames,
                objective_evidence_routes=routes,
                blocks_by_document_id=blocks,
                tables_by_document_id=tables,
                figures_by_document_id=figures,
                document_trees_by_document_id={},
                table_cells_by_document_id=table_cells,
            )
            reconstructed = reconstruct_paper_experiments(
                collection_id=collection_id,
                source_facts=extracted,
                objectives=(objective,),
                document_contexts=(
                    ObjectiveExperimentAnalysisService._document_contexts_for_experiments(
                        blocks_by_document_id=blocks,
                        tables_by_document_id=tables,
                        figures_by_document_id=figures,
                    )
                ),
            )
            experiments = assemble_paper_experiments(
                collection_id=collection_id,
                document_id=document.document_id,
                source_facts=reconstructed,
            )
            evidence, contributions = materialize_evidence(
                collection_id=collection_id,
                analysis=analysis,
                objective=objective,
                experiments=experiments,
                technical_audits=tuple(read_audits),
                paper_maps=(paper_map,),
                frames=frames,
                routes=routes,
                blocks_by_document_id=blocks,
                tables_by_document_id=tables,
                figures_by_document_id=figures,
                document_trees_by_document_id={},
            )
            findings = FindingSynthesisService(
                assertion_judge=FindingAssertionJudge(response_client)
            ).synthesize(
                collection_id=collection_id,
                objective=objective,
                analysis=analysis,
                contributions=contributions,
                evidence_records=evidence,
            )

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
                "model_traces": {
                    "document_profile": [profile_trace] if profile_trace else [],
                    "objective_pipeline": response_client.traces,
                    "table_repair": deepcopy(paper_facts_extractor.traces),
                },
            }
        )
        report.update(
            {
                "source_observation_count": len(reconstructed),
                "paper_experiment_count": len(experiments),
                "objective_evidence_count": len(evidence),
                "finding_count": len(findings),
            }
        )
        report["execution_stats"] = usage.execution_stats(
            duration_ms=round((perf_counter() - started_at) * 1000)
        ).to_record()
        report["checks"] = _checks(report)
        report["status"] = (
            "pass" if all(check["passed"] for check in report["checks"]) else "fail"
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
                "document_profile": [profile_trace] if profile_trace else [],
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
    return report


def _parse_pdf(
    *, backend_root: Path, pdf_path: Path, pdf_bytes: bytes, scenario_id: str
) -> Any:
    document_id = f"paper_{sha256(pdf_bytes).hexdigest()[:12]}"
    bundle = build_pdf_bundle(
        row=pd.Series(
            {
                "id": document_id,
                "title": pdf_path.name,
                "source_path": str(pdf_path),
                "source_type": "pdf",
                "metadata": {"benchmark_scenario": scenario_id},
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


def _objective(
    *,
    document_id: str,
    collection_id: str,
    objective_payload: dict[str, Any],
    case_id: str,
) -> ResearchObjective:
    required = {
        "question",
        "material_scope",
        "variables",
        "outcomes",
    }
    missing = sorted(field for field in required if not objective_payload.get(field))
    if missing:
        raise ValueError(f"case {case_id} objective missing fields: {', '.join(missing)}")
    payload = {
        "collection_id": collection_id,
        "objective_id": f"obj-live-{case_id}",
        "question": objective_payload["question"],
        "material_scope": objective_payload["material_scope"],
        "variables": objective_payload["variables"],
        "outcomes": objective_payload["outcomes"],
        "constraints": objective_payload.get("constraints", []),
        "requested_comparator": objective_payload.get("requested_comparator"),
        "seed_document_ids": [document_id],
        "confidence": 1.0,
        "reason": f"Fixed researcher-defined live acceptance question for {case_id}.",
        "confirmation_status": "confirmed",
    }
    return ResearchObjective.from_mapping(payload)


def _checks(report: dict[str, Any]) -> list[dict[str, Any]]:
    expected_role = str(report["expected_doc_role"])
    profile = report["profile"]
    paper_map = report["paper_map"]
    observations = report["source_observations"]
    experiments = report["paper_experiments"]
    evidence = report["objective_evidence"]
    findings = report["findings"]
    traces = report.get("model_traces", {})
    usage = report.get("execution_stats", {})
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add(
        "profile_matches_expected_paper_role",
        expected_role == "unknown" or profile.get("doc_type") == expected_role,
        {"expected": expected_role, "actual": profile.get("doc_type")},
    )
    add(
        "paper_map_matches_expected_paper_role",
        expected_role == "unknown" or paper_map.get("doc_role") == expected_role,
        {"expected": expected_role, "actual": paper_map.get("doc_role")},
    )
    if expected_role == "review":
        add(
            "review_does_not_enter_experiment_reconstruction",
            not experiments,
            {"paper_experiment_count": len(experiments)},
        )
        review_synthesis = paper_map.get("review_synthesis") or {}
        add(
            "review_map_retains_review_owned_synthesis",
            any(
                review_synthesis.get(field)
                for field in ("synthesis_claims", "disputes", "evidence_gaps", "citation_leads")
            ),
            {
                "synthesis_claim_count": len(review_synthesis.get("synthesis_claims", [])),
                "dispute_count": len(review_synthesis.get("disputes", [])),
                "gap_count": len(review_synthesis.get("evidence_gaps", [])),
                "citation_lead_count": len(review_synthesis.get("citation_leads", [])),
            },
        )
    else:
        add(
            "experimental_case_has_source_facts_and_experiments",
            bool(observations) and bool(experiments),
            {
                "source_observation_count": len(observations),
                "paper_experiment_count": len(experiments),
            },
        )

    source_ids = {str(item.get("observation_id")) for item in observations}
    evidence_ids = {str(item.get("evidence_id")) for item in evidence}
    measurement_ids = {
        str(measurement.get("result_id"))
        for experiment in experiments
        for measurement in experiment.get("measurements", [])
    }
    bound_measurements = {
        str(measurement.get("result_id"))
        for experiment in experiments
        for measurement in experiment.get("measurements", [])
        if measurement.get("variant_id") and measurement.get("test_condition_id")
    }
    add(
        "measurement_lineage_is_source_backed",
        measurement_ids <= source_ids and bound_measurements <= source_ids,
        {
            "measurement_count": len(measurement_ids),
            "source_observation_count": len(source_ids),
            "unbound_measurement_ids": sorted(measurement_ids - source_ids),
        },
    )
    finding_evidence_ids = {
        str(evidence_id)
        for finding in findings
        for contribution in finding.get("paper_contributions", [])
        for evidence_id in (
            contribution.get("supporting_evidence_ids", [])
            + contribution.get("contradicting_evidence_ids", [])
        )
    }
    add(
        "finding_lineage_points_to_materialized_evidence",
        finding_evidence_ids <= evidence_ids,
        {
            "finding_evidence_count": len(finding_evidence_ids),
            "evidence_count": len(evidence_ids),
            "missing_evidence_ids": sorted(finding_evidence_ids - evidence_ids),
        },
    )
    comparable_ids = {
        str(item.get("evidence_id"))
        for item in evidence
        if item.get("evidence_status") == "comparable"
    }
    add(
        "technical_or_incomplete_inputs_do_not_become_findings",
        finding_evidence_ids <= comparable_ids
        and (bool(findings) if comparable_ids else not findings),
        {
            "comparable_evidence_count": len(comparable_ids),
            "finding_count": len(findings),
        },
    )
    required_tasks = {
        "document_profile",
        "paper_map",
        "objective_paper_frame",
    }
    if expected_role != "review":
        required_tasks.add("objective_evidence_extraction")
    if comparable_ids:
        required_tasks.add("finding_synthesis")
    observed_tasks = {
        str(trace.get("task_type"))
        for trace_group in traces.values()
        if isinstance(trace_group, list)
        for trace in trace_group
        if isinstance(trace, dict)
        and trace.get("trace_status") == "available"
        and trace.get("raw_output")
    }
    model_usage = usage.get("model_usage", [])
    request_count = sum(item.get("request_count", 0) for item in model_usage)
    add(
        "model_boundaries_have_live_traces_and_usage",
        required_tasks <= observed_tasks
        and bool(model_usage)
        and usage.get("unreported_request_count") == 0
        and request_count >= sum(
            len(group) for group in traces.values() if isinstance(group, list)
        ),
        {
            "required_tasks": sorted(required_tasks),
            "observed_tasks": sorted(observed_tasks),
            "request_count": request_count,
            "unreported_request_count": usage.get("unreported_request_count"),
        },
    )
    return checks


if __name__ == "__main__":
    raise SystemExit(main())
