#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any


REQUIRED_FAMILIES = (
    "collections",
    "collection_files",
    "import_manifests",
    "tasks",
    "artifacts",
    "auth_users",
    "auth_sessions",
    "source_documents",
    "source_text_units",
    "source_blocks",
    "source_tables",
    "source_table_rows",
    "source_table_cells",
    "source_figures",
    "source_reference_entries",
    "core_document_profiles",
    "core_evidence_anchors",
    "core_method_facts",
    "core_sample_variants",
    "core_test_conditions",
    "core_baseline_references",
    "core_measurement_results",
    "research_objectives",
    "confirmed_goals",
    "research_understandings",
    "goal_sessions",
    "goal_messages",
    "experiment_plans",
    "feedback",
    "curations",
    "evaluation_gold_sets",
    "evaluation_gold_items",
    "prediction_snapshots",
    "evaluation_runs",
)


def capture_baseline(scenario: dict[str, Any]) -> dict[str, Any]:
    if scenario.get("schema_version") != "persistence-scenario.v1":
        raise ValueError("unsupported persistence scenario schema")
    records = scenario.get("records")
    if not isinstance(records, dict):
        raise ValueError("scenario records must be an object")
    for family in REQUIRED_FAMILIES:
        if family not in records:
            raise ValueError(f"missing required record family: {family}")
        if not isinstance(records[family], list):
            raise ValueError(f"record family must be a list: {family}")

    non_empty_families = tuple(
        family for family in REQUIRED_FAMILIES if family != "source_figures"
    )
    for family in non_empty_families:
        if not records[family]:
            raise ValueError(f"required record family is empty: {family}")

    documents = {item["id"]: item for item in records["source_documents"]}
    text_units = {item["id"]: item for item in records["source_text_units"]}
    blocks = {item["block_id"]: item for item in records["source_blocks"]}
    files_by_document = {
        item["document_id"]: item for item in records["collection_files"]
    }
    anchors = {
        item["anchor_id"]: item for item in records["core_evidence_anchors"]
    }
    measurements = {
        item["result_id"]: item for item in records["core_measurement_results"]
    }
    objectives = {
        item["objective_id"]: item for item in records["research_objectives"]
    }
    collections = {
        item["collection_id"]: item for item in records["collections"]
    }

    evidence_traces: list[dict[str, Any]] = []
    claim_ids: list[str] = []
    claims_by_id: dict[str, dict[str, Any]] = {}
    evidence_refs_by_id: dict[str, dict[str, Any]] = {}
    contexts_by_id: dict[str, dict[str, Any]] = {}
    for understanding in records["research_understandings"]:
        evidence_refs = {
            item["evidence_ref_id"]: item
            for item in understanding.get("evidence_refs", [])
        }
        contexts = {
            item["context_id"]: item for item in understanding.get("contexts", [])
        }
        evidence_refs_by_id.update(evidence_refs)
        contexts_by_id.update(contexts)
        for claim in understanding.get("claims", []):
            claim_id = claim["claim_id"]
            claim_ids.append(claim_id)
            claims_by_id[claim_id] = claim
            for evidence_ref_id in claim.get("evidence_ref_ids", []):
                evidence_ref = evidence_refs.get(evidence_ref_id)
                if evidence_ref is None:
                    raise ValueError(
                        f"unresolved claim evidence reference: {evidence_ref_id}"
                    )
                for fact_id in evidence_ref.get("fact_ids", []):
                    if fact_id not in measurements:
                        raise ValueError(f"unresolved evidence fact: {fact_id}")
                for context_id in claim.get("context_ids", []):
                    if context_id not in contexts:
                        raise ValueError(f"unresolved claim context: {context_id}")
                for anchor_id in evidence_ref.get("anchor_ids", []):
                    anchor = anchors.get(anchor_id)
                    if anchor is None:
                        raise ValueError(f"unresolved evidence anchor: {anchor_id}")
                    document_id = evidence_ref.get("document_id") or anchor.get(
                        "document_id"
                    )
                    if document_id not in documents:
                        raise ValueError(
                            f"unresolved evidence document: {document_id}"
                        )
                    source_record_id = anchor.get("block_id")
                    source_block = blocks.get(source_record_id)
                    if source_block is None:
                        raise ValueError(
                            f"unresolved evidence source block: {source_record_id}"
                        )
                    text_unit_id = anchor.get("snippet_id")
                    if not text_unit_id:
                        block_text_units = source_block.get("text_unit_ids") or []
                        text_unit_id = block_text_units[0] if block_text_units else None
                    if text_unit_id not in text_units:
                        raise ValueError(
                            f"unresolved evidence text unit: {text_unit_id}"
                        )
                    source_file = files_by_document.get(document_id)
                    if source_file is None:
                        raise ValueError(
                            f"unresolved evidence collection file: {document_id}"
                        )
                    evidence_traces.append(
                        {
                            "claim_id": claim_id,
                            "evidence_ref_id": evidence_ref_id,
                            "anchor_id": anchor_id,
                            "source_record_kind": "block",
                            "source_record_id": source_record_id,
                            "text_unit_id": text_unit_id,
                            "document_id": document_id,
                            "file_id": source_file["file_id"],
                            "quote": evidence_ref.get("quote") or anchor.get("quote"),
                            "href": evidence_ref.get("href"),
                        }
                    )

    for goal in records["confirmed_goals"]:
        if goal.get("collection_id") not in collections:
            raise ValueError(
                f"unresolved goal collection: {goal.get('collection_id')}"
            )
        objective_id = goal.get("source_objective_id")
        if objective_id and objective_id not in objectives:
            raise ValueError(f"unresolved goal objective: {objective_id}")
    for item in records["feedback"]:
        claim_id = item.get("claim_id")
        if claim_id and claim_id not in claims_by_id:
            raise ValueError(f"unresolved feedback claim: {claim_id}")
    for item in records["curations"]:
        claim_id = item.get("claim_id")
        if claim_id and claim_id not in claims_by_id:
            raise ValueError(f"unresolved curation claim: {claim_id}")
        for evidence_ref_id in item.get("curated_evidence_ref_ids", []):
            if evidence_ref_id not in evidence_refs_by_id:
                raise ValueError(
                    f"unresolved curation evidence reference: {evidence_ref_id}"
                )
        for context_id in item.get("curated_context_ids", []):
            if context_id not in contexts_by_id:
                raise ValueError(f"unresolved curation context: {context_id}")

    collection = records["collections"][0]
    task = records["tasks"][0]
    artifacts = records["artifacts"][0]
    goal = records["confirmed_goals"][0]
    understanding = next(
        (
            item
            for item in records["research_understandings"]
            if item.get("scope", {}).get("goal_id") == goal["goal_id"]
        ),
        None,
    )
    if understanding is None:
        raise ValueError(f"missing understanding for goal: {goal['goal_id']}")
    if not evidence_traces:
        raise ValueError("scenario has no complete evidence trace")
    trace = evidence_traces[0]
    source_profile = next(
        (
            item
            for item in records["core_document_profiles"]
            if item.get("document_id") == trace["document_id"]
        ),
        None,
    )
    if source_profile is None:
        raise ValueError(
            f"missing document profile for source trace: {trace['document_id']}"
        )

    id_fields = {
        "collections": "collection_id",
        "tasks": "task_id",
        "source_documents": "id",
        "source_text_units": "id",
        "core_measurement_results": "result_id",
        "research_objectives": "objective_id",
        "confirmed_goals": "goal_id",
        "goal_messages": "message_id",
        "feedback": "feedback_id",
        "curations": "curation_id",
        "evaluation_runs": "evaluation_run_id",
    }
    ordered_ids = {
        family: [item[id_field] for item in records[family]]
        for family, id_field in id_fields.items()
    }
    ordered_ids["claims"] = claim_ids

    field_sources = {
        "collection": records["collections"][0],
        "task": records["tasks"][0],
        "source_document": records["source_documents"][0],
        "measurement_result": records["core_measurement_results"][0],
        "confirmed_goal": records["confirmed_goals"][0],
        "research_understanding": records["research_understandings"][0],
        "feedback": records["feedback"][0],
        "evaluation_run": records["evaluation_runs"][0],
    }
    summary = understanding.get("summary") or {
        "claim_count": len(understanding.get("claims", [])),
        "relation_count": len(understanding.get("relations", [])),
        "evidence_ref_count": len(understanding.get("evidence_refs", [])),
        "context_count": len(understanding.get("contexts", [])),
    }
    collection_id = collection["collection_id"]
    document_id = trace["document_id"]

    return {
        "schema_version": "persistence-baseline.v1",
        "scenario_id": scenario["scenario_id"],
        "record_counts": {
            family: len(records[family]) for family in REQUIRED_FAMILIES
        },
        "ordered_ids": ordered_ids,
        "field_sets": {
            name: sorted(payload) for name, payload in field_sources.items()
        },
        "api_contract": {
            "collection_build": {
                "endpoint": f"/api/v1/collections/{collection_id}/tasks/build",
                "request_status": 200,
                "task_id": task["task_id"],
                "task_type": task["task_type"],
                "status": task["status"],
                "current_stage": task["current_stage"],
            },
            "workspace": {
                "endpoint": f"/api/v1/collections/{collection_id}/workspace",
                "status_code": 200,
                "collection_id": collection_id,
                "file_count": len(records["collection_files"]),
                "status_summary": collection["status"],
                "latest_task_status": task["status"],
                "artifacts": {
                    key: artifacts[key]
                    for key in (
                        "documents_ready",
                        "document_profiles_ready",
                        "evidence_cards_ready",
                        "comparison_rows_ready",
                    )
                },
            },
            "goal_analysis": {
                "endpoint": (
                    f"/api/v1/collections/{collection_id}/goals/"
                    f"{goal['goal_id']}/analysis"
                ),
                "status_code": 200,
                "goal_id": goal["goal_id"],
                "status": goal["status"],
                "phase": goal.get("analysis_progress", {}).get("phase"),
                "understanding_state": understanding["state"],
                "summary": summary,
            },
            "source_trace": {
                "endpoint": (
                    f"/api/v1/collections/{collection_id}/documents/"
                    f"{document_id}/source"
                ),
                "status_code": 200,
                "document_id": document_id,
                "source_filename": source_profile["source_filename"],
                "claim_id": trace["claim_id"],
                "evidence_ref_id": trace["evidence_ref_id"],
                "anchor_id": trace["anchor_id"],
                "source_record_id": trace["source_record_id"],
            },
        },
        "evidence_traces": evidence_traces,
        "integrity": {"status": "pass", "orphan_count": 0},
    }


def measure_capture(scenario: dict[str, Any], *, iterations: int) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be greater than zero")
    samples_ms: list[float] = []
    for _ in range(iterations):
        started = perf_counter()
        capture_baseline(scenario)
        samples_ms.append((perf_counter() - started) * 1000)
    ordered = sorted(samples_ms)
    median = ordered[len(ordered) // 2]
    p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]
    return {
        "iterations": iterations,
        "median_ms": round(median, 3),
        "p95_ms": round(p95, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture a deterministic persistence migration baseline."
    )
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=0)
    args = parser.parse_args(argv)

    scenario = json.loads(args.fixture.read_text(encoding="utf-8"))
    baseline = capture_baseline(scenario)
    payload: dict[str, Any] = baseline
    if args.iterations:
        payload = {
            "baseline": baseline,
            "performance": measure_capture(scenario, iterations=args.iterations),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
