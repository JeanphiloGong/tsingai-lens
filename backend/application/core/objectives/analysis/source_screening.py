from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from hashlib import sha1
from typing import Annotated, Any, Callable, Iterable, Literal, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from application.core.objectives import property_matching
from application.core.objectives.llm.structured_response import StructuredResponseClient
from domain.core import PaperSkim, ResearchObjective, normalize_objective_terms
from domain.source import SourceDocumentTree

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

_FRAME_TABLE_ROW_LIMIT = 3
_FRAME_SOURCE_UNIT_LIMIT = 8
_FRAME_SECTION_CHUNK_CHARS = 2_400
_FRAME_PRIOR_STUDY_LIMIT = 8
_FRAME_PRIOR_RELATIONSHIP_LIMIT = 12
_FRAME_TABLE_TEXT_CHARS = 800
_FRAME_TABLE_VALUE_CHARS = 240
_FRAME_SCREENING_NOTE_CHARS = 320
OBJECTIVE_PAPER_FRAME_PROMPT_TOKEN_LIMIT = 12_288
OBJECTIVE_PAPER_FRAME_PROMPT_VERSION = "objective_paper_frame.v3"

_FRAME_MAX_COMPLETION_TOKENS = 1024
_FRAME_RELEVANCE = {"high", "medium", "low", "irrelevant", "uncertain"}
_FRAME_PAPER_ROLES = {
    "primary_experiment",
    "supporting_method",
    "supporting_background",
    "review",
    "modeling_only",
    "irrelevant",
    "mixed",
    "uncertain",
}
_FRAME_SYSTEM_PROMPT = """
You are the source-relevance judge for one bounded neighborhood of a paper under one confirmed research objective.

Non-negotiable rules:
- This is bounded source-candidate classification, not whole-paper summarization or final fact extraction.
- Return exactly one JSON object and nothing else.
- Copy every supplied `source_unit_id` exactly once into either `relevant_source_unit_ids` or `excluded_source_unit_ids`.
- Never invent, rewrite, omit, or duplicate a source-unit id.
- Treat uncertain candidates as relevant so the downstream evidence router can inspect them.
- Do not emit measurement results, sample variants, evidence anchors, source text, or persistence ids.
- Do not infer material systems from filenames.
- Judge only the supplied neighborhood; omitted paper sources are outside this batch.
""".strip()


class _SourceScreeningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StructuredPaperFrameBatch(_SourceScreeningResponse):
    _source_accounting_origin: Literal["model", "repair"] = PrivateAttr(default="model")
    _source_accounting_errors: tuple[str, ...] = PrivateAttr(default=())

    relevance: Literal["high", "medium", "low", "irrelevant", "uncertain"] = "uncertain"
    paper_role: Literal[
        "primary_experiment",
        "supporting_method",
        "supporting_background",
        "review",
        "modeling_only",
        "irrelevant",
        "mixed",
        "uncertain",
    ] = "uncertain"
    screening_note: str | None = None
    material_match: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=8,
    )
    changed_variables: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=8,
    )
    measured_property_scope: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=8,
    )
    test_environment_scope: list[Annotated[str, Field(max_length=160)]] = Field(
        default_factory=list,
        max_length=8,
    )
    relevant_source_unit_ids: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list,
        max_length=8,
    )
    excluded_source_unit_ids: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list,
        max_length=8,
    )

    @field_validator(
        "material_match",
        "changed_variables",
        "measured_property_scope",
        "test_environment_scope",
        "relevant_source_unit_ids",
        "excluded_source_unit_ids",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return [] if value is None else value

    @model_validator(mode="after")
    def _validate_source_partition(self) -> "StructuredPaperFrameBatch":
        relevant = self.relevant_source_unit_ids
        excluded = self.excluded_source_unit_ids
        if len(relevant) != len(set(relevant)) or len(excluded) != len(set(excluded)):
            raise ValueError("paper frame source-unit ids must be unique")
        if set(relevant) & set(excluded):
            raise ValueError(
                "paper frame source-unit ids cannot be both relevant and excluded"
            )
        return self

    @property
    def source_accounting_origin(self) -> Literal["model", "repair"]:
        return self._source_accounting_origin

    @property
    def source_accounting_errors(self) -> tuple[str, ...]:
        return self._source_accounting_errors

    def record_source_accounting_repair(self, errors: Iterable[str]) -> None:
        self._source_accounting_origin = "repair"
        self._source_accounting_errors = tuple(
            str(error).strip() for error in errors if str(error).strip()
        )

    @field_validator("relevance", mode="before")
    @classmethod
    def _normalize_relevance(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_FRAME_RELEVANCE, default="uncertain")

    @field_validator("paper_role", mode="before")
    @classmethod
    def _normalize_paper_role(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_FRAME_PAPER_ROLES, default="uncertain")


def _normalize_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return lowered if lowered in allowed else default


def build_objective_paper_frame_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "TASK MODEL\n"
        "Perform bounded source-candidate classification for downstream objective-scoped evidence routing. "
        "This request contains one partial neighborhood, not the whole paper.\n\n"
        "INPUT SCHEMA\n"
        "- `collection_id`: backend scope identity; it is not scientific evidence and must not be returned.\n"
        "- `objective`: the confirmed comparison question and scientific axes.\n"
        "- `document`: backend metadata; the filename is not scientific evidence.\n"
        "- `document_profile`: backend document-type metadata; it is a routing hint, not authority over visible source text.\n"
        "- `paper_prior`: compact PaperSkim study context linked to the objective; it is a hint, not authority over visible source text.\n"
        "- `source_units`: current section chunks and table-row chunks. Each has a backend-owned `source_unit_id`, kind, stable source reference, and visible scientific content.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Read the objective variables, outcomes, material scope, constraints, and comparator.\n"
        "2. For each source unit independently, decide whether it may contain direct results, changed-variable context, material/sample/test context, mechanism context, or a useful table for that objective.\n"
        "3. Put useful or uncertain candidates in `relevant_source_unit_ids`; put only clearly unrelated, review-only, composition-only, or generic background candidates in `excluded_source_unit_ids`.\n"
        "4. Optionally write one short `screening_note` explaining why the current candidates should or should not be inspected. This is a local selection note, not a paper summary or scientific Evidence.\n"
        "5. Set batch `relevance` and `paper_role` from current evidence and `paper_prior`. Do not infer whole-paper irrelevance from facts absent in this partial neighborhood.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- A Methods section defining the objective variable but not reporting the outcome is relevant.\n"
        "- A Results table using a symbol or abbreviation for an objective axis is relevant when headers, caption, or cells establish that meaning.\n"
        "- A literature-comparison table without current-work results is excluded unless the objective explicitly asks for literature comparison.\n"
        "- Shared material alone does not make generic composition or background text relevant.\n\n"
        "SAME-SCHEMA EXAMPLES\n"
        "Relevant input: "
        '{"collection_id":"col-example","objective":{"variables":["laser power"],"outcomes":["relative density"]},"document":{"document_id":"paper-example"},"document_profile":{"doc_type":"experimental"},"paper_prior":{"doc_role":"experimental"},"source_units":[{"source_unit_id":"unit-methods","source_kind":"section","text":"Laser power was varied."},{"source_unit_id":"unit-composition","source_kind":"table","caption_text":"Nominal composition."}]}\n'
        "Relevant output: "
        '{"relevance":"medium","paper_role":"primary_experiment","screening_note":"The current batch defines the changed process variable.","material_match":[],"changed_variables":["laser power"],"measured_property_scope":[],"test_environment_scope":[],"relevant_source_unit_ids":["unit-methods"],"excluded_source_unit_ids":["unit-composition"]}\n\n'
        "Local exclusion input: "
        '{"collection_id":"col-example","objective":{"variables":["laser power"],"outcomes":["relative density"]},"document":{"document_id":"paper-example"},"source_units":[{"source_unit_id":"unit-composition","source_kind":"table","caption_text":"Nominal composition."}]}\n'
        "Local exclusion output: "
        '{"relevance":"low","paper_role":"uncertain","screening_note":"This batch contains nominal composition only.","material_match":[],"changed_variables":[],"measured_property_scope":[],"test_environment_scope":[],"relevant_source_unit_ids":[],"excluded_source_unit_ids":["unit-composition"]}\n\n'
        "OUTPUT CONTRACT\n"
        "Return only schema-valid structured data. Every input `source_unit_id` must appear exactly once across `relevant_source_unit_ids` and `excluded_source_unit_ids`. "
        "Keep `screening_note` to one concise sentence and return no source text, paper-level conclusion, or reasoning transcript."
    )
    return _FRAME_SYSTEM_PROMPT, user_prompt


class ObjectiveSourceScreener:
    """Classify one bounded Source batch for a confirmed Objective."""

    def __init__(self, response_client: StructuredResponseClient) -> None:
        self.response_client = response_client

    def screen_batch(self, payload: dict[str, Any]) -> StructuredPaperFrameBatch:
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

        def parse_json_text_with_contract(**kwargs: Any) -> tuple[BaseModel, str | None]:
            return self.response_client.complete_json(
                **kwargs,
                repair_instruction_builder=build_repair_instruction,
                parsed_validator=validate_source_accounting,
                validation_error_observer=record_source_accounting_error,
            )

        try:
            response = self.response_client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=StructuredPaperFrameBatch,
                max_completion_tokens=_FRAME_MAX_COMPLETION_TOKENS,
                json_text_parser=parse_json_text_with_contract,
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
        screening_note = _optional_text(response.screening_note)
        if screening_note and len(screening_note) > _FRAME_SCREENING_NOTE_CHARS:
            logger.warning(
                "Objective paper framing screening note truncated model=%s "
                "original_chars=%s retained_chars=%s",
                self.response_client.model,
                len(screening_note),
                _FRAME_SCREENING_NOTE_CHARS,
            )
            screening_note = screening_note[:_FRAME_SCREENING_NOTE_CHARS].rstrip()
        response.screening_note = screening_note
        if source_accounting_errors:
            response.record_source_accounting_repair(source_accounting_errors)
        return response

    def estimate_prompt_tokens(self, payload: dict[str, Any]) -> int:
        system_prompt, user_prompt = build_objective_paper_frame_prompt(payload)
        return self.response_client.estimate_prompt_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperFrameBatch,
        )


@dataclass(frozen=True)
class PaperFrameSourceDisposition:
    """Final framing decision and provenance for one transient Source unit."""

    source_unit_id: str
    source_kind: str
    source_ref: str
    disposition: str
    accounting_errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_unit_id or not self.source_kind or not self.source_ref:
            raise ValueError("paper frame Source disposition requires complete lineage")
        if self.disposition not in {
            "model_relevant",
            "model_excluded",
            "repaired_relevant",
            "repaired_excluded",
            "fallback_relevant",
        }:
            raise ValueError(
                f"unsupported paper frame Source disposition: {self.disposition}"
            )
        object.__setattr__(self, "accounting_errors", tuple(self.accounting_errors))
        if self.disposition.startswith(("repaired_", "fallback_")) and not (
            self.accounting_errors
        ):
            raise ValueError(
                "repaired or fallback paper frame disposition requires accounting errors"
            )

    @property
    def is_relevant(self) -> bool:
        return self.disposition not in {"model_excluded", "repaired_excluded"}

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperFrameSourceDisposition":
        return cls(
            source_unit_id=_text(payload.get("source_unit_id")),
            source_kind=_text(payload.get("source_kind")),
            source_ref=_text(payload.get("source_ref")),
            disposition=_text(payload.get("disposition")),
            accounting_errors=tuple(
                str(error).strip()
                for error in payload.get("accounting_errors") or ()
                if str(error).strip()
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "source_unit_id": self.source_unit_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "disposition": self.disposition,
            "accounting_errors": list(self.accounting_errors),
        }


@dataclass(frozen=True)
class PaperAnalysisFrame:
    """Transient paper traversal state; never persisted or exposed by the API."""

    objective_id: str
    document_id: str
    relevance: str
    paper_role: str
    screening_note: str | None
    material_match: tuple[str, ...]
    changed_variables: tuple[str, ...]
    measured_property_scope: tuple[str, ...]
    test_environment_scope: tuple[str, ...]
    relevant_sections: tuple[str, ...]
    relevant_text_source_refs: tuple[str, ...]
    relevant_tables: tuple[str, ...]
    excluded_tables: tuple[str, ...]
    source_dispositions: tuple[PaperFrameSourceDisposition, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperAnalysisFrame":
        return cls(
            objective_id=_text(payload.get("objective_id")),
            document_id=_text(payload.get("document_id")),
            relevance=_text(payload.get("relevance")) or "uncertain",
            paper_role=_text(payload.get("paper_role")) or "uncertain",
            screening_note=_optional_text(payload.get("screening_note")),
            material_match=normalize_objective_terms(payload.get("material_match")),
            changed_variables=normalize_objective_terms(
                payload.get("changed_variables")
            ),
            measured_property_scope=normalize_objective_terms(
                payload.get("measured_property_scope")
            ),
            test_environment_scope=normalize_objective_terms(
                payload.get("test_environment_scope")
            ),
            relevant_sections=normalize_objective_terms(
                payload.get("relevant_sections")
            ),
            relevant_text_source_refs=normalize_objective_terms(
                payload.get("relevant_text_source_refs")
            ),
            relevant_tables=normalize_objective_terms(payload.get("relevant_tables")),
            excluded_tables=normalize_objective_terms(payload.get("excluded_tables")),
            source_dispositions=tuple(
                PaperFrameSourceDisposition.from_mapping(item)
                for item in payload.get("source_dispositions") or ()
                if isinstance(item, Mapping)
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "relevance": self.relevance,
            "paper_role": self.paper_role,
            "screening_note": self.screening_note,
            "material_match": list(self.material_match),
            "changed_variables": list(self.changed_variables),
            "measured_property_scope": list(self.measured_property_scope),
            "test_environment_scope": list(self.test_environment_scope),
            "relevant_sections": list(self.relevant_sections),
            "relevant_text_source_refs": list(self.relevant_text_source_refs),
            "relevant_tables": list(self.relevant_tables),
            "excluded_tables": list(self.excluded_tables),
            "source_dispositions": [
                disposition.to_record() for disposition in self.source_dispositions
            ],
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    return _text(value) or None


def _notify_progress(
    progress_callback: ProgressCallback | None,
    **progress_detail: Any,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(progress_detail)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Research objective progress callback failed phase=%s",
            progress_detail.get("phase"),
        )


def screen_sources(
    *,
    collection_id: str,
    source_screener: ObjectiveSourceScreener,
    objectives: tuple[ResearchObjective, ...],
    paper_skims: tuple[PaperSkim, ...],
    documents: tuple[Any, ...],
    profiles_by_document_id: dict[str, Any],
    blocks_by_document_id: dict[str, list[Any]],
    tables_by_document_id: dict[str, list[Any]],
    document_trees_by_document_id: dict[str, SourceDocumentTree],
    progress_callback: ProgressCallback | None = None,
) -> tuple[PaperAnalysisFrame, ...]:
    skim_by_document_id = {
        skim.document_id: skim for skim in paper_skims if skim.document_id
    }
    frames: list[PaperAnalysisFrame] = []
    logger.info(
        "Research objective paper framing started collection_id=%s objective_count=%s document_count=%s",
        collection_id,
        len(objectives),
        len(documents),
    )
    objective_count = len(objectives)
    document_count = len(documents)
    total_frame_requests = objective_count * document_count
    completed_frame_requests = 0
    for objective_position, objective in enumerate(objectives, start=1):
        for document_position, document in enumerate(documents, start=1):
            completed_frame_requests += 1
            document_id = str(getattr(document, "document_id", "") or "")
            document_title = str(getattr(document, "title", None) or "").strip() or None
            source_filename = _resolve_source_filename(document)
            _notify_progress(
                progress_callback,
                phase="objective_paper_framing_started",
                current=completed_frame_requests,
                total=total_frame_requests,
                unit="frames",
                message="Checking each paper against each research objective.",
                active_document_id=document_id,
                active_document_title=document_title,
                active_source_filename=source_filename,
                active_objective_id=objective.objective_id,
            )
            tables = tables_by_document_id.get(document_id, [])
            logger.info(
                "Research objective paper framing document started collection_id=%s objective_id=%s objective_position=%s objective_count=%s document_id=%s document_position=%s document_count=%s completed_frame_requests=%s total_frame_requests=%s remaining_frame_requests=%s table_count=%s",
                collection_id,
                objective.objective_id,
                objective_position,
                objective_count,
                document_id,
                document_position,
                document_count,
                completed_frame_requests - 1,
                total_frame_requests,
                max(total_frame_requests - completed_frame_requests + 1, 0),
                len(tables),
            )
            if document_id in set(objective.excluded_document_ids):
                frames.append(
                    PaperAnalysisFrame.from_mapping(
                        {
                            "objective_id": objective.objective_id,
                            "document_id": document_id,
                            "relevance": "irrelevant",
                            "paper_role": "irrelevant",
                            "screening_note": (
                                "Paper was explicitly excluded from this research "
                                "objective."
                            ),
                        }
                    )
                )
                logger.info(
                    "Research objective paper framing skipped explicitly excluded document collection_id=%s objective_id=%s document_id=%s completed_frame_requests=%s total_frame_requests=%s remaining_frame_requests=%s",
                    collection_id,
                    objective.objective_id,
                    document_id,
                    completed_frame_requests,
                    total_frame_requests,
                    max(total_frame_requests - completed_frame_requests, 0),
                )
                continue
            payload = _build_objective_paper_frame_payload(
                collection_id=collection_id,
                objective=objective,
                paper_skim=skim_by_document_id.get(document_id),
                document=document,
                profile=profiles_by_document_id.get(document_id),
                blocks=blocks_by_document_id.get(document_id, []),
                tables=tables,
                document_tree=document_trees_by_document_id.get(document_id),
            )
            batches = _build_objective_paper_frame_batches(
                source_screener=source_screener,
                payload=payload,
            )
            batch_results: list[tuple[Mapping[str, Any], str, tuple[str, ...]]] = []
            fallback_batch_count = 0
            for batch_position, (batch_payload, prompt_tokens) in enumerate(
                batches,
                start=1,
            ):
                fallback_reason: str | None = None
                fallback_errors: tuple[str, ...] = ()
                if (
                    prompt_tokens is None
                    or prompt_tokens > OBJECTIVE_PAPER_FRAME_PROMPT_TOKEN_LIMIT
                ):
                    fallback_reason = "prompt_token_preflight_failed"
                    fallback_errors = (
                        "objective paper framing prompt token preflight failed; "
                        f"prompt_tokens={prompt_tokens}",
                    )
                else:
                    try:
                        parsed = source_screener.screen_batch(batch_payload)
                        batch_results.append(
                            (
                                parsed.model_dump(),
                                parsed.source_accounting_origin,
                                parsed.source_accounting_errors,
                            )
                        )
                        continue
                    except Exception as exc:  # noqa: BLE001
                        fallback_reason = "model_call_failed"
                        fallback_errors = (f"{type(exc).__name__}: {str(exc).strip()}",)
                        logger.warning(
                            "Research objective paper framing batch model failed; preserving batch sources collection_id=%s objective_id=%s document_id=%s batch_position=%s batch_count=%s prompt_tokens=%s",
                            collection_id,
                            objective.objective_id,
                            document_id,
                            batch_position,
                            len(batches),
                            prompt_tokens,
                            exc_info=True,
                        )

                fallback_batch_count += 1
                logger.warning(
                    "Research objective paper framing batch used conservative fallback collection_id=%s objective_id=%s document_id=%s batch_position=%s batch_count=%s source_unit_count=%s reason=%s prompt_tokens=%s",
                    collection_id,
                    objective.objective_id,
                    document_id,
                    batch_position,
                    len(batches),
                    len(batch_payload["source_units"]),
                    fallback_reason,
                    prompt_tokens,
                )
                batch_results.append(
                    (
                        _build_conservative_objective_paper_frame_batch(
                            payload=batch_payload,
                            paper_skim=skim_by_document_id.get(document_id),
                        ),
                        "fallback",
                        fallback_errors,
                    )
                )

            frame = _aggregate_objective_paper_frame_batches(
                objective_id=objective.objective_id,
                document_id=document_id,
                source_units=payload["source_units"],
                batch_results=batch_results,
                paper_skim=skim_by_document_id.get(document_id),
            )
            frames.append(frame)
            logger.info(
                "Research objective paper framing document finished collection_id=%s objective_id=%s objective_position=%s objective_count=%s document_id=%s document_position=%s document_count=%s relevance=%s paper_role=%s relevant_tables=%s excluded_tables=%s batch_count=%s fallback_batch_count=%s completed_frame_requests=%s total_frame_requests=%s remaining_frame_requests=%s",
                collection_id,
                objective.objective_id,
                objective_position,
                objective_count,
                document_id,
                document_position,
                document_count,
                frame.relevance,
                frame.paper_role,
                len(frame.relevant_tables),
                len(frame.excluded_tables),
                len(batches),
                fallback_batch_count,
                completed_frame_requests,
                total_frame_requests,
                max(total_frame_requests - completed_frame_requests, 0),
            )
    logger.info(
        "Research objective paper framing finished collection_id=%s frame_count=%s",
        collection_id,
        len(frames),
    )
    return tuple(frames)


def _route_prompt_objective_record(
    objective: ResearchObjective,
) -> dict[str, Any]:
    return {
        "objective_id": objective.objective_id,
        "question": objective.question,
        "material_scope": list(objective.material_scope),
        "variables": list(objective.variables),
        "outcomes": list(objective.outcomes),
        "mechanisms": list(objective.mechanisms),
        "constraints": list(objective.constraints),
        "requested_comparator": objective.requested_comparator,
    }


def _build_objective_paper_frame_payload(
    *,
    collection_id: str,
    objective: ResearchObjective,
    paper_skim: PaperSkim | None,
    document: Any,
    profile: Any,
    blocks: list[Any],
    tables: list[Any],
    document_tree: SourceDocumentTree | None,
) -> dict[str, Any]:
    section_units = _build_frame_section_source_units(
        blocks,
        document_tree=document_tree,
    )
    table_units = _build_frame_table_source_units(tables)
    source_units = [*section_units, *table_units]
    source_unit_ids = [str(item.get("source_unit_id") or "") for item in source_units]
    if any(not source_unit_id for source_unit_id in source_unit_ids) or len(
        source_unit_ids
    ) != len(set(source_unit_ids)):
        raise ValueError(
            "objective paper framing requires unique backend source-unit ids"
        )
    return {
        "collection_id": collection_id,
        "objective": _route_prompt_objective_record(objective),
        "paper_prior": _build_objective_paper_frame_prior(
            objective=objective,
            paper_skim=paper_skim,
        ),
        "document": {
            "document_id": getattr(document, "document_id", None),
            "title": getattr(document, "title", None),
            "source_filename": _resolve_source_filename(document),
        },
        "document_profile": profile.to_record() if profile else {},
        "source_units": source_units,
    }


def _build_objective_paper_frame_batches(
    *,
    source_screener: ObjectiveSourceScreener,
    payload: Mapping[str, Any],
) -> tuple[tuple[dict[str, Any], int | None], ...]:
    base_payload = {
        key: value for key, value in payload.items() if key != "source_units"
    }
    source_units = [
        dict(item)
        for item in payload.get("source_units") or ()
        if isinstance(item, Mapping)
    ]
    batches: list[tuple[dict[str, Any], int | None]] = []
    current_units: list[dict[str, Any]] = []
    current_tokens: int | None = None

    def batch_payload(units: list[dict[str, Any]]) -> dict[str, Any]:
        return {**base_payload, "source_units": list(units)}

    def estimate(candidate: dict[str, Any]) -> int | None:
        try:
            return source_screener.estimate_prompt_tokens(candidate)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Research objective paper framing token preflight failed",
                exc_info=True,
            )
            return None

    for source_unit in source_units:
        if len(current_units) >= _FRAME_SOURCE_UNIT_LIMIT:
            batches.append((batch_payload(current_units), current_tokens))
            current_units = []
            current_tokens = None

        candidate_units = [*current_units, source_unit]
        candidate_payload = batch_payload(candidate_units)
        candidate_tokens = estimate(candidate_payload)
        if (
            candidate_tokens is not None
            and candidate_tokens <= OBJECTIVE_PAPER_FRAME_PROMPT_TOKEN_LIMIT
        ):
            current_units = candidate_units
            current_tokens = candidate_tokens
            continue

        if current_units:
            batches.append((batch_payload(current_units), current_tokens))
            singleton_payload = batch_payload([source_unit])
            singleton_tokens = estimate(singleton_payload)
        else:
            singleton_payload = candidate_payload
            singleton_tokens = candidate_tokens

        if (
            singleton_tokens is not None
            and singleton_tokens <= OBJECTIVE_PAPER_FRAME_PROMPT_TOKEN_LIMIT
        ):
            current_units = [source_unit]
            current_tokens = singleton_tokens
        else:
            batches.append((singleton_payload, singleton_tokens))
            current_units = []
            current_tokens = None

    if current_units:
        batches.append((batch_payload(current_units), current_tokens))
    return tuple(batches)


def _build_conservative_objective_paper_frame_batch(
    *,
    payload: Mapping[str, Any],
    paper_skim: PaperSkim | None,
) -> dict[str, Any]:
    return {
        "relevance": "uncertain",
        "paper_role": _deterministic_frame_paper_role(paper_skim),
        "screening_note": None,
        "material_match": [],
        "changed_variables": [],
        "measured_property_scope": [],
        "test_environment_scope": [],
        "relevant_source_unit_ids": [
            str(item.get("source_unit_id") or "")
            for item in payload.get("source_units") or ()
            if isinstance(item, Mapping) and str(item.get("source_unit_id") or "")
        ],
        "excluded_source_unit_ids": [],
    }


def _aggregate_objective_paper_frame_batches(
    *,
    objective_id: str,
    document_id: str,
    source_units: Iterable[Mapping[str, Any]],
    batch_results: Iterable[tuple[Mapping[str, Any], str, tuple[str, ...]]],
    paper_skim: PaperSkim | None,
) -> PaperAnalysisFrame:
    units = tuple(source_units)
    results = tuple(batch_results)
    source_unit_ids = tuple(
        str(unit.get("source_unit_id") or "").strip() for unit in units
    )
    if not all(source_unit_ids) or len(source_unit_ids) != len(set(source_unit_ids)):
        raise ValueError(
            "objective paper frame aggregation requires unique Source-unit ids"
        )
    units_by_id = dict(zip(source_unit_ids, units, strict=True))
    dispositions_by_id: dict[str, PaperFrameSourceDisposition] = {}
    for record, decision_origin, accounting_errors in results:
        if decision_origin not in {"model", "repair", "fallback"}:
            raise ValueError(
                "objective paper frame aggregation received unsupported decision "
                f"origin: {decision_origin}"
            )
        relevant_batch_ids = tuple(
            str(value).strip()
            for value in record.get("relevant_source_unit_ids") or ()
            if str(value).strip()
        )
        excluded_batch_ids = tuple(
            str(value).strip()
            for value in record.get("excluded_source_unit_ids") or ()
            if str(value).strip()
        )
        returned_ids = (*relevant_batch_ids, *excluded_batch_ids)
        if len(returned_ids) != len(set(returned_ids)):
            raise ValueError(
                "objective paper frame aggregation received duplicate Source-unit "
                "dispositions"
            )
        normalized_errors = tuple(
            str(error).strip() for error in accounting_errors if str(error).strip()
        )
        for source_unit_id in returned_ids:
            unit = units_by_id.get(source_unit_id)
            if unit is None:
                raise ValueError(
                    "objective paper frame aggregation received unknown Source-unit "
                    f"id: {source_unit_id}"
                )
            if source_unit_id in dispositions_by_id:
                raise ValueError(
                    "objective paper frame aggregation received more than one "
                    f"disposition for Source-unit id: {source_unit_id}"
                )
            is_relevant = source_unit_id in relevant_batch_ids
            if decision_origin == "fallback":
                if not is_relevant:
                    raise ValueError(
                        "objective paper frame fallback cannot exclude a Source unit"
                    )
                disposition = "fallback_relevant"
            elif decision_origin == "repair":
                disposition = (
                    "repaired_relevant" if is_relevant else "repaired_excluded"
                )
            else:
                disposition = "model_relevant" if is_relevant else "model_excluded"
            dispositions_by_id[source_unit_id] = PaperFrameSourceDisposition(
                source_unit_id=source_unit_id,
                source_kind=str(unit.get("source_kind") or "").strip(),
                source_ref=str(unit.get("source_ref") or "").strip(),
                disposition=disposition,
                accounting_errors=normalized_errors,
            )

    missing_ids = [
        source_unit_id
        for source_unit_id in source_unit_ids
        if source_unit_id not in dispositions_by_id
    ]
    if missing_ids:
        raise ValueError(
            "objective paper frame aggregation is missing Source-unit "
            f"dispositions: {missing_ids}"
        )
    source_dispositions = tuple(
        dispositions_by_id[source_unit_id] for source_unit_id in source_unit_ids
    )
    relevant_ids = {
        disposition.source_unit_id
        for disposition in source_dispositions
        if disposition.is_relevant
    }
    excluded_ids = set(source_unit_ids) - relevant_ids
    all_sources_excluded = bool(units_by_id) and not relevant_ids

    relevance_rank = {
        "irrelevant": 0,
        "uncertain": 1,
        "low": 2,
        "medium": 3,
        "high": 4,
    }

    def record_relevance(record: Mapping[str, Any]) -> str:
        value = str(record.get("relevance") or "uncertain")
        return value if value in relevance_rank else "uncertain"

    ranked_results = sorted(
        enumerate(results),
        key=lambda item: (
            relevance_rank[record_relevance(item[1][0])],
            -item[0],
        ),
        reverse=True,
    )
    relevance = (
        "irrelevant"
        if all_sources_excluded
        else (
            record_relevance(ranked_results[0][1][0]) if ranked_results else "uncertain"
        )
    )
    if relevant_ids and relevance == "irrelevant":
        relevance = "uncertain"

    representative_results = ranked_results
    representative = representative_results[0][1][0] if representative_results else {}
    screening_note_record = next(
        (
            record
            for _position, (record, decision_origin, _errors) in representative_results
            if decision_origin != "fallback"
            and record_relevance(record) != "irrelevant"
            and str(record.get("screening_note") or "").strip()
        ),
        {},
    )

    def values(field: str) -> list[str]:
        return list(
            dict.fromkeys(
                text
                for record, _decision_origin, _errors in results
                for value in record.get(field) or ()
                if (text := str(value).strip())
            )
        )

    relevant_sections: list[str] = []
    relevant_text_source_refs: list[str] = []
    relevant_tables: list[str] = []
    excluded_tables: list[str] = []
    for unit in units:
        source_unit_id = str(unit.get("source_unit_id") or "")
        source_kind = str(unit.get("source_kind") or "")
        if source_kind == "section" and source_unit_id in relevant_ids:
            label = str(unit.get("section_label") or "").strip()
            if label and label not in relevant_sections:
                relevant_sections.append(label)
            source_ref = str(unit.get("source_ref") or "").strip()
            if source_ref and source_ref not in relevant_text_source_refs:
                relevant_text_source_refs.append(source_ref)
        if source_kind != "table":
            continue
        table_id = str(unit.get("source_ref") or "").strip()
        if not table_id:
            continue
        if source_unit_id in relevant_ids and table_id not in relevant_tables:
            relevant_tables.append(table_id)
        elif source_unit_id in excluded_ids and table_id not in excluded_tables:
            excluded_tables.append(table_id)
    excluded_tables = [
        table_id for table_id in excluded_tables if table_id not in set(relevant_tables)
    ]

    deterministic_paper_role = _deterministic_frame_paper_role(paper_skim)
    if deterministic_paper_role == "review":
        paper_role = "review"
    else:
        paper_role = (
            str(representative.get("paper_role") or "").strip()
            or deterministic_paper_role
        )
    if relevance != "irrelevant" and paper_role == "irrelevant":
        paper_role = deterministic_paper_role

    return PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective_id,
            "document_id": document_id,
            "relevance": relevance,
            "paper_role": paper_role,
            "screening_note": screening_note_record.get("screening_note"),
            "material_match": values("material_match"),
            "changed_variables": values("changed_variables"),
            "measured_property_scope": values("measured_property_scope"),
            "test_environment_scope": values("test_environment_scope"),
            "relevant_sections": relevant_sections,
            "relevant_text_source_refs": relevant_text_source_refs,
            "relevant_tables": relevant_tables,
            "excluded_tables": excluded_tables,
            "source_dispositions": [
                disposition.to_record() for disposition in source_dispositions
            ],
        }
    )


def _build_objective_paper_frame_prior(
    *,
    objective: ResearchObjective,
    paper_skim: PaperSkim | None,
) -> dict[str, Any]:
    if paper_skim is None:
        return {}

    lineage_relationship_ids = set(objective.source_relationship_ids)
    studies: list[dict[str, Any]] = []
    relationship_count = 0
    for study in paper_skim.studies:
        selected_relationships = []
        for relationship in study.relationships:
            if lineage_relationship_ids:
                selected = relationship.relationship_id in lineage_relationship_ids
            else:
                selected = _frame_relationship_supports_objective(
                    relationship=relationship,
                    objective=objective,
                )
            if not selected:
                continue
            selected_relationships.append(
                {
                    "varied_factors": list(relationship.varied_factors),
                    "outcome": relationship.outcome,
                }
            )
            relationship_count += 1
            if relationship_count >= _FRAME_PRIOR_RELATIONSHIP_LIMIT:
                break
        if selected_relationships:
            studies.append(
                {
                    "experiment_label": study.experiment_label,
                    "design_type": study.design_type,
                    "claim_scope": study.claim_scope,
                    "material_scope": list(study.material_scope),
                    "process_context": list(study.process_context),
                    "sample_context": list(study.sample_context),
                    "test_context": list(study.test_context),
                    "comparator": study.comparator,
                    "fixed_conditions": list(study.fixed_conditions),
                    "relationships": selected_relationships,
                }
            )
        if (
            len(studies) >= _FRAME_PRIOR_STUDY_LIMIT
            or relationship_count >= _FRAME_PRIOR_RELATIONSHIP_LIMIT
        ):
            break
    return {
        "doc_role": paper_skim.doc_role,
        "evidence_density": paper_skim.evidence_density,
        "studies": studies,
    }


def _frame_relationship_supports_objective(
    *,
    relationship: Any,
    objective: ResearchObjective,
) -> bool:
    variable_supported = any(
        property_matching.variable_matches_objective_scope(factor, variable)
        for factor in relationship.varied_factors
        for variable in objective.variables
    )
    outcome_supported = any(
        property_matching.axis_values_match(relationship.outcome, outcome)
        for outcome in objective.outcomes
    )
    return variable_supported and outcome_supported


def _frame_source_unit_id(
    *,
    source_kind: str,
    source_ref: str,
    chunk_position: int,
) -> str:
    identity = json.dumps(
        [source_kind, source_ref, chunk_position],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return f"frame:{source_kind}:{sha1(identity.encode('utf-8')).hexdigest()}"


def _build_frame_section_source_units(
    blocks: list[Any],
    *,
    document_tree: SourceDocumentTree | None,
) -> list[dict[str, Any]]:
    if document_tree is not None:
        units = _build_frame_tree_section_source_units(document_tree)
        if units:
            return units

    units: list[dict[str, Any]] = []
    for block in sorted(
        blocks,
        key=lambda item: int(getattr(item, "block_order", 0) or 0),
    ):
        text = str(getattr(block, "text", "") or "").strip()
        block_type = str(getattr(block, "block_type", "") or "")
        if not text or block_type not in {"heading", "paragraph", "list_item"}:
            continue
        source_ref = str(getattr(block, "block_id", "") or "").strip()
        if not source_ref:
            source_ref = f"block-order-{int(getattr(block, 'block_order', 0) or 0)}"
        section_label = str(getattr(block, "heading_path", "") or "").strip()
        if block_type == "heading":
            section_label = text
        section_label = section_label or "Unsectioned"
        for chunk_position, chunk in enumerate(
            _split_frame_section_text(text),
            start=1,
        ):
            units.append(
                {
                    "source_unit_id": _frame_source_unit_id(
                        source_kind="section",
                        source_ref=source_ref,
                        chunk_position=chunk_position,
                    ),
                    "source_kind": "section",
                    "source_ref": source_ref,
                    "section_label": section_label,
                    "text": chunk,
                }
            )
    return units


def _build_frame_tree_section_source_units(
    document_tree: SourceDocumentTree,
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for node in _document_tree_nodes_in_order(document_tree):
        is_section = node.node_type == "section"
        is_root_text = (
            node.parent_id == document_tree.root_node_id
            and node.node_type in {"paragraph", "list_item"}
        )
        if not (is_section or is_root_text) or _tree_node_in_reference_branch(
            document_tree, node
        ):
            continue
        text = (
            _section_text_from_tree_node(document_tree, node)
            if is_section
            else str(node.text or "").strip()
        )
        if not text and is_section and node.title:
            text = str(node.title)
        if not text:
            continue
        for chunk_position, chunk in enumerate(
            _split_frame_section_text(text),
            start=1,
        ):
            units.append(
                {
                    "source_unit_id": _frame_source_unit_id(
                        source_kind="section",
                        source_ref=node.node_id,
                        chunk_position=chunk_position,
                    ),
                    "source_kind": "section",
                    "source_ref": node.node_id,
                    "section_label": (
                        _tree_section_label(node) if is_section else "Unsectioned"
                    ),
                    "text": chunk,
                }
            )
    return units


def _split_frame_section_text(text: str) -> tuple[str, ...]:
    remaining = str(text or "").strip()
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= _FRAME_SECTION_CHUNK_CHARS:
            chunks.append(remaining)
            break
        split_at = max(
            remaining.rfind("\n\n", 0, _FRAME_SECTION_CHUNK_CHARS + 1),
            remaining.rfind(". ", 0, _FRAME_SECTION_CHUNK_CHARS + 1),
            remaining.rfind(" ", 0, _FRAME_SECTION_CHUNK_CHARS + 1),
        )
        if split_at < _FRAME_SECTION_CHUNK_CHARS // 2:
            split_at = _FRAME_SECTION_CHUNK_CHARS
        elif remaining[split_at : split_at + 2] == ". ":
            split_at += 1
        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()
    return tuple(chunks)


def _build_frame_table_source_units(
    tables: list[Any],
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for table in sorted(
        tables,
        key=lambda item: int(getattr(item, "table_order", 0) or 0),
    ):
        table_id = str(getattr(table, "table_id", "") or "").strip()
        if not table_id:
            continue
        matrix = tuple(getattr(table, "table_matrix", ()) or ())
        serialized_rows = [
            [
                str(cell)[:_FRAME_TABLE_VALUE_CHARS]
                for cell in (row if isinstance(row, (list, tuple)) else (row,))
            ]
            for row in matrix
        ]
        row_chunks = [
            serialized_rows[position : position + _FRAME_TABLE_ROW_LIMIT]
            for position in range(0, len(serialized_rows), _FRAME_TABLE_ROW_LIMIT)
        ] or [[]]
        for chunk_position, rows in enumerate(row_chunks, start=1):
            row_start = (chunk_position - 1) * _FRAME_TABLE_ROW_LIMIT
            units.append(
                {
                    "source_unit_id": _frame_source_unit_id(
                        source_kind="table",
                        source_ref=table_id,
                        chunk_position=chunk_position,
                    ),
                    "source_kind": "table",
                    "source_ref": table_id,
                    "caption_text": str(getattr(table, "caption_text", None) or "")[
                        :_FRAME_TABLE_TEXT_CHARS
                    ],
                    "heading_path": str(getattr(table, "heading_path", None) or "")[
                        :_FRAME_TABLE_TEXT_CHARS
                    ],
                    "column_headers": [
                        str(value)[:_FRAME_TABLE_VALUE_CHARS]
                        for value in getattr(table, "column_headers", ()) or ()
                    ],
                    "row_count": int(getattr(table, "row_count", 0) or 0),
                    "col_count": int(getattr(table, "col_count", 0) or 0),
                    "row_start": row_start,
                    "row_end": row_start + len(rows),
                    "sample_rows": rows,
                }
            )
    return units


def _section_text_from_tree_node(
    document_tree: SourceDocumentTree,
    node: Any,
) -> str:
    texts: list[str] = []
    for child_id in node.child_ids:
        child = document_tree.nodes[child_id]
        if child.node_type in {"section", "references_section"}:
            continue
        if child.node_type not in {"paragraph", "list_item"}:
            continue
        text = str(child.text or "").strip()
        if text:
            texts.append(text)
    return "\n\n".join(texts).strip()


def _tree_section_label(node: Any) -> str:
    if getattr(node, "heading_path", ()):
        return " > ".join(str(part) for part in node.heading_path if str(part))
    title = str(getattr(node, "title", "") or "").strip()
    return title or "Unsectioned"


def _deterministic_frame_paper_role(paper_skim: PaperSkim | None) -> str:
    doc_role = str(getattr(paper_skim, "doc_role", "") or "")
    if doc_role == "experimental":
        return "primary_experiment"
    if doc_role == "review":
        return "review"
    return "uncertain"


def _document_tree_nodes_in_order(
    document_tree: SourceDocumentTree,
) -> list[Any]:
    return sorted(
        document_tree.nodes.values(),
        key=lambda node: (int(getattr(node, "order", 0) or 0), node.node_id),
    )


def _tree_node_in_reference_branch(
    document_tree: SourceDocumentTree,
    node: Any,
) -> bool:
    current = node
    while current is not None:
        if current.node_type in {"references_section", "reference_entry"}:
            return True
        if getattr(current, "semantic_role", None) == "references":
            return True
        parent_id = getattr(current, "parent_id", None)
        current = document_tree.nodes.get(parent_id) if parent_id else None
    return False


def _resolve_source_filename(document: Any) -> str | None:
    metadata = getattr(document, "metadata", {}) or {}
    for key in ("source_filename", "original_filename", "stored_filename"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return None
