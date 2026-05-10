from __future__ import annotations

import ast
import json
from typing import Any
from uuid import uuid4

import pandas as pd
from fastapi import HTTPException

from application.derived.protocol.document_meta_service import load_document_title_map
from infra.persistence.factory import build_protocol_artifact_repository


protocol_artifact_repository = build_protocol_artifact_repository()


def _frame(records: tuple[Any, ...]) -> pd.DataFrame | None:
    if not records:
        return None
    return pd.DataFrame([dict(record) for record in records])


def _to_python(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        for parser in (json.loads, ast.literal_eval):
            try:
                return parser(text)
            except Exception:
                continue
        return text
    return value


def _to_list(value: Any) -> list[Any]:
    parsed = _to_python(value)
    if parsed is None:
        return []
    if isinstance(parsed, list):
        return parsed
    return [parsed]


def _to_dict(value: Any) -> dict[str, Any]:
    parsed = _to_python(value)
    if isinstance(parsed, dict):
        return parsed
    return {}


def _safe_int(value: Any) -> int | None:
    parsed = _to_python(value)
    if parsed is None:
        return None
    try:
        return int(parsed)
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    parsed = _to_python(value)
    if parsed is None:
        return None
    try:
        return float(parsed)
    except Exception:
        return None


def _resolve_paper_id(row: pd.Series) -> str | None:
    explicit = _to_python(row.get("paper_id"))
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    evidence_refs = _to_list(row.get("evidence_refs"))
    for ref in evidence_refs:
        if isinstance(ref, dict) and ref.get("paper_id"):
            return str(ref["paper_id"])
    doc_ids = _to_list(row.get("document_ids"))
    if doc_ids:
        return str(doc_ids[0])
    return None


def _contains_paper(row: pd.Series, paper_ids: set[str]) -> bool:
    paper_id = _resolve_paper_id(row)
    return paper_id in paper_ids if paper_id else False


def _normalize_step(row: pd.Series, title_map: dict[str, str] | None = None) -> dict[str, Any]:
    conditions = _to_dict(row.get("conditions") or row.get("conditions_json"))
    characterization = _to_list(
        row.get("characterization") or row.get("characterization_json")
    )
    controls = _to_list(row.get("controls") or row.get("controls_json"))
    evidence_refs = _to_list(row.get("evidence_refs") or row.get("evidence_refs_json"))
    materials = _to_list(row.get("materials") or row.get("materials_json"))
    paper_id = _resolve_paper_id(row)
    return {
        "step_id": str(row.get("step_id") or row.get("id") or ""),
        "paper_id": paper_id,
        "paper_title": (title_map or {}).get(paper_id or ""),
        "section_id": _to_python(row.get("section_id")),
        "block_id": _to_python(row.get("block_id")),
        "block_type": _to_python(row.get("block_type")),
        "order": _safe_int(row.get("order")),
        "action": str(_to_python(row.get("action")) or row.get("raw_text") or row.get("text") or ""),
        "purpose": _to_python(row.get("purpose")),
        "expected_output": _to_python(row.get("expected_output")),
        "materials": materials,
        "conditions": conditions,
        "characterization": characterization,
        "controls": controls,
        "evidence_refs": evidence_refs,
        "confidence_score": _safe_float(row.get("confidence_score")),
        "validation_status": _to_python(row.get("validation_status")),
        "validation_errors": _to_list(row.get("validation_errors_json")),
    }


def _normalize_block(row: pd.Series) -> dict[str, Any]:
    return {
        "paper_id": _resolve_paper_id(row) or _to_python(row.get("paper_id")),
        "section_id": _to_python(row.get("section_id")),
        "block_id": _to_python(row.get("block_id")) or _to_python(row.get("id")),
        "source_block_id": _to_python(row.get("source_block_id")),
        "source_block_type": _to_python(row.get("source_block_type")),
        "heading_path": _to_python(row.get("heading_path")),
        "block_type": _to_python(row.get("block_type")),
        "text": _to_python(row.get("text")),
        "order": _safe_int(row.get("order")),
    }


def _measurement_plan(target_properties: list[str], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lowered = [item.lower() for item in target_properties]
    plan: list[dict[str, Any]] = []
    if not lowered or any("mechan" in item or "力学" in item for item in lowered):
        plan.append(
            {
                "property": "mechanical",
                "methods": ["tensile", "flexural", "fatigue"],
                "metrics": ["strength_MPa", "modulus_GPa", "elongation_pct"],
            }
        )
    if not lowered or any("therm" in item or "热" in item for item in lowered):
        plan.append(
            {
                "property": "thermal",
                "methods": ["DSC", "TGA", "thermal_conductivity"],
                "metrics": ["Tg_K", "decomposition_onset_K", "k_W_mK"],
            }
        )
    if not lowered or any("durab" in item or "aging" in item or "耐久" in item for item in lowered):
        plan.append(
            {
                "property": "durability",
                "methods": ["aging_test", "cyclic_loading", "corrosion_test"],
                "metrics": ["retention_pct", "lifetime_hours", "cycle_count"],
            }
        )

    discovered = []
    seen = set()
    for step in steps:
        for item in step.get("characterization", []):
            label = item.get("method") if isinstance(item, dict) else str(item)
            label = str(label).strip()
            if label and label not in seen:
                seen.add(label)
                discovered.append(label)
    if discovered:
        plan.append({"property": "characterization", "methods": discovered, "metrics": []})
    return plan


def _risk_checks(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for step in steps:
        conditions = step.get("conditions", {}) or {}
        temp_k = _safe_float(conditions.get("temperature_k") or conditions.get("temperature"))
        atmosphere = conditions.get("atmosphere")
        if isinstance(temp_k, float) and temp_k >= 1400:
            checks.append({"severity": "high", "message": f"Step {step.get('order')} temperature is high ({temp_k} K)."})
        if temp_k and not atmosphere:
            checks.append({"severity": "medium", "message": f"Step {step.get('order')} has temperature but no atmosphere."})
    if not checks:
        checks.append({"severity": "info", "message": "No critical conflicts detected from protocol artifacts."})
    return checks


def _open_questions(steps: list[dict[str, Any]]) -> list[str]:
    questions: list[str] = []
    for step in steps:
        conditions = step.get("conditions", {}) or {}
        if not conditions.get("temperature_k") and not conditions.get("temperature"):
            questions.append(f"Step {step.get('order')} missing temperature.")
        if not conditions.get("duration_s") and not conditions.get("duration"):
            questions.append(f"Step {step.get('order')} missing duration.")
    if not steps:
        questions.append("No protocol steps available in artifacts.")
    return questions[:10]


def _default_controls(steps: list[Any]) -> list[Any]:
    controls: list[Any] = []
    for step in steps:
        for control in step.get("controls", []):
            if control not in controls:
                controls.append(control)
    if controls:
        return controls
    return ["baseline_control"]


def load_protocol_artifacts(
    collection_id: str,
    output_path: str | None = None,
    paper_ids: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    paper_filter = set(paper_ids or [])
    artifacts = protocol_artifact_repository.read_collection_artifacts(collection_id)
    blocks_df = _frame(artifacts.procedure_blocks)
    steps_df = _frame(artifacts.protocol_steps)
    title_map = load_document_title_map(collection_id)

    if blocks_df is None and steps_df is None:
        raise HTTPException(status_code=404, detail="未找到 protocol 产物，请先生成 procedure blocks 和 protocol steps")

    if paper_filter:
        if blocks_df is not None:
            blocks_df = blocks_df[blocks_df.apply(lambda row: _contains_paper(row, paper_filter), axis=1)]
        if steps_df is not None:
            steps_df = steps_df[steps_df.apply(lambda row: _contains_paper(row, paper_filter), axis=1)]

    blocks = [] if blocks_df is None else [_normalize_block(row) for _, row in blocks_df.head(limit).iterrows()]
    steps = [] if steps_df is None else [_normalize_step(row, title_map) for _, row in steps_df.head(limit).iterrows()]

    return {
        "output_path": output_path,
        "paper_ids": sorted(paper_filter) if paper_filter else None,
        "summary": {
            "procedure_blocks": 0 if blocks_df is None else int(len(blocks_df)),
            "protocol_steps": 0 if steps_df is None else int(len(steps_df)),
        },
        "procedure_blocks": blocks,
        "protocol_steps": steps,
    }


def list_protocol_steps(
    collection_id: str,
    output_path: str | None = None,
    paper_id: str | None = None,
    block_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    artifacts = protocol_artifact_repository.read_collection_artifacts(collection_id)
    steps_df = _frame(artifacts.protocol_steps)
    if steps_df is None:
        raise HTTPException(status_code=404, detail="protocol steps 不存在")
    title_map = load_document_title_map(collection_id)

    if paper_id:
        steps_df = steps_df[steps_df.apply(lambda row: _resolve_paper_id(row) == paper_id, axis=1)]
    if block_type and "block_type" in steps_df.columns:
        steps_df = steps_df[steps_df["block_type"].astype(str) == block_type]

    normalized = [_normalize_step(row, title_map) for _, row in steps_df.iterrows()]
    normalized.sort(key=lambda item: ((item.get("paper_id") or ""), item.get("order") or 0, item.get("step_id") or ""))
    items = normalized[offset : offset + limit]
    return {
        "output_path": output_path,
        "paper_id": paper_id,
        "block_type": block_type,
        "total": len(normalized),
        "count": len(items),
        "items": items,
    }


def build_sop_draft(
    collection_id: str,
    output_path: str | None,
    goal: str,
    target_properties: list[str] | None = None,
    paper_ids: list[str] | None = None,
    max_steps: int = 12,
) -> dict[str, Any]:
    if not goal.strip():
        raise HTTPException(status_code=400, detail="goal 不能为空")

    payload = list_protocol_steps(
        collection_id=collection_id,
        output_path=output_path,
        limit=1000,
    )
    steps = payload["items"]
    if paper_ids:
        allowed = set(paper_ids)
        steps = [item for item in steps if item.get("paper_id") in allowed]
    steps = steps[:max_steps]

    properties = target_properties or []
    draft = {
        "sop_id": str(uuid4()),
        "version": 1,
        "objective": goal,
        "target_properties": properties,
        "paper_ids": paper_ids or sorted({step.get("paper_id") for step in steps if step.get("paper_id")}),
        "controls": _default_controls(steps),
        "steps": steps,
        "measurement_plan": _measurement_plan(properties, steps),
        "risk_checks": _risk_checks(steps),
        "open_questions": _open_questions(steps),
        "artifact_summary": payload["total"],
    }
    return {
        "output_path": output_path,
        "goal": goal,
        "count": len(steps),
        "sop_draft": draft,
    }
