from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from document.repositories.profile_repository import ProfileRepository
from infra.persistence.postgres.models.workspace import (
    DocumentPreparationORM,
)
from document.domain.profile import (
    DocumentProfile,
    summarize_document_profile_workspace,
)
from domain.shared.enums import (
    DOC_TYPE_EXPERIMENTAL,
    DOC_TYPE_REVIEW,
    DOC_TYPE_UNCERTAIN,
)


@pytest.fixture
def profile_repository(monkeypatch):
    session = AsyncMock()
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=session)
    manager.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=manager)
    monkeypatch.setattr("document.repositories.profile_repository.AsyncSessionLocal", factory)
    return ProfileRepository(), session


def test_stored_document_profile_reads_canonical_fields(profile_repository) -> None:
    repository, session = profile_repository
    session.scalar.return_value = DocumentPreparationORM(
        document_id="doc-exp",
        profile_json={
            "document_id": "doc-exp",
            "description": "Composite processing study.",
            "doc_type": "experimental",
            "source_fingerprint": "source-v1",
            "profile_version": "document_profile.v1",
            "profile_fingerprint": "profile-v1",
            "generated_at": "2026-10-28T00:00:00+00:00",
        },
    )
    profile = asyncio.run(repository.read("workspace", "doc-exp"))

    assert profile == DocumentProfile(
        document_id="doc-exp",
        description="Composite processing study.",
        doc_type=DOC_TYPE_EXPERIMENTAL,
        source_fingerprint="source-v1",
        profile_version="document_profile.v1",
        profile_fingerprint="profile-v1",
        generated_at="2026-10-28T00:00:00+00:00",
    )


def test_profile_read_requires_current_storage_contract(profile_repository) -> None:
    repository, session = profile_repository
    session.scalar.return_value = DocumentPreparationORM(
        document_id="doc",
        profile_json={
            "document_id": "doc",
            "description": "",
            "doc_type": "uncertain",
        },
    )

    with pytest.raises((KeyError, ValueError)):
        asyncio.run(repository.read("workspace", "doc"))


def test_summarize_document_profile_workspace_emits_workspace_warnings() -> None:
    review_profile = DocumentProfile(
        "doc-review", DOC_TYPE_REVIEW, "Review of materials research.",
        "source-review", "profile-review", "document_profile.v2", "2026-01-01T00:00:00Z",
    )
    uncertain_profile = DocumentProfile(
        "doc-uncertain", DOC_TYPE_UNCERTAIN, "Uncertain document.",
        "source-uncertain", "profile-uncertain", "document_profile.v2", "2026-01-01T00:00:00Z",
    )

    summary = summarize_document_profile_workspace([review_profile, uncertain_profile])

    assert summary.total_documents == 2
    assert summary.by_doc_type == {DOC_TYPE_REVIEW: 1, DOC_TYPE_UNCERTAIN: 1}
    assert summary.technical_failure_count == 0
    assert (
        "Workspace is review-heavy or mixed; experimental evidence may require manual review."
        in summary.warnings
    )
    assert (
        "Some documents remain uncertain and may need manual review."
        in summary.warnings
    )


def test_summarize_document_profile_workspace_has_no_technical_failure_field() -> None:
    profile = DocumentProfile(
        "doc-failed", DOC_TYPE_UNCERTAIN, "Uncertain document.",
        "source-failed", "profile-failed", "document_profile.v2", "2026-01-01T00:00:00Z",
    )

    summary = summarize_document_profile_workspace([profile])

    assert summary.technical_failure_count == 0
