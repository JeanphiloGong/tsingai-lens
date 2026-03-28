from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from fastapi import HTTPException


_SECTION_FILE = "sections.parquet"
_BLOCK_FILE = "procedure_blocks.parquet"
_STEP_FILE = "protocol_steps.parquet"


def _read_parquet_optional(path: Path) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"无法读取协议产物: {path.name}: {exc}") from exc


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


def _normalize_step(row: pd.Series) -> dict[str, Any]:
    conditions = _to_dict(row.get("conditions"))
    characterization = _to_list(row.get("characterization"))
    controls = _to_list(row.get("controls"))
    evidence_refs = _to_list(row.get("evidence_refs"))
    materials = _to_list(row.get("materials"))
    return {
        "step_id": str(row.get("step_id") or row.get("id") or ""),
        "paper_id": _resolve_paper_id(row),
        "section_id": _to_python(row.get("section_id")),
        "block_id": _to_python(row.get("block_id")),
        "block_type": _to_python(row.get("block_type")),
        "order": _safe_int(row.get("order")),
        "action": str(_to_python(row.get("action")) or row.get("text") or ""),
        "purpose": _to_python(row.get("purpose")),
        "expected_output": _to_python(row.get("expected_output")),
        "materials": materials,
        "conditions": conditions,
        "characterization": characterization,
        "controls": controls,
        "evidence_refs": evidence_refs,
        "confidence_score": _safe_float(row.get("confidence_score")),
    }


def _normalize_section(row: pd.Series) -> dict[str, Any]:
    return {
        "paper_id": _resolve_paper_id(row) or _to_python(row.get("paper_id")),
        "section_id": _to_python(row.get("section_id")) or _to_python(row.get("id")),
        "section_type": _to_python(row.get("section_type")),
        "title": _to_python(row.get("title")),
        "text": _to_python(row.get("text")),
        "order": _safe_int(row.get("order")),
        "language": _to_python(row.get("language")),
    }


def _normalize_block(row: pd.Series) -> dict[str, Any]:
    return {
        "paper_id": _resolve_paper_id(row) or _to_python(row.get("paper_id")),
        "section_id": _to_python(row.get("section_id")),
        "block_id": _to_python(row.get("block_id")) or _to_python(row.get("id")),
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


def _default_controls(steps: list[dict[str, Any]]) -> list[Any]:
    controls: list[Any] = []
    for step in steps:
        for control in step.get("controls", []):
            if control not in controls:
                controls.append(control)
    if controls:
        return controls
    return ["baseline_control"]


def load_protocol_artifacts(base_dir: Path, paper_ids: list[str] | None = None, limit: int = 50) -> dict[str, Any]:
    paper_filter = set(paper_ids or [])
    sections_df = _read_parquet_optional(base_dir / _SECTION_FILE)
    blocks_df = _read_parquet_optional(base_dir / _BLOCK_FILE)
    steps_df = _read_parquet_optional(base_dir / _STEP_FILE)

    if sections_df is None and blocks_df is None and steps_df is None:
        raise HTTPException(status_code=404, detail="未找到 protocol 产物，请先生成 sections/procedure_blocks/protocol_steps parquet")

    if paper_filter:
        if sections_df is not None:
            sections_df = sections_df[sections_df.apply(lambda row: _contains_paper(row, paper_filter), axis=1)]
        if blocks_df is not None:
            blocks_df = blocks_df[blocks_df.apply(lambda row: _contains_paper(row, paper_filter), axis=1)]
        if steps_df is not None:
            steps_df = steps_df[steps_df.apply(lambda row: _contains_paper(row, paper_filter), axis=1)]

    sections = [] if sections_df is None else [_normalize_section(row) for _, row in sections_df.head(limit).iterrows()]
    blocks = [] if blocks_df is None else [_normalize_block(row) for _, row in blocks_df.head(limit).iterrows()]
    steps = [] if steps_df is None else [_normalize_step(row) for _, row in steps_df.head(limit).iterrows()]

    return {
        "output_path": str(base_dir),
        "paper_ids": sorted(paper_filter) if paper_filter else None,
        "summary": {
            "sections": 0 if sections_df is None else int(len(sections_df)),
            "procedure_blocks": 0 if blocks_df is None else int(len(blocks_df)),
            "protocol_steps": 0 if steps_df is None else int(len(steps_df)),
        },
        "sections": sections,
        "procedure_blocks": blocks,
        "protocol_steps": steps,
    }


def list_protocol_steps(
    base_dir: Path,
    paper_id: str | None = None,
    block_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    steps_df = _read_parquet_optional(base_dir / _STEP_FILE)
    if steps_df is None:
        raise HTTPException(status_code=404, detail="protocol_steps.parquet 不存在")

    if paper_id:
        steps_df = steps_df[steps_df.apply(lambda row: _resolve_paper_id(row) == paper_id, axis=1)]
    if block_type and "block_type" in steps_df.columns:
        steps_df = steps_df[steps_df["block_type"].astype(str) == block_type]

    normalized = [_normalize_step(row) for _, row in steps_df.iterrows()]
    normalized.sort(key=lambda item: ((item.get("paper_id") or ""), item.get("order") or 0, item.get("step_id") or ""))
    items = normalized[offset : offset + limit]
    return {
        "output_path": str(base_dir),
        "paper_id": paper_id,
        "block_type": block_type,
        "total": len(normalized),
        "count": len(items),
        "items": items,
    }


def build_sop_draft(
    base_dir: Path,
    goal: str,
    target_properties: list[str] | None = None,
    paper_ids: list[str] | None = None,
    max_steps: int = 12,
) -> dict[str, Any]:
    if not goal.strip():
        raise HTTPException(status_code=400, detail="goal 不能为空")

    payload = list_protocol_steps(base_dir=base_dir, limit=1000)
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
        "output_path": str(base_dir),
        "goal": goal,
        "count": len(steps),
        "sop_draft": draft,
    }
