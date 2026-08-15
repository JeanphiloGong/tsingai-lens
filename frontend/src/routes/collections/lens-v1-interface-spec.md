# Lens V1 Frontend Interface Spec

## Purpose

This document defines the maintained collection-facing information
architecture and browser behavior. It complements the backend API contract; it
does not add alternate payloads or compatibility routes.

## Product Direction

Lens v1 supports traceable cross-paper research comparison:

```text
collection workspace
  -> comparisons and results
  -> research Objectives and Findings
  -> exact document Evidence
  -> reviewed downstream assistant or experiment plan
```

Comparison remains the primary collection analysis surface. Objective Findings
provide the expert synthesis/review surface. Documents provide source
verification. Graph and protocol are secondary.

## Collection Navigation

- `/collections/[id]`
  Workspace, files, task progress, warnings, and next action.
- `/collections/[id]/comparisons`
  Primary cross-paper comparison table.
- `/collections/[id]/documents`
  Paper inventory and source reading entry.
- `/collections/[id]/objectives`
  Candidate/confirmed research Objectives and analysis lifecycle.
- `/collections/[id]/objectives/[objective_id]`
  Finding review workspace.
- `/collections/[id]/results/*`
  Comparable-result drilldown.
- `/collections/[id]/materials/*`
  Material/sample projections.
- `/collections/[id]/assistant`
  Collection-bound assistant grounded on reviewed published Findings.
- `/collections/[id]/protocol/*`
  Conditional downstream protocol views.
- `/collections/[id]/graph`
  Secondary graph exploration.

No standalone report, Markdown answer, or alternate Goal-result page is part of
the target interface.

## Workspace

The collection workspace shows:

- collection metadata and document count;
- latest build state and current stage;
- actionable failure details and retry;
- Source/Core readiness and warnings;
- a primary next action.

Primary action order:

1. upload when no files exist;
2. monitor when a build is queued/running;
3. retry when the latest build failed;
4. open comparisons when comparison output exists;
5. open documents when Source exists but semantic output is incomplete.

The workspace does not expose retired internal pipeline stages as product
concepts.

## Comparisons And Results

The comparisons page is optimized for scanning material, process, property,
baseline, test conditions, comparability, and warnings. A row opens canonical
result detail; Evidence and document source are secondary audit actions.

The result page preserves normalized values, conditions, provenance, and
source links. It never reconstructs Objective Findings from comparison rows.

## Research Objectives

The Objective list separates:

- confirmation state: `candidate | confirmed`;
- active analysis state: `queued | running | succeeded | failed`;
- published result availability.

Actions are state-specific:

- candidate: Confirm;
- confirmed without analysis: Analyze;
- queued/running: show phase and current paper, then poll;
- failed: Retry;
- succeeded: Open Findings.

When a retry fails but an older published version exists, the page keeps those
published Findings accessible and shows the failed retry separately.

## Finding Workspace

The Objective detail page has two levels:

1. a compact Finding list;
2. one selected Finding detail.

The list shows the statement, synthesis status, qualitative certainty, and
directly contributing paper count. It does not repeat the selected detail's
factor/outcome relation or expose internal IDs.

The selected detail shows:

- the Finding statement, factors, outcome, direction, and attribution scope;
- baseline, target, reported result, and comparability from structured Evidence;
- typed material, sample, process, and test scientific context;
- deterministic analysis boundaries and aggregate status counts for PaperContributions
  without Evidence;
- subordinate mechanisms with translated relation and assertion strength;
- exact Evidence excerpts grouped by contribution role;
- titled paper/page/source metadata and Open source action;
- one Feedback action that expands the review form.

Feedback uses `analysis_version + finding_id`. The list response already
contains the complete Finding display shape, so changing selection reuses that
item and loads only its Evidence. Stale rapid-selection responses are
discarded. Only contributions with matched Evidence receive full paper groups;
empty contributions collapse into one aggregate status line. When every
contribution is empty, the section shows one collection-level empty state
instead of repeated paper placeholders. One Evidence comparison remains one
row even when factors changed jointly; the row identifies support or
contradiction and retains the reported direction. Empty context categories are
omitted, and each mechanism links to its exact mechanism-context Evidence.

## Document Verification

Document detail is a parsed-paper reading surface with optional PDF/source
reference. A source deep link carries `source_ref` and page. The page scrolls or
selects the stable parsed block/table/figure when possible and falls back to the
page-level source view when exact geometry is unavailable.

Visible source labels use paper title, section, table/figure label, page, and
quote. Raw internal IDs remain in debug details only.

## Assistant And Experiment Plans

The assistant distinguishes:

- collection-grounded answer;
- collection-limited answer;
- general fallback/background.

Objective-focused grounded answers consume bounded, training-ready published
Findings and return visible source links. Saved assistant-generated experiment
plans retain analysis version, Finding fingerprint, Evidence fingerprint, and
Evidence IDs. Plans remain editable drafts and display stale source status when
any underlying snapshot changes.

## Graph

The graph supports Objective, document, Evidence, comparison, material,
property, test-condition, and baseline nodes. Default layout is layered.
Selecting a node shows its canonical object/source links. The graph does not
own scientific conclusions or analysis lifecycle.

## Shared Data Rules

- Use the same-origin helper in `_shared/api.ts`.
- `researchView.ts` is the single Objective/Finding/Evidence browser client.
- Paginated responses retain `offset`, `limit`, and `total`.
- Every Finding/Evidence response retains `analysis_version`.
- Do not add fallback response normalizers for retired fields.
- Do not derive a second conclusion object from Finding detail.
- Keep server error text actionable but do not show stack traces or raw payload
  dumps in the main interface.

## Responsive Rules

- On desktop, a sticky compact Finding list and the selected review detail form
  a two-column master-detail workspace; feedback opens on demand near the end
  of the evidence review.
- On mobile, the Finding list precedes the selected detail as clearly separated
  full-width regions.
- On mobile, tables become scrollable or stacked without truncating statement
  meaning or source quotes.
- Fixed controls keep stable dimensions; long scientific terms wrap.
- No control or label may overlap adjacent content.

## Verification

Unit and browser checks cover:

- candidate confirmation;
- queued/running current-paper progress;
- failed retry with and without prior published Findings;
- Finding selection and detail;
- exact Evidence excerpt and source jump;
- feedback submission;
- assistant grounding on published Findings;
- mobile and desktop layout without overlap.

## Related Docs

- [`../../../../docs/contracts/research-objective-workspace-contract.md`](../../../../docs/contracts/research-objective-workspace-contract.md)
- [`../../../../backend/docs/specs/api.md`](../../../../backend/docs/specs/api.md)
- [`../../../../docs/decisions/rfc-comparison-result-document-product-flow.md`](../../../../docs/decisions/rfc-comparison-result-document-product-flow.md)
- [`../../../../docs/decisions/rfc-pdf-backed-document-workbench.md`](../../../../docs/decisions/rfc-pdf-backed-document-workbench.md)
