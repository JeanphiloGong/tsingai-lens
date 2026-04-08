---
id: ADR-2026-001
title: Backend Application Layer Ownership Boundary
type: adr
level: domain
domain: backend
status: active
owner: backend-maintainers
created_at: 2026-04-07
updated_at: 2026-04-07
last_verified_at: 2026-04-07
review_by: 2026-07-07
version: v1
source_of_truth: true
related_issues: [61]
related_docs:
  - docs/05-policies/documentation-governance.md
  - backend/docs/api.md
supersedes: []
superseded_by: []
tags:
  - backend
  - architecture
  - application-layer
---

# Backend Application Layer Ownership Boundary

## Status

Active

## Context

The backend currently contains multiple overlapping layers and migration seams:

- `api/` holds the new public route entrypoints
- `application/` exists, but some modules still act as forwarding shims
- legacy logic still lives in `app/usecases/`
- `controllers/` and `services/` still coexist with the newer package layout
- `retrieval/` remains the large engine and infrastructure surface

This has made the intended dependency direction harder to read and easier to
violate.

## Decision

The repository adopts the following backend ownership boundary:

1. `api/` is the HTTP boundary.
   It owns routes, request parsing, response shaping, and HTTP exception
   translation only.
2. `application/` owns use-case orchestration.
   It coordinates domain logic, repositories, and infrastructure adapters, and
   must stop being a forwarding-only facade over `app/usecases/`.
3. `domain/` owns domain models, invariants, and domain-level rules.
4. `infra/` and adapter packages own external integrations such as persistence,
   retrieval, vector stores, and other runtime dependencies.
5. `retrieval/` remains an engine package that should be reached through
   application-owned or infrastructure-owned boundaries rather than ad hoc
   imports from route code.

## Consequences

### Accepted consequences

- `api/` should depend on `application/`, not on legacy `app/usecases/`
  directly.
- `application/` should contain real orchestration logic over time, not
  permanent re-export modules.
- backend-specific implementation docs can stay in `backend/docs/`, while this
  ADR remains the durable repo-level decision record for the layering rule.

### Follow-up implications

- migration work tracked by #61 should move logic out of forwarding shims and
  into `application/`
- new backend refactors should preserve `api -> application -> domain/infra`
  as the intended dependency direction
- future docs that explain local backend implementation details should prefer
  `backend/docs/`, not root `docs/`, unless they become cross-module authority

## Alternatives Considered

### Remove `application/` and route directly into `app/usecases/`

Rejected because it would preserve the legacy implementation layout and weaken
the intended boundary between HTTP concerns and use-case orchestration.

### Keep `application/` as a permanent forwarding facade

Rejected because it adds indirection without ownership and makes the layer look
more complete than it actually is.
