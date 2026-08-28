from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from domain.core import DocumentProfile
from domain.source import source_documents_from_records
from infra.persistence.memory import (
    MemoryDocumentProfileRepository,
    MemoryPaperMapRepository,
    MemorySourceArtifactRepository,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _load_trace_module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "export_extraction_trace.py"
    spec = importlib.util.spec_from_file_location("export_extraction_trace", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Record:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def to_record(self) -> dict:
        return dict(self.payload)


class _ObjectiveRepository:
    async def list_objectives(self, collection_id: str):
        return (
            SimpleNamespace(
                objective_id="obj-1",
                published_analysis_version=1,
            ),
        )

    async def list_evidence(self, *args, **kwargs):
        records = (
            _Record(
                {
                    "evidence_id": "ev-1",
                    "document_id": "paper-1",
                    "source_kind": "table",
                    "source_ref": "tbl-paper-1-1",
                    "source_excerpt": "Sample A reached 560 MPa.",
                }
            ),
        )
        return records, len(records)

    async def list_findings(self, *args, **kwargs):
        records = (
            _Record(
                {
                    "finding_id": "finding-1",
                    "statement": "Sample A reached 560 MPa in the reported test.",
                }
            ),
        )
        return records, len(records)


@pytest.mark.anyio
async def test_export_trace_writes_current_source_and_objective_views(
    tmp_path,
    monkeypatch,
):
    trace = _load_trace_module()
    source_repository = MemorySourceArtifactRepository()
    source_document = source_documents_from_records(
        documents=[
            {
                "id": "paper-1",
                "title": "Trace Paper",
                "text": "Table 1 Mechanical Results",
            }
        ],
        tables=[
            {
                "table_id": "tbl-paper-1-1",
                "document_id": "paper-1",
                "table_order": 1,
                "caption_text": "Table 1 Mechanical Results",
                "page": 5,
                "column_headers": ["Sample", "Strength (MPa)"],
                "table_matrix": [["Sample", "Strength (MPa)"], ["A", "560"]],
            }
        ],
    )[0]
    await source_repository.replace_document("col-test", source_document)
    profile_repository = MemoryDocumentProfileRepository()
    await profile_repository.replace(
        DocumentProfile.from_mapping(
            {
                "document_id": "paper-1",
                "collection_id": "col-test",
                "title": "Trace Paper",
                "doc_type": "experimental",
                "parsing_warnings": [],
                "confidence": 0.9,
            }
        )
    )
    monkeypatch.setattr(
        trace,
        "build_database_engine",
        lambda _settings: SimpleNamespace(dispose=AsyncMock()),
    )
    monkeypatch.setattr(trace, "build_session_factory", lambda _engine: None)
    monkeypatch.setattr(
        trace,
        "PostgresSourceArtifactRepository",
        lambda _sessions: source_repository,
    )
    monkeypatch.setattr(
        trace,
        "PostgresDocumentProfileRepository",
        lambda _sessions: profile_repository,
    )
    monkeypatch.setattr(
        trace,
        "PostgresPaperMapRepository",
        lambda _sessions: MemoryPaperMapRepository(),
    )
    monkeypatch.setattr(
        trace,
        "PostgresObjectiveRepository",
        lambda _sessions: _ObjectiveRepository(),
    )

    trace_dir = await trace.export_trace(
        backend_root=tmp_path,
        collection_id="col-test",
        trace_name="trace-test",
    )

    summary = json.loads((trace_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["artifact_rows"]["tables"] == 1
    assert summary["artifact_rows"]["objective_evidence"] == 1
    assert (trace_dir / "artifacts" / "tables.json").is_file()
    assert "Table 1 Mechanical Results" in (trace_dir / "source_tables.md").read_text(
        encoding="utf-8"
    )
    objective_trace = (trace_dir / "extraction_trace.md").read_text(
        encoding="utf-8"
    )
    assert "Sample A reached 560 MPa in the reported test." in objective_trace
    assert "Sample A reached 560 MPa." in objective_trace
