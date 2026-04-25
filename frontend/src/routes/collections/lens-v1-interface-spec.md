# Lens V1 Frontend Interface Spec

## Purpose

This document defines the frontend execution spec for the next Lens v1
collection interface wave.

It answers:

- which collection-facing pages should be primary
- how the frontend should map to the agreed API contract
- how to migrate from the current steps-first workspace to a
  comparison-first interface with result drilldown and document verification

It does not redefine the backend API contract itself.

## Product Direction

The frontend should align to the shared Lens v1 direction:

- `workspace` is the collection entry surface
- `comparisons` is the primary analysis surface
- `results` is the core product object surface
- `documents` is the source verification surface
- `evidence` is a support layer that should primarily appear inside result and
  document flows
- `protocol/*` is a conditional branch
- `graph` and `reports` remain secondary surfaces

The frontend should therefore stop treating protocol steps, SOP generation, or
standalone evidence inspection as the default main path through a collection.

## Current Frontend Problems

The current frontend still reflects the older product center:

- collection sub-navigation still lacks a first-class `results` surface
- the workspace primary action can still route users using older readiness
  assumptions
- evidence is still too close to the center of the collection hierarchy
- the workspace contract still has to normalize older artifact-first fields
- reports must stay visually contained as workspace context unless a stable
  product reports surface is intentionally reintroduced

This means the frontend can still mislead users about the intended product
flow even though the shared product direction is now:

`comparisons -> result detail -> document detail`

## Design Goals

- keep comparison as the primary collection-facing analysis page
- introduce `results` as the main drilldown object family
- make documents the explicit source verification surface
- keep evidence visible for trust and traceback without making it the main
  collection center
- keep workspace focused on readiness, warnings, and next actions
- keep protocol available without making it the main product promise
- allow frontend implementation to proceed before backend finishes every new
  endpoint

## Out Of Scope

- replacing the visual design system wholesale
- redesigning public home page copy beyond navigation and IA needs
- removing legacy graph or protocol routes in the first wave
- waiting for backend completion before building the new collection UI

## Target Collection IA

The target collection route family should be:

- `/collections/[id]`
  Workspace overview and entry surface
- `/collections/[id]/comparisons`
  Primary comparison workspace
- `/collections/[id]/results`
  Result list page
- `/collections/[id]/results/[resultId]`
  Result detail page
- `/collections/[id]/documents`
  Document list and screening page
- `/collections/[id]/documents/[documentId]`
  Document detail and source verification page
- `/collections/[id]/protocol`
  Conditional protocol landing surface
- `/collections/[id]/protocol/steps`
  Protocol steps browsing
- `/collections/[id]/protocol/sop`
  SOP draft surface
- `/collections/[id]/graph`
  Secondary graph analysis

Optional or transitional support route:

- `/collections/[id]/evidence`
  Support or debug surface for claim-centered evidence browsing when that view
  is still useful during migration

Redirect-only aliases such as `/steps`, `/sop`, `/search`, `/tasks`,
`/reports`, and `/settings` are no longer part of the target frontend route
family. Old deep links should use the canonical routes or workspace anchors
instead of compatibility pages.

## Navigation Rules

The collection sub-navigation should be reordered to reflect product priority:

1. `Workspace`
2. `Comparisons`
3. `Documents`
4. `Results` under secondary navigation only
5. `Protocol`
6. `Graph`

Rules:

- `Comparisons` is the primary analysis destination
- `Documents` is the source recovery, paper evidence-chain, and verification page
- `Results` remains the drilldown destination from comparison rows, document
  chains, and review workflows, but should not appear as a primary collection
  entry
- `Evidence`, if still rendered as a standalone page, should not displace
  `Documents` in the primary tab order
- `Protocol` is visible but visually secondary
- `Graph` remains available but should not be styled as the main end state
- `Reports` should stay hidden or secondary until a stable collection-scoped
  reports contract exists

## Page-Level Spec

### Workspace

Route:

- `/collections/[id]`

Purpose:

- summarize collection state
- surface workflow readiness
- expose collection-level warnings
- guide the user to the next best page

Primary sections:

- collection summary
- workflow stage rail
- warnings panel
- document summary
- recent tasks
- file upload and file list
- secondary surfaces

The workspace should no longer use protocol readiness or standalone evidence
readiness as the main signal for what to do next.

Primary CTA rules:

- no files: guide to upload
- active task: guide to monitoring progress
- comparisons ready: guide to `comparisons`
- results ready but comparisons not ready: guide to `results`
- documents ready but no downstream semantic outputs: guide to `documents`
- protocol ready: show as secondary CTA, not primary

Secondary CTA rules:

- evidence, when exposed, should be framed as support for traceability review
- graph should remain secondary even when ready

### Comparisons

Route:

- `/collections/[id]/comparisons`

Purpose:

- present `comparison_rows` as the primary analysis table
- separate comparable from limited and blocked rows
- let users drill from normalized rows into the canonical result object

Primary sections:

- collection comparison summary
- filters
- main comparison table
- row detail drawer or side panel

Expected table columns:

- material system
- process
- property
- baseline
- test conditions
- comparability status
- warnings count

Expected interactions:

- filter by `comparability_status`
- filter by material or property
- open result detail
- open supporting evidence as a secondary action
- jump to source document context when verification is needed

The comparison row is not the final semantic stop. It is the collection-facing
analysis projection that should drill into `results/[resultId]`.

Detailed traceback rules are defined in
[`claim-traceback-navigation-contract.md`](claim-traceback-navigation-contract.md).

### Results

Routes:

- `/collections/[id]/results`
- `/collections/[id]/results/[resultId]`

Purpose:

- retain the collection's extracted results as the atomic product object layer
- let users inspect what a result actually says before returning to source
- connect comparison judgments, evidence support, and source document recovery

Result list sections:

- collection result summary
- filters
- result list or table

Result detail sections:

- chain summary
- parent variant dossier summary
- process or sample state
- chain-local test condition
- result values and value provenance
- baseline detail
- structure or defect support
- collection-scoped assessment
- series navigation when sibling chains exist
- source document links and anchor actions

Expected interactions:

- filter by material, property, baseline, test condition, or comparability
- open result detail from list or from comparison rows
- open filtered comparisons from a result
- open source document verification from a result
- inspect supporting evidence without losing result-chain context

`Results` is the product-facing projection over internal semantic comparison
artifacts, but it is no longer a primary collection entry. Route code should
not expose raw `ComparableResult` internals as the page's primary conceptual
model. As the additive evidence-chain contract lands, the result page should
read as one chain-first drilldown rather than as a generic measurement card.

### Documents

Routes:

- `/collections/[id]/documents`
- `/collections/[id]/documents/[documentId]`

Purpose:

- present `document_profiles` as the document gating layer
- show which papers are experimental, mixed, review, or uncertain
- act as the source-of-truth recovery page for results and evidence

Document list sections:

- document type distribution
- protocol suitability distribution
- collection-level warnings
- per-document profile table

Document detail sections:

- source metadata
- original content or content viewer
- paper overview and missingness summary
- variant dossier list
- grouped result series under each dossier
- chain detail drawer or equivalent drilldown
- evidence highlights or traceback targets

Expected interactions:

- filter by `doc_type`
- filter by `protocol_extractable`
- inspect `protocol_extractability_signals`
- inspect parsing warnings per paper
- open result detail for results extracted from the same paper
- expand one variant dossier and inspect grouped result series
- open one full chain detail from a series row
- land on anchored source context from result or evidence flows

### Evidence

Optional route:

- `/collections/[id]/evidence`

Purpose:

- preserve claim-centered evidence browsing when it still helps with review,
  debugging, or migration
- keep traceback inspection available without making evidence the main product
  center

Rules:

- this page should be visually secondary to `comparisons`, `results`, and
  `documents`
- evidence pages should be reachable from result and document pages
- new product copy should avoid implying evidence is the canonical collection
  landing surface

Detailed traceback rules are defined in
[`claim-traceback-navigation-contract.md`](claim-traceback-navigation-contract.md).

### Protocol

Routes:

- `/collections/[id]/protocol`
- `/collections/[id]/protocol/steps`
- `/collections/[id]/protocol/sop`

Purpose:

- preserve protocol browsing as a conditional branch
- make its constraints explicit

Rules:

- the landing state should explain when protocol is unavailable or limited
- protocol readiness must be presented as conditional corpus suitability, not
  as the default collection goal
- `steps` and `sop` may remain as detailed subpages, but their copy should
  avoid implying they are the main product output

### Graph

Route:

- `/collections/[id]/graph`

Purpose:

- keep graph exploration available as a secondary analytical surface

Rules:

- graph should not be the first tab after workspace
- graph copy should position it as supporting structure or evidence view, not
  the main collection outcome

## Shared Data Layer Spec

The shared browser-side data layer should be reorganized around the agreed Lens
v1 resources.

### Keep

- `src/routes/_shared/api.ts`
- `src/routes/_shared/collections.ts`
- `src/routes/_shared/tasks.ts`
- `src/routes/_shared/protocol.ts`
- `src/routes/_shared/graph.ts`

### Upgrade

- `src/routes/_shared/workspace.ts`

`workspace.ts` should support both:

- current compatibility fields:
  - `artifacts`
  - legacy `capabilities`
  - temporary `evidence` links or flags when they are still exposed
- target Lens v1 fields:
  - `workflow`
  - `document_summary`
  - `warnings`
  - `links`
  - `results` capability and route fields

The adapter should normalize both shapes so route code does not need to care
which backend phase is active.

### Add

- `src/routes/_shared/documents.ts`
- `src/routes/_shared/results.ts`
- `src/routes/_shared/comparisons.ts`
- `src/routes/_shared/evidence.ts`

These modules should define:

- API fetch functions
- response types
- normalization helpers
- optional fixture-backed fallback loaders

## Contract Adapter Rule

The frontend should be contract-first but migration-safe.

That means:

- route code should read the agreed Lens v1 semantics
- shared adapters may temporarily map current backend payloads into those
  semantics
- route pages should not directly depend on raw artifact booleans except inside
  the adapter layer
- route pages should not use raw semantic-substrate payloads as product-facing
  page models when a product projection is expected

## Fixture Strategy

The frontend should not block on backend completion.

Use a fixture mode for not-yet-landed resources:

- `comparisons`
- `results`
- `documents`
- optional `evidence`

Recommended approach:

- add a lightweight feature flag such as `VITE_USE_API_FIXTURES`
- keep fixture payloads shaped exactly like the agreed API contract
- allow individual fetchers to switch between real API and local fixtures

This allows:

- route implementation
- visual design
- state design
- table and filter interactions
- early UI review

without waiting for backend delivery.

## Route Migration Plan

### Wave 1: Contract Adapter and Route Skeletons

Deliverables:

- upgrade `workspace.ts` adapter
- add `documents.ts`, `results.ts`, `comparisons.ts`, and optional `evidence.ts`
- add route skeletons:
  - `/comparisons`
  - `/results`
  - `/results/[resultId]`
  - `/documents`
  - `/documents/[documentId]`
  - optional `/evidence`
  - `/protocol`
- reorder collection sub-navigation

Constraint:

- no large visual rewrite yet
- use fixtures where backend resources are missing

### Wave 2: Workspace Reframe

Deliverables:

- rewrite collection workspace around workflow, warnings, and next actions
- make `comparisons` the default ready-state CTA
- add `results` as the secondary semantic CTA before documents
- demote protocol and graph in the workspace card hierarchy
- replace artifact chip language with workflow-stage language

Constraint:

- keep upload and task polling intact
- preserve current file and task operations

### Wave 3: Primary Analysis and Drilldown Surfaces

Deliverables:

- keep `comparisons` as the main analysis table
- build `results` as the core drilldown object family
- replace the current documents redirect with a real documents page
- add document detail as the source verification page

Constraint:

- these pages must be reviewable in fixture mode before backend completion

### Wave 4: Evidence, Protocol, and Graph Repositioning

Deliverables:

- connect evidence entry points from result and document pages
- decide whether standalone `/evidence` remains visible or becomes secondary
- move `steps` and `sop` under protocol framing
- update copy and entry points so protocol is clearly conditional
- reduce graph prominence in page hierarchy and workspace CTAs

### Wave 5: Cleanup and Compatibility

Deliverables:

- keep redirect-only route aliases out of the collection route tree
- keep stale guidance from describing `/steps`, `/sop`, `/search`, `/tasks`,
  `/reports`, or `/settings` as collection pages
- tighten type definitions to the final backend contract
- remove stale wording that still treats evidence as the main collection center

Completed cleanup:

- redirect-only `/steps`, `/sop`, `/search`, `/tasks`, `/reports`, and
  `/settings` collection pages have been removed
- the unused frontend reports API client has been removed because the current
  browser workflow keeps reports as a non-fetching workspace note, not as a
  standalone page or primary contract

## Copy and UX Rules

- avoid language that implies every collection should end in protocol steps
- use `comparison`, `result`, and `document verification` in primary copy
- use `evidence` as trust and traceback support language
- use `protocol branch` or equivalent conditional framing in helper copy
- use explicit degraded states:
  - `not_ready`
  - `limited`
  - `not_applicable`
  - `not_comparable`
- when protocol is unavailable, explain why instead of showing a generic empty
  state

## Testing Spec

The frontend test surface should move beyond the current home-page smoke test.

### Unit and route-level expectations

- workspace adapter can normalize both current and target payload shapes
- comparison fixtures render expected status groups
- result fixtures render semantic summary, assessment, and source actions
- document fixtures render type and extractability distributions
- evidence fixtures, when still used, render traceback and support sections

### E2E expectations

Add at least these flows:

1. create collection -> upload files -> open workspace
2. workspace shows workflow-centric sections rather than protocol-first CTAs
3. navigate from workspace to comparisons
4. navigate from comparisons to a result detail page
5. navigate from result detail to document detail
6. navigate to protocol and see conditional framing

Fixture-backed E2E is acceptable for not-yet-landed APIs.

## Acceptance Criteria

- collection navigation reflects `workspace / comparisons / documents` as the
  primary order, with `results / evidence / protocol / graph` kept secondary
- the primary collection CTA no longer defaults to SOP, protocol steps, or
  standalone evidence review
- `comparisons` exists as the main analysis surface
- `results` exists as the atomic drilldown object family without becoming a
  primary collection entry
- `documents` is a real page rather than a redirect
- `workspace` is framed around workflow readiness and warnings rather than raw
  artifact booleans
- the frontend can run the new collection UI in fixture mode before backend
  completion

## Related Docs

- [`../../../docs/decisions/rfc-comparison-result-document-product-flow.md`](../../../docs/decisions/rfc-comparison-result-document-product-flow.md)
- [`claim-traceback-navigation-contract.md`](claim-traceback-navigation-contract.md)
- [`collection-ui-restructure-proposal.md`](collection-ui-restructure-proposal.md)
- [`../../../../backend/docs/specs/api.md`](../../../../backend/docs/specs/api.md)
- [`../../../../backend/docs/architecture/domain-architecture.md`](../../../../backend/docs/architecture/domain-architecture.md)
