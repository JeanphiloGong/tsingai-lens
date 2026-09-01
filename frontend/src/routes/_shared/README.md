# Shared Route Support

This node owns browser-side helpers shared across frontend routes.

## Responsibilities

- keep requests on the same-origin `/api/*` and `/api/v1/*` contract;
- centralize authentication expiry and API error handling;
- expose typed clients for Collection, Document preparation, Source,
  Objective/Finding, and Assistant resources;
- keep formatting, translations, and task-state shaping out
  of route components.

## Important Files

- `api.ts`
  Base request helpers and shared HTTP error behavior.
- `collections.ts`, `collectionDocuments.ts`, `tasks.ts`
  Collection upload, current Document, independent preparation, and task
  progress contracts. `tasks.ts` also queues collection-level research-question
  formation and normalizes its persisted `objective_discovery` Task.
- `researchView.ts`
  Canonical Objective/Finding API client. The Objective flow reads
  summary/analysis state, paginated Findings, one Finding detail, and paginated
  versioned Evidence. It also reads one Objective's complete deterministic
  collection Paper Map scope. Seed IDs remain question provenance; only the
  returned recommended IDs are the default analysis selection, while papers
  requiring inspection remain a user decision. Its analysis command atomically
  confirms candidate Objectives and queues analysis over exact selected ready
  `document_ids` through the same endpoint. It also reads the
  deterministic Evidence Map for one Objective's published analysis; that read
  model does not create a second research identity. Feedback, curation, and
  dataset export use only
  `(collection_id, objective_id, analysis_version, finding_id)`.
- `chatSessions.ts`
  Collection-bound Research Agent sessions, typed trajectories, streamed text
  deltas, capability results, exact write decisions, and the one-item pending
  Source handoff between a document reader and its Collection Agent.
- `experimentPlans.ts`
  Objective-scoped, human-authored experiment-plan drafts. Historical plans
  may retain source provenance returned by the API.
- `i18n.ts`
  Shared labels for active routes and states.

There is one browser contract. Do not add alternate API origins, compatibility
normalizers, or parallel Objective result types.
