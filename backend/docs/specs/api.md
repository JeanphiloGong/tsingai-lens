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
The build request accepts `mode: standard | fast` and defaults to `standard`.
The selected mode is persisted before dispatch and determines the runtime
dependency graph for that task.

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
- `GET /api/v1/collections/{collection_id}/paper-study-inventory`
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
- ordered `source_relationship_ids` linking the Objective to paper-study
  relationships;
- `active_analysis`, `published_analysis`, and warnings on detail responses.

The Objective list is ordered by the persisted collection-build rank and
supports `offset` and optional `limit`. When `limit` is omitted, the response
contains every Objective from `offset` onward so lower-ranked candidates remain
visible without client pagination. An explicit `limit` applies ordinary
pagination. The response contains `total`, `offset`, and the applied `limit`
(`null` when omitted), and each Objective contains its one-based `rank`. Rank is
for researcher prioritization and never removes a paper-study relationship from
the persisted inventory.

The paper-study inventory reads the active persisted Objective build and
supports `offset` and `limit`. Its response contains `total`, `offset`, `limit`,
`research_objectives_ready`, and a mixed `items` sequence containing:

- one `paper_study` entry for each paper-local experiment, observation, or
  modeling study, including design, claim scope, material/process/sample/test
  context, comparator, and fixed conditions;
- every study relationship as one complete jointly varied factor set and one
  outcome with exact `source_kind + source_ref` locators; supported kinds are
  `document`, `block`, `table`, `table_row`, and `figure`, and `table_row`
  references the persisted Source `row_id` rather than its enclosing table;
- each relationship's `pending | promoted | rejected` disposition, linked
  Objective id for promoted relationships, or explicit backend-derived reason
  for rejection; the discovery model does not reject relationships, and a
  relationship too large for model labeling uses a backend-built standalone
  Objective fallback;
- one `unresolved_signal` entry for every source-backed variable or outcome
  that could not yet form a defensible relationship, preserving the same study
  context, exact Source locators, confidence, and reason;
- one `source_unit_coverage` entry for every eligible first-stage Source unit,
  preserving `source_unit_id`, `window_id`, exact Source kind/reference, and one
  of `relationship_emitted`, `unresolved_signal_emitted`, `no_study_signal`, or
  backend-derived `extraction_failed`.

The inventory is a typed audit projection of `ObjectiveFactSet`; it is not a
second aggregate and does not trigger extraction, grouping, or analysis.
First-stage Source windows split rather than truncate scientific text, table
metadata, or figure captions. Cross-window reconciliation may receive bounded
excerpts, while the persisted signal keeps its complete structured fields and
exact Source locator; failure leaves the signal unresolved. The inventory still
does not guarantee that the first-stage LLM extracted every source-supported
study or relationship, so it is complete for extracted records rather than proof
of complete paper interpretation. `source_unit_coverage_counts` always contains
all four status counts. `coverage_complete` is `false` when any window produced
`extraction_failed`; `true` means every eligible Source unit received a
contract-valid first-stage outcome. It measures extraction execution, not
scientific recall, relevance certainty, or systematic-review completeness.

`ObjectiveAnalysis` is addressed by the Objective identity plus a positive
`analysis_version`. It contains immutable Source/pipeline/model/prompt lineage,
`queued | running | succeeded | failed` status, phase, document progress,
current document, terminal error, timestamps, and provider-reported execution
`stats`. Statistics include duration, request counts and provider-reported token
usage grouped by response model, plus the prompt versions used by the analysis.
`unreported_request_count` identifies calls that failed without provider usage
or omitted token fields. Token totals contain only reported usage and remain
`null` when no call reported usage; the backend never estimates missing tokens
from prompt or response text.

Confirmation does not start analysis. `POST .../analysis` queues the next
version and returns immediately. The frontend polls `GET .../analysis`. Retry
allocates a new version. A failed active version leaves the prior published
version readable. If the backend cannot dispatch a queued version to its local
analysis worker, it records that version as failed and returns `503`, allowing
the client to retry without leaving a permanently queued version. Only a
complete succeeded version can become published.

Objective document scope and current-analysis projection are build-scoped. A
rebuild may preserve a confirmed Objective identity and all historical analysis
rows, but an analysis from an older Source build is not exposed as active or
published for the rebuilt Objective. It remains readable only by its explicit
historical `analysis_version`.

### Published Findings And Evidence

- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence`

Finding and Evidence list endpoints support `offset` and `limit`. All responses
include an explicit `analysis_version`. If omitted from the query, the backend
uses the published Objective version. Evidence accepts an optional `finding_id`
filter.

A Finding contains:

- `finding_id`, statement, one complete `factors` tuple, one `outcome`, and
  direction;
- assertion strength, attribution scope, synthesis status, certainty, and
  display rank;
- subordinate mechanisms and typed material/sample/process/test scientific
  context;
- deterministic analysis limitations and one PaperContribution binding for
  every analyzed, excluded, or failed paper.

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

Direct contributing paper count is computed from PaperContribution Evidence
bindings rather than stored as a second declaration. `agreement`, `conflict`,
and `condition_dependent` require direct results from at least two distinct
papers; otherwise synthesis remains `insufficient_confirmation`. Context-only
Evidence cannot establish an outcome.

### Finding Feedback, Curation, And Dataset Export

- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/feedback`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/feedback`
- `PUT /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/curation`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/curation`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/finding-dataset`
- `GET /api/v1/collections/{collection_id}/finding-dataset`
- `GET /api/v1/collections/{collection_id}/finding-gold-draft`

Feedback requires `analysis_version`, `review_status`, and `issue_type`.
Curation requires `analysis_version` and one complete canonical
`curated_finding`. The service validates its exact identity and every
version-local Evidence/PaperContribution binding. Unknown, stale, unpublished,
partial, and cross-version references return `404`, `409`, or `422` and are
never silently rebound.

Dataset export supports `format=json | training_jsonl` plus optional
`label_status` and `dataset_use_status` filters. `objective_finding_dataset.v2`
includes canonical system prediction, optional expert target, resolved training
target, deterministic Finding/Evidence fingerprints, and exact Evidence
excerpts with document/page/locator provenance. `training_jsonl` contains one
`{messages, metadata}` object per line and omits samples without valid training
messages. IDs preserve lineage; source text and scientific context are part of
model input. The latest feedback or curation event controls dataset status.

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
