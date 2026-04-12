# Collection UI Restructure Proposal

## Purpose

This document records the next frontend collection-UI restructuring proposal for
Lens v1.

It focuses on three problems that the current interface still has after the
first contract-alignment wave:

- information architecture is still mixed by system module instead of user task
- collection and page states are not expressed as a clear product state machine
- primary, conditional, and derived views still compete at the same visual
  level

It does not redefine the backend API contract or replace the broader Lens v1
frontend interface spec.

## Why This Needs A Separate Proposal

The existing
[`lens-v1-interface-spec.md`](lens-v1-interface-spec.md) already defines the
Lens v1 route family and the comparison-first / evidence-first direction.

What it does not yet freeze tightly enough is:

- which pages are true primary surfaces versus conditional branches
- how collection state should be represented to users
- how empty, processing, limited, not-applicable, and failed states should be
  rendered
- how the workspace should reduce first-screen cognitive load

This proposal narrows to those questions.

## Current Problems

### 1. The top-level navigation still mixes different layers

The current collection navigation treats these as near-equals:

- workspace
- comparisons
- evidence
- documents
- protocol
- graph

But in the Lens v1 product model they are not equal:

- `workspace` is the entry summary
- `comparisons / evidence / documents` are the primary collection-facing
  artifacts
- `protocol` is a conditional branch
- `graph` is a derived or advanced view

This creates an immediate hierarchy mismatch.

### 2. The UI still leaks implementation vocabulary

Users should not need to understand backend nouns such as:

- comparison rows
- evidence cards
- document profiles
- traceability status
- protocol suitability

Those objects may remain valid system contracts, but page copy, labels, empty
states, and calls to action should answer user questions in product language.

### 3. Collection states are still underspecified in the product layer

The interface currently blurs several different meanings:

- empty collection
- files uploaded but not processed
- processing in progress
- partial readiness
- not applicable for protocol
- real failure

When these meanings are not separated, the UI falls back to raw absence,
generic locked states, or backend-flavored errors.

### 4. The workspace still tries to be too many pages at once

The current collection home combines:

- workspace summary
- upload page
- processing monitor
- result directory
- secondary tools directory

That makes the first screen feel scattered even when each individual component
is valid.

### 5. Error and empty states are not yet productized

For the main collection surfaces, the frontend should not expose raw "not
found" semantics when the real meaning is:

- not generated yet
- still processing
- unsuitable for this collection
- insufficient evidence
- failed generation

Those are product states, not transport errors.

## Target Model

The collection UI should be organized into four layers.

### Layer 1: Entry Summary

- `workspace`

This page answers:

- what kind of collection this is
- what is ready
- what is limited or not applicable
- what the user should do next

### Layer 2: Primary Analysis Views

- `comparisons`
- `evidence`
- `documents`

These are the default research views for Lens v1.

### Layer 3: Conditional Branch

- `protocol`

This should be visible only as a subordinate path, not as the default center of
the product.

### Layer 4: Derived / Advanced Views

- `graph`
- `reports`
- export tools

These remain available, but they should not compete with the main collection
views on first read.

## Navigation Proposal

### Preferred Navigation

Primary navigation:

- `Workspace`
- `Comparisons`
- `Evidence`
- `Documents`
- `More`

Under `More`:

- `Protocol`
- `Graph`
- `Reports`
- exports

### Transitional Navigation

If a `More` menu is too much churn for the next wave, use a visual hierarchy
that still encodes the product model:

- keep `Workspace / Comparisons / Evidence / Documents` as the first-class tabs
- demote `Protocol` and `Graph` visually
- hide `Protocol` when the collection is explicitly not suitable
- hide `Graph` behind an advanced affordance when it has no meaningful preview

## Collection State Machine

The collection home should explicitly model these top-level states.

### 1. Empty

Meaning:

- no files uploaded

Primary action:

- upload papers

UI rule:

- only the upload task should dominate the page

### 2. Ready To Process

Meaning:

- files exist
- no active processing run
- no primary analysis outputs yet

Primary action:

- start processing

UI rule:

- emphasize one main button and keep advanced indexing options collapsed

### 3. Processing

Meaning:

- active task is running

Primary action:

- monitor progress

UI rule:

- the page should explain that primary views are being generated, not merely
  appear empty

### 4. Ready With Limits

Meaning:

- at least one primary artifact is ready
- at least one other artifact is limited, not applicable, or still absent

Primary action:

- go to the best available primary view

UI rule:

- explain limits explicitly rather than presenting raw missing pages

### 5. Failed

Meaning:

- the pipeline failed in a way the user should handle

Primary action:

- retry or inspect failure details

UI rule:

- this is the only state where true failure styling should dominate

## Resource-Level State Semantics

Each major resource should map backend readiness into product meanings:

- `not_started`
  User meaning: not generated yet
- `processing`
  User meaning: still being prepared
- `ready`
  User meaning: open now
- `limited`
  User meaning: partially useful, but read warnings first
- `not_applicable`
  User meaning: this collection is not suitable for this view
- `failed`
  User meaning: generation failed

The frontend should never surface these as raw backend-state explanations.
Instead, each page should render them as local UX states with concrete next
actions.

## Workspace Proposal

The collection workspace should be a real overview page, not a merged upload
and tool directory page.

### Top Section

The first screen should contain a single collection diagnosis block:

- collection name
- collection description if present
- current state
- recommended next action
- paper mix summary
- collection warnings

### Main Views Section

This section should contain only:

- comparisons
- evidence
- documents

Each card should answer:

- what this page helps you decide
- whether it is ready
- one next action

### Secondary Views Section

This section should contain:

- protocol
- graph

These cards should explain why they are secondary:

- protocol is conditional
- graph is derived / exploratory

### Source Papers Section

Source-paper upload and file management should move below the main views and
should be collapsible by default once the collection has files.

### Advanced Section

Reports, raw settings, and debugging-style metadata should remain collapsed.

## Page Role Proposal

### Comparisons

This page should answer:

- which results across papers can really be compared
- which ones are only partially comparable
- which ones should not be compared directly

The main table should use user language such as:

- material
- treatment
- result
- compared against
- test setup
- can compare?
- why be careful

### Evidence

This page should answer:

- what supports a conclusion
- where that support comes from
- under what conditions the result holds

It should foreground:

- conclusion text
- source type
- trace-back strength
- evidence anchors
- process / baseline / test context

### Documents

This page should answer:

- which papers are experimental
- which are reviews or mixed sources
- which are safe to continue using for downstream extraction

It should foreground:

- paper type
- step-extraction suitability
- warnings
- reasons or signals behind suitability judgments

### Protocol

This page family should answer:

- whether procedural extraction is meaningful for this collection
- what steps are available if the branch is valid

If the branch is not applicable, the page should say so directly and route the
user back to the primary views.

### Graph

This page should answer:

- whether a derived relationship view is available
- whether only export is available

It should not be framed as a required page for understanding a collection.

## Error And Empty State Rules

For collection-facing pages, do not surface raw `404` style text when the
actual product meaning is known.

Instead use these mappings:

- no files
  Show upload guidance
- not processed
  Show start-processing guidance
- processing
  Show in-progress state
- unsuitable collection
  Explain why the page is not applicable
- insufficient artifact
  Explain what is missing and where to look instead
- failed
  Show retry / failure guidance

## Copy Rules

### Keep internal nouns internal

The UI may keep system object names in code, but user-facing copy should prefer
task language:

- comparisons: "which results can really be compared"
- evidence: "what supports this conclusion"
- documents: "which papers are experimental versus review"
- protocol: "only when usable procedures exist"

### Keep one main question per page

Each page should open with a lead that answers:

- what decision this page helps the user make

It should not open with implementation semantics.

## Delivery Slices

### Slice 1: Workspace Hierarchy

- make the workspace a true overview page
- move source-paper operations below primary views
- separate primary and secondary surfaces clearly

### Slice 2: State-Driven Empty / Limited / Not-Applicable UX

- replace raw missing-resource messaging
- define per-page product states
- align resource warnings to collection diagnosis

### Slice 3: Navigation Demotion For Conditional And Derived Views

- demote protocol and graph from equal-weight navigation
- add `More` navigation if acceptable
- otherwise preserve visual hierarchy through secondary styling and readiness
  gating

### Slice 4: Copy And Label Cleanup

- convert page leads, filters, table columns, and status labels into
  user-facing language
- keep bilingual parity across English and Chinese copy

## Acceptance Signals

The restructuring is successful when:

- a first-time user can tell from the workspace what the collection is and
  where to start
- comparisons, evidence, and documents are visibly the main path
- protocol no longer reads like the default collection outcome
- graph no longer reads like a primary product page
- normal readiness states never show raw `404`-style language
- upload and source-paper controls no longer dominate the first screen after a
  collection already has material

## Related Docs

- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
- [`frontend-plan.md`](frontend-plan.md)
