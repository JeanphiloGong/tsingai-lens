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
     -> factors, outcome, direction, and synthesis status
     -> baseline / target / reported-result comparison
     -> typed scientific context, deterministic analysis boundaries, and mechanisms
     -> PaperContribution bindings
     -> exact Evidence excerpts and Source links
     -> feedback action
```

Objective confirmation state and analysis execution state are separate. The
page handles these states explicitly:

- candidate: confirm is the primary action;
- confirmed without analysis: start analysis;
- queued/running: poll and show current phase/document progress;
- failed without a published result: retry;
- failed with a published result: identify both the displayed published version
  and failed retry version, keep the prior Findings visible, and offer retry;
- succeeded with Findings: show Findings from the published analysis version;
- succeeded without Findings: state that analysis completed but the inspected
  Evidence did not form a directly comparable Finding.

Published Finding metadata shows the model recorded for that published analysis,
not the model attached to a newer active or failed retry. Historical analyses
without model metadata are labeled explicitly instead of guessing a model.

The Finding list returns the complete display shape. Selection reuses that item
and loads only its paginated Evidence with the published `analysis_version`;
stale rapid-selection responses are discarded.
The UI keeps internal IDs out of presentation while retaining them for API
identity and source navigation. Evidence displays the exact returned
`source_excerpt` once, shows baseline/target/result fields structurally, uses
document profile titles for paper labels, and links to the stable Source
locator. Only papers with matched Evidence receive full source groups; papers
without Evidence are reduced to one aggregate status line, and an entirely
empty result uses one collection-level empty state. Jointly changed variables
remain one Evidence row, direct rows identify support or contradiction and
direction, empty context categories are omitted, and mechanisms link to their
exact supporting Evidence.

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
