from __future__ import annotations

import ast
import json
import re
from typing import Any

import pandas as pd
from fastapi import HTTPException

from application.derived.protocol.document_meta_service import load_document_title_map
from infra.persistence.factory import build_protocol_artifact_repository


protocol_artifact_repository = build_protocol_artifact_repository()


def _read_steps(collection_id: str) -> pd.DataFrame:
    artifacts = protocol_artifact_repository.read_collection_artifacts(collection_id)
    if not artifacts.protocol_steps:
        raise HTTPException(status_code=404, detail="protocol steps 不存在")
    return pd.DataFrame([dict(record) for record in artifacts.protocol_steps])


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


def _resolve_paper_id(row: pd.Series) -> str | None:
    value = _to_python(row.get("paper_id"))
    if isinstance(value, str) and value.strip():
        return value.strip()
    evidence = _to_list(row.get("evidence_refs"))
    for ref in evidence:
        if isinstance(ref, dict) and ref.get("paper_id"):
            return str(ref["paper_id"])
    return None


def _stringify(value: Any) -> str:
    parsed = _to_python(value)
    if parsed is None:
        return ""
    if isinstance(parsed, list):
        return " ".join(_stringify(item) for item in parsed)
    if isinstance(parsed, dict):
        return " ".join(f"{key} {_stringify(val)}" for key, val in parsed.items())
    return str(parsed)


def _row_payload(row: pd.Series, title_map: dict[str, str] | None = None) -> dict[str, Any]:
    paper_id = _resolve_paper_id(row)
    return {
        "step_id": str(row.get("step_id") or row.get("id") or ""),
        "paper_id": paper_id,
        "paper_title": (title_map or {}).get(paper_id or ""),
        "order": _to_python(row.get("order")),
        "action": _stringify(row.get("action") or row.get("raw_text") or row.get("text")),
        "purpose": _to_python(row.get("purpose")),
        "block_type": _to_python(row.get("block_type")),
        "materials": _to_python(row.get("materials") or row.get("materials_json")),
        "characterization": _to_python(
            row.get("characterization") or row.get("characterization_json")
        ),
        "conditions": _to_python(row.get("conditions") or row.get("conditions_json")),
        "confidence_score": _to_python(row.get("confidence_score")),
    }


def search_protocol_steps(
    collection_id: str,
    query: str,
    limit: int = 10,
    paper_id: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    terms = [token.lower() for token in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", query) if token]
    if not terms:
        raise HTTPException(status_code=400, detail="q 不能为空")

    steps_df = _read_steps(collection_id)
    title_map = load_document_title_map(collection_id)
    if paper_id:
        steps_df = steps_df[steps_df.apply(lambda row: _resolve_paper_id(row) == paper_id, axis=1)]

    scored: list[dict[str, Any]] = []
    for _, row in steps_df.iterrows():
        payload = _row_payload(row, title_map)
        haystack = " ".join(
            [
                payload["action"],
                _stringify(payload.get("purpose")),
                _stringify(payload.get("materials")),
                _stringify(payload.get("conditions")),
                _stringify(payload.get("characterization")),
            ]
        ).lower()
        score = 0.0
        matched: list[str] = []
        for term in terms:
            if term in haystack:
                score += 1.0
                matched.append(term)
        if score <= 0:
            continue
        payload["score"] = score / float(len(terms))
        payload["matched_terms"] = sorted(set(matched))
        scored.append(payload)

    scored.sort(
        key=lambda item: (
            float(item["score"]),
            float(item.get("confidence_score") or 0.0),
        ),
        reverse=True,
    )
    items = scored[:limit]
    return {
        "output_path": output_path,
        "query": query,
        "paper_id": paper_id,
        "count": len(items),
        "items": items,
    }
