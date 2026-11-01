from application.chat.capabilities import document_sources
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from domain.source import SourceDocument, SourceBlock
from application.chat.capabilities import CapabilityExecutionContext
from application.chat.capabilities.document_sources import (
    InspectDocumentSourcesCapability,
    InspectDocumentSourcesToolRequest,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("length", [20, 700])
async def test_section_pages_keep_source_order_and_only_selected_outline(
    length, monkeypatch
):
    blocks = tuple(
        SourceBlock(
            block_id=f"b{i}",
            document_id="paper",
            block_type="paragraph",
            text="Methods text " * length,
            block_order=i,
            page=1,
            heading_path="Methods",
        )
        for i in range(14)
    )
    other = tuple(
        SourceBlock(
            block_id=f"other{i}",
            document_id="paper",
            block_type="paragraph",
            text="Other observation",
            block_order=14 + i,
            page=2,
            heading_path=f"Other {i}",
        )
        for i in range(20)
    )
    doc = SourceDocument(
        document_id="paper",
        document_order=0,
        title="Synthetic paper",
        text="",
        blocks=blocks + other,
    )
    monkeypatch.setattr(
        document_sources.collection_service, "get_collection_for_user", AsyncMock()
    )
    monkeypatch.setattr(
        document_sources,
        "SourceArtifactRepo",
        SimpleNamespace(read_document=AsyncMock(return_value=doc)),
    )
    cap = InspectDocumentSourcesCapability()
    context = CapabilityExecutionContext(
        "chat", "user", "col", "call", max_result_tokens=8000
    )
    seen = []
    offset = 0
    pages = 0
    while True:
        pages += 1
        assert pages <= 20
        result = await cap.execute(
            context,
            InspectDocumentSourcesToolRequest(
                document_id="paper", heading_path="Methods", offset=offset, limit=200
            ),
        )
        assert result.status == "succeeded"
        assert cap._result_tokens(result) <= context.max_result_tokens
        assert [
            section["heading_path"] for section in result.data["document_outline"]
        ] == ["Methods"]
        assert all(not source["content_truncated"] for source in result.data["sources"])
        seen.extend(source["source_ref"] for source in result.data["sources"])
        next_offset = result.data["next_offset"]
        if next_offset is None:
            break
        assert next_offset > offset
        offset = next_offset
    assert seen == [f"b{i}" for i in range(14)]
    if length == 20:
        assert pages == 1


@pytest.mark.anyio
async def test_permission_failure_stops_before_loading_sources(monkeypatch):
    repo = SimpleNamespace(read_document=AsyncMock())
    monkeypatch.setattr(
        document_sources.collection_service,
        "get_collection_for_user",
        AsyncMock(side_effect=PermissionError()),
    )
    monkeypatch.setattr(document_sources, "SourceArtifactRepo", repo)
    cap = InspectDocumentSourcesCapability()
    with pytest.raises(PermissionError):
        await cap.execute(
            CapabilityExecutionContext("chat", "user", "col", "call"),
            InspectDocumentSourcesToolRequest(document_id="paper"),
        )
    repo.read_document.assert_not_called()


@pytest.mark.anyio
async def test_small_section_budget_contains_real_body_in_one_batch(monkeypatch):
    blocks = tuple(
        SourceBlock(
            block_id=f"b{i}",
            document_id="paper",
            block_type="paragraph",
            text="measured observation " * 6,
            block_order=i,
            page=1,
            heading_path="Methods",
        )
        for i in range(5)
    )
    document = SourceDocument(
        document_id="paper",
        document_order=0,
        title="Synthetic paper",
        text="",
        blocks=blocks,
    )
    monkeypatch.setattr(
        document_sources.collection_service, "get_collection_for_user", AsyncMock()
    )
    monkeypatch.setattr(
        document_sources,
        "SourceArtifactRepo",
        SimpleNamespace(read_document=AsyncMock(return_value=document)),
    )
    capability = InspectDocumentSourcesCapability()
    result = await capability.execute(
        CapabilityExecutionContext(
            "chat", "user", "col", "call", max_result_tokens=2000
        ),
        InspectDocumentSourcesToolRequest(document_id="paper", heading_path="Methods"),
    )
    assert result.status == "succeeded"
    assert result.data["returned_source_count"] == 5
    assert all(source["content"] for source in result.data["sources"])
    assert result.data["next_offset"] is None
    assert capability._result_tokens(result) <= 2000
