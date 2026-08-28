"""Transient Objective drafts supported by collection proposal context."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.core.objectives import property_matching
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


ShortText = Annotated[str, Field(min_length=1, max_length=240)]


def normalize_terms(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


class ObjectiveDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=5, max_length=500)
    material_scope: list[ShortText] = Field(default_factory=list, max_length=6)
    variables: list[ShortText] = Field(min_length=1, max_length=6)
    outcomes: list[ShortText] = Field(min_length=1, max_length=1)
    mechanisms: list[ShortText] = Field(default_factory=list, max_length=6)
    constraints: list[ShortText] = Field(default_factory=list, max_length=8)
    requested_comparator: str | None = Field(default=None, max_length=240)

    @field_validator(
        "material_scope",
        "variables",
        "outcomes",
        "mechanisms",
        "constraints",
    )
    @classmethod
    def _normalize_lists(cls, values: list[str]) -> list[str]:
        return normalize_terms(values)

    @field_validator("question")
    @classmethod
    def _normalize_question(cls, value: str) -> str:
        return " ".join(value.split())


class ProposeObjectiveDraftsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drafts: list[ObjectiveDraftInput] = Field(min_length=1, max_length=3)


class ProposeObjectiveDraftsCapability:
    spec = ToolSpec(
        name="propose_objective_drafts",
        description=(
            "Record one to three focused transient Research Objective drafts for user "
            "review. Each draft must have one specific outcome. The result may report "
            "PaperResearchMap proposal context, but it is not Evidence and does not "
            "create a Core Objective."
        ),
        risk=ToolRisk.DRAFT,
        input_model=ProposeObjectiveDraftsArguments,
    )

    def __init__(
        self,
        *,
        collection_service: Any,
        objective_repository: Any,
        paper_map_repository: Any,
    ) -> None:
        self.collection_service = collection_service
        self.objective_repository = objective_repository
        self.paper_map_repository = paper_map_repository

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: ProposeObjectiveDraftsArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        paper_maps = await self.paper_map_repository.list_collection(
            context.collection_id
        )
        existing = await self.objective_repository.list_objectives(
            context.collection_id
        )
        records: list[dict[str, Any]] = []
        refs: list[ChatResourceRef] = []
        unsupported_count = 0
        for position, draft in enumerate(arguments.drafts):
            support_ids = self._supporting_documents(draft, paper_maps)
            similar_ids = self._similar_objectives(draft, existing)
            if not support_ids:
                unsupported_count += 1
            draft_id = self._draft_id(context.tool_call_id, position, draft)
            records.append(
                {
                    "draft_id": draft_id,
                    "status": "draft",
                    **draft.model_dump(),
                    "support_status": (
                        "paper_map_context" if support_ids else "unsupported"
                    ),
                    "supporting_document_ids": list(support_ids),
                    "similar_objective_ids": list(similar_ids),
                    "support_is_evidence": False,
                }
            )
            refs.append(
                ChatResourceRef(
                    resource_type="objective_draft",
                    resource_id=draft_id,
                )
            )
        warnings = (
            (
                f"{unsupported_count} drafts have no matching PaperResearchMap "
                "relationship context; they remain unverified proposals.",
            )
            if unsupported_count
            else ()
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "draft_count": len(records),
                "drafts": records,
                "persistence": "transient_chat_result",
            },
            resource_refs=tuple(refs),
            warnings=warnings,
        )

    @staticmethod
    def _supporting_documents(
        draft: ObjectiveDraftInput,
        paper_maps: tuple,
    ) -> tuple[str, ...]:
        document_ids: list[str] = []
        for paper_map in paper_maps:
            if any(
                ProposeObjectiveDraftsCapability._relationship_supports(
                    draft,
                    study.material_scope,
                    relationship.varied_factors,
                    relationship.outcome,
                )
                for study in paper_map.studies
                for relationship in study.relationships
            ):
                document_ids.append(paper_map.document_id)
        return tuple(dict.fromkeys(document_ids))

    @staticmethod
    def _relationship_supports(
        draft: ObjectiveDraftInput,
        study_materials: tuple[str, ...],
        varied_factors: tuple[str, ...],
        outcome: str,
    ) -> bool:
        material_matches = (
            not draft.material_scope
            or not study_materials
            or any(
                property_matching.axis_values_match(draft_material, study_material)
                for draft_material in draft.material_scope
                for study_material in study_materials
            )
        )
        variables_match = all(
            any(
                property_matching.axis_values_match(variable, factor)
                for factor in varied_factors
            )
            for variable in draft.variables
        )
        outcome_matches = property_matching.axis_values_match(
            draft.outcomes[0],
            outcome,
        )
        return material_matches and variables_match and outcome_matches

    @staticmethod
    def _similar_objectives(draft: ObjectiveDraftInput, objectives: tuple) -> tuple[str, ...]:
        return tuple(
            objective.objective_id
            for objective in objectives
            if len(objective.outcomes) == 1
            and property_matching.axis_values_match(
                draft.outcomes[0],
                objective.outcomes[0],
            )
            and all(
                any(
                    property_matching.axis_values_match(variable, candidate)
                    for candidate in objective.variables
                )
                for variable in draft.variables
            )
        )[:6]

    @staticmethod
    def _draft_id(
        tool_call_id: str,
        position: int,
        draft: ObjectiveDraftInput,
    ) -> str:
        identity = json.dumps(
            {
                "tool_call_id": tool_call_id,
                "position": position,
                "draft": draft.model_dump(),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"draft_{sha256(identity.encode('utf-8')).hexdigest()[:20]}"


__all__ = [
    "ObjectiveDraftInput",
    "ProposeObjectiveDraftsArguments",
    "ProposeObjectiveDraftsCapability",
    "normalize_terms",
]
