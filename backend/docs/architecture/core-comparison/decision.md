# Retired Core Comparison Decision

## Summary

This page records why the old comparison-semantic substrate is no longer a
Lens v1 product surface.

The maintained rule is:

`Source -> Objective -> published analysis -> Finding -> ObjectiveEvidence`

The retired comparison rows, comparable results, collection overlays, Evidence
cards, Materials, and Graph projections cannot become a parallel conclusion
identity.

## Accepted Boundaries

- Source owns parsed paper content and exact locators.
- Objective analysis owns scientific comparison and uncertainty.
- Finding owns the published conclusion.
- ObjectiveEvidence owns versioned support and Source traceback.
- Legacy comparison records are removed rather than retained as a second
  persistence model.

## Current Scientific Objects

- `ObjectiveEvidence` records one versioned, Source-grounded fact relevant to
  a confirmed research question.
- `ObjectiveEvidenceComparison` records whether that Evidence contains a
  grounded within-paper comparison and the limits of that comparison.
- `Finding` records the published cross-paper conclusion and its uncertainty.

Published Finding and ObjectiveEvidence records are the evaluation and export
inputs. They do not depend on a comparison row, comparable result, collection
overlay, or material-first reassessment policy.

## Ownership Rules

- no comparison repository or compatibility read remains
- current HTTP resources are defined only by
  [`../../specs/api.md`](../../specs/api.md)

## Guardrails

- no compatibility route for retired comparison resources
- no hidden Finding reconstruction in exports or browser clients
- no material-first comparison substrate or compatibility layer

Earlier field-level boundaries remain available in Git history when needed for
offline data archaeology.

## Related Docs

- [`current-state.md`](current-state.md)
- [`../../specs/api.md`](../../specs/api.md)
- [`../overview.md`](../overview.md)
- [`../goal-core-source-layering.md`](../goal-core-source-layering.md)
