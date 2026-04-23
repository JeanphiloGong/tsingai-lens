# RFC Comparison-Result-Document Product Flow

## Summary

This RFC records a shared product-direction correction for the collection
workspace after the paper-facts and comparable-result decisions.

The core judgment is:

- the collection workspace should remain comparison-first at the user-facing
  entry surface
- `Result` should become the core product object that users drill into from a
  comparison row
- `Document` should remain the source-of-truth page that users return to for
  verification and original context
- `Evidence` should remain essential, but it should primarily appear inside
  result and document drill-down flows rather than as the main collection
  navigation center
- backend-internal `ComparableResult` and `CollectionComparableResult` should
  remain internal semantic substrate names rather than the main product-facing
  names

In practical terms, the intended user-facing flow is:

`workspace -> comparisons -> result detail -> document detail`

This RFC is a shared product and contract direction. It does not replace the
current backend API authority or frontend route-level implementation docs.

## Relationship To Current Docs

This RFC should be read with:

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
- [Paper Facts And Comparison Current State](../architecture/paper-facts-and-comparison-current-state.md)
- [RFC Paper-Facts Primary Domain Model and Derived Comparison Views](rfc-paper-facts-primary-domain-model.md)
- [RFC Comparable-Result Substrate and Materials Database Direction](rfc-comparable-result-substrate-and-materials-database-direction.md)

Implementation companions remain module-owned:

- [`../backend/docs/specs/api.md`](../../backend/docs/specs/api.md)
- [`../frontend/src/routes/collections/lens-v1-interface-spec.md`](../../frontend/src/routes/collections/lens-v1-interface-spec.md)

This RFC should not be used to silently treat raw
`/api/v1/comparable-results` payloads as the final product-facing page model.

## Context

Lens v1 is correctly positioned as a collection-first, evidence-backed
comparison workspace.

That part is not changing.

What has changed is the shape of the internal semantic backbone.

The repository now has a clearer separation between:

- document-grounded paper facts
- reusable comparable-result semantics
- collection-scoped assessment
- row and card projections

At the same time, the user-facing collection experience still carries older
assumptions:

- `Evidence` is still treated too much like a top-level main object
- the comparison table still risks becoming both the analysis page and the
  only readable fact page
- raw `ComparableResult` payloads can look tempting as a direct new page model
- the product still lacks one stable answer to the question:
  "what is the core thing a user opens when a comparison row looks important?"

The missing answer is a product-facing `Result`.

## Problem Statement

If the shared product flow stays underspecified, four problems follow.

### 1. The Main Drill-Down Object Stays Ambiguous

Users can see comparison rows and evidence traces, but there is still no
cleanly named product object that answers:

- what exactly was extracted
- under what condition
- relative to which baseline
- with what evidence

That makes the comparison row carry too much product meaning by itself.

### 2. `Evidence` Stays Over-Central In Navigation

Evidence is essential to trust, but it is not the main unit of work a user is
usually judging in the collection workspace.

The main judgment is usually:

- which results are comparable
- what each result actually means
- whether the source paper supports that reading

If evidence remains a first-class navigation center, the product can keep
overweighting trace snippets relative to the result object they are supposed
to support.

### 3. Internal Semantic Names Can Leak Into Product Language

`ComparableResult` is an appropriate internal name for the semantic substrate.

It is not a good primary product name for most users.

If the repository exposes that name directly at the UI and main API layer, the
product language will start inheriting internal implementation concerns such as
binding payloads, normalization payloads, and scoped overlays.

### 4. `Material` Can Be Mistaken For The Main Product Object

In the first vertical, materials are a primary indexing and filtering
dimension.

They are not the whole object a researcher is judging.

The product object is a result about a material under some condition, with
some baseline and evidence support.

The shared product name therefore should be `Result`, not `Material`.

## Proposed Direction

### 1. Keep `Comparisons` As The Primary Collection Analysis Surface

The collection comparison page should remain the primary user-facing analysis
surface.

That page answers:

- which results can be placed side by side
- which results remain limited or blocked
- why the current comparability judgment was assigned

This keeps Lens aligned with the Lens v1 boundary that comparison, not generic
chat or generic document reading, is the primary collection job.

### 2. Introduce `Result` As The Core Product Object

The main drill-down object should be `Result`.

That page answers:

- what was extracted
- what property and value were reported
- which material or variant it refers to
- what baseline and test condition were bound
- what evidence supports it
- what the current collection thinks about its comparability

The product-facing `Result` is not a new replacement for the internal
comparable-result substrate. It is a product projection over that substrate.

### 3. Treat `Document` As The Source-Of-Truth Verification Surface

The document page should remain the place users return to when they need to:

- inspect original context
- read quoted or anchored source passages
- confirm how a result was grounded in the paper
- see what else was extracted from the same paper

In other words, the document page is the verification and source-recovery
surface, not the main collection analysis surface.

### 4. Treat `Evidence` As A Support Layer

Evidence remains essential because Lens is evidence-backed.

But the main product hierarchy should understand evidence as support for
result and comparison judgments rather than as the primary collection object.

The preferred experience is:

- open a comparison row
- inspect the result
- inspect supporting evidence
- return to the document when deeper source verification is needed

### 5. Keep The Internal Semantic Backbone Intact

This RFC does not propose undoing the current internal semantic direction.

The internal backbone should continue to be understood as:

`paper facts -> ComparableResult -> CollectionComparableResult -> ComparisonRow`

That layered interpretation remains useful because it separates:

- reusable semantic result identity
- collection-scoped assessment
- presentation-specific projections

## Product Surface Model

The shared product surface should be interpreted through four layers.

### Documents

`Documents` answer:

- which papers are in the collection
- which papers are experimental, review, mixed, or uncertain
- which extracted results came from a given paper

### Results

`Results` answer:

- what extracted results exist in this collection
- what each result says
- what context and evidence are attached to it

### Comparisons

`Comparisons` answer:

- which results can be compared inside this collection
- which warnings or missing context prevent stronger judgments

### Evidence

`Evidence` answers:

- why a result or comparison should be trusted
- where the supporting anchors live

The key product distinction is:

- `Results` are the core object layer
- `Comparisons` are the main analysis view
- `Documents` are the source verification layer
- `Evidence` is the support layer

## User Workflow

Two different orderings must be kept explicit.

### Semantic Build Order

The system still builds knowledge in this order:

`documents -> results -> comparisons`

That is a semantic dependency order, not a UI recommendation.

### Frontend Primary Workflow

The recommended user flow should be:

`workspace -> comparisons -> result detail -> document detail`

This is the right product flow because users usually enter the collection to
judge comparison outcomes first, then inspect one important result, then
return to the source paper only when verification is needed.

These two orderings do not conflict. They answer different questions.

## Naming Rules

The product and API naming should follow these rules.

### Product-Facing Terms

Use:

- `Document`
- `Result`
- `Comparison`
- `Evidence`

### Internal Terms

Internal backend terms may continue to use:

- `ComparableResult`
- `CollectionComparableResult`
- `ComparisonRowRecord`

### Explicit Boundary

Do not expose `ComparableResult` as the primary product name for the main
collection pages.

Do not expose `Material` as the main product object either.

`Material` should remain a major filter and indexing dimension within the
`Result` and `Comparison` surfaces.

## Target Surface Family

The intended collection-facing route family should converge toward:

- `workspace`
- `comparisons`
- `results`
- `documents`
- `protocol`
- `graph`

The preferred tab order is:

1. `Workspace`
2. `Comparisons`
3. `Results`
4. `Documents`
5. `Protocol`
6. `Graph`

`Evidence` may remain temporarily available as a standalone surface, but it
should no longer be treated as the primary collection navigation center.

## Shared Contract Implications

This RFC implies the following shared contract direction.

### Workspace

The workspace should keep acting as the entry summary page, but its links and
capabilities should evolve to expose:

- `comparisons`
- `results`
- `documents`
- `protocol`
- `graph`

Primary CTA priority should move toward:

`comparisons -> results -> documents`

### Comparisons

The comparison surface should remain the primary analysis table for the
collection.

It should also become an explicit drill-down origin into `Result`.

In practical terms, a comparison row should not be the last stop. It should be
the entry into the result object that the row is about.

### Results

The product-facing result surface should be collection-scoped.

It should present a user-readable projection over:

- internal `ComparableResult`
- the current collection's `CollectionComparableResult`
- source document summary and navigation

It should not simply dump raw semantic payload fields.

### Documents

The document surface should remain the source-of-truth recovery page.

It should also surface which results were extracted from that paper so the
user can move naturally from verification back into semantic objects.

### Evidence

Evidence should remain accessible for traceback and trust inspection, but it
should be entered primarily from result or document flows rather than being
the center of the main collection hierarchy.

## Implementation Direction

This RFC defines the target direction, not the exact module rollout order.

The intended implementation shape is still:

1. keep the internal semantic backbone stable
2. add a product-facing `results` read model and route family
3. make comparison rows drill into result detail
4. make document detail expose extracted results and evidence support
5. demote standalone evidence navigation over time

Module-local implementation plans should define the exact sequencing for:

- backend API contract updates
- frontend route changes
- workspace CTA and navigation changes
- evidence-page demotion or retention strategy

## Guardrails

This direction should be interpreted with five guardrails.

### 1. Do Not Replace The Comparison-First Product Entry

The comparison page remains the primary user-facing analysis entry.

### 2. Do Not Treat Raw Comparable-Result Retrieval As The Main Product Page

Corpus retrieval and semantic inspection are useful internal or secondary
surfaces, but they are not the same thing as the main user-facing result page.

### 3. Do Not Promote `Evidence` Back Into The Main Product Center

Evidence is essential support, not the main navigation center for the
collection workspace.

### 4. Do Not Collapse `Result` Into `Material`

Materials remain a major organizing dimension, but the product object is the
result, not the material alone.

### 5. Do Not Reinterpret Internal Substrate Names As Final UX Copy

Internal backend semantic names should stay decoupled from product-facing page
language unless a later shared decision explicitly changes that boundary.

## Shared Implications

### Shared Docs

Shared docs should start describing the collection experience through this
distinction:

- `Comparisons` as the main analysis surface
- `Results` as the core product object layer
- `Documents` as the source verification layer
- `Evidence` as the support layer

### Backend

Backend-owned docs and contracts should preserve the internal semantic
backbone while introducing a product-facing `results` contract instead of
reusing raw `ComparableResult` retrieval payloads as the main UI contract.

### Frontend

Frontend-owned docs and route plans should treat:

- `comparisons` as the default collection analysis page
- `results` as the main drill-down destination
- `documents` as the recovery and verification surface

## Related Docs

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Paper Facts And Comparison Current State](../architecture/paper-facts-and-comparison-current-state.md)
- [RFC Paper-Facts Primary Domain Model and Derived Comparison Views](rfc-paper-facts-primary-domain-model.md)
- [RFC Comparable-Result Substrate and Materials Database Direction](rfc-comparable-result-substrate-and-materials-database-direction.md)
- [Backend API Spec](../../backend/docs/specs/api.md)
- [Frontend Lens V1 Interface Spec](../../frontend/src/routes/collections/lens-v1-interface-spec.md)
