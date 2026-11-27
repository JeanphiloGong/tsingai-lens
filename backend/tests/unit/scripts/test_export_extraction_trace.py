from __future__ import annotations

from infra.persistence import database
from tests.support.postgres import seed_workspace

from tests.support.source_artifacts import build_source_documents

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from document.domain import DocumentProfile
from domain.core.finding import Finding, FindingPaperContribution
from domain.core.research_objective import ObjectiveEvidence
from domain.core.scientific_fact import ScientificContext
from document.repositories.profile_repository import ProfileRepository
from research.discovery.repositories.paper_map_repository import PaperMapRepository
from document.repositories.source_repository import SourceRepository


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


class _ObjectiveRepository:
    async def read_analysis(self, *args):
        return SimpleNamespace(
            status="succeeded", origin="human_authored", scientific_record_source="authored_snapshot"
        )

    async def list_objectives(self, workspace_id: str):
        return (
            SimpleNamespace(
                objective_id="obj-1",
                published_analysis_version=1,
            ),
        )

    async def list_evidence(self, *args, **kwargs):
        records = (
            ObjectiveEvidence(
                workspace_id="col-test",
                objective_id="obj-1",
                analysis_version=1,
                evidence_id="ev-1",
                document_id="paper-1",
                source_kind="table",
                source_ref="tbl-paper-1-1",
                source_excerpt="Sample A reached 560 MPa.",
                page_numbers=(),
                related_source_refs=(),
                evidence_role="direct_result",
                selection_status="candidate",
                selection_reason=None,
                changed_variables=(),
                comparison=None,
                reported_result=None,
                attribution_scope="descriptive_only",
                scientific_context=ScientificContext(),
                resolution_status="unknown",
                failure_reason=None,
                confidence=0.0,
            ),
        )
        return records, len(records)

    async def list_findings(self, *args, **kwargs):
        records = (
            Finding(
                workspace_id="col-test",
                objective_id="obj-1",
                analysis_version=1,
                finding_id="finding-1",
                statement="Sample A reached 560 MPa in the reported test.",
                factors=("treatment",),
                outcome="strength",
                direction="unknown",
                assertion_strength="descriptive",
                attribution_scope="descriptive_only",
                synthesis_status="insufficient_confirmation",
                certainty=0.0,
                display_rank=0,
                mechanisms=(),
                scientific_context=ScientificContext(),
                limitations=(),
                paper_contributions=(
                    FindingPaperContribution(
                        document_id="paper-1",
                        analysis_status="analyzed",
                        supporting_evidence_ids=("ev-1",),
                    ),
                ),
            ),
        )
        return records, len(records)


@pytest.mark.anyio
async def test_export_trace_writes_current_source_and_objective_views(tmp_path, monkeypatch, *, postgres_session_factory):
    trace = _load_trace_module()
    source_repository = SourceRepository()
    source_document = build_source_documents(
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
    await seed_workspace(database.AsyncSessionLocal, 'col-test', document_ids=(source_document.document_id,))
    await source_repository.replace_document("col-test", source_document)
    profile_repository = ProfileRepository()
    await profile_repository.replace(
        "col-test",
        DocumentProfile(
            document_id="paper-1",
            description="Trace Paper",
            doc_type="experimental",
            source_fingerprint="source-test",
            profile_fingerprint="profile-test",
            profile_version="document_profile.v2",
            generated_at="2026-01-01T00:00:00Z",
        )
    )
    monkeypatch.setattr(
        trace,
        "build_database_engine",
        lambda _settings: SimpleNamespace(dispose=AsyncMock()),
    )
    monkeypatch.setattr(trace.AsyncSessionLocal, "configure", lambda **_kwargs: None)
    monkeypatch.setattr(
        trace,
        "SourceRepository",
        lambda: source_repository,
    )
    monkeypatch.setattr(
        trace,
        "ProfileRepository",
        lambda: profile_repository,
    )
    monkeypatch.setattr(
        trace,
        "PaperMapRepository",
        lambda: PaperMapRepository(),
    )
    monkeypatch.setattr(
        trace,
        "ObjectiveRepository",
        lambda: _ObjectiveRepository(),
    )

    trace_dir = await trace.export_trace(
        backend_root=tmp_path,
        workspace_id="col-test",
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
