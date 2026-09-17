#!/usr/bin/env python3
"""Offline/opt-in live question-formation probe. No database or approved writes.

Compares current Objective discovery with opt-in Core question formation.
Input: scenarios with interest, papers (paper_map, excerpts), and optional hidden
expectation. Excerpts contain text or an explicit PDF/page/start/end locator.
Output: input hashes, model traces, source-bound candidates and reading checks.
Mechanical checks are NOT expert scientific acceptance or full Agent E2E.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from time import perf_counter

from pydantic import ValidationError

from _common import (
    add_runtime_arguments,
    build_openai_client,
    ensure_backend_root_on_path,
    payload_hash,
    resolve_runtime,
    write_json_output,
)

ensure_backend_root_on_path(Path(__file__).resolve().parents[2])

from application.core.objectives.discovery.axis_equivalence import (
    ResearchAxisEquivalenceClassifier,
)
from application.core.objectives.llm.structured_response import StructuredResponseClient
from application.core.objectives.objective_candidate_service import (
    CandidateQuestionBatch,
    ObjectiveCandidateService,
)
from domain.core import PaperResearchMap, PreparedDocumentInput
from infra.llm.usage import capture_llm_usage


def audit_output(scenario: dict, result: CandidateQuestionBatch) -> dict:
    sources = {
        (p["document_id"], s["source_ref"]): s["text"]
        for p in scenario["papers"]
        for s in p["excerpts"]
    }
    errors = []
    if not result.candidates and not (result.abstention_reason or "").strip():
        errors.append("empty_result_without_abstention")
    for candidate in result.candidates:
        for paper in candidate.papers:
            for source_ref, text in paper.source_texts:
                key = (paper.paper_map.document_id, source_ref)
                if key not in sources or text != sources[key]:
                    errors.append(f"source_binding_mismatch:{key}")
    expected = scenario.get("expectation", {})
    target = set(expected.get("shared_question_documents", []))
    groups = [
        {p.paper_map.document_id for p in item.papers if p.role == "inspect"}
        for item in result.candidates
    ]
    excluded = set(expected.get("not_direct_documents", []))
    return {
        "reference_errors": errors,
        "shared_question_coverage": (
            any(target <= group for group in groups) if target else None
        ),
        "no_excluded_direct_papers": not any(excluded & group for group in groups),
        "expected_abstention": (
            not result.candidates if expected.get("abstain") else None
        ),
        "scientific_acceptance": "requires_review_of_sources_questions_and_limitations",
    }


def load_scenarios(path: Path) -> list[dict]:
    scenarios = json.loads(path.read_text(encoding="utf-8"))["scenarios"]
    seen = set()
    for scenario in scenarios:
        if scenario["scenario_id"] in seen:
            raise ValueError("duplicate scenario id")
        seen.add(scenario["scenario_id"])
        document_ids = set()
        for paper in scenario["papers"]:
            document_id = paper["document_id"]
            if (
                document_id in document_ids
                or document_id != paper["paper_map"]["document_id"]
            ):
                raise ValueError("invalid paper map ownership")
            document_ids.add(document_id)
            refs = set()
            for excerpt in paper["excerpts"]:
                if excerpt["source_ref"] in refs:
                    raise ValueError("duplicate Source locator")
                refs.add(excerpt["source_ref"])
                if "text" not in excerpt:
                    pdf = Path(excerpt["pdf"]).expanduser()
                    if not pdf.is_absolute():
                        pdf = path.resolve().parent / pdf
                    pdf = pdf.resolve(strict=True)
                    page = int(excerpt["page"])
                    if page < 1:
                        raise ValueError("PDF page must be positive")
                    text = subprocess.run(
                        [
                            "pdftotext",
                            "-f",
                            str(page),
                            "-l",
                            str(page),
                            "-raw",
                            str(pdf),
                            "-",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    ).stdout
                    start = text.index(excerpt["start"]) if excerpt.get("start") else 0
                    end = (
                        text.index(excerpt["end"], start)
                        if excerpt.get("end")
                        else len(text)
                    )
                    excerpt["text"] = text[start:end].strip()
                if not excerpt["text"].strip():
                    raise ValueError("empty excerpt")
                excerpt["text_sha256"] = payload_hash(excerpt["text"])
            paper_map = PaperResearchMap.from_mapping(paper["paper_map"])
            if any(
                ref.source_ref not in refs
                for study in paper_map.studies
                for relationship in study.relationships
                for ref in relationship.source_refs
            ):
                raise ValueError("map relationship refers to an unavailable excerpt")
    return scenarios


def run_baseline(scenario: dict, runtime, client) -> dict:
    response_client = StructuredResponseClient(client=client, model=runtime.model)
    response_client.reasoning_effort = runtime.reasoning_effort
    maps = tuple(
        PaperResearchMap.from_mapping(p["paper_map"]) for p in scenario["papers"]
    )
    started = perf_counter()
    with capture_llm_usage() as usage:
        facts = ObjectiveCandidateService().discover_candidate_facts(
            "probe",
            paper_maps=maps,
            document_inputs=tuple(
                PreparedDocumentInput(m.document_id, payload_hash(m.to_record()))
                for m in maps
            ),
            axis_equivalence_classifier=ResearchAxisEquivalenceClassifier(
                response_client
            ),
        )
    return {
        "objectives": [o.to_record() for o in facts.research_objectives],
        "execution_stats": usage.execution_stats(
            duration_ms=int((perf_counter() - started) * 1000)
        ).to_record(),
        "last_axis_trace": response_client.consume_last_trace(),
        "interest_filter": "none_in_current_discovery_contract",
    }


def run_proposal(scenario: dict, runtime, client) -> dict:
    response_client = StructuredResponseClient(client=client, model=runtime.model)
    response_client.reasoning_effort = runtime.reasoning_effort
    started = perf_counter()
    record = {"input_sha256": payload_hash(scenario)}
    with capture_llm_usage() as usage:
        try:
            result = ObjectiveCandidateService().propose_candidate_questions(
                "probe",
                paper_maps=tuple(
                    PaperResearchMap.from_mapping(p["paper_map"])
                    for p in scenario["papers"]
                ),
                source_texts={
                    (p["document_id"], s["source_ref"]): s["text"]
                    for p in scenario["papers"]
                    for s in p["excerpts"]
                },
                research_interest=scenario.get("interest"),
                response_client=response_client,
                max_completion_tokens=runtime.max_completion_tokens or 8192,
                request_timeout_s=runtime.timeout_s,
            )
            record.update(
                status="completed",
                abstention_reason=result.abstention_reason,
                candidates=[
                    {
                        "objective": candidate.objective.to_record(),
                        "papers": [
                            {
                                "document_id": paper.paper_map.document_id,
                                "paper_map": paper.paper_map.to_record(),
                                "excerpts": [
                                    {"source_ref": ref, "text": text}
                                    for ref, text in paper.source_texts
                                ],
                                "role": paper.role,
                                "reason": paper.reason,
                                "limitation": paper.limitation,
                            }
                            for paper in candidate.papers
                        ],
                    }
                    for candidate in result.candidates
                ],
                audit=audit_output(scenario, result),
            )
        except Exception as exc:
            record.update(status="technical_failure", error_type=type(exc).__name__)
            if isinstance(exc, ValidationError):
                record["validation_errors"] = [
                    {"loc": list(error["loc"]), "type": error["type"]}
                    for error in exc.errors(include_input=False, include_url=False)
                ]
    record["trace"] = response_client.consume_last_trace()
    record["execution_stats"] = usage.execution_stats(
        duration_ms=int((perf_counter() - started) * 1000)
    ).to_record()
    record["duration_s"] = round(perf_counter() - started, 3)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_runtime_arguments(
        parser,
        include_temperature=False,
        default_max_completion_tokens=8192,
        default_timeout_s=180,
    )
    parser.add_argument("--scenario-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execution", choices=("offline", "live"), default="offline")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument(
        "--scenario-id", action="append", help="Run only the named scenario(s)."
    )
    parser.add_argument(
        "--ignore-interest",
        action="store_true",
        help="Evaluate automatic formation without a user interest.",
    )
    args = parser.parse_args()
    if not 1 <= args.repeat <= 3:
        parser.error("repeat must be 1..3 for this small probe")
    scenarios = load_scenarios(args.scenario_file)
    if args.scenario_id:
        unknown = set(args.scenario_id) - {s["scenario_id"] for s in scenarios}
        if unknown:
            parser.error(f"unknown scenario ids: {sorted(unknown)}")
        scenarios = [s for s in scenarios if s["scenario_id"] in args.scenario_id]
    if args.ignore_interest:
        for scenario in scenarios:
            scenario["interest"] = None
    report = {
        "probe_version": "objective_question_probe.v3",
        "execution": args.execution,
        "git_head": subprocess.check_output(
            [
                "git",
                "-C",
                str(Path(__file__).resolve().parents[2]),
                "rev-parse",
                "HEAD",
            ],
            text=True,
        ).strip(),
        "scenario_sha256": payload_hash(scenarios),
        "scenarios": scenarios,
        "runs": [],
        "boundary": "No production writes. Baseline uses maps only; Core proposals also read original excerpts. Candidate formation, not Agent/analysis E2E. Scientific judgments require review.",
    }
    write_json_output(args.output, report)
    if args.execution == "offline":
        print(
            json.dumps(
                {
                    "status": "offline_validated",
                    "scenarios": len(scenarios),
                    "output": str(args.output),
                }
            )
        )
        return
    runtime = resolve_runtime(args, allow_placeholder_api_key=False)
    report["model_requested"] = runtime.model
    report["reasoning_effort"] = runtime.reasoning_effort
    with build_openai_client(runtime).with_options(max_retries=0) as client:
        for scenario in scenarios:
            print(f"Baseline: {scenario['scenario_id']}", flush=True)
            baseline = run_baseline(scenario, runtime, client)
            report["runs"].append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "baseline": baseline,
                    "proposals": [],
                }
            )
            write_json_output(args.output, report)
            for repeat in range(args.repeat):
                print(
                    f"Proposal: {scenario['scenario_id']} {repeat + 1}/{args.repeat}",
                    flush=True,
                )
                result = run_proposal(scenario, runtime, client)
                report["runs"][-1]["proposals"].append(result)
                write_json_output(args.output, report)
                print(
                    json.dumps(
                        {
                            "status": result["status"],
                            "duration_s": result["duration_s"],
                            "audit": result.get("audit"),
                        }
                    ),
                    flush=True,
                )
    print(f"Report: {args.output}", flush=True)


if __name__ == "__main__":
    main()
