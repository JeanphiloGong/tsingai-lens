# Shared Route Support

This node owns browser-side helpers shared across frontend routes.

## Responsibilities

- keep requests on the same-origin `/api/*` and `/api/v1/*` contract;
- centralize authentication expiry and API error handling;
- expose typed clients for Collection, Document preparation, Source,
  Objective/Finding, and Assistant resources;
- keep formatting, translations, and Pipeline Run state presentation out
  of route components.

## Important Files

- `api.ts`
  Base request helpers and same-origin downloads. JSON uses HTTP 200 with
  `{code,message,data,meta}`; `requestJson` unwraps `data`, and business failures
  raise `ApiError(code, message, data)`. `isApiErrorCode` compares numeric business
  codes and `getApiErrorReason` reads stable `data.code` strings. Authentication
  expiry clears local auth and chat storage before redirecting, only for
  `200301` plus `authentication_required`. Network
  errors remain ordinary errors. `requestBlob` rejects JSON failures before
  saving, unwraps ordinary JSON exports, and preserves file bytes identified
  by Content-Disposition. `buildApiUrl` owns URLs for requests and streams.
- `collections.ts`, `collectionDocuments.ts`, `pipelineRuns.ts`
  Collection upload, current Document, independent preparation, and Pipeline
  Run progress contracts. Collection history uses compact run summaries; one
  run read retains complete diagnostic state. `pipelineRuns.ts` also queues
  collection-level research-question formation and reads its persisted
  `objective_discovery` Pipeline Run directly. Clients reject invalid response
  identities and required containers at the request boundary; they do not
  fabricate missing states or rebuild valid server responses.
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
  dataset export use only `(collection_id, objective_id, analysis_version,
finding_id)`. Dataset URLs preserve the selected label and dataset-use
  filters for JSON or training JSONL downloads; collection-level dataset and
  gold-draft URLs serve the corresponding collection exports.
- `chatSessions.ts`
  Collection-bound Research Agent sessions, typed trajectories, streamed text
  deltas, capability results, exact write decisions, and the bounded pending
  Source handoff between a document reader and its Collection Agent. JSON
  rejection before stream start is handled before parsing SSE; after start,
  `error` events and cancellation retain the existing recovery flow.
- `experimentPlans.ts`
  Objective-scoped, human-authored experiment-plan drafts. Historical plans
  may retain source provenance returned by the API.
- `i18n.ts`
  Shared labels for active routes and states. The selected language also updates
  the document language for assistive technology.

There is one browser contract. Do not add alternate API origins, compatibility
normalizers, or parallel Objective result types.
