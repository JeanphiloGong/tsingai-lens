# Shared Route Support

This node owns browser-side helpers that are shared across frontend routes.

## Scope

- same-origin API request helpers
- collection, file, task, graph, goal-session, material review report, and
  workspace clients
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
  profiles, paper coverage, sample matrices, comparable groups, condition
  series, and evidence-backed values
- `materialReviewReport.ts`
  Material review report status, generation, Markdown preview, and PDF artifact
  URL helper for collection-scoped material dossiers
- `goalSessions.ts`
  Collection-bound goal session API helper for copilot context, messages,
  answer source modes, and evidence references
- `i18n.ts`
  Shared translations and labels
