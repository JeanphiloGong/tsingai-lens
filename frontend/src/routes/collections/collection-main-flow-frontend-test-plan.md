# Collection Main Flow Frontend Test Plan

## Purpose

This document records the frontend-local plan for hardening automated coverage
around the implemented Lens v1 main collection flow:

`workspace -> comparisons -> result detail -> document detail`

The goal of this wave is not to redesign the UI again. It is to protect the
current product path before follow-on cleanup work touches protocol, reports,
or residual backend migration debt.

## Scope

In scope:

- route-level automated coverage for the collection workspace, comparisons,
  results, result detail, and document detail pages
- drilldown assertions that protect the current primary navigation path from
  workspace CTA through result and source verification
- the smallest fixture or fetch-mocking work needed to drive those pages in
  frontend tests
- one optional end-to-end golden-path check if the route-level coverage leaves
  a gap that unit-level browser tests cannot cover honestly

Out of scope:

- changing collection information architecture or route ownership
- changing backend API contracts
- redesigning protocol, graph, or reports surfaces
- introducing a second test-only browser contract, adapter, or wrapper layer
- broad test-infrastructure replacement or a new frontend test framework

## Related Docs

- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
  Route-family authority for the collection UI and its testing expectations
- [`../../../docs/decisions/rfc-comparison-result-document-product-flow.md`](../../../docs/decisions/rfc-comparison-result-document-product-flow.md)
  Shared product direction for the collection drilldown model
- [`../../../../backend/docs/specs/api.md`](../../../../backend/docs/specs/api.md)
  Backend HTTP contract authority for `workspace`, `comparisons`, `results`,
  and `documents`
- [`../../../docs/frontend-plan.md`](../../../docs/frontend-plan.md)
  Same-origin frontend contract guide

## Why A Separate Child Plan Exists

The main feature wave is already implemented.

The current gap is narrower:

- backend results APIs and frontend pages already exist
- workspace, comparisons, result detail, and document detail already connect
  end to end
- existing automated coverage is still concentrated in shared helpers and a
  generic smoke test

That means the missing work is no longer a product-flow rollout. It is a
frontend-local protection wave for the now-implemented route family.

This deserves its own child plan because the interface spec already defines
the target behavior, but it does not prescribe the concrete file-level test
work needed to keep that behavior stable.

## Current Test Gap

The current frontend coverage already proves some contract basics:

- `src/routes/_shared/workspace.spec.ts`
- `src/routes/_shared/results.spec.ts`
- shared helper coverage for graph state
- a minimal route smoke test

The remaining risk is page-level drift.

Today there is no focused automated coverage that locks in:

- workspace primary CTA selection across `comparisons`, `results`, and
  `documents` readiness states
- comparison-row drilldown into result detail
- result-detail drilldown back to source document detail
- result-list action links
- document-detail rendering of related results from the same source paper

Without that coverage, later cleanup work can break the main Lens v1 product
flow while still leaving shared helper tests green.

## Testing Rules For This Wave

- protect the current product path exactly as implemented:
  `workspace -> comparisons -> result detail -> document detail`
- prefer route-level browser tests with the existing Vitest + Svelte test
  stack before expanding Playwright coverage
- keep fetch mocking and fixture setup close to the owning route tests instead
  of adding a new shared compatibility harness
- query visible roles, links, headings, and actions instead of binding tests to
  fragile DOM structure
- keep same-origin API semantics intact; tests should exercise the real route
  contract shape, not a simplified shadow payload
- if a route cannot be tested honestly without adding production wrappers,
  cover that gap with one Playwright golden-path test instead of refactoring
  the app into a test harness

## Delivery Waves

### Wave 1: Route-Level Coverage

This is the required implementation wave.

Goals:

- add focused browser tests for the implemented collection pages
- lock in the current CTA and drilldown semantics
- prove the page chain remains navigable with real contract-shaped payloads

### Wave 2: Golden-Path End-To-End Coverage

This is optional follow-on work.

Goals:

- replace or extend the current demo-style Playwright smoke test
- cover one collection main-flow journey at browser level

This second wave should stay thin. The goal is one honest main-path guard, not
an E2E matrix explosion.

## File-Level Plan

### 1. Workspace route coverage

Files:

- `frontend/src/routes/collections/[id]/+page.svelte`
- `frontend/src/routes/collections/[id]/+page.svelte.spec.ts`

Changes:

- add route-level tests for primary CTA selection
- cover at least these readiness cases:
  - comparisons ready -> CTA points to `comparisons`
  - results ready but comparisons limited or unavailable -> CTA points to
    `results`
  - documents ready but downstream semantics unavailable -> CTA points to
    `documents`
- keep existing secondary-surface behavior out of the primary assertion path

Do not:

- re-center the workspace around protocol or graph
- add a second workspace normalization layer for testability

### 2. Comparisons page drilldown coverage

Files:

- `frontend/src/routes/collections/[id]/comparisons/+page.svelte`
- `frontend/src/routes/collections/[id]/comparisons/+page.svelte.spec.ts`

Changes:

- add tests that render the comparisons page with current nested comparison
  payloads
- assert a comparison row exposes the result drilldown action
- assert the action target points to `/collections/{id}/results/{result_id}`

Do not:

- fall back to testing old flat comparison-row contracts
- reintroduce evidence-first primary navigation in the page assertions

### 3. Results list coverage

Files:

- `frontend/src/routes/collections/[id]/results/+page.svelte`
- `frontend/src/routes/collections/[id]/results/+page.svelte.spec.ts`

Changes:

- add tests for result-list rendering from product-facing results payloads
- assert row actions open:
  - result detail
  - source document detail
- cover at least one filter interaction that proves the page is using the real
  result fields rather than a placeholder list

### 4. Result detail coverage

Files:

- `frontend/src/routes/collections/[id]/results/[resultId]/+page.svelte`
- `frontend/src/routes/collections/[id]/results/[resultId]/+page.svelte.spec.ts`

Changes:

- add tests that render result detail with measurement, context, assessment,
  and evidence sections
- assert the page exposes the source-document action
- assert the source-document action points to
  `/collections/{id}/documents/{document_id}`
- assert the page keeps the comparison return path visible

### 5. Document detail coverage

Files:

- `frontend/src/routes/collections/[id]/documents/[document_id]/+page.svelte`
- `frontend/src/routes/collections/[id]/documents/[document_id]/+page.svelte.spec.ts`

Changes:

- add tests that render document detail with related results
- assert related results link back into result detail
- keep source-verification and related-result behavior covered in the same page
  test instead of splitting the product story across two disconnected specs

### 6. Optional Playwright main-flow guard

Files:

- `frontend/e2e/demo.test.ts`
- or a new collection-flow-focused e2e spec if the demo file should stay as a
  separate smoke check

Changes:

- if Wave 1 still leaves an honest gap, add one main-flow browser path:
  workspace -> comparisons -> result detail -> document detail
- keep it narrow and fixture-backed if needed

Do not:

- build a large route matrix in Playwright for this wave
- duplicate all route-level assertions in E2E form

## Recommended Order

1. add workspace route coverage
2. add comparisons page drilldown coverage
3. add result detail and document detail coverage
4. add results list coverage if still missing after the drilldown path is
   protected
5. decide whether one Playwright golden-path test is still necessary

## Verification

Minimum checks for Wave 1:

- `npm run test:unit -- --run src/routes/collections/[id]/+page.svelte.spec.ts`
- `npm run test:unit -- --run src/routes/collections/[id]/comparisons/+page.svelte.spec.ts`
- `npm run test:unit -- --run src/routes/collections/[id]/results/+page.svelte.spec.ts`
- `npm run test:unit -- --run src/routes/collections/[id]/results/[resultId]/+page.svelte.spec.ts`
- `npm run test:unit -- --run src/routes/collections/[id]/documents/[document_id]/+page.svelte.spec.ts`
- `npm run check`

Optional Wave 2 check:

- `npm run test:e2e`

Behavioral assertions:

- workspace primary CTA follows the intended readiness order
- comparisons drill into result detail
- result detail drills into document detail
- document detail exposes related results
- result-list actions continue to point to result and document surfaces

## Risks

Main risks in this wave:

- route components may be harder to render directly than shared helpers because
  they depend on params, async fetches, and workspace state
- brittle text-only assertions can drift with i18n changes even when behavior
  remains correct
- test fixtures can accidentally mask contract drift if they simplify the real
  payload shape

Mitigations:

- prefer role and link assertions over large snapshot-style DOM checks
- keep fixtures contract-shaped and local to the route being tested
- use one thin Playwright path only where route-level rendering becomes too
  coupled to test honestly

## Exit Criteria

This wave is complete when:

- the main collection flow is covered by targeted frontend automation rather
  than shared-helper tests alone
- the route family has direct regression guards for result and document
  drilldown
- no new frontend adapter, wrapper, or alternate browser contract was added to
  make the tests pass
