from __future__ import annotations

import pytest

from domain.source.document import (
    CollectionDocumentRecord,
    DocumentRecord,
    DocumentVersionRecord,
    collection_document_identity,
    document_identity_for_sha256,
)


def test_document_identity_is_stable_opaque_and_bounded() -> None:
    digest = "a" * 64

    document_id, document_version_id = document_identity_for_sha256(digest)

    assert (document_id, document_version_id) == document_identity_for_sha256(digest)
    assert document_id.startswith("doc_")
    assert document_version_id.startswith("docver_")
    assert len(document_id) <= 64
    assert len(document_version_id) <= 64
    assert digest not in document_id
    assert digest not in document_version_id
    assert collection_document_identity("col_demo", document_id).startswith("coldoc_")
    assert len(collection_document_identity("col_demo", document_id)) <= 64


@pytest.mark.parametrize("digest", ["a" * 63, "A" * 64, "z" * 64])
def test_document_identity_rejects_noncanonical_sha256(digest: str) -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        document_identity_for_sha256(digest)


def test_canonical_document_records_keep_identity_and_membership_explicit() -> None:
    document = DocumentRecord(
        document_id="doc_1",
        created_at="2026-07-19T09:00:00+00:00",
    )
    version = DocumentVersionRecord(
        document_version_id="docver_1",
        document_id=document.document_id,
        sha256="b" * 64,
        media_type="application/pdf",
        created_at=document.created_at,
    )
    membership = CollectionDocumentRecord(
        collection_document_id="coldoc_1",
        collection_id="col_1",
        document_id=document.document_id,
        document_version_id=version.document_version_id,
        created_at=document.created_at,
    )

    assert version.document_id == document.document_id
    assert membership.document_id == document.document_id
    assert membership.document_version_id == version.document_version_id
