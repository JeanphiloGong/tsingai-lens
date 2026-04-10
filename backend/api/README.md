# Backend API Boundary

This node owns the new public HTTP boundary for query and report routes.

## Scope

- route registration under `api/routes/`
- request parsing and response shaping for those routes
- translation between HTTP concerns and application use cases

## Current Contents

- `routes/query.py`
- `routes/reports.py`
- `schemas/`

## Boundary Rule

This package should stay thin. It should not absorb collection, task, protocol,
or storage orchestration logic.

## Relationship To The Rest Of The Backend

- depends on `application/` for use-case orchestration
- should not reach deep into `retrieval/` directly when a clearer boundary
  exists
- currently coexists with `controllers/`, which still own the app-layer
  collection and task HTTP surface
