# Lens V1 Architecture Boundary

## Purpose

This document defines the shared system boundary for Lens v1.

It translates the product mission and v1 definition into a concrete shared
architecture shape without dropping into backend-only implementation detail.

The main architectural rule is:

Lens v1 is evidence-first and comparison-first. Protocol generation remains a
conditional downstream branch.

## Scope

This document covers:

- the shared objects that Lens v1 must preserve
- the collection-level workflow that defines the system
- the artifact and API boundary between shared architecture and local
  implementation
- the role of protocol generation inside the system

This document does not cover:

- detailed backend service breakdowns
- final route schemas
- frontend page structure
- model or provider selection

## Core Objects

Lens v1 should be built around the following shared research objects:

- `claim`
  A paper-level or span-level assertion that can be judged.
- `evidence`
  The figure, table, method, measurement, or source span that supports a
  claim.
- `condition_context`
  The material system, process, baseline, test condition, and scope that
  constrain where a claim holds.
- `comparability`
  A judgment about whether two extracted results can be inspected side by side
  without misleading the user.

These objects are more central to Lens v1 than `protocol_step`.

## Collection-Level Flow

The shared Lens v1 workflow should be:

1. ingest papers into a collection
2. profile each document for type and protocol suitability
3. extract evidence-oriented units
4. normalize comparison-ready rows across the collection
5. expose traceback from each important output to the underlying evidence
6. run protocol extraction only when the collection or paper is suitable

This means a collection can be useful even when it produces zero final protocol
steps.

## Shared Artifact Boundary

The shared artifact model for Lens v1 should separate the evidence backbone
from the protocol branch.

Backbone artifacts:

- `documents_raw`
- `document_profiles`
- `evidence_cards`
- `comparison_rows`

Conditional branch artifacts:

- `protocol_candidates`
- `protocol_steps`

The backbone artifacts define the product's core value. The protocol artifacts
extend the system for methods-heavy collections.

## Shared API Boundary

At the shared architecture level, the system should expose four types of
collection-facing capability:

- collection ingestion and readiness
- document profiling and suitability signals
- evidence and comparison browsing
- conditional protocol browsing

The API does not need to force every collection into a protocol-shaped result.
Instead, it should make room for explicit states such as:

- `protocol_limited`
- `not_extractable`
- `insufficient`
- `not_comparable`

This is part of the product contract, not an implementation detail.

## Workspace Semantics

The workspace should communicate which part of the system is useful for the
current collection.

For Lens v1, the workspace should be able to tell the user:

- whether the collection is mostly experimental, review-heavy, mixed, or
  uncertain
- whether evidence outputs are ready
- whether comparison outputs are ready
- whether protocol outputs are available or intentionally absent
- whether warnings limit direct comparison or protocol generation

This prevents the product from implying that "no protocol steps" means "no
value".

## Protocol Boundary

Protocol extraction remains in Lens v1, but only as a narrower branch.

Protocol output should be:

- conditional on document suitability
- filtered by confidence and evidence support
- secondary to evidence-backed comparison

Protocol output should not be:

- the required result of every upload
- the default interpretation of review-heavy literature
- the product's primary definition of success

## Shared Module Responsibilities

At the shared architecture level:

- `backend/` owns ingestion, artifact generation, storage, and the public HTTP
  contract
- `frontend/` owns collection-facing browsing and presentation of evidence,
  comparison, and protocol states
- root `docs/` owns shared mission, v1 boundary, architecture, and RFC-level
  decisions

The shared system should keep its stable meaning in root docs and leave
execution detail to module-owned plans.

## Related Docs

- [Lens Mission and Positioning](../50-guides/lens-mission-positioning.md)
- [Lens V1 Definition](../40-specs/lens-v1-definition.md)
- [Lens Evidence-First Direction and Conditional Protocol Generation](../10-rfcs/evidence-first-literature-parsing.md)
- [System Overview](system-overview.md)
- [Backend Evidence-First Parsing Refactor Plan](../../backend/docs/backend-evidence-first-parsing-plan.md)
