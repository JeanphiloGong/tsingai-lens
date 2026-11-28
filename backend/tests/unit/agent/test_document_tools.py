from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.tools.document import (
    ListDocumentProfilesCapability,
    ReadSourceCapability,
    SearchSourcesCapability,
)
from agent.tools.registry import ToolExecutionContext
from document.application.source_reading import SourceReadingError
from document.domain import DocumentProfile
from domain.chat import ToolResultStatus


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def authorize(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr("agent.tools.document.workspace_service.get_workspace_for_user", AsyncMock())


class FakeReading:
    async def read_source(self, **kwargs):
        return SimpleNamespace(
            locator=SimpleNamespace(
                document_id=kwargs["document_id"],
                source_kind=kwargs["source_kind"],
                source_ref=kwargs["source_ref"],
                source_type="text",
            ),
            source_version="source-1",
            source_digest="digest-1",
            offset=kwargs["offset"],
            limit=kwargs["limit"],
            content="Methods content",
            next_offset=None,
        )

    async def search_sources(self, **kwargs):
        return SimpleNamespace(offset=0, limit=8, next_offset=None, candidates=())


class FakeProfiles:
    async def list_workspace(self, workspace_id, document_ids=None):
        return (
            DocumentProfile(
                document_id="doc-1",
                doc_type="experimental",
                description="Laser powder bed fusion study",
                source_fingerprint="source-1",
                profile_fingerprint="profile-1",
                profile_version="document_profile.v2",
                generated_at="2026-01-01T00:00:00Z",
            ),
        )


def context() -> ToolExecutionContext:
    return ToolExecutionContext(
        user_id="user-1",
        workspace_id="workspace-1",
        task_id="task-1",
        operation_id="operation-1",
        tool_call_id="call-1",
    )


@pytest.mark.anyio
async def test_read_source_adapter_passes_server_workspace_to_document_service():
    result = await ReadSourceCapability(FakeReading()).execute(
        context(),
        ReadSourceCapability(FakeReading()).spec.input_model(
            document_id="doc-1",
            source_kind="text_window",
            source_ref="block-1",
        ),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.data["document_id"] == "doc-1"
    assert result.data["content"] == "Methods content"


@pytest.mark.anyio
async def test_search_source_adapter_returns_document_search_page():
    capability = SearchSourcesCapability(FakeReading())
    result = await capability.execute(
        context(),
        capability.spec.input_model(query="laser"),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.data == {"offset": 0, "limit": 8, "next_offset": None, "candidates": []}


@pytest.mark.anyio
async def test_profile_adapter_filters_description_without_accessing_storage():
    capability = ListDocumentProfilesCapability(FakeProfiles())
    result = await capability.execute(
        context(),
        capability.spec.input_model(query="laser"),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.data["documents"][0]["document_id"] == "doc-1"
    assert result.data["documents"][0]["description"].startswith("Laser")


@pytest.mark.anyio
async def test_read_source_adapter_maps_document_error():
    class FailingReading:
        async def read_source(self, **kwargs):
            raise SourceReadingError("source_version_changed")

    capability = ReadSourceCapability(FailingReading())
    result = await capability.execute(
        context(),
        capability.spec.input_model(
            document_id="doc-1",
            source_kind="text_window",
            source_ref="block-1",
        ),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error_code == "source_version_changed"
