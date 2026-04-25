# Materials Comparison V2 Frontend Alignment Plan

## Purpose

This document records the frontend-local implementation plan for adopting the
materials comparison v2 backend contract on the existing collection
comparisons surface.

The goal is to cut the current `/collections/[id]/comparisons` page over to
the stronger nested comparison payload without introducing a new route, a new
page family, or a long-lived compatibility adapter.

## Scope

In scope:

- direct frontend adoption of the nested comparison response contract
- updates to the shared comparison client and normalization logic
- updates to the comparisons page filters, summary counts, table rendering, and
  source-navigation entry points
- fixture alignment so local frontend development does not mask contract drift
- lightweight UI exposure of review and uncertainty semantics that are now part
  of the backend contract

Out of scope:

- collection IA redesign
- new comparison routes such as `/comparisons-v2`
- changes to evidence, documents, workspace, protocol, graph, or reports
  beyond existing navigation links
- long-lived dual parsing of old flat and new nested comparison shapes

## Companion Docs

- [`../../../../backend/docs/plans/materials-comparison-v2-plan.md`](../../../../backend/docs/plans/backend-wide/materials-comparison-v2/implementation-plan.md)
  Backend-owned source plan for the sample/result-backed comparison backbone
- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
  Collection route-family interface authority for Lens v1
- [`claim-traceback-navigation-contract.md`](claim-traceback-navigation-contract.md)
  Source-navigation contract used by the comparisons page

## Why This Needs A Separate Frontend Plan

The backend cutover is already implemented around a nested response model with
`display`, `evidence_bundle`, `assessment`, and `uncertainty`.

The current frontend comparisons surface still assumes the old flat row shape.
That mismatch means the route can keep the same URL while still failing at the
consumer contract layer.

This deserves a separate frontend-local plan because the route-family spec
already defines comparisons as the main analysis surface, but it does not
freeze the exact implementation steps for this contract cutover.

## Current Mismatch

The backend response now groups comparison row data into four zones:

- `display`
- `evidence_bundle`
- `assessment`
- `uncertainty`

The current frontend still reads comparison rows as if these fields live at the
top level:

- `material_system_normalized`
- `process_normalized`
- `property_normalized`
- `baseline_normalized`
- `test_condition_normalized`
- `supporting_evidence_ids`
- `comparability_status`
- `comparability_warnings`

This mismatch affects three concrete frontend areas:

1. shared type definitions and response normalization in
   `src/routes/_shared/comparisons.ts`
2. comparisons-page filtering, summary counts, table rendering, and source
   actions in `src/routes/collections/[id]/comparisons/+page.svelte`
3. frontend fixtures, which still use the old flat row shape and can hide the
   real API mismatch when `VITE_USE_API_FIXTURES=true`

## Frontend Adoption Rules

- keep the existing `/collections/[id]/comparisons` route
- directly adopt the nested backend contract
- do not add a frontend-local adapter layer that preserves the old flat row
  interface
- do not keep dual-read logic for old and new row shapes after the cutover
- remove old flat-field assumptions in the same task that introduces the new
  nested contract
- keep the existing table-first page layout in the first frontend wave
- surface review and uncertainty semantics explicitly enough that the stronger
  backend contract is not collapsed back into a plain status table

## Target Frontend Contract

The frontend should treat each row as:

```ts
type ComparisonRow = {
  row_id: string;
  collection_id: string;
  source_document_id: string;
  display: ComparisonDisplay;
  evidence_bundle: ComparisonEvidenceBundle;
  assessment: ComparisonAssessment;
  uncertainty: ComparisonUncertainty;
};
```

The shared client should keep the backend grouping intact instead of flattening
it back into a legacy view model.

## Field Mapping

| Current frontend usage | New backend field | Frontend use after cutover |
| --- | --- | --- |
| `row_id` | `row_id` | unchanged |
| `collection_id` | `collection_id` | unchanged |
| `source_document_id` | `source_document_id` | unchanged |
| `supporting_evidence_ids` | `evidence_bundle.supporting_evidence_ids` | evidence count and source jump |
| `material_system_normalized` | `display.material_system_normalized` | material filter and table column |
| `process_normalized` | `display.process_normalized` | process column |
| `property_normalized` | `display.property_normalized` | property filter and table column |
| `baseline_normalized` | `display.baseline_normalized` | baseline column |
| `test_condition_normalized` | `display.test_condition_normalized` | test column |
| `comparability_status` | `assessment.comparability_status` | status filter, summary counts, label |
| `comparability_warnings` | `assessment.comparability_warnings` | warnings display |

Important newly available fields that should not stay unused:

- `display.variant_label`
- `display.variable_axis`
- `display.variable_value`
- `display.result_summary`
- `assessment.requires_expert_review`
- `assessment.assessment_epistemic_status`
- `uncertainty.missing_critical_context`
- `uncertainty.unresolved_baseline_link`
- `uncertainty.unresolved_condition_link`

## File-Level Change Plan

### 1. Shared comparison client

File:

- `frontend/src/routes/_shared/comparisons.ts`

Changes:

- replace the flat `ComparisonRow` type with nested `display`,
  `evidence_bundle`, `assessment`, and `uncertainty` subtypes
- update `normalizeRow()` so it parses the nested backend payload directly
- keep validation and fallback behavior local to the shared client
- update `buildFixture()` to emit the nested shape instead of the flat shape

Do not:

- add a `flattenComparisonRow()` helper
- preserve a legacy `ComparisonRow` compatibility type
- parse both shapes indefinitely

### 2. Comparisons page

File:

- `frontend/src/routes/collections/[id]/comparisons/+page.svelte`

Changes:

- switch filter inputs to `display.material_system_normalized`,
  `display.property_normalized`, and `assessment.comparability_status`
- switch summary counts to `assessment.comparability_status`
- switch source and evidence actions to
  `evidence_bundle.supporting_evidence_ids`
- switch warnings rendering to `assessment.comparability_warnings`
- keep the current page structure and table layout in the first wave

### 3. Shared copy

File:

- `frontend/src/routes/_shared/i18n.ts`

Changes:

- keep existing comparison labels
- add narrow copy for expert review and missing context when needed
- avoid backend-internal wording in user-facing labels

## Page Rendering Plan

The first frontend wave should keep the current high-level page structure:

- comparison summary
- filters
- main comparison table
- source/evidence actions

The table can keep its current columns in the first cutover:

- material
- process
- result
- baseline
- test setup
- can compare
- why be careful
- actions

The page should still expose a few of the newly available fields so the v2
backend work is visible to users:

- show `display.result_summary` as supporting text in the result column
- show `display.variant_label` when present under the material column
- show a lightweight `requires_expert_review` indicator in the status column
- append `uncertainty.missing_critical_context` to the caution/warnings column

These are intentionally lightweight additions. They do not require a new
drawer, side panel, or page-level IA change.

## Recommended Implementation Order

1. update `src/routes/_shared/comparisons.ts` types, normalization, and
   fixtures
2. update `src/routes/collections/[id]/comparisons/+page.svelte` to consume
   the nested contract end to end
3. update `src/routes/_shared/i18n.ts` with any new comparison copy
4. remove old flat-field assumptions from the touched files before finishing

## Verification Plan

Minimum frontend checks for this wave:

- `VITE_USE_API_FIXTURES=false`:
  comparisons page loads real backend rows with the nested contract
- `VITE_USE_API_FIXTURES=true`:
  local fixtures use the same nested contract and render the page correctly
- filter by `comparable`, `limited`, `not_comparable`, and `insufficient`
- filter by material and property still works after the field-path changes
- source navigation still uses the first
  `evidence_bundle.supporting_evidence_ids` entry
- at least one row with `requires_expert_review=true` shows an explicit review
  cue
- at least one row with `missing_critical_context` shows an explicit caution
  cue

## Risks

Main frontend risks:

- fixture mode can hide real API mismatch if fixture payloads are not updated
- a pure path swap without any UI exposure of uncertainty will throw away the
  main product meaning added by the backend
- a compatibility adapter would reduce short-term churn but leave the old flat
  semantics alive in the frontend

Mitigations:

- update fixtures in the same task as the shared client cutover
- expose review and missing-context semantics in the existing table
- delete flat-field reads from touched files before closing the task

## Exit Criteria

- the comparisons page consumes the backend nested contract directly
- no new route or compatibility surface is introduced
- fixture and live API modes use the same response shape
- current comparisons filters, summary cards, and traceback entry points still
  work
- the page visibly communicates expert-review and missing-context cases
