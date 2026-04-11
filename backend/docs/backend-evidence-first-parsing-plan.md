# Backend Evidence-First Parsing Refactor Plan

## Summary

This document records the backend-local implementation plan for shifting
literature parsing away from a protocol-first pipeline and toward an
evidence-first pipeline with conditional protocol generation.

The shared direction is defined in the project RFC
[`docs/10-rfcs/evidence-first-literature-parsing.md`](../../docs/10-rfcs/evidence-first-literature-parsing.md).
This backend plan narrows that direction into module-owned execution slices,
artifact changes, and verification targets.

## Scope

This plan covers backend-owned work only:

- parsing artifact shape
- backend service responsibilities
- collection workspace semantics
- backend API additions and adjustments
- verification slices for backend behavior

This plan does not cover:

- frontend redesign beyond API consumption implications
- OCR or scanned PDF support
- model provider selection
- graph export removal or replacement

## Proposed Change

### Phase 0: Repair current protocol payload fidelity

Before changing parsing direction, make the current backend responses faithful
to stored artifacts.

Goals:

- decode structured `*_json` fields when listing protocol steps
- expose source-bearing fields such as raw evidence spans where available
- ensure current protocol APIs are not hiding structured data already present in
  artifact storage

This keeps the existing system observable while larger parsing changes land.

### Phase 1: Add document profiling as a backend artifact

Introduce a document profiling stage that classifies each paper and determines
whether protocol extraction should run.

Proposed artifact:

- `document_profiles.parquet`

Suggested fields:

- `paper_id`
- `doc_type`
- `methods_density`
- `evidence_density`
- `protocol_extractable`
- `warnings`

Expected effect:

- review-heavy collections stop defaulting into final protocol step generation
- workspace can surface parsing suitability instead of only artifact existence

### Phase 2: Add evidence-first extraction outputs

Introduce backend services that extract evidence-oriented units before
protocol-specific units.

Primary artifact targets:

- `evidence_cards.parquet`
- `comparison_rows.parquet`

Evidence-oriented units should cover:

- material system or composition
- process or treatment conditions
- microstructure observations
- measurement methods
- property values and units
- baseline or control references
- evidence spans and confidence

Expected effect:

- structured retrieval becomes more useful for research analysis
- the backend exposes outputs closer to the actual materials-research workflow

### Phase 3: Reposition protocol extraction behind candidate filtering

Convert protocol extraction into a conditional branch rather than the default
main parsing output.

Proposed artifact split:

- `protocol_candidates.parquet`
- `protocol_steps.parquet`

Rules:

- only protocol-suitable documents enter the branch
- low-signal or weakly supported candidate steps remain candidates or are
  dropped
- final `protocol_steps` should represent filtered, defensible steps rather than
  every keyword hit

Expected effect:

- returning zero final steps becomes acceptable for unsuitable collections
- SOP draft generation depends on stronger protocol inputs

### Phase 4: Expand workspace and API semantics

Update workspace and collection APIs to reflect evidence-first parsing.

Suggested backend additions:

- document profile readiness
- evidence readiness
- comparison readiness
- document type distribution
- warnings for review-heavy or protocol-limited collections

Suggested API additions:

- `GET /api/v1/collections/{collection_id}/documents/profile`
- `GET /api/v1/collections/{collection_id}/evidence/cards`
- `GET /api/v1/collections/{collection_id}/comparisons`

The current protocol APIs remain, but should no longer imply that every indexed
collection is expected to produce final protocol steps.

## File Change Plan

### Keep

- `backend/services/collection_service.py`
- `backend/services/task_service.py`
- `backend/services/index_task_runner.py`
- `backend/services/artifact_registry_service.py`
- graph, query, and report flows outside the protocol branch

### Add

- `backend/application/document_profile_service.py`
- `backend/application/evidence_extract_service.py`
- `backend/application/comparison_service.py`
- `backend/application/protocol_candidate_service.py`

Potential helper additions if layout-aware parsing becomes explicit:

- `backend/application/layout_block_service.py`
- `backend/application/evidence_schema_service.py`

### Reposition or replace

The following current protocol services should no longer be the sole backbone of
literature parsing:

- `backend/application/protocol_section_service.py`
- `backend/application/protocol_block_service.py`
- `backend/application/protocol_extract_service.py`
- `backend/application/protocol_pipeline_service.py`

Their future role should be one of:

- protocol-branch helper logic
- compatibility layer during migration
- fallback parser for methods-heavy documents

### API and schema touchpoints

- `backend/controllers/collections.py`
- `backend/controllers/schemas/retrieval.py`
- `backend/controllers/schemas/workspace.py`
- `backend/services/workspace_service.py`

## Execution Order

1. repair current protocol response decoding and evidence field exposure
2. add document profiling artifact generation
3. surface profile readiness and warnings in workspace responses
4. introduce evidence extraction artifacts
5. introduce comparison normalization artifacts
6. split protocol extraction into candidates versus final steps
7. update SOP generation to depend on filtered final protocol steps
8. add collection-level APIs for profiles, evidence, and comparisons

This order is meant to preserve a usable backend while the parsing model
changes underneath it.

## Verification

### Regression verification

- current experimental sample fixtures still produce usable protocol results
- existing graph and report flows remain available
- protocol APIs continue to return valid payloads after decoding changes

### New behavior verification

- review-heavy fixtures produce zero or near-zero final protocol steps
- document profiles classify fixtures into reasonable types
- evidence artifacts include conditions, measurement methods, and evidence spans
- comparison artifacts expose normalized cross-paper rows
- workspace clearly signals when a collection is protocol-limited

### Test slices

- unit tests for document profiling decisions
- unit tests for evidence extraction normalization
- unit tests for comparison-row generation
- protocol branch tests for candidate filtering and abstain behavior
- app-layer tests for new workspace and collection APIs

## Risks

- Current service relocation from `services/` to `application/` is already in
  flight, so parsing refactor work must avoid fighting the ongoing package move
- Artifact count and storage complexity will increase
- Document typing heuristics may be noisy before corpus tuning
- Mixed papers may require warnings rather than clean binary classification
- API surface growth can confuse consumers unless workspace messaging stays
  clear

## Related Docs

- [`../../docs/10-rfcs/evidence-first-literature-parsing.md`](../../docs/10-rfcs/evidence-first-literature-parsing.md)
  Shared parsing direction RFC
- [`backend-overview.md`](backend-overview.md)
  Current backend architecture overview
- [`api.md`](api.md)
  Current public backend API contract
- [`../../docs/research/materials-optimize.md`](../../docs/research/materials-optimize.md)
  Research-facing requirements that motivate the refactor
