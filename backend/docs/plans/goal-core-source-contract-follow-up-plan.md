# Goal/Core/Source Contract Follow-up Plan

## Purpose

This document records the next backend child plan for freezing the
Goal/Core/Source contracts before deeper layer expansion.

It is intentionally narrower than the parent roadmap:

- lock boundaries first
- ship minimal Goal entry contract second
- expand Source adapters after contract guardrails are in place

## Why This Follow-up Exists

Core stabilization work has already moved key semantics into a safer baseline:

- Core parsing seam extraction is in place
- `*_generated` versus `*_ready` semantics are now explicit
- protocol branch behavior is aligned with Core-first artifact readiness

The next risk is not missing features. The next risk is boundary drift:

- Goal entry could bypass Core artifact flow
- Source adapters could start writing Core semantics directly
- schema evolution could create multiple incompatible fact models

This follow-up exists to prevent that drift by freezing contracts first.

## Scope

This follow-up covers:

- layer ownership and dependency-direction contract freeze
- minimal Goal Layer object contract and route shape
- Source normalization contract at the collection handoff seam
- Core-consumption invariants for goal-first and paper-first entry convergence
- verification matrix for cross-layer contract enforcement

This follow-up does not cover:

- graph semantic migration (`/graph`, `/graphml`) cutover
- crawler ranking or external provider selection
- protocol extraction algorithm upgrades
- frontend IA redesign

## Contract Decisions

### Layer Ownership Contract

- Goal Layer owns research intent orchestration only.
- Core owns research semantics and judgment artifacts only.
- Source Layer owns acquisition and normalization only.

Hard boundary:

- Goal and Source must not generate `document_profiles`, `evidence_cards`,
  `comparison_rows`, or protocol artifacts directly.

### Goal Contract (Minimal)

Goal-facing contract objects stay intentionally small:

- `research_brief`
- `coverage_assessment`
- `seed_collection`
- `entry_recommendation`

Guardrails:

- no direct evidence or comparison payloads in Goal responses
- no direct protocol-step payloads in Goal responses
- Goal output must resolve to a collection identifier that enters the same Core
  routes as paper-first flow

### Source Contract (Collection Handoff)

Source adapters must emit normalized import units, not research judgments:

- `documents`
- `text_units`
- `source_metadata`

Guardrails:

- Source can populate or enrich collections
- Source cannot set Core artifact readiness or protocol readiness fields

### Core Consumption Contract

Core remains the only place that turns collection material into research
artifacts:

- `document_profiles`
- `evidence_cards`
- `comparison_rows`
- optional downstream `protocol_candidates` and `protocol_steps`

Core lifecycle semantics remain authoritative:

- `*_generated` answers whether a stage completed generation attempt
- `*_ready` answers whether that artifact is available for user-level
  consumption

## Execution Waves

### Wave A: Contract Freeze In Docs And Schemas

Goal:

- make contracts explicit before adding more behavior.

Primary changes:

- add/confirm backend-local contract definitions for Goal input/output objects
- document Source normalized handoff fields at the API/spec level
- document non-bypass rules across Goal, Source, and Core

Exit criteria:

- one unambiguous contract document exists
- route/schema and architecture docs reference the same boundary language

### Wave B: Minimal Goal Surface Skeleton

Goal:

- ship a first-class Goal entry path that only seeds collections.

Primary changes:

- add `application/goals/service.py` for orchestration
- add goal-facing controller surface and response schemas
- return `seed_collection` plus `entry_recommendation` without bypassing Core

Exit criteria:

- goal-first request can create or enrich a collection
- returned collection enters existing Core endpoints unchanged

### Wave C: Source Normalization Seam Hardening

Goal:

- standardize import outputs from upload and future adapters.

Primary changes:

- define Source normalization seam under ingestion-owned code
- align upload path and adapter path to emit the same normalized import shape
- keep adapter implementation replaceable behind the same handoff contract

Exit criteria:

- upload and adapter ingestion both terminate at collection boundaries
- Core receives consistent normalized inputs regardless of source channel

### Wave D: Cross-Layer Contract Guard Tests

Goal:

- enforce contracts through tests rather than relying on conventions.

Primary changes:

- add app-layer tests for goal-first to Core convergence
- add contract tests that Goal/Source cannot emit or mutate Core artifacts
- add readiness matrix assertions for generated-versus-ready semantics at route
  boundaries

Exit criteria:

- contract invariants fail fast in tests when boundaries are violated
- both entry paths converge to one Core artifact model

## File Change Plan

### Docs And Contracts

- `docs/specs/api.md`
- `docs/architecture/goal-core-source-layering.md`
- this follow-up plan

### Goal Skeleton

- new `application/goals/service.py`
- new `controllers/goals.py` (or domain-local equivalent)
- new `controllers/schemas/goals.py`
- collection handoff integration in `application/collections/`

### Source Normalization Seam

- `infra/ingestion/` seam module(s) for normalized handoff
- upload path integration where collection imports are assembled

### Verification

- `tests/application/` slices for Goal and collection handoff
- `tests/controllers/` slices for Goal route semantics
- `tests/integration/` slices for goal-first versus paper-first convergence

## Acceptance Matrix

- Goal route returns contract objects only, not Core artifacts.
- Goal-first entry resolves to a collection visible in existing workspace and
  Core routes.
- Source adapters feed collections with normalized import units only.
- Core remains the only producer of evidence/comparison artifacts.
- readiness semantics remain stable with `generated` and `ready` split.

## Risks

- adding Goal endpoints too early can create implicit promises before Source
  and Core handoff constraints are encoded
- Source seam hardening can regress current upload behavior if normalization
  contracts are not tested against existing fixtures
- if contract language drifts across docs and schemas, teams will reintroduce
  bypass paths accidentally

## Recommended Reading Order

1. [`goal-core-source-implementation-plan.md`](goal-core-source-implementation-plan.md)
2. [`core-stabilization-and-seam-extraction-plan.md`](core-stabilization-and-seam-extraction-plan.md)
3. this follow-up plan
4. [`core-derived-graph-follow-up-plan.md`](core-derived-graph-follow-up-plan.md)

## Related Docs

- [`goal-core-source-implementation-plan.md`](goal-core-source-implementation-plan.md)
- [`core-stabilization-and-seam-extraction-plan.md`](core-stabilization-and-seam-extraction-plan.md)
- [`core-derived-graph-follow-up-plan.md`](core-derived-graph-follow-up-plan.md)
- [`../architecture/goal-core-source-layering.md`](../architecture/goal-core-source-layering.md)
- [`../specs/api.md`](../specs/api.md)
