# Research Objectives

This package owns candidate Objective discovery and confirmed, versioned
Objective analysis.

## Owners

- `research_objective_service.py`
  Orchestrates candidate discovery persistence and runs confirmed Objective
  analysis. It loads the immutable Source build, delegates candidate discovery
  to the two direct owners below, and atomically replaces the candidate fact
  set. Confirmed analysis traverses Source document trees with bounded
  transient state, emits one `PaperContribution` per included document, and
  emits `ObjectiveEvidence` records containing exact excerpts and typed Source
  locators. Framing, routing, and extraction consume the persisted
  ResearchObjective variables, outcomes, mechanisms, constraints, and
  requested comparator directly. Table-selection hints remain transient
  service values.
- `paper_skim_service.py`
  Owns the per-document discovery stage. It builds bounded model input from
  Source documents, profiles, text blocks, tables, figures, and document trees,
  then emits one `PaperSkim` research map per document. A skim retains only the
  stable Source `document_id`; title and filename metadata remain Source-owned.
- `objective_candidate_service.py`
  Owns collection-level candidate discovery from `PaperSkim` records. It
  validates seed-paper support, canonicalizes model-produced document ids and
  research axes, restores a model-omitted material scope only when every seed
  skim supports the same material, validates merge decisions, and removes exact
  duplicates.
- `evidence_routing.py`
  Owns the transient Source-selection decisions created while routing one
  confirmed Objective across its documents.
- `evidence_extraction.py`
  Owns structured Evidence drafts before the service binds exact Source text
  and publishes durable `ObjectiveEvidence` records.
- `property_matching.py`
  Owns application-layer matching from noisy Source labels to Objective axes,
  including observed OCR aliases, materials-specific broad outcome hints,
  contextual process-symbol hints, and deterministic method-family selection.
  These rules guide extraction and do not define universal domain equivalence.
- `analysis_service.py`
  Queues, claims, fails, and atomically publishes one Objective analysis
  version.
- `finding_synthesis_service.py`
  Produces evidence-calibrated paper and cross-paper Findings from validated
  Objective Evidence.
- `extraction.py`
  Calls the configured model provider for Objective discovery, framing,
  Evidence extraction, and Finding synthesis and owns their bounded retry and
  repair behavior.
- `prompts.py` and `schemas.py`
  Define Objective prompts and their validated response contracts.

## Objective Boundary

Candidate discovery is part of collection build. Deep analysis begins only
after the user confirms an Objective. Each run receives one immutable Source
build, allocates a new `analysis_version`, and returns:

- `PaperContribution[]`
- `ObjectiveEvidence[]`
- `Finding[]`

Source selection and extraction are one persisted Evidence lifecycle:
`candidate -> selected -> extracted | rejected | failed`. Selection decisions
may be transient, but only `ObjectiveEvidence` is durable.

Each extracted Evidence record binds one exact Source excerpt to an explicit
scientific attribution contract:

- one Evidence extraction represents one baseline-to-target comparison
  interval, and each changed-factor name appears at most once;
- `changed_variables` retains every changed factor with baseline and target
  values;
- `comparison` records both groups, all comparison axes, and whether the
  groups are scientifically comparable;
- `reported_result` contains exactly one measured outcome for result Evidence;
- `attribution_scope` distinguishes an isolated effect, joint effect,
  association, description, or non-attributable comparison;
- `scientific_context` stores fixed material, sample, process, and test
  attributes as typed name/value/unit entries.

When an extracted Evidence record omits material or process context, the
service may fill the missing material category or missing process-identity
attribute from already persisted scope data. It uses the same document's
`PaperSkim.candidate_materials` and `PaperSkim.candidate_processes`. Objective
scope alone never supplies document Evidence context. The service preserves
extracted process attributes, does not replace extracted context, and does not
infer new scientific attributes.

Transient extraction state is scoped to one Objective, analysis version, and
document. It carries only prior role/outcome coverage and Source positions
between blocks, never prior scientific values or context. It is reset before
the next document and never supplies a missing changed variable or outcome.

Deterministic table Evidence retains row and result-column coordinates in its
related Source locators. Pairwise table results include both source rows, retain
material differences, reject sparse comparison axes as non-attributable, and
are bounded per Objective/document.

Finding synthesis groups Evidence only by an exact normalized changed-factor
tuple and one exact outcome. Multiple baseline-to-target intervals in that
group form one condition series rather than separate Findings, and their exact
endpoints remain on the individual Evidence records. For a condition series,
the model-facing view retains every Evidence and paper id, factor endpoint,
structured result, and attribution scope while omitting repeated excerpts and
context; its Finding statement cannot publish numeric endpoints because they
belong to individual comparisons. The backend keeps the complete persisted
Evidence for validation and traceback. Each group can produce at most one
Finding. The backend binds the result-set identity, assigns every direct result
as supporting or
contradicting, requires the statement to foreground heterogeneous responses
when directions oppose, and derives condition boundaries, attribution scope,
synthesis status, certainty, common scientific context, and one Finding-local
binding for every PaperContribution in the analysis. The provider may identify
only subordinate mechanisms backed by supplied context Evidence. Published
analysis limitations are derived deterministically from validated factor
coupling, direct-Evidence coverage, contradiction, condition boundaries, and
attribution scope; provider-authored free-text limitations are not published.

When a schema-valid candidate fails a backend semantic guard, synthesis records
the concrete rejection reason and permits one bounded provider repair against
the same Evidence. The repaired candidate must pass every original guard; a
second rejection is terminal for that result set and no invalid Finding is
published.

`agreement`, `conflict`, `condition_dependent`, and
`insufficient_confirmation` therefore describe validated Evidence coverage,
not provider confidence or a stored paper-count declaration. Coupled variables
remain one complete factor tuple and cannot be presented as an isolated causal
effect.
