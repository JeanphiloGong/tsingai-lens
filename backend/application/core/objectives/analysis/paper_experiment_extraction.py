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


class ExtractedTestConditionModelOutput(BaseModel):
    """A reported protocol candidate; its local key does not prove binding."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    test_key: str = Field(
        min_length=1,
        description="Required response-local key for this test candidate, even when its scientific identity is broad.",
    )
    test_type: str = Field(
        min_length=1,
        description="Source-reported test or characterization category; do not invent a method.",
    )
    source_labels: list[str] = Field(
        min_length=1, description="Supplied Sxxx labels supporting this test.",
    )
    method: str | None = Field(
        default=None, description="Reported method or instrument; null when absent.",
    )
    standard: str | None = Field(
        default=None, description="Reported standard; null when absent.",
    )
    parameters: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Reported operating values as name/value/unit objects, including temperature, speed and replication.",
    )
    outcome_scope: list[str] = Field(
        default_factory=list, description="Outcomes explicitly covered by this protocol.",
    )
    binding_source_labels: list[str] = Field(
        default_factory=list,
        description="Supplied sources explicitly linking the protocol to this experiment; empty when unknown.",
    )
    protocol_specificity: Literal["exact", "partial", "category", "broad", "unknown"] = Field(
        default="unknown",
        description="Concrete method identity supported by the sources; a local key alone is not exact identity.",
    )
    protocol_completeness: Literal["complete", "partial", "unknown"] = Field(
        default="unknown",
        description="Coverage of reported operating conditions, separate from protocol identity.",
    )
    missing_parameters: list[str] = Field(
        default_factory=list,
        description="Unreported operating details; preserve them without inventing values.",
    )


class ExtractedPaperExperimentModelOutput(BaseModel):
    """Experiment content with explicit protocol structure and extensible facts."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    label: str = Field(
        min_length=1, description="Human-readable source-supported experiment label.",
    )
    scope_description: str = Field(
        min_length=1, description="Reported population, treatment assignment and experiment boundary.",
    )
    test_conditions: list[ExtractedTestConditionModelOutput] = Field(
        default_factory=list,
        description="Reported protocol candidates. Omit unsupported tests; measurement test_key may remain null when binding is unknown.",
    )


class ExtractedDocumentIssueModelOutput(BaseModel):
    """A document-wide gap, not a reference to a local experiment member."""

    model_config = ConfigDict(extra="allow")

    target_ref: Literal["document", "experiment"] = Field(
        default="document", description="Global issue scope; local member references belong inside that experiment's unresolved_issues.",
    )
    description: str = Field(min_length=1, description="Source-supported gap or limitation; never invent missing facts.")
    source_labels: list[str] = Field(default_factory=list, description="Supplied Sxxx labels supporting this issue, when available.")


class PaperExperimentDraftEnvelope(BaseModel):
    """Provider content schema; application gates still own scientific binding."""

    model_config = ConfigDict(extra="forbid")

    experiments: list[ExtractedPaperExperimentModelOutput] = Field(
        default_factory=list,
        description=(
            "Zero or more bounded experiment Draft objects. Each object uses "
            "response-local keys where useful and may contain source-local "
            "reported observations. Local "
            "keys identify declared variants and tests. Measurement references may "
            "be null when their binding is unresolved; use supplied Sxxx source labels."
        ),
    )
    source_labels: list[str] = Field(
        default_factory=list,
        description=(
            "The supplied Sxxx labels used anywhere in this response; never "
            "invent source IDs or SourceReference objects."
        ),
    )
    unresolved_issues: list[ExtractedDocumentIssueModelOutput] = Field(
        default_factory=list,
        description=(
            "Document-level boundary, conflict, or missing-context records. "
            "Use target_ref=document or experiment and description. Member-specific "
            "issues belong inside their experiment, not here; keep unknowns."
        ),
    )


PAPER_EXPERIMENT_DRAFT_PROMPT_VERSION = "paper_experiment_draft.v3"


_DRAFT_SCHEMA_HINT: dict[str, Any] = {
    "experiments": [
        {
            "series_key": "local-series-key",
            "label": "source-supported experiment label",
            "scope_description": "reported population and treatment assignment",
            "scope_kind": "parent",
            "member_hints": {
                "variant_keys": [],
                "test_keys": [],
                "measurement_keys": [],
            },
            "experimental_variants": [
                {
                    "variant_key": "local-variant-key",
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
                    "test_key": "local-test-key",
                    "test_type": "paper-reported method",
                    "method": "reported method or instrument",
                    "standard": "reported standard, if any",
                    "parameters": [],
                    "outcome_scope": ["requested outcome"],
                    "source_labels": ["S001"],
                    "binding_source_labels": ["S001"],
                    "protocol_specificity": "exact",
                    "protocol_completeness": "partial",
                    "missing_parameters": [],
                    "protocol_evidence": [],
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
   measurement's `variant_key` or `test_key` may be null when the row/sample or protocol is
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
  and stated sample/test labels. Give source-supported candidates local keys;
  bind measurement references only when the paper supports the exact edges.
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
reported fact; measurement variant/test references are optional when the source does
not prove an exact binding. Preserve large or multi-column table results in
their complete Source block; do not introduce a separate table-row domain
object.
Every declared variant and test candidate needs a non-empty local key. This
key identifies the candidate within the response, not a proven scientific
binding. Only measurement references may be null when their edges are unknown.
Every experiment needs label and scope_description. Put reported temperature,
speed and repetition values in test parameters as name/value/unit objects.
Top-level unresolved_issues target_ref must be document or experiment. Inside
an experiment, use experiment or a path to a declared member:
variants/<variant_key>, test_conditions/<test_key>, measurements/<measurement_key>,
or comparisons/<comparison_key>. Do not use a bare local key or free text as
target_ref. Put the explanation in description.
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
                except ValidationError as exc:
                    reason = "; ".join(
                        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                        for error in exc.errors(include_input=False, include_url=False)
                    )
                    attempts.append(
                        ExtractionAttempt(
                            strategy=strategy,
                            status="rejected",
                            reason=reason,
                            call_index=call_index,
                        )
                    )
                    previous = None
                    missing = (reason,)
                    continue
                except Exception as exc:
                    raise ProviderTechnicalError(type(exc).__name__) from exc

                raw = response.model_dump(mode="python", exclude_unset=True)
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
                missing = (str(exc),)

        return PaperExperimentExtractionResult(
            output=last_output,
            readiness=last_readiness,
            attempts=tuple(attempts),
            status=(
                "partial_archive" if last_output is not None
                else "abstained" if any(attempt.status == "insufficient" for attempt in attempts)
                else "technical_failure"
            ),
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
