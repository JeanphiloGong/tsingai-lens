# Shared Route Support

This node owns browser-side helpers that are shared across frontend routes.

## Scope

- same-origin API request helpers
- collection, file, task, graph, goal-session, research-view, and workspace
  clients
- i18n and theme support
- shared route notices and utility functions

## Responsibilities

- keep route data access consistent with the `/api/*` and `/api/v1/*` contract
- centralize browser error handling and shared formatting logic
- prevent route components from duplicating API and state-shaping helpers

## Important Files

- `api.ts`
  Base request helpers
- `collections.ts`, `files.ts`, `tasks.ts`
  Domain-specific API wrappers
- `researchView.ts`
  Research-view aggregation contract helper for material summaries, material
  profiles, research understandings, research objectives, objective paper
  frames, paper coverage, sample matrices, comparable groups, condition series,
  evidence-backed values, and expert feedback/curation requests for
  research-understanding claims. Claim feedback and curations are read back by
  scope so the workbench can show saved expert review history and expert
  corrections after refresh. The same helper also reads curation-derived gold
  drafts and finding-centered dataset exports for evaluation handoff, including
  review-decision hints that tell the workbench which accept/reject/correct
  actions are allowed or blocked for a review candidate. Goal Findings retain
  their synthesis status, shared and incomparable conditions, and per-paper
  contributions so the existing detail view can explain cross-paper support
  without adding a separate frontend resource.
- `goalSessions.ts`
  Collection-bound goal session API helper for copilot context, messages,
  answer source modes, and evidence references
- `experimentPlans.ts`
  Goal-scoped experiment plan draft API helper for saving and editing
  human-reviewable protocol suggestions produced from grounded copilot answers;
  Goal Copilot saves also carry source mode, review gate, used evidence ids,
  and source-link counts in metadata so protocol drafts remain auditable
- `i18n.ts`
  Shared translations and labels
