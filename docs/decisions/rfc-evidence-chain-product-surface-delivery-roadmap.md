# RFC Evidence-Chain Product Surface Delivery Roadmap

## Summary

This RFC records the shared delivery order for the next Lens wave that turns
the existing paper-facts and comparable-result backbone into a researcher-
readable evidence-chain product surface.

This page should be treated as the overall cross-module planning entry point
for this wave.

The core judgment is:

- the current semantic backbone is good enough to keep
- the next step is not a new top-level substrate
- the next step is to make one narrow vertical readable as:
  - one paper
  - several variant dossiers
  - several result chains under each dossier
  - several result-series rows when only a test-side axis varies

The first acceptance target for this roadmap is a narrow PBF-metal slice.

This RFC is a shared cross-module delivery guide. It does not replace the
backend API authority, backend Core plan family, or frontend route-family
implementation docs.

## Relationship To Current Docs

Read this RFC with:

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
- [Paper Facts And Comparison Current State](../architecture/paper-facts-and-comparison-current-state.md)
- [RFC Paper-Facts Primary Domain Model and Derived Comparison Views](rfc-paper-facts-primary-domain-model.md)
- [RFC Comparison-Result-Document Product Flow](rfc-comparison-result-document-product-flow.md)
- [RFC Document-Result Evidence-Chain Contract Freeze](rfc-document-result-evidence-chain-contract-freeze.md)

The main module-owned implementation companions are:

- [`../../backend/docs/plans/backend-wide/evidence-chain-product-surface/backend-implementation-plan.md`](../../backend/docs/plans/backend-wide/evidence-chain-product-surface/backend-implementation-plan.md)
- [`../../backend/docs/plans/core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md`](../../backend/docs/plans/core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md)
- [`../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md`](../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md)

This RFC should be used to coordinate the order of delivery across modules.
It should not be used as the backend schema authority or as the frontend page
spec by itself.

## Planning Role

Use this roadmap when the question is:

- what the shared target end state is
- which layer has to be made trustworthy first
- what order backend and frontend work should ship in
- what the narrow-wave acceptance bar is

Use the module-owned companion docs when the question is:

- which backend files and payloads change
- which frontend route surfaces and groupings change
- which local verification commands should run

This roadmap exists to prevent backend and frontend from carrying separate
"master plans" for the same wave.

## Problem

Lens has already moved away from a summary-first reading model.

The current runtime and contracts are already centered on:

`document_profiles -> paper facts family -> comparable_results -> collection_comparable_results -> row projection`

The remaining issue is that this backbone is still not thick enough and not
surfaced clearly enough to satisfy a researcher who needs a full experimental
evidence chain.

Today the main gap is not:

- whether the system has `variant` and `result` objects

The main gap is:

- whether one paper can be projected into stable evidence chains with enough
  process, test, structure, baseline, provenance, and comparability detail to
  support real review and next-step decisions

If the backend and frontend continue to evolve independently, three problems
follow:

1. the backend may add fields without producing a readable drilldown unit
2. the frontend may invent grouping logic that the semantic truth does not
   support
3. the system may look more detailed while still failing the actual research
   job

## Execution Hierarchy

The wave should be understood through four nested units of work.

### 1. Result Chain Is The Foundational Acceptance Unit

The first unit that must become trustworthy is one result chain:

- one variant or sample state
- one test-condition set
- one result or tightly coupled result bundle
- one baseline interpretation
- one support path back to anchors

If this unit is unstable or semantically mixed, every higher grouping will
amplify the error.

### 2. Variant Dossier Groups Stable Chains Inside One Paper

A variant dossier is a paper-local grouping over shared sample or process
state. It is only trustworthy after the child result chains are trustworthy.

### 3. Collection Comparison Aligns Chains Across Papers

Collection comparison is a semantic alignment and assessment layer over many
result chains inside one collection.

It should answer:

- which chains can be compared
- which chains remain limited or blocked
- which missing fields or provenance issues explain the limit

It should not be treated as a replacement for the underlying chain truth.

### 4. Collection Synthesis And Experiment Planning Stay Downstream

Broader material-level synthesis or experiment-planning output may eventually
be added as a higher projection, but it is not the first acceptance target for
this wave.

The first wave succeeds when evidence-chain reconstruction and collection-level
comparison become trustworthy enough that downstream synthesis no longer has to
guess.

## Target End State

The first accepted end state for this roadmap is:

- one narrow materials vertical can be read and reviewed as an evidence-chain
  system rather than as a summary system

In practical terms, that means:

### On The Backend

- `sample_variants`, `test_conditions`, and `measurement_results` are thick
  enough to represent a PBF-metal evidence chain
- value provenance is explicit enough to distinguish reported, derived, and
  estimated values
- comparability assessment reflects real review constraints such as
  orientation, strain rate, baseline type, and missing source parameters
- document and result drilldown can expose grouped dossier and chain
  projections without adding a new permanent top-level artifact family

### On The Frontend

- one document can be read as several variant dossiers
- each dossier can show grouped result chains or result-series rows
- one result page can explain one full evidence chain instead of one isolated
  measurement
- source anchors remain one click away from any chain row

### At The Product Level

- the intended user flow remains:

`workspace -> comparisons -> result detail -> document detail`

- but the result and document pages become evidence-chain reading surfaces
  rather than thin detail shells

## Acceptance Ladder

This wave should be accepted in this order:

1. one result chain is reconstructed honestly and repeatedly
2. one paper can be read as several variant dossiers over those chains
3. one collection can compare those chains without hiding missingness or
   provenance
4. only after the first three are reliable should broader synthesis or
   experiment-planning claims be treated as credible

This ladder is important because collection aggregation is only a useful
projection when the single-chain layer is already stable.

## Delivery Order

The shared delivery order should be:

1. backend fact thickening
2. backend comparability and provenance policy
3. backend grouped drilldown projection
4. frontend document-page dossier and series surface
5. frontend result-page chain surface
6. collection-workspace handoff and end-to-end acceptance

The rest of this RFC explains why this order matters.

### Phase 1: Backend Fact Thickening

Goal:

- make the Core truth thick enough before any UI tries to present evidence
  chains

This phase should add the minimum PBF-metal fact detail needed for:

- shared process or sample state
- test conditions
- structure and characterization support
- value provenance

It should explicitly avoid creating a second semantic backbone.

This phase is done when the backend can distinguish at least:

- process temperature
- test temperature
- characterization temperature
- reported value
- derived value

without forcing the frontend to guess.

### Phase 2: Backend Comparability And Provenance Policy

Goal:

- make collection-scoped judgments reflect real evidence-chain missingness

This phase should tighten `ComparableResult` assessment for the narrow
materials slice, including checks such as:

- missing orientation
- missing strain rate
- unresolved baseline type
- derived energy density without adequate source parameters

This phase is done when a result can be marked `comparable`, `limited`,
`insufficient`, or `not_comparable` for reasons that a domain reviewer would
recognize as meaningful.

### Phase 3: Backend Grouped Drilldown Projection

Goal:

- expose dossier, chain, and series read projections over the existing
  semantic truth

This phase should add grouped drilldown to the existing read paths rather than
replace them with a breaking contract wave.

The main required outputs are:

- document-scoped grouped drilldown
- result-scoped chain context
- explicit provenance and missingness fields for UI use

This phase is done when one paper can be projected into stable dossier and
chain groupings from the current Core truth.

### Phase 4: Frontend Document-Page Dossier And Series Surface

Goal:

- make the document page a real source-reading page with an evidence review
  panel

This phase should introduce:

- paper overview
- variant dossier list
- grouped result series under each dossier
- chain detail drawer
- source-anchor jump actions

This phase is done when a user can inspect one paper and answer:

- which variants exist
- what process or sample state is shared
- which results change only because a test-side axis changes

without leaving the document page.

### Phase 5: Frontend Result-Page Chain Surface

Goal:

- make the result page readable as one evidence chain

This phase should reframe result detail around:

- parent variant dossier
- process or sample state
- test condition
- structure support
- result values
- baseline
- comparability
- provenance
- source anchors

This phase is done when the result page can explain why a value matters before
the user needs to return to the comparison table or source document.

### Phase 6: Collection Handoff And End-To-End Acceptance

Goal:

- make the collection flow coherent from comparison row into evidence-chain
  drilldown

This phase should verify the full path:

`comparison row -> result chain -> source document anchors`

It should also verify that the system can support a first real narrow-vertical
research review rather than only a more detailed looking UI.

## Acceptance Gates

This roadmap should be treated as successful only when all of the following
are true on the narrow target corpus.

### 1. Stable Single-Chain Reconstruction

Given one paper, the system can repeatedly reconstruct:

- the same current-work result chains
- the same parent variant binding
- the same baseline and test-condition binding
- the same source-linked support trail

within normal model variance bounds.

### 2. Honest Missingness

The system reports missing conditions instead of inventing them.

Important examples include:

- missing strain rate
- missing build orientation
- missing baseline type
- missing source parameters for a derived value

### 3. Temperature Semantics Stay Separated

The system does not collapse these into one generic field:

- process temperature
- test temperature
- characterization temperature

### 4. Document Pages Support Variant Review

One document page can support a researcher reviewing:

- the paper's variants
- the result series under each variant
- the supporting source anchors

without falling back to a raw list of unrelated results.

### 5. Collection Comparison Preserves Chain Honesty

Collection comparison groups and filters stable chains without hiding that a
row is limited by:

- missing test context
- missing baseline meaning
- unresolved provenance
- non-comparable sample-state differences

### 6. Result Pages Carry Real Chain Context

One result page can explain:

- what was measured
- under what test condition
- for which variant
- relative to which baseline
- with what structure or characterization support
- with what provenance and comparability warnings

## Boundary Rules

This roadmap should not be misread as permission to:

- add a new permanent `variant_dossiers` artifact family
- treat collection aggregation as a replacement for stable single-chain facts
- turn the frontend into a second semantic owner
- broaden the first delivery wave beyond the narrow proving vertical
- skip comparability and provenance work in favor of presentation polish
- treat experimental planning output as done before evidence-chain
  reconstruction is reliable

## Risks

- the backend may still be too generic in areas outside the first vertical
- grouped drilldown can become unstable if fact thickening is incomplete
- the frontend may overfit to the first materials slice if grouped projections
  are not kept additive and explicit
- cross-module sequencing can drift if module-local plans are updated without
  a shared acceptance conversation

## Adoption Notes

The preferred adoption pattern is:

1. finish the backend-local dossier and chain support slices
2. expose additive grouped drilldown payloads
3. build the frontend document and result reading surfaces against those
   payloads
4. validate the full comparison-to-document path on the narrow corpus
5. only then discuss broader experiment-planning automation

The main point of this order is simple:

- evidence-chain reconstruction must become reliable before downstream
  research-planning claims are treated as trustworthy

## Related Docs

- [RFC Comparison-Result-Document Product Flow](rfc-comparison-result-document-product-flow.md)
- [RFC Paper-Facts Primary Domain Model and Derived Comparison Views](rfc-paper-facts-primary-domain-model.md)
- [`../../backend/docs/plans/backend-wide/evidence-chain-product-surface/backend-implementation-plan.md`](../../backend/docs/plans/backend-wide/evidence-chain-product-surface/backend-implementation-plan.md)
- [`../../backend/docs/plans/core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md`](../../backend/docs/plans/core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md)
- [`../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md`](../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md)
