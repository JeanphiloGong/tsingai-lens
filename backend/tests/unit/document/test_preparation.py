from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from document.application.preparation import DocumentPreparation
from document.domain import DocumentProfile
from document.domain.source import SourceDocument
from pipeline.definitions.document_preparation import document_preparation_nodes


@dataclass
class FakeSourceRepository:
    saved: SourceDocument | None = None

    async def replace_document(self, workspace_id, document, *, db=None):
        self.saved = document


class FakeDocumentRepository:
    async def read(self, *, workspace_id, document_id, source_version, db=None):
        return SourceDocument(
            document_id=document_id,
            document_order=0,
            title="Methods",
            text="source",
            metadata={"source_fingerprint": source_version},
        )


@dataclass
class FakeProfileRepository:
    saved: DocumentProfile | None = None

    async def replace(self, workspace_id, profile, *, db=None):
        self.saved = profile


def test_document_preparation_nodes_keep_real_dependency_order():
    service = DocumentPreparation(
        FakeDocumentRepository(), FakeSourceRepository(), FakeProfileRepository()
    )
    nodes = document_preparation_nodes(service)
    assert tuple((node.name, node.dependencies) for node in nodes) == (
        ("source_parsing", ()),
        ("document_profile", ("source_parsing",)),
    )


def test_source_success_and_profile_write_share_preparation_contract():
    async def check():
        artifacts = FakeSourceRepository()
        profiles = FakeProfileRepository()
        service = DocumentPreparation(FakeDocumentRepository(), artifacts, profiles)
        source = SourceDocument(
            "doc-a",
            0,
            "Methods",
            "laser power 200 W",
            metadata={"source_fingerprint": "source-1"},
        )
        parsed = await service.parse_source(
            workspace_id="workspace-a", document_id="doc-a", parsed=source
        )
        assert parsed.profile is None
        assert artifacts.saved == source
        profile = DocumentProfile(
            document_id="doc-a",
            doc_type="experimental",
            description="Experimental process study.",
            source_fingerprint="source-1",
            profile_fingerprint="profile-1",
            profile_version="document_profile.v2",
            generated_at="2026-11-27T00:00:00Z",
        )
        result = await service.save_profile(
            workspace_id="workspace-a",
            document_id="doc-a",
            source_version="source-1",
            profile=profile,
            db=object(),
        )
        assert result.profile == profile
        assert profiles.saved == profile

    asyncio.run(check())


def test_profile_version_mismatch_does_not_write():
    async def check():
        profiles = FakeProfileRepository()
        service = DocumentPreparation(FakeDocumentRepository(), FakeSourceRepository(), profiles)
        profile = DocumentProfile(
            "doc-a", "experimental", "Experimental study.", "source-old", "profile-1", "v2", "now"
        )
        with pytest.raises(ValueError, match="source version"):
            await service.save_profile(
                workspace_id="workspace-a",
                document_id="doc-a",
                source_version="source-current",
                profile=profile,
                db=object(),
            )
        assert profiles.saved is None

    asyncio.run(check())
