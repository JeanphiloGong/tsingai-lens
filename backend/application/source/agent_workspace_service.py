"""Bounded workspace and Objective context for the Research Agent."""

from __future__ import annotations

from application.source import workspace_service
from repositories.workspace_repository import StoredDocument
from repositories.paper_map_repository import PaperMapRepo
from repositories.objective_repository import ObjectiveRepo
from repositories.document_profile_repository import DocumentProfileRepo
from document.repositories.source_repository import SourceRepo

from domain.chat import ToolResultStatus

import logging
import re
import hashlib
import json
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.application.context_builder import ChatContextBuilder
from domain.chat import ChatResourceRef, ChatToolResult


_OBJECTIVE_LIMIT = 12
_PAPER_LIMIT = 100
_ABSTRACT_LIMIT = 1_200
logger = logging.getLogger(__name__)


class GetWorkspaceContextToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetWorkspaceContextService:

    async def execute(
        self,
        *,
        user_id: str,
        workspace_id: str,
        tool_call_id: str | None,
        max_result_tokens: int,
        _arguments: GetWorkspaceContextToolRequest,
    ) -> ChatToolResult:
        workspace = await workspace_service.get_workspace_for_user(
            workspace_id,
            user_id,
        )
        objectives = await ObjectiveRepo.list_objectives(
            workspace_id
        )
        visible = objectives[:_OBJECTIVE_LIMIT]
        objective_records = [self._objective_summary(item) for item in visible]
        omitted = len(objectives) - len(visible)
        warnings = (
            (f"{omitted} additional Objectives were omitted from this bounded result.",)
            if omitted
            else ()
        )
        return ChatToolResult(
            tool_call_id=tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "workspace": {
                    "workspace_id": workspace.workspace.workspace_id,
                    "name": workspace.workspace.name[:240],
                    "description": (
                        workspace.workspace.description[:1_000]
                        if workspace.workspace.description
                        else None
                    ),
                    "status": workspace.workspace.status,
                    "paper_count": len(workspace.documents),
                },
                "objective_count": len(objectives),
                "objectives": objective_records,
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="workspace",
                    resource_id=workspace_id,
                    href=f"/workspaces/{workspace_id}",
                ),
                *(
                    ChatResourceRef(
                        resource_type="research_objective",
                        resource_id=item.objective_id,
                        href=(
                            f"/workspaces/{workspace_id}/objectives/"
                            f"{item.objective_id}"
                        ),
                    )
                    for item in visible
                ),
            ),
            warnings=warnings,
        )

    @staticmethod
    def _objective_summary(objective: Any) -> dict[str, Any]:
        return {
            "objective_id": objective.objective_id,
            "question": objective.question[:500],
            "material_scope": list(objective.material_scope[:6]),
            "variables": list(objective.variables[:6]),
            "outcomes": list(objective.outcomes[:3]),
            "confirmation_status": objective.confirmation_status,
            "published_analysis_version": objective.published_analysis_version,
            "confidence": objective.confidence,
        }


class BrowseWorkspacePapersToolRequest(BaseModel):
    """Bounded, researcher-visible paper screening parameters."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=240)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(
        default=_PAPER_LIMIT, ge=1, le=_PAPER_LIMIT,
        description="Optional record cap; the returned page is fitted to the available context. Follow next_offset.",
    )

    @field_validator("query")
    @classmethod
    def _normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split()).casefold()
        return normalized or None


class BrowseWorkspacePapersService:
    """Screen paper identities and high-level map signals before Source reading."""


    async def execute(
        self,
        *,
        user_id: str,
        workspace_id: str,
        tool_call_id: str | None,
        max_result_tokens: int,
        arguments: BrowseWorkspacePapersToolRequest,
    ) -> ChatToolResult:
        workspace = await workspace_service.get_workspace_for_user(
            workspace_id,
            user_id,
        )
        document_records = workspace.documents
        document_ids = tuple(item.document.document_id for item in document_records)
        profiles = await DocumentProfileRepo.list_workspace(
            workspace_id,
            document_ids=document_ids or None,
        )
        paper_maps = await PaperMapRepo.list_workspace(
            workspace_id,
            document_ids=document_ids or None,
        )
        profiles_by_id = {profile.document_id: profile for profile in profiles}
        maps_by_id = {paper_map.document_id: paper_map for paper_map in paper_maps}

        candidates = [
            (record, profiles_by_id.get(record.document.document_id))
            for record in document_records
        ]
        if arguments.query:
            candidates = [
                (record, profile)
                for record, profile in candidates
                if self._matches_query(record, profile, arguments.query)
            ]
        visible_candidates = candidates[
            arguments.offset : arguments.offset + arguments.limit
        ]
        paper_records: list[dict[str, Any]] = []
        for record, profile in visible_candidates:
            document_id = str(record.document.document_id or "")
            paper_map = maps_by_id.get(document_id)
            source_document = None
            try:
                source_document = await SourceRepo.read_document(
                    workspace_id,
                    document_id,
                )
            except Exception:
                logger.warning(
                    "Paper screening Source read failed document_id=%s",
                    document_id,
                    exc_info=True,
                )
                source_status = "read_failed"
            else:
                if source_document is not None:
                    source_status = "available"
                else:
                    source_status = {
                        "processing": "preparing",
                        "stored": "not_prepared",
                        "uploaded": "not_prepared",
                        "failed": "preparation_failed",
                    }.get(str(record.status or ""), "unavailable")
            abstract_excerpt, abstract_status = self._abstract_excerpt(source_document)
            screening_limitations: list[str] = []
            if profile is None:
                screening_limitations.append("Document Profile is not available.")
            if paper_map is None:
                screening_limitations.append("Paper Map is not available yet.")
            elif paper_map.map_status == "insufficient_map":
                screening_limitations.extend(paper_map.map_limitations[:3])
            if abstract_status == "not_found":
                screening_limitations.append(
                    "No explicitly labelled Abstract Source was available for this paper."
                )
            paper_records.append(
                self._paper_record(
                    record,
                    profile,
                    paper_map,
                    abstract_excerpt=abstract_excerpt,
                    abstract_status=abstract_status,
                    source_status=source_status,
                    screening_limitations=screening_limitations,
                )
            )

        next_offset = arguments.offset + len(visible_candidates)
        if next_offset >= len(candidates):
            next_offset = None
        failed_source_count = sum(
            paper["source_status"] in {"preparation_failed", "unavailable", "read_failed"}
            for paper in paper_records
        )
        result = ChatToolResult(
            tool_call_id=tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "query": arguments.query,
                "catalog_digest": hashlib.sha256(json.dumps(document_ids).encode()).hexdigest(),
                "paper_total": len(candidates),
                "offset": arguments.offset,
                "limit": arguments.limit,
                "returned_paper_count": len(paper_records),
                "next_offset": next_offset,
                "papers": paper_records,
                "support_is_evidence": False,
                "screening_only": True,
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="workspace",
                    resource_id=workspace_id,
                    href=f"/workspaces/{workspace_id}",
                ),
                *(
                    ChatResourceRef(
                        resource_type="document",
                        resource_id=str(item.get("document_id") or ""),
                        href=(
                            f"/workspaces/{workspace_id}/documents/"
                            f"{item.get('document_id')}"
                        ),
                    )
                    for item in paper_records
                ),
            ),
            warnings=(
                (
                    f"Prepared Source content is unavailable for {failed_source_count} paper(s) "
                    "on this page. Check each paper's source_status; this is not scientific absence.",
                )
                if failed_source_count
                else ()
            ),
        )
        while len(paper_records) > 1 and ChatContextBuilder.estimate_tokens(
            ChatContextBuilder.tool_result_message(result)
        ) > max_result_tokens:
            paper_records.pop()
            visible_ids = {paper["document_id"] for paper in paper_records}
            failed_source_count = sum(
                paper["source_status"] in {"preparation_failed", "unavailable", "read_failed"}
                for paper in paper_records
            )
            result = replace(
                result,
                data={**result.data, "papers": list(paper_records),
                      "returned_paper_count": len(paper_records),
                      "next_offset": arguments.offset + len(paper_records)},
                resource_refs=tuple(ref for ref in result.resource_refs
                                    if ref.resource_type == "workspace" or ref.resource_id in visible_ids),
                warnings=(
                    (f"Prepared Source content is unavailable for {failed_source_count} paper(s) "
                     "on this page. Check each paper's source_status; this is not scientific absence.",)
                    if failed_source_count else ()
                ),
            )
        return result

    @staticmethod
    def _matches_query(record: StoredDocument, profile: Any, query: str) -> bool:
        values = [
            record.document.filename,
            record.storage_key,
            getattr(profile, "title", None),
        ]
        haystack = " ".join(str(value or "") for value in values).casefold()
        return query in haystack

    @classmethod
    def _paper_record(
        cls,
        record: StoredDocument,
        profile: Any,
        paper_map: Any,
        *,
        abstract_excerpt: str | None,
        abstract_status: str,
        source_status: str,
        screening_limitations: list[str],
    ) -> dict[str, Any]:
        document_id = str(record.document.document_id or "")
        map_studies = tuple(getattr(paper_map, "studies", ()) or ())
        materials = cls._unique(
            value
            for study in map_studies
            for value in getattr(study, "material_scope", ())
        )
        processes = cls._unique(
            value
            for study in map_studies
            for value in getattr(study, "process_context", ())
        )
        variables = cls._unique(
            value
            for study in map_studies
            for relationship in getattr(study, "relationships", ())
            for value in getattr(relationship, "varied_factors", ())
        )
        outcomes = cls._unique(
            getattr(relationship, "outcome", "")
            for study in map_studies
            for relationship in getattr(study, "relationships", ())
        )
        return {
            "document_id": document_id,
            "filename": str(
                record.document.filename
                or record.storage_key
                or document_id
            )[:500],
            "title": (
                str(getattr(profile, "title", None) or "")[:500]
                or None
            ),
            "status": str(record.status or "unknown"),
            "source_status": source_status,
            "document_type": str(getattr(profile, "doc_type", None) or "uncertain"),
            "profile_confidence": getattr(profile, "confidence", None),
            "paper_role": str(getattr(paper_map, "doc_role", None) or "unknown"),
            "map_status": (
                str(getattr(paper_map, "map_status", None) or "not_available")
                if paper_map is not None
                else "not_available"
            ),
            "map_confidence": getattr(paper_map, "confidence", None),
            "materials": materials,
            "processes": processes,
            "variables": variables,
            "outcomes": outcomes,
            "abstract_excerpt": abstract_excerpt,
            "abstract_status": abstract_status,
            "screening_limitations": screening_limitations[:5],
            "screening_only": True,
            "support_is_evidence": False,
        }

    @staticmethod
    def _unique(values: Any) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = " ".join(str(value or "").split()).strip()
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                output.append(text[:240])
        return output[:12]

    @staticmethod
    def _abstract_excerpt(document: Any) -> tuple[str | None, str]:
        if document is None:
            return None, "source_not_ready"
        blocks = sorted(
            getattr(document, "blocks", ()) or (),
            key=lambda item: getattr(item, "block_order", 0),
        )
        for block in blocks:
            heading = str(getattr(block, "heading_path", "") or "").casefold()
            if "abstract" not in heading and "摘要" not in heading:
                continue
            text = " ".join(str(getattr(block, "text", "") or "").split()).strip()
            if text:
                return text[:_ABSTRACT_LIMIT], "found"
        # Some parsers keep the Abstract label in the paragraph, not its heading.
        for block in blocks:
            heading = str(getattr(block, "heading_path", "") or "")
            if re.search(r"\b(?:references|bibliography)\b|参考文献", heading, re.IGNORECASE):
                continue
            match = re.match(
                r"^\s*(?:abstract\b|摘要)\s*[:：—–-]\s*(\S.*)$",
                str(getattr(block, "text", "") or ""),
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                text = " ".join(match.group(1).split())
                return text[:_ABSTRACT_LIMIT], "found"
        return None, "not_found"


__all__ = [
    "BrowseWorkspacePapersToolRequest",
    "BrowseWorkspacePapersService",
    "GetWorkspaceContextToolRequest",
    "GetWorkspaceContextService",
    "browse_workspace_papers",
    "get_workspace_context",
]


async def get_workspace_context(
    *, user_id: str, workspace_id: str, tool_call_id: str | None,
    task_id: str = "", operation_id: str = "", max_result_tokens: int = 12_000,
) -> ChatToolResult:
    return await GetWorkspaceContextService().execute(
        user_id=user_id,
        workspace_id=workspace_id,
        tool_call_id=tool_call_id,
        max_result_tokens=max_result_tokens,
        _arguments=GetWorkspaceContextToolRequest(),
    )


async def browse_workspace_papers(
    *, user_id: str, workspace_id: str, query: str | None, offset: int,
    limit: int, tool_call_id: str | None, task_id: str = "", operation_id: str = "",
    max_result_tokens: int = 12_000,
) -> ChatToolResult:
    return await BrowseWorkspacePapersService().execute(
        user_id=user_id,
        workspace_id=workspace_id,
        tool_call_id=tool_call_id,
        max_result_tokens=max_result_tokens,
        arguments=BrowseWorkspacePapersToolRequest(query=query, offset=offset, limit=limit),
    )
