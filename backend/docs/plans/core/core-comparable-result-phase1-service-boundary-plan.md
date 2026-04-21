# Core Comparable Result Phase 1 Service Boundary Plan

## Summary

This child plan defines the physical responsibility split for `Phase 1`.

The goal is not to create a generic new service layer. The goal is to make the
existing comparison implementation explicit enough that assembly, assessment,
projection, and orchestration do not keep collapsing into one row-builder blob.

## Goal

Preserve one clear owning application entrypoint while making three comparison
responsibilities explicit and testable:

- comparable-result assembly
- comparability evaluation
- row projection

## Non-Goals

- introducing a generic `services/` package
- adding wrappers or compatibility facades
- forcing three new public service classes just for naming symmetry

## Phase 1 Boundary Decision

### Keep One Owning Entry Service

`ComparisonService` remains the owning application entrypoint for:

- build orchestration
- artifact read/write coordination
- rebuild control flow
- collection-facing integration seams

### Keep Domain Judgment In The Domain Layer

`backend/domain/core/comparison.py` remains the owner for:

- deterministic identity builders
- `ComparisonAssessment` evaluation logic
- comparison-semantic dataclasses

### Make Assembly And Projection Explicit

Assembly and projection responsibilities must be explicit and unit-testable.
Phase 1 allows either of these physical shapes:

- explicit private helpers inside `comparison_service.py`
- narrow Core-owned helper modules directly adjacent to the comparison service

Phase 1 does not require a broad package extraction. It does require that those
responsibilities are no longer hidden inside one long row-centered method.

## Guardrails

- no generic `services/` junk drawer
- no per-view shadow semantic assemblers
- no compatibility layer that preserves the row-first model
- no moving semantic ownership out of `domain/core/comparison.py`

## File Scope

Expected primary file ownership:

- `backend/application/core/comparison_service.py`
- `backend/domain/core/comparison.py`

Likely verification paths:

- `backend/tests/unit/domains/test_comparison_domain.py`
- comparison-service unit tests covering build and projection behavior

## Acceptance Criteria

- assembly, assessment, projection, and orchestration responsibilities are easy
  to name and point to in code review
- domain judgment stays domain-owned
- application orchestration stays application-owned
- Phase 1 does not add a generic new service layer

## Verification

- unit coverage for deterministic ids and assessment logic
- targeted service tests showing orchestration delegates through explicit
  responsibility boundaries
- code review can identify one owning entrypoint and one owned domain judgment
  surface without ambiguity

## Relationships

- Parent roadmap:
  [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
- Sibling child plans:
  [`core-comparable-result-phase1-persistence-split-plan.md`](core-comparable-result-phase1-persistence-split-plan.md)
  and
  [`core-comparable-result-phase1-read-path-cutover-plan.md`](core-comparable-result-phase1-read-path-cutover-plan.md)
