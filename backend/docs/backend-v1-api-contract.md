# Backend V1 API Contract

## Purpose

This document defines the backend-local target HTTP contract for the Lens v1
collection comparison workflow.

It narrows the root Lens v1 definition and artifact contracts into the backend
API surfaces that frontend work should integrate against first.

It does not replace:

- [`api.md`](api.md) as the inventory of currently exposed public endpoints
- root product and architecture docs under `../docs/`
- detailed artifact field contracts in
  [`../../docs/40-specs/lens-core-artifact-contracts.md`](../../docs/40-specs/lens-core-artifact-contracts.md)

## Contract Principles

- the primary unit is the collection, not the single paper
- the primary Lens v1 surface is the collection comparison workspace
- product-facing APIs should expose workflow meaning, not raw internal artifact
  filenames
- document typing, evidence, comparison, and traceability are primary
- protocol remains a supported but secondary branch
- the API must be able to say `not_ready`, `limited`, `not_applicable`, or
  `not_comparable` instead of forcing a stronger result

## Base URL and Auth

- Base URL: `/api/v1`
- Current auth state: no authentication is enabled yet

## Acceptance Workflow

The frontend acceptance flow for Lens v1 should be:

1. create a collection
2. upload files into the collection
3. start an indexing task
4. poll task state until indexing settles
5. load the collection workspace
6. navigate from workspace into document profiles, evidence cards, and
   comparison rows
7. use protocol endpoints only when the collection is protocol-suitable

## Endpoint Roles

### Collection and task entrypoints

These endpoints remain the ingestion and orchestration entrypoints:

- `POST /api/v1/collections`
- `GET /api/v1/collections`
- `GET /api/v1/collections/{collection_id}`
- `DELETE /api/v1/collections/{collection_id}`
- `POST /api/v1/collections/{collection_id}/files`
- `GET /api/v1/collections/{collection_id}/files`
- `POST /api/v1/collections/{collection_id}/tasks/index`
- `GET /api/v1/collections/{collection_id}/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/artifacts`

These are not the main Lens v1 value surfaces, but they remain required for
collection lifecycle management.

### Primary Lens v1 surfaces

These endpoints are the target frontend integration center for Lens v1:

- `GET /api/v1/collections/{collection_id}/workspace`
  Current endpoint. Should become the workflow entry and summary surface.
- `GET /api/v1/collections/{collection_id}/documents/profiles`
  Planned endpoint. Should expose `document_profiles`.
- `GET /api/v1/collections/{collection_id}/evidence/cards`
  Planned endpoint. Should expose `evidence_cards`.
- `GET /api/v1/collections/{collection_id}/comparisons`
  Planned endpoint. Should expose `comparison_rows`.

### Secondary collection surfaces

These endpoints may remain available, but they are not the acceptance center of
Lens v1:

- `GET /api/v1/collections/{collection_id}/graph`
- `GET /api/v1/collections/{collection_id}/graphml`
- `GET /api/v1/collections/{collection_id}/reports/communities`
- `GET /api/v1/collections/{collection_id}/reports/communities/{community_id}`
- `GET /api/v1/collections/{collection_id}/reports/patterns`
- `POST /api/v1/query`

### Conditional protocol branch

These endpoints remain supported as a downstream branch:

- `GET /api/v1/collections/{collection_id}/protocol/steps`
- `GET /api/v1/collections/{collection_id}/protocol/search`
- `POST /api/v1/collections/{collection_id}/protocol/sop`

They should not imply that every collection is expected to yield trustworthy
protocol steps.

## Workspace Contract

### Route

- `GET /api/v1/collections/{collection_id}/workspace`

### Role

This is the primary Lens v1 entry surface for frontend integration.

The workspace should answer:

- what is the collection state right now
- which workflow resources are ready
- what warnings or suitability limits apply
- where the frontend should navigate next

### Current state

The current workspace payload is artifact-centric and still exposes backend
implementation details such as `sections_ready` and
`procedure_blocks_ready`.

That current shape is acceptable for migration, but it is not the desired
steady-state contract for the Lens v1 acceptance surface.

### Target fields

The target workspace contract should expose at least:

- `collection`
- `file_count`
- `status_summary`
- `workflow`
- `document_summary`
- `warnings`
- `latest_task`
- `recent_tasks`
- `capabilities`
- `links`

### Target field semantics

`workflow` should summarize readiness by product-facing workflow stage:

- `documents`
- `evidence`
- `comparisons`
- `protocol`

Each stage should use explicit states rather than raw booleans when possible,
such as:

- `not_started`
- `processing`
- `ready`
- `limited`
- `not_applicable`
- `failed`

`document_summary` should expose collection-level rollups derived from
`document_profiles`, including:

- document type distribution
- protocol suitability distribution
- collection-level suitability warnings

`warnings` should expose collection-facing issues that affect research
judgment, for example:

- review-heavy corpus
- protocol-limited corpus
- comparison-limited corpus
- missing evidence traceability

`links` should point the frontend to the primary next resources:

- document profiles
- evidence cards
- comparison rows
- protocol steps when applicable

### Compatibility rule

During migration, the backend may continue returning the current `artifacts`
object.

When both are present, frontend integrations should treat `workflow`,
`document_summary`, and `warnings` as the preferred Lens v1 contract and treat
raw artifact booleans as compatibility fields.

## Document Profiles Contract

### Route

- `GET /api/v1/collections/{collection_id}/documents/profiles`

### Role

This resource exposes `document_profiles` as the gating layer for the rest of
the Lens v1 comparison workflow.

### Minimum response shape

- `collection_id`
- `total`
- `count`
- `summary`
- `items`

`summary` should expose collection-level rollups derived from profile items.

Each item should include the minimum shared contract fields already defined in
the root spec:

- `document_id`
- `collection_id`
- `doc_type`
- `protocol_extractable`
- `protocol_extractability_signals`
- `parsing_warnings`
- `confidence`

### Integration meaning

The frontend should use this endpoint to:

- separate experimental, review, mixed, and uncertain papers
- decide whether protocol browsing should even be emphasized
- surface corpus-level warnings before users inspect comparisons

## Evidence Cards Contract

### Route

- `GET /api/v1/collections/{collection_id}/evidence/cards`

### Role

This resource exposes `evidence_cards`, which are the primary claim-centered
evidence objects in Lens v1.

### Minimum response shape

- `collection_id`
- `total`
- `count`
- `items`

Each item should expose the minimum shared evidence-card contract:

- `evidence_id`
- `document_id`
- `collection_id`
- `claim_text`
- `claim_type`
- `evidence_source_type`
- `evidence_anchors`
- `material_system`
- `condition_context`
- `confidence`
- `traceability_status`

### Integration meaning

The frontend should use this resource for:

- claim inspection
- evidence traceback
- condition-aware source review
- weak-evidence inspection before comparison judgments

## Comparison Rows Contract

### Route

- `GET /api/v1/collections/{collection_id}/comparisons`

### Role

This resource exposes `comparison_rows`, the primary collection-facing
comparison artifact in Lens v1.

### Minimum response shape

- `collection_id`
- `total`
- `count`
- `items`

Each item should expose the minimum shared comparison-row contract:

- `row_id`
- `collection_id`
- `source_document_id`
- `supporting_evidence_ids`
- `material_system_normalized`
- `process_normalized`
- `property_normalized`
- `baseline_normalized`
- `test_condition_normalized`
- `comparability_status`
- `comparability_warnings`

### Integration meaning

This is the primary collection-facing data surface for:

- identifying directly comparable results
- separating `comparable` rows from `limited`, `not_comparable`, and
  `insufficient` rows
- drilling from a collection-level comparison row back into evidence cards and
  source documents

## Protocol Branch Contract

### Retained routes

- `GET /api/v1/collections/{collection_id}/protocol/steps`
- `GET /api/v1/collections/{collection_id}/protocol/search`
- `POST /api/v1/collections/{collection_id}/protocol/sop`

### Contract rule

These endpoints remain collection-scoped, but they are conditional outputs.

They should be treated as:

- available for methods-heavy and protocol-suitable corpora
- limited or absent for review-heavy or weakly procedural corpora
- downstream of document profiling and evidence extraction rather than the Lens
  v1 backbone

## Error Contract

The backend should converge on these coarse error classes for collection-facing
workflows:

- `400` for request validation problems
- `404` for missing collection or task resources
- `409` for resources that exist conceptually but are not ready yet
- `500` for internal failures

For readiness failures, the response body should remain structured enough for
frontend handling, including:

- stable `code`
- human-readable `message`
- the relevant `collection_id` or `task_id`
- the blocked workflow stage or artifact when available

The current `protocol_artifacts_not_ready` error is compatible with this
direction and should become part of a broader readiness pattern rather than a
one-off special case.

## Migration Notes

- `api.md` remains the current public endpoint inventory
- this document defines the Lens v1 target contract the frontend should align
  to next
- current graph and protocol routes remain available during migration
- new document, evidence, and comparison resources should be introduced without
  breaking existing collection and task flows

## Related Docs

- [`api.md`](api.md)
- [`backend-domain-architecture.md`](backend-domain-architecture.md)
- [`backend-evidence-first-parsing-plan.md`](backend-evidence-first-parsing-plan.md)
- [`../../docs/40-specs/lens-v1-definition.md`](../../docs/40-specs/lens-v1-definition.md)
- [`../../docs/40-specs/lens-core-artifact-contracts.md`](../../docs/40-specs/lens-core-artifact-contracts.md)
