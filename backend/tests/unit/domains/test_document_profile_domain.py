from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from repositories.document_profile_repository import DocumentProfileRepository
from infra.persistence.postgres.models.document_preparation import (
    DocumentPreparationRow,
)
from domain.core.document_profile import (
    DocumentProfile,
    summarize_document_profile_collection,
)
from domain.shared.enums import (
    DOC_TYPE_EXPERIMENTAL,
    DOC_TYPE_REVIEW,
    DOC_TYPE_UNCERTAIN,
)


@pytest.fixture
def profile_repository():
    session = AsyncMock()
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=session)
    manager.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=manager)
    return DocumentProfileRepository(), session


def test_stored_document_profile_reads_canonical_fields(profile_repository) -> None:
    repository, session = profile_repository
    session.scalar.return_value = DocumentPreparationRow(
        document_id="doc-exp",
        profile_json={
            "document_id": "doc-exp",
            "title": "Composite Processing Study",
            "doc_type": "experimental",
            "profile_warnings": [],
            "confidence": 0.91,
            "profile_status": "completed",
            "source_fingerprint": "source-v1",
            "profile_version": "document_profile.v1",
            "profile_fingerprint": "profile-v1",
            "generated_at": "2026-10-28T00:00:00+00:00",
        },
    )
    profile = asyncio.run(repository.read("collection", "doc-exp"))

    assert profile == DocumentProfile(
        document_id="doc-exp",
        title="Composite Processing Study",
        doc_type=DOC_TYPE_EXPERIMENTAL,
        profile_warnings=(),
        confidence=0.91,
        profile_status="completed",
        source_fingerprint="source-v1",
        profile_version="document_profile.v1",
        profile_fingerprint="profile-v1",
        generated_at="2026-10-28T00:00:00+00:00",
    )


def test_profile_read_requires_current_storage_contract(profile_repository) -> None:
    repository, session = profile_repository
    session.scalar.return_value = DocumentPreparationRow(
        document_id="doc",
        profile_json={
            "document_id": "doc",
            "title": None,
            "doc_type": "uncertain",
            "profile_warnings": [],
            "confidence": 0.0,
        },
    )

    with pytest.raises(KeyError, match="profile_status"):
        asyncio.run(repository.read("collection", "doc"))


def test_summarize_document_profile_collection_emits_collection_warnings() -> None:
    review_profile = DocumentProfile("doc-review", None, DOC_TYPE_REVIEW, (), 0.8)
    uncertain_profile = DocumentProfile(
        "doc-uncertain", None, DOC_TYPE_UNCERTAIN, (), 0.0
    )

    summary = summarize_document_profile_collection([review_profile, uncertain_profile])

    assert summary.total_documents == 2
    assert summary.by_doc_type == {DOC_TYPE_REVIEW: 1, DOC_TYPE_UNCERTAIN: 1}
    assert summary.technical_failure_count == 0
    assert (
        "Collection is review-heavy or mixed; experimental evidence may require manual review."
        in summary.warnings
    )
    assert (
        "Some documents remain uncertain and may need manual review."
        in summary.warnings
    )


def test_summarize_document_profile_collection_separates_technical_failure() -> None:
    profile = DocumentProfile(
        "doc-failed",
        None,
        DOC_TYPE_UNCERTAIN,
        ("document_profile_extraction_failed",),
        0.0,
        profile_status="extraction_failed",
    )

    summary = summarize_document_profile_collection([profile])

    assert summary.technical_failure_count == 1
    assert (
        "Some document profiles failed technical extraction and need retry."
        in summary.warnings
    )
