"""Read-only preview of paper scope for one proposed research question."""

from __future__ import annotations

from typing import Any

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.chat.capabilities.objective_proposal import ObjectiveDraftInput
from application.core.objectives.scope_screening import screen_objective_scope
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


_PREVIEW_CATEGORY_LIMIT = 24


class PreviewResearchScopeArguments(ObjectiveDraftInput):
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
        ),
        risk=ToolRisk.READ,
        input_model=PreviewResearchScopeArguments,
    )

    def __init__(self, *, collection_service: Any, paper_map_repository: Any) -> None:
        self.collection_service = collection_service
        self.paper_map_repository = paper_map_repository

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: PreviewResearchScopeArguments,
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
                status="failed",
                error_code="paper_map_not_ready",
                error_message=(
                    "The collection Paper Map is not ready. Prepare the literature "
                    "collection before previewing question-specific scope."
                ),
            )

        preview = screen_objective_scope(paper_maps, objective=arguments)
        likely_relevant = [
            item.to_record()
            for item in preview.decisions
            if item.classification == "likely_relevant"
        ]
        needs_inspection = [
            item.to_record()
            for item in preview.decisions
            if item.classification == "needs_inspection"
        ]
        confidently_out_of_scope = [
            item.to_record()
            for item in preview.decisions
            if item.classification == "confidently_out_of_scope"
        ]
        scope_counts = preview.counts
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
                f"{omitted_count} classified paper record(s) were omitted from this "
                "bounded preview; omitted papers were not added to the suggested scope."
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "question": arguments.question,
                "likely_relevant": likely_relevant,
                "needs_inspection": needs_inspection,
                "confidently_out_of_scope": confidently_out_of_scope,
                "scope_counts": scope_counts,
                "omitted_record_count": omitted_count,
                "suggested_scope": {
                    "seed_document_ids": [
                        item["document_id"] for item in likely_relevant
                    ],
                    "review_document_ids": [
                        item["document_id"] for item in needs_inspection
                    ],
                    "excluded_document_ids": [
                        item["document_id"] for item in confidently_out_of_scope
                    ],
                },
                "support_is_evidence": preview.support_is_evidence,
            },
            resource_refs=refs,
            warnings=tuple(warning_items),
        )


__all__ = ["PreviewResearchScopeArguments", "PreviewResearchScopeCapability"]
