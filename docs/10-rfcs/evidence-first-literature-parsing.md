# Lens Evidence-First Direction and Conditional Protocol Generation

## Summary

This RFC proposes clarifying Lens as an evidence-and-comparison oriented
literature intelligence system rather than a generic "turn papers into
protocols" pipeline.

The practical parsing change is to shift TsingAI-Lens from a steps-first
literature parsing pipeline to an evidence-first pipeline. The product-level
change is to treat protocol extraction as one downstream branch rather than the
default center of the system.

Materials science remains the first vertical direction used to validate this
model, but the system-level identity should stay broader than a materials-only
protocol extractor.

The proposed direction is:

1. treat Lens as a cross-paper clue, evidence, and comparison engine
2. parse documents into evidence-oriented structures first
3. normalize comparison-ready rows for research use
4. run protocol extraction only when a document or collection is suitable for
   protocol generation

## Relationship To Current Docs

This RFC should now be read as the originating proposal and decision record for
the evidence-first shift.

The current shared definitions promoted out of this RFC now live in:

- [Lens Mission and Positioning](../50-guides/lens-mission-positioning.md)
- [Lens V1 Definition](../40-specs/lens-v1-definition.md)
- [Lens V1 Architecture Boundary](../30-architecture/lens-v1-architecture-boundary.md)
- [Lens Core Artifact Contracts](../40-specs/lens-core-artifact-contracts.md)
- [Backend Evidence-First Parsing Refactor Plan](../../backend/docs/plans/evidence-first-parsing-plan.md)

This RFC should keep the why, tradeoff, and transition rationale for the shift
away from protocol-first parsing. It should not keep absorbing new current-state
definitions once those definitions have been promoted into the shared guide,
spec, architecture, and backend plan layers.

## North Star

Lens v1 should let a researcher complete in about one hour the kind of
cross-paper comparison work that would otherwise take most of a day, while
keeping each important judgment traceable back to original evidence and
conditions.

For the first vertical, the clearest value statement is:

> Lens v1 helps materials researchers compare 20-50 papers, identify genuinely
> comparable results, spot weak-evidence claims and conflict sources, and trace
> each decision back to original paper evidence and conditions.

## Context

### Product and research direction

The repository-level product goal is a research literature intelligence system
for ingestion, graph extraction, and structured retrieval rather than a generic
"turn any paper into a procedure" pipeline.

Lens should help users discover useful clues across many papers:

- which claims repeat across papers
- which conditions and baselines make results comparable or non-comparable
- which variables are promising enough to inform follow-up experiments
- which evidence chains are strong enough to trust

This makes evidence quality, source traceability, and cross-paper comparison
more central than raw step extraction volume.

The key product objects for that job are:

- `claim`
  what a paper is asserting in a way that can be judged
- `evidence`
  which figure, table, method, span, or measurement supports that claim
- `condition/context`
  which material system, process, measurement condition, baseline, and scope
  constrain where that claim holds
- `comparability`
  whether two claims can be inspected side by side without misleading the user

The active research requirements further prioritize:

- evidence chains between claims, methods, and measurements
- comparability across material systems, process conditions, and tests
- support for experiment design and follow-up decisions

### Materials as the first vertical, not the whole product

Materials science is the first vertical used to prove out Lens because it has a
clear need for:

- structure-processing-properties-performance reasoning
- baseline and control tracking
- measurement-condition normalization
- evidence-backed experiment design

However, Lens should not be defined as a materials-only protocol system. The
materials vertical should shape the first schema and reasoning layer while the
shared product remains a broader literature intelligence engine.

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

- shared product direction for Lens as an evidence-first clue engine
- materials Phase 1 boundaries as the first vertical validation slice
- backend parsing and artifact generation direction
- workspace capability semantics for evidence-first versus protocol-first flows
- collection-level API additions needed to expose evidence and comparison data

This RFC does not cover:

- OCR for scanned PDFs
- a full frontend redesign
- final model or vendor selection for parsing
- deprecating graph export or structured retrieval
- committing to fully automatic SOP generation for all corpora

This RFC also does not propose Lens v1 as:

- a generic chat shell for papers
- a single-paper summary product
- a full "AI scientist" or autonomous experiment system
- a guarantee that every uploaded paper must produce protocol steps
- a graph-first showcase where visualization is the primary user value

## Proposed Change

### 1. Adopt a Lens-first product framing

Lens should optimize for:

- evidence traceability
- cross-paper comparison
- clue discovery and hypothesis support
- conditional protocol generation when the corpus supports it

Lens should not optimize around "every uploaded document must become final
protocol steps".

The main product flow should become:

1. ingest documents into a collection
2. profile and parse documents into evidence-oriented units
3. surface clues, comparisons, and graph/report outputs
4. derive protocol and SOP outputs only when document quality and type support
   them

### 1a. Make the v1 loop narrow and testable

Lens v1 should prove one concrete workflow rather than a broad research
automation story.

The smallest valuable loop is:

1. collection creation and paper ingestion
2. document profiling
3. claim/evidence/condition extraction
4. normalized cross-paper comparison
5. evidence traceback into original source spans

This loop is more important than early SOP quality, agent behavior, or
hypothesis generation breadth.

### 2. Introduce document profiling before protocol extraction

Add a document profiling stage that classifies each paper as one of:

- `experimental`
- `review`
- `mixed`
- `uncertain`

Each profile should also include a `protocol_extractable` decision and
warnings. Protocol extraction should become conditional on that decision rather
than the default outcome for every document.

### 3. Make evidence extraction the primary parsing output

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

### 4. Normalize comparison-ready rows as a first-class artifact

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

### 5. Treat protocol extraction as a conditional branch

Retain protocol extraction, but reposition it as a secondary branch that runs
only for documents or collections that are suitable for procedural synthesis.

The branch should produce:

- `protocol_candidates`
- quality gating and abstain decisions
- final `protocol_steps` only for candidates that pass the quality bar

Returning zero final steps for a review-heavy collection is a valid and
preferred outcome when the alternative would be misleading steps.

### 6. Define the materials Phase 1 boundary around evidence and comparison

The first vertical delivery for materials science should prioritize:

- document typing for experimental versus review-heavy corpora
- Q-C-E or equivalent evidence cards
- material / process / structure / property comparison rows
- baseline and test-condition normalization
- collection-level warnings for protocol-limited corpora

The first vertical should explicitly optimize for:

- quickly finding comparable versus non-comparable results
- surfacing conflict sources across papers
- identifying weak-evidence claims before they enter experiment planning
- shortening literature review time without removing human judgment

Materials Phase 1 should not make "high-quality SOP from any uploaded paper"
the acceptance bar. Protocol and SOP outputs should remain a narrower branch
validated on methods-heavy material papers.

### 7. Expand workspace and API semantics

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

The main product value should come from `document_profiles`,
`evidence_cards`, and `comparison_rows`. Protocol artifacts remain important,
but they should no longer define the whole parsing backbone.

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

## Phase Boundary

### Phase 1 should prove

- Lens can distinguish review-heavy and methods-heavy collections
- Lens can distinguish strong-evidence versus weak-evidence claim regions
- evidence outputs are more trustworthy than the current steps-first outputs
- comparison-ready rows can support literature reading and experiment planning
- protocol browsing still works for suitable experimental papers
- users can trace important comparison judgments back to source evidence

### Phase 1 should not try to prove

- perfect full-paper scientific understanding
- universal protocol extraction across mixed corpora
- table, figure, and caption parsing completeness for all publishers
- autonomous experiment design without human review
- a broad, open-ended "chat with your papers" experience as the main product
- hypothesis oracle behavior or fully automatic scientific reasoning

## Explicit V1 Non-Goals

To avoid turning Lens into a toy workflow, Lens v1 should explicitly avoid
centering the following as primary promises:

- auto-generating SOPs from arbitrary corpora
- turning every paper into final protocol steps
- replacing evidence review with free-form generation
- prioritizing graph visual polish over comparison quality
- framing the system as an autonomous research agent
- presenting unsupported correlations as mechanistic insight

## Verification

The direction in this RFC is acceptable when all of the following are true:

- Lens outputs are useful even when a collection does not produce protocol
  steps
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
6. align workspace messaging and frontend discovery around clue/evidence-first
   browsing

This RFC should remain a proposal until the parsing direction and surface
semantics are explicitly accepted.
