# Lens V1 Architecture Boundary

## Purpose

This document defines the shared object model and system boundary required to
support the Lens v1 product contract.

It does not define user-facing value, success criteria, or backend sequencing.

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

Lens v1 should be built around the following shared object families:

- `document_profile`
  A coarse routing and warning object for one paper.
- `paper_fact`
  A durable paper-level fact such as sample identity, method, condition,
  baseline, measurement result, characterization finding, or evidence anchor.
- `comparison_view`
  A deterministic collection-facing comparison projection assembled from paper
  facts.
- `evidence_view`
  A reader-facing and traceback-facing evidence projection assembled from paper
  facts and anchors.

At the shared architecture level, the primary paper-fact family should include:

- `sample_variant`
- `method_fact`
- `test_condition`
- `baseline_reference`
- `measurement_result`
- `characterization_observation`
- `evidence_anchor`
- `structure_feature` as optional enrichment

These objects are more central to Lens v1 than `protocol_step`.

## Collection-Level Flow

The shared Lens v1 workflow should be:

1. ingest papers into a collection
2. profile each document for type and protocol suitability
3. extract paper facts from the collection
4. derive comparison-ready rows across the collection
5. derive evidence-facing traceback views over the same facts
6. expose traceback from each important output to the underlying evidence
7. run protocol extraction only when the collection or paper is suitable

This means a collection can be useful even when it produces zero final protocol
steps.

Collection-level suitability states should be derived from
`document_profiles` rather than introduced as an unrelated parallel source of
truth.

## Shared Artifact Boundary

The shared artifact model for Lens v1 should separate the primary paper-facts
backbone from its derived views and from the protocol branch.

Primary Core artifacts:

- `documents_raw`
- `document_profiles`
- the `paper_facts` family

Derived Core views:

- `comparison_rows`
- `evidence_cards`

Conditional branch artifacts:

- `protocol_candidates`
- `protocol_steps`

## Artifact Roles

The artifacts above do not have equal architectural weight.

- `document_profiles`
  Determines document type, protocol suitability, and collection-level gating.
- `paper_facts`
  Carries the primary research meaning that later comparisons and evidence
  browsing depend on.
- `comparison_rows`
  Serves as the primary collection-facing comparison view derived from paper
  facts.
- `evidence_cards`
  Serves as a derived evidence-facing and traceback-facing view.
- `protocol_candidates`
  Holds provisional procedural candidates derived from document profiling and
  Core facts.
- `protocol_steps`
  Holds filtered procedural outputs that survive the protocol branch quality
  bar.

Protocol derivation should depend on document profiling and paper-facts-backed
Core outputs rather than bypassing the Core backbone.

## Shared API Boundary

At the shared architecture level, the system should expose four types of
collection-facing capability:

- collection ingestion and readiness
- document profiling and suitability signals
- single-paper facts plus evidence/comparison browsing
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
- whether paper-facts-backed evidence outputs are ready
- whether comparison outputs are ready
- whether protocol outputs are available or intentionally absent
- whether warnings limit direct comparison or protocol generation

This prevents the product from implying that "no protocol steps" means "no
value".

## Protocol And Graph Boundary

Protocol extraction remains in Lens v1, but only as a narrower branch.

Protocol output should be:

- conditional on document suitability
- filtered by confidence and evidence support
- secondary to evidence-backed comparison

Protocol output should not be:

- the required result of every upload
- the default interpretation of review-heavy literature
- the product's primary definition of success

Graph and report views in v1 should be derived views over paper facts,
evidence views, and comparison views, not independent extraction backbones or
primary acceptance surfaces.

## Shared Module Responsibilities

At the shared architecture level:

- `backend/` owns ingestion, artifact generation, storage, and the public HTTP
  contract
- `frontend/` owns collection-facing browsing and presentation of facts,
  evidence views, comparison views, and protocol states
- root `docs/` owns shared mission, v1 boundary, architecture, and RFC-level
  decisions

The shared system should keep its stable meaning in root docs and leave
execution detail to module-owned plans.

## Related Docs

- [Lens Mission and Positioning](../overview/lens-mission-positioning.md)
- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens Core Artifact Contracts](../contracts/lens-core-artifact-contracts.md)
- [RFC Paper-Facts Primary Domain Model and Derived Comparison Views](../decisions/rfc-paper-facts-primary-domain-model.md)
- [Lens Evidence-First Direction and Conditional Protocol Generation](../decisions/rfc-evidence-first-literature-parsing.md)
- [System Overview](../overview/system-overview.md)
- [Backend Evidence-First Parsing Refactor Plan](../../backend/docs/plans/historical/evidence-first-parsing-plan.md)
