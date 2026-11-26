# Research Objective HTTP API

Status: target Research module contract for the module reconstruction. The current route
implementation is under `backend/controllers/core/research_objective_routes.py`. It still
serializes the full Objective in the list response and does not yet expose the dedicated detail
route described below. The V1 implementation must bring the route schemas, frontend types, and
tests to this contract.

## Conventions

- Routes use the `/api/v1` prefix and the existing authenticated session.
- The authenticated `user_id` comes from the request context. Clients do not submit it.
- Every response uses the `code/message/data/meta` envelope.
- Workspace ownership is checked before reading or changing an Objective.
- Request models reject unknown fields.

## Objective creation paths

- `POST /api/v1/workspaces/{workspace_id}/objective-discovery` accepts selected prepared
  Documents and queues or reuses an Objective Discovery PipelineRun.
- Agent `create_objective_candidate` persists a user-approved `chat_assisted` candidate.
- Agent `derive_objective` persists a candidate linked to a published parent analysis.

All three paths produce the same Research Objective lifecycle. A candidate must be confirmed
before an analysis version can be started.

## List Objective summaries

`GET /api/v1/workspaces/{workspace_id}/objectives?offset=0&limit=50`

`offset` defaults to `0`. `limit` is optional and has a maximum of `100`. When supplied, the
response contains only fields needed to sort, search, display status, and navigate to an
Objective.

| Field | Type | Meaning |
| --- | --- | --- |
| `workspace_id` | string | Resource boundary in the response envelope |
| `objectives` | object[] | Ranked candidate and confirmed Objective summaries |
| `objectives[].objective_id` | string | Stable Objective identity |
| `objectives[].rank` | integer | Current rank, at least `1` |
| `objectives[].question` | string | Research question |
| `objectives[].material_scope` | string[] | Material scope |
| `objectives[].variables` | string[] | Changed factors |
| `objectives[].outcomes` | string[] | Observed outcomes |
| `objectives[].requested_comparator` | string or null | Requested comparison |
| `objectives[].origin` | enum | `system_discovered` or `chat_assisted` |
| `objectives[].confirmation_status` | enum | `candidate` or `confirmed` |
| `objectives[].active_analysis_version` | integer or null | Current analysis version |
| `objectives[].published_analysis_version` | integer or null | Latest readable published version |
| `offset`, `limit`, `total` | integer | Pagination metadata |

The list does not expose mechanisms, constraints, source relationships, excluded Documents,
derivation basis, creator user IDs, or tool-call IDs.

## Read one Objective

`GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}`

The detail response includes the list summary fields plus the following research and lineage
fields.

| Field | Type | Meaning |
| --- | --- | --- |
| `mechanisms` | string[] | Candidate mechanisms |
| `constraints` | string[] | Research constraints |
| `seed_document_ids` | string[] | Documents that led to the question |
| `excluded_document_ids` | string[] | Explicitly excluded Documents |
| `source_relationship_ids` | string[] | Research relationships used during discovery |
| `confidence` | number | Candidate formation confidence |
| `reason` | string or null | Candidate formation reason |
| `parent_objective_id` | string or null | Parent Objective for a derived question |
| `parent_analysis_version` | integer or null | Published parent version used for derivation |
| `derivation_basis` | object[] | Finding, evidence-gap, or paper-contribution references |
| `created_at`, `updated_at` | string or null | Resource timestamps |

Creator user IDs and tool-call IDs are restricted audit data. They are not returned to ordinary
Objective clients.

## Discovery and analysis routes

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/workspaces/{workspace_id}/objective-discovery` | Queue discovery from selected prepared Documents |
| `GET` | `/api/v1/workspaces/{workspace_id}/objectives/{objective_id}/scope` | Preview recommended, review, and excluded Documents |
| `POST` | `/api/v1/workspaces/{workspace_id}/objectives/{objective_id}/analysis` | Confirm the Objective and start or reuse an analysis version |
| `GET` | `/api/v1/workspaces/{workspace_id}/objectives/{objective_id}/analysis/status` | Read lightweight progress |
| `GET` | `/api/v1/workspaces/{workspace_id}/objectives/{objective_id}/analysis` | Read active and published analysis projections |
| `GET` | `/api/v1/workspaces/{workspace_id}/objectives/{objective_id}/findings` | List published Findings |
| `GET` | `/api/v1/workspaces/{workspace_id}/objectives/{objective_id}/evidence` | List published Evidence |
| `GET` | `/api/v1/workspaces/{workspace_id}/objectives/{objective_id}/evidence-map` | Read the published Evidence map |

The analysis request contains `document_ids`. The service verifies Workspace ownership and the
Document preparation fingerprints before creating or reusing an analysis version. A successful
analysis version does not automatically mean that it has been published.

## Error semantics

| Condition | Result |
| --- | --- |
| Workspace or Objective is not visible to the user | Existing resource-not-found semantics |
| Document is outside the Workspace or its preparation changed | Reject without creating a new analysis version |
| Candidate is not confirmed | `objective_confirmation_required` |
| Parent analysis is no longer published | `objective_parent_analysis_stale` |
| Derivation basis is duplicated, cross-Objective, or technical-only | Reject the write |
| Analysis version or status does not match the active successful version | Do not advance the publication pointer |
