"""Bounded collection and Objective context for the Research Agent."""

from __future__ import annotations

from application.source import collection_service
from repositories.paper_map_repository import PaperMapRepo
from repositories.objective_repository import ObjectiveRepo
from repositories.document_profile_repository import DocumentProfileRepo
from repositories.source_artifact_repository import SourceArtifactRepo

from domain.chat import ToolResultStatus

import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


_OBJECTIVE_LIMIT = 12
_PAPER_LIMIT = 12
_ABSTRACT_LIMIT = 1_200
logger = logging.getLogger(__name__)


class GetCollectionContextToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetCollectionContextCapability:
    spec = ToolSpec(
        name="get_collection_context",
        description=(
            "Read a bounded overview of the current literature collection and its "
            "Research Objective candidates. Use this before making collection-specific "
            "claims or proposing new Objective drafts."
        ),
        risk=ToolRisk.READ,
        input_model=GetCollectionContextToolRequest,
    )

    async def execute(
        self,
        context: CapabilityExecutionContext,
        _arguments: GetCollectionContextToolRequest,
    ) -> ChatToolResult:
        collection = await collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        objectives = await ObjectiveRepo.list_objectives(
            context.collection_id
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
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "collection": {
                    "collection_id": collection["collection_id"],
                    "name": collection["name"][:240],
                    "description": (
                        collection["description"][:1_000]
                        if collection.get("description")
                        else None
                    ),
                    "status": collection["status"],
                    "paper_count": collection["paper_count"],
                },
                "objective_count": len(objectives),
                "objectives": objective_records,
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="collection",
                    resource_id=context.collection_id,
                    href=f"/collections/{context.collection_id}",
                ),
                *(
                    ChatResourceRef(
                        resource_type="research_objective",
                        resource_id=item.objective_id,
                        href=(
                            f"/collections/{context.collection_id}/objectives/"
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


class BrowseCollectionPapersToolRequest(BaseModel):
    """Bounded, researcher-visible paper screening parameters."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=240)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=8, ge=1, le=_PAPER_LIMIT)

    @field_validator("query")
    @classmethod
    def _normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split()).casefold()
        return normalized or None


class BrowseCollectionPapersCapability:
    """Screen paper identities and high-level map signals before Source reading."""

    spec = ToolSpec(
        name="browse_collection_papers",
        description=(
            "Browse a bounded page of papers in the current collection by visible "
            "filename or title. The optional query is a literal identity filter, not "
            "semantic topic search; omit it to discover all visible paper identities "
            "before selecting a paper by title or filename. Returns preparation state, document type, bounded "
            "Paper Map materials, processes, variables, outcomes, and an abstract "
            "excerpt when an explicitly labelled abstract Source is available. "
            "Profile, Paper Map and abstract availability are optional navigation "
            "signals: inspect available document Sources directly when they are missing. "
            "source_status reports prepared content availability, not a completed read. "
            "Follow next_offset for later papers; an empty filename query match does "
            "not establish scientific absence. Missing map or abstract metadata does "
            "not establish an unreadable or irrelevant paper. When Source content is "
            "ready, use inspect_document_sources to inspect its outline and relevant "
            "body directly; a Paper Map is optional navigation. "
            "These are screening signals only, not Evidence, and this capability "
            "does not change the formal analysis scope."
        ),
        risk=ToolRisk.READ,
        input_model=BrowseCollectionPapersToolRequest,
    )

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: BrowseCollectionPapersToolRequest,
    ) -> ChatToolResult:
        collection = await collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        document_records = tuple(collection.get("documents") or ())
        document_ids = tuple(
            str(item.get("document_id") or "")
            for item in document_records
            if isinstance(item, dict) and str(item.get("document_id") or "").strip()
        )
        profiles = await DocumentProfileRepo.list_collection(
            context.collection_id,
            document_ids=document_ids or None,
        )
        paper_maps = await PaperMapRepo.list_collection(
            context.collection_id,
            document_ids=document_ids or None,
        )
        profiles_by_id = {profile.document_id: profile for profile in profiles}
        maps_by_id = {paper_map.document_id: paper_map for paper_map in paper_maps}

        candidates = [
            (record, profiles_by_id.get(str(record.get("document_id") or "")))
            for record in document_records
            if isinstance(record, dict)
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
            document_id = str(record.get("document_id") or "")
            paper_map = maps_by_id.get(document_id)
            source_document = None
            try:
                source_document = await SourceArtifactRepo.read_document(
                    context.collection_id,
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
                    }.get(str(record.get("status") or ""), "unavailable")
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
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "query": arguments.query,
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
                    resource_type="collection",
                    resource_id=context.collection_id,
                    href=f"/collections/{context.collection_id}",
                ),
                *(
                    ChatResourceRef(
                        resource_type="document",
                        resource_id=str(item.get("document_id") or ""),
                        href=(
                            f"/collections/{context.collection_id}/documents/"
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

    @staticmethod
    def _matches_query(record: dict[str, Any], profile: Any, query: str) -> bool:
        values = [
            record.get("original_filename"),
            record.get("stored_filename"),
            getattr(profile, "title", None),
        ]
        haystack = " ".join(str(value or "") for value in values).casefold()
        return query in haystack

    @classmethod
    def _paper_record(
        cls,
        record: dict[str, Any],
        profile: Any,
        paper_map: Any,
        *,
        abstract_excerpt: str | None,
        abstract_status: str,
        source_status: str,
        screening_limitations: list[str],
    ) -> dict[str, Any]:
        document_id = str(record.get("document_id") or "")
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
                record.get("original_filename")
                or record.get("stored_filename")
                or document_id
            )[:500],
            "title": (
                str(getattr(profile, "title", None) or "")[:500]
                or None
            ),
            "status": str(record.get("status") or "unknown"),
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
    "BrowseCollectionPapersToolRequest",
    "BrowseCollectionPapersCapability",
    "GetCollectionContextToolRequest",
    "GetCollectionContextCapability",
]
