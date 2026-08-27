"""Read-only preview of paper scope for one proposed research question."""

from __future__ import annotations

from typing import Any, Iterable

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.chat.capabilities.objective_proposal import ObjectiveDraftInput
from application.core.objectives import property_matching
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

        likely_relevant: list[dict[str, Any]] = []
        needs_inspection: list[dict[str, Any]] = []
        confidently_out_of_scope: list[dict[str, Any]] = []
        for skim in paper_maps:
            classification, reason, basis = self._classify(skim, arguments)
            record = {
                "document_id": skim.document_id,
                "doc_role": skim.doc_role,
                "classification": classification,
                "reason": reason,
                "map_status": skim.map_status,
                "map_limitations": list(skim.map_limitations),
                "support_basis": basis,
            }
            if classification == "likely_relevant":
                likely_relevant.append(record)
            elif classification == "needs_inspection":
                needs_inspection.append(record)
            else:
                confidently_out_of_scope.append(record)
        scope_counts = {
            "likely_relevant": len(likely_relevant),
            "needs_inspection": len(needs_inspection),
            "confidently_out_of_scope": len(confidently_out_of_scope),
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
        omitted_count = len(paper_maps) - len(returned_records)

        review_required_ids = [item["document_id"] for item in needs_inspection]
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
                    "review_document_ids": review_required_ids,
                    "excluded_document_ids": [
                        item["document_id"] for item in confidently_out_of_scope
                    ],
                },
                "support_is_evidence": False,
            },
            resource_refs=refs,
            warnings=tuple(warning_items),
        )

    @classmethod
    def _classify(
        cls,
        skim: Any,
        question: PreviewResearchScopeArguments,
    ) -> tuple[str, str, list[str]]:
        relationship_matches: list[str] = []
        partial_scope = False
        for study in skim.studies:
            for relationship in study.relationships:
                if cls._scope_matches(
                    question,
                    study.material_scope,
                    relationship.varied_factors,
                    (relationship.outcome,),
                ):
                    relationship_matches.append(relationship.relationship_id)
                elif cls._scope_partially_matches(
                    question,
                    study.material_scope,
                    relationship.varied_factors,
                    (relationship.outcome,),
                ):
                    partial_scope = True
        if relationship_matches:
            return "likely_relevant", "mapped_research_scope", relationship_matches

        review_matches: list[str] = []
        for field_name in ("synthesis_claims", "disputes", "evidence_gaps"):
            for position, item in enumerate(
                getattr(skim.review_synthesis, field_name)
            ):
                if cls._scope_matches(
                    question,
                    item.material_scope,
                    item.variables,
                    item.outcomes,
                ):
                    review_matches.append(f"{field_name}:{position}")
                elif cls._scope_partially_matches(
                    question,
                    item.material_scope,
                    item.variables,
                    item.outcomes,
                ):
                    partial_scope = True
        if review_matches:
            return "likely_relevant", "review_author_judgment", review_matches

        citation_matches = [
            f"citation_leads:{position}"
            for position, item in enumerate(skim.review_synthesis.citation_leads)
            if cls._scope_matches(
                question,
                item.material_scope,
                item.variables,
                item.outcomes,
            )
        ]
        if citation_matches:
            return "needs_inspection", "citation_lead_only", citation_matches
        if skim.map_status != "sufficient":
            return "needs_inspection", "paper_map_incomplete", []
        if partial_scope or cls._unresolved_scope_matches(skim, question):
            return "needs_inspection", "partial_scope_match", []
        if cls._material_scope_conflicts(skim, question.material_scope):
            return "confidently_out_of_scope", "material_scope_conflict", []
        if any(
            property_matching.objective_variable_theme(variable) is not None
            for variable in question.variables
        ):
            return "needs_inspection", "umbrella_scope_not_established", []
        return "confidently_out_of_scope", "no_mapped_scope_match", []

    @classmethod
    def _material_scope_conflicts(
        cls,
        skim: Any,
        requested: Iterable[str],
    ) -> bool:
        requested_values = tuple(requested)
        if not requested_values:
            return False
        observed_scopes = [
            tuple(study.material_scope)
            for study in skim.studies
            if study.material_scope
        ]
        for field_name in (
            "synthesis_claims",
            "disputes",
            "evidence_gaps",
            "citation_leads",
        ):
            observed_scopes.extend(
                tuple(item.material_scope)
                for item in getattr(skim.review_synthesis, field_name)
                if item.material_scope
            )
        observed_values = tuple(
            value for scope in observed_scopes for value in scope
        )
        material_values = tuple(
            value
            for value in observed_values
            if property_matching.material_scope_value_is_specific(value)
            or property_matching.material_scope_value_is_broad(value)
        )
        return bool(material_values) and not any(
            property_matching.material_scope_value_is_broad(value)
            for value in material_values
        ) and not any(
            cls._material_matches(requested_values, observed)
            for observed in observed_scopes
        )

    @classmethod
    def _scope_matches(
        cls,
        question: PreviewResearchScopeArguments,
        materials: Iterable[str],
        variables: Iterable[str],
        outcomes: Iterable[str],
    ) -> bool:
        observed_variables = tuple(variables)
        observed_outcomes = tuple(outcomes)
        return (
            cls._material_matches(question.material_scope, tuple(materials))
            and all(
                any(
                    property_matching.variable_matches_objective_scope(
                        observed,
                        requested,
                    )
                    for observed in observed_variables
                )
                for requested in question.variables
            )
            and all(
                cls._outcome_matches(requested, observed_outcomes)
                for requested in question.outcomes
            )
        )

    @classmethod
    def _scope_partially_matches(
        cls,
        question: PreviewResearchScopeArguments,
        materials: Iterable[str],
        variables: Iterable[str],
        outcomes: Iterable[str],
    ) -> bool:
        observed_variables = tuple(variables)
        observed_outcomes = tuple(outcomes)
        if not cls._material_matches(question.material_scope, tuple(materials)):
            return False
        variable_match = any(
            property_matching.variable_matches_objective_scope(observed, requested)
            for requested in question.variables
            for observed in observed_variables
        )
        outcome_match = any(
            cls._outcome_matches(requested, observed_outcomes)
            for requested in question.outcomes
        )
        return variable_match or outcome_match

    @staticmethod
    def _material_matches(requested: Iterable[str], observed: Iterable[str]) -> bool:
        requested_values = tuple(requested)
        observed_values = tuple(observed)
        return (
            not requested_values
            or not observed_values
            or any(
                property_matching.material_values_match_for_scope(left, right)
                for left in requested_values
                for right in observed_values
            )
        )

    @classmethod
    def _unresolved_scope_matches(
        cls,
        skim: Any,
        question: PreviewResearchScopeArguments,
    ) -> bool:
        return any(
            cls._material_matches(question.material_scope, signal.material_scope)
            and (
                signal.signal_type == "variable"
                and any(
                    property_matching.variable_matches_objective_scope(
                        signal.label,
                        requested,
                    )
                    for requested in question.variables
                )
                or signal.signal_type == "outcome"
                and any(
                    cls._outcome_matches(requested, (signal.label,))
                    for requested in question.outcomes
                )
            )
            for signal in skim.unresolved_signals
        )

    @staticmethod
    def _outcome_matches(requested: str, observed: Iterable[str]) -> bool:
        return property_matching.property_matches_target_axes(
            requested,
            target_axes=tuple(observed),
        )


__all__ = ["PreviewResearchScopeArguments", "PreviewResearchScopeCapability"]
