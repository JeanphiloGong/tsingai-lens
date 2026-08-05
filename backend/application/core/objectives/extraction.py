from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from time import perf_counter
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from application.core.objectives.prompts import (
    FINDING_SYNTHESIS_PROMPT_VERSION,
    build_finding_synthesis_prompt,
    build_objective_evidence_prompt,
    build_objective_evidence_route_prompt,
    build_objective_paper_frame_prompt,
    build_paper_skim_prompt,
    build_research_axis_canonicalization_prompt,
    build_research_objective_discovery_prompt,
    build_research_objective_merge_prompt,
)
from application.core.objectives.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredEvidenceExtractions,
    StructuredEvidenceSelections,
    StructuredFindingSynthesis,
    StructuredObjectiveMergePlan,
    StructuredPaperContributionDraft,
    StructuredPaperSkim,
    StructuredResearchObjective,
    StructuredResearchObjectives,
)
from application.core.structured_extraction.json_support import (
    coerce_message_content,
    extract_json_object,
    load_json_payload,
    trace_json,
    trace_text,
)

logger = logging.getLogger(__name__)

_EXTRACTION_MODE_JSON_TEXT = "json_text"
_EXTRACTION_MODE_PROVIDER_PARSE = "provider_parse"
_DEFAULT_EXTRACTION_MODE = _EXTRACTION_MODE_PROVIDER_PARSE
_PAPER_SKIM_MAX_COMPLETION_TOKENS = 256
_RESEARCH_OBJECTIVE_DISCOVERY_MAX_COMPLETION_TOKENS = 2400
_OBJECTIVE_EVIDENCE_SELECTION_MAX_COMPLETION_TOKENS = 512
_OBJECTIVE_EVIDENCE_MAX_COMPLETION_TOKENS = 2048
_FINDING_SYNTHESIS_MAX_COMPLETION_TOKENS = 1024
_TRACE_TEXT_LIMIT = 8000
_SUPPORTED_EXTRACTION_MODES = {
    _EXTRACTION_MODE_JSON_TEXT,
    _EXTRACTION_MODE_PROVIDER_PARSE,
}


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
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperSkim,
            max_completion_tokens=_PAPER_SKIM_MAX_COMPLETION_TOKENS,
        )
        if not isinstance(response, StructuredPaperSkim):
            raise TypeError("unexpected paper skim response type")
        return response

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        system_prompt, user_prompt = build_research_objective_discovery_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredResearchObjectives,
            max_completion_tokens=(
                _RESEARCH_OBJECTIVE_DISCOVERY_MAX_COMPLETION_TOKENS
            ),
            force_json_text=True,
            json_text_parser=self._parse_research_objectives_json_response,
        )
        if not isinstance(response, StructuredResearchObjectives):
            raise TypeError("unexpected research objective response type")
        return response

    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        system_prompt, user_prompt = build_research_objective_merge_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredObjectiveMergePlan,
        )
        if not isinstance(response, StructuredObjectiveMergePlan):
            raise TypeError("unexpected research objective merge response type")
        return response

    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        system_prompt, user_prompt = build_research_axis_canonicalization_prompt(
            payload
        )
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredAxisCanonicalizationPlan,
        )
        if not isinstance(response, StructuredAxisCanonicalizationPlan):
            raise TypeError("unexpected research axis canonicalization response type")
        return response

    def assess_objective_paper(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperContributionDraft:
        system_prompt, user_prompt = build_objective_paper_frame_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperContributionDraft,
        )
        if not isinstance(response, StructuredPaperContributionDraft):
            raise TypeError("unexpected objective paper frame response type")
        return response

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
        )
        if not isinstance(response, StructuredEvidenceSelections):
            raise TypeError("unexpected objective evidence route response type")
        return response

    def extract_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredEvidenceExtractions:
        system_prompt, user_prompt = build_objective_evidence_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredEvidenceExtractions,
            max_completion_tokens=_OBJECTIVE_EVIDENCE_MAX_COMPLETION_TOKENS,
            force_json_text=True,
            include_schema_for_forced_json=False,
            json_text_parser=self._parse_objective_evidence_json_response,
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
        task_type: str | None = None,
        prompt_version: str | None = None,
    ) -> BaseModel:
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
                except Exception:
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
                completion = self.client.chat.completions.create(**attempt_kwargs)
                raw_content = coerce_message_content(
                    completion.choices[0].message.content if completion.choices else None
                )
                if not raw_content:
                    raise RuntimeError(
                        "structured extraction returned empty response content"
                    )
                payload = load_json_payload(extract_json_object(raw_content))
                try:
                    return response_model.model_validate(payload), raw_content
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
                            return (
                                response_model.model_validate(filtered_payload),
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

    def _parse_research_objectives_json_response(
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
            "response_format": {"type": "json_object"},
            **self._provider_request_options(),
        }
        if max_completion_tokens is not None:
            request_kwargs["max_completion_tokens"] = max_completion_tokens
        last_error: Exception | None = None
        last_raw_content: str | None = None
        preserved_objectives: list[StructuredResearchObjective] = []
        for attempt in range(2):
            attempt_kwargs = dict(request_kwargs)
            attempt_messages = [*messages]
            attempt_kwargs["messages"] = attempt_messages
            if attempt:
                if isinstance(last_error, ValidationError):
                    validation_errors = last_error.errors(
                        include_input=False,
                        include_url=False,
                    )
                    repair_detail = "; ".join(
                        f"{'.'.join(str(part) for part in error['loc'])}: "
                        f"{error['msg']}"
                        for error in validation_errors
                    )
                else:
                    validation_errors = []
                    repair_detail = str(last_error or "invalid structured output")
                retry_scope = (
                    "Return corrections only for invalid objectives; do not repeat "
                    "or rewrite objectives that were already valid. "
                    if preserved_objectives
                    else "Return one corrected `objectives` JSON array. "
                )
                if validation_errors and all(
                    "question roles" in str(error["msg"])
                    for error in validation_errors
                ):
                    retry_instruction = (
                        f"{retry_scope}"
                        "Correct every research-objective role error. Keep atomic, "
                        "non-duplicate axes and preserve their variable-to-outcome "
                        "direction. If an error names a field label missing from the "
                        "question and another label already occupies that variables or "
                        "outcomes role, delete the missing label from the list. If "
                        "deleting it would leave that role empty, put the full missing "
                        "label verbatim in the question. Then use the canonical form "
                        "'How does <full variables labels joined with and> affect <full "
                        "outcomes labels joined with and>?'. Keep material and process "
                        "scope only in material_scope or constraints. Drop any objective "
                        "that still cannot satisfy this form. Return only compact JSON. "
                        f"Errors: {repair_detail[:1000]}"
                    )
                else:
                    retry_instruction = (
                        "Previous output was invalid. "
                        f"{retry_scope}"
                        "Correct the JSON or schema errors exactly. Keep the top-level "
                        "object to the single `objectives` field, use only schema fields, "
                        "and return no more than six objectives. Return only compact JSON "
                        f"without commentary. Errors: {repair_detail[:1000]}"
                    )
                if last_raw_content:
                    attempt_messages.append(
                        {"role": "assistant", "content": last_raw_content}
                    )
                attempt_messages.append(
                    {"role": "user", "content": retry_instruction}
                )
                messages[:] = attempt_messages
                logger.warning(
                    "Retrying research objective discovery JSON response model=%s",
                    self.model,
                )
            try:
                completion = self.client.chat.completions.create(**attempt_kwargs)
                raw_content = coerce_message_content(
                    completion.choices[0].message.content if completion.choices else None
                )
                last_raw_content = raw_content
                if attempt and raw_content:
                    messages.append({"role": "assistant", "content": raw_content})
                if not raw_content:
                    raise RuntimeError(
                        "structured extraction returned empty response content"
                    )
                payload = load_json_payload(extract_json_object(raw_content))
                try:
                    parsed = StructuredResearchObjectives.model_validate(payload)
                    if attempt and preserved_objectives:
                        parsed = StructuredResearchObjectives(
                            objectives=self._deduplicate_objectives(
                                [*preserved_objectives, *parsed.objectives]
                            )
                        )
                    return parsed, raw_content
                except ValidationError as validation_error:
                    if (
                        isinstance(payload, dict)
                        and isinstance(payload.get("objectives"), list)
                    ):
                        objective_payloads = payload["objectives"]
                        if len(objective_payloads) > 6:
                            raise validation_error
                        validation_paths = {
                            ".".join(str(part) for part in error["loc"])
                            for candidate_error in (last_error, validation_error)
                            if isinstance(candidate_error, ValidationError)
                            for error in candidate_error.errors(
                                include_input=False,
                                include_url=False,
                            )
                        }
                        allowed_echo_keys = {
                            f"`{path}`" for path in validation_paths if path
                        }
                        if set(payload) - {"objectives"} - allowed_echo_keys:
                            raise validation_error
                        valid_objectives: list[StructuredResearchObjective] = []
                        invalid_objective_payloads: list[dict[str, Any]] = []
                        for objective_payload in objective_payloads:
                            try:
                                valid_objectives.append(
                                    StructuredResearchObjective.model_validate(
                                        objective_payload
                                    )
                                )
                            except ValidationError:
                                if isinstance(objective_payload, dict):
                                    invalid_objective_payloads.append(objective_payload)
                        if attempt == 0:
                            preserved_objectives = valid_objectives
                        else:
                            preserved_keys = {
                                objective.model_dump_json()
                                for objective in preserved_objectives
                            }
                            corrected_objectives = [
                                objective
                                for objective in valid_objectives
                                if objective.model_dump_json() not in preserved_keys
                            ]
                            corrected_objectives.extend(
                                objective
                                for objective_payload in invalid_objective_payloads
                                if (
                                    objective := self._repair_trailing_scope_objective(
                                        objective_payload
                                    )
                                )
                                is not None
                            )
                            if corrected_objectives:
                                return (
                                    StructuredResearchObjectives(
                                        objectives=self._deduplicate_objectives(
                                            [
                                                *preserved_objectives,
                                                *corrected_objectives,
                                            ]
                                        )
                                    ),
                                    raw_content,
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
                                StructuredResearchObjectives.model_validate(
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
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("structured extraction failed after retry") from last_error

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
            "response_format": {"type": "json_object"},
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
                attempt_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Previous evidence extraction output failed validation: "
                            f"{repair_detail[:1000]}. Return at most one schema-valid "
                            "extraction or {\"extractions\":[]}. Context evidence must "
                            "use reported_result null, no changed variables, no "
                            "comparison, and not_attributable. isolated_effect requires "
                            "exactly one changed variable and a comparable comparison; "
                            "joint_effect requires at least two. Return only compact JSON."
                        ),
                    }
                )
                logger.warning(
                    "Retrying objective evidence JSON response model=%s",
                    self.model,
                )
            try:
                completion = self.client.chat.completions.create(**attempt_kwargs)
                raw_content = coerce_message_content(
                    completion.choices[0].message.content if completion.choices else None
                )
                if not raw_content:
                    raise RuntimeError(
                        "structured extraction returned empty response content"
                    )
                payload = load_json_payload(extract_json_object(raw_content))
                try:
                    return (
                        StructuredEvidenceExtractions.model_validate(payload),
                        raw_content,
                    )
                except ValidationError:
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
                        return StructuredEvidenceExtractions(), raw_content
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
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("structured extraction failed after retry") from last_error

    @staticmethod
    def _deduplicate_objectives(
        objectives: list[StructuredResearchObjective],
    ) -> list[StructuredResearchObjective]:
        deduplicated: list[StructuredResearchObjective] = []
        seen: set[str] = set()
        for objective in objectives:
            key = objective.model_dump_json()
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(objective)
        return deduplicated

    @staticmethod
    def _repair_trailing_scope_objective(
        payload: dict[str, Any],
    ) -> StructuredResearchObjective | None:
        filtered = {
            key: value
            for key, value in payload.items()
            if key in StructuredResearchObjective.model_fields
        }
        variables = [
            str(value).strip()
            for value in filtered.get("variables", [])
            if str(value).strip()
        ]
        outcomes = [
            str(value).strip()
            for value in filtered.get("outcomes", [])
            if str(value).strip()
        ]
        question = str(filtered.get("question") or "").strip()
        if not question or not variables or not outcomes:
            return None

        probe = dict(filtered)
        probe["constraints"] = [
            *list(filtered.get("constraints") or []),
            *re.findall(r"[^\W_]+", question, flags=re.UNICODE),
        ]
        try:
            StructuredResearchObjective.model_validate(probe)
        except ValidationError:
            return None

        subject = " and ".join(variables)
        result = " and ".join(outcomes)
        auxiliary = "does" if len(variables) == 1 else "do"
        repaired = dict(filtered)
        repaired["question"] = f"How {auxiliary} {subject} affect {result}?"
        try:
            return StructuredResearchObjective.model_validate(repaired)
        except ValidationError:
            return None

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
        completion = self.client.beta.chat.completions.parse(**request_kwargs)
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
