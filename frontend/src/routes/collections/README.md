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
  back to Core-owned surfaces; goal-scoped experiment readiness links send
  experts back to the review queue, training-ready findings, or protocol draft
  action according to the current curated Finding state, and saved protocol
  drafts preserve review-gate and used-evidence metadata for later audit;
  saved Goal Copilot plans show whether their exact Finding/evidence source
  version is current, stale, or unverified, and only current plans can enter
  the ready-for-review state
- render document detail as a Markdown-first paper reader from parsed Source
  artifacts as soon as document content exists, with PDF/source preview kept as
  an optional reference view and structured extraction details available as an
  explicit split-view expansion only after downstream Core artifacts are ready
- coordinate file upload and task-start actions
- poll task status and artifact readiness
- surface graph, research-understanding, evidence, and comparison capabilities
  to the user
- surface confirmed-goal review progress on the objectives page so experts can
  see training-ready, message-exportable, protocol-ready experiment-input, and
  still-unreviewed finding counts before opening individual goal workspaces,
  with top review-priority diagnostics and pending review actions linking
  directly to the next candidate finding when the dataset summary provides one
- render research understanding as an expert review workspace by default:
  users scan Findings first, then inspect linked relations, evidence, context,
  support grade, review status, paper count, and evidence count; finding
  evidence displays the selected source quote first, keeps the full parsed
  source block in an expandable audit section with paper/page/heading/block
  provenance, and remains clickable back to the document reader; internal
  finding/claim/evidence ids remain hidden binding data for feedback, curation,
  source navigation, audit details, and review-queue deep links that open a
  specific finding for accept/reject/correct review; expert review progress uses
  dataset review-candidate counts as the canonical remaining-work number so
  primary paper-level Findings that still need human confirmation are included,
  while the separate evidence-repair filter only narrows to Findings whose
  evidence, support, or projection needs closer inspection; Finding detail also
  shows training-message diagnostics and protocol-readiness gaps from the
  dataset sample so experts can tell whether a Finding is ready after review or
  needs variable, direction, scope, support, message, or traceable-evidence
  correction before training export or experiment drafting; Finding
  detail also shows the selected candidate's position in the active review queue and
  prioritizes the next review action for table-row checks, conflict resolution,
  mechanism-evidence decisions, paper-level scope limits, and continuous
  accept/reject/correct review; the review loop exposes the decision template,
  decision board TSV, agent review prompts, and review packet download actions
  whenever review candidates remain; the in-browser batch import accepts reviewed JSONL rows or
  spreadsheet-filled TSV decision boards and checks them against the current
  dataset before writing labels; the dataset panel surfaces optimization
  hotspots by variable, outcome, direction, and evidence role so repeated
  expert-review risks are visible before prompt or model tuning; when
  the backend dataset sample provides an acceptance gate, the detail view also
  shows whether direct accept is allowed, whether correction is required first,
  and the expert checks that must be completed before the finding becomes
  training-ready; hard `accept_blockers` disable direct accept even when a
  stale or edited row says accept is allowed;
  when the dataset sample provides a `review_decision_hint`, the detail view
  surfaces the next review decision, blocked actions, and accept-blocking
  reasons without showing raw JSON or internal identifiers;
  the batch decision
  import panel treats unconfirmed `agent_review` rows as review drafts and
  sends human-confirmed agent review rows to the backend import service, which
  applies the canonical accept/reject/correct conversion rules; dry-runs also
  show affected-goal readiness counts and pending accept/reject/correct counts
  plus the expert satisfaction gate status and blocking reasons, so experts
  can judge whether a batch will create training-ready, exportable, or
  protocol-ready samples before import
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
