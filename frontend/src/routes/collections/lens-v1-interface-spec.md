# Lens V1 Frontend Interface Spec

## Purpose

This document defines the frontend execution spec for the next Lens v1
interface wave.

It answers:

- which collection-facing pages should become primary
- how the frontend should map to the agreed API contract
- how to migrate from the current steps-first workspace to a
  comparison-first interface without blocking on backend completion

It does not redefine the backend API contract itself.

## Product Direction

The frontend should align to the agreed Lens v1 contract:

- `workspace` is the collection entry surface
- `documents/profiles` is the document gating surface
- `evidence/cards` is the evidence inspection surface
- `comparisons` is the primary analysis surface
- `protocol/*` is a conditional branch
- `graph` and `reports` remain secondary surfaces

The frontend should therefore stop treating protocol steps and SOP generation
as the default main path through a collection.

## Current Frontend Problems

The current frontend still reflects the old product center:

- collection sub-navigation is `overview / steps / sop / graph`
- the workspace primary action can route users into `steps` or `sop`
- the workspace contract must be driven by workflow readiness and capabilities
  instead of stale artifact flags such as `sections_ready` or `graphml_ready`
- `documents`, `tasks`, and `reports` routes are still redirects or legacy
  compatibility surfaces rather than primary pages

This means the frontend currently reinforces a protocol-first mental model even
though the agreed Lens v1 contract is comparison-first and evidence-first.

## Design Goals

- make comparison the primary collection-facing analysis page
- make evidence and documents first-class support surfaces
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
- `/collections/[id]/evidence`
  Evidence card inspection
- `/collections/[id]/documents`
  Document profile inspection
- `/collections/[id]/protocol`
  Conditional protocol landing surface
- `/collections/[id]/protocol/steps`
  Protocol steps browsing
- `/collections/[id]/protocol/sop`
  SOP draft surface
- `/collections/[id]/graph`
  Secondary graph analysis

During migration, the existing `/steps` and `/sop` routes may remain as
compatibility aliases or redirects into `/protocol/*`.

## Navigation Rules

The collection sub-navigation should be reordered to reflect product priority:

1. `Workspace`
2. `Comparisons`
3. `Evidence`
4. `Documents`
5. `Protocol`
6. `Graph`

Rules:

- `Comparisons` is the primary analysis destination
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

The workspace should no longer use protocol readiness as the main signal for
"what to do next".

Primary CTA rules:

- no files: guide to upload
- active task: guide to monitoring progress
- comparisons ready: guide to `comparisons`
- evidence ready but comparisons not ready: guide to `evidence`
- documents ready but no downstream outputs: guide to `documents`
- protocol ready: show as secondary CTA, not primary

### Comparisons

Route:

- `/collections/[id]/comparisons`

Purpose:

- present `comparison_rows` as the primary analysis table
- separate comparable from limited and blocked rows
- let users drill from normalized rows back into evidence and sources

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
- open supporting evidence
- jump to source document context

Detailed traceback rules are defined in
[`claim-traceback-navigation-contract.md`](claim-traceback-navigation-contract.md).

### Evidence

Route:

- `/collections/[id]/evidence`

Purpose:

- present claim-centered evidence cards
- allow traceability inspection before or alongside comparison judgments

Primary sections:

- evidence summary
- filters
- evidence card list
- anchor detail panel

Expected interactions:

- filter by `claim_type`
- filter by `traceability_status`
- filter by `evidence_source_type`
- expand `condition_context`
- open linked source anchors

Detailed traceback rules are defined in
[`claim-traceback-navigation-contract.md`](claim-traceback-navigation-contract.md).

### Documents

Route:

- `/collections/[id]/documents`

Purpose:

- present `document_profiles` as the document gating layer
- show which papers are experimental, mixed, review, or uncertain
- show protocol suitability signals without making protocol the center

Primary sections:

- document type distribution
- protocol suitability distribution
- collection-level warnings
- per-document profile table

Expected interactions:

- filter by `doc_type`
- filter by `protocol_extractable`
- inspect `protocol_extractability_signals`
- inspect parsing warnings per paper

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
- target Lens v1 fields:
  - `workflow`
  - `document_summary`
  - `warnings`
  - `links`

The adapter should normalize both shapes so route code does not need to care
which backend phase is active.

### Add

- `src/routes/_shared/documents.ts`
- `src/routes/_shared/evidence.ts`
- `src/routes/_shared/comparisons.ts`

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

## Fixture Strategy

The frontend should not block on backend completion.

Use a fixture mode for not-yet-landed resources:

- `documents/profiles`
- `evidence/cards`
- `comparisons`

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
- add `documents.ts`, `evidence.ts`, and `comparisons.ts`
- add route skeletons:
  - `/comparisons`
  - `/evidence`
  - `/documents`
  - `/protocol`
- reorder collection sub-navigation

Constraint:

- no large visual rewrite yet
- use fixtures where backend resources are missing

### Wave 2: Workspace Reframe

Deliverables:

- rewrite collection workspace around workflow, warnings, and next actions
- demote protocol and graph in the workspace card hierarchy
- replace artifact chip language with workflow-stage language

Constraint:

- keep upload and task polling intact
- preserve current file and task operations

### Wave 3: Primary Analysis Surfaces

Deliverables:

- build the `comparisons` page as the main analysis table
- build the `evidence` page with traceability drill-down
- replace `documents` redirect with a real document profile page

Constraint:

- these pages must be reviewable in fixture mode before backend completion

### Wave 4: Protocol and Graph Repositioning

Deliverables:

- move `steps` and `sop` under protocol framing
- update copy and entry points so protocol is clearly conditional
- reduce graph prominence in page hierarchy and workspace CTAs

### Wave 5: Cleanup and Compatibility

Deliverables:

- remove redirect-only route patterns that no longer serve the IA
- decide whether `/steps` and `/sop` stay as aliases or redirect to
  `/protocol/*`
- tighten type definitions to the final backend contract

## Copy and UX Rules

- avoid language that implies every collection should end in protocol steps
- use "comparison", "evidence", and "document suitability" in primary copy
- use "protocol branch" or equivalent conditional framing in helper copy
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
- evidence cards render traceability and condition sections
- document profiles render type and extractability distributions

### E2E expectations

Add at least these flows:

1. create collection -> upload files -> open workspace
2. workspace shows workflow-centric sections rather than protocol-first CTAs
3. navigate from workspace to comparisons
4. navigate from comparisons to evidence
5. navigate to protocol and see conditional framing

Fixture-backed E2E is acceptable for not-yet-landed APIs.

## Acceptance Criteria

- collection navigation reflects `workspace / comparisons / evidence /
  documents / protocol / graph`
- the primary collection CTA no longer defaults to SOP or protocol steps
- `comparisons` exists as the main analysis surface
- `documents` is a real page rather than a redirect
- `workspace` is framed around workflow readiness and warnings rather than raw
  artifact booleans
- the frontend can run the new collection UI in fixture mode before backend
  completion

## Related Docs

- [`../../../docs/frontend-plan.md`](../../../docs/frontend-plan.md)
- [`../../../../backend/docs/specs/api.md`](../../../../backend/docs/specs/api.md)
- [`../../../../backend/docs/architecture/domain-architecture.md`](../../../../backend/docs/architecture/domain-architecture.md)
