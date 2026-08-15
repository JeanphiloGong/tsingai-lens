from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Iterable, Mapping
from time import perf_counter
from typing import Any

import tiktoken
from openai import LengthFinishReasonError, OpenAI
from pydantic import BaseModel, ValidationError

from application.core.objectives import property_matching
from application.core.objectives.prompts import (
    FINDING_SYNTHESIS_PROMPT_VERSION,
    OBJECTIVE_EVIDENCE_EXTRACTION_PROMPT_VERSION,
    OBJECTIVE_EVIDENCE_ROUTE_PROMPT_VERSION,
    OBJECTIVE_PAPER_FRAME_PROMPT_VERSION,
    PAPER_SIGNAL_RECONCILIATION_PROMPT_VERSION,
    PAPER_SKIM_PROMPT_VERSION,
    RESEARCH_AXIS_CANONICALIZATION_PROMPT_VERSION,
    build_finding_synthesis_prompt,
    build_objective_evidence_prompt,
    build_objective_evidence_route_prompt,
    build_objective_paper_frame_prompt,
    build_paper_skim_prompt,
    build_paper_signal_reconciliation_prompt,
    build_research_axis_canonicalization_prompt,
)
from application.core.objectives.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredEvidenceExtractions,
    StructuredEvidenceSelections,
    StructuredFindingSynthesis,
    StructuredPaperFrameBatch,
    StructuredPaperSignalReconciliation,
    StructuredPaperSkim,
)
from application.core.structured_extraction.json_support import (
    coerce_message_content,
    extract_json_object,
    load_json_payload,
    trace_json,
    trace_text,
)
from infra.llm.usage import record_llm_completion, record_llm_prompt_version

logger = logging.getLogger(__name__)

_EXTRACTION_MODE_JSON_TEXT = "json_text"
_EXTRACTION_MODE_PROVIDER_PARSE = "provider_parse"
_DEFAULT_EXTRACTION_MODE = _EXTRACTION_MODE_PROVIDER_PARSE
_PAPER_SKIM_MAX_COMPLETION_TOKENS = 4096
PAPER_SKIM_PROMPT_TOKEN_LIMIT = 12_288
_PAPER_SIGNAL_RECONCILIATION_MAX_COMPLETION_TOKENS = 4096
PAPER_SIGNAL_RECONCILIATION_PROMPT_TOKEN_LIMIT = 12_288
_AXIS_CANONICALIZATION_MAX_COMPLETION_TOKENS = 1024
_OBJECTIVE_PAPER_FRAME_MAX_COMPLETION_TOKENS = 1024
OBJECTIVE_PAPER_FRAME_PROMPT_TOKEN_LIMIT = 12_288
_OBJECTIVE_EVIDENCE_SELECTION_MAX_COMPLETION_TOKENS = 512
_OBJECTIVE_EVIDENCE_MAX_COMPLETION_TOKENS = 2048
_FINDING_SYNTHESIS_MAX_COMPLETION_TOKENS = 1024
_TRACE_TEXT_LIMIT = 8000
_SUPPORTED_EXTRACTION_MODES = {
    _EXTRACTION_MODE_JSON_TEXT,
    _EXTRACTION_MODE_PROVIDER_PARSE,
}


class PaperSkimOutputSaturatedError(Exception):
    """A PaperSkim response cannot completely fit in one bounded output."""


class ObjectiveExtractor:
    """Objective-owned model extraction entrypoint."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        extraction_mode: str | None = None,
    ) -> None:
        self.model = (
            model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        ).strip() or "gpt-4o-mini"
        self.extraction_mode = self._resolve_extraction_mode(extraction_mode)
        self.enable_thinking = os.getenv("LLM_ENABLE_THINKING", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.last_trace: dict[str, Any] | None = None
        self.client = client or OpenAI(
            api_key=(api_key or os.getenv("LLM_API_KEY", "").strip() or "not-needed"),
            base_url=(base_url or os.getenv("LLM_BASE_URL", "").strip() or None),
        )

    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        system_prompt, user_prompt = build_paper_skim_prompt(payload)

        def validate_study_identities(response: BaseModel) -> None:
            if not isinstance(response, StructuredPaperSkim):
                raise TypeError("unexpected paper skim response type")
            source_keys = {
                str(source_unit.get("source_unit_id") or "").strip(): (
                    str(source_unit.get("source_kind") or "").strip(),
                    str(source_unit.get("source_ref") or "").strip(),
                )
                for source_unit in payload.get("source_units") or ()
                if isinstance(source_unit, Mapping)
                and str(source_unit.get("source_unit_id") or "").strip()
            }
            study_identities = [
                study.identity_key(source_keys) for study in response.studies
            ]
            if len(study_identities) != len(set(study_identities)):
                raise ValueError("studies contain duplicate study identities")

        def parse_json_text(**kwargs: Any) -> tuple[BaseModel, str | None]:
            return self._parse_json_text_response(
                **kwargs,
                parsed_validator=validate_study_identities,
                fail_on_output_saturation=True,
            )

        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperSkim,
            max_completion_tokens=_PAPER_SKIM_MAX_COMPLETION_TOKENS,
            json_text_parser=parse_json_text,
            parsed_validator=validate_study_identities,
            fail_on_output_saturation=True,
            task_type="paper_skim",
            prompt_version=PAPER_SKIM_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredPaperSkim):
            raise TypeError("unexpected paper skim response type")
        return response

    def estimate_paper_skim_prompt_tokens(self, payload: dict[str, Any]) -> int:
        """Count the complete repair-capable prompt before model execution."""

        system_prompt, user_prompt = build_paper_skim_prompt(payload)
        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperSkim,
            include_schema=True,
        )
        try:
            encoding = tiktoken.encoding_for_model(self.model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        serialized_messages = json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return len(encoding.encode(serialized_messages))

    def reconcile_paper_signals(
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
            conflicts = self._paper_signal_reconciliation_conflicts(
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
            return self._discard_conflicting_signal_relationships(
                response,
                signals_by_id=signals_by_id,
            )

        def build_repair_instruction(repair_detail: str) -> str:
            return (
                "Previous paper signal reconciliation was invalid: "
                f"{repair_detail}. Make every relationship context-compatible. "
                "Do not combine signals when material_scope, process_context, "
                "sample_context, test_context, fixed_conditions, experiment_label, "
                "comparator, design_type, or claim_scope conflict. Return only safe "
                "relationships, optionally explain rejected candidates in "
                "unresolved_signals, and return only compact JSON. The backend derives "
                "unresolved records for omitted inputs."
            )

        def parse_json_text(**kwargs: Any) -> tuple[BaseModel, str | None]:
            return self._parse_json_text_response(
                **kwargs,
                repair_instruction_builder=build_repair_instruction,
                parsed_validator=validate_or_recover_contexts,
            )

        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperSignalReconciliation,
            max_completion_tokens=(
                _PAPER_SIGNAL_RECONCILIATION_MAX_COMPLETION_TOKENS
            ),
            json_text_parser=parse_json_text,
            parsed_validator=validate_or_recover_contexts,
            task_type="paper_signal_reconciliation",
            prompt_version=PAPER_SIGNAL_RECONCILIATION_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredPaperSignalReconciliation):
            raise TypeError("unexpected paper signal reconciliation response type")
        return response

    def estimate_paper_signal_reconciliation_prompt_tokens(
        self,
        payload: dict[str, Any],
    ) -> int:
        """Count the complete schema-bearing reconciliation prompt."""

        system_prompt, user_prompt = build_paper_signal_reconciliation_prompt(payload)
        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperSignalReconciliation,
            include_schema=True,
        )
        try:
            encoding = tiktoken.encoding_for_model(self.model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        serialized_messages = json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return len(encoding.encode(serialized_messages))

    @staticmethod
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

    @staticmethod
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
                    reason = (
                        "Conflicting reconciliation context: "
                        f"{', '.join(conflicts)}."
                    )
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

    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        system_prompt, user_prompt = build_research_axis_canonicalization_prompt(
            payload
        )

        def validate_axis_accounting(response: BaseModel) -> None:
            if not isinstance(response, StructuredAxisCanonicalizationPlan):
                raise TypeError("unexpected research axis canonicalization response type")
            self._validate_axis_candidate_accounting(
                response,
                axis_pairs=payload.get("axis_pairs"),
            )

        def parse_json_text(**kwargs: Any) -> tuple[BaseModel, str | None]:
            return self._parse_axis_canonicalization_json_response(
                **kwargs,
                axis_accounting_validator=validate_axis_accounting,
            )

        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredAxisCanonicalizationPlan,
            max_completion_tokens=_AXIS_CANONICALIZATION_MAX_COMPLETION_TOKENS,
            json_text_parser=parse_json_text,
            parsed_validator=validate_axis_accounting,
            task_type="research_axis_canonicalization",
            prompt_version=RESEARCH_AXIS_CANONICALIZATION_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredAxisCanonicalizationPlan):
            raise TypeError("unexpected research axis canonicalization response type")
        return response

    @staticmethod
    def _validate_axis_candidate_accounting(
        response: StructuredAxisCanonicalizationPlan,
        *,
        axis_pairs: Any,
    ) -> None:
        if not isinstance(axis_pairs, list):
            raise ValueError("axis pair selection requires axis_pairs")
        expected_ids = [
            str(pair.get("pair_id") or "").strip()
            for pair in axis_pairs
            if isinstance(pair, Mapping) and str(pair.get("pair_id") or "").strip()
        ]
        decision_ids = [decision.pair_id for decision in response.decisions]
        if decision_ids != expected_ids:
            raise ValueError(
                "axis pair decisions must account for every input pair_id exactly once "
                "and in input order"
            )

    def _parse_axis_canonicalization_json_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_completion_tokens: int | None,
        axis_accounting_validator: Callable[[BaseModel], None],
    ) -> tuple[BaseModel, str | None]:
        def build_repair_instruction(repair_detail: str) -> str:
            return (
                "Previous axis pair classification was invalid: "
                f"{repair_detail}. Return one decision for every input pair_id, in "
                "input order, without omissions or duplicates. Set equivalent=true "
                "only when both labels name exactly the same scientific axis. Related, "
                "inverse, broad, narrow, or uncertain pairs require equivalent=false. "
                "Return only compact JSON."
            )

        return self._parse_json_text_response(
            messages=messages,
            response_model=response_model,
            max_completion_tokens=max_completion_tokens,
            repair_instruction_builder=build_repair_instruction,
            parsed_validator=axis_accounting_validator,
        )

    def assess_objective_paper(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperFrameBatch:
        system_prompt, user_prompt = build_objective_paper_frame_prompt(payload)
        source_accounting_errors: list[str] = []

        source_unit_ids = tuple(
            str(item.get("source_unit_id") or "").strip()
            for item in payload.get("source_units") or ()
            if isinstance(item, Mapping)
            and str(item.get("source_unit_id") or "").strip()
        )
        if not source_unit_ids or len(source_unit_ids) != len(set(source_unit_ids)):
            raise ValueError("objective paper framing requires unique source-unit ids")

        def record_source_accounting_error(error: Exception) -> None:
            detail = str(error).strip()
            if not detail or not any(
                marker in detail
                for marker in (
                    "objective paper frame must account",
                    "paper frame source-unit ids",
                )
            ):
                return
            if detail not in source_accounting_errors:
                source_accounting_errors.append(detail)

        def validate_source_accounting(parsed: BaseModel) -> BaseModel:
            if not isinstance(parsed, StructuredPaperFrameBatch):
                raise TypeError("unexpected objective paper frame response type")
            returned_ids = (
                *parsed.relevant_source_unit_ids,
                *parsed.excluded_source_unit_ids,
            )
            missing_ids = [
                source_unit_id
                for source_unit_id in source_unit_ids
                if source_unit_id not in returned_ids
            ]
            unknown_ids = [
                source_unit_id
                for source_unit_id in returned_ids
                if source_unit_id not in source_unit_ids
            ]
            if missing_ids or unknown_ids:
                raise ValueError(
                    "objective paper frame must account for every source-unit id "
                    "exactly once; "
                    f"expected_source_unit_ids={list(source_unit_ids)}; "
                    f"missing_source_unit_ids={missing_ids}; "
                    f"unknown_source_unit_ids={unknown_ids}"
                )
            return parsed

        def build_repair_instruction(repair_detail: str) -> str:
            return (
                "Previous objective paper framing output had invalid source-unit "
                f"accounting: {repair_detail}. Return only one compact JSON object. "
                "Partition this exact ID list once and only once between "
                "relevant_source_unit_ids and excluded_source_unit_ids: "
                f"{json.dumps(source_unit_ids, ensure_ascii=True)}. Copy every ID "
                "verbatim; do not omit, duplicate, shorten, or invent an ID. Treat "
                "an uncertain source as relevant."
            )

        def parse_json_text(**kwargs: Any) -> tuple[BaseModel, str | None]:
            return self._parse_json_text_response(
                **kwargs,
                repair_instruction_builder=build_repair_instruction,
                parsed_validator=validate_source_accounting,
                validation_error_observer=record_source_accounting_error,
            )

        try:
            response = self._parse_structured_response(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=StructuredPaperFrameBatch,
                max_completion_tokens=_OBJECTIVE_PAPER_FRAME_MAX_COMPLETION_TOKENS,
                json_text_parser=parse_json_text,
                parsed_validator=validate_source_accounting,
                validation_error_observer=record_source_accounting_error,
                task_type="objective_paper_frame",
                prompt_version=OBJECTIVE_PAPER_FRAME_PROMPT_VERSION,
            )
        except Exception as exc:
            if not source_accounting_errors:
                raise
            raise ValueError(
                "objective paper frame source accounting repair failed; "
                f"initial_errors={source_accounting_errors}; final_error={exc}"
            ) from exc
        if not isinstance(response, StructuredPaperFrameBatch):
            raise TypeError("unexpected objective paper frame response type")
        if source_accounting_errors:
            response.record_source_accounting_repair(source_accounting_errors)
        return response

    def estimate_objective_paper_frame_prompt_tokens(
        self,
        payload: dict[str, Any],
    ) -> int:
        """Count the complete schema-bearing objective framing prompt."""

        system_prompt, user_prompt = build_objective_paper_frame_prompt(payload)
        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperFrameBatch,
            include_schema=True,
        )
        try:
            encoding = tiktoken.encoding_for_model(self.model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        serialized_messages = json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return len(encoding.encode(serialized_messages))

    def select_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredEvidenceSelections:
        if not isinstance(payload.get("current_source"), dict):
            raise ValueError("objective evidence routing requires current_source")
        system_prompt, user_prompt = build_objective_evidence_route_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredEvidenceSelections,
            max_completion_tokens=(
                _OBJECTIVE_EVIDENCE_SELECTION_MAX_COMPLETION_TOKENS
            ),
            force_json_text=True,
            task_type="objective_evidence_route",
            prompt_version=OBJECTIVE_EVIDENCE_ROUTE_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredEvidenceSelections):
            raise TypeError("unexpected objective evidence route response type")
        return response

    def extract_objective_evidence(
        self,
        payload: dict[str, Any],
        *,
        invalid_extraction: Mapping[str, Any] | None = None,
        validation_errors: Iterable[str] = (),
    ) -> StructuredEvidenceExtractions:
        system_prompt, user_prompt = build_objective_evidence_prompt(payload)
        repair_errors = tuple(
            str(error).strip() for error in validation_errors if str(error).strip()
        )
        if invalid_extraction is not None:
            user_prompt = (
                f"{user_prompt}\n\n"
                + self._objective_evidence_repair_instruction(
                    repair_detail="; ".join(repair_errors)
                    or "the extraction failed deterministic Source grounding",
                    invalid_extraction=invalid_extraction,
                )
            )
        elif repair_errors:
            raise ValueError("Evidence repair errors require an invalid extraction")
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredEvidenceExtractions,
            max_completion_tokens=_OBJECTIVE_EVIDENCE_MAX_COMPLETION_TOKENS,
            force_json_text=True,
            include_schema_for_forced_json=False,
            json_text_parser=self._parse_objective_evidence_json_response,
            task_type="objective_evidence_extraction",
            prompt_version=OBJECTIVE_EVIDENCE_EXTRACTION_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredEvidenceExtractions):
            raise TypeError("unexpected objective evidence extraction response type")
        return response

    def synthesize_findings(
        self,
        payload: dict[str, Any],
    ) -> StructuredFindingSynthesis:
        system_prompt, user_prompt = build_finding_synthesis_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredFindingSynthesis,
            max_completion_tokens=_FINDING_SYNTHESIS_MAX_COMPLETION_TOKENS,
            json_text_parser=self._parse_finding_synthesis_json_response,
            task_type="finding_synthesis",
            prompt_version=FINDING_SYNTHESIS_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredFindingSynthesis):
            raise TypeError("unexpected Finding synthesis response type")
        return response

    def _parse_structured_response(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        max_completion_tokens: int | None = None,
        force_json_text: bool = False,
        include_schema_for_forced_json: bool = True,
        json_text_parser: Callable[..., tuple[BaseModel, str | None]] | None = None,
        parsed_validator: Callable[[BaseModel], BaseModel | None] | None = None,
        validation_error_observer: Callable[[Exception], None] | None = None,
        task_type: str | None = None,
        prompt_version: str | None = None,
        fail_on_output_saturation: bool = False,
    ) -> BaseModel:
        if task_type is not None and prompt_version is not None:
            record_llm_prompt_version(task_type, prompt_version)
        parse_json_text = json_text_parser or self._parse_json_text_response
        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
            include_schema=self.extraction_mode != _EXTRACTION_MODE_PROVIDER_PARSE,
        )
        self.last_trace = None
        started_at = perf_counter()
        trace_extraction_mode = self.extraction_mode
        try:
            use_provider_parse = (
                self.extraction_mode == _EXTRACTION_MODE_PROVIDER_PARSE
                and not force_json_text
            )
            if use_provider_parse:
                try:
                    parsed, raw_content = self._parse_provider_structured_response(
                        messages=messages,
                        response_model=response_model,
                        max_completion_tokens=max_completion_tokens,
                    )
                    if parsed_validator is not None:
                        validated = parsed_validator(parsed)
                        if validated is not None:
                            parsed = validated
                except LengthFinishReasonError as exc:
                    if fail_on_output_saturation:
                        raise PaperSkimOutputSaturatedError(
                            "PaperSkim provider output reached the completion-token "
                            "limit"
                        ) from exc
                    logger.warning(
                        "Objective provider output reached the completion-token limit; "
                        "retrying with json_text model=%s response_model=%s",
                        self.model,
                        response_model.__name__,
                    )
                    messages = self._build_messages(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        response_model=response_model,
                        include_schema=True,
                    )
                    parsed, raw_content = parse_json_text(
                        messages=messages,
                        response_model=response_model,
                        max_completion_tokens=max_completion_tokens,
                    )
                    trace_extraction_mode = (
                        f"{_EXTRACTION_MODE_PROVIDER_PARSE}->{_EXTRACTION_MODE_JSON_TEXT}"
                    )
                except Exception as exc:
                    if validation_error_observer is not None:
                        validation_error_observer(exc)
                    logger.warning(
                        "Objective provider parse failed; retrying with json_text "
                        "model=%s response_model=%s",
                        self.model,
                        response_model.__name__,
                        exc_info=True,
                    )
                    messages = self._build_messages(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        response_model=response_model,
                        include_schema=True,
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "The provider-parsed output failed validation. "
                                "Correct this validation error and return only the "
                                f"schema-valid JSON object: {str(exc)[:1000]}"
                            ),
                        }
                    )
                    parsed, raw_content = parse_json_text(
                        messages=messages,
                        response_model=response_model,
                        max_completion_tokens=max_completion_tokens,
                    )
                    trace_extraction_mode = (
                        f"{_EXTRACTION_MODE_PROVIDER_PARSE}->{_EXTRACTION_MODE_JSON_TEXT}"
                    )
            else:
                if self.extraction_mode == _EXTRACTION_MODE_PROVIDER_PARSE:
                    if include_schema_for_forced_json:
                        messages = self._build_messages(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            response_model=response_model,
                            include_schema=True,
                        )
                    trace_extraction_mode = _EXTRACTION_MODE_JSON_TEXT
                parsed, raw_content = parse_json_text(
                    messages=messages,
                    response_model=response_model,
                    max_completion_tokens=max_completion_tokens,
                )
        except Exception:
            elapsed_s = perf_counter() - started_at
            self.last_trace = self._build_trace(
                task_type=task_type,
                prompt_version=prompt_version,
                response_model=response_model,
                messages=messages,
                extraction_mode=trace_extraction_mode,
                trace_status="failed",
                elapsed_s=elapsed_s,
                error="structured extraction failed",
            )
            logger.exception(
                "Objective extraction failed mode=%s model=%s "
                "response_model=%s elapsed_s=%.3f validated=false",
                self.extraction_mode,
                self.model,
                response_model.__name__,
                elapsed_s,
            )
            raise
        elapsed_s = perf_counter() - started_at
        self.last_trace = self._build_trace(
            task_type=task_type,
            prompt_version=prompt_version,
            response_model=response_model,
            messages=messages,
            extraction_mode=trace_extraction_mode,
            trace_status="available",
            elapsed_s=elapsed_s,
            raw_content=raw_content,
            parsed_output=parsed,
        )
        logger.debug(
            "Objective extraction finished mode=%s model=%s "
            "response_model=%s elapsed_s=%.3f validated=true",
            self.extraction_mode,
            self.model,
            response_model.__name__,
            elapsed_s,
        )
        return parsed

    def _build_messages(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        include_schema: bool,
    ) -> list[dict[str, str]]:
        user_content = user_prompt
        if include_schema:
            schema = json.dumps(
                response_model.model_json_schema(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            user_content = (
                f"{user_prompt}\n\n"
                "Return exactly one JSON object that matches this schema. "
                "Do not include markdown fences or commentary.\n"
                f"JSON schema:\n{schema}"
            )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def _parse_json_text_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_completion_tokens: int | None,
        repair_instruction_builder: Callable[[str], str] | None = None,
        payload_normalizer: Callable[[Any], Any] | None = None,
        parsed_validator: Callable[[BaseModel], BaseModel | None] | None = None,
        validation_error_observer: Callable[[Exception], None] | None = None,
        fail_on_output_saturation: bool = False,
    ) -> tuple[BaseModel, str | None]:
        request_kwargs = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "response_format": {"type": "json_object"},
            **self._provider_request_options(),
        }
        if max_completion_tokens is not None:
            request_kwargs["max_completion_tokens"] = max_completion_tokens
        last_error: Exception | None = None
        for attempt in range(2):
            attempt_kwargs = dict(request_kwargs)
            attempt_messages = [*messages]
            attempt_kwargs["messages"] = attempt_messages
            if attempt:
                if isinstance(last_error, ValidationError):
                    repair_detail = "; ".join(
                        f"{'.'.join(str(part) for part in error['loc'])}: "
                        f"{error['msg']}"
                        for error in last_error.errors(
                            include_input=False,
                            include_url=False,
                        )
                    )
                else:
                    repair_detail = str(last_error or "invalid structured output")
                if repair_instruction_builder is not None:
                    retry_instruction = repair_instruction_builder(repair_detail[:1000])
                else:
                    retry_instruction = (
                        "Previous output was invalid. Return only the smallest valid "
                        "JSON object matching the schema. Do not explain, repeat the "
                        "prompt, or include markdown. Correct these validation errors: "
                        f"{repair_detail[:1000]}"
                    )
                attempt_messages.append(
                    {"role": "user", "content": retry_instruction}
                )
                logger.warning(
                    "Retrying structured JSON response model=%s response_model=%s",
                    self.model,
                    response_model.__name__,
                )
            try:
                try:
                    completion = self.client.chat.completions.create(**attempt_kwargs)
                except Exception as exc:
                    record_llm_completion(
                        getattr(exc, "completion", None),
                        requested_model=self.model,
                    )
                    raise
                record_llm_completion(completion, requested_model=self.model)
                choice = completion.choices[0] if completion.choices else None
                if (
                    fail_on_output_saturation
                    and getattr(choice, "finish_reason", None) == "length"
                ):
                    raise PaperSkimOutputSaturatedError(
                        "PaperSkim JSON output reached the completion-token limit"
                    )
                raw_content = coerce_message_content(
                    choice.message.content if choice is not None else None
                )
                if not raw_content:
                    raise RuntimeError(
                        "structured extraction returned empty response content"
                    )
                payload = load_json_payload(extract_json_object(raw_content))
                if payload_normalizer is not None:
                    payload = payload_normalizer(payload)
                try:
                    parsed = response_model.model_validate(payload)
                    if parsed_validator is not None:
                        validated = parsed_validator(parsed)
                        if validated is not None:
                            parsed = validated
                    return parsed, raw_content
                except ValidationError:
                    if isinstance(payload, dict):
                        extra_keys = set(payload) - set(response_model.model_fields)
                        if extra_keys - {"confidence"}:
                            raise
                        filtered_payload = {
                            key: value
                            for key, value in payload.items()
                            if key in response_model.model_fields
                        }
                        if filtered_payload != payload:
                            parsed = response_model.model_validate(filtered_payload)
                            if parsed_validator is not None:
                                validated = parsed_validator(parsed)
                                if validated is not None:
                                    parsed = validated
                            return parsed, raw_content
                    raise
            except (
                RuntimeError,
                ValueError,
                ValidationError,
                json.JSONDecodeError,
            ) as exc:
                if validation_error_observer is not None:
                    validation_error_observer(exc)
                last_error = exc
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("structured extraction failed after retry") from last_error

    def _parse_finding_synthesis_json_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_completion_tokens: int | None,
    ) -> tuple[BaseModel, str | None]:
        def build_repair_instruction(repair_detail: str) -> str:
            return (
                "Previous finding synthesis output failed validation: "
                f"{repair_detail}. Return at most one schema-valid finding or "
                '{"findings":[]}. Return only compact JSON.'
            )

        return self._parse_json_text_response(
            messages=messages,
            response_model=response_model,
            max_completion_tokens=max_completion_tokens,
            repair_instruction_builder=build_repair_instruction,
        )

    def _parse_objective_evidence_json_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_completion_tokens: int | None,
    ) -> tuple[BaseModel, str | None]:
        request_kwargs = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_evidence_extractions",
                    "schema": StructuredEvidenceExtractions.model_json_schema(),
                    "strict": True,
                },
            },
            **self._provider_request_options(),
        }
        if max_completion_tokens is not None:
            request_kwargs["max_completion_tokens"] = max_completion_tokens
        echoed_prompt_keys = {
            "OBJECTIVE",
            "OBJECTIVE VARIABLES",
            "OBJECTIVE OUTCOMES",
            "ROUTE HINT ONLY (DO NOT COPY AS EVIDENCE ROLE)",
            "SOURCE KIND",
            "SOURCE",
        }
        last_error: Exception | None = None
        last_invalid_extraction: dict[str, Any] | None = None
        max_attempts = 3
        for attempt in range(max_attempts):
            attempt_kwargs = dict(request_kwargs)
            attempt_messages = [*messages]
            attempt_kwargs["messages"] = attempt_messages
            if attempt:
                if isinstance(last_error, ValidationError):
                    repair_detail = "; ".join(
                        f"{'.'.join(str(part) for part in error['loc'])}: "
                        f"{error['msg']}"
                        for error in last_error.errors(
                            include_input=False,
                            include_url=False,
                        )
                    )
                else:
                    repair_detail = str(last_error or "invalid structured output")
                if "echoed input fields" in repair_detail:
                    retry_instruction = (
                        "Your previous response only echoed the input fields and did "
                        "not perform evidence extraction. Do not repeat OBJECTIVE, "
                        "OBJECTIVE VARIABLES, OBJECTIVE OUTCOMES, ROUTE HINT, SOURCE "
                        "KIND, or SOURCE. Re-read SOURCE and return exactly one compact "
                        "JSON object with the single top-level key `extractions`. Use "
                        "{\"extractions\":[]} only when SOURCE contains no comparison "
                        "that answers the objective."
                    )
                else:
                    retry_instruction = self._objective_evidence_repair_instruction(
                        repair_detail=repair_detail,
                        invalid_extraction=last_invalid_extraction,
                    )
                attempt_messages.append(
                    {"role": "user", "content": retry_instruction}
                )
                logger.warning(
                    "Retrying objective evidence JSON response model=%s "
                    "repair_attempt=%s max_repair_attempts=%s",
                    self.model,
                    attempt,
                    max_attempts - 1,
                )
            try:
                try:
                    completion = self.client.chat.completions.create(**attempt_kwargs)
                except Exception as exc:
                    record_llm_completion(
                        getattr(exc, "completion", None),
                        requested_model=self.model,
                    )
                    raise
                record_llm_completion(completion, requested_model=self.model)
                raw_content = coerce_message_content(
                    completion.choices[0].message.content if completion.choices else None
                )
                if not raw_content:
                    raise RuntimeError(
                        "structured extraction returned empty response content"
                    )
                payload = self._normalize_fixed_objective_evidence_conditions(
                    load_json_payload(extract_json_object(raw_content))
                )
                try:
                    return (
                        StructuredEvidenceExtractions.model_validate(payload),
                        raw_content,
                    )
                except ValidationError:
                    last_invalid_extraction = (
                        self._single_objective_evidence_extraction(payload)
                    )
                    if (
                        isinstance(payload, dict)
                        and isinstance(payload.get("extractions"), list)
                    ):
                        extra_keys = set(payload) - {"extractions"}
                        if extra_keys and extra_keys <= echoed_prompt_keys:
                            return (
                                StructuredEvidenceExtractions.model_validate(
                                    {"extractions": payload["extractions"]}
                                ),
                                raw_content,
                            )
                    if (
                        isinstance(payload, dict)
                        and "extractions" not in payload
                        and bool(payload)
                        and set(payload) <= echoed_prompt_keys
                    ):
                        raise ValueError(
                            "objective evidence response echoed input fields instead "
                            "of returning extractions"
                        )
                    if isinstance(payload, dict):
                        extra_keys = set(payload) - set(response_model.model_fields)
                        if extra_keys - {"confidence"}:
                            raise
                        filtered_payload = {
                            key: value
                            for key, value in payload.items()
                            if key in response_model.model_fields
                        }
                        if filtered_payload != payload:
                            return (
                                StructuredEvidenceExtractions.model_validate(
                                    filtered_payload
                                ),
                                raw_content,
                            )
                    raise
            except (
                RuntimeError,
                ValueError,
                ValidationError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    continue
                raise
        raise RuntimeError("structured extraction failed after repairs") from last_error

    @staticmethod
    def _normalize_fixed_objective_evidence_conditions(payload: Any) -> Any:
        def identical_nonempty_scalar(left: Any, right: Any) -> bool:
            if isinstance(left, bool) or isinstance(right, bool):
                return type(left) is type(right) and left == right
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left == right
            if isinstance(left, str) and isinstance(right, str):
                return bool(left.strip()) and left == right
            return False

        if not isinstance(payload, Mapping):
            return payload
        extractions = payload.get("extractions")
        if not isinstance(extractions, list):
            return payload

        changed = False
        normalized_extractions: list[Any] = []
        for extraction in extractions:
            if not isinstance(extraction, Mapping):
                normalized_extractions.append(extraction)
                continue
            variables = extraction.get("changed_variables")
            if not isinstance(variables, list):
                normalized_extractions.append(extraction)
                continue

            fixed_names: set[str] = set()
            changed_variables: list[Any] = []
            for variable in variables:
                if not isinstance(variable, Mapping):
                    changed_variables.append(variable)
                    continue
                baseline = variable.get("baseline_value")
                target = variable.get("target_value")
                variable_name = str(variable.get("name") or "").strip().casefold()
                if not variable_name or not identical_nonempty_scalar(
                    baseline,
                    target,
                ):
                    changed_variables.append(variable)
                    continue
                fixed_names.add(variable_name)
                changed = True

            if not fixed_names:
                normalized_extractions.append(extraction)
                continue
            normalized_extraction = dict(extraction)
            normalized_extraction["changed_variables"] = changed_variables
            remaining_variable_names = {
                str(variable.get("name") or "").strip().casefold()
                for variable in changed_variables
                if isinstance(variable, Mapping)
                and str(variable.get("name") or "").strip()
            }
            comparison = extraction.get("comparison")
            if isinstance(comparison, Mapping) and isinstance(
                comparison.get("axis_names"), list
            ):
                normalized_comparison = dict(comparison)
                normalized_comparison["axis_names"] = [
                    axis
                    for axis in comparison["axis_names"]
                    if str(axis).strip().casefold() not in fixed_names
                    or str(axis).strip().casefold() in remaining_variable_names
                ]
                normalized_extraction["comparison"] = normalized_comparison
            if (
                extraction.get("attribution_scope") == "joint_effect"
                and len(changed_variables) == 1
                and len(remaining_variable_names) == 1
            ):
                normalized_extraction["attribution_scope"] = "isolated_effect"
            normalized_extractions.append(normalized_extraction)

        if not changed:
            return payload
        normalized_payload = dict(payload)
        normalized_payload["extractions"] = normalized_extractions
        return normalized_payload

    @staticmethod
    def _single_objective_evidence_extraction(
        payload: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(payload, Mapping):
            return None
        extractions = payload.get("extractions")
        if not isinstance(extractions, list) or len(extractions) != 1:
            return None
        item = extractions[0]
        return dict(item) if isinstance(item, Mapping) else None

    @staticmethod
    def _objective_evidence_repair_instruction(
        *,
        repair_detail: str,
        invalid_extraction: Mapping[str, Any] | None,
    ) -> str:
        invalid_json = (
            json.dumps(
                dict(invalid_extraction),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if invalid_extraction is not None
            else "null"
        )
        return (
            "TASK\nRepair one invalid Evidence extraction against the original "
            "SOURCE. This is correction of the supplied candidate, not a new Source "
            "search or a new extraction task.\n"
            "REPAIR INPUT\n"
            f"- VALIDATION ERRORS: {repair_detail[:1000]}\n"
            f"- INVALID EXTRACTION: {invalid_json}\n"
            "DECISION PROCESS\n"
            "1. Check each named invalid field against SOURCE and keep every valid "
            "field unchanged.\n"
            "2. Correct a field only when its replacement is explicit in SOURCE. "
            "When SOURCE does not support a valid correction, remove the unsupported "
            "claim only if the remaining item still has honest scientific meaning; "
            "otherwise abstain with {\"extractions\":[]}.\n"
            "3. If `reported_result` is non-null, use `direct_result` or "
            "`contradictory_result` as `evidence_role`. If keeping a context role, "
            "set `reported_result` to null, `changed_variables` to [], `comparison` "
            "to null, and `attribution_scope` to `not_attributable`.\n"
            "4. `isolated_effect` and `joint_effect` require distinct baseline and "
            "target values for every changed variable. `comparison.axis_names` must "
            "exactly match the distinct `changed_variables` names. If SOURCE lacks "
            "complete endpoints, use `association_only` only for an explicit "
            "association; otherwise use `descriptive_only` or abstain.\n"
            "5. If `comparison.comparable` is false, use `not_attributable`; do not "
            "change it to true unless SOURCE explicitly supports a complete "
            "comparison. Remove each fixed parameter from `changed_variables` and "
            "`comparison.axis_names` when its endpoints are identical. A fixed "
            "control does not make the comparison incomparable. For a condition "
            "series, choose one complete Source-supported interval.\n"
            "HARD RULES\n"
            "- Correct only values supported by SOURCE; do not invent comparison "
            "endpoints or scientific context, and never copy from outside SOURCE.\n"
            "- A fixed parameter is fixed context, not a changed variable.\n"
            "- For a condition series, choose one complete source-supported interval "
            "and never merge separate intervals.\n"
            "- Preserve valid fields that do not require correction.\n"
            "BOUNDARY EXAMPLES\n"
            "- If candidate target is 160 W but SOURCE explicitly compares 100 W "
            "with 140 W, 140 W may replace 160 W; other grounded fields stay fixed.\n"
            "- If candidate unit is MPa but SOURCE gives no unit, set that unit to "
            "null only when the remaining result is still meaningful; never infer a "
            "unit from domain knowledge.\n"
            "- If SOURCE contains no complete comparison or attributable result, "
            "return {\"extractions\":[]}.\n"
            "OUTPUT SCHEMA\nReturn only "
            "{\"extractions\":[<one corrected extraction>]} or "
            "{\"extractions\":[]}."
        )

    def _parse_provider_structured_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_completion_tokens: int | None,
    ) -> tuple[BaseModel, str | None]:
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "response_format": response_model,
            **self._provider_request_options(),
        }
        if max_completion_tokens is not None:
            request_kwargs["max_completion_tokens"] = max_completion_tokens
        try:
            completion = self.client.beta.chat.completions.parse(**request_kwargs)
        except Exception as exc:
            record_llm_completion(
                getattr(exc, "completion", None),
                requested_model=self.model,
            )
            raise
        record_llm_completion(completion, requested_model=self.model)
        if not completion.choices:
            raise RuntimeError("structured extraction returned no completion choices")
        message = completion.choices[0].message
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            raw_content = coerce_message_content(getattr(message, "content", None))
            raise RuntimeError(
                "structured extraction returned no parsed response content"
                + (f": {raw_content[:500]}" if raw_content else "")
            )
        raw_content = coerce_message_content(getattr(message, "content", None))
        if isinstance(parsed, response_model):
            return parsed, raw_content
        return response_model.model_validate(parsed), raw_content

    def _provider_request_options(self) -> dict[str, Any]:
        if self.enable_thinking:
            return {}
        return {
            "extra_body": {
                "chat_template_kwargs": {
                    "enable_thinking": False,
                }
            }
        }

    def consume_last_trace(self) -> dict[str, Any] | None:
        trace = self.last_trace
        self.last_trace = None
        return dict(trace) if trace else None

    def _build_trace(
        self,
        *,
        task_type: str | None,
        prompt_version: str | None,
        response_model: type[BaseModel],
        messages: list[dict[str, str]],
        extraction_mode: str,
        trace_status: str,
        elapsed_s: float,
        raw_content: str | None = None,
        parsed_output: BaseModel | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "task_type": task_type or response_model.__name__,
            "prompt_version": prompt_version,
            "model": self.model,
            "extraction_mode": extraction_mode,
            "response_model": response_model.__name__,
            "trace_status": trace_status,
            "elapsed_s": round(elapsed_s, 6),
            "messages": [
                {
                    "role": trace_text(message.get("role")),
                    "content": trace_text(message.get("content"), _TRACE_TEXT_LIMIT),
                }
                for message in messages
            ],
            "raw_output": trace_text(raw_content, _TRACE_TEXT_LIMIT),
            "parsed_output": trace_json(
                parsed_output.model_dump(mode="json") if parsed_output else None
            ),
            "error": trace_text(error, 1000),
        }

    def _resolve_extraction_mode(self, extraction_mode: str | None) -> str:
        candidate = (
            extraction_mode
            or os.getenv("CORE_LLM_EXTRACTION_MODE", _DEFAULT_EXTRACTION_MODE)
        )
        normalized = str(candidate or "").strip().lower() or _DEFAULT_EXTRACTION_MODE
        if normalized in _SUPPORTED_EXTRACTION_MODES:
            return normalized
        logger.warning(
            "Invalid CORE_LLM_EXTRACTION_MODE=%s; falling back to %s",
            normalized,
            _DEFAULT_EXTRACTION_MODE,
        )
        return _DEFAULT_EXTRACTION_MODE


def build_default_objective_extractor() -> ObjectiveExtractor:
    return ObjectiveExtractor()
