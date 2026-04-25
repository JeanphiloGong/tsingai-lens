# Shared Route Support

This node owns browser-side helpers that are shared across frontend routes.

## Scope

- same-origin API request helpers
- collection, file, task, graph, protocol, and workspace clients
- i18n and theme support
- shared route notices and utility functions

## Responsibilities

- keep route data access consistent with the `/api/*` and `/api/v1/*` contract
- centralize browser error handling and shared formatting logic
- prevent route components from duplicating API and state-shaping helpers

## Important Files

- `api.ts`
  Base request helpers
- `collections.ts`, `files.ts`, `tasks.ts`, `protocol.ts`
  Domain-specific API wrappers
- `i18n.ts`
  Shared translations and labels
