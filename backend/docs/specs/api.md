# API Contract

This document describes the maintained Lens v1 HTTP contract. The generated
OpenAPI document at `/api/openapi.json` is the field-level runtime reference;
this file owns resource boundaries and cross-endpoint semantics.

## Conventions

- Product APIs use `/api/v1/*`.
- API documentation uses `/api/docs`, `/api/redoc`, and `/api/openapi.json`.
- Browser requests use bearer authentication after `POST /api/v1/auth/login`.
- Every business response carries `X-Request-ID`.
- A collection is the primary working scope; a document is a source inside it.
- PostgreSQL is the structured runtime authority.
- GET requests never trigger LLM analysis.
- Retired payloads and endpoints are not accepted through aliases or fallback
  parsers.

## Resource Map

### Authentication

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Invalid or expired credentials return `401`. The frontend clears local auth
state and returns the user to login.

### Collections, Files, And Builds

- `GET /api/v1/collections`
- `POST /api/v1/collections`
- `GET /api/v1/collections/{collection_id}`
- `DELETE /api/v1/collections/{collection_id}`
- `GET /api/v1/collections/{collection_id}/files`
- `POST /api/v1/collections/{collection_id}/files`
- `GET /api/v1/collections/{collection_id}/tasks`
- `POST /api/v1/collections/{collection_id}/tasks/build`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/artifacts`
- `GET /api/v1/collections/{collection_id}/workspace`

Collection build parses Source, creates document profiles and reusable paper
facts, and discovers Objective candidates. It does not run confirmed Objective
deep analysis. Task responses expose current stage, progress, terminal error,
and retry-appropriate status; a failed task is never presented as a new task.

### Goal Intake And Assistant Sessions

- `POST /api/v1/goals/intake`
- `POST /api/v1/goal-sessions`
- `GET /api/v1/goal-sessions/{session_id}`
- `PATCH /api/v1/goal-sessions/{session_id}`
- `GET /api/v1/goal-sessions/{session_id}/messages`
- `POST /api/v1/goal-sessions/{session_id}/messages`

Goal intake seeds a collection; it is not a second research-result identity.
An assistant session may set `focused_objective_id`. Objective-grounded answers
consume bounded published Findings and exact Evidence links. The response
distinguishes collection-grounded, collection-limited, and general content.

### Research Objectives

- `GET /api/v1/collections/{collection_id}/objectives`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}`
- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/confirm`
- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/analysis`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/analysis`

`ResearchObjective` is the only business aggregate root. Its identity is
`(collection_id, objective_id)`. The Objective response contains:

- question and material/process/property/comparison scope;
- included and excluded document IDs;
- `confirmation_status`: `candidate | confirmed`;
- `active_analysis_version` and `published_analysis_version`;
- `active_analysis`, `published_analysis`, and warnings on detail responses.

`ObjectiveAnalysis` is addressed by the Objective identity plus a positive
`analysis_version`. It contains immutable Source/pipeline/model/prompt lineage,
`queued | running | succeeded | failed` status, phase, document progress,
current document, terminal error, and timestamps.

Confirmation does not start analysis. `POST .../analysis` queues the next
version and returns immediately. The frontend polls `GET .../analysis`. Retry
allocates a new version. A failed active version leaves the prior published
version readable. Only a complete succeeded version can become published.

### Published Findings And Evidence

- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence`

Finding and Evidence list endpoints support `offset` and `limit`. All responses
include an explicit `analysis_version`. If omitted from the query, the backend
uses the published Objective version. Evidence accepts an optional `finding_id`
filter.

A Finding contains:

- `finding_id`, `finding_level`, statement, variables, mediators, outcomes,
  direction, and scope summary;
- evidence strength, generalization status, paper count, confidence, and
  display rank;
- ordered Relations;
- structured Context;
- Derivation with contributing documents, supporting/contradicting Evidence,
  comparison status, and rationale.

An Evidence record contains:

- `evidence_id`, `document_id`, `source_kind`, and stable `source_ref`;
- exact `source_excerpt`, page numbers, and related typed Source locators;
- evidence role and selection/extraction state;
- normalized material, sample, process, test, value, baseline, interpretation,
  and join fields.

The consumer identity is always:

```text
(collection_id, objective_id, analysis_version, finding_id)
```

A paper Finding has direct-result support from one paper and remains
paper-level. A cross-paper Finding requires comparable direct results from at
least two distinct papers. Context-only Evidence cannot establish an outcome.

### Finding Feedback, Curation, And Dataset Export

- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/feedback`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/feedback`
- `PUT /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/curation`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/curation`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/finding-dataset`
- `GET /api/v1/collections/{collection_id}/finding-dataset`
- `GET /api/v1/collections/{collection_id}/finding-gold-draft`

Feedback requires `analysis_version`, `review_status`, and `issue_type`.
Curation requires `analysis_version`, a corrected statement, and version-local
Evidence IDs. Unknown, stale, unpublished, and cross-version references return
`404` or `409` and are never silently rebound.

Dataset export supports `format=json | training_jsonl` plus optional
`label_status` and `dataset_use_status` filters. `objective_finding_dataset.v1`
includes system prediction, optional expert target, and exact Evidence excerpts
with document/page/locator provenance. `training_jsonl` contains one
`{messages, metadata}` object per line and omits samples without valid training
messages. IDs preserve lineage; source text is part of model input.

### Objective Experiment Plans

- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans`
- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans`
- `PATCH /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans/{plan_id}`

Plans are human-editable downstream drafts, not scientific source records.
Assistant-created plans must reference a grounded message from the same user,
collection, and Objective. The service records source Finding/Evidence lineage
and rejects stale or ungrounded protocol input.

### Research Aggregation

- `GET /api/v1/collections/{collection_id}/research-view`
- `GET /api/v1/collections/{collection_id}/materials`
- `GET /api/v1/collections/{collection_id}/materials/{material_id}/research-view`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/research-view`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/materials`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/materials/{material_id}/research-view`

These endpoints aggregate reusable paper facts and comparison projections into
paper coverage, sample matrices, condition series, material profiles, and
comparable groups. They do not own or duplicate Objective Findings.

### Documents And Source Verification

- `GET /api/v1/collections/{collection_id}/documents/profiles`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/profile`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/content`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/markdown`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/source`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/figures/{figure_id}/image`
- `GET /api/v1/collections/{collection_id}/references`
- `POST /api/v1/collections/{collection_id}/references/build`

The document reader shows parsed paper content and supports precise Source
navigation. A Finding Evidence link names the owning document, stable
`source_ref`, and page when available. Internal Source IDs are audit/navigation
parameters, not visible paper titles.

### Comparable Results And Comparisons

- `GET /api/v1/comparable-results`
- `GET /api/v1/comparable-results/{comparable_result_id}`
- `GET /api/v1/collections/{collection_id}/results`
- `GET /api/v1/collections/{collection_id}/results/{result_id}`
- `GET /api/v1/collections/{collection_id}/comparisons`
- `GET /api/v1/collections/{collection_id}/comparisons/{row_id}`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/comparison-semantics`

Comparable results are canonical normalized result objects. Collection
comparisons are deterministic projections with source/evidence links. They do
not create another Objective conclusion identity.

### Evidence Cards

- `GET /api/v1/collections/{collection_id}/evidence/cards`
- `GET /api/v1/collections/{collection_id}/evidence/{evidence_id}`
- `GET /api/v1/collections/{collection_id}/evidence/{evidence_id}/traceback`

These endpoints expose reusable paper-fact Evidence cards and source traceback.
They are distinct from versioned `ObjectiveEvidence` and are not accepted as a
substitute for Finding-specific Evidence membership.

### Graph

- `GET /api/v1/collections/{collection_id}/graph`
- `GET /api/v1/collections/{collection_id}/graph/nodes/{node_id}/neighbors`
- `GET /api/v1/collections/{collection_id}/graphml`

The graph is a secondary projection over canonical Objective, document,
Evidence, comparison, material, property, test-condition, and baseline records.
It has no independent scientific state.

## Error Contract

Errors use the status appropriate to the failure:

- `400`: malformed input;
- `401`: invalid or expired authentication;
- `403`: authenticated user lacks access;
- `404`: collection, Objective, Finding, Evidence, or source record is absent;
- `409`: lifecycle conflict, unpublished/stale version, or artifact not ready;
- `422`: request schema validation;
- `500/502/503`: internal or upstream service failure.

Where an endpoint returns a structured detail object, it includes a stable
`code`, user-readable `message`, and relevant resource IDs. Internal stack
traces and credentials never enter the HTTP response.

## Frontend Integration

- Use same-origin requests through the shared API helper.
- Poll only queued/running task or Objective analysis states.
- On a failed Objective analysis, show retry while retaining the last published
  Findings if one exists.
- Paginate Findings and Evidence; do not request a complete Objective object
  graph.
- Use `source_excerpt` as the displayed original Evidence and `source_ref` plus
  page for document navigation.
- Submit feedback against the selected `analysis_version + finding_id`.

## Related Docs

- [Research Objective and Finding contract](../../../docs/contracts/research-objective-workspace-contract.md)
- [Persistence model](../architecture/persistence-model.md)
- [Backend architecture overview](../architecture/overview.md)
