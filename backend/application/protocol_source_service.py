from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ProtocolArtifactPaths:
    base_dir: Path
    documents: Path
    text_units: Path
    sections: Path
    procedure_blocks: Path


def resolve_protocol_artifact_paths(base_dir: str | Path) -> ProtocolArtifactPaths:
    base_path = Path(base_dir).expanduser().resolve()
    return ProtocolArtifactPaths(
        base_dir=base_path,
        documents=base_path / "documents.parquet",
        text_units=base_path / "text_units.parquet",
        sections=base_path / "sections.parquet",
        procedure_blocks=base_path / "procedure_blocks.parquet",
    )


def load_protocol_inputs(base_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    paths = resolve_protocol_artifact_paths(base_dir)
    documents = pd.read_parquet(paths.documents)
    text_units: pd.DataFrame | None = None
    if paths.text_units.is_file():
        text_units = pd.read_parquet(paths.text_units)
    return documents, text_units


def build_document_records(
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if "id" not in documents.columns:
        raise ValueError("documents dataframe missing required 'id' column")
    if "text" not in documents.columns and text_units is None:
        raise ValueError("documents dataframe missing 'text' and no text_units fallback provided")

    text_unit_ids_by_doc: dict[str, list[str]] = {}
    if text_units is not None and {"id", "text"}.issubset(text_units.columns):
        for _, row in text_units.iterrows():
            text_unit_id = str(row.get("id"))
            for doc_id in _listify(row.get("document_ids")):
                text_unit_ids_by_doc.setdefault(str(doc_id), []).append(text_unit_id)

    rows: list[dict[str, Any]] = []
    for _, row in documents.iterrows():
        paper_id = str(row.get("id"))
        text = str(row.get("text") or "").strip()
        if not text and text_units is not None:
            text = _join_text_units_for_document(text_units, paper_id)
        rows.append(
            {
                "paper_id": paper_id,
                "title": _coerce_optional_text(row.get("title")) or paper_id,
                "text": text,
                "text_unit_ids": text_unit_ids_by_doc.get(paper_id, []),
            }
        )

    return pd.DataFrame(rows, columns=["paper_id", "title", "text", "text_unit_ids"])


def persist_sections(base_dir: str | Path, sections: pd.DataFrame) -> Path:
    paths = resolve_protocol_artifact_paths(base_dir)
    paths.base_dir.mkdir(parents=True, exist_ok=True)
    sections.to_parquet(paths.sections, index=False)
    return paths.sections


def persist_procedure_blocks(base_dir: str | Path, procedure_blocks: pd.DataFrame) -> Path:
    paths = resolve_protocol_artifact_paths(base_dir)
    paths.base_dir.mkdir(parents=True, exist_ok=True)
    procedure_blocks.to_parquet(paths.procedure_blocks, index=False)
    return paths.procedure_blocks


def _join_text_units_for_document(text_units: pd.DataFrame, paper_id: str) -> str:
    matched: list[str] = []
    for _, row in text_units.iterrows():
        if paper_id not in {str(item) for item in _listify(row.get("document_ids"))}:
            continue
        text = str(row.get("text") or "").strip()
        if text:
            matched.append(text)
    return "\n".join(matched)


def _coerce_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                return [text]
            if isinstance(parsed, list):
                return parsed
        return [text]
    if pd.isna(value):
        return []
    return [value]
