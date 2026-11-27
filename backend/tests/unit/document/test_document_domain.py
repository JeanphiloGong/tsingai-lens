from __future__ import annotations

from dataclasses import replace

import pytest

from document.domain import Document, DocumentProfile
from document.domain.source import SourceDocument, SourceTable, assemble_source_documents


def test_document_domain_keeps_file_identity_only():
    document = Document(
        document_id="doc-a",
        filename="paper.pdf",
        sha256="a" * 64,
        media_type="application/pdf",
        size_bytes=12,
    )
    assert document.filename == "paper.pdf"
    assert not hasattr(document, "status")


def test_source_assembly_rejects_artifacts_from_another_document():
    paper = SourceDocument("doc-a", 0, "Methods", "laser power 200 W")
    table = SourceTable(
        table_id="table-a",
        document_id="doc-a",
        table_order=0,
        caption_text="Settings",
        caption_block_id=None,
        page=3,
        heading_path="Methods",
        column_headers=("power",),
        table_matrix=(("power",), ("200 W",)),
    )
    source, = assemble_source_documents(documents=(paper,), tables=(table,))
    assert source.tables == (table,)
    with pytest.raises(ValueError, match="unknown document"):
        assemble_source_documents(
            documents=(paper,),
            tables=(replace(table, document_id="doc-b"),),
        )


def test_document_profile_requires_navigation_description_and_fingerprints():
    profile = DocumentProfile(
        document_id="doc-a",
        doc_type="experimental",
        description="Experimental process and porosity study.",
        source_fingerprint="source-1",
        profile_fingerprint="profile-1",
        profile_version="document_profile.v2",
        generated_at="2026-11-26T00:00:00Z",
    )
    assert profile.doc_type == "experimental"
    with pytest.raises(ValueError, match="description"):
        DocumentProfile(
            "doc-a", "experimental", "", "source-1", "profile-1", "v2", "now"
        )
