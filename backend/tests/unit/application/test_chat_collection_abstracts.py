from application.chat.capabilities import document_sources
from application.chat.capabilities import collection_context
from infra.persistence import database
from copy import deepcopy
from tests.support.source_artifacts import build_source_documents
from tests.support.postgres import seed_collection
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.chat.capabilities.collection_context import (
    BrowseCollectionPapersCapability,
    BrowseCollectionPapersToolRequest,
)
from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.capabilities.document_sources import (
    InspectDocumentSourcesCapability,
    InspectDocumentSourcesToolRequest,
)
from domain.source.artifacts import SourceBlock, SourceDocument
from repositories.document_profile_repository import DocumentProfileRepository
from repositories.paper_map_repository import PaperMapRepository
from repositories.source_artifact_repository import SourceArtifactRepository


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
    assert BrowseCollectionPapersCapability._abstract_excerpt(
        document(f"{label}\nPreheating changes residual stress.")
    ) == ("Preheating changes residual stress.", "found")


def test_labelled_section_takes_precedence_over_inline_label():
    source = document("Abstract: Inline paragraph.")
    source.blocks += (SourceBlock(
        block_id="block-2", document_id="paper-1", block_type="paragraph",
        text="Section abstract.", block_order=1, heading_path="Abstract",
    ),)
    assert BrowseCollectionPapersCapability._abstract_excerpt(source) == (
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
    assert BrowseCollectionPapersCapability._abstract_excerpt(document(text, heading)) == (
        None, "not_found",
    )


def test_unprepared_source_remains_unprepared():
    assert BrowseCollectionPapersCapability._abstract_excerpt(None) == (None, "source_not_ready")


@pytest.mark.parametrize("text,expected_status", [
    ("Abstract: Preheating changes residual stress.", "found"),
    ("No explicitly labelled abstract is available.", "not_found"),
])
def test_browse_prepared_paper_reports_only_real_screening_limitations(text, expected_status):
    collection_context.collection_service = SimpleNamespace(get_collection_for_user=AsyncMock(return_value={
            "documents": [{"document_id": "paper-1", "original_filename": "Preheating.pdf", "status": "ready"}],
        }))
    collection_context.DocumentProfileRepo = SimpleNamespace(list_collection=AsyncMock(return_value=[
            SimpleNamespace(document_id="paper-1", title="Preheating", doc_type="experimental", confidence=0.9),
        ]))
    collection_context.PaperMapRepo = SimpleNamespace(list_collection=AsyncMock(return_value=[
            SimpleNamespace(document_id="paper-1", map_status="sufficient", studies=(), map_limitations=()),
        ]))
    collection_context.SourceArtifactRepo = SimpleNamespace(read_document=AsyncMock(return_value=document(text)))
    capability = BrowseCollectionPapersCapability()
    result = asyncio.run(capability.execute(
        CapabilityExecutionContext(session_id="session-1", user_id="user-1", collection_id="collection-1", tool_call_id="call-1"),
        BrowseCollectionPapersToolRequest(),
    ))
    paper = result.data["papers"][0]
    assert paper["abstract_status"] == expected_status
    assert result.warnings == ()
    assert paper["source_status"] == "available"
    assert bool(paper["screening_limitations"]) == (expected_status == "not_found")
    assert paper["support_is_evidence"] is False
    assert any(ref.resource_id == "paper-1" for ref in result.resource_refs)
    collection_context.SourceArtifactRepo.read_document.assert_awaited_once_with("collection-1", "paper-1")


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
    collection_context.collection_service = SimpleNamespace(get_collection_for_user=AsyncMock(return_value={
            "documents": [{"document_id": "paper-1", "original_filename": "LPBF preheating.pdf", "status": document_status}],
        }))
    collection_context.DocumentProfileRepo = SimpleNamespace(list_collection=AsyncMock(
            return_value=[] if missing == "profile" else [profile]
        ))
    collection_context.PaperMapRepo = SimpleNamespace(list_collection=AsyncMock(
            return_value=[] if missing == "map" else [paper_map]
        ))
    collection_context.SourceArtifactRepo = SimpleNamespace(read_document=AsyncMock(return_value=document(
            "Preheating temperature was varied." if missing == "abstract" else "Abstract: LPBF preheating study."
        )))
    capability = BrowseCollectionPapersCapability()
    result = asyncio.run(capability.execute(
        CapabilityExecutionContext(session_id="s", user_id="u", collection_id="c", tool_call_id="t"),
        BrowseCollectionPapersToolRequest(),
    ))
    assert result.status == "succeeded"
    assert result.warnings == ()
    assert result.data["papers"][0]["source_status"] == "available"
    assert result.data["papers"][0]["screening_limitations"]


def test_browse_keeps_progress_and_real_source_failures_separate(caplog):
    records = [
        {"document_id": "paper-1", "original_filename": "LPBF preheating.pdf", "status": "ready"},
        {"document_id": "paper-2", "original_filename": "Processing.pdf", "status": "processing"},
        {"document_id": "paper-3", "original_filename": "Stored.pdf", "status": "stored"},
        {"document_id": "paper-4", "original_filename": "Preparation failed.pdf", "status": "failed"},
        {"document_id": "paper-5", "original_filename": "Source unavailable.pdf", "status": "ready"},
        {"document_id": "paper-6", "original_filename": "Read failed.pdf", "status": "ready"},
        {"document_id": "paper-7", "original_filename": "Later paper.pdf", "status": "ready"},
    ]

    async def read_source(_collection_id, document_id):
        if document_id == "paper-6":
            raise OSError("private-storage-detail")
        return document("Abstract: LPBF study.") if document_id == "paper-1" else None

    collection_context.collection_service = SimpleNamespace(get_collection_for_user=AsyncMock(return_value={"documents": records}))
    collection_context.DocumentProfileRepo = SimpleNamespace(list_collection=AsyncMock(return_value=[]))
    collection_context.PaperMapRepo = SimpleNamespace(list_collection=AsyncMock(return_value=[]))
    collection_context.SourceArtifactRepo = SimpleNamespace(read_document=AsyncMock(side_effect=read_source))
    capability = BrowseCollectionPapersCapability()
    context = CapabilityExecutionContext(session_id="s", user_id="u", collection_id="c", tool_call_id="t")
    result = asyncio.run(capability.execute(context, BrowseCollectionPapersToolRequest(limit=6)))
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

    miss = asyncio.run(capability.execute(context, BrowseCollectionPapersToolRequest(query="not-a-filename")))
    assert miss.data["papers"] == []
    assert miss.warnings == ()


def test_normal_pagination_is_not_a_warning():
    collection_context.collection_service = SimpleNamespace(get_collection_for_user=AsyncMock(return_value={
            "documents": [{"document_id": f"paper-{i}", "status": "ready"} for i in range(10)],
        }))
    collection_context.DocumentProfileRepo = SimpleNamespace(list_collection=AsyncMock(return_value=[]))
    collection_context.PaperMapRepo = SimpleNamespace(list_collection=AsyncMock(return_value=[]))
    collection_context.SourceArtifactRepo = SimpleNamespace(read_document=AsyncMock(return_value=document("Methods text.")))
    capability = BrowseCollectionPapersCapability()
    result = asyncio.run(capability.execute(
        CapabilityExecutionContext(session_id="s", user_id="u", collection_id="c", tool_call_id="t"),
        BrowseCollectionPapersToolRequest(limit=8),
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
            "original_filename": "P002-preheating.pdf",
            "status": "ready",
        },
        {
            "document_id": "paper-2",
            "original_filename": "Missing.pdf",
            "status": "ready",
        },
    ]
    collection_service = SimpleNamespace(
        get_collection_for_user=AsyncMock(return_value={"documents": records}),
        get_document=AsyncMock(return_value=records[1]),
    )
    sources = SourceArtifactRepository()
    collection_context.collection_service = collection_service
    collection_context.DocumentProfileRepo = DocumentProfileRepository()
    collection_context.PaperMapRepo = PaperMapRepository()
    collection_context.SourceArtifactRepo = sources
    browse = BrowseCollectionPapersCapability()
    document_sources.collection_service = collection_service
    document_sources.SourceArtifactRepo = sources
    inspect = InspectDocumentSourcesCapability()
    context = CapabilityExecutionContext(
        session_id="s", user_id="u", collection_id="c", tool_call_id="browse"
    )

    async def scenario():
        await seed_collection(database.AsyncSessionLocal, 'c', document_ids=(source_document.document_id,))
        await sources.replace_document("c", source_document)
        survey = await browse.execute(context, BrowseCollectionPapersToolRequest())
        assert [paper["source_status"] for paper in survey.data["papers"]] == ["available", "unavailable"]
        assert len(survey.warnings) == 1
        selected = await browse.execute(context, BrowseCollectionPapersToolRequest(query="P002"))
        assert selected.warnings == ()
        paper = selected.data["papers"][0]
        assert paper["abstract_status"] == "not_found"
        assert paper["map_status"] == "not_available"

        outline = await inspect.execute(context, InspectDocumentSourcesToolRequest(
            document_id=paper["document_id"], limit=1,
        ))
        heading = next(section["heading_path"] for section in outline.data["document_outline"]
                       if section["heading_path"] == "Experimental Procedures")
        read = await inspect.execute(context, InspectDocumentSourcesToolRequest(
            document_id=paper["document_id"], heading_path=heading,
        ))
        assert read.status == "succeeded"
        assert read.data["returned_source_count"] == 1
        assert read.data["sources"][0]["content"] == source_document.blocks[0].text
        assert read.data["sources"][0]["content_truncated"] is False
        assert read.data["sources"][0]["source_digest"]
        assert any(ref.resource_type == "source" for ref in read.resource_refs)
        missing = await inspect.execute(context, InspectDocumentSourcesToolRequest(document_id="paper-2"))
        assert missing.status == "failed"
        assert missing.error_code == "document_sources_not_ready"

    asyncio.run(scenario())
