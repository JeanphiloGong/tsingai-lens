# User Ownership Modeling

## Purpose

This topic family records the backend-local plan for adding user ownership to
Lens collections and user-created research outputs without turning the current
single-user system into a full account-management project.

The goal is to make the data model ready for multi-user expansion while
keeping the current collection-centered Core backbone intact.

## Authority Boundary

- this family owns the backend implementation plan for collection ownership,
  current-user context, and user-scoped access checks
- stable public API contract changes belong in
  [`../../../specs/api.md`](../../../specs/api.md) when implementation reaches
  that point
- authentication product policy, billing, teams, and shared frontend IA do not
  belong in this backend-local plan
- Core artifacts remain collection-derived and should not gain duplicated
  user ownership fields unless a later decision requires it

## Reading Order

- [`implementation-plan.md`](implementation-plan.md)
  Backend plan for introducing collection ownership and current-user scoping

## Related Docs

- [`../goal-source-core-layering/README.md`](../goal-source-core-layering/README.md)
- [`../api-surface-migration/current-state.md`](../api-surface-migration/current-state.md)
- [`../../../architecture/goal-core-source-layering.md`](../../../architecture/goal-core-source-layering.md)
