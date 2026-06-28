# Collection Routes

This node owns the collection workspace route family in the frontend.

## Scope

- `collections/[id]/+layout.svelte`
- `collections/[id]/+page.svelte`
- `collections/[id]/objectives/+page.svelte`
- `collections/[id]/objectives/[objective_id]/+page.svelte`
- `collections/[id]/materials/+page.svelte`
- `collections/[id]/materials/[material_id]/+page.svelte`
- `collections/[id]/documents/+page.svelte`
- `collections/[id]/evidence/+page.svelte`
- `collections/[id]/comparisons/+page.svelte`
- `collections/[id]/assistant/+page.svelte`
- `collections/[id]/documents/[document_id]/+page.svelte`

## Responsibilities

- render the collection workspace
- render collection-level research objectives and objective-scoped logic-chain
  workspaces with paper coverage, evidence units, source links, and extraction
  diagnostics
- render collection-level document profile screening signals
- render canonical collection materials, collection-scoped material profiles, and
  material research understanding as a More / material dossier surface
- render collection-level evidence cards and source-anchor entry points
- render global comparison review as a More / All Comparisons surface
- render the collection-bound AI research copilot as a top-level collection tab
  with explicit answer source modes and clickable document/evidence source links
  back to Core-owned surfaces
- render document detail as a Markdown-first paper reader from parsed Source
  artifacts as soon as document content exists, with PDF/source preview kept as
  an optional reference view and structured extraction details available as an
  explicit split-view expansion only after downstream Core artifacts are ready
- coordinate file upload and task-start actions
- poll task status and artifact readiness
- surface graph, research-understanding, evidence, and comparison capabilities
  to the user
- render research understanding as an expert review workspace by default:
  users scan claims first, then inspect linked relations, evidence, context,
  support status, paper count, and evidence count; internal claim/evidence ids
  remain hidden binding data for feedback, curation, source navigation, and
  audit details
- keep source traceback on the document page user-facing: parsed Markdown is
  the default reading surface, original PDF/PDF.js preview remains available
  for evidence location and page-level fallback when precise regions are missing,
  and block IDs stay diagnostic-only

## Local Docs

- [`../../../../docs/decisions/rfc-evidence-chain-product-surface-delivery-roadmap.md`](../../../../docs/decisions/rfc-evidence-chain-product-surface-delivery-roadmap.md)
  Shared cross-module roadmap and overall delivery order for the evidence-chain
  wave
- [`../../../../docs/decisions/rfc-comparison-result-document-product-flow.md`](../../../../docs/decisions/rfc-comparison-result-document-product-flow.md)
  Shared product-flow decision for comparison, result, and document drilldown
- [`../../../../docs/contracts/research-view-aggregation-contract.md`](../../../../docs/contracts/research-view-aggregation-contract.md)
  Shared frontend/backend target contract for paper matrices, collection
  comparable groups, cross-paper matrices, and evidence-backed values
- [`../../../../docs/contracts/research-objective-workspace-contract.md`](../../../../docs/contracts/research-objective-workspace-contract.md)
  Shared frontend/backend contract for objective-first workspace routes,
  payloads, readiness, and paper-frame rendering
- [`../../../docs/research-view-aggregation/README.md`](../../../docs/research-view-aggregation/README.md)
  Frontend implementation topic for research-view aggregation navigation,
  route state, matrices, evidence drawers, and debug placement
- [`core-derived-graph-structure-and-drilldown-frontend-alignment-plan.md`](core-derived-graph-structure-and-drilldown-frontend-alignment-plan.md)
  Frontend-local graph cutover plan for the lean graph contract, canonical
  drilldown, and neighbors expansion
- [`graph-exploration-interaction-and-layout-proposal.md`](graph-exploration-interaction-and-layout-proposal.md)
  Follow-on proposal for graph focus, neighborhood expansion gestures, and
  in-node card layout on the Cytoscape graph page
- [`comparable-result-semantic-artifact-frontend-alignment-plan.md`](comparable-result-semantic-artifact-frontend-alignment-plan.md)
  Frontend-local plan for preserving semantic comparison artifact state and
  graph readiness semantics during the comparable-result rollout
- [`comparable-result-stale-semantics-frontend-correctness-plan.md`](comparable-result-stale-semantics-frontend-correctness-plan.md)
  Frontend-local child plan for preserving backend stale artifact semantics in
  workspace normalization and fallback surface-state logic
- [`materials-comparison-v2-frontend-alignment-plan.md`](materials-comparison-v2-frontend-alignment-plan.md)
  Frontend-local contract cutover plan for the nested comparisons response
- [`collection-main-flow-frontend-test-plan.md`](collection-main-flow-frontend-test-plan.md)
  Frontend-local child plan for page-level coverage of the collection main flow
  from workspace through result and document drilldown
- [`collection-ui-restructure-proposal.md`](collection-ui-restructure-proposal.md)
  Follow-on collection UI restructuring proposal for state hierarchy and page
  information architecture
- [`legacy-route-alias-cleanup-plan.md`](legacy-route-alias-cleanup-plan.md)
  Frontend-local plan for removing redirect-only collection route aliases while
  keeping active backend APIs intact
- [`document-result-evidence-chain-proposal.md`](document-result-evidence-chain-proposal.md)
  Frontend-local proposal for reading documents and results as variant dossiers,
  result chains, and result series
- [`document-evidence-review-split-view-plan.md`](document-evidence-review-split-view-plan.md)
  Frontend-local plan for the document detail split view that aligns source
  text with selected evidence chains
- [`document-pdfjs-reader-implementation-plan.md`](document-pdfjs-reader-implementation-plan.md)
  Frontend-local implementation plan for replacing the simulated source reader
  with a PDF.js reader and custom source highlight layer
- [`../../../../docs/decisions/rfc-pdf-backed-document-workbench.md`](../../../../docs/decisions/rfc-pdf-backed-document-workbench.md)
  Shared frontend/backend plan for making the document detail route a
  PDF-backed paper understanding workbench with locator fallback
- [`claim-traceback-navigation-contract.md`](claim-traceback-navigation-contract.md)
  Claim-to-source navigation contract for comparison, result, and document
  evidence-panel traceback behavior

## Dependency Rule

Route components here should use shared helpers from `../_shared/` for API
access, formatting, and cross-route support rather than re-implementing those
concerns locally.
