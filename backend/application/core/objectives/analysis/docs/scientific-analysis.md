# Scientific Analysis

This page defines the scientific order of the Objective analysis runtime. It uses
one concrete scenario as the reference: a researcher asks whether a process
treatment changes a measured outcome, reads Methods and Results from a paper,
checks the sample/test relationship, and decides whether the result can be
compared with another paper.

The central distinction is between candidate content and accepted bindings. A
model can recover a useful value while still being unable to say which exact
sample or protocol produced it. Lens keeps that value visible, but does not
turn a broad label into a precise scientific relationship.

## End-to-end order

    Objective and prepared Documents
      -> Source screening
      -> deterministic Source routing
      -> bounded Draft extraction
      -> service reconciliation
      -> Source-label resolution and binding
      -> immutable PaperExperiment revision
      -> Objective-scoped selection
      -> optional cross-paper synthesis

The order is a scientific dependency, not an implementation preference:
screening finds where to look; Source reading establishes facts; reconciliation
decides which candidate scopes are defensible; binding establishes who and what
produced a result; only then can an Objective select evidence or synthesize a
Finding.

## 1. Screening and routing

source_screening.screen_sources produces transient paper frames. A positive
frame means that a Source should be inspected, not that the paper already
contains usable Evidence. Review papers remain secondary context; a cited
experiment must be inspected in its primary paper before it can support a
Finding.

evidence_routing.route_sources turns frames and the Source tree into a bounded
inspection queue. Routing is deterministic and carries no scientific claim. A
framing false negative must not hide a Source that contains an explicit
Objective variable or result signal. Conversely, an unread navigation
candidate is not silently counted as a missing scientific result.

## 2. Source-local fact extraction

source_extraction.extract_and_validate_source_facts reads routed Sources and
returns transient SourceObservation records. It owns table payload assembly,
bounded table repair, model extraction, and route-scoped technical failures.
source_validation.validate_source_fact checks each observation against the exact
Source before it enters the same-paper working state.

Extraction and validation alternate per Source; they are not a collection-wide
"extract everything, then validate later" pass. Methods, captions, tables,
figures, and Results may complete one another only inside the same document and
only when a Source supplies an explicit identity or relationship. A paper map,
Objective hint, or general scientific knowledge cannot fill a missing field.

A successful empty read is an inspected Source with no supported fact. A
provider error, timeout, or irrecoverable parser error is a technical failure.
The two dispositions are kept separate so scientific absence is never confused
with an unavailable read.

## 3. PaperExperiment Draft extraction

PaperExperimentExtractor.extract receives a service-built
PaperExperimentSourceBundle. The bundle gives the model request-local labels
such as S001; the real document_id, source_ref, and fingerprint remain
server-owned.

The provider envelope is deliberately small:

    PaperExperimentModelOutput (service context)
      experiments: PaperExperimentDraft[]
      source_labels: string[]
      unresolved_issues: object[]

The current provider contract is `paper_experiment_draft.v2`. Its nested
scientific payload remains open-ended so a psychology, biology, or materials
paper can report different attributes; the JSON schema descriptions and prompt
schema hint define the stable local-key/source-label envelope. Deterministic
`prepare_model_output` remains the authority for formal-ID rejection,
cross-reference validity, and source/binding gates. A valid provider envelope
therefore does not by itself make a Draft ready for persistence or a Finding.

Each Draft contains only content and response-local keys. Typical content is:

    experimental_variants[]   # sample/object plus treatment or state
    test_conditions[]         # method/protocol and applicability
    measurements[]            # reported value/text and local references
    comparisons[]             # candidate within-paper relationships
    reported_interpretations[]
    unresolved_issues[]

The model may propose series_key, variant_key, test_key, measurement_key, and
comparison_key. These keys are valid only inside this response. It may also
provide candidate fields such as identity_specificity, protocol_specificity,
direction_candidate, or attribution_scope_candidate; they are hints for
service checks, not accepted status.

The model must not generate formal experiment/result IDs, database IDs,
collection or Objective ownership, revision numbers, formal SourceReference
objects, binding/relation status, or final direction/basis/causal decisions.
PaperExperimentModelOutput.from_model_mapping rejects those fields, and the
service attaches request context and the Source catalog.

### Why broad facts are allowed

Papers often say only "mechanical test", "sample group", or "condition A" in a
result table while the exact protocol or group definition appears elsewhere.
Rejecting the value at extraction time would lose a report that a researcher
can still review. Therefore a broad sample/test is valid Draft content, but it
must carry one of the following:

- a candidate local reference such as candidate_variant_keys or
  candidate_test_keys;
- a missing dimension or unresolved issue; or
- a Source label showing where the broader statement came from.

The service later classifies the edge as exact, partial, ambiguous, or unbound.
A model assertion that a generic label is exact cannot override this
classification. A measurement with a value but a non-exact edge is retained in
the revision and is ineligible for a strict Selection.

## 4. Preparation and deterministic checks

prepare_model_output performs structural checks without assigning formal
identity:

1. Every local key is unique and every local reference resolves.
2. Every measurement has a reportable value or result text and a reviewable
   Source label.
3. Every comparison references measurements on both sides and uses one outcome
   vocabulary.
4. Unknown Source labels and malformed unresolved-item targets are rejected.
5. Conflicting reports are retained as separate measurements. A comparison
   that references either side is marked uncertain until a report is selected.
6. Numeric direction is computed only when there is one numeric value per side
   and one shared unit. No aggregation rule is invented.

These checks produce audit issues and candidate fields. They do not claim that
the paper has been fully understood.

## 5. Boundary reconciliation

reconcile_model_output is the service-owned handoff before formal identity
allocation. The model can propose scopes, but it cannot accept its own proposal.

The rules are intentionally conservative:

| Candidate scope | Service treatment |
|---|---|
| parent or matrix | May serve as a physical experiment container when its content supports that scope. |
| selected_stratum or follow_up | Must name a parent and a selector that actually hits local facts; it remains an overlapping view of the parent. |
| physical_split, split, or independent | Requires positive Source-backed evidence such as a different population, assignment, cohort, specimen set, or design. |
| unknown | Cannot receive a formal identity until reconciled; it is not promoted to a parent because it appeared first. |

A section, table, outcome, response order, or a change of wording is not
evidence of a new physical experiment. Conversely, two independent populations
must not be merged merely because they share an outcome or a test category.
When scopes cannot be decided, retain the content in a partial revision and
record the boundary issue. Do not manufacture a parent or split to make the
count look complete.

The current reconciliation helper may collapse advisory overlapping scopes into
a parent and retain positive physical splits. This is a service operation, not
a model success signal. It must be covered by boundary precision/recall tests;
any collision or ambiguous split is a manual-reconciliation blocker.

## 6. Source binding

bind_model_output runs only on a ReconciledPaperExperimentOutput. It:

- resolves request-local Source labels to immutable SourceReference values;
- injects the formal experiment identity, version, document, and fingerprint;
- preserves unresolved issues and reported alternatives; and
- computes result-level binding from source-backed sample and test edges.

An exact measurement requires all of the following:

1. a local sample key and a concrete, non-ambiguous sample identity;
2. a local test key and a concrete, outcome-applicable protocol identity;
3. a result Source reference; and
4. a distinct Source-backed binding edge for the sample and test.

Missing one edge, a generic category-only test, duplicate sample labels, or
an explicit outcome-scope mismatch yields uncertain/partial, not direct. The
`protocol_completeness` and `missing_parameters` fields remain source-coverage
metadata: a concrete protocol can be selected with partial or unknown coverage,
but the resulting Finding carries that limitation. A revision is bound only
when its measurements satisfy the binding rules; a revision with retained but
unresolved measurements is partial.

Paper-native identifiers are preserved without becoming Lens identities. The
Draft may carry a domain-specific name such as `stimulus_id`, `condition_id`,
or `batch_id` only inside `population_scope.reported_identifiers` or
`measurement_scope.reported_identifiers`. Formal Lens names and arbitrary
`*_id`/`*_ids` fields remain rejected elsewhere; the service allocates formal
identities after source and boundary validation.

This is why the extraction contract must not require the model to recover exact
sample-test bindings in one response. The contract asks the model to expose
candidate edges and uncertainty; deterministic binding and a focused follow-up
read do the high-risk work.

## 7. Handling the observed strategy failures

Live runs have shown different failure modes for the extraction strategies. They
must not be reported as one generic "model quality" problem.

### Broad sample/test facts

Do not tighten the Draft schema until it rejects useful papers. Keep the value,
Source, candidate references, and missing dimensions. A targeted follow-up may
read the Methods row, table footnote, caption, or test protocol that can close
the edge. If it cannot, stop at a partial revision and exclude that measurement
from strict comparison.

### Boundary-first over-splitting

Do not let the boundary-first prompt allocate one experiment per table,
section, outcome, or model proposal. Treat its output as candidate scopes and
run the same reconciliation rules as every other strategy. Require positive
split evidence and a stable local selector. If a proposed split has no such
evidence, collapse it into a parent view or retain it unresolved; never create a
formal identity solely to satisfy a requested experiment count.

### Merges and omitted conflicts in other strategies

Fact-first and hybrid prompts may return repeated local keys, merge independent
series, or omit a conflicting report when the context is large. The service
must merge only complementary records with the same local identity and
overlapping Source lineage. Different scalar values, incompatible populations,
or incompatible test protocols remain separate records and generate an audit
issue. A repair call should request only the missing row, relation, or conflict
pair; it must not rerun an unbounded whole-paper synthesis.

### Acceptance states

The result of these checks is explicit:

    ready extraction       -> revision + eligible Objective Selection
    partial extraction     -> immutable partial revision only
    abstained extraction   -> no revision unless an auditable candidate exists
    technical failure      -> retryable failure with trace

No strategy is accepted because it returned valid JSON or many measurements.
Benchmark reports must separate raw model counts from service canonicalization
and score at least boundary precision/recall, measurement recall, relation
coverage, conflict recall, Source traceability, and exact binding.

## 8. Writing revisions and selections

ExperimentAnalysisWriter.write_experiment_analysis allocates stable identity
from the reconciled physical scope, reads the latest revision, binds the Draft,
and writes immutable revisions atomically. It does not copy legacy Evidence into
the new graph.

Ready experiment outputs can produce ObjectiveExperimentSelection records.
Partial outputs are persisted for audit and may also create selections for an
exact, source-bound Objective slice. Selection is per Objective slice:
unresolved measurements in the same revision do not block a ready slice, and a
broad measurement cannot enter merely because another result in the revision is
ready. Partial or unknown protocol coverage remains visible as a Finding
limitation.

## 9. Finding synthesis

ExperimentFindingSynthesisService consumes fixed revisions and selections. A
single-paper Finding can read one or more selections directly. A cross-paper
ComparisonGroup is optional and is created only when the selected outcome,
factor endpoints, material/object context, test protocol, and result meaning
are compatible. It organizes the selections; it is not a second fact ledger and
it does not repair an unresolved binding.

The synthesis service preserves agreement, conflict, condition dependence,
association-only relationships, and non-comparability. A Finding cannot be
stronger than the exact measurements and comparisons in its selected revision
set. If no defensible result set exists, the analysis publishes a visible
scientific abstention with the reasons; a provider failure remains retryable.

ExperimentCompatibilityProjection is read-only. It derives existing Objective,
Evidence, and Finding response shapes from the fixed graph without creating a
duplicate scientific-fact store.

## 10. Reproducibility and repair budget

Every revision records the document preparation fingerprint and Source
references used by its content. A supplement, corrected table, or successful
targeted follow-up creates a successor revision; it does not rewrite an earlier
Finding. A repair request is bounded by the extraction budget and must name its
missing target. Repeated inability to close the target is an honest partial or
abstained result, not a reason to invent a value.

## 11. Verification

The nearest focused tests are:

- tests/unit/application/test_paper_experiment_extraction.py
- tests/unit/application/test_paper_experiment_authoring_contract.py
- tests/unit/application/test_experiment_analysis_writer.py
- tests/unit/application/test_experiment_compatibility_projection.py
- tests/unit/application/test_objective_analysis_service.py

The complete acceptance scenario must demonstrate: Source recall, source-local
grounding, broad-fact preservation, exact-binding demotion, positive/negative
boundary decisions, conflict retention, immutable revision writing, and the
absence of a Selection/Finding when the required binding remains unresolved.
