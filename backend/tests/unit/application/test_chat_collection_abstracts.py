import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.chat.capabilities.collection_context import (
    BrowseCollectionPapersCapability,
    BrowseCollectionPapersToolRequest,
)
from application.chat.capabilities.contracts import CapabilityExecutionContext
from domain.source.artifacts import SourceBlock


def document(text, heading="Paper title"):
    return SimpleNamespace(blocks=(SourceBlock(
        block_id="block-1", document_id="paper-1", block_type="paragraph",
        text=text, block_order=0, heading_path=heading,
    ),))


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
    capability = BrowseCollectionPapersCapability(
        collection_service=SimpleNamespace(get_collection_for_user=AsyncMock(return_value={
            "documents": [{"document_id": "paper-1", "original_filename": "Preheating.pdf", "status": "ready"}],
        })),
        document_profile_repository=SimpleNamespace(list_collection=AsyncMock(return_value=[
            SimpleNamespace(document_id="paper-1", title="Preheating", doc_type="experimental", confidence=0.9),
        ])),
        paper_map_repository=SimpleNamespace(list_collection=AsyncMock(return_value=[
            SimpleNamespace(document_id="paper-1", map_status="sufficient", studies=(), map_limitations=()),
        ])),
        source_artifact_repository=SimpleNamespace(read_document=AsyncMock(return_value=document(text))),
    )
    result = asyncio.run(capability.execute(
        CapabilityExecutionContext(session_id="session-1", user_id="user-1", collection_id="collection-1", tool_call_id="call-1"),
        BrowseCollectionPapersToolRequest(),
    ))
    paper = result.data["papers"][0]
    assert paper["abstract_status"] == expected_status
    assert bool(result.warnings) == (expected_status == "not_found")
    assert bool(paper["screening_limitations"]) == (expected_status == "not_found")
    assert paper["support_is_evidence"] is False
    assert any(ref.resource_id == "paper-1" for ref in result.resource_refs)
    capability.source_artifact_repository.read_document.assert_awaited_once_with("collection-1", "paper-1")
