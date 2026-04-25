# Document And Result Evidence-Chain Proposal

## Purpose

This document records a frontend-local proposal for making `documents` and
`results` readable as evidence-chain surfaces instead of generic detail pages.

It narrows the collection route family to one specific UI question:

- what should the frontend use as the primary reading unit once semantic
  comparison artifacts are available

It does not redefine the shared Lens v1 product boundary or the backend API
contract.

## Why This Needs A Separate Proposal

The existing route-family docs already define the broad Lens v1 hierarchy:

- `comparisons` is the primary analysis surface
- `results` is the core drilldown object
- `documents` is the source verification surface
- `evidence` remains a support layer

What those docs do not yet define tightly enough is how a researcher should
read a paper or one extracted result when the work depends on an experimental
evidence chain rather than on one isolated value.

This gap matters most in materials and other experimental domains where one
reported number is not meaningful without:

- sample or variant state
- processing history
- test conditions
- structure or defect evidence
- baseline meaning
- comparability limits

This proposal records the frontend reading model for that narrower problem.

## Scope

In scope:

- document detail information architecture
- result detail information architecture
- frontend grouping model for `variant dossier`, `result chain`, and
  `result series`
- source-viewer and anchor interactions for those groupings
- UI rules for separating process conditions, test conditions, and structure
  observations

Out of scope:

- backend schema redesign
- shared product hierarchy between workspace, comparisons, results, and
  documents
- extraction prompt design
- collection-level comparison table redesign beyond entry points into the new
  drilldown model

## Reader Questions

The proposed document and result surfaces should let a user answer these
questions quickly:

1. Which sample or variant states appear in this paper?
2. What process or sample-state context is shared by each variant?
3. Which result chains belong to each variant?
4. Which parts of the result change because the test condition changed?
5. What structure or defect evidence supports the reported behavior?
6. Which missing fields or warnings limit cross-paper comparison?

## Core Reading Model

The frontend should use four nested reading units.

### Paper

The paper remains the entry point for document reading.

At this level the UI should summarize:

- material system
- process route
- primary property families covered
- variant count
- missingness or traceability warnings that affect the whole paper

### Variant Dossier

A `variant dossier` is the shared experimental state for one normalized sample
or material condition inside a paper.

Examples:

- `optimized VED`
- `optimized VED + HIP`
- `900 C annealed`

The dossier should carry the context that does not change across its child
chains:

- material label or composition
- normalized variant label
- process or sample-state fields
- shared structure evidence when that evidence applies to the whole variant
- known missing fields that affect all child chains

### Result Chain

A `result chain` is the smallest drilldown unit that should appear as a
complete, reviewable piece of evidence in the frontend.

One result chain should bind together:

- one variant
- one fixed result context
- one test condition set
- one result or tightly coupled result bundle
- one baseline interpretation
- one support trail back to source anchors

In practice, a result chain should answer:

- what was measured
- under which conditions
- relative to what baseline
- with what supporting structure or defect evidence
- with what comparability limits

### Result Series

A `result series` is a UI grouping for multiple sibling result chains that keep
the same variant dossier and only vary along one test-side axis.

Typical example:

- same `optimized VED + HIP` variant
- same tensile method
- same orientation and strain rate
- test temperature changes from `25 C` to `400 C` to `650 C`

The frontend should render these as one series instead of as unrelated cards.

## Chain Identity Rules

The frontend should group data with these rules.

### Keep One Variant Dossier When Process Or Sample State Is Shared

Fields that belong to the dossier include:

- composition
- powder or feedstock state when available
- process parameters
- post-treatment history
- build orientation when it is part of sample preparation
- exposure or aging history before testing

If one of those changes in a way that creates a new sample state, the frontend
should treat it as a different variant dossier instead of as one series row.

### Create Separate Result Chains When Test Context Changes

A result chain changes when test-side conditions change, such as:

- test temperature
- strain rate
- loading direction
- environment
- frequency
- specimen state at test time

These are different chains even when the parent variant dossier stays the
same.

### Use A Result Series Only For Test-Side Variation

The frontend should build a series when:

- the same variant dossier is fixed
- the same property family is fixed
- the same test family is fixed
- one explicit test-side axis varies in a user-readable way

Good series axes include:

- test temperature
- strain rate
- hold time
- cycle count bucket

The frontend should not collapse rows into one series when the apparent axis is
actually a process or sample-state change.

## Temperature Placement Rules

Temperature is the most common place where semantics get mixed, so the UI needs
explicit placement rules.

### Process Temperature

Examples:

- preheat temperature
- HIP temperature
- solution-treatment temperature
- aging temperature

These belong in the variant dossier under shared process or sample state.

If the temperature change creates a different treatment condition, it usually
creates a different variant dossier.

### Test Temperature

Examples:

- room-temperature tensile
- `400 C` tensile
- `650 C` creep

These belong in the result chain under test condition.

If the same variant is tested at multiple temperatures, the frontend should
keep one variant dossier and show multiple result chains inside one result
series.

### Characterization Temperature

Examples:

- in-situ heated XRD
- DSC scan temperature
- hot-stage microscopy

These belong under structure or observation conditions, not under process
state and not under the main test axis unless the measured property is itself a
characterization result.

## Document Page Proposal

The document page should become a source-reading page with an evidence review
panel, not only a content viewer plus related result links.

### Layout

- left: source viewer or content viewer with anchor highlighting
- right: evidence review panel
- bottom or secondary panel: cross-paper entry points when needed

### Evidence Review Panel

The right panel should have these top-level tabs:

- `Overview`
- `Variants`
- `Chains`
- `Missingness`

### Overview Tab

This tab should summarize:

- paper scope
- material system
- process route
- primary properties covered
- number of variants
- number of result chains
- paper-level missingness or traceability warnings

### Variants Tab

This should list one card per variant dossier.

Each card should show:

- normalized variant label
- material system
- shared process or sample state
- properties covered
- shared evidence summary
- shared missingness badges

Selecting a dossier should expand its child result series.

### Result Series In Document View

Inside one dossier, result chains should be grouped into series when possible.

Example:

```text
Variant S3 = optimized VED + HIP

Shared state
P=280 W, v=1200 mm/s, h=100 um, t=30 um
HIP=yes

Tensile vs test temperature
25 C  -> YS 940, UTS 1040, EL 15%
400 C -> YS 780, UTS 860, EL 18%
650 C -> YS 520, UTS 610, EL 22%
```

Each row should expose:

- the varying axis value
- primary result values
- baseline label
- comparability status
- missingness or warning badges
- an action to open full chain detail

### Chain Detail Drawer

Clicking a row should open a detail drawer or side panel that shows the full
result chain:

- variant summary
- process or sample state
- test condition
- structure or defect evidence
- result values
- baseline
- mechanism claim
- support evidence
- comparability warnings
- source anchors

Each anchor should support direct jump back into the source viewer.

## Result Detail Page Proposal

The result detail page should present one result chain as the primary object,
not only a generic measurement card.

### Required Sections

- chain summary
- parent variant dossier summary
- process or sample state
- test condition
- structure or defect support
- result values
- baseline and baseline type
- collection-scoped comparability assessment
- source anchors and document jump actions

### Related Context

When sibling chains exist in the same result series, the page should also show
a compact series navigator so users can move across:

- the same variant at different test temperatures
- the same variant at different strain rates
- other closely related test-side axes

This keeps the user inside one experimental story instead of forcing repeated
returns to the result list.

## Comparison Workspace Entry Rules

The comparison workspace should remain the main cross-paper analysis surface,
but it should be able to open into the new chain model cleanly.

The preferred flow is:

1. open comparison row
2. open result detail
3. inspect supporting chain context
4. jump to document anchors for source verification

The comparison table should not try to absorb the full chain detail into one
row.

## Backend Consumption Rules

This proposal does not redefine backend ownership, but the frontend should use
semantic drilldown data as its primary source when available.

Preferred source:

- collection-scoped document comparison semantics

The route-family UI should prefer backend-provided semantics for:

- variant identity
- process context
- test conditions
- structure support
- baseline resolution
- comparability status
- anchor linkage

The frontend should not invent unsupported semantic groupings from raw text
when the backend has not resolved them.

## First Delivery Slice

The first implementation wave should stay narrow.

1. Add a `Variant dossier` panel to the document page.
2. Render result chains as grouped series inside each dossier.
3. Add a chain detail drawer with anchor jump actions.
4. Reframe the result detail page around one chain plus its parent dossier.

This is enough to test whether the frontend is presenting a real evidence
chain rather than only a result card and a source link.

## Related Docs

- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
  Collection route-family product hierarchy and broad page responsibilities
- [`claim-traceback-navigation-contract.md`](claim-traceback-navigation-contract.md)
  Source-navigation rules for anchor-based document verification
- [`../../../../docs/decisions/rfc-comparison-result-document-product-flow.md`](../../../../docs/decisions/rfc-comparison-result-document-product-flow.md)
  Shared Lens v1 product decision for comparison, result, document, and
  evidence roles
