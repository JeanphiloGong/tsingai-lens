# Backend User Ownership Modeling Plan

## Summary

Lens should add user ownership now, before goal sessions, collection-bound AI
chat, and review-report generation create more user-scoped records.

The first backend step should be deliberately small:

- add `owner_user_id` to collection metadata
- resolve the effective user id on the backend, not from request bodies
- scope collection list, read, file upload, deletion, and derived actions by
  the current user
- let Core artifacts inherit user ownership through `collection_id`
- keep team membership, full authentication, and storage-path migration out of
  this wave

This preserves the current collection-centered product model while avoiding a
future rewrite where every artifact has to be retrofitted with ownership.

## Context

The current collection record owns the user's paper knowledge base, but it does
not record a user owner. The persisted metadata shape is:

```text
collection_id
name
description
status
paper_count
created_at
updated_at
```

That is acceptable for a local single-user prototype, but it becomes fragile
once Lens adds:

- collection-bound AI conversations
- persistent goal sessions
- generated material review reports
- personal saved research state
- later multi-user or team access

Adding ownership after those records exist would force a broader data migration
and make authorization boundaries harder to audit.

## Target Model

### Collections

`Collection` is the ownership root for a user's knowledge base.

```text
Collection
- collection_id
- owner_user_id
- name
- description
- status
- paper_count
- created_at
- updated_at
```

`owner_user_id` is required in normalized collection metadata. Legacy
collection records that do not have the field should normalize to the local
default user during read.

### Goal Sessions

Goal sessions should be modeled as user-created working state bound to a
collection.

```text
GoalSession
- goal_session_id
- user_id
- collection_id
- focused_material_id?
- focused_paper_id?
- goal_text
- goal_brief_json
- answer_mode: grounded | hybrid | general
- rolling_summary
- last_evidence_ids
- collection_data_version
- created_at
- updated_at
```

`GoalSession.user_id` records the session owner. `collection_id` still defines
which knowledge base the session can use.

### Review Reports

Review reports are generated user actions over collection-owned Core outputs.

```text
MaterialReviewReport
- report_id
- collection_id
- material_id
- created_by_user_id
- status
- generated_at
```

`created_by_user_id` records who generated the report. The report's data
access still flows through the collection permission check.

### Core Artifacts

Do not add `user_id` directly to these Core artifacts in the first wave:

```text
DocumentProfile
EvidenceCard
ComparisonRow
MaterialProfile
ComparableResult
```

They are generated from a collection and inherit ownership through
`collection_id`. Duplicating `user_id` across all derived artifacts would add
write churn and risk inconsistent ownership values.

## Current-User Context

The backend should introduce one current-user seam for application code.

In the local single-user phase:

```text
get_current_user_id() -> "local_user"
```

When authentication is introduced, the same seam can resolve:

```text
get_current_user_id() -> authenticated_user.id
```

The frontend should not send `user_id` in collection, goal, or report request
bodies. User identity belongs to the request authentication context, not to
client-provided resource fields.

## API Semantics

### Collection Creation

`POST /api/v1/collections` should create metadata with:

```text
owner_user_id = current_user_id
```

The public response does not need to expose `owner_user_id` in the first wave
unless frontend behavior needs it. Persisting and enforcing the field is the
important modeling step.

### Collection Listing

`GET /api/v1/collections` should return only collections owned by the current
user.

### Collection Access

Collection-scoped endpoints should verify ownership before reading or mutating
collection state:

```text
GET /api/v1/collections/{collection_id}
DELETE /api/v1/collections/{collection_id}
POST /api/v1/collections/{collection_id}/files
GET /api/v1/collections/{collection_id}/files
POST /api/v1/collections/{collection_id}/tasks/index
GET /api/v1/collections/{collection_id}/workspace
```

The early product can return `404` for collections not owned by the current
user. That avoids leaking whether another user's collection id exists. A later
team-sharing model can revisit `403` behavior where explicit membership is
visible.

### Derived Actions

Derived endpoints such as graph, material research view, and review-report
generation should keep calling the collection ownership check before loading
Core outputs.

## Persistence Shape

The current file-backed collection metadata should add `owner_user_id` inside
`meta.json`:

```json
{
  "collection_id": "col_xxx",
  "owner_user_id": "local_user",
  "name": "AM 316L papers",
  "description": "...",
  "status": "idle",
  "paper_count": 0,
  "created_at": "...",
  "updated_at": "..."
}
```

This wave should not move collection directories to a user-scoped path such as:

```text
data/users/{user_id}/collections/{collection_id}
```

Changing storage paths would affect artifact readers, background tasks,
exports, and local data. Metadata ownership is enough for the first wave.

## Implementation Slices

### Slice 1: Collection Record Ownership

Update the collection domain record to carry `owner_user_id`.

Planned files:

- `backend/domain/source/collection.py`
- `backend/tests/unit/domains/test_source_collection_domain.py`

Behavior:

- `CollectionRecord.create()` requires `owner_user_id`
- `CollectionRecord.from_mapping()` normalizes missing ownership to
  `"local_user"` for legacy metadata
- `to_record()` writes `owner_user_id`

### Slice 2: Current User Dependency

Add a narrow backend current-user provider.

Planned files:

- a small backend-owned auth or request-context module
- affected collection and goal controllers

Behavior:

- local default returns `"local_user"`
- request bodies do not accept `user_id`
- services receive the effective user id from controller or application
  context

### Slice 3: Collection Service Scoping

Thread `owner_user_id` through collection creation and access.

Planned files:

- `backend/application/source/collection_service.py`
- `backend/controllers/source/collections.py`
- `backend/controllers/source/tasks.py`

Behavior:

- create writes `owner_user_id`
- list filters by current user
- get/delete/file/task entrypoints reject records not owned by current user
- legacy collections read as owned by `"local_user"`

### Slice 4: Goal Intake Handoff

Goal intake creates a collection, so it must use the same current-user context.

Planned files:

- `backend/controllers/goal/*`
- `backend/application/goal/brief_service.py`

Behavior:

- goal intake passes the current user into collection creation
- goal handoff remains collection-backed
- no research conclusion is generated in the Goal Brief layer

### Slice 5: Review Report Generation

Review report generation should record the requesting user without changing
Core artifact ownership.

Planned files:

- `backend/application/derived/material_review_report_service.py`
- `backend/controllers/derived/material_review_report.py`
- related unit tests

Behavior:

- generation checks access through the collection
- report metadata records `created_by_user_id`
- report context still reads Core artifacts by `collection_id`

## Verification

Focused verification should cover:

- legacy collection records normalize to `owner_user_id = "local_user"`
- new collection creation persists `owner_user_id`
- listing hides collections owned by other users
- get/delete/upload/task endpoints reject non-owned collections
- goal intake creates a collection owned by the current user
- review-report generation records `created_by_user_id`

Suggested commands:

```text
cd backend
uv run pytest tests/unit/domains/test_source_collection_domain.py
uv run pytest tests/unit/services/test_collection_service.py
uv run pytest tests/unit/services/test_goal_brief_service.py
uv run pytest tests/unit/services/test_material_review_report_service.py
```

Adjust the exact test paths to the files touched in the implementation wave.

## Non-Goals

This wave does not implement:

- login, registration, passwords, or OAuth
- team workspaces
- collection sharing
- billing or account plans
- a user profile page
- storage directory migration
- duplicated `user_id` fields on every Core artifact
- frontend-visible user management

## Future Team Model

`owner_user_id` should not become the entire authorization model.

When collaboration is needed, add membership separately:

```text
CollectionMember
- collection_id
- user_id
- role: owner | editor | viewer
```

Then collection access can be resolved by:

```text
owner_user_id == current_user_id
or current_user_id is a collection member
```

That keeps ownership, collaboration, and generated Core artifacts cleanly
separated.

## Open Questions

- Should public collection responses expose `owner_user_id`, or should the
  field remain internal until account UI exists?
- Should unauthorized collection access return `404` everywhere in the first
  wave, or should operator-only endpoints use `403`?
- Should current-user context live in a small auth module now, or under a
  request-context module until real authentication is introduced?
