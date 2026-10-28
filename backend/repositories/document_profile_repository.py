"""PostgreSQL repository for document profile."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core.document_profile import (
    DocumentProfile,
    ProfileStatus,
    PROFILE_STATUS_COMPLETED,
    PROFILE_STATUS_EXTRACTION_FAILED,
    PROFILE_EXTRACTION_FAILED_WARNING,
)
from domain.shared.enums import (
    DOC_TYPE_EXPERIMENTAL,
    DOC_TYPE_REVIEW,
    DOC_TYPE_MIXED,
    DOC_TYPE_UNCERTAIN,
)
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.document_preparation import (
    DocumentPreparationRow,
)


class DocumentProfileRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def replace(self, collection_id: str, profile: DocumentProfile) -> None:
        next_profile = {
            "document_id": profile.document_id,
            "title": profile.title,
            "doc_type": profile.doc_type,
            "profile_warnings": list(profile.profile_warnings),
            "confidence": round(float(profile.confidence), 2),
            "profile_status": profile.profile_status,
            "source_fingerprint": profile.source_fingerprint,
            "profile_version": profile.profile_version,
            "profile_fingerprint": profile.profile_fingerprint,
            "generated_at": profile.generated_at,
        }
        async with self.session_factory.begin() as session:
            document = await session.get(Document, profile.document_id)
            if document is None or document.collection_id != collection_id:
                raise FileNotFoundError(
                    "collection document not found: "
                    f"{collection_id}/{profile.document_id}"
                )
            row = await session.get(DocumentPreparationRow, profile.document_id)
            if row is None:
                now = datetime.now(timezone.utc)
                session.add(
                    DocumentPreparationRow(
                        document_id=profile.document_id,
                        profile_json=next_profile,
                        created_at=now,
                        updated_at=now,
                    )
                )
                return
            row.profile_json = next_profile
            row.updated_at = datetime.now(timezone.utc)

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> DocumentProfile | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(DocumentPreparationRow)
                .join(
                    Document,
                    Document.document_id == DocumentPreparationRow.document_id,
                )
                .where(
                    DocumentPreparationRow.document_id == document_id,
                    Document.collection_id == collection_id,
                )
            )
            if row is None or not row.profile_json:
                return None
            payload = dict(row.profile_json or {})
            payload.setdefault("document_id", row.document_id)
            warnings = _normalize_string_tuple(payload.get("profile_warnings"))
            profile = DocumentProfile(
                document_id=str(payload.get("document_id") or ""),
                title=_normalize_optional_text(payload.get("title")),
                doc_type=_normalize_doc_type(payload.get("doc_type")),
                profile_warnings=warnings,
                confidence=round(float(payload.get("confidence") or 0.0), 2),
                profile_status=_normalize_profile_status(
                    payload.get("profile_status"), warnings=warnings
                ),
                source_fingerprint=_normalize_optional_text(payload.get("source_fingerprint")),
                profile_version=_normalize_optional_text(payload.get("profile_version")),
                profile_fingerprint=_normalize_optional_text(payload.get("profile_fingerprint")),
                generated_at=_normalize_optional_text(payload.get("generated_at")),
            )
            return profile

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[DocumentProfile, ...]:
        if document_ids == ():
            return ()
        async with self.session_factory() as session:
            statement = (
                select(DocumentPreparationRow)
                .join(
                    Document,
                    Document.document_id == DocumentPreparationRow.document_id,
                )
                .where(Document.collection_id == collection_id)
            )
            if document_ids is not None:
                statement = statement.where(
                    DocumentPreparationRow.document_id.in_(document_ids)
                )
            rows = await session.scalars(
                statement.order_by(DocumentPreparationRow.document_id)
            )
            profiles = []
            for row in rows:
                if not row.profile_json:
                    continue
                payload = dict(row.profile_json or {})
                payload.setdefault("document_id", row.document_id)
                warnings = _normalize_string_tuple(payload.get("profile_warnings"))
                profile = DocumentProfile(
                    document_id=str(payload.get("document_id") or ""),
                    title=_normalize_optional_text(payload.get("title")),
                    doc_type=_normalize_doc_type(payload.get("doc_type")),
                    profile_warnings=warnings,
                    confidence=round(float(payload.get("confidence") or 0.0), 2),
                    profile_status=_normalize_profile_status(
                        payload.get("profile_status"), warnings=warnings
                    ),
                    source_fingerprint=_normalize_optional_text(payload.get("source_fingerprint")),
                    profile_version=_normalize_optional_text(payload.get("profile_version")),
                    profile_fingerprint=_normalize_optional_text(payload.get("profile_fingerprint")),
                    generated_at=_normalize_optional_text(payload.get("generated_at")),
                )
                profiles.append(profile)
            return tuple(profiles)


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    if hasattr(value, "tolist") and not isinstance(value, (dict, bytes)):
        converted = value.tolist()
        if converted is not value:
            return _normalize_string_tuple(converted)
    text = str(value).strip()
    return (text,) if text else ()


def _normalize_doc_type(
    value: Any,
) -> str:
    raw = _normalize_label(value)
    if raw in {
        DOC_TYPE_EXPERIMENTAL,
        DOC_TYPE_REVIEW,
        DOC_TYPE_MIXED,
        DOC_TYPE_UNCERTAIN,
    }:
        return raw

    if raw in {
        "research article",
        "research paper",
        "original research",
        "original article",
        "primary research",
        "primary study",
        "empirical study",
        "experiment",
        "experimental study",
    }:
        return DOC_TYPE_EXPERIMENTAL

    if raw in {
        "review article",
        "review paper",
        "literature review",
        "survey",
        "overview",
        "perspective",
    }:
        return DOC_TYPE_REVIEW

    if raw in {
        "mixed",
        "mixed study",
        "mixed article",
    }:
        return DOC_TYPE_MIXED

    if raw in {
        "",
        "unknown",
        "unclear",
        "other",
        "n/a",
        "na",
    }:
        return DOC_TYPE_UNCERTAIN

    return DOC_TYPE_UNCERTAIN


def _normalize_profile_status(
    value: Any,
    *,
    warnings: tuple[str, ...] = (),
) -> ProfileStatus:
    normalized = _normalize_label(value)
    if (
        normalized.replace(" ", "_") == PROFILE_STATUS_EXTRACTION_FAILED
        or PROFILE_EXTRACTION_FAILED_WARNING in warnings
    ):
        return PROFILE_STATUS_EXTRACTION_FAILED
    return PROFILE_STATUS_COMPLETED


def _normalize_label(value: Any) -> str:
    text = _normalize_optional_text(value)
    if text is None:
        return ""
    return text.lower().replace("_", " ").replace("-", " ")


__all__ = ['DocumentProfileRepository']
