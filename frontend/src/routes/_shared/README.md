# Shared Route Support

This node owns browser-side helpers shared across frontend routes.

## Responsibilities

- keep requests on the same-origin `/api/*` and `/api/v1/*` contract;
- centralize authentication expiry and API error handling;
- expose typed clients for collection, Source, Objective/Finding,
  assistant, and workspace resources;
- keep formatting, translations, and task-state shaping out
  of route components.

## Important Files

- `api.ts`
  Base request helpers and shared HTTP error behavior.
- `collections.ts`, `files.ts`, `tasks.ts`
  Collection import, build, and progress contracts.
- `researchView.ts`
  Canonical Objective/Finding API client. The Objective flow reads
  summary/analysis state, paginated Findings, one Finding detail, and paginated
  versioned Evidence. It also reads the deterministic Evidence Map for one
  Objective's published analysis; that read model does not create a second
  research identity. Feedback, curation, and dataset export use only
  `(collection_id, objective_id, analysis_version, finding_id)`.
- `chatSessions.ts`
  Collection-bound Research Agent sessions, typed trajectories, capability
  results, and exact write decisions.
- `experimentPlans.ts`
  Objective-scoped, human-authored experiment-plan drafts. Historical plans
  may retain source provenance returned by the API.
- `i18n.ts`
  Shared labels for active routes and states.

There is one browser contract. Do not add alternate API origins, compatibility
normalizers, or parallel Objective result types.
