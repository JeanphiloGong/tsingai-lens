from application.source import agent_source_service as document_sources
from application.source import agent_workspace_service as workspace_context
from infra.persistence import database
from copy import deepcopy
from tests.support.source_artifacts import build_source_documents
from tests.support.postgres import seed_workspace
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.source.agent_workspace_service import (
    BrowseWorkspacePapersService,
    BrowseWorkspacePapersToolRequest,
)
from agent.tools.registry import ToolExecutionContext
from application.source.agent_source_service import (
    InspectDocumentSourcesService,
    InspectDocumentSourcesToolRequest,
)
from document.domain.source import SourceBlock, SourceDocument
from repositories.document_profile_repository import DocumentProfileRepository
from repositories.paper_map_repository import PaperMapRepository
from document.repositories.source_repository import SourceRepository


from workspace.domain.workspace import Workspace
from document.domain.document import Document
from repositories.workspace_repository import StoredWorkspace, StoredDocument


def stored_workspace(records):
    return StoredWorkspace(
        workspace=Workspace("workspace-1", "user-1", "Papers", None, "idle"),
        created_at="2026-11-01", updated_at="2026-11-01",
        documents=tuple(
            StoredDocument(
                document=Document(document_id=item["document_id"], filename=item.get("filename", item["document_id"]), sha256="digest", media_type=None, size_bytes=0),
                storage_key="workspace/input/" + item["document_id"], created_at="2026-11-01",
                status=item.get("status", "stored"),
            )
            for item in records
        ),
    )


def document(text, heading="Paper title"):
    return SimpleNamespace(
        document_id="paper-1",
        document_order=0,
        title="Paper title",
        text=text,
        blocks=(SourceBlock(
            block_id="block-1", document_id="paper-1", block_type="paragraph",
            text=text, block_order=0, heading_path=heading,
        ),),
        tables=(),
        figures=(),
    )


@pytest.mark.parametrize("label", ["Abstract:", "ABSTRACT :", "Abstract —", "Abstract–", "摘要："])
def test_inline_abstract_is_read_without_an_abstract_heading(label):
    assert BrowseWorkspacePapersService._abstract_excerpt(
        document(f"{label}\nPreheating changes residual stress.")
    ) == ("Preheating changes residual stress.", "found")


def test_labelled_section_takes_precedence_over_inline_label():
    source = document("Abstract: Inline paragraph.")
    source.blocks += (SourceBlock(
        block_id="block-2", document_id="paper-1", block_type="paragraph",
        text="Section abstract.", block_order=1, heading_path="Abstract",
    ),)
    assert BrowseWorkspacePapersService._abstract_excerpt(source) == (
        "Section abstract.", "found",
    )


@pytest.mark.parametrize("text,heading", [
    ("We describe an abstract model of preheating.", "Introduction"),
    ("Abstract: A cited paper summary.", "References"),
    ("Abstract: A cited paper summary.", "Bibliography"),
    ("摘要：引用论文摘要。", "参考文献"),
    ("Abstract theory predicts residual stress.", "Introduction"),
    ("Abstract:\n ", "Paper title"),
    ("Keywords: titanium, preheating", "Paper title"),
])
def test_missing_or_incidental_abstract_is_not_invented(text, heading):
    assert BrowseWorkspacePapersService._abstract_excerpt(document(text, heading)) == (
        None, "not_found",
    )


def test_unprepared_source_remains_unprepared():
    assert BrowseWorkspacePapersService._abstract_excerpt(None) == (None, "source_not_ready")


@pytest.mark.parametrize("text,expected_status", [
    ("Abstract: Preheating changes residual stress.", "found"),
    ("No explicitly labelled abstract is available.", "not_found"),
])
def test_browse_prepared_paper_reports_only_real_screening_limitations(text, expected_status):
    workspace_context.workspace_service = SimpleNamespace(get_workspace_for_user=AsyncMock(return_value=stored_workspace([{"document_id": "paper-1", "filename": "Preheating.pdf", "status": "ready"}])))
    workspace_context.DocumentProfileRepo = SimpleNamespace(list_workspace=AsyncMock(return_value=[
            SimpleNamespace(document_id="paper-1", title="Preheating", doc_type="experimental", confidence=0.9),
        ]))
    workspace_context.PaperMapRepo = SimpleNamespace(list_workspace=AsyncMock(return_value=[
            SimpleNamespace(document_id="paper-1", map_status="sufficient", studies=(), map_limitations=()),
        ]))
    workspace_context.SourceRepo = SimpleNamespace(read_document=AsyncMock(return_value=document(text)))
    capability = BrowseWorkspacePapersService()
    result = asyncio.run(capability.execute(
        user_id="user-1", workspace_id="workspace-1",
        tool_call_id="call-1", max_result_tokens=12_000,
        arguments=BrowseWorkspacePapersToolRequest(),
    ))
    paper = result.data["papers"][0]
    assert paper["abstract_status"] == expected_status
    assert result.warnings == ()
    assert paper["source_status"] == "available"
    assert bool(paper["screening_limitations"]) == (expected_status == "not_found")
    assert paper["support_is_evidence"] is False
    assert any(ref.resource_id == "paper-1" for ref in result.resource_refs)
    workspace_context.SourceRepo.read_document.assert_awaited_once_with("workspace-1", "paper-1")


@pytest.mark.parametrize("missing,document_status", [
    ("profile", "ready"), ("map", "ready"), ("insufficient_map", "ready"),
    ("abstract", "ready"), ("profile", "failed"),
])
def test_optional_screening_information_does_not_require_researcher_intervention(missing, document_status):
    profile = SimpleNamespace(
        document_id="paper-1", title="LPBF preheating", doc_type="experimental", confidence=0.9
    )
    paper_map = SimpleNamespace(
        document_id="paper-1", studies=(), map_status="sufficient", map_limitations=()
    )
    if missing == "insufficient_map":
        paper_map.map_status = "insufficient_map"
        paper_map.map_limitations = ("Process scope is not mapped.",)
    workspace_context.workspace_service = SimpleNamespace(get_workspace_for_user=AsyncMock(return_value=stored_workspace([{"document_id": "paper-1", "filename": "LPBF preheating.pdf", "status": document_status}])))
    workspace_context.DocumentProfileRepo = SimpleNamespace(list_workspace=AsyncMock(
            return_value=[] if missing == "profile" else [profile]
        ))
    workspace_context.PaperMapRepo = SimpleNamespace(list_workspace=AsyncMock(
            return_value=[] if missing == "map" else [paper_map]
        ))
    workspace_context.SourceRepo = SimpleNamespace(read_document=AsyncMock(return_value=document(
            "Preheating temperature was varied." if missing == "abstract" else "Abstract: LPBF preheating study."
        )))
    capability = BrowseWorkspacePapersService()
    result = asyncio.run(capability.execute(
        user_id="u", workspace_id="c",
        tool_call_id="t", max_result_tokens=12_000,
        arguments=BrowseWorkspacePapersToolRequest(),
    ))
    assert result.status == "succeeded"
    assert result.warnings == ()
    assert result.data["papers"][0]["source_status"] == "available"
    assert result.data["papers"][0]["screening_limitations"]


def test_browse_keeps_progress_and_real_source_failures_separate(caplog):
    records = [
        {"document_id": "paper-1", "filename": "LPBF preheating.pdf", "status": "ready"},
        {"document_id": "paper-2", "filename": "Processing.pdf", "status": "processing"},
        {"document_id": "paper-3", "filename": "Stored.pdf", "status": "stored"},
        {"document_id": "paper-4", "filename": "Preparation failed.pdf", "status": "failed"},
        {"document_id": "paper-5", "filename": "Source unavailable.pdf", "status": "ready"},
        {"document_id": "paper-6", "filename": "Read failed.pdf", "status": "ready"},
        {"document_id": "paper-7", "filename": "Later paper.pdf", "status": "ready"},
    ]

    async def read_source(_workspace_id, document_id):
        if document_id == "paper-6":
            raise OSError("private-storage-detail")
        return document("Abstract: LPBF study.") if document_id == "paper-1" else None

    workspace_context.workspace_service = SimpleNamespace(get_workspace_for_user=AsyncMock(return_value=stored_workspace(records)))
    workspace_context.DocumentProfileRepo = SimpleNamespace(list_workspace=AsyncMock(return_value=[]))
    workspace_context.PaperMapRepo = SimpleNamespace(list_workspace=AsyncMock(return_value=[]))
    workspace_context.SourceRepo = SimpleNamespace(read_document=AsyncMock(side_effect=read_source))
    capability = BrowseWorkspacePapersService()
    context = ToolExecutionContext(operation_id="operation", task_id="s", user_id="u", workspace_id="c", tool_call_id="t")
    result = asyncio.run(capability.execute(user_id=context.user_id, workspace_id=context.workspace_id, tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens, arguments= BrowseWorkspacePapersToolRequest(limit=6)))
    assert [paper["source_status"] for paper in result.data["papers"]] == [
        "available", "preparing", "not_prepared", "preparation_failed", "unavailable", "read_failed"
    ]
    assert result.data["next_offset"] == 6
    assert result.data["paper_total"] == 7
    assert len(result.warnings) == 1
    assert "3" in result.warnings[0]
    assert "private-storage-detail" not in str({
        "tool_call_id": result.tool_call_id,
        "status": result.status.value,
        "data": deepcopy(dict(result.data)),
        "resource_refs": [
            {
                "resource_type": item.resource_type,
                "resource_id": item.resource_id,
                "href": item.href,
            }
            for item in result.resource_refs
        ],
        "warnings": list(result.warnings),
        "error_code": result.error_code,
        "error_message": result.error_message,
    })
    assert "paper-6" in caplog.text

    miss = asyncio.run(capability.execute(user_id=context.user_id, workspace_id=context.workspace_id, tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens, arguments= BrowseWorkspacePapersToolRequest(query="not-a-filename")))
    assert miss.data["papers"] == []
    assert miss.warnings == ()


def test_normal_pagination_is_not_a_warning():
    workspace_context.workspace_service = SimpleNamespace(get_workspace_for_user=AsyncMock(return_value=stored_workspace([{"document_id": f"paper-{i}", "status": "ready"} for i in range(10)])))
    workspace_context.DocumentProfileRepo = SimpleNamespace(list_workspace=AsyncMock(return_value=[]))
    workspace_context.PaperMapRepo = SimpleNamespace(list_workspace=AsyncMock(return_value=[]))
    workspace_context.SourceRepo = SimpleNamespace(read_document=AsyncMock(return_value=document("Methods text.")))
    capability = BrowseWorkspacePapersService()
    result = asyncio.run(capability.execute(
        user_id="u", workspace_id="c",
        tool_call_id="t", max_result_tokens=12_000,
        arguments=BrowseWorkspacePapersToolRequest(limit=8),
    ))
    assert result.warnings == ()
    assert result.data["next_offset"] == 8
    assert result.data["returned_paper_count"] == 8


def test_browse_can_continue_to_source_read_when_optional_metadata_is_missing(*, postgres_session_factory):
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "agent_p002" / "source_document.json"
    record = json.loads(fixture.read_text(encoding="utf-8"))
    record["id"] = record["document_id"]
    source_document = build_source_documents(
        documents=[record],
        text_units=record.get("text_units", ()),
        blocks=record.get("blocks", ()),
        tables=record.get("tables", ()),
        table_rows=record.get("table_rows", ()),
        table_cells=record.get("table_cells", ()),
        figures=record.get("figures", ()),
    )[0]
    records = [
        {
            "document_id": source_document.document_id,
            "filename": "P002-preheating.pdf",
            "status": "ready",
        },
        {
            "document_id": "paper-2",
            "filename": "Missing.pdf",
            "status": "ready",
        },
    ]
    workspace_service = SimpleNamespace(
        get_workspace_for_user=AsyncMock(return_value=stored_workspace(records)),
        get_document=AsyncMock(return_value=records[1]),
    )
    sources = SourceRepository()
    workspace_context.workspace_service = workspace_service
    workspace_context.DocumentProfileRepo = DocumentProfileRepository()
    workspace_context.PaperMapRepo = PaperMapRepository()
    workspace_context.SourceRepo = sources
    browse = BrowseWorkspacePapersService()
    document_sources.workspace_service = workspace_service
    document_sources.SourceRepo = sources
    inspect = InspectDocumentSourcesService()
    context = ToolExecutionContext(
        operation_id="operation",
        task_id="s", user_id="u", workspace_id="c", tool_call_id="browse"
    )

    async def scenario():
        await seed_workspace(database.AsyncSessionLocal, 'c', document_ids=(source_document.document_id,))
        await sources.replace_document("c", source_document)
        survey = await browse.execute(user_id=context.user_id, workspace_id=context.workspace_id, tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens, arguments= BrowseWorkspacePapersToolRequest())
        assert [paper["source_status"] for paper in survey.data["papers"]] == ["available", "unavailable"]
        assert len(survey.warnings) == 1
        selected = await browse.execute(user_id=context.user_id, workspace_id=context.workspace_id, tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens, arguments= BrowseWorkspacePapersToolRequest(query="P002"))
        assert selected.warnings == ()
        paper = selected.data["papers"][0]
        assert paper["abstract_status"] == "not_found"
        assert paper["map_status"] == "not_available"

        outline = await inspect.execute(user_id=context.user_id, workspace_id=context.workspace_id, tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens, arguments= InspectDocumentSourcesToolRequest(
            document_id=paper["document_id"], limit=1,
        ))
        heading = next(section["heading_path"] for section in outline.data["document_outline"]
                       if section["heading_path"] == "Experimental Procedures")
        read = await inspect.execute(user_id=context.user_id, workspace_id=context.workspace_id, tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens, arguments= InspectDocumentSourcesToolRequest(
            document_id=paper["document_id"], heading_path=heading,
        ))
        assert read.status == "succeeded"
        assert read.data["returned_source_count"] == 1
        assert read.data["sources"][0]["content"] == source_document.blocks[0].text
        assert read.data["sources"][0]["content_truncated"] is False
        assert read.data["sources"][0]["source_digest"]
        assert any(ref.resource_type == "source" for ref in read.resource_refs)
        missing = await inspect.execute(user_id=context.user_id, workspace_id=context.workspace_id, tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens, arguments= InspectDocumentSourcesToolRequest(document_id="paper-2"))
        assert missing.status == "failed"
        assert missing.error_code == "document_sources_not_ready"

    asyncio.run(scenario())
