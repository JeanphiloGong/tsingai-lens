from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.core.objectives import property_matching
from application.core.objectives.llm.structured_response import StructuredResponseClient

PAPER_SIGNAL_RECONCILIATION_PROMPT_VERSION = "paper_signal_reconciliation.v4"
PAPER_SIGNAL_RECONCILIATION_PROMPT_TOKEN_LIMIT = 12_288

_MAX_COMPLETION_TOKENS = 4096

_SYSTEM_PROMPT = """
You are adjudicating one bounded candidate neighborhood within one paper.

Non-negotiable rules:
- This batch has exactly one outcome anchor and candidate variable signals selected by the backend.
- This is paper-level membership adjudication, not cross-paper grouping or final synthesis.
- Return exactly one JSON object and nothing else.
- Link signals only when their supplied excerpts support one paper-owned research scope.
- Copy only supplied `signal_id` values; never invent scientific labels or ids.
- Preserve ambiguity by returning an unresolved signal instead of guessing a link.
- Account only for the current batch; the backend derives final whole-paper accounting.
""".strip()


def _normalize_list(value: object) -> object:
    return [] if value is None else value


class _SignalReconciliationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("confidence", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_confidence(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["confidence"].get_default(call_default_factory=True)


class StructuredPaperSignalRelationship(_SignalReconciliationResponse):
    signal_ids: list[Annotated[str, Field(max_length=80)]] = Field(
        min_length=2,
        max_length=12,
    )
    confidence: float = 0.0

    @field_validator("signal_ids", mode="before")
    @classmethod
    def _normalize_signal_ids(cls, value: object) -> object:
        return _normalize_list(value)


class StructuredUnresolvedPaperSignal(_SignalReconciliationResponse):
    signal_id: Annotated[str, Field(min_length=1, max_length=80)]
    reason: Annotated[str, Field(min_length=1, max_length=240)]

    @field_validator("reason", mode="before")
    @classmethod
    def _bound_reason(cls, value: object) -> str:
        reason = " ".join(str(value or "").strip().split())
        return (reason or "No supported paper-scope link was established.")[:240]


class StructuredPaperSignalStudy(_SignalReconciliationResponse):
    relationships: list[StructuredPaperSignalRelationship] = Field(
        min_length=1,
        max_length=11,
    )

    @field_validator("relationships", mode="before")
    @classmethod
    def _normalize_relationships(cls, value: object) -> object:
        return _normalize_list(value)


class StructuredPaperSignalReconciliation(_SignalReconciliationResponse):
    studies: list[StructuredPaperSignalStudy] = Field(
        default_factory=list,
        max_length=1,
    )
    unresolved_signals: list[StructuredUnresolvedPaperSignal] = Field(
        default_factory=list,
        max_length=12,
    )

    @field_validator("studies", "unresolved_signals", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)


def build_paper_signal_reconciliation_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "TASK MODEL\n"
        "Decide whether the candidate variables in one bounded candidate neighborhood "
        "belong to the same stated paper-owned research scope as its exactly one "
        "outcome anchor. "
        "This is membership adjudication, not scientific-field generation or "
        "whole-paper discovery.\n\n"
        "INPUT SCHEMA\n"
        "- `document_id` identifies the one paper.\n"
        "- `signals` contains exactly one outcome anchor and one or more candidate "
        "variables. Each has a backend-owned `signal_id`, exact label, bounded "
        "paper-scope context, and high-level Source excerpts with stable Source-unit "
        "positions.\n"
        "- Signals omitted from this request are outside the current batch; omitted "
        "paper signals are outside this batch, not negative evidence.\n"
        "- Source excerpts are the authority for deciding whether signals describe the "
        "same stated research scope. Detailed experiment facts are not available at "
        "this stage.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "DECISION PROCESS\n"
        "1. Identify the single outcome anchor and evaluate each candidate variable "
        "against it.\n"
        "2. Compare material, process family, claim ownership, and Source statements. "
        "Do not link signals merely because they occur in the same paper or nearby "
        "sections.\n"
        "3. Form a relationship only when the high-level excerpts state that the "
        "variable was varied, compared, or modeled and the outcome was inspected in "
        "that same paper-owned research scope.\n"
        "4. Return at most one paper-scope group for this neighborhood. Relationships "
        "may share the outcome anchor only when the Source supports that membership.\n"
        "5. Do not infer sample groups, controls, test settings, values, directions, or "
        "a complete experiment. Do not reason about omitted signals.\n"
        "6. Include a rejected candidate once in `unresolved_signals` when a concise "
        "scientific reason is visible. The backend treats every omitted input signal "
        "as unresolved, so never invent a reason merely to repeat an ID.\n\n"
        "HARD RULES\n"
        "- In every relationship, copy only input `signal_id` values and include at "
        "least one variable signal and one outcome signal.\n"
        "- Keep `signal_ids` unique inside each relationship, and never return the "
        "same signal membership more than once. Relationship membership is unordered; "
        "reversing the same IDs does not create another relationship.\n"
        "- Never combine incompatible materials, process families, claim ownership, "
        "or explicit contexts. Ambiguous proximity is not a link.\n"
        "- Do not output labels, contexts, Source locators, questions, or new scientific "
        "fields; the backend derives them from selected signals.\n"
        "- Do not mark a signal unresolved if it appears in a relationship. Backend "
        "relationship acceptance is authoritative when the response repeats an ID.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Split high-level statement: an abstract says laser power was varied for LPBF "
        "316L, and the conclusion says the paper evaluated relative density across "
        "those power conditions. Link both signal ids into one relationship.\n"
        "- Different scopes: one high-level Source describes heat-treatment effects on "
        "tensile strength, while another describes as-built corrosion behavior without "
        "linking it to heat treatment. Return the unmatched signals unresolved.\n"
        "- Ambiguous outcome: a caption lists hardness without identifying which stated "
        "process axis it accompanies. Keep the hardness signal unresolved.\n\n"
        "- Duplicate membership: [variable-a,outcome-a] and "
        "[outcome-a,variable-a] are the same relationship. Return it once.\n\n"
        "OUTPUT CONTRACT\n"
        "Return exactly `studies` and `unresolved_signals`. Return at most one study, "
        "up to 11 relationships, and up to 12 unresolved signals. Each relationship "
        "contains only `signal_ids` and `confidence`; each unresolved item has one "
        "`signal_id` and a concise `reason`. The backend derives final whole-paper "
        "accounting after all candidate batches finish. Return empty arrays when appropriate."
    )
    return _SYSTEM_PROMPT, user_prompt


class PaperSignalReconciler:
    """Adjudicate one bounded paper-scope variable/outcome neighborhood."""

    def __init__(self, response_client: StructuredResponseClient) -> None:
        self.response_client = response_client

    def reconcile(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperSignalReconciliation:
        system_prompt, user_prompt = build_paper_signal_reconciliation_prompt(payload)
        signals_by_id = {
            str(signal.get("signal_id") or "").strip(): signal
            for signal in payload.get("signals") or ()
            if isinstance(signal, Mapping)
            and str(signal.get("signal_id") or "").strip()
        }
        conflicting_response_count = 0

        def validate_or_recover_contexts(response: BaseModel) -> BaseModel | None:
            nonlocal conflicting_response_count
            if not isinstance(response, StructuredPaperSignalReconciliation):
                raise TypeError("unexpected paper signal reconciliation response type")
            conflicts = _paper_signal_reconciliation_conflicts(
                response,
                signals_by_id=signals_by_id,
            )
            if not conflicts:
                return None
            conflicting_response_count += 1
            if conflicting_response_count == 1:
                raise ValueError(
                    "paper signal relationships must be context-compatible; "
                    + "; ".join(conflicts)
                )
            return _discard_conflicting_signal_relationships(
                response,
                signals_by_id=signals_by_id,
            )

        def build_repair_instruction(repair_detail: str) -> str:
            return (
                "Previous paper signal reconciliation was invalid: "
                f"{repair_detail}. Make every relationship context-compatible. "
                "Do not combine signals when material_scope, process_context, "
                "experiment_label, design_type, or claim_scope conflict. Return only safe "
                "relationships, optionally explain rejected candidates in "
                "unresolved_signals, and return only compact JSON. The backend derives "
                "unresolved records for omitted inputs."
            )

        def parse_json_text_with_contract(**kwargs: Any) -> tuple[BaseModel, str | None]:
            return self.response_client.complete_json(
                **kwargs,
                repair_instruction_builder=build_repair_instruction,
                parsed_validator=validate_or_recover_contexts,
            )

        response = self.response_client.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperSignalReconciliation,
            max_completion_tokens=_MAX_COMPLETION_TOKENS,
            json_text_parser=parse_json_text_with_contract,
            parsed_validator=validate_or_recover_contexts,
            task_type="paper_signal_reconciliation",
            prompt_version=PAPER_SIGNAL_RECONCILIATION_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredPaperSignalReconciliation):
            raise TypeError("unexpected paper signal reconciliation response type")
        return response

    def estimate_prompt_tokens(self, payload: dict[str, Any]) -> int:
        """Count the complete schema-bearing reconciliation prompt."""

        system_prompt, user_prompt = build_paper_signal_reconciliation_prompt(payload)
        return self.response_client.estimate_prompt_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperSignalReconciliation,
        )


def _paper_signal_reconciliation_conflicts(
    response: StructuredPaperSignalReconciliation,
    *,
    signals_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    conflicts: list[str] = []
    for study_position, study in enumerate(response.studies):
        for relationship_position, relationship in enumerate(study.relationships):
            signal_ids = tuple(
                str(signal_id).strip() for signal_id in relationship.signal_ids
            )
            context_conflicts = property_matching.paper_signal_context_conflicts(
                signals_by_id[signal_id]
                for signal_id in signal_ids
                if signal_id in signals_by_id
            )
            if context_conflicts:
                conflicts.append(
                    f"studies[{study_position}].relationships"
                    f"[{relationship_position}] signal_ids={list(signal_ids)} "
                    f"conflict in {', '.join(context_conflicts)}"
                )
    return tuple(conflicts)


def _discard_conflicting_signal_relationships(
    response: StructuredPaperSignalReconciliation,
    *,
    signals_by_id: Mapping[str, Mapping[str, Any]],
) -> StructuredPaperSignalReconciliation:
    studies: list[dict[str, Any]] = []
    retained_signal_ids: set[str] = set()
    rejected_reasons_by_id: dict[str, str] = {}
    for study in response.studies:
        relationships: list[dict[str, Any]] = []
        for relationship in study.relationships:
            signal_ids = tuple(
                str(signal_id).strip() for signal_id in relationship.signal_ids
            )
            conflicts = property_matching.paper_signal_context_conflicts(
                signals_by_id[signal_id]
                for signal_id in signal_ids
                if signal_id in signals_by_id
            )
            if conflicts:
                reason = f"Conflicting reconciliation context: {', '.join(conflicts)}."
                for signal_id in signal_ids:
                    rejected_reasons_by_id.setdefault(signal_id, reason)
                continue
            relationships.append(relationship.model_dump())
            retained_signal_ids.update(signal_ids)
        if relationships:
            studies.append({"relationships": relationships})

    unresolved = [item.model_dump() for item in response.unresolved_signals]
    unresolved_ids = {str(item["signal_id"]).strip() for item in unresolved}
    for signal_id, reason in rejected_reasons_by_id.items():
        if signal_id in retained_signal_ids or signal_id in unresolved_ids:
            continue
        unresolved.append({"signal_id": signal_id, "reason": reason})
        unresolved_ids.add(signal_id)
    return StructuredPaperSignalReconciliation.model_validate(
        {"studies": studies, "unresolved_signals": unresolved}
    )


__all__ = [
    "PAPER_SIGNAL_RECONCILIATION_PROMPT_TOKEN_LIMIT",
    "PaperSignalReconciler",
    "StructuredPaperSignalReconciliation",
    "build_paper_signal_reconciliation_prompt",
]
