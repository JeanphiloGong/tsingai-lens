# Lens Core Artifact Contracts

## Scope

This document defines the minimum shared contracts for the Lens v1 Core
artifacts after the paper-facts domain-model correction.

The shared contract now distinguishes between:

- primary domain artifacts:
  - `document_profiles`
  - the `paper_facts` family
- derived Core views:
  - `comparison_rows`
  - `evidence_cards`

This document does not define:

- storage engine details
- final API payload shapes
- every optional derived field

For the decision that changed Lens from an evidence-card-centered primary model
to a paper-facts-centered primary model, read
[`rfc-paper-facts-primary-domain-model.md`](../decisions/rfc-paper-facts-primary-domain-model.md).

## Business Flow Interpretation

These contracts describe the main Lens v1 business flow rather than a
protocol-first extraction flow.

In business terms, the system should work like this:

1. papers enter a collection
2. `document_profiles` decides coarse document routing and warnings
3. the Core extracts the `paper_facts` family for each paper
4. `comparison_rows` turns those facts into collection-facing comparison views
5. `evidence_cards` turns those facts into traceback-ready reader views
6. `protocol_candidates` and `protocol_steps` remain optional downstream
   outputs used only when the source material is suitable

In that flow:

- `document_profiles` is the coarse routing layer
- the `paper_facts` family is the primary research object layer
- `comparison_rows` is the primary collection-facing comparison view
- `evidence_cards` is an evidence-facing and traceback-facing projection
- `protocol_*` artifacts are downstream branches rather than the business
  backbone

Lens v1 therefore organizes papers into durable paper facts first, then builds
comparison and evidence views over those facts.

## Contract Rules

The following rules apply across the Core artifact set:

- primary domain objects must represent durable paper facts rather than only
  UI-facing summaries
- derived views must declare the primary objects they depend on
- required fields cannot be omitted silently
- enumerated states must stay explicit rather than collapsing into vague text
- traceability fields must exist even when the status is partial or weak

## Document Profiles

### Role

`document_profiles` decides document type, protocol suitability, and early
collection-level gating.

Collection-level suitability states should be derived from
`document_profiles` rather than introduced as an unrelated parallel source of
truth.

`document_profiles` is not a paper-summary layer. It is a coarse routing and
warning object.

### Minimum Required Fields

- `document_id`
- `collection_id`
- `doc_type`
  Allowed values: `experimental | review | mixed | uncertain`
- `protocol_extractable`
  Allowed values: `yes | partial | no | uncertain`
- `protocol_extractability_signals`
- `parsing_warnings`
- `confidence`

### Field Semantics

| Field | Purpose | Notes |
| --- | --- | --- |
| `document_id` | Unique identity for one source document | Used to bind the profile to downstream fact and view artifacts |
| `collection_id` | Binds the profile to the collection that owns the document | Keeps profiling collection-scoped rather than global |
| `doc_type` | Stores the document's coarse literature type | Drives downstream routing, warnings, and suitability decisions |
| `protocol_extractable` | Stores whether protocol derivation is likely to be usable | Should not collapse into a bare boolean because partial or uncertain cases matter |
| `protocol_extractability_signals` | Preserves the controlled reasons behind the protocol judgment | May remain empty in narrow triage waves, but when populated it must stay enum-like rather than free-form |
| `parsing_warnings` | Carries early warnings about ambiguity, missing structure, or review contamination | Should be surfaced to workspace and downstream review flows |
| `confidence` | Stores the system's confidence in the profile judgment | Helps distinguish firm routing from weak heuristics |

### Document Type Semantics

- `experimental`
  The document is primarily methods- and results-bearing and is suitable for
  deeper paper-facts extraction.
- `review`
  The document is primarily synthetic or narrative and should not be treated as
  a default protocol source.
- `mixed`
  The document contains both evidence-bearing experimental content and broader
  review or discussion content.
- `uncertain`
  The system cannot yet classify the document with enough confidence for a
  stronger routing decision.

### Protocol Extractability Semantics

- `yes`
  The document likely contains enough procedural continuity and condition
  completeness to justify protocol derivation.
- `partial`
  Some procedural content is present, but critical steps, parameters, or
  continuity may be missing.
- `no`
  The document should not be used as a protocol source.
- `uncertain`
  The system does not yet have enough signal to make a reliable protocol
  routing decision.

### Upstream And Downstream

- Upstream: raw documents and parsed text/layout units
- Downstream: workspace suitability messaging, protocol gating, and fact-layer
  extraction routing

### Missingness Rules

- `doc_type` and `protocol_extractable` may be uncertain, but they may not be
  omitted
- `parsing_warnings` may be empty, but the field must exist

## Paper Facts Family

### Role

The `paper_facts` family is the primary Lens research object layer.

It should preserve what one paper says about:

- samples or variants
- methods
- conditions
- baselines
- measurements or results
- characterization findings
- evidence anchors
- optional structure-level enrichment

The minimum shared family members are:

- `sample_variants`
- `method_facts`
- `test_conditions`
- `baseline_references`
- `measurement_results`
- `characterization_observations`
- `evidence_anchors`
- `structure_features` as optional enrichment

### Common Contract Rules

Every primary fact object should preserve:

- a stable object id
- `document_id`
- `collection_id`
- traceability back to source anchors or source-locator fields
- `confidence`

Whenever the object is normalized or inferred rather than directly copied from
the paper, it should also preserve an explicit epistemic or derivation status.

### Family Member Roles

- `sample_variants`
  Identifies the sample or experimental variant that later facts belong to.
- `method_facts`
  Preserves process, characterization, and test methods as first-class facts.
- `test_conditions`
  Preserves structured condition payloads rather than flattening them into one
  opaque summary string.
- `baseline_references`
  Preserves explicit control or baseline semantics.
- `measurement_results`
  Acts as the main comparison input object and preserves links to sample,
  condition, baseline, and evidence.
- `characterization_observations`
  Preserves characterization findings as first-class facts rather than
  incidental prose.
- `evidence_anchors`
  Preserves the shared traceback surface across facts and derived views.
- `structure_features`
  Adds optional structure-level enrichment when the evidence is strong enough.

### Family Dependency Rule

The `paper_facts` family should be extracted before comparison and evidence
views are assembled.

No single derived view may become the only semantic source of truth for those
facts.

## Evidence Cards

### Role

`evidence_cards` is a derived evidence-facing and reader-facing view in Lens
v1.

An evidence card may present one narrow claim, observation, or result-focused
reading unit, but that unit should be understood as a projection over paper
facts plus anchors rather than the only primary research object in the system.

The same evidence anchor or the same fact may support more than one evidence
card when multiple reader-facing views are useful.

### Minimum Required Fields

The current shared compatibility surface should preserve:

- `evidence_id`
- `document_id`
- `collection_id`
- `claim_text`
- `claim_type`
- `evidence_source_type`
  Allowed values should distinguish at least `figure | table | method | text`
- `evidence_anchors`
- `material_system`
- `condition_context`
- `confidence`
- `traceability_status`

### Field Semantics

| Field | Purpose | Notes |
| --- | --- | --- |
| `evidence_id` | Unique identity for one evidence card | Used by UI selection, traceback, and narrow evidence review workflows |
| `document_id` | Binds the card to its source document | Supports source inspection and paper-level grouping |
| `collection_id` | Binds the card to the owning collection | Keeps evidence views aligned with collection-level workflows |
| `claim_text` | Stores the card's reader-facing claim or summary phrase | This is a display-oriented meaning shell, not the only canonical research fact |
| `claim_type` | Classifies what kind of reader-facing unit this is | Helps separate property, mechanism, process, or qualitative views |
| `evidence_source_type` | Stores what kind of source supports the card | Important for judging evidence strength and UI presentation |
| `evidence_anchors` | Points back to spans, figures, tables, or methods sections | This is the main traceback hook |
| `material_system` | Records the material system discussed by the card | Useful for reader orientation, but canonical sample identity should still live in paper facts |
| `condition_context` | Records process, baseline, and test context shown on the card | This should be derived from structured facts rather than invented as one opaque blob |
| `confidence` | Stores the system's confidence in the card projection | Helps downstream ranking and review |
| `traceability_status` | States whether the card has usable evidence anchors | Keeps downstream consumers from assuming all cards are equally grounded |

### Condition Context Structure

`condition_context` may be stored as a structured object, but it should
preserve distinct subfields rather than becoming one opaque JSON blob.

When available, it should separately retain:

- process or treatment context
- baseline or control context
- test or measurement context

### Evidence Source Type Semantics

`evidence_source_type` should distinguish at least:

- `figure`
- `table`
- `method`
- `text`

More granular subtypes may be added later, but these distinctions should
survive normalization.

### Traceability Status Semantics

- `direct`
  The card is anchored to clear source evidence such as figure, table, or span
  references.
- `partial`
  The card has some traceback signal, but the anchor is incomplete or weak.
- `missing`
  The card exists as a provisional projection, but it should not be treated as
  well-grounded evidence until traceback improves.

### Recommended Linkage Fields

When the runtime is ready, evidence cards should also preserve linkage back to
the primary fact layer, for example:

- `related_fact_ids`
- `sample_variant_ids`
- `measurement_result_ids`

### Upstream And Downstream

- Upstream: paper facts plus evidence anchors
- Downstream: traceback UI, narrow claim inspection, evidence-oriented reading,
  and protocol candidate derivation

### Missingness Rules

- an evidence card may omit numeric `value` or `unit` when the projected view
  is qualitative
- an evidence card may not omit `claim_text`, `evidence_source_type`,
  `evidence_anchors`, or `traceability_status`

## Comparison Rows

### Role

`comparison_rows` is the primary collection-facing comparison artifact in Lens
v1.

Each row represents one normalized result candidate derived from paper facts.
It is not a pairwise comparison object.

Each row should be understood as a deterministic comparison view assembled
over:

- one measurement-result-like fact
- its linked sample identity
- its linked test condition when resolved
- its linked baseline when resolved
- its supporting evidence and traceback anchors
- comparability assessment outputs

### Minimum Required Fields

- `row_id`
- `collection_id`
- `source_document_id`
- `supporting_evidence_ids`
- `material_system_normalized`
- `process_normalized`
- `property_normalized`
- `baseline_normalized`
- `test_condition_normalized`
- `comparability_status`
  Allowed values: `comparable | limited | not_comparable | insufficient`
- `comparability_warnings`

### Field Semantics

| Field | Purpose | Notes |
| --- | --- | --- |
| `row_id` | Unique identity for one comparison row | Used by UI selection, pagination, sorting, and traceback jumps |
| `collection_id` | Binds the row to one collection-level comparison workspace | Comparison rows are collection-scoped rather than global |
| `source_document_id` | Preserves which document produced the row | Supports source filtering and paper-level drill-down |
| `supporting_evidence_ids` | Anchors the row to traceback-ready evidence views that justify it | Prevents the row from becoming an ungrounded summary while public compatibility still uses evidence ids |
| `material_system_normalized` | Normalizes the material system into a comparison-ready label | Used to group or filter rows that refer to the same system family |
| `process_normalized` | Normalizes the process or treatment route | Keeps fabrication or treatment differences explicit during comparison |
| `property_normalized` | Normalizes the property or metric being discussed | Ensures the workspace compares the same type of result |
| `baseline_normalized` | Normalizes the control or baseline the result is measured against | Critical for deciding whether an apparent improvement is truly comparable |
| `test_condition_normalized` | Normalizes the conditions under which the result was measured | Prevents results from being compared without accounting for test context |
| `comparability_status` | Stores the system's coarse judgment about whether the row can be directly compared | Drives default ranking, filtering, and warning treatment in the workspace |
| `comparability_warnings` | Stores the explicit reasons why comparability is limited or blocked | Used to explain the status instead of showing a bare label |

### Comparability Status Semantics

- `comparable`
  Safe to include in the primary comparison view without a major comparability
  warning.
- `limited`
  Still useful to inspect, but only with visible caveats because some context
  is incomplete or only partially aligned.
- `not_comparable`
  Should not be presented as a directly comparable result because key baseline,
  condition, or normalization constraints are violated.
- `insufficient`
  The source material does not provide enough information to judge
  comparability reliably.

### Comparability Judgment Provenance

Comparability judgments should remain inspectable.

The default expectation is deterministic or rule-derived assessment over the
fact layer. If any hybrid judgment is later introduced, the basis must still
remain explicit and reviewable.

### Recommended Value Fields

- `value`
- `unit`

### Upstream And Downstream

- Upstream: paper facts, document profiles, and traceback-ready evidence views
- Downstream: collection comparison workspace, conflict review, and derived
  graph or report views

### Missingness Rules

- a comparison row may omit `value` or `unit` when the source result is
  qualitative
- a row may not be labeled `comparable` if its normalized baseline or test
  condition is missing or contradicted
- `comparability_status` and `comparability_warnings` must always be present

## Dependency Rule

The Lens v1 Core flow should follow this order:

1. `document_profiles`
2. the `paper_facts` family
3. `comparison_rows`
4. `evidence_cards`

`protocol_candidates` and `protocol_steps` are downstream branches and should
not bypass this flow.

## Related Docs

- [Lens Mission and Positioning](../overview/lens-mission-positioning.md)
- [Lens V1 Definition](lens-v1-definition.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
- [RFC Paper-Facts Primary Domain Model and Derived Comparison Views](../decisions/rfc-paper-facts-primary-domain-model.md)
- [Backend Evidence-First Parsing Refactor Plan](../../backend/docs/plans/historical/evidence-first-parsing-plan.md)
