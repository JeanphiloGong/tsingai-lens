---
id: RFC-2026-001
title: Evidence-First Literature Parsing and Conditional Protocol Generation
type: rfc
level: system
domain: shared
status: draft
owner: repo-maintainers
created_at: 2026-04-11
updated_at: 2026-04-11
last_verified_at: 2026-04-11
review_by: 2026-07-11
version: v1
source_of_truth: false
related_issues: [63]
related_docs:
  - docs/30-architecture/system-overview.md
  - backend/docs/backend-overview.md
  - backend/docs/api.md
  - docs/research/materials-optimize.md
supersedes: []
superseded_by: []
tags:
  - rfc
  - parsing
  - evidence
  - protocol
---

# Evidence-First Literature Parsing and Conditional Protocol Generation

## Summary

This RFC proposes shifting TsingAI-Lens from a steps-first literature parsing
pipeline to an evidence-first pipeline.

The current pipeline assumes that uploaded papers can be normalized into
`sections -> procedure_blocks -> protocol_steps`, then reused for search and
SOP drafting. That works for some methods-heavy experimental papers, but it
breaks down for mixed corpora that include review papers, table-heavy summaries,
and narrative discussions.

The proposed direction is:

1. parse documents into evidence-oriented structures first
2. normalize comparison-ready rows for research use
3. run protocol extraction only when a document or collection is suitable for
   protocol generation

## Context

### Product and research direction

The repository-level product goal is a research literature intelligence system
for ingestion, graph extraction, and structured retrieval rather than a generic
"turn any paper into a procedure" pipeline.

The active research requirements further prioritize:

- evidence chains between claims, methods, and measurements
- comparability across material systems, process conditions, and tests
- support for experiment design and follow-up decisions

### Current failure modes

The current parsing path is centered on protocol outputs:

- `documents/text_units -> sections -> procedure_blocks -> protocol_steps`
- `protocol_steps` are then reused by the list/search/SOP flows

Observed problems in this shape:

- review-style text can be misclassified as synthesis or characterization steps
- low-signal phrases can become final `protocol_steps`
- the pipeline has no explicit document typing or abstain path
- the main output is step-shaped even when the useful value is actually
  evidence, conditions, and comparisons
- current API responses can lose nested structured fields that already exist in
  stored artifacts

These issues create a mismatch between the parsing pipeline and the intended
research workflow.

## Scope

This RFC covers:

- backend parsing and artifact generation direction
- workspace capability semantics for evidence-first versus protocol-first flows
- collection-level API additions needed to expose evidence and comparison data

This RFC does not cover:

- OCR for scanned PDFs
- a full frontend redesign
- final model or vendor selection for parsing
- deprecating graph export or structured retrieval

## Proposed Change

### 1. Introduce document profiling before protocol extraction

Add a document profiling stage that classifies each paper as one of:

- `experimental`
- `review`
- `mixed`
- `uncertain`

Each profile should also include a `protocol_extractable` decision and
warnings. Protocol extraction should become conditional on that decision rather
than the default outcome for every document.

### 2. Make evidence extraction the primary parsing output

Add an evidence-first parsing layer that produces durable evidence units rather
than only step-shaped outputs.

Core extracted units should cover:

- material system and composition
- process conditions
- microstructure observations
- measurements and test conditions
- property values and units
- baseline/control information
- source evidence spans and confidence

These outputs should support the research requirements around evidence chains,
comparability, and experiment planning.

### 3. Normalize comparison-ready rows as a first-class artifact

Add a comparison normalization stage so collections can directly support
cross-paper comparison instead of forcing all downstream value through
`protocol_steps`.

Comparison rows should make it possible to compare:

- material system
- process or treatment
- measured property
- value and unit
- test conditions
- baseline/control
- evidence completeness or comparability warnings

### 4. Treat protocol extraction as a conditional branch

Retain protocol extraction, but reposition it as a secondary branch that runs
only for documents or collections that are suitable for procedural synthesis.

The branch should produce:

- `protocol_candidates`
- quality gating and abstain decisions
- final `protocol_steps` only for candidates that pass the quality bar

Returning zero final steps for a review-heavy collection is a valid and
preferred outcome when the alternative would be misleading steps.

### 5. Expand workspace and API semantics

Workspace and API responses should communicate the evidence-first flow rather
than only protocol readiness.

Suggested additions:

- document profile readiness
- evidence extraction readiness
- comparison readiness
- document type distribution
- collection warnings such as review-heavy or protocol-limited collections

New collection-level APIs should expose evidence and comparison outputs as
first-class results instead of requiring users to infer them from protocol
artifacts.

## Artifact Model

The target artifact model is:

- `documents_raw.parquet`
  Raw document-level ingestion output and provenance
- `page_blocks.parquet`
  Layout-aware blocks or page-local text units
- `document_profiles.parquet`
  Document type, protocol suitability, and parsing warnings
- `document_sections.parquet`
  Section-level parsing output
- `content_blocks.parquet`
  Typed blocks such as methods/results/table/caption
- `evidence_cards.parquet`
  Evidence-centered extraction output
- `comparison_rows.parquet`
  Comparison-ready normalized rows
- `protocol_candidates.parquet`
  Candidate procedural steps before quality gating
- `protocol_steps.parquet`
  Final protocol steps after filtering

Not every stage must land in the first implementation wave, but the pipeline
should evolve toward this shape.

## Module Change Plan

### Keep

- collection, task, workspace, and artifact registry flow
- index orchestration and graph/report outputs
- collection-scoped API structure

### Add

- document profile service
- layout or typed block parsing service
- evidence extraction service
- comparison normalization service
- protocol candidate service

### Reposition

- existing protocol section/block/extract services should move from being the
  main parsing backbone to being protocol-branch helpers or fallback logic

## Verification

The direction in this RFC is acceptable when all of the following are true:

- review-heavy collections no longer emit obviously fake protocol steps as the
  primary result
- methods-heavy experimental documents still produce usable final protocol
  steps
- evidence outputs retain source spans and structured conditions
- comparison outputs can be used to inspect cross-paper differences in process,
  structure, and property claims
- workspace can signal when a collection is suitable for protocol browsing
  versus evidence/comparison browsing

## Risks

- More artifact types and API surfaces will increase backend complexity
- Document typing and quality gates will need iterative tuning on real corpora
- Mixed documents may remain ambiguous and require explicit warnings
- Evidence-first parsing does not remove the need for human review on weak or
  incomplete papers

## Adoption Notes

Suggested delivery order:

1. fix current protocol response fidelity issues, especially nested structured
   field decoding
2. add document profiling and protocol suitability checks
3. expose evidence-first artifacts
4. add comparison outputs
5. tighten protocol extraction behind candidate filtering and abstain logic

This RFC should remain a proposal until the parsing direction and surface
semantics are explicitly accepted.
