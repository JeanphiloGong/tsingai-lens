# Backend Application Layer Ownership Boundary

## Status

Active

## Context

The backend contains multiple layers with explicit ownership boundaries:

- `api/` holds the new public route entrypoints
- `application/` owns use-case orchestration for query and reporting flows
- `controllers/` and `services/` still coexist with the newer package layout
- `infra/source/*` now owns the active Source runtime and parser/indexing seam

This has made the intended dependency direction harder to read and easier to
violate.

## Decision

The repository adopts the following backend ownership boundary:

1. `api/` is the HTTP boundary.
   It owns routes, request parsing, response shaping, and HTTP exception
   translation only.
2. `application/` owns use-case orchestration.
   It coordinates domain logic, repositories, and infrastructure adapters, and
   should remain the main dependency target for HTTP-facing route code.
3. `domain/` owns domain models, invariants, and domain-level rules.
4. `infra/` and adapter packages own external integrations such as persistence,
   Source runtime, vector stores, and other runtime dependencies.
5. backend runtime code should reach those external integrations through
   application-owned or infrastructure-owned boundaries rather than ad hoc
   imports from route code.

## Consequences

### Accepted consequences

- `api/` should depend on `application/` rather than bypassing it with
  ad hoc orchestration in route modules.
- application-owned orchestration should stay explicit and testable.
- backend-specific implementation docs stay in backend-owned locations rather
  than in root shared docs.

### Follow-up implications

- new backend refactors should preserve `api -> application -> domain/infra`
  as the intended dependency direction
- future docs that explain local backend implementation details should prefer
  backend-owned locations rather than root shared docs unless they become
  cross-module authority

## Alternatives Considered

### Remove `application/` and route directly into `app/usecases/`

Rejected because it would preserve the legacy implementation layout and weaken
the intended boundary between HTTP concerns and use-case orchestration.
