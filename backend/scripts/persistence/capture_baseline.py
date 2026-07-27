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
    "objective_analyses",
    "objective_paper_contributions",
    "objective_evidence",
    "objective_findings",
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
        if family != "source_figures" and not records[family]:
            raise ValueError(f"required record family is empty: {family}")

    collections = {item["collection_id"]: item for item in records["collections"]}
    documents = {item["id"]: item for item in records["source_documents"]}
    text_units = {item["id"]: item for item in records["source_text_units"]}
    blocks = {item["block_id"]: item for item in records["source_blocks"]}
    files_by_document = {
        item["document_id"]: item for item in records["collection_files"]
    }
    anchors = {
        item["anchor_id"]: item for item in records["core_evidence_anchors"]
    }
    objectives = {
        (item["collection_id"], item["objective_id"]): item
        for item in records["research_objectives"]
    }
    analyses = {
        (item["collection_id"], item["objective_id"], item["analysis_version"]): item
        for item in records["objective_analyses"]
    }
    evidence_by_key = {
        (
            item["collection_id"],
            item["objective_id"],
            item["analysis_version"],
            item["evidence_id"],
        ): item
        for item in records["objective_evidence"]
    }
    findings_by_key = {
        (
            item["collection_id"],
            item["objective_id"],
            item["analysis_version"],
            item["finding_id"],
        ): item
        for item in records["objective_findings"]
    }

    traces: list[dict[str, Any]] = []
    for finding_key, finding in findings_by_key.items():
        collection_id, objective_id, analysis_version, finding_id = finding_key
        if (collection_id, objective_id) not in objectives:
            raise ValueError(f"unresolved finding objective: {objective_id}")
        if (collection_id, objective_id, analysis_version) not in analyses:
            raise ValueError(f"unresolved finding analysis version: {analysis_version}")
        derivation = finding.get("derivation") or {}
        supporting_ids = derivation.get("supporting_evidence_ids") or []
        if not supporting_ids:
            raise ValueError(f"finding has no supporting evidence: {finding_id}")
        for evidence_id in supporting_ids:
            evidence = evidence_by_key.get(
                (collection_id, objective_id, analysis_version, evidence_id)
            )
            if evidence is None:
                raise ValueError(f"unresolved finding evidence: {evidence_id}")
            if evidence.get("evidence_role") != "direct_result":
                raise ValueError(f"non-direct finding evidence: {evidence_id}")
            traces.append(
                _source_trace(
                    finding_id=finding_id,
                    evidence=evidence,
                    documents=documents,
                    blocks=blocks,
                    text_units=text_units,
                    anchors=anchors,
                    files_by_document=files_by_document,
                )
            )

    for family in ("feedback", "curations"):
        for item in records[family]:
            key = (
                item.get("collection_id"),
                item.get("objective_id"),
                item.get("analysis_version"),
                item.get("finding_id"),
            )
            if key not in findings_by_key:
                raise ValueError(f"unresolved {family[:-1]} finding: {key[-1]}")
            for evidence_id in item.get("curated_evidence_ids", []):
                evidence_key = (*key[:3], evidence_id)
                if evidence_key not in evidence_by_key:
                    raise ValueError(f"unresolved curation evidence: {evidence_id}")

    if not traces:
        raise ValueError("scenario has no complete Finding evidence trace")
    collection = records["collections"][0]
    task = records["tasks"][0]
    artifacts = records["artifacts"][0]
    objective = records["research_objectives"][0]
    analysis = analyses[
        (
            objective["collection_id"],
            objective["objective_id"],
            objective["published_analysis_version"],
        )
    ]
    trace = traces[0]
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
        "objective_evidence": "evidence_id",
        "objective_findings": "finding_id",
        "goal_messages": "message_id",
        "feedback": "feedback_id",
        "curations": "curation_id",
        "evaluation_runs": "evaluation_run_id",
    }
    field_sources = {
        "collection": collection,
        "task": task,
        "source_document": records["source_documents"][0],
        "measurement_result": records["core_measurement_results"][0],
        "objective_finding": records["objective_findings"][0],
        "feedback": records["feedback"][0],
        "evaluation_run": records["evaluation_runs"][0],
    }
    collection_id = collection["collection_id"]
    document_id = trace["document_id"]
    return {
        "schema_version": "persistence-baseline.v1",
        "scenario_id": scenario["scenario_id"],
        "record_counts": {
            family: len(records[family]) for family in REQUIRED_FAMILIES
        },
        "ordered_ids": {
            family: [item[id_field] for item in records[family]]
            for family, id_field in id_fields.items()
        },
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
            "objective_analysis": {
                "endpoint": (
                    f"/api/v1/collections/{collection_id}/objectives/"
                    f"{objective['objective_id']}/analysis"
                ),
                "status_code": 200,
                "objective_id": objective["objective_id"],
                "analysis_version": analysis["analysis_version"],
                "status": analysis["status"],
                "phase": analysis["phase"],
                "finding_count": len(records["objective_findings"]),
                "evidence_count": len(records["objective_evidence"]),
            },
            "source_trace": {
                "endpoint": (
                    f"/api/v1/collections/{collection_id}/documents/"
                    f"{document_id}/source"
                ),
                "status_code": 200,
                "document_id": document_id,
                "source_filename": source_profile["source_filename"],
                "finding_id": trace["finding_id"],
                "evidence_id": trace["evidence_id"],
                "anchor_id": trace["anchor_id"],
                "source_record_id": trace["source_record_id"],
            },
        },
        "evidence_traces": traces,
        "integrity": {"status": "pass", "orphan_count": 0},
    }


def _source_trace(
    *,
    finding_id: str,
    evidence: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    blocks: dict[str, dict[str, Any]],
    text_units: dict[str, dict[str, Any]],
    anchors: dict[str, dict[str, Any]],
    files_by_document: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    document_id = evidence.get("document_id")
    if document_id not in documents:
        raise ValueError(f"unresolved evidence document: {document_id}")
    source_record_id = evidence.get("source_ref")
    source_block = blocks.get(source_record_id)
    if source_block is None:
        raise ValueError(f"unresolved evidence source block: {source_record_id}")
    text_unit_ids = source_block.get("text_unit_ids") or []
    text_unit_id = text_unit_ids[0] if text_unit_ids else None
    if text_unit_id not in text_units:
        raise ValueError(f"unresolved evidence text unit: {text_unit_id}")
    source_file = files_by_document.get(document_id)
    if source_file is None:
        raise ValueError(f"unresolved evidence collection file: {document_id}")
    anchor_ids = evidence.get("anchor_ids") or []
    anchor_id = anchor_ids[0] if anchor_ids else None
    if anchor_id not in anchors:
        raise ValueError(f"unresolved evidence anchor: {anchor_id}")
    if evidence.get("source_excerpt") not in (source_block.get("text") or ""):
        raise ValueError(
            f"evidence excerpt does not resolve to source block: {evidence['evidence_id']}"
        )
    return {
        "finding_id": finding_id,
        "evidence_id": evidence["evidence_id"],
        "anchor_id": anchor_id,
        "source_record_kind": "block",
        "source_record_id": source_record_id,
        "text_unit_id": text_unit_id,
        "document_id": document_id,
        "file_id": source_file["file_id"],
        "quote": evidence["source_excerpt"],
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
