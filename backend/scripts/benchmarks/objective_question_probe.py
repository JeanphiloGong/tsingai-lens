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
import subprocess
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from _common import (
    add_runtime_arguments,
    build_openai_client,
    ensure_backend_root_on_path,
    payload_hash,
    resolve_runtime,
    write_json_output,
)
from pydantic import ValidationError

ensure_backend_root_on_path(Path(__file__).resolve().parents[2])

from domain.core.research_objective import (
    PaperSourceUnitCoverageStatus,
    PaperResearchMap,
    PaperResearchSourceRef,
    ReviewKnowledgeItem,
    ReviewSynthesisMap,
    PaperResearchRelationship,
    PaperResearchScope,
    PaperResearchSignal,
    PaperSourceUnitCoverage,
    build_paper_research_scope_id,
    build_paper_research_relationship,
    build_paper_research_signal,
)

from application.core.objectives.discovery.axis_equivalence import (
    ResearchAxisEquivalenceClassifier,
)
from application.core.objectives.llm.structured_response import StructuredResponseClient
from application.core.objectives.objective_candidate_service import (
    CandidateQuestionBatch,
    ObjectiveCandidateService,
)
from domain.core import PreparedDocumentInput
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


def load_scenarios(
    path: Path,
) -> tuple[list[dict], dict[str, tuple[PaperResearchMap, ...]]]:
    scenarios = json.loads(path.read_text(encoding="utf-8"))["scenarios"]
    seen = set()
    paper_maps_by_scenario = {}
    for scenario in scenarios:
        if scenario["scenario_id"] in seen:
            raise ValueError("duplicate scenario id")
        seen.add(scenario["scenario_id"])
        document_ids = set()
        paper_maps = []
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
            payload = paper["paper_map"]
            map_document_id = document_id
            studies = []
            for study in payload.get("studies", ()):
                document_id = study.get("document_id", map_document_id)
                design_type = study.get("design_type", "uncertain")
                claim_scope = study.get("claim_scope", "uncertain")
                experiment_label = study.get("experiment_label")
                material_scope = tuple(study.get("material_scope", ()))
                process_context = tuple(study.get("process_context", ()))
                parent_study_boundary = json.dumps(
                    {
                        "document_id": document_id.casefold(),
                        "design_type": design_type,
                        "claim_scope": claim_scope,
                        "experiment_label": (
                            experiment_label.casefold() if experiment_label else None
                        ),
                        "material_scope": sorted(
                            value.casefold() for value in material_scope
                        ),
                        "process_context": sorted(
                            value.casefold() for value in process_context
                        ),
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                relationships = []
                for relationship in study.get("relationships", ()):
                    varied_factors = tuple(relationship["varied_factors"])
                    source_refs = tuple(
                        dict.fromkeys(
                            PaperResearchSourceRef(
                                ref["source_kind"], ref["source_ref"]
                            )
                            for ref in relationship["source_refs"]
                        )
                    )
                    if relationship.get("relationship_id") is None:
                        relationships.append(
                            build_paper_research_relationship(
                                document_id=document_id,
                                varied_factors=varied_factors,
                                outcome=relationship["outcome"],
                                source_refs=source_refs,
                                confidence=relationship.get("confidence", 0.0),
                                parent_study_boundary=parent_study_boundary,
                            )
                        )
                    else:
                        relationships.append(
                            PaperResearchRelationship(
                                relationship_id=relationship["relationship_id"],
                                varied_factors=varied_factors,
                                outcome=relationship["outcome"],
                                source_refs=source_refs,
                                confidence=relationship.get("confidence", 0.0),
                            )
                        )
                relationships = tuple(relationships)
                study_id = study.get("study_id")
                if study_id is None:
                    study_id = build_paper_research_scope_id(
                        document_id=document_id,
                        design_type=design_type,
                        claim_scope=claim_scope,
                        experiment_label=experiment_label,
                        material_scope=material_scope,
                        process_context=process_context,
                        relationships=relationships,
                    )
                studies.append(
                    PaperResearchScope(
                        study_id=study_id,
                        document_id=document_id,
                        design_type=design_type,
                        claim_scope=claim_scope,
                        experiment_label=experiment_label,
                        material_scope=material_scope,
                        process_context=process_context,
                        relationships=relationships,
                        confidence=study.get("confidence", 0.0),
                    )
                )
            signals = []
            for signal in payload.get("unresolved_signals", ()):
                signal_type = signal["signal_type"]
                variable_role = signal.get(
                    "variable_role",
                    "not_applicable" if signal_type == "outcome" else "uncertain",
                )
                source_refs = tuple(
                    dict.fromkeys(
                        PaperResearchSourceRef(ref["source_kind"], ref["source_ref"])
                        for ref in signal["source_refs"]
                    )
                )
                if signal.get("signal_id") is None:
                    signals.append(
                        build_paper_research_signal(
                            document_id=map_document_id,
                            signal_type=signal_type,
                            label=signal["label"],
                            variable_role=variable_role,
                            design_type=signal.get("design_type", "uncertain"),
                            claim_scope=signal.get("claim_scope", "uncertain"),
                            experiment_label=signal.get("experiment_label"),
                            material_scope=tuple(signal.get("material_scope", ())),
                            process_context=tuple(signal.get("process_context", ())),
                            source_refs=source_refs,
                            confidence=signal.get("confidence", 0.0),
                            reason=signal.get("reason"),
                        )
                    )
                else:
                    signals.append(
                        PaperResearchSignal(
                            signal_id=signal["signal_id"],
                            signal_type=signal_type,
                            label=signal["label"],
                            variable_role=variable_role,
                            design_type=signal.get("design_type", "uncertain"),
                            claim_scope=signal.get("claim_scope", "uncertain"),
                            experiment_label=signal.get("experiment_label"),
                            material_scope=tuple(signal.get("material_scope", ())),
                            process_context=tuple(signal.get("process_context", ())),
                            source_refs=source_refs,
                            confidence=signal.get("confidence", 0.0),
                            reason=signal.get("reason"),
                        )
                    )
            review = payload.get("review_synthesis", {})
            review_items = {}
            for field_name in (
                "synthesis_claims",
                "disputes",
                "evidence_gaps",
                "citation_leads",
            ):
                review_items[field_name] = tuple(
                    ReviewKnowledgeItem(
                        content=item["content"],
                        material_scope=tuple(item.get("material_scope", ())),
                        variables=tuple(item.get("variables", ())),
                        outcomes=tuple(item.get("outcomes", ())),
                        conditions=tuple(item.get("conditions", ())),
                        source_refs=tuple(
                            dict.fromkeys(
                                PaperResearchSourceRef(
                                    ref["source_kind"], ref["source_ref"]
                                )
                                for ref in item["source_refs"]
                            )
                        ),
                        confidence=item.get("confidence", 0.0),
                    )
                    for item in review.get(field_name, ())
                )
            paper_map = PaperResearchMap(
                document_id=map_document_id,
                doc_role=payload.get("doc_role", "uncertain"),
                studies=tuple(studies),
                evidence_density=payload.get("evidence_density", "unknown"),
                confidence=payload.get("confidence", 0.0),
                warnings=tuple(payload.get("warnings", ())),
                unresolved_signals=tuple(signals),
                source_unit_coverage=tuple(
                    PaperSourceUnitCoverage(
                        source_unit_id=item["source_unit_id"],
                        window_id=item["window_id"],
                        source_kind=item["source_kind"],
                        source_ref=item["source_ref"],
                        status=PaperSourceUnitCoverageStatus(item["status"]),
                        reason=item.get("reason"),
                    )
                    for item in payload.get("source_unit_coverage", ())
                ),
                map_status=payload.get("map_status", "unknown"),
                map_limitations=tuple(payload.get("map_limitations", ())),
                review_synthesis=ReviewSynthesisMap(
                    synthesis_claims=review_items["synthesis_claims"],
                    disputes=review_items["disputes"],
                    evidence_gaps=review_items["evidence_gaps"],
                    citation_leads=review_items["citation_leads"],
                ),
                input_fingerprint=payload.get("input_fingerprint"),
                map_version=payload.get("map_version"),
                generated_at=payload.get("generated_at"),
            )
            paper_maps.append(paper_map)
            if any(
                ref.source_ref not in refs
                for study in paper_map.studies
                for relationship in study.relationships
                for ref in relationship.source_refs
            ):
                raise ValueError("map relationship refers to an unavailable excerpt")
        paper_maps_by_scenario[scenario["scenario_id"]] = tuple(paper_maps)
    return scenarios, paper_maps_by_scenario


def run_baseline(
    scenario: dict, runtime, client, *, paper_maps: tuple[PaperResearchMap, ...]
) -> dict:
    response_client = StructuredResponseClient(client=client, model=runtime.model)
    response_client.reasoning_effort = runtime.reasoning_effort
    maps = paper_maps
    started = perf_counter()
    with capture_llm_usage() as usage:
        facts = ObjectiveCandidateService().discover_candidate_facts(
            "probe",
            paper_maps=maps,
            document_inputs=tuple(
                PreparedDocumentInput(
                    m.document_id,
                    payload_hash(
                        {
                            "document_id": m.document_id,
                            "doc_role": m.doc_role,
                            "studies": [
                                {
                                    "study_id": study.study_id,
                                    "document_id": study.document_id,
                                    "design_type": study.design_type,
                                    "claim_scope": study.claim_scope,
                                    "experiment_label": study.experiment_label,
                                    "material_scope": list(study.material_scope),
                                    "process_context": list(study.process_context),
                                    "relationships": [
                                        {
                                            "relationship_id": item.relationship_id,
                                            "varied_factors": list(item.varied_factors),
                                            "outcome": item.outcome,
                                            "source_refs": [
                                                {
                                                    "source_kind": item.source_kind,
                                                    "source_ref": item.source_ref,
                                                }
                                                for item in item.source_refs
                                            ],
                                            "confidence": item.confidence,
                                        }
                                        for item in study.relationships
                                    ],
                                    "confidence": study.confidence,
                                }
                                for study in m.studies
                            ],
                            "evidence_density": m.evidence_density,
                            "confidence": m.confidence,
                            "warnings": list(m.warnings),
                            "unresolved_signals": [
                                {
                                    "signal_id": signal.signal_id,
                                    "signal_type": signal.signal_type,
                                    "label": signal.label,
                                    "variable_role": signal.variable_role,
                                    "design_type": signal.design_type,
                                    "claim_scope": signal.claim_scope,
                                    "experiment_label": signal.experiment_label,
                                    "material_scope": list(signal.material_scope),
                                    "process_context": list(signal.process_context),
                                    "source_refs": [
                                        {
                                            "source_kind": item.source_kind,
                                            "source_ref": item.source_ref,
                                        }
                                        for item in signal.source_refs
                                    ],
                                    "confidence": signal.confidence,
                                    "reason": signal.reason,
                                }
                                for signal in m.unresolved_signals
                            ],
                            "source_unit_coverage": [
                                {
                                    "source_unit_id": item.source_unit_id,
                                    "window_id": item.window_id,
                                    "source_kind": item.source_kind,
                                    "source_ref": item.source_ref,
                                    "status": item.status.value,
                                    "reason": item.reason,
                                }
                                for item in m.source_unit_coverage
                            ],
                            "map_status": m.map_status,
                            "map_limitations": list(m.map_limitations),
                            "review_synthesis": {
                                field_name: [
                                    {
                                        "content": item.content,
                                        "material_scope": list(item.material_scope),
                                        "variables": list(item.variables),
                                        "outcomes": list(item.outcomes),
                                        "conditions": list(item.conditions),
                                        "source_refs": [
                                            {
                                                "source_kind": item.source_kind,
                                                "source_ref": item.source_ref,
                                            }
                                            for item in item.source_refs
                                        ],
                                        "confidence": item.confidence,
                                    }
                                    for item in getattr(m.review_synthesis, field_name)
                                ]
                                for field_name in (
                                    "synthesis_claims",
                                    "disputes",
                                    "evidence_gaps",
                                    "citation_leads",
                                )
                            },
                            "input_fingerprint": m.input_fingerprint,
                            "map_version": m.map_version,
                            "generated_at": m.generated_at,
                        }
                    ),
                )
                for m in maps
            ),
            axis_equivalence_classifier=ResearchAxisEquivalenceClassifier(
                response_client
            ),
        )
    stats = usage.execution_stats(duration_ms=int((perf_counter() - started) * 1000))
    return {
        "objectives": [
            {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in asdict(objective).items()
            }
            for objective in facts.research_objectives
        ],
        "execution_stats": {
            "duration_ms": stats.duration_ms,
            "token_usage": (
                asdict(stats.token_usage) if stats.token_usage is not None else None
            ),
            "model_usage": [asdict(item) for item in stats.model_usage],
            "unreported_request_count": stats.unreported_request_count,
            "prompt_versions": dict(stats.prompt_versions),
        },
        "last_axis_trace": response_client.consume_last_trace(),
        "interest_filter": "none_in_current_discovery_contract",
    }


def run_proposal(
    scenario: dict, runtime, client, *, paper_maps: tuple[PaperResearchMap, ...]
) -> dict:
    response_client = StructuredResponseClient(client=client, model=runtime.model)
    response_client.reasoning_effort = runtime.reasoning_effort
    started = perf_counter()
    record = {"input_sha256": payload_hash(scenario)}
    with capture_llm_usage() as usage:
        try:
            result = ObjectiveCandidateService().propose_candidate_questions(
                "probe",
                paper_maps=paper_maps,
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
                        "objective": {
                            key: list(value) if isinstance(value, tuple) else value
                            for key, value in asdict(candidate.objective).items()
                        },
                        "papers": [
                            {
                                "document_id": paper.paper_map.document_id,
                                "paper_map": {
                                    "document_id": paper.paper_map.document_id,
                                    "doc_role": paper.paper_map.doc_role,
                                    "studies": [
                                        {
                                            "study_id": study.study_id,
                                            "document_id": study.document_id,
                                            "design_type": study.design_type,
                                            "claim_scope": study.claim_scope,
                                            "experiment_label": study.experiment_label,
                                            "material_scope": list(
                                                study.material_scope
                                            ),
                                            "process_context": list(
                                                study.process_context
                                            ),
                                            "relationships": [
                                                {
                                                    "relationship_id": item.relationship_id,
                                                    "varied_factors": list(
                                                        item.varied_factors
                                                    ),
                                                    "outcome": item.outcome,
                                                    "source_refs": [
                                                        {
                                                            "source_kind": item.source_kind,
                                                            "source_ref": item.source_ref,
                                                        }
                                                        for item in item.source_refs
                                                    ],
                                                    "confidence": item.confidence,
                                                }
                                                for item in study.relationships
                                            ],
                                            "confidence": study.confidence,
                                        }
                                        for study in paper.paper_map.studies
                                    ],
                                    "evidence_density": paper.paper_map.evidence_density,
                                    "confidence": paper.paper_map.confidence,
                                    "warnings": list(paper.paper_map.warnings),
                                    "unresolved_signals": [
                                        {
                                            "signal_id": signal.signal_id,
                                            "signal_type": signal.signal_type,
                                            "label": signal.label,
                                            "variable_role": signal.variable_role,
                                            "design_type": signal.design_type,
                                            "claim_scope": signal.claim_scope,
                                            "experiment_label": signal.experiment_label,
                                            "material_scope": list(
                                                signal.material_scope
                                            ),
                                            "process_context": list(
                                                signal.process_context
                                            ),
                                            "source_refs": [
                                                {
                                                    "source_kind": item.source_kind,
                                                    "source_ref": item.source_ref,
                                                }
                                                for item in signal.source_refs
                                            ],
                                            "confidence": signal.confidence,
                                            "reason": signal.reason,
                                        }
                                        for signal in paper.paper_map.unresolved_signals
                                    ],
                                    "source_unit_coverage": [
                                        {
                                            "source_unit_id": item.source_unit_id,
                                            "window_id": item.window_id,
                                            "source_kind": item.source_kind,
                                            "source_ref": item.source_ref,
                                            "status": item.status.value,
                                            "reason": item.reason,
                                        }
                                        for item in paper.paper_map.source_unit_coverage
                                    ],
                                    "map_status": paper.paper_map.map_status,
                                    "map_limitations": list(
                                        paper.paper_map.map_limitations
                                    ),
                                    "review_synthesis": {
                                        field_name: [
                                            {
                                                "content": item.content,
                                                "material_scope": list(
                                                    item.material_scope
                                                ),
                                                "variables": list(item.variables),
                                                "outcomes": list(item.outcomes),
                                                "conditions": list(item.conditions),
                                                "source_refs": [
                                                    {
                                                        "source_kind": item.source_kind,
                                                        "source_ref": item.source_ref,
                                                    }
                                                    for item in item.source_refs
                                                ],
                                                "confidence": item.confidence,
                                            }
                                            for item in getattr(
                                                paper.paper_map.review_synthesis,
                                                field_name,
                                            )
                                        ]
                                        for field_name in (
                                            "synthesis_claims",
                                            "disputes",
                                            "evidence_gaps",
                                            "citation_leads",
                                        )
                                    },
                                    "input_fingerprint": paper.paper_map.input_fingerprint,
                                    "map_version": paper.paper_map.map_version,
                                    "generated_at": paper.paper_map.generated_at,
                                },
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
    stats = usage.execution_stats(duration_ms=int((perf_counter() - started) * 1000))
    record["execution_stats"] = {
        "duration_ms": stats.duration_ms,
        "token_usage": (
            asdict(stats.token_usage) if stats.token_usage is not None else None
        ),
        "model_usage": [asdict(item) for item in stats.model_usage],
        "unreported_request_count": stats.unreported_request_count,
        "prompt_versions": dict(stats.prompt_versions),
    }
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
    scenarios, paper_maps_by_scenario = load_scenarios(args.scenario_file)
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
            baseline = run_baseline(
                scenario,
                runtime,
                client,
                paper_maps=paper_maps_by_scenario[scenario["scenario_id"]],
            )
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
                result = run_proposal(
                    scenario,
                    runtime,
                    client,
                    paper_maps=paper_maps_by_scenario[scenario["scenario_id"]],
                )
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
