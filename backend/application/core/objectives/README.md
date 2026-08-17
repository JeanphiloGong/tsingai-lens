# Research Objectives

This package owns candidate Objective discovery and confirmed, versioned
Objective analysis.

## Owners

- `research_objective_service.py`
  Orchestrates candidate discovery persistence and runs confirmed Objective
  analysis. It loads the immutable Source build, delegates candidate discovery
  to its direct owners, and atomically replaces the candidate fact set. For a
  confirmed Objective, it coordinates the ordered analysis stages and consumes
  their transient and durable results. The remaining publication
  responsibilities move to direct owners in a separate behavior-preserving
  slice.
- `analysis/source_screening.py`
  Owns confirmed-Objective Source screening from paper inputs to ordered
  `PaperAnalysisFrame` results. It traverses Source document trees, constructs
  bounded framing batches, and keeps the screening prompt, response schema,
  Source-id accounting, repair, token bounds, and batch model call with that
  responsibility. It preserves model, repair, and conservative fallback
  provenance. A screening decision means that a Source should or should not be
  inspected; it is not proof that the Source contains usable Evidence.
- `analysis/evidence_routing.py`
  Owns the transient `EvidenceCandidate` records created after screening and
  the complete bounded routing judgment: prompt, response schema, role
  normalization, model call, deterministic fallback, and final
  extraction-queue order. It binds every model decision to the current
  Objective, document, and Source, preserves tree order within a paper, and
  round-robins papers before extraction. Model and deterministic decisions are
  inspection hints only; neither is persisted or treated as scientific
  Evidence.
- `analysis/source_extraction.py`
  Owns transient `ExtractedEvidenceDraft` records and the inspection of every
  routed Source. It constructs bounded Source payloads, repairs structurally
  fragmented tables when required, extracts deterministic table records before
  model fallback, and owns the Source-local extraction prompt, response schema,
  scientific validation, bounded repair, completion budget, and direct model
  call. It records route-scoped provider or structured-output failures. Each
  schema-valid model draft is passed immediately to
  `analysis/source_validation.py` before it can update the state supplied to
  the next Source prompt.
- `analysis/source_validation.py`
  Owns deterministic validation of one model-authored draft against its exact
  Source. It independently grounds results, comparison labels, variables, and
  scientific context; unsupported results abstain, while a supported result
  with incomplete comparison support is retained only as descriptive Evidence.
  It records the field families supported by the Source and never calls the
  model or borrows facts from another Source.
- `analysis/paper_experiment.py`
  Owns reconstruction after every routed Source in a paper has been inspected.
  It fills missing material or process scope only from the same paper's skim,
  binds Methods conditions to Results only through exact and unambiguous sample
  identities, and derives the existing bounded pairwise comparisons. Missing or
  conflicting sample identities remain descriptive, and reconstruction never
  crosses a document boundary.
- `analysis/evidence_materialization.py`
  Owns the boundary from reconstructed drafts to durable `ObjectiveEvidence`
  and auditable `PaperContribution` records. It retains confirmed-Objective
  details, canonicalizes uniquely matching axes, resolves exact Source excerpts
  and related locators, and keeps one existing preference winner for each
  Objective, document, Source kind, and Source ref. Paper route, extracted,
  failed, and comparable counts come from that same final Evidence set. It does
  not persist artifacts or perform cross-paper Finding synthesis.
- `analysis/finding_synthesis.py`
  Owns deterministic cross-paper result-set construction and durable Finding
  publication. `FindingSynthesisService` retains complete Evidence membership,
  direction, identity, statement, status, certainty, limitations, and
  provenance. Its bounded `FindingAssertionJudge` model call decides only
  assertion strength and optional context or mechanism annotations for one
  backend-owned result set.
- `paper_skim_service.py`
  Orchestrates the per-document discovery stage. It assigns every eligible
  non-reference text node, table row, and table/figure caption to one full
  section-path group. `overview`, `methods`, `results`, `conclusion`, and
  `unknown` remain window metadata; they no longer collect unrelated sections
  into one global role bucket. Each section group is packed without sampling or
  truncation, then screened independently. Every table row repeats its table
  caption, heading path, and column headers while retaining the row locator as
  Source authority. The complete serialized prompt, including the response
  schema, is preflighted against a 12,288-token prompt budget before the model
  receives it; PaperSkim generation has a separate 4,096-token completion
  budget. A relationship or unresolved signal may reference at most the same 12
  unique Source-unit ids available in one input batch. Duplicate or non-input
  ids are invalid and enter one bounded structured repair. Prompt overflow
  splits before execution. Provider length termination or model-declared output
  saturation enters the same recursive Source-unit subdivision path as a failed
  multi-unit batch, preserving stable Source-unit ids until only a terminal
  singleton can become `extraction_failed`. A relationship with no varied
  factor is retained as an unresolved outcome signal when its outcome and
  Source lineage are valid; the backend does not invent a missing factor or
  discard valid sibling relationships.
  Successful siblings are retained. Duplicate studies are consolidated and
  unresolved study signals are reconciled only after every terminal batch has
  finished. The resulting one `PaperSkim` per document retains every distinct
  schema-valid `PaperStudy` and its complete `PaperStudyRelationship` records.
  The backend derives one first-stage
  extraction outcome for every eligible Source unit from validated relationship
  and signal references: `relationship_emitted`, `unresolved_signal_emitted`,
  `no_study_signal`, or `extraction_failed`. Jointly varied factors remain
  attached to one outcome and exact Source locators. Parsed table rows use
  `table_row + row_id`, while table captions and headers use
  `table + table_id`; inline table-matrix rows without a persisted row identity
  remain table-level. A skim retains only the stable Source `document_id`;
  title, filename, and window metadata remain Source-owned or transient.
- `discovery/study_window.py`
  Owns the model judgment for one bounded PaperSkim Source window: its prompt,
  response schema, scientific bounds, repair instruction, stable-identity
  validation, token budget, and model call. It reports studies, relationships,
  and unresolved signals supported by that window; it does not batch Sources,
  combine windows, or create collection Objectives.
- `discovery/signal_reconciliation.py`
  Owns the model judgment that decides whether variable and outcome signals
  found in different windows belong to one compatible experiment. Its prompt,
  response schema, context-conflict validation, bounded repair, deterministic
  conflict removal, token budget, and model call live together. Paper-wide
  signal accounting and study consolidation remain in `paper_skim_service.py`.
- `discovery/axis_equivalence.py`
  Owns the bounded model judgment that classifies backend-proposed material,
  variable, and outcome label pairs as exactly equivalent or different. It
  keeps the pair-accounting schema, prompt, repair, budget, and call together.
  It cannot return canonical labels, groups, Objective questions, confidence,
  lineage, or dispositions; those remain backend-owned.
- `objective_candidate_service.py`
  Owns collection-level Objective discovery from `PaperStudyRelationship`
  records. Before grouping, the backend proposes a bounded set of plausible
  material, variable, and outcome label pairs. The model classifies every pair
  as exactly equivalent or different; it cannot invent labels or groups. The
  backend then builds conservative complete-link groups, anchored by the most
  frequent source labels, and keeps every unclassified label unchanged. This
  normalized view is transient: persisted studies retain their extracted labels
  and exact Source lineage. Objective membership then requires the same complete
  factor set, one outcome, and a non-conflicting material scope. Common stainless
  steel grade spellings have one deterministic material identity. A relationship
  with missing material scope may join a known-material group only when exactly
  one scientifically compatible group exists; it cannot bridge conflicting
  materials. The resulting Objective retains one unambiguous material anchor;
  an ambiguous or absent shared scope stays empty and is explained in its
  reason. Objective confidence is the minimum available non-zero confidence
  from its source studies and relationships. It remains zero only when no
  source provides confidence, which is also recorded in the reason. A broad
  label with one measurement interpretation is refined deterministically, while
  a generic multi-measurement property family such as `mechanical properties`
  receives a rejection disposition until a specific outcome is available.
  Established research outcomes such as fatigue strength or microstructure stay
  intact rather than being replaced with an invented sub-measurement. Process,
  sample, test, comparator, design, and fixed-condition differences remain on
  each `PaperStudy`; they do not fragment a candidate Objective because later
  Evidence and Comparison own scientific comparability. For a multi-document
  collection, the backend promotes only compatible groups supported by at least
  two papers; a single-document collection may still produce paper-local
  candidates. The backend derives each accepted Objective question, seed
  documents, shared scope, and lineage, then ranks cross-paper support before
  relationship count and confidence. Every relationship is promoted to an
  Objective or receives a backend-derived rejection disposition,
  while unresolved study signals remain separately visible. No second model
  call can move a relationship outside its backend-owned group, reject an input
  relationship, or remove records from persisted accounting.
  The model does not generate collection Objectives: it is used only for bounded
  axis-equivalence decisions. The backend constructs each question, variable,
  outcome, seed-document set, and `source_relationship_ids` from the accepted
  relationship group.
- `property_matching.py`
  Owns application-layer matching from noisy Source labels to Objective axes,
  including observed OCR aliases, materials-specific broad outcome hints,
  contextual process-symbol hints, and deterministic method-family selection.
  These rules guide extraction and do not define universal domain equivalence.
- `analysis_service.py`
  Queues, claims, fails, and atomically publishes one Objective analysis
  version.
- `extraction.py`
  Owns the shared structured-response transport: provider invocation, JSON
  parsing and repair, trace capture, usage accounting, and schema-bearing prompt
  token estimation. Judgment-specific prompts, schemas, validation, and repair
  instructions belong to their discovery or analysis owner.

## Objective Boundary

Candidate discovery is part of collection build. Deep analysis begins only
after the user confirms an Objective. Each run receives one immutable Source
build, allocates a new `analysis_version`, and returns:

- `PaperContribution[]`
- `ObjectiveEvidence[]`
- `Finding[]`

Objective discovery has separate prompt and output bounds. Per-paper screening
uses as many full-section-path batches as the paper requires. Source units in a
section are packed at 4,000 characters and 12 units, then the exact system
message, user message, input payload, and response schema are counted against a
12,288-token prompt budget. Every eligible non-reference text node, table row,
and caption is assigned once, so later Methods, Results, Conclusions, and later
figure/table content are not dropped merely by position. Unusually long text
and structured Source content are split into contiguous bounded pieces without
truncating captions, headers, or row text. Each table-row unit repeats the full
caption, heading path, and column headers needed to interpret that row.
Cross-window reconciliation is outcome-centered. For each measured or predicted
outcome, the backend selects variable signals that have no hard context conflict
and share positive experiment evidence: an exact Source locator, nearby stable
Source-unit position, explicit experiment label, or overlapping process, sample,
test, fixed-condition, or comparator context. Shared material alone is not enough
to propose a link. Candidate variables are packed with one repeated outcome anchor
into batches of at most 12 signals, and the complete schema-bearing prompt is
preflighted against a 12,288-token budget. Omitted signals remain outside that
batch rather than becoming negative evidence. Model payloads receive bounded
excerpts and stable Source-unit positions while exact Source locators remain
backend-owned. The model decides only supported memberships and may explain
rejected candidates. The backend derives unresolved records for omitted inputs,
ignores an unresolved copy of an already linked signal, and permits only the
single outcome anchor, never a variable, to support multiple valid study groups.
Before a reconciliation leaves the extractor, every relationship
is checked against the input signals' material, process, sample, test, fixed,
experiment, comparator, design, and claim contexts. A conflict triggers one
bounded repair with the conflicting relationship, signal IDs, and context fields.
If the repaired response still contains a conflict, only that relationship is
discarded: signals not retained by another valid relationship become unresolved,
while valid relationships in the same response survive. The PaperSkim service
canonicalizes each relationship's unordered signal membership, merges repeated
memberships, and deduplicates relationships that resolve to the same factors,
outcome, and Source lineage before constructing a `PaperStudy`. All signal ids
from merged copies remain linked, and the lowest duplicate confidence is kept.
Failed reconciliation batches do not erase successful sibling batches, and a
relationship established in any batch overrides another batch's local unresolved
decision. After all batches finish, the backend derives final paper-wide signal
accounting. The PaperSkim service repeats the same deterministic context check as
a final boundary guard and separates individually valid relationships into
distinct PaperStudies when their contexts do not belong to one study. A broader
reconciliation failure leaves all affected signals unresolved instead of removing
them. Every emitted relationship and signal Source-unit ID must resolve to the
exact batch input.
The backend derives coverage from those validated references; an unreferenced unit becomes
`no_study_signal` without requiring the model to repeat a coverage object. A
failed call, invalid reference, 4,096-token output termination, or explicit
`output_saturated=true` result causes a multi-unit batch to split recursively.
Successful siblings survive, while only a terminal failed singleton becomes
`extraction_failed`. After all terminal batches finish, deterministic study
consolidation and paper-level unresolved-signal reconciliation remain the final
paper authority. `coverage_complete` therefore means that every eligible
Source unit was processed by a contract-valid first-stage extraction; it does
not prove that the model found every scientifically relevant study,
relationship, variable, or outcome. Model-call count grows with document length
and with failed-batch subdivision. Permanent singleton failures are included in
the Objective node summary and warnings. The collection build finishes as
`partial_success` while candidates derived from successful Source units remain
readable.

Objective paper framing is also source-batched. Explicitly excluded documents
are rejected by the backend without entering the model. The framing prior
contains only scientific fields from the paper relationships linked to the confirmed
Objective; full studies, Source locators, coverage records, unresolved signals,
and backend lineage IDs stay out of the prompt. Root-level unsectioned text and
every non-reference section are split into stable contiguous chunks. Every table
row enters a stable contiguous row chunk, with caption, heading path, and column
headers repeated on each chunk; one relevant or uncertain chunk keeps the whole
table routable. There is no keyword sampling or top-N removal. Model-visible
source-unit IDs are bounded opaque hashes of the Source kind, full stable Source
ref, and chunk position; the full Source ref remains backend-owned for downstream
traceability. The service packs at most eight
source units per request and preflights the complete schema-bearing prompt
against a 12,288-token input budget while reserving 1,024 completion tokens.
The model is instructed to place every supplied source-unit ID exactly once in
a relevant or excluded set. Missing, unknown, duplicate, or overlapping IDs
are invalid and enter one bounded accounting repair. A repaired response retains
the initial gap and marks every final batch decision as repaired. If repair,
provider execution, or prompt preflight fails, only that batch receives explicit
`fallback_relevant` dispositions with the failure reason; fallback is never
presented as a model relevance judgment. The backend requires exactly one
terminal disposition for every input ID before aggregation and records each
decision, its Source kind and full Source ref, and its model/repair/fallback
provenance in the transient `PaperAnalysisFrame`. It then derives selected
section or block Source refs from those dispositions for routing. Duplicate
section headings therefore remain distinct when the downstream router traverses
the document tree. A failed or irreducibly large batch keeps only its own
sources routable and cannot erase successful sibling decisions or mark their
paper role irrelevant. A paper becomes `irrelevant` only when every visible
source unit was explicitly excluded by a model or repaired decision.

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
backend turns each cross-paper membership group into one Objective. A
paper-local group is promoted only when the collection itself contains one
document; otherwise it remains traceable through its rejection disposition.
Accepted Objectives are ranked and persisted; the HTTP list returns all ranked
Objectives by default and supports explicit pagination when requested. Every
relationship is
persisted as `pending`, `promoted`, or `rejected`; rejection is a backend
eligibility or schema decision, never a model disposition. Partial Source
signals remain separately visible.
The schema migration cannot reconstruct studies from the former independent axis
lists, so it marks existing Objective builds not ready. Rebuilding the collection
regenerates the study inventory from Source artifacts.

Source selection and extraction are one persisted Evidence lifecycle:
`candidate -> selected -> extracted | rejected | failed`. Selection decisions
may be transient, but only `ObjectiveEvidence` is durable.

Each model call may return zero or one source-local Evidence extraction for the
selected Source. The extractor permits at most two sequential bounded repairs
for malformed JSON or schema-invalid output against that same Source; it does
not expose a second semantic-grounding call. A named parameter with identical,
non-empty scalar baseline and target values is fixed scientific context, not a
changed variable. At the model adapter boundary, the backend removes such a
parameter from `changed_variables` and `comparison.axis_names`. When that
removal leaves exactly one changed variable from a `joint_effect` draft, the
backend derives `isolated_effect`. When every named variable is fixed, the
backend removes the comparison and retains a grounded reported result as
`descriptive_only`. Because `comparison.axis_names` repeats changed-variable
identity, the adapter restores a missing or empty axis list only when every
changed variable has a unique non-empty name and complete, distinct endpoints.
When a result is present but an `isolated_effect` or `joint_effect` response has
no complete changed-variable interval, the adapter preserves the source-local
result and group labels but demotes the attribution to `association_only` or
`descriptive_only`; it never asks schema repair to invent the missing endpoint.
The backend never infers an axis or scientific value from Objective text.

After schema validation, the service grounds the reported result, comparison
labels, changed variables, and scientific context independently against their
owning Source. An unsupported result is discarded as abstention. A grounded
result with unsupported variables or comparison fields survives as partial,
descriptive Evidence instead of becoming a technical failure. After all routed
Sources for the document have been inspected, the service may bind that result
to process conditions from other Sources in the same document only when the
result names explicit baseline and target samples and both sample identities
resolve to unambiguous process contexts. A successful binding derives the
changed-variable endpoints from those condition Sources and preserves the
result and comparison labels from the result Source. Missing or conflicting
sample bindings remain `descriptive_only`; no cross-document binding or semantic
LLM repair is attempted.

Every related Source locator records a `supports` list naming the scientific
field families owned by that Source, such as `reported_result`,
`comparison.labels`, `changed_variables`, or `scientific_context.process`.
Provider, transport, or unrecoverable structured-output errors remain technical
failures and produce explicit failed Evidence. A Source with no grounded target
result or useful context is an abstention and does not produce failed Evidence.

Final Evidence materialization enforces zero or one durable record for each
`objective_id + document_id + source_kind + source_ref`. This boundary covers
normal extraction, repair output, deterministic derivation, and replayed drafts;
`evidence_id` alone is not Source identity. When candidates conflict, extracted
Evidence outranks failed attempts, result Evidence outranks context, richer
validated scientific content outranks sparse content, and resolution then
confidence break remaining ties. The service never merges scientific fields
from competing candidates. If every candidate failed, one detailed failed
record remains, so PaperContribution extracted/failed counts are derived from
the same final Source-keyed Evidence set exposed to readers.

An extraction failure is also durable Evidence when the analysis can otherwise
complete. It retains the exact `document_id + source_kind + source_ref` locator
and Source excerpt, has `selection_status=failed`, requires a `failure_reason`,
and is `not_attributable`. It remains visible beside successful Evidence through
the Evidence API but cannot support a Finding. When one provider failure
suppresses later calls for the same Objective/document, every affected routed
Source receives its own failed Evidence record rather than disappearing from
paper accounting.

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

Evidence extraction interleaves documents round-robin while preserving Source
tree order inside each document. A provider-unavailable response suppresses
later provider calls only for that Objective/document; routes from other papers
continue. This prevents a paper with many table rows from consuming all useful
attempts before another paper is examined.

Deterministic table Evidence retains row and result-column coordinates in its
related Source locators. Pairwise table results include both source rows, retain
material differences, reject sparse comparison axes as non-attributable, and
are bounded per Objective/document.

Before an Evidence draft becomes durable, each source variable, comparison
axis, and outcome that resolves to exactly one confirmed Objective axis adopts
that Objective label. Unit-qualified labels and approved Source aliases
therefore share one runtime identity, while unmatched coupled factors remain
verbatim. Exact Source wording is still retained in the excerpt, result text,
and Source locators. Finding domain validation stays strict over these canonical
Evidence identities and does not own application-level alias rules.

After Evidence construction, each `PaperContribution` records one auditable
paper outcome. `routed_source_count`, `extracted_source_count`, and
`failed_source_count` count unique `(source_kind, source_ref)` locators;
`comparable_evidence_count` counts eligible Evidence rows because multiple
comparisons may legitimately come from one Source. A comparable row is inside
the Objective axes, has a known direction, and can support a Finding. The
terminal dispositions are:

- `excluded`: framing excluded the paper and every count is zero;
- `no_routable_evidence`: the paper was retained but no Source was selected;
- `extraction_failed`: Sources were routed, none produced extracted Evidence,
  and at least one failed;
- `no_comparable_evidence`: extraction completed but produced no eligible
  direct result for this Objective;
- `comparable_evidence`: at least one eligible direct result survived, possibly
  alongside partial Source failures.

Finding synthesis first excludes Evidence that cannot support a Finding or has
`direction=unknown`. A unit-qualified or noisy factor/outcome label is mapped to
an Objective axis only when that match is unique; the canonical factor tuple
and one outcome define the initial group. Explicitly opposing directions remain
in one result set; non-opposing labels such as `mixed` form separate result sets
instead of being mislabeled as contradictions. The primary direction is chosen
first by independent document support, then by Evidence count, confidence, and
a stable direction order. Multiple baseline-to-target intervals in one set form
a condition series rather than separate Findings, and their exact endpoints
remain on the individual Evidence records.

The model sees at most 16 representatives selected round-robin across documents
and directions. It also receives a complete per-document summary containing
Evidence count, direction counts, and attribution-scope counts for the whole
result set. This bound affects generation input only: no durable Evidence is
deleted or sampled. The backend retains the complete result set to generate the
statement, assign every supporting and contradicting Evidence ID, derive
Finding-local paper bindings and synthesis status, and preserve Source
traceback. Repeated rows from one paper therefore never count as independent
cross-paper confirmation. Each result set can produce at most one Finding. The
statement contains only the complete factor tuple, one outcome, backend-owned
direction, and explicit opposing directions; it cannot copy model-authored
numbers or silently omit a coupled factor. The model decides only assertion
strength and optional context or subordinate mechanisms backed by supplied
context Evidence. Published condition boundaries and analysis limitations are
derived deterministically from validated factor coupling, direct-Evidence
coverage, contradiction, condition state, and attribution scope.

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
