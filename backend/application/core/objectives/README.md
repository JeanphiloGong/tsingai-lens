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
  Owns the per-document discovery stage. It assigns every eligible
  non-reference text node and every table/figure caption to one section-aware
  `overview`, `methods`, `results`, `conclusion`, or `unknown` source window.
  Each bounded window is screened independently; duplicate study signals are
  reconciled only after all windows finish. The resulting one `PaperSkim` per
  document retains every distinct schema-valid `PaperStudy` and its complete
  `PaperStudyRelationship` records. It also records one first-stage extraction
  outcome for every eligible Source unit: `relationship_emitted`,
  `unresolved_signal_emitted`, `no_study_signal`, or backend-derived
  `extraction_failed`. Jointly varied factors remain attached to one outcome
  and exact Source locators. Parsed table rows use
  `table_row + row_id`, while table captions and headers use
  `table + table_id`; inline table-matrix rows without a persisted row identity
  remain table-level. A skim retains only the stable Source `document_id`;
  title, filename, and window metadata remain Source-owned or transient.
- `objective_candidate_service.py`
  Owns collection-level Objective discovery from `PaperStudyRelationship`
  records. Before grouping, the backend proposes a bounded set of plausible
  material, variable, and outcome label pairs. The model classifies every pair
  as exactly equivalent or different; it cannot invent labels or groups. The
  backend then builds conservative complete-link groups, anchored by the most
  frequent source labels, and keeps every unclassified label unchanged. This
  normalized view is transient: persisted studies retain their extracted labels
  and exact Source lineage. Objective membership then requires the same complete
  factor set, one outcome, and a non-conflicting material scope. Process,
  sample, test, comparator, design, and fixed-condition differences remain on
  each `PaperStudy`; they do not fragment a candidate Objective because later
  Evidence and Comparison own scientific comparability. The backend directly
  promotes each compatible relationship group to one Objective, derives its
  question, seed documents, shared scope, and lineage, then ranks cross-paper
  support before relationship count and confidence. Every relationship is
  promoted to an Objective or receives a backend-derived rejection disposition,
  while unresolved study signals remain separately visible. No second model
  call can move a relationship outside its backend-owned group, reject an input
  relationship, or remove records from persisted accounting.
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
  Calls the configured model provider for PaperSkim extraction, relationship
  axis canonicalization, framing, Evidence extraction, and Finding synthesis
  and owns their bounded retry and repair behavior.
- `prompts.py` and `schemas.py`
  Define Objective prompts and their validated response contracts.

## Objective Boundary

Candidate discovery is part of collection build. Deep analysis begins only
after the user confirms an Objective. Each run receives one immutable Source
build, allocates a new `analysis_version`, and returns:

- `PaperContribution[]`
- `ObjectiveEvidence[]`
- `Finding[]`

Objective discovery has two different bounds. Per-paper screening uses as many
4,000-character section-aware source windows as the paper requires. Every
eligible non-reference text node and caption is assigned once, so later Methods,
Results, Conclusions, and later figure/table captions are not dropped merely by
position. Unusually long text and structured Source content are split into
contiguous bounded pieces without truncating captions, headers, or row text.
Cross-window reconciliation receives bounded excerpts for already extracted
signals, but each signal retains its complete structured fields and exact Source
locator. Reconciliation failure leaves those signals unresolved instead of
removing them. Every valid window response must account for its exact input
Source-unit IDs. Missing, duplicate, unknown, or status-inconsistent coverage
invalidates that window, and the backend records `extraction_failed` rather than
inventing `no_study_signal`. A failed window does not discard valid neighboring
windows. `coverage_complete` therefore means that every eligible Source unit was
processed by a contract-valid first-stage extraction; it does not prove that the
model found every scientifically relevant study, relationship, variable, or
outcome. Model-call count grows with document length.

After screening, the backend persists extracted studies, relationships,
unresolved signals, and Source-unit coverage before collection grouping. It
normalizes material, variable, and outcome labels before computing candidate
membership. Candidate generation is capped at 96 pairs per axis type, and the
model receives at most 16 pairs per call. Every response must classify every
input pair exactly once and in order. Missing, duplicate, unknown, or reordered
IDs trigger one bounded repair; if any batch still fails, the whole collection
keeps its source labels rather than applying a partial mapping. Only
`equivalent=true` decisions form edges, and a label joins a group only when it
has an explicit edge to every current member. The complete jointly varied
factor tuple and one outcome then define the research axis; explicit material
conflicts remain a hard boundary. Other study-context differences are retained,
not flattened, and are evaluated downstream when Evidence is compared. The
backend turns each membership group directly into one Objective. All Objectives
are ranked and persisted; the HTTP list returns all ranked Objectives by default
and supports explicit pagination when requested. Every relationship is
persisted as `pending`, `promoted`, or `rejected`; rejection is a backend
eligibility or schema decision, never a model disposition. Partial Source
signals remain separately visible.
The schema migration cannot reconstruct studies from the former independent axis
lists, so it marks existing Objective builds not ready. Rebuilding the collection
regenerates the study inventory from Source artifacts.

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
attribute from already persisted scope data. It uses material and process values
from the same document's linked `PaperSkim.studies`. Objective scope
alone never supplies document Evidence context. The service preserves extracted
process attributes, does not replace extracted context, and does not infer new
scientific attributes.

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
