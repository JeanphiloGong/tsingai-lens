from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from repositories.document_profile_repository import DocumentProfileRepository
from infra.persistence.postgres.models.document_preparation import DocumentPreparationRow

from domain.core.document_profile import (
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
    return DocumentProfileRepository(factory), session


def test_stored_document_profile_normalizes_identity_and_lists(profile_repository) -> None:
    repository, session = profile_repository
    session.scalar.return_value = DocumentPreparationRow(document_id="test", profile_json={
            "document_id": "doc-exp",
            "title": "Composite Processing Study",
            "doc_type": "experimental",
            "profile_warnings": [],
            "confidence": 0.91,
        })
    profile = asyncio.run(repository.read("collection", "test"))

    assert profile.document_id == "doc-exp"
    assert profile.title == "Composite Processing Study"
    assert profile.doc_type == DOC_TYPE_EXPERIMENTAL
def test_stored_document_profile_coerces_invalid_doc_type(profile_repository) -> None:
    repository, session = profile_repository
    session.scalar.return_value = DocumentPreparationRow(document_id="test", profile_json={
            "document_id": "doc-bad",
            "doc_type": "research_article",
            "profile_warnings": [],
        })
    profile = asyncio.run(repository.read("collection", "test"))

    assert profile.doc_type == DOC_TYPE_EXPERIMENTAL


def test_stored_document_profile_does_not_infer_doc_type_from_warnings(profile_repository) -> None:
    repository, session = profile_repository
    session.scalar.return_value = DocumentPreparationRow(document_id="test", profile_json={
            "document_id": "doc-mixed",
            "doc_type": "article",
            "profile_warnings": ["review_contamination_detected"],
        })
    profile = asyncio.run(repository.read("collection", "test"))

    assert profile.doc_type == DOC_TYPE_UNCERTAIN


def test_summarize_document_profile_collection_emits_collection_warnings(profile_repository) -> None:
    repository, session = profile_repository
    session.scalar.return_value = DocumentPreparationRow(document_id="test", profile_json={
            "document_id": "doc-review",
            "doc_type": DOC_TYPE_REVIEW,
        })
    review_profile = asyncio.run(repository.read("collection", "test"))
    session.scalar.return_value = DocumentPreparationRow(document_id="test", profile_json={
            "document_id": "doc-uncertain",
            "doc_type": DOC_TYPE_UNCERTAIN,
        })
    uncertain_profile = asyncio.run(repository.read("collection", "test"))

    summary = summarize_document_profile_collection([review_profile, uncertain_profile])

    assert summary.total_documents == 2
    assert summary.by_doc_type == {
        DOC_TYPE_REVIEW: 1,
        DOC_TYPE_UNCERTAIN: 1,
    }
    assert summary.technical_failure_count == 0
    assert (
        "Collection is review-heavy or mixed; experimental evidence may require manual review."
        in summary.warnings
    )
    assert "Some documents remain uncertain and may need manual review." in summary.warnings


def test_summarize_document_profile_collection_separates_technical_failure(profile_repository) -> None:
    repository, session = profile_repository
    session.scalar.return_value = DocumentPreparationRow(document_id="test", profile_json={
            "document_id": "doc-failed",
            "doc_type": "uncertain",
            "profile_warnings": ["document_profile_extraction_failed"],
            "profile_status": "extraction_failed",
        })
    profile = asyncio.run(repository.read("collection", "test"))

    summary = summarize_document_profile_collection([profile])

    assert summary.technical_failure_count == 1
    assert "Some document profiles failed technical extraction and need retry." in summary.warnings


def test_document_profile_migrates_legacy_failure_warning_to_failure_status(profile_repository) -> None:
    repository, session = profile_repository
    session.scalar.return_value = DocumentPreparationRow(document_id="test", profile_json={
            "document_id": "doc-legacy-failed",
            "doc_type": "uncertain",
            "profile_warnings": ["document_profile_extraction_failed"],
        })
    profile = asyncio.run(repository.read("collection", "test"))

    assert profile.profile_status == "extraction_failed"
