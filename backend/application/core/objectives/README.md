# Research Objectives

This package owns candidate Objective discovery and confirmed, versioned
Objective analysis.

## Owners

- `research_objective_service.py`
  Orchestrates candidate discovery persistence and runs confirmed Objective
  analysis. It loads the immutable Source build, delegates candidate discovery
  to its direct owners, and atomically replaces the candidate fact set. For a
  confirmed Objective, it coordinates the ordered analysis stages and consumes
  their transient and durable results.
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
  routed Source through `extract_and_validate_source_facts`. It constructs
  bounded Source payloads, repairs structurally fragmented tables when
  required, extracts deterministic table records before model fallback, and
  owns the Source-local extraction prompt, response schema, scientific
  validation, bounded repair, completion budget, and direct model call. It
  records route-scoped provider or structured-output failures. Each
  schema-valid model draft is passed immediately to
  `analysis/source_validation.py` before it can update the state supplied to
  the next Source prompt, so extraction and validation alternate per Source
  rather than running as two collection-wide passes.
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
  binds Methods conditions to Results only through unambiguous sample identities;
  spacing and punctuation variants of the same alphanumeric label share one
  identity. Repeated Source reports of one measured comparison become one
  paper-owned fact with all Source locators retained when their scientific
  contexts are equal or uniquely compatible; missing context cannot bridge
  conflicting experimental states. It derives the existing bounded pairwise
  comparisons. A
  Source-grounded author comparison whose groups bind but whose linked
  context does not expose quantified process values remains association-only;
  it is not promoted to an isolated effect. Missing or conflicting sample
  identities remain descriptive, and reconstruction never crosses a document
  boundary.
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
- `evidence_map.py`
  Projects one published Objective analysis into the read-only
  `Objective -> Finding -> Evidence -> Source -> Document` relationship map.
  It reads existing domain records, preserves support, contradiction, context,
  and exact Source lineage, and reports failed or excluded papers only as
  coverage. It does not call a model, persist graph records, or restore the
  retired collection-wide Graph aggregate.
- `llm/structured_response.py`
  Owns the shared technical model boundary: provider invocation, schema-bearing
  messages, JSON parsing and bounded repair, trace capture, usage accounting,
  and complete prompt-token estimation. It does not own a scientific judgment,
  prompt, response schema, or domain state.
- `paper_skim_service.py`
  Orchestrates the pre-Objective paper-map stage. From every parsed paper it
  selects at most 16 high-level Source items: abstract/highlights, conclusion or
  summary, a bounded overview sample, and a few table/figure captions. When a
  poorly structured paper has none of those sections, it samples the first and
  last four narrative items. Detailed Methods, Results paragraphs, and table
  rows remain available to confirmed-Objective analysis but do not enter
  automatic Objective discovery. Table-map input carries a compact caption and
  bounded column headers; it never carries measurement rows.

  Selected items retain their original document-order identity, are grouped by
  broad reading role, packed up to 12 per request, and preflighted with the
  complete schema-bearing prompt against 12,288 tokens. Paper-map generation
  has a 2,048-token completion budget and returns at most four scope groups, six
  relationships per group, and eight unresolved signals. A relationship means
  that a high-level Source states the paper investigates the supplied material,
  joint intervention axes, and one specific outcome. It is candidate scope, not
  `ObjectiveEvidence`, a measured effect, or proof that two experiments are
  comparable. Sample context, test context, comparator, and fixed conditions
  are removed at this boundary; confirmed-Objective extraction owns them.

  Duplicate or non-input Source ids remain invalid and enter one bounded
  structured repair. Prompt overflow and output saturation can subdivide only
  the already bounded selected Sources. The shared per-paper recovery budget
  defaults to 4-12 calls, with a five-minute deadline; successful siblings
  survive while a terminal failure becomes `extraction_failed`. Broad or
  compound outcomes remain unresolved instead of being guessed. Review input
  retains only review-author synthesis and never reconstructs a cited primary
  experiment. The resulting `PaperSkim` persists Source-linked candidate-scope
  relationships, unresolved axes, and one coverage result for every selected
  Source unit. Coverage completeness refers to that bounded map, not to every
  Source in the full paper.
- `discovery/study_window.py`
  Owns the model judgment for one bounded PaperSkim Source window: its prompt,
  response schema, scientific bounds, repair instruction, stable-identity
  validation, token budget, and model call. It maps stated paper-owned research
  axes and unresolved signals; it does not reconstruct complete experiments,
  batch Sources, combine windows, or create collection Objectives.
- `discovery/signal_reconciliation.py`
  Owns the model judgment that decides whether incomplete variable and outcome
  signals found in different high-level windows describe one paper-owned
  research scope. It does not reconstruct an experiment. Its prompt,
  response schema, context-conflict validation, bounded repair, deterministic
  conflict removal, token budget, and model call live together. Paper-wide
  signal accounting and study consolidation remain in `paper_skim_service.py`.
  That final boundary keeps a broad or compound outcome signal unresolved even
  when reconciliation tries to link it to candidate variables.
- `discovery/axis_equivalence.py`
  Owns the bounded model judgment that classifies backend-proposed material,
  variable, and outcome label pairs for exact scientific-axis equivalence.
  Variable pairs carry bounded process, sample, and joint-factor
  observations from the PaperStudy records where each label occurred. Those
  observations disambiguate the controlled quantity and processing stage;
  co-occurrence or a shared outcome is not equivalence evidence. The module
  keeps pair accounting, prompt, repair, budget, and calls together. It cannot
  return canonical labels, groups, Objective questions, confidence, lineage, or
  dispositions; those remain backend-owned.
- `objective_candidate_service.py`
  Owns collection-level Objective discovery from `PaperStudyRelationship`
  records. The backend proposes high-overlap alias candidates plus sparse
  low-overlap alias pairs indexed by one exact outcome, a focused
  factor/intervention hint,
  different papers, and non-conflicting material scope. Outcome alias candidates
  without high label overlap require an exact shared variable and a shared
  measurement-identity hint. The model classifies every proposed pair for exact
  equivalence; it cannot invent labels or groups. Exact-equivalence edges build
  conservative complete-link alias groups. Related but non-equivalent axes do
  not become aliases.
  Outcomes must remain one exact measurement identity or an accepted synonym;
  related but distinct outcomes seed separate candidate questions. This
  normalized view is transient: persisted studies retain their
  extracted labels and exact Source lineage. Relationships may support one
  bounded Objective when they have non-conflicting material scope, one specific
  outcome identity, and one explicit intervention theme such as heat treatment,
  hot isostatic pressing, thermal post-processing, laser exposure, or build
  preheating. The Objective uses the most specific theme shared by every member;
  it never borrows one paper's precise factor as the group variable. Theme
  membership is not axis equivalence: each relationship retains its complete
  jointly varied factor set, and downstream Evidence comparison decides whether
  exact interventions, material states, methods, and test conditions are
  comparable. Only `current_work` relationships may seed an
  Objective; background, synthesis, uncertain, and varied-versus-fixed
  inconsistent relationships receive rejection dispositions. Common stainless steel grade
  spellings and established Ti-6Al-4V forms have one deterministic material
  identity. A relationship
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
  collection, the backend promotes only bounded groups supported by at least
  two papers; a single-document collection may still produce paper-local
  candidates. The backend derives each accepted Objective question, seed
  documents, shared scope, and lineage, then ranks cross-paper support before
  relationship count and confidence. Every relationship is promoted to an
  Objective or receives a backend-derived rejection disposition,
  while unresolved study signals remain separately visible. No second model
  call can move a relationship outside its backend-owned group, reject an input
  relationship, or remove records from persisted accounting.
  The completion trace reports count-only relationship dispositions, unresolved
  signals, and Source-unit coverage, including whether relationship accounting
  is complete and whether any extraction failed. It does not emit scientific
  labels, Source locators, excerpts, rejection reasons, or inventory records.
  The model does not generate collection Objectives: it is used only for bounded
  axis-equivalence decisions. The backend constructs each question, variable,
  outcome, seed-document set, and `source_relationship_ids` from the accepted
  relationship group.
- `property_matching.py`
  Owns application-layer matching from noisy Source labels to Objective axes,
  including observed OCR aliases, materials-specific broad outcome hints,
  bounded intervention-theme membership, contextual process-symbol hints, and
  deterministic method-family selection. Theme membership is exposed separately
  from exact axis matching so it can widen Objective inspection without
  canonicalizing distinct Source variables or comparison groups. These rules
  guide extraction and do not define universal domain equivalence.
- `analysis_service.py`
  Queues, claims, fails, and atomically publishes one Objective analysis
  version.
## Objective Boundary

Candidate discovery is part of collection build. Deep analysis begins only
after the user confirms an Objective. Each run receives one immutable Source
build, allocates a new `analysis_version`, and returns:

- `PaperContribution[]`
- `ObjectiveEvidence[]`
- `Finding[]`

Objective discovery has separate prompt and output bounds. Per-paper mapping
uses a deterministic researcher-like skim rather than full-document extraction:
abstract/highlights, conclusion or summary, a bounded overview sample, and a few
visual captions. A poorly structured document falls back to bounded narrative
edge sampling. At most 16 selected items can enter this stage, and no table row
does. The exact system message, user message, payload, and response schema are
counted against a 12,288-token prompt budget before execution. Independent broad
reading-role windows run with `CORE_EXTRACTION_MAX_CONCURRENCY` (default `4`)
and merge back in Source order.

Each model relationship maps an explicitly stated joint factor set to one
specific outcome axis. It authorizes a candidate question only; it does not
claim a direction, value, isolated effect, or comparable experiment. Incomplete
variable or outcome axes remain unresolved. Bounded cross-window reconciliation
may link only signals with positive paper-scope evidence such as an exact Source,
nearby original document position, explicit paper-owned label, or compatible
process context. Shared material alone remains insufficient, and any hard
context conflict rejects only the affected relationship.

The backend derives selected-Source coverage from validated references; an
unreferenced selected unit becomes `no_study_signal` without requiring the model
to return coverage. A failed call, invalid reference, 2,048-token output
termination, or explicit `output_saturated=true` result can subdivide only this
bounded map input. The default shared recovery budget is 4-12 calls per paper.
Successful siblings survive, while a terminal failure becomes
`extraction_failed`. `coverage_complete` therefore means that every selected
paper-map Source received a valid first-stage outcome; it does not mean that
every full-paper Source was read or that every relevant study was found. Those
full-paper judgments begin after Objective confirmation. Permanent failures
remain in the Objective node summary and warnings, and candidates from successful
Sources remain readable.

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

After mapping, the backend persists paper-scope groups, relationships,
unresolved signals, and selected-Source coverage before collection grouping. It
normalizes material, variable, and outcome labels before computing candidate
membership. Exact-equivalence candidates require high label overlap. Additional
low-overlap alias candidates come from a sparse index over one exact outcome,
focused factor or intervention hints, different papers, and compatible material
scope; a shared outcome alone never creates a factor Cartesian product. Outcome
labels with weak lexical overlap enter alias classification only when compatible
cross-paper facts share an exact variable and a measurement-identity hint. Only
`equivalent=true` can merge those outcomes. All eligible
pairs are processed in batches of at most 16. Every
response must classify every input pair exactly once and in order. Missing,
duplicate, unknown, or reordered IDs trigger one bounded repair; if any batch
still fails, the whole collection keeps its source labels rather than applying a
partial mapping. Only `equivalent=true` decisions form alias edges, and a label
joins an alias group only when it has an explicit edge to every current member.
The classifier returns only exact equivalence; it does not emit or confirm a
topic relation. Each variable pair includes at most two bounded PaperStudy
observations, each with the original joint-factor list and process/sample
context. These snapshots are
interpretive context, not proof that jointly varied factors are the same
intervention. Outcomes must be exactly equivalent after accepted alias
normalization. Every source relationship keeps its complete jointly varied
factor tuple and one specific outcome. A collection Objective is created when
at least two paper-owned current-work relationships have compatible material
scope, the same specific outcome, and either the same exact factor tuple or one
bounded shared intervention theme. The Objective variable is the precise tuple
when that tuple repeats; otherwise it is the most specific shared theme.
Explicit material conflicts remain a hard boundary. Other study-context and
exact-factor differences are retained, not flattened, and are evaluated
downstream when Evidence is compared. A theme-level Objective admits each
member's exact Evidence into analysis, while Finding result sets continue to
group by the exact extracted variables and compatible scientific context. A
paper-local group is promoted only when the
collection itself contains one
document; otherwise it remains traceable through its rejection disposition.
Accepted Objectives are ranked and persisted; the HTTP list returns all ranked
Objectives by default and supports explicit pagination when requested. Ranking
prefers independent paper support first, then Source-backed structured result
locators such as tables, table rows, and figures across independent papers,
then structured Source count, relationship count, and confidence. Multiple
tables in one paper cannot outrank structured result support distributed across
multiple papers. This ordering is an inspection priority only: a structured
Source locator does not establish a grounded or comparable result, and
downstream analysis may correctly publish an abstention for the highest-ranked
Objective.
Every
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
Sources for the document have been inspected, paper reconstruction may bind that
result to process conditions from other Sources in the same document. A
multi-level condition table is usable only when its repeated parent headers,
leaf headers, caption-defined symbols and units, and row values jointly define
exact labeled conditions. The backend does not derive process meaning from a
label such as `800 SC` itself.

Paper reconstruction registers labels within one Objective and document using
an alphanumeric identity, so `800SC`, `800 SC`, and `800-SC` resolve to the same
condition while retaining the Source spelling for display and provenance. It
merges complementary condition context and marks conflicting definitions of one
normalized identity ambiguous. A grounded result with no model-authored
comparison may use a registered label mentioned in its own Source with only
separator differences. For an explicit unchanged series, the first and last
mentioned conditions form a comparison only when both have complete process
context and exactly one process factor differs. The backend derives that
factor's endpoints and fixed context from the condition Sources, retains the
result Source, and may then classify the Evidence as `isolated_effect`. Missing
fields, multiple changed factors, ambiguous labels, or conflicting definitions
remain associative or `descriptive_only`; no cross-document binding, fuzzy
semantic matching, or LLM repair is attempted.

Every related Source locator records a `supports` list naming the scientific
field families owned by that Source, such as `reported_result`,
`comparison.labels`, `changed_variables`, or `scientific_context.process`.
Provider, transport, or unrecoverable structured-output errors remain technical
failures and produce explicit failed Evidence. A Source with no grounded target
result or useful context is an abstention and does not produce failed Evidence.

Final Evidence materialization uses stable `evidence_id` as the scientific-claim
identity and exact Source locators as provenance. Replayed drafts with the same
`evidence_id` remain idempotent, while distinct measurements or comparisons
from the same table, figure, or text Source remain separate durable records with
their own related locators. PaperContribution extracted/failed counts are
derived from this complete claim set exposed to readers.

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
and one outcome define the initial group. Before result direction is inspected,
the backend divides cross-paper Evidence into complete-link comparability
strata using fixed material, sample, process, and test context. Cross-paper
records must expose the same fixed-context fields with non-conflicting values;
missing fields do not imply equality and explicit differences form separate
strata. Changed variables are excluded from that fixed-context comparison. A
paper's already reconstructed within-paper comparison intervals remain intact.
Explicitly opposing directions remain in one context-compatible result set;
non-opposing labels such as `mixed` form separate result sets instead of being
mislabeled as contradictions. The primary direction is chosen only after this
scientific boundary, first by independent document support, then by Evidence
count, confidence, and a stable direction order. Multiple baseline-to-target
intervals in one set form a condition series rather than separate Findings, and
their exact endpoints remain on the individual Evidence records. For treatment
or processing-condition axes, the backend first separates untreated-reference
comparisons (`AB`, `AF`, `as-built`, or `as-fabricated` to a treated state) from
treated-state-to-treated-state comparisons. This preserves every extracted
interval while preventing a treatment-series contrast from manufacturing a
conflict inside a cross-paper reference-to-treatment Finding.
An axis such as `post-processing condition`, `processing condition`, `condition`,
`sample state`, or `material state` represents an unresolved condition package,
not one isolated scientific factor. A pairwise comparison on one such axis is
therefore `association_only`; an explicit single factor can remain
`isolated_effect`, while multiple explicit changed factors remain one
`joint_effect` tuple.
Opposing directions across different ranges of the changed axis may therefore
form one `condition_dependent` Finding when every fixed context field remains
compatible; an opposing fixed material, sample, process, or test condition does
not.

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
context Evidence. For a reference-to-treatment result set, the statement also
names the untreated reference contrast and any common material and orientation
context retained across supporting papers. The backend bounds the model's
assertion strength: the model may choose a weaker claim, but only a deterministic
controlled single-factor table comparison can remain `causal`; compound or
unresolved conditions are at most `associative`, and descriptive Evidence is at
most `descriptive`. Published condition boundaries and analysis limitations are
derived deterministically from validated factor coupling, direct-Evidence
coverage, contradiction, condition state, and attribution scope.

Finding certainty starts from the weakest direct Evidence confidence and is then
capped by independent document support: one document at `0.50`, two at `0.75`,
and three or more at `0.85`. `conflict` is capped at `0.60`,
`condition_dependent` at `0.70`, and `insufficient_confirmation` at `0.50`.
Additional Evidence rows from an already counted document preserve traceback but
do not raise the independence tier.

When a schema-valid candidate fails a backend semantic guard, synthesis records
the concrete rejection reason and permits one bounded provider repair against
the same Evidence. The repaired candidate must pass every original guard; a
second rejection is terminal for that result set and no invalid Finding is
published.

An empty Finding set is a valid scientific abstention when paper contributions
and source-backed Evidence were still produced. That analysis version is
published as `succeeded` with its paper dispositions and Evidence intact; the
backend does not manufacture a placeholder conclusion. Missing contributions,
missing source-backed Evidence, provider failures, invalid structured output,
and persistence failures remain technical analysis failures.

`agreement`, `conflict`, `condition_dependent`, and
`insufficient_confirmation` therefore describe validated Evidence coverage,
not provider confidence or a stored paper-count declaration. Coupled variables
remain one complete factor tuple and cannot be presented as an isolated causal
effect.
