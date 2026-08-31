# Collection Routes

This node owns the Collection route family.

## Primary Routes

- `collections/[id]/+page.svelte`
  Research-first Collection readiness and next action. It summarizes current
  papers, preparation, and Objective availability; ready papers stay out of the
  main view, while papers requiring preparation or retry remain available in an
  expandable attention section. Objective discovery uses the complete current
  ready-paper set without restoring the retired Collection build contract.
  The overview keeps a persistent four-stage research strip and, while paper
  preparation tasks are queued or running, adds an aggregate progress bar with
  ready/total papers, active task count, and weighted task completion. It does
  not present one task as the progress of the entire collection.
- `collections/[id]/objectives/+page.svelte`
  Candidate and confirmed research Objectives plus analysis progress/retry.
- `collections/[id]/objectives/[objective_id]/+page.svelte`
  Published Finding list and one selected Finding detail.
- `collections/[id]/comparisons/+page.svelte`
  Published cross-paper Finding overview grouped by Objective.
- `collections/[id]/graph/+page.svelte`
  Secondary Objective Evidence Map. It selects one published Objective and
  shows deterministic Finding, Evidence, exact Source, paper, and coverage
  relationships without restoring the retired collection-wide Graph contract.
- `collections/[id]/documents/*`
  Parsed-paper reading and exact Source verification.
- `collections/[id]/assistant/+page.svelte`
  Collection-bound Research Agent conversation with transient streamed text,
  capability activity, structured results, canonical resource links, and exact
  write approval.
  Its research-process capability projects the same current Documents and
  persisted per-paper preparation tasks used by the Collection page; Chat does
  not own a second progress model or expose model reasoning and retry internals.
  The Agent may propose preparing exact papers. The action requires approval,
  returns their queued or reused tasks, and does not discover or confirm an
  Objective or start deep Objective analysis.
  For a researcher-authored question, the Agent can preview a bounded paper
  scope without claiming that mapped relationships or review citations are
  Evidence. Creating the untested Objective candidate requires approval, and
  starting its canonical Objective analysis requires a separate approval. The
  Agent can then inspect the same persisted analysis state and paper progress
  shown by the Objective workspace.
  This route remains available before Objective discovery finishes so the
  researcher can converse, inspect readiness, and form Objective proposals;
  capabilities must still expose missing or incomplete collection artifacts.

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

Objective confirmation state and analysis execution state remain separate
domain states, but one analysis command owns the approval-and-queue transition.
Before that command, the Objective list prioritizes active, confirmed, and
published work, then the highest-ranked candidates. Five Objectives are shown
at a time in that order, with local pagination over the complete loaded list.
Seed papers are labeled as the sources from which the question was formed; they
are not treated as its complete analysis recommendation. Choosing to start a new
analysis loads the Objective's collection-wide scope preview and uses all
current `recommended_document_ids` that are ready. A small scope-adjustment
action opens the separate confirmation dialog, where system recommendations are
selected, `needs_inspection` papers are visible but unselected, and current
exclusions remain unselected. The request sends only those exact ready
`document_ids`. Editing one Objective does not change another.
Processing and failed papers cannot be selected and do not block ready papers.
Retry reuses the failed analysis version's frozen paper IDs without recalculating
the scope. An Objective with no recommended papers requires an explicit paper
selection before analysis.
Objective search matches the question, material scope, variables, and outcomes
across the complete loaded list, then paginates matching results five at a time.
Workflow-state filtering distinguishes pending, active, published, and failed
analysis; changing a filter resets to the first page so no matching Objective is
hidden by a stale page position.
The page handles these states explicitly:

- candidate: confirm and analyze is the primary action;
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
locator. Within each paper, Evidence is grouped by Source kind and stable
`source_ref`; the UI reports Source and comparison counts separately, identifies
a shared baseline across repeated comparisons, and collapses multi-comparison
Sources by default without removing their row-level traceback. A shared-baseline
matrix is shown only when the Source, comparison axes, baseline label, baseline
result, outcome, unit, and comparability all agree. It shows the baseline once,
then target condition, reported result, signed delta, direction, source link, and
an on-demand excerpt per comparison; conflicting baselines remain separate
Evidence records. On narrow screens, matrix rows become labeled vertical fields
instead of relying on horizontal scrolling. Only papers with matched Evidence
receive full source groups; papers without Evidence are reduced to one aggregate
status line, and an entirely empty result uses one collection-level empty state.
Jointly changed variables remain one Evidence row, direct rows identify support
or contradiction and direction, empty context categories are omitted, and
mechanisms link to their exact supporting Evidence.

## Product Boundary

The collection comparison page is a read-only overview of published
Objective Findings. It does not rebuild conclusions from legacy comparison
rows, Evidence cards, material projections, or collection-wide graph
projections. The Objective Evidence Map is a read-only view of those same
published records, not another aggregate or analysis path. The Objective page
owns the single confirmation-and-analysis command; the Finding page owns expert
review; the document reader owns Source verification.
The Research Agent and experiment plans may consume published Findings, but
they do not introduce a second conclusion identity.

The Papers route reports the complete profiled collection size while rendering
one bounded, compact page. Its title/filename search, document-type filter, and
parsing-warning filter are collection-wide and run before pagination. Page,
search, or filter failures remain explicit instead of presenting one partial
page as the whole collection. Routine internal Document IDs stay out of the
paper list; exact Source navigation continues through the canonical paper
reader.

## Current Contract Docs

- [`../../../../docs/contracts/research-objective-workspace-contract.md`](../../../../docs/contracts/research-objective-workspace-contract.md)
  Canonical Objective, Finding, Evidence, lifecycle, and browser contract.
- [`../../../../docs/decisions/rfc-pdf-backed-document-workbench.md`](../../../../docs/decisions/rfc-pdf-backed-document-workbench.md)
  PDF-backed Source verification behavior.

Route components use helpers from `../_shared/`; they do not implement a second
API client or normalize retired payloads.
