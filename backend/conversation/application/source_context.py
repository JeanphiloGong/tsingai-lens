"""Verify selected paper excerpts against the owning prepared Source."""

from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata
from urllib.parse import urlencode

from application.source import workspace_service
from domain.source.artifacts import SourceDocument
from domain.chat.resource_ref import ChatResourceRef
from domain.chat.source_context import ChatSourceContext
from exceptions import RequestInvalidException, ResourceNotFoundException
from infra.source.artifact_bundle import source_table_payload
from repositories.source_artifact_repository import SourceArtifactRepo


class InvalidSourceContext(RequestInvalidException):
    def __init__(self, message: str) -> None:
        super().__init__(message, data={"code": "chat_source_context_invalid"})


@dataclass(frozen=True)
class _SelectedSource:
    content: str
    page: int | None
    heading_path: str | None


def _resolve_source(
    document: SourceDocument, *, source_kind: str, source_ref: str
) -> _SelectedSource:
    if source_kind == "text_window":
        source = next(
            (item for item in document.blocks if item.block_id == source_ref), None
        )
        if source is not None:
            return _SelectedSource(
                source.text,
                source.page,
                source.heading_path,
            )
    elif source_kind == "table":
        source = next(
            (item for item in document.tables if item.table_id == source_ref), None
        )
        if source is not None:
            record = source_table_payload(source)
            return _SelectedSource(
                (record["table_markdown"] or "").strip(),
                source.page,
                source.heading_path,
            )
    elif source_kind == "figure":
        source = next(
            (item for item in document.figures if item.figure_id == source_ref), None
        )
        if source is not None:
            return _SelectedSource(
                source.caption_text or "",
                source.page,
                source.heading_path,
            )
    else:
        raise ValueError(f"unsupported Source kind: {source_kind}")
    raise FileNotFoundError("Source was not found in the requested document")


def normalize_source_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


async def canonical_source_contexts(
    workspace_id: str,
    source_contexts: tuple[ChatSourceContext, ...],
) -> tuple[ChatSourceContext, ...]:
    if any(item.workspace_id != workspace_id for item in source_contexts):
        raise InvalidSourceContext(
            "source context does not belong to the Chat workspace"
        )
    canonical_contexts: list[ChatSourceContext] = []
    for item in source_contexts:
        try:
            await workspace_service.get_document(
                workspace_id,
                item.document_id,
            )
        except ResourceNotFoundException as exc:
            raise InvalidSourceContext(
                "source context document does not belong to the Chat workspace"
            ) from exc
        document = await SourceArtifactRepo.read_document(
            workspace_id,
            item.document_id,
        )
        if document is None:
            raise InvalidSourceContext(
                "selected Source content is not prepared for this document"
            )
        if document.document_id != item.document_id:
            raise InvalidSourceContext(
                "selected Source document identity does not match its "
                "canonical Source"
            )
        document_title = (document.title or document.document_id).strip()[:500]
        try:
            canonical = _resolve_source(
                document,
                source_kind=item.source_kind,
                source_ref=item.source_ref,
            )
        except ValueError as exc:
            raise InvalidSourceContext(
                "selected Source kind is not supported"
            ) from exc
        except FileNotFoundError as exc:
            raise InvalidSourceContext(
                "selected Source reference does not identify a canonical Source "
                "in this document"
            ) from exc

        heading_path = (
            canonical.heading_path.strip()[:1000]
            if canonical.heading_path is not None
            else None
        )
        canonical_content = canonical.content
        normalized_content = normalize_source_text(canonical_content)
        normalized_quote = normalize_source_text(item.quote)
        if not normalized_quote or normalized_quote not in normalized_content:
            raise InvalidSourceContext(
                "selected Source quote is not contained in the canonical Source"
            )
        digest = sha256(canonical_content.encode("utf-8")).hexdigest()
        if item.source_digest is not None and item.source_digest.lower() != digest:
            raise InvalidSourceContext(
                "selected Source digest does not match the canonical Source"
            )
        query = {
            "view": "parsed-paper",
            "source_ref": item.source_ref,
        }
        if canonical.page is not None:
            query["page"] = str(canonical.page)
        canonical_contexts.append(
            ChatSourceContext(
                resource_ref=ChatResourceRef(
                    resource_type="source",
                    resource_id=f"{item.document_id}:{item.source_ref}",
                    href=(
                        f"/workspaces/{workspace_id}/documents/"
                        f"{item.document_id}?{urlencode(query)}"
                    ),
                ),
                workspace_id=workspace_id,
                document_id=item.document_id,
                document_title=document_title,
                source_kind=item.source_kind,
                source_ref=item.source_ref,
                page=canonical.page,
                quote=normalized_quote,
                heading_path=heading_path,
                quote_truncated=(
                    item.quote_truncated or normalized_quote != normalized_content
                ),
                source_digest=digest,
            )
        )
    return tuple(canonical_contexts)
