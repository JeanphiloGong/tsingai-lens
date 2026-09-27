"""Bounded Source-grounded extraction of PaperExperiment Drafts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from time import monotonic
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from application.core.objectives.analysis.paper_experiment_contract import (
    DraftReadiness,
    PaperExperimentModelOutput,
    ReconciledPaperExperimentOutput,
    SOURCE_REPORTED_IDENTIFIER_FIELDS,
    assess_draft_readiness,
    prepare_model_output,
)
from application.core.objectives.llm.structured_response import (
    StructuredResponseClient,
)
from domain.core.research_objective import ResearchObjective


class PaperExperimentDraftEnvelope(BaseModel):
    """The only provider envelope; nested objects use response-local keys.

    The nested graph intentionally remains open because papers report domain
    specific attributes.  The application contract performs the strict
    cross-reference and provenance checks after parsing.  The field
    descriptions below are part of the provider JSON schema and keep that
    distinction visible to the model without forcing a materials-science
    vocabulary into the transport type.
    """

    model_config = ConfigDict(extra="forbid")

    experiments: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Zero or more bounded experiment Draft objects. Each object uses "
            "response-local keys where useful and may contain source-local "
            "reported observations. Local "
            "variant_key/test_key values are optional when the paper only gives "
            "a broad or unresolved scope; use supplied Sxxx source labels."
        ),
        # Pydantic emits only ``{"type": "object"}`` for ``dict[str, Any]``
        # on some supported versions.  Make the provider contract explicit:
        # scientific Draft fields are intentionally open here and are checked
        # by the application authoring contract after parsing.
        json_schema_extra={
            "items": {
                "type": "object",
                "additionalProperties": True,
            }
        },
    )
    source_labels: list[str] = Field(
        default_factory=list,
        description=(
            "The supplied Sxxx labels used anywhere in this response; never "
            "invent source IDs or SourceReference objects."
        ),
    )
    unresolved_issues: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Document-level boundary, conflict, or missing-context records. "
            "Use target_ref and description; keep unknowns instead of guessing."
        ),
    )


PAPER_EXPERIMENT_DRAFT_PROMPT_VERSION = "paper_experiment_draft.v2"


_DRAFT_SCHEMA_HINT: dict[str, Any] = {
    "experiments": [
        {
            "series_key": "local-series-key",
            "scope_kind": "parent",
            "member_hints": {
                "variant_keys": [],
                "test_keys": [],
                "measurement_keys": [],
            },
            "experimental_variants": [
                {
                    "variant_key": None,
                    "variant_label": "paper label",
                    "subject_attributes": [],
                    "intervention_attributes": [],
                    "state": [],
                    "population_scope": {
                        "reported_identifiers": {
                            "sample_id": "paper-owned-id",
                            "domain_specific_id": "paper-owned-id",
                        }
                    },
                    "source_labels": ["S001"],
                    "binding_source_labels": ["S001"],
                }
            ],
            "test_conditions": [
                {
                    "test_key": None,
                    "test_type": "paper-reported method",
                    "parameters": [],
                    "source_labels": ["S001"],
                    "binding_source_labels": ["S001"],
                }
            ],
            "measurements": [
                {
                    "measurement_key": "local-measurement-key",
                    "variant_key": None,
                    "test_key": None,
                    "reported_sample_label": "verbatim row/paragraph wording",
                    "reported_test_label": "verbatim header/method wording",
                    "candidate_variant_keys": [],
                    "candidate_test_keys": [],
                    "outcome": "requested outcome",
                    "value": None,
                    "unit": None,
                    "measurement_scope": {
                        "reported_identifiers": {
                            "measurement_native_id": "paper-owned-id"
                        }
                    },
                    "source_labels": ["S002"],
                    "variant_binding_source_labels": ["S002"],
                    "test_binding_source_labels": ["S001"],
                }
            ],
            "comparisons": [],
            "reported_interpretations": [],
            "unresolved_issues": [],
        }
    ],
    "source_labels": ["S001", "S002"],
    "unresolved_issues": [],
}


@dataclass(frozen=True)
class PaperExperimentSourceBundle:
    document_id: str
    source_fingerprint: str
    prompt_sources: tuple[Mapping[str, Any], ...]
    source_catalog: Mapping[str, Mapping[str, Any]]
    omitted_source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.document_id.strip() or not self.source_fingerprint.strip():
            raise ValueError("source bundle requires document and fingerprint")
        if set(self.source_catalog) != {
            str(item.get("source_label") or "").strip()
            for item in self.prompt_sources
        }:
            raise ValueError("prompt Source labels must match the service catalog")


@dataclass(frozen=True)
class ExtractionAttempt:
    strategy: str
    status: Literal["passed", "insufficient", "rejected", "technical_failure"]
    reason: str | None = None
    call_index: int = 0


@dataclass(frozen=True)
class ExtractionBudget:
    max_calls: int = 3
    max_completion_tokens_per_call: int = 8_000
    max_total_completion_tokens: int = 24_000
    max_seconds: float = 240.0

    def __post_init__(self) -> None:
        if (
            self.max_calls < 1
            or self.max_completion_tokens_per_call < 1
            or self.max_total_completion_tokens < 1
            or self.max_seconds <= 0
        ):
            raise ValueError("extraction budget values must be positive")


@dataclass(frozen=True)
class PaperExperimentExtractionResult:
    output: ReconciledPaperExperimentOutput | None
    readiness: DraftReadiness | None
    attempts: tuple[ExtractionAttempt, ...]
    status: Literal[
        "ready",
        "partial_archive",
        "abstained",
        "technical_failure",
    ]
    omitted_source_refs: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


class ProviderTechnicalError(RuntimeError):
    """Transport, timeout, quota, or provider availability failure."""


def _in_scoped_reported_identifiers(ancestors: tuple[str, ...]) -> bool:
    """Keep paper-native IDs only in an explicit scope identifier map."""

    for index, ancestor in enumerate(ancestors):
        if ancestor != "reported_identifiers":
            continue
        if any(
            parent in {"population_scope", "measurement_scope"}
            for parent in ancestors[:index]
        ):
            return True
    return False


def _without_service_ids(
    value: Any,
    *,
    ancestors: tuple[str, ...] = (),
) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            normalized_key = str(key).casefold()
            in_reported_identifier_map = _in_scoped_reported_identifiers(ancestors)
            is_service_identity = (
                normalized_key
                in {
                    "id",
                    "ids",
                    "document_id",
                    "source_fingerprint",
                    "source_ref",
                }
                or (
                    (normalized_key.endswith("_id") or normalized_key.endswith("_ids"))
                    and normalized_key not in SOURCE_REPORTED_IDENTIFIER_FIELDS
                    and not in_reported_identifier_map
                )
            )
            if not is_service_identity:
                sanitized[str(key)] = _without_service_ids(
                    nested,
                    ancestors=(*ancestors, normalized_key),
                )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [
            _without_service_ids(item, ancestors=ancestors)
            for item in value
        ]
    return value


def build_source_bundle(
    *,
    document_id: str,
    source_fingerprint: str,
    source_payloads: Sequence[Mapping[str, Any]],
) -> PaperExperimentSourceBundle:
    """Assign request-local labels while keeping real Source IDs server-side."""

    prompt_sources: list[Mapping[str, Any]] = []
    catalog: dict[str, Mapping[str, Any]] = {}
    seen_source_refs: set[str] = set()
    for index, raw in enumerate(source_payloads, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"source payload {index} must be an object")
        source_ref = str(raw.get("source_ref") or "").strip()
        source_kind = str(raw.get("source_kind") or "block").strip()
        if not source_ref:
            raise ValueError(f"source payload {index} has no source_ref")
        if source_ref in seen_source_refs:
            continue
        seen_source_refs.add(source_ref)
        quote = str(
            raw.get("quote")
            or raw.get("text")
            or raw.get("table_markdown")
            or raw.get("caption_text")
            or raw.get("figure_text")
            or ""
        ).strip()
        if not quote:
            raise ValueError(f"source payload {source_ref} has no reviewable quote")
        label = f"S{len(prompt_sources) + 1:03d}"
        catalog[label] = {
            "document_id": document_id,
            "source_fingerprint": source_fingerprint,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "quote": quote,
        }
        prompt = _without_service_ids(dict(raw))
        prompt["source_label"] = label
        prompt_sources.append(prompt)
    return PaperExperimentSourceBundle(
        document_id=document_id,
        source_fingerprint=source_fingerprint,
        prompt_sources=tuple(prompt_sources),
        source_catalog=catalog,
    )


def build_bundle_from_routes(
    *,
    document_id: str,
    source_fingerprint: str,
    routes: Sequence[Any],
    blocks: list[Any],
    tables: list[Any],
    figures: list[Any],
    document_tree: Any | None,
    table_cells: list[Any],
    max_sources: int = 24,
    max_chars: int = 48_000,
) -> PaperExperimentSourceBundle:
    """Render already-routed Sources once and expose any budget omissions."""

    if max_sources < 1 or max_chars < 1:
        raise ValueError("Source bundle budgets must be positive")
    from application.core.objectives.analysis.source_extraction import (
        build_route_source_payload,
    )

    candidates: list[Mapping[str, Any]] = []
    for route in routes:
        if str(getattr(route, "document_id", "") or "") != document_id:
            continue
        # Routing may retain contextual or excluded candidates for audit, but
        # only extractable routes are part of the bounded Draft input.  Keep
        # this boundary identical to the routed Source accounting in the
        # Objective service.
        if not bool(getattr(route, "extractable", False)):
            continue
        payload = build_route_source_payload(
            route=route,
            blocks=blocks,
            tables=tables,
            figures=figures,
            document_tree=document_tree,
            table_cells=table_cells,
        )
        if payload:
            candidates.append(payload)

    selected: list[Mapping[str, Any]] = []
    omitted: list[str] = []
    used_chars = 0
    for payload in candidates:
        source_ref = str(payload.get("source_ref") or "").strip()
        rendered = json.dumps(payload, ensure_ascii=False, default=str)
        if len(selected) >= max_sources or used_chars + len(rendered) > max_chars:
            if source_ref:
                omitted.append(source_ref)
            continue
        selected.append(payload)
        used_chars += len(rendered)

    bundle = build_source_bundle(
        document_id=document_id,
        source_fingerprint=source_fingerprint,
        source_payloads=selected,
    )
    return PaperExperimentSourceBundle(
        document_id=bundle.document_id,
        source_fingerprint=bundle.source_fingerprint,
        prompt_sources=bundle.prompt_sources,
        source_catalog=bundle.source_catalog,
        omitted_source_refs=tuple(dict.fromkeys(omitted)),
    )


def _prompt(
    *,
    objective: ResearchObjective,
    bundle: PaperExperimentSourceBundle,
    strategy: str,
    previous: Mapping[str, Any] | None = None,
    missing: Sequence[str] = (),
) -> tuple[str, str]:
    system_prompt = """
TASK MODEL
You are the source-grounded content extractor for one confirmed research
Objective. Recover what this paper explicitly reports about bounded experiment
series so a deterministic service can validate and archive it. This is not
paper summarization, causal interpretation, identity allocation, or Finding
publication.

INPUT SCHEMA
- objective: the question, requested variables, outcomes, scope, and constraints.
- sources: a bounded list of source objects. `source_label` is the only label
  that may be returned; the other source fields are evidence to inspect.
- previous_candidate and missing_context: an earlier Draft and the specific
  gaps to repair. They may be null/empty on the first attempt.

DECISION PROCESS
1. Read table headers, row labels, continuation pages, captions, footnotes, and
   applicable Methods together. Recover every source-supported reported value;
   if none are supported, return `experiments: []`.
2. Read tabular results as part of the complete supplied Source block. Preserve
   each source-supported reported result and its stated sample/test scope; do
   not create a global sample or test object merely because a row or column has
   a label.
3. Group facts only when the Sources support one bounded experimental series;
   keep independent populations, assignments, or designs separate. Boundary
   proposals are diagnostic hints, not an authoritative member list.
4. Attach each value and each binding edge to the supplied Source labels. A
   `variant_key` or `test_key` may be null when the row/sample or protocol is
   broad, category-level, or unresolved. Keep the verbatim
   `reported_sample_label`/`reported_test_label`, candidate local keys, missing
   dimensions, and an unresolved issue instead of guessing an exact edge.
5. Preserve repeated or conflicting reports as separate observations. Do not
   average, overwrite, infer significance, or turn a multi-factor comparison
   into a single-factor claim.
6. Return the smallest complete JSON envelope described by the output schema.

HARD RULES
- Never emit formal Lens IDs, request ownership, revision numbers, database
  Source references, binding/status fields, final direction/basis, or causal
  judgments. The service supplies those after validation.
- Use only supplied `Sxxx` labels. Paper-owned identifiers, including
  domain-specific names such as `sample_id`, `stimulus_id`, or `condition_id`,
  may appear only inside `population_scope.reported_identifiers` or
  `measurement_scope.reported_identifiers`. Never use a Lens-owned identity
  such as `experiment_id` or `variant_id` for that purpose.
- A zero-experiment result is valid when the supplied Sources do not support a
  recoverable experiment. Do not create a placeholder experiment.

BOUNDARY EXAMPLES
- A table reports `NP=72` and `P150=82`, and Methods identifies one tensile
  protocol: emit the two reported measurements, retaining their source block
  and stated sample/test labels. Add local variants and exact keys only when
  the paper explicitly supports them; otherwise retain the broad scope.
- A table says only `condition A` and the Methods do not identify its treatment:
  retain the row/value, set its candidate variant/test edge to null or a
  candidate list, add an unresolved issue, and do not claim an exact binding.
- A paper reports one tensile result in a table and a different value in the
  Results paragraph for the same reported scope: retain both observations with
  their separate source labels and mark the conflict for service audit.
- A boundary call proposes one experiment per table or outcome: keep those as
  diagnostic proposals. The service defaults to one parent and accepts a
  physical split only with positive evidence of a different population,
  assignment, or design.
- A review paragraph with no source-supported experiment rows: return empty
  `experiments` and explain the document-level unresolved issue if useful.

OUTPUT SCHEMA
Return exactly one JSON object with `experiments`, `source_labels`, and
`unresolved_issues`. The nested Draft shape is shown in the user payload;
unknown scientific attributes are allowed. Source labels are required for a
reported fact; local variant/test references are optional when the source does
not prove an exact binding. Preserve large or multi-column table results in
their complete Source block; do not introduce a separate table-row domain
object.
""".strip()
    user_prompt = json.dumps(
        {
            "strategy": strategy,
            "objective": {
                "question": objective.question,
                "subject_scope": list(objective.material_scope),
                "variables": list(objective.variables),
                "outcomes": list(objective.outcomes),
                "constraints": list(objective.constraints),
            },
            "sources": list(bundle.prompt_sources),
            "previous_candidate": previous,
            "missing_context": list(missing),
            "draft_schema": _DRAFT_SCHEMA_HINT,
            "draft_schema_note": (
                "The draft_schema values are illustrative placeholders, not facts "
                "to copy. Use only values supported by the supplied Sources."
            ),
            "allowed_scope_kinds": [
                "parent",
                "matrix",
                "selected_stratum",
                "follow_up",
                "physical_split",
                "unknown",
            ],
            "required_top_level_keys": [
                "experiments",
                "source_labels",
                "unresolved_issues",
            ],
        },
        ensure_ascii=False,
    )
    return system_prompt, user_prompt


class PaperExperimentExtractor:
    """Run a bounded Draft extraction without turning failure into science."""

    def __init__(
        self,
        response_client: StructuredResponseClient,
        *,
        strategy_order: Sequence[str] = (
            "focused-single-pass",
            "focused-fact-first",
            "focused-context-repair",
        ),
        budget: ExtractionBudget = ExtractionBudget(),
    ) -> None:
        strategies = tuple(str(item).strip() for item in strategy_order if str(item).strip())
        if not strategies:
            raise ValueError("extractor requires at least one strategy")
        self.response_client = response_client
        self.strategy_order = strategies
        self.budget = budget

    def extract(
        self,
        *,
        objective: ResearchObjective,
        bundle: PaperExperimentSourceBundle,
    ) -> PaperExperimentExtractionResult:
        # A paper with no readable routed Source is a scientific abstention,
        # not a provider failure.  In particular, do not spend a model call
        # trying to infer an experiment from an empty context.
        if not bundle.prompt_sources:
            return PaperExperimentExtractionResult(
                output=None,
                readiness=None,
                attempts=(),
                status="abstained",
                omitted_source_refs=bundle.omitted_source_refs,
                diagnostics=("no_readable_sources",),
            )
        attempts: list[ExtractionAttempt] = []
        previous: Mapping[str, Any] | None = None
        missing: tuple[str, ...] = ()
        last_output: ReconciledPaperExperimentOutput | None = None
        last_readiness: DraftReadiness | None = None
        deadline = monotonic() + self.budget.max_seconds

        def remaining_timeout() -> float:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ProviderTechnicalError("time_budget_exhausted")
            return remaining

        for call_index, strategy in enumerate(
            self.strategy_order[: self.budget.max_calls],
            start=1,
        ):
            remaining_completion_tokens = (
                self.budget.max_total_completion_tokens
                - (call_index - 1) * self.budget.max_completion_tokens_per_call
            )
            if remaining_completion_tokens <= 0:
                return PaperExperimentExtractionResult(
                    output=last_output,
                    readiness=last_readiness,
                    attempts=tuple(attempts),
                    status=(
                        "partial_archive"
                        if last_output is not None
                        else "technical_failure"
                    ),
                    omitted_source_refs=bundle.omitted_source_refs,
                    diagnostics=("completion_token_budget_exhausted",),
                )
            if monotonic() >= deadline:
                return PaperExperimentExtractionResult(
                    output=last_output,
                    readiness=last_readiness,
                    attempts=tuple(attempts),
                    status=(
                        "partial_archive"
                        if last_output is not None
                        else "technical_failure"
                    ),
                    omitted_source_refs=bundle.omitted_source_refs,
                    diagnostics=("time_budget_exhausted",),
                )

            system_prompt, user_prompt = _prompt(
                objective=objective,
                bundle=bundle,
                strategy=strategy,
                previous=previous,
                missing=missing,
            )
            try:
                try:
                    response = self.response_client.complete(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        response_model=PaperExperimentDraftEnvelope,
                        max_completion_tokens=min(
                            self.budget.max_completion_tokens_per_call,
                            remaining_completion_tokens,
                        ),
                        task_type="paper_experiment_draft",
                        prompt_version=PAPER_EXPERIMENT_DRAFT_PROMPT_VERSION,
                        before_request=remaining_timeout,
                    )
                except ValidationError:
                    attempts.append(
                        ExtractionAttempt(
                            strategy=strategy,
                            status="rejected",
                            reason="provider response did not match the Draft envelope",
                            call_index=call_index,
                        )
                    )
                    previous = None
                    missing = ()
                    continue
                except Exception as exc:
                    raise ProviderTechnicalError(type(exc).__name__) from exc

                raw = response.model_dump(mode="python")
                output = PaperExperimentModelOutput.from_model_mapping(
                    raw,
                    document_id=bundle.document_id,
                    source_fingerprint=bundle.source_fingerprint,
                    source_labels=bundle.source_catalog,
                )
                reconciled = prepare_model_output(output, objective=objective)
                if not reconciled.output.experiments:
                    attempts.append(
                        ExtractionAttempt(
                            strategy=strategy,
                            status="insufficient",
                            reason="no source-supported experiment draft",
                            call_index=call_index,
                        )
                    )
                    previous = raw
                    missing = ("no source-supported experiment draft",)
                    continue
                readiness = assess_draft_readiness(
                    reconciled,
                    objective=objective,
                    omitted_source_refs=bundle.omitted_source_refs,
                )
                last_output = reconciled
                last_readiness = readiness
                previous = raw
                missing = readiness.missing_context
                if readiness.ready:
                    attempts.append(
                        ExtractionAttempt(
                            strategy=strategy,
                            status="passed",
                            call_index=call_index,
                        )
                    )
                    return PaperExperimentExtractionResult(
                        output=reconciled,
                        readiness=readiness,
                        attempts=tuple(attempts),
                        status="ready",
                        omitted_source_refs=bundle.omitted_source_refs,
                    )
                attempts.append(
                    ExtractionAttempt(
                        strategy=strategy,
                        status="insufficient",
                        reason="; ".join(missing),
                        call_index=call_index,
                    )
                )
            except ProviderTechnicalError as exc:
                attempts.append(
                    ExtractionAttempt(
                        strategy=strategy,
                        status="technical_failure",
                        reason=str(exc),
                        call_index=call_index,
                    )
                )
                if last_output is not None:
                    return PaperExperimentExtractionResult(
                        output=last_output,
                        readiness=last_readiness,
                        attempts=tuple(attempts),
                        status="partial_archive",
                        omitted_source_refs=bundle.omitted_source_refs,
                        diagnostics=(
                            "technical_failure_after_partial",
                            str(exc),
                        ),
                    )
                return PaperExperimentExtractionResult(
                    output=None,
                    readiness=None,
                    attempts=tuple(attempts),
                    status="technical_failure",
                    omitted_source_refs=bundle.omitted_source_refs,
                    diagnostics=("provider_technical_failure", str(exc)),
                )
            except ValueError as exc:
                attempts.append(
                    ExtractionAttempt(
                        strategy=strategy,
                        status="rejected",
                        reason=str(exc),
                        call_index=call_index,
                    )
                )
                previous = None
                missing = ()

        return PaperExperimentExtractionResult(
            output=last_output,
            readiness=last_readiness,
            attempts=tuple(attempts),
            status="partial_archive" if last_output is not None else "abstained",
            omitted_source_refs=bundle.omitted_source_refs,
            diagnostics=tuple(
                attempt.reason for attempt in attempts if attempt.reason
            ),
        )


__all__ = [
    "ExtractionAttempt",
    "ExtractionBudget",
    "PAPER_EXPERIMENT_DRAFT_PROMPT_VERSION",
    "PaperExperimentDraftEnvelope",
    "PaperExperimentExtractionResult",
    "PaperExperimentExtractor",
    "PaperExperimentSourceBundle",
    "ProviderTechnicalError",
    "build_bundle_from_routes",
    "build_source_bundle",
]
