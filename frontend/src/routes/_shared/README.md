# Shared Route Support

This node owns browser-side helpers shared across frontend routes.

## Responsibilities

- keep requests on the same-origin `/api/*` and `/api/v1/*` contract;
- centralize authentication expiry and API error handling;
- expose typed clients for collection, Source, Core, Objective, comparison,
  assistant, and workspace resources;
- keep formatting, translations, graph projection, and task-state shaping out
  of route components.

## Important Files

- `api.ts`
  Base request helpers and shared HTTP error behavior.
- `collections.ts`, `files.ts`, `tasks.ts`
  Collection import, build, and progress contracts.
- `researchView.ts`
  Material/document aggregation plus the canonical Objective API client. The
  Objective flow reads summary/analysis state, paginated Findings, one Finding
  detail, and paginated versioned Evidence. Feedback, curation, and dataset
  export use only `(collection_id, objective_id, analysis_version, finding_id)`.
- `graph.ts`
  Browser graph projection for Objective, document, Evidence, comparison,
  material, property, test-condition, and baseline nodes.
- `goalSessions.ts`
  Collection-bound assistant sessions and Finding-grounded messages.
- `experimentPlans.ts`
  Objective-scoped, human-editable experiment-plan drafts grounded in reviewed
  Finding Evidence.
- `i18n.ts`
  Shared labels for active routes and states.

There is one browser contract. Do not add alternate API origins, compatibility
normalizers, or parallel Objective result types.
