# Collection Routes

This node owns the collection workspace route family.

## Primary Routes

- `collections/[id]/+page.svelte`
  Collection readiness, files, tasks, warnings, and next action.
- `collections/[id]/objectives/+page.svelte`
  Candidate and confirmed research Objectives plus analysis progress/retry.
- `collections/[id]/objectives/[objective_id]/+page.svelte`
  Published Finding list and one selected Finding detail.
- `collections/[id]/comparisons/+page.svelte`
  Cross-paper comparison workspace.
- `collections/[id]/results/*`
  Comparable-result drilldown.
- `collections/[id]/documents/*`
  Parsed-paper reading and exact Source verification.
- `collections/[id]/materials/*`
  Material and sample-matrix projections.
- `collections/[id]/assistant/+page.svelte`
  Collection-bound assistant grounded on published, reviewed Findings.
- `collections/[id]/graph/+page.svelte`
  Secondary graph projection.

## Objective Interaction

The user-facing hierarchy is:

```text
Research Objective
  -> Findings list
  -> selected Finding
     -> Relation
     -> applicability Context
     -> exact Evidence excerpts and Source links
     -> Derivation audit
     -> feedback action
```

Objective confirmation state and analysis execution state are separate. The
page handles these states explicitly:

- candidate: confirm is the primary action;
- confirmed without analysis: start analysis;
- queued/running: poll and show current phase/document progress;
- failed without a published result: retry;
- failed with a published result: keep the prior Findings visible and offer
  retry;
- succeeded: show Findings from the published analysis version.

Finding and Evidence requests always include the published `analysis_version`.
The UI keeps internal IDs out of presentation while retaining them for API
identity and source navigation. Evidence displays the exact returned
`source_excerpt`, paper/page metadata, and a document link carrying the stable
Source locator.

## Product Boundary

The collection comparison workspace remains the Lens v1 primary analysis
surface. Objective Findings are the expert review and downstream grounding
surface; they do not introduce a second Goal/Task/Workspace product concept.
Materials, graph, assistant, and experiment plans consume published Findings or
other canonical Core artifacts and do not reconstruct an alternate conclusion
model.

## Current Contract Docs

- [`../../../../docs/contracts/research-objective-workspace-contract.md`](../../../../docs/contracts/research-objective-workspace-contract.md)
  Canonical Objective, Finding, Evidence, lifecycle, and browser contract.
- [`../../../../docs/contracts/research-view-aggregation-contract.md`](../../../../docs/contracts/research-view-aggregation-contract.md)
  Material/document aggregation contract.
- [`../../../../docs/decisions/rfc-comparison-result-document-product-flow.md`](../../../../docs/decisions/rfc-comparison-result-document-product-flow.md)
  Comparison, result, and document product flow.
- [`../../../../docs/decisions/rfc-pdf-backed-document-workbench.md`](../../../../docs/decisions/rfc-pdf-backed-document-workbench.md)
  PDF-backed Source verification behavior.

Route components use helpers from `../_shared/`; they do not implement a second
API client or normalize retired payloads.
