from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from application.core.objectives import property_matching
from application.core.objectives.llm.structured_response import StructuredResponseClient

PAPER_SIGNAL_RECONCILIATION_PROMPT_VERSION = "paper_signal_reconciliation.v5"
PAPER_SIGNAL_RECONCILIATION_PROMPT_TOKEN_LIMIT = 12_288

_MAX_COMPLETION_TOKENS = 4096

_SYSTEM_PROMPT = """
You are adjudicating one bounded candidate neighborhood within one paper.

Non-negotiable rules:
- This batch has exactly one outcome anchor and candidate variable signals selected by the backend.
- This is paper-level membership adjudication, not cross-paper grouping or final synthesis.
- Return exactly one JSON object and nothing else.
- Link signals only when their supplied excerpts support one paper-owned research scope.
- Copy only supplied short `signal_label` values; never invent scientific labels or identifiers.
- The backend owns real signal and Source identity.
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


class _StructuredModelSignalRelationship(_SignalReconciliationResponse):
    signal_labels: list[Annotated[str, Field(max_length=12)]] = Field(
        min_length=2,
        max_length=12,
    )
    confidence: float = 0.0

    @field_validator("signal_labels", mode="before")
    @classmethod
    def _normalize_signal_labels(cls, value: object) -> object:
        return _normalize_list(value)

    @model_validator(mode="after")
    def _validate_unique_signal_labels(self) -> "_StructuredModelSignalRelationship":
        if len(self.signal_labels) != len(set(self.signal_labels)):
            raise ValueError("paper signal relationship labels must be unique")
        return self


class _StructuredModelUnresolvedSignal(_SignalReconciliationResponse):
    signal_label: Annotated[str, Field(min_length=1, max_length=12)]
    reason: Annotated[str, Field(min_length=1, max_length=240)]

    @field_validator("reason", mode="before")
    @classmethod
    def _bound_reason(cls, value: object) -> str:
        reason = " ".join(str(value or "").strip().split())
        return (reason or "No supported paper-scope link was established.")[:240]


class _StructuredModelSignalStudy(_SignalReconciliationResponse):
    relationships: list[_StructuredModelSignalRelationship] = Field(
        min_length=1,
        max_length=11,
    )

    @field_validator("relationships", mode="before")
    @classmethod
    def _normalize_relationships(cls, value: object) -> object:
        return _normalize_list(value)


class _StructuredModelSignalReconciliation(_SignalReconciliationResponse):
    studies: list[_StructuredModelSignalStudy] = Field(
        default_factory=list,
        max_length=1,
    )
    unresolved_signals: list[_StructuredModelUnresolvedSignal] = Field(
        default_factory=list,
        max_length=12,
    )

    @field_validator("studies", "unresolved_signals", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)


def _paper_signal_model_payload(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    signals_by_label: dict[str, Mapping[str, Any]] = {}
    signal_ids: set[str] = set()
    type_positions = {"variable": 0, "outcome": 0}
    model_signals: list[dict[str, Any]] = []
    for signal in payload.get("signals") or ():
        if not isinstance(signal, Mapping):
            continue
        signal_id = str(signal.get("signal_id") or "").strip()
        signal_type = str(signal.get("signal_type") or "").strip()
        if not signal_id or signal_type not in type_positions:
            raise ValueError(
                "paper signal reconciliation requires identified variable/outcome signals"
            )
        if signal_id in signal_ids:
            raise ValueError("paper signal reconciliation requires unique signal ids")
        signal_ids.add(signal_id)
        type_positions[signal_type] += 1
        prefix = "V" if signal_type == "variable" else "O"
        signal_label = f"{prefix}{type_positions[signal_type]}"
        signals_by_label[signal_label] = signal
        model_signal = {
            "signal_label": signal_label,
            **{
                key: signal[key]
                for key in (
                    "signal_type",
                    "label",
                    "experiment_label",
                    "design_type",
                    "claim_scope",
                    "material_scope",
                    "process_context",
                    "confidence",
                )
                if signal.get(key) not in (None, "", [], {})
            },
            "sources": [
                {
                    "section_path": str(source.get("section_path") or "").strip(),
                    "excerpt": str(source.get("excerpt") or "").strip(),
                }
                for source in signal.get("sources") or ()
                if isinstance(source, Mapping)
                and str(source.get("excerpt") or "").strip()
            ],
        }
        model_signals.append(model_signal)
    return {"signals": model_signals}, signals_by_label


def _rebind_signal_reconciliation(
    response: _StructuredModelSignalReconciliation,
    *,
    signals_by_label: Mapping[str, Mapping[str, Any]],
) -> StructuredPaperSignalReconciliation:
    returned_labels = {
        label
        for study in response.studies
        for relationship in study.relationships
        for label in relationship.signal_labels
    } | {item.signal_label for item in response.unresolved_signals}
    unknown_labels = sorted(returned_labels - signals_by_label.keys())
    if unknown_labels:
        raise ValueError(
            "paper signal reconciliation references unknown signal labels: "
            f"{unknown_labels}"
        )
    return StructuredPaperSignalReconciliation.model_validate(
        {
            "studies": [
                {
                    "relationships": [
                        {
                            "signal_ids": [
                                str(
                                    signals_by_label[label].get("signal_id") or ""
                                ).strip()
                                for label in relationship.signal_labels
                            ],
                            "confidence": relationship.confidence,
                        }
                        for relationship in study.relationships
                    ]
                }
                for study in response.studies
            ],
            "unresolved_signals": [
                {
                    "signal_id": str(
                        signals_by_label[item.signal_label].get("signal_id") or ""
                    ).strip(),
                    "reason": item.reason,
                }
                for item in response.unresolved_signals
            ],
        }
    )


def build_paper_signal_reconciliation_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    model_payload, _signals_by_label = _paper_signal_model_payload(payload)
    user_prompt = (
        "TASK MODEL\n"
        "Decide whether the candidate variables in one bounded candidate neighborhood "
        "belong to the same stated paper-owned research scope as its exactly one "
        "outcome anchor. "
        "This is membership adjudication, not scientific-field generation or "
        "whole-paper discovery.\n\n"
        "INPUT SCHEMA\n"
        "- `signals` contains exactly one outcome anchor and one or more candidate "
        "variables. Each has a request-local `signal_label`, exact scientific label, "
        "bounded paper-scope context, and high-level Source excerpts.\n"
        "- Signals omitted from this request are outside the current batch; omitted "
        "paper signals are outside this batch, not negative evidence.\n"
        "- Source excerpts are the authority for deciding whether signals describe the "
        "same stated research scope. Detailed experiment facts are not available at "
        "this stage.\n\n"
        f"Input JSON:\n{json.dumps(model_payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
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
        "as unresolved, so never invent a reason merely to repeat a label.\n\n"
        "HARD RULES\n"
        "- In every relationship, copy only input `signal_label` values and include at "
        "least one variable signal and one outcome signal.\n"
        "- Keep `signal_labels` unique inside each relationship, and never return the "
        "same signal membership more than once. Relationship membership is unordered; "
        "reversing the same labels does not create another relationship.\n"
        "- Never combine incompatible materials, process families, claim ownership, "
        "or explicit contexts. Ambiguous proximity is not a link.\n"
        "- Do not output labels, contexts, Source locators, questions, or new scientific "
        "fields; the backend derives them from selected signals.\n"
        "- Do not mark a signal unresolved if it appears in a relationship. Backend "
        "relationship acceptance is authoritative when the response repeats a label.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Split high-level statement: an abstract says laser power was varied for LPBF "
        "316L, and the conclusion says the paper evaluated relative density across "
        "those power conditions. Link both signal labels into one relationship.\n"
        "- Different scopes: one high-level Source describes heat-treatment effects on "
        "tensile strength, while another describes as-built corrosion behavior without "
        "linking it to heat treatment. Return the unmatched signals unresolved.\n"
        "- Ambiguous outcome: a caption lists hardness without identifying which stated "
        "process axis it accompanies. Keep the hardness signal unresolved.\n\n"
        "- Duplicate membership: [V1,O1] and [O1,V1] are the same relationship. "
        "Return it once.\n\n"
        "OUTPUT CONTRACT\n"
        "Return exactly `studies` and `unresolved_signals`. Return at most one study, "
        "up to 11 relationships, and up to 12 unresolved signals. Each relationship "
        "contains only `signal_labels` and `confidence`; each unresolved item has one "
        "`signal_label` and a concise `reason`. The backend derives final whole-paper "
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
        _model_payload, signals_by_label = _paper_signal_model_payload(payload)
        signals_by_id = {
            str(signal.get("signal_id") or "").strip(): signal
            for signal in signals_by_label.values()
        }
        allowed_labels = tuple(signals_by_label)
        conflicting_response_count = 0

        def validate_or_recover_contexts(response: BaseModel) -> BaseModel | None:
            nonlocal conflicting_response_count
            if not isinstance(response, _StructuredModelSignalReconciliation):
                raise TypeError("unexpected paper signal reconciliation response type")
            rebound = _rebind_signal_reconciliation(
                response,
                signals_by_label=signals_by_label,
            )
            conflicts = _paper_signal_reconciliation_conflicts(
                rebound,
                signals_by_id=signals_by_id,
            )
            if not conflicts:
                return rebound
            conflicting_response_count += 1
            if conflicting_response_count == 1:
                raise ValueError(
                    "paper signal relationships must be context-compatible; "
                    + "; ".join(conflicts)
                )
            return _discard_conflicting_signal_relationships(
                rebound,
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
                "unresolved records for omitted inputs. Copy only these request-local "
                f"signal labels: {json.dumps(allowed_labels, ensure_ascii=True)}."
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
            response_model=_StructuredModelSignalReconciliation,
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
            response_model=_StructuredModelSignalReconciliation,
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
