from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from document.application.source_reading import (
    SourceReadingError,
    SourceReadingService,
)
from domain.source import SourceBlock, SourceDocument, SourceTable


class FakeSourceRepository:
    def __init__(self, document: SourceDocument) -> None:
        self.document = document

    async def read(self, *, workspace_id, document_id, source_version):
        assert workspace_id == "workspace-1"
        if document_id != self.document.document_id:
            raise FileNotFoundError(document_id)
        if source_version not in (None, "source-v1"):
            raise ValueError("source_version_changed")
        return self.document

    async def list(self, *, workspace_id, document_ids):
        assert workspace_id == "workspace-1"
        if document_ids is None or self.document.document_id in document_ids:
            return (self.document,)
        return ()


@pytest.fixture
def source_document() -> SourceDocument:
    return SourceDocument(
        document_id="document-1",
        document_order=0,
        title="Methods",
        text="laser power 200 W",
        metadata={"source_fingerprint": "source-v1"},
        blocks=(
            SourceBlock(
                block_id="block-1",
                document_id="document-1",
                block_type="paragraph",
                text="laser power 200 W",
                block_order=0,
                page=3,
                heading_path="Methods",
            ),
        ),
        tables=(
            SourceTable(
                table_id="table-1",
                document_id="document-1",
                table_order=0,
                caption_text="Laser settings",
                caption_block_id=None,
                page=3,
                heading_path="Methods",
                column_headers=("power",),
                table_matrix=(("power",), ("200 W",), ("250 W",)),
            ),
        ),
    )


def test_read_search_and_table_preserve_source_locators(source_document):
    async def check():
        service = SourceReadingService(FakeSourceRepository(source_document))

        window = await service.read_source(
            workspace_id="workspace-1",
            document_id="document-1",
            source_kind="text_window",
            source_ref="block-1",
            source_version="source-v1",
            limit=5,
        )
        assert window.content == "laser"
        assert window.next_offset == 5
        assert window.locator.source_ref == "block-1"

        search = await service.search_sources(
            workspace_id="workspace-1",
            document_ids=("document-1",),
            query="LASER",
        )
        assert search.candidates[0].locator.source_ref == "block-1"
        assert search.candidates[0].locator.source_kind == "text_window"

        table = await service.inspect_table(
            workspace_id="workspace-1",
            document_id="document-1",
            table_ref="table-1",
            source_version="source-v1",
            row_limit=1,
        )
        assert table.rows == (("200 W",),)
        assert table.next_row_offset == 1

    asyncio.run(check())


def test_reading_rejects_stale_versions_and_invalid_locators(source_document):
    async def check():
        service = SourceReadingService(FakeSourceRepository(source_document))

        with pytest.raises(SourceReadingError, match="source_version_changed") as stale:
            await service.read_source(
                workspace_id="workspace-1",
                document_id="document-1",
                source_kind="text_window",
                source_ref="block-1",
                source_version="old-version",
            )
        assert stale.value.code == "source_version_changed"

        with pytest.raises(SourceReadingError, match="source_not_found") as missing:
            await service.read_source(
                workspace_id="workspace-1",
                document_id="document-1",
                source_kind="text_window",
                source_ref="missing-block",
            )
        assert missing.value.code == "source_not_found"

        with pytest.raises(SourceReadingError, match="source_offset_out_of_range"):
            await service.read_source(
                workspace_id="workspace-1",
                document_id="document-1",
                source_kind="text_window",
                source_ref="block-1",
                offset=100,
            )

    asyncio.run(check())


def test_unprepared_source_and_empty_search_have_stable_errors(source_document):
    async def check():
        unprepared = replace(source_document, metadata={})
        service = SourceReadingService(FakeSourceRepository(unprepared))

        with pytest.raises(SourceReadingError, match="document_sources_not_ready"):
            await service.read_source(
                workspace_id="workspace-1",
                document_id="document-1",
                source_kind="text_window",
                source_ref="block-1",
            )

        prepared = SourceReadingService(FakeSourceRepository(source_document))
        with pytest.raises(SourceReadingError, match="source_query_required"):
            await prepared.search_sources(
                workspace_id="workspace-1",
                document_ids=None,
                query="   ",
            )

    asyncio.run(check())
