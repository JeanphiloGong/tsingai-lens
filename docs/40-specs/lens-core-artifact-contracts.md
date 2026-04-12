# Lens Core Artifact Contracts

## Scope

This document defines the minimum shared contracts for the three core Lens v1
artifacts:

- `document_profiles`
- `evidence_cards`
- `comparison_rows`

These contracts exist to keep the evidence backbone strict before backend and
frontend implementations spread across more surfaces.

This document does not define:

- storage engine details
- final API payload shapes
- every optional derived field

## Business Flow Interpretation

These artifact contracts describe the main Lens v1 business flow rather than a
protocol-first extraction flow.

In business terms, the system should work like this:

1. papers enter a collection
2. `document_profiles` decides how each paper should be treated
3. `evidence_cards` stores the core research judgment units for each paper
4. `comparison_rows` turns those evidence units into collection-facing
   comparison rows
5. `protocol_candidates` and `protocol_steps` are optional downstream outputs
   used only when the source material is suitable

In that flow:

- `document_profiles` is the gating layer
- `evidence_cards` is the core research object layer
- `comparison_rows` is the primary collection-facing workspace layer
- `protocol_*` artifacts are downstream branches rather than the business
  backbone

Lens v1 therefore organizes papers into research objects that are comparable,
traceable, and reviewable before it decides whether any protocol-like output
should exist.

## Contract Rules

The following rules apply across all three artifacts:

- required fields cannot be omitted silently
- enumerated states must stay explicit rather than collapsing into vague text
- traceability fields must exist even when the status is partial or weak
- downstream artifacts must declare their upstream dependency

## Document Profiles

### Role

`document_profiles` decides document type, protocol suitability, and early
collection-level gating.

Collection-level suitability states should be derived from
`document_profiles` rather than introduced as an unrelated parallel source of
truth.

### Minimum Required Fields

- `document_id`
- `collection_id`
- `doc_type`
  Allowed values: `experimental | review | mixed | uncertain`
- `protocol_extractable`
  Allowed values: `yes | partial | no | uncertain`
- `protocol_extractability_signals`
  Must expose the current reasons or signals behind the decision.
- `parsing_warnings`
- `confidence`

### Field Semantics

| Field | Purpose | Notes |
| --- | --- | --- |
| `document_id` | Unique identity for one source document | Used to bind the profile to downstream evidence and comparison artifacts |
| `collection_id` | Binds the profile to the collection that owns the document | Keeps profiling collection-scoped rather than global |
| `doc_type` | Stores the document's coarse literature type | Drives downstream routing, warnings, and suitability decisions |
| `protocol_extractable` | Stores whether protocol derivation is likely to be usable | Should not collapse into a bare boolean because partial or uncertain cases matter |
| `protocol_extractability_signals` | Preserves the concrete reasons behind the protocol judgment | Makes gating explainable instead of opaque |
| `parsing_warnings` | Carries early warnings about ambiguity, missing structure, or review contamination | Should be surfaced to workspace and downstream review flows |
| `confidence` | Stores the system's confidence in the profile judgment | Helps distinguish firm routing from weak heuristics |

### Document Type Semantics

- `experimental`
  The document is primarily methods- and results-bearing and is suitable for
  evidence extraction with stronger procedural potential.
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

### Signal Expectations

`protocol_extractability_signals` should preserve explicit signals such as:

- methods density
- procedural continuity
- condition completeness
- critical parameter missingness
- review contamination

### Upstream And Downstream

- Upstream: raw documents and parsed text/layout units
- Downstream: workspace suitability messaging, protocol gating, and comparison
  quality review

### Missingness Rules

- `doc_type` and `protocol_extractable` may be uncertain, but they may not be
  omitted
- `parsing_warnings` may be empty, but the field must exist

## Evidence Cards

### Role

`evidence_cards` is the primary claim-centered evidence artifact in Lens v1.

Each card has one primary claim-bearing unit and one or more supporting
evidence anchors plus its associated condition context.

An evidence card is therefore a claim object with evidence attached, not an
evidence cluster with claims attached.

The same evidence anchor may support more than one evidence card when multiple
distinct claims depend on the same figure, table, method, or text span.

### Minimum Required Fields

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
| `evidence_id` | Unique identity for one evidence card | Used by comparison rows, traceback, and review workflows |
| `document_id` | Binds the card to its source document | Supports source inspection and paper-level grouping |
| `collection_id` | Binds the card to the owning collection | Keeps evidence objects aligned with collection-level workflows |
| `claim_text` | Stores the claim-bearing text or normalized claim statement | This is the central meaning-bearing payload of the card |
| `claim_type` | Classifies what kind of claim this is | Helps separate property, mechanism, process, or qualitative claims |
| `evidence_source_type` | Stores what kind of source supports the claim | Important for judging evidence strength and UI presentation |
| `evidence_anchors` | Points back to spans, figures, tables, or methods sections | This is the main traceback hook |
| `material_system` | Records the material system or composition discussed by the claim | Needed for later normalization and comparison |
| `condition_context` | Records the process, baseline, and test context that constrain the claim | Prevents the claim from floating free of its conditions; should not collapse into one opaque blob |
| `confidence` | Stores the system's confidence in the card | Helps downstream ranking and review |
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
  The card exists as a provisional extraction, but it should not be treated as
  well-grounded evidence until traceback improves.

### Recommended Normalized Fields

These fields should be present whenever the source supports them:

- `property_metric`
- `value`
- `unit`
- `test_conditions`
- `baseline`

### Upstream And Downstream

- Upstream: document profiles and parsed source units
- Downstream: comparison row generation, traceback UI, and protocol candidate
  derivation

### Missingness Rules

- an evidence card may omit numeric `value` or `unit` when the claim is
  qualitative
- an evidence card may not omit `claim_text`, `evidence_source_type`,
  `evidence_anchors`, or `traceability_status`

## Comparison Rows

### Role

`comparison_rows` is the primary collection-facing comparison artifact in Lens
v1.

Each row represents one normalized result or claim candidate ready for
collection-level inspection. It is not a pairwise comparison object.

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
| `source_document_id` | Preserves which document produced the normalized row | Supports source filtering and paper-level drill-down |
| `supporting_evidence_ids` | Anchors the row to the evidence cards that justify it | Prevents the row from becoming an ungrounded summary |
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

Comparability judgments may be:

- rule-derived
- model-derived
- hybrid

That provenance should remain inspectable so the system can explain whether a
row was limited by explicit normalization rules, model judgment, or both.

### Recommended Value Fields

- `value`
- `unit`

### Upstream And Downstream

- Upstream: evidence cards and document profiles
- Downstream: collection comparison workspace, conflict review, and derived
  graph or report views

### Missingness Rules

- a comparison row may omit `value` or `unit` when the source claim is
  qualitative
- a row may not be labeled `comparable` if its normalized baseline or test
  condition is missing or contradicted
- `comparability_status` and `comparability_warnings` must always be present

## Dependency Rule

The Lens v1 backbone should flow in this order:

1. `document_profiles`
2. `evidence_cards`
3. `comparison_rows`

`protocol_candidates` and `protocol_steps` are downstream branches and should
not bypass this backbone.

## Related Docs

- [Lens Mission and Positioning](../50-guides/lens-mission-positioning.md)
- [Lens V1 Definition](lens-v1-definition.md)
- [Lens V1 Architecture Boundary](../30-architecture/lens-v1-architecture-boundary.md)
- [Backend Evidence-First Parsing Refactor Plan](../../backend/docs/plans/evidence-first-parsing-plan.md)
