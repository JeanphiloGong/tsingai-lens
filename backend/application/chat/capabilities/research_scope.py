"""Read-only preview of paper scope for one proposed research question."""

from __future__ import annotations

from domain.chat import ToolResultStatus

from typing import Any

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.chat.capabilities.objective_proposal import ObjectiveDraftInput
from application.core.objectives.scope_screening import screen_objective_scope
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


_PREVIEW_CATEGORY_LIMIT = 24


class PreviewResearchScopeToolRequest(ObjectiveDraftInput):
    """One focused question whose likely paper scope should be reviewed."""


class PreviewResearchScopeCapability:
    spec = ToolSpec(
        name="preview_research_scope",
        description=(
            "Preview which mapped papers are likely relevant to one focused research "
            "question, which still need researcher inspection, and which are "
            "confidently out of scope. This is a read-only screening judgment, not "
            "Evidence. A paper with an insufficient map is never automatically "
            "excluded, and review-paper citation leads are navigation only."
            " A missing exact map match for an umbrella intervention, such as energy "
            "input, is uncertainty rather than grounds to exclude a same-material "
            "paper without an explicit scope conflict. If maps are unavailable, "
            "use the paper survey and available Sources to inspect candidate scope; "
            "map construction is not a prerequisite for original-content reading."
        ),
        risk=ToolRisk.READ,
        input_model=PreviewResearchScopeToolRequest,
    )

    def __init__(self, *, collection_service: Any, paper_map_repository: Any) -> None:
        self.collection_service = collection_service
        self.paper_map_repository = paper_map_repository

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: PreviewResearchScopeToolRequest,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        paper_maps = await self.paper_map_repository.list_collection(
            context.collection_id
        )
        if not paper_maps:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.FAILED,
                error_code="paper_map_not_ready",
                error_message=(
                    "The collection Paper Map is not ready. Prepare the literature "
                    "collection before previewing question-specific scope."
                ),
            )

        preview = screen_objective_scope(paper_maps, objective=arguments)
        likely_relevant = [
            {
                "document_id": item.document_id,
                "classification": item.classification,
                "reason": item.reason,
                "doc_role": item.doc_role,
                "map_status": item.map_status,
                "map_limitations": list(item.map_limitations),
                "support_basis": list(item.support_basis),
                "is_seed": item.is_seed,
            }
            for item in preview.decisions
            if item.classification == "likely_relevant"
        ]
        needs_inspection = [
            {
                "document_id": item.document_id,
                "classification": item.classification,
                "reason": item.reason,
                "doc_role": item.doc_role,
                "map_status": item.map_status,
                "map_limitations": list(item.map_limitations),
                "support_basis": list(item.support_basis),
                "is_seed": item.is_seed,
            }
            for item in preview.decisions
            if item.classification == "needs_inspection"
        ]
        confidently_out_of_scope = [
            {
                "document_id": item.document_id,
                "classification": item.classification,
                "reason": item.reason,
                "doc_role": item.doc_role,
                "map_status": item.map_status,
                "map_limitations": list(item.map_limitations),
                "support_basis": list(item.support_basis),
                "is_seed": item.is_seed,
            }
            for item in preview.decisions
            if item.classification == "confidently_out_of_scope"
        ]
        scope_counts = preview.counts
        suggested_scope = {
            "recommended_document_ids": list(preview.recommended_document_ids),
            "review_document_ids": list(preview.review_document_ids),
            "excluded_document_ids": list(preview.excluded_document_ids),
        }
        likely_relevant = likely_relevant[:_PREVIEW_CATEGORY_LIMIT]
        needs_inspection = needs_inspection[:_PREVIEW_CATEGORY_LIMIT]
        confidently_out_of_scope = confidently_out_of_scope[
            :_PREVIEW_CATEGORY_LIMIT
        ]
        returned_records = (
            *likely_relevant,
            *needs_inspection,
            *confidently_out_of_scope,
        )
        refs = tuple(
            ChatResourceRef(
                resource_type="document",
                resource_id=record["document_id"],
                href=(
                    f"/collections/{context.collection_id}/documents/"
                    f"{record['document_id']}"
                ),
            )
            for record in returned_records
        )
        omitted_count = len(preview.decisions) - len(returned_records)

        warning_items: list[str] = []
        if scope_counts["needs_inspection"]:
            warning_items.append(
                f"{scope_counts['needs_inspection']} paper(s) still require researcher "
                "inspection before they can be included or excluded."
            )
        if omitted_count:
            warning_items.append(
                f"{omitted_count} classified paper detail record(s) were omitted from "
                "this bounded preview; the suggested scope remains complete because "
                "all classified document IDs are included."
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "question": arguments.question,
                "likely_relevant": likely_relevant,
                "needs_inspection": needs_inspection,
                "confidently_out_of_scope": confidently_out_of_scope,
                "scope_counts": scope_counts,
                "returned_record_count": len(returned_records),
                "omitted_record_count": omitted_count,
                "scope_complete": True,
                "suggested_scope": suggested_scope,
                "support_is_evidence": preview.support_is_evidence,
            },
            resource_refs=refs,
            warnings=tuple(warning_items),
        )


__all__ = ["PreviewResearchScopeToolRequest", "PreviewResearchScopeCapability"]
