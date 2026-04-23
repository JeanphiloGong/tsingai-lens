# RFC Paper-Facts Primary Domain Model and Derived Comparison Views

## Summary

This RFC proposes changing the primary Lens domain model from a claim-centered
`evidence_cards` backbone to a paper-facts family that can support both:

- single-paper fact inspection
- cross-paper comparison

The core decision is simple:

- primary domain objects should represent durable paper facts
- `comparison_rows` should be derived from those facts
- `evidence_cards` should become a reader-facing evidence view rather than the
  primary research object

This RFC does not reject the Lens v1 comparison-first product goal. It argues
that the comparison-first product goal depends on a first-class paper-facts
layer rather than competing with it.

## Relationship To Current Docs

This RFC should be read after the current-state note:

- [Paper Facts And Comparison Current State](../architecture/paper-facts-and-comparison-current-state.md)

The current shared product boundary remains defined by:

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens Mission and Positioning](../overview/lens-mission-positioning.md)

The current shared artifact contracts and architecture boundary still reflect a
stronger claim-centered backbone:

- [Lens Core Artifact Contracts](../contracts/lens-core-artifact-contracts.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)

This RFC proposes the next reconciliation step. It should not be treated as
the current source of truth until the repository accepts the change and updates
the shared contracts and architecture docs.

## Context

Lens v1 is correctly positioned as a comparison-first, evidence-first
literature intelligence system for research collections rather than a
single-paper summary tool.

That product goal does not remove the need for a paper-facts layer. It makes
that layer more important.

In practical product terms, Lens needs both:

1. a single-paper facts surface that tells the user what one paper says about
   samples, methods, conditions, baselines, properties, and results
2. a comparison surface that tells the user which extracted results can be
   inspected side by side without misleading them

The current repository has drifted into a hybrid state:

- shared contracts still define `evidence_cards` as the core research object
- the materials comparison direction already relies more heavily on
  `sample_variants`, `measurement_results`, `test_conditions`, and
  `baseline_references`
- runtime comparison assembly already behaves more like a
  sample-and-result-backed system than a direct evidence-card projection

This creates two kinds of instability:

- the system does not clearly expose a first-class paper-facts model
- `evidence_cards` is overloaded as claim object, evidence browser, traceback
  entry, and compatibility layer

## Problem Statement

The current object model makes one central mistake:

- it treats the reader-facing evidence card too much like the primary research
  fact

That is not a stable fit for materials comparison work.

In this domain, comparison depends on:

- what the sample actually is
- how it was processed or prepared
- which characterization or test methods were used
- which property was measured
- under which condition it was measured
- which baseline or control it is compared against
- where the supporting source evidence lives

Those are paper facts. They are not all reducible to one claim-bearing card.

If the system keeps treating `evidence_cards` as the primary research object,
it will continue to mix:

- domain facts
- UI display shells
- traceback views
- comparison support bundles

That mixture makes extraction, normalization, UI design, and evaluation harder
than they need to be.

## Proposed Change

### 1. Declare A Paper-Facts Family As The Primary Domain Model

Lens should treat the following family as the primary paper-facts layer:

- `document_profiles`
- `sample_variants`
- `method_facts`
- `test_conditions`
- `baseline_references`
- `measurement_results`
- `characterization_observations`
- `evidence_anchors`
- `structure_features` as optional enrichment

These objects should represent what the system believes a paper contains in a
durable, inspectable, and comparable form.

### 2. Define The Role Of Each Primary Object

#### `document_profiles`

Role:

- coarse routing only
- document type and suitability signaling
- collection-level warning support

This object should remain tightly controlled and enum-like. It should not
become a free-form summary layer.

#### `sample_variants`

Role:

- identify the sample or experimental variant that later results belong to
- retain the material or host-system context needed for comparison
- preserve the variable axis and variant definition when present

#### `method_facts`

Role:

- preserve paper-level method facts in a first-class way
- separate process, characterization, and test methods

Recommended minimum field family:

- `method_id`
- `document_id`
- `collection_id`
- `method_role`
  Allowed values should begin with `process | characterization | test`
- `method_name`
- `method_payload`
- `evidence_anchor_ids`
- `confidence`

This object is necessary because users need to see what methods a paper used,
not only which claims or results were later inferred from those methods.

#### `test_conditions`

Role:

- preserve the condition context that constrains where a result holds
- keep condition payloads structured rather than flattened into one opaque
  summary string

#### `baseline_references`

Role:

- preserve explicit baseline or control semantics
- distinguish within-paper controls, process baselines, literature benchmarks,
  and similar baseline types

#### `measurement_results`

Role:

- act as the main result object for comparison
- preserve property identity, value shape, units, traceability, and links to
  sample, condition, baseline, and evidence

This is the main comparison input object, not a secondary projection.

#### `characterization_observations`

Role:

- preserve characterization findings as first-class facts rather than leaving
  them as incidental prose

#### `evidence_anchors`

Role:

- unify the traceback surface across paper facts and derived views
- preserve span, section, table, figure, page, or equivalent source hooks

#### `structure_features`

Role:

- provide optional structure-level enrichment for materials reasoning when the
  evidence is strong enough

This object should not block the first stable paper-facts backbone unless the
active corpus requires it on the critical path.

### 3. Define Derived Views Explicitly

The following should be treated as derived views rather than primary domain
objects:

- `comparison_rows`
- `evidence_cards`
- paper-level reader panels or summaries

#### `comparison_rows`

`comparison_rows` should be a deterministic comparison view assembled from
paper facts. A comparison row is not a first-pass extraction object.

Its inputs should be:

- one `measurement_result`
- its linked `sample_variant`
- its linked `test_condition` when resolved
- its linked `baseline_reference` when resolved
- relevant characterization or structure context when available
- evidence support and traceback anchors
- assessment outputs such as comparability warnings and missing context

#### `evidence_cards`

`evidence_cards` should become an evidence-facing or reader-facing projection.

Recommended role:

- traceback entry
- narrow claim inspection view
- evidence-oriented reading support

`evidence_cards` should no longer be treated as the only primary research
object in the system.

### 4. Separate Extraction From Projection

The extraction layer should first produce paper facts only.

The view layer should then derive:

- `comparison_rows`
- `evidence_cards`
- paper facts panels
- warnings and summary views

This separation prevents one service from trying to act as:

- fact extractor
- UI shaper
- comparison engine
- compatibility adapter

at the same time.

### 5. Clarify The Source/Core Boundary

Source should hand Core neutral structured inputs such as:

- documents
- blocks or chunks
- tables or rows
- raw anchorable spans

Source may still provide operationally useful structure, but it should not own
the final research-fact meaning.

Core should own:

- paper-facts extraction
- normalization
- result linkage
- comparison assembly

### 6. Treat `structure_features` As Phase-2 Enrichment By Default

Unless the active corpus proves that structure-level interpretation is required
on the phase-1 critical path, `structure_features` should remain an enrichment
layer rather than a blocker for the main facts backbone.

This keeps the system focused on stabilizing:

- sample identity
- methods
- conditions
- baselines
- results
- evidence anchors

before expanding harder interpretation layers.

## Recommended Data Flow

The recommended flow becomes:

1. ingest documents into a collection
2. build neutral source artifacts and anchors
3. build `document_profiles`
4. extract `paper facts family`
5. normalize terms, units, links, and aliases
6. assemble `comparison_rows`
7. derive `evidence_cards` and reader-facing evidence views
8. run protocol or other downstream branches only when suitable

This preserves the comparison-first product goal while putting the correct
domain facts underneath it.

## Non-Goals

This RFC does not propose:

- removing evidence browsing from Lens
- removing traceback or claim inspection behavior
- forcing a full phase-1 ontology for every future scientific domain
- deciding the exact final API payload for every new artifact
- deciding every storage column name in this document

It also does not propose:

- turning Lens into a single-paper summary product
- replacing the comparison workspace as the primary Lens v1 acceptance surface

## Migration Guidance

The recommended migration sequence is:

### Stage 1: Freeze Contract Drift

- stop expanding `evidence_cards` into more domain responsibilities
- keep `document_profiles` tightly constrained
- avoid adding new permanent features that assume cards are the only primary
  research object

### Stage 2: Promote Paper Facts

- introduce or formalize `method_facts`
- formalize `evidence_anchors`
- make the extraction stage produce paper facts before view objects

### Stage 3: Rebuild Derived Views

- make `comparison_rows` a facts-derived view only
- rebuild `evidence_cards` as a projection over facts plus anchors

### Stage 4: Update Shared Contracts

- rewrite the shared artifact contracts and architecture boundary so they
  describe:
  - the paper-facts family
  - derived comparison views
  - derived evidence views

## Verification

This direction is successful when the system can demonstrate all of the
following:

- a user can inspect one paper's samples, methods, conditions, baselines, and
  results without reconstructing them from evidence cards manually
- a result shown in comparison rows is always traceable back to the supporting
  paper facts and source anchors
- comparison assembly does not depend on cards as the only semantic source
- `document_profiles` remains a strict routing and warning layer
- evidence browsing still works, but it no longer dictates the whole domain
  model

## Risks

This change will require coordinated updates across:

- shared contracts
- backend extraction and normalization
- comparison assembly
- evidence browsing APIs
- frontend information architecture

The main implementation risk is partial migration, where facts, cards, and
comparison rows all continue to hold overlapping semantics for too long.

That risk is still lower than preserving the current ambiguity indefinitely.

## Related Docs

- [Paper Facts And Comparison Current State](../architecture/paper-facts-and-comparison-current-state.md)
- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens Core Artifact Contracts](../contracts/lens-core-artifact-contracts.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
- [Lens Evidence-First Direction and Conditional Protocol Generation](rfc-evidence-first-literature-parsing.md)
- [Materials Comparison V2 Plan](../../backend/docs/plans/backend-wide/materials-comparison-v2-plan.md)
