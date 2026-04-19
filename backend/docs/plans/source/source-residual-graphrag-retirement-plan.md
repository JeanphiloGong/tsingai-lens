# Source Residual GraphRAG Retirement Plan

## Summary

This document records the backend-local follow-up plan to retire the remaining
GraphRAG-shaped runtime and indexing logic that still survives behind the
Source boundary.

The target is narrower than "replace all Source ingestion now".

This plan focuses on residual GraphRAG retirement after product-surface
cutover and query retirement:

- remove dead `infra/graphrag` helpers that no longer participate in runtime
- remove hidden incremental-update behavior that is not part of the public
  backend contract
- reduce Source/indexing output requirements to the minimum handoff still
  needed by Core
- retire entity/community/report/embedding indexing stages once that minimum
  handoff exists

It should be read as the next backend-local retirement wave after the query
path has been removed.

For the next Source follow-up after runtime shrink, read
[`born-digital-source-parser-first-plan.md`](born-digital-source-parser-first-plan.md).
For the final repository-level deletion of the retired historical package, read
[`retrieval-package-retirement-plan.md`](retrieval-package-retirement-plan.md).

## Status

Status as of 2026-04-17:

- Wave A is complete
- Wave B is complete
- Wave C is complete
- Wave D is partially complete

Completed implementation in this repository now includes:

- default Source indexing emits only the minimal handoff consumed by Core:
  `documents.parquet` and `text_units.parquet`
- `create_final_text_units.py` no longer loads entities, relationships, or
  covariates
- default Standard/Fast pipeline registration has been reduced to:
  `load_input_documents -> create_base_text_units -> create_final_documents -> create_final_text_units`
- graph/community/report/embedding workflow files have been removed from the
  active workflow registry and deleted from `retrieval/index/workflows/`
- active `infra/source/*` code no longer imports `retrieval.*` directly; input
  loading, chunking, config shaping, storage/cache setup, and runtime logging
  now live inside Source-owned modules

Still pending after this cut:

- deeper retirement of now-orphaned GraphRAG operations, prompt/config slices,
  and supporting runtime modules that no longer sit on the active Source path
- product-facing cleanup of `graphml_*` readiness flags described in Wave E

## Context

The backend has already cut product-facing graph and report semantics over to
Core artifacts, and the public query surface has been retired.

That means the remaining GraphRAG footprint is now concentrated in Source and
indexing internals:

- `IndexTaskRunner` still calls `retrieval.api.index.build_index` before Core
  post-processing
- the default retrieval pipeline still creates `entities`, `relationships`,
  `communities`, `community_reports`, and embeddings
- hidden incremental-update paths still exist even though the public HTTP
  contract does not expose update mode
- `documents.parquet` and `text_units.parquet` are still produced through a
  GraphRAG-oriented indexing workflow even though they are the only outputs
  the current Core pipeline truly needs upstream

At the same time, the current Core and protocol flows still depend on the
Source handoff:

- `documents.parquet`
- `text_units.parquet`
- derived `sections.parquet`
- derived protocol artifacts when the collection is suitable

This plan therefore exists to answer one backend question:

which GraphRAG-owned Source/indexing pieces can be removed immediately, which
should be retired next, and which must remain until a minimal Source handoff is
fully in place.

## Scope

This plan covers:

- retirement of dead `infra/graphrag` runtime helpers
- retirement of hidden incremental-update flows
- simplification of Source/indexing pipeline stages
- reduction of Source output requirements to a minimal Core handoff
- retirement of residual entity/community/report/embedding indexing stages

This plan does not cover:

- redesign of Goal Brief or Goal Consumer layers
- replacement OCR or parsing-engine selection
- frontend IA or new product surfaces
- changes to the current Core-backed graph/report/product semantics
- protocol redesign beyond keeping its existing dependency on Source handoff

## Proposed Change

### Retirement Rules

- keep the current Core-backed product surface unchanged while Source internals
  shrink
- preserve `documents.parquet` and `text_units.parquet` until a replacement
  Source handoff exists and is verified
- do not keep entity/community/report artifacts merely because older GraphRAG
  indexing once produced them
- do not keep incremental-update code when the public backend task contract
  does not expose update mode
- treat `graph.graphml` as a legacy indexing byproduct, not as a product-facing
  graph authority

### Wave A: Remove Dead Infra GraphRAG Helpers

Goal:

- remove backend runtime helpers that no longer participate in the actual
  product or Source path

Primary changes:

- delete `backend/infra/graphrag/__init__.py`
- delete `backend/infra/graphrag/collection_store.py`
- delete `backend/infra/graphrag/graphml_export.py`

Reason:

- current runtime code no longer imports `infra.graphrag`
- graph export is now Core-derived in `infra/graph/graphml.py`
- collection bootstrap no longer needs a separate GraphRAG-owned helper layer

Exit criteria:

- `rg "infra\\.graphrag" backend --glob '!backend/docs/**'` returns no runtime
  imports
- backend compile/test guards no longer need to protect against
  `infra.graphrag` leakage outside historical docs or explicit retirement docs

### Wave B: Retire Hidden Incremental Update

Goal:

- remove incremental-index behavior that is not part of the public backend
  contract

Primary changes:

- remove `backend/application/indexing/run_mode_service.py`
- simplify `backend/application/indexing/index_task_runner.py` to full rebuild
  only
- remove update-only retrieval workflows:
  - `backend/retrieval/index/workflows/update_entities_relationships.py`
  - `backend/retrieval/index/workflows/update_text_units.py`
  - `backend/retrieval/index/workflows/update_covariates.py`
  - `backend/retrieval/index/workflows/update_communities.py`
  - `backend/retrieval/index/workflows/update_community_reports.py`
  - `backend/retrieval/index/workflows/update_text_embeddings.py`
  - `backend/retrieval/index/workflows/update_clean_state.py`
- remove `backend/retrieval/index/update/`
- remove update pipeline registration from
  `backend/retrieval/index/workflows/factory.py`
- remove `StandardUpdate` and `FastUpdate` from
  `backend/retrieval/config/enums.py`

Reason:

- `POST /api/v1/collections/{collection_id}/tasks/index` does not expose
  `is_update_run`
- update-mode downgrade logic is currently preserving a hidden behavior, not a
  public product capability

Exit criteria:

- task creation remains full-rebuild only
- no runtime code path still probes incremental baseline or update vector-store
  state
- retrieval pipeline registry no longer contains update workflow chains

### Wave C: Introduce Minimal Source Handoff

Goal:

- reduce Source/indexing outputs to the minimum set that current Core and
  protocol paths still require

Primary changes:

- define minimal required Source outputs as:
  - `documents.parquet`
  - `text_units.parquet`
  - optional import manifest/provenance
  - optional protocol downstream outputs created after Core suitability gating
- stop treating the following as required Source outputs:
  - `entities.parquet`
  - `relationships.parquet`
  - `communities.parquet`
  - `community_reports.parquet`
  - `covariates.parquet`
  - `embeddings.*`
  - `graph.graphml`
- rewrite `backend/retrieval/index/workflows/create_final_text_units.py` so it
  no longer depends on entities, relationships, or covariates
- keep `backend/retrieval/index/workflows/create_final_documents.py` only for
  document/text-unit normalization unless it can also be replaced by a simpler
  Source-native normalizer

Reason:

- current app-layer document/evidence/protocol code still depends on
  `documents.parquet` and `text_units.parquet`
- current product graph/report routes no longer depend on entity/community
  artifacts

Exit criteria:

- Core post-processing can run with only documents and text-units as Source
  handoff
- app-layer document/evidence/protocol flows no longer require GraphRAG entity
  or community artifacts to exist

### Wave D: Retire Residual GraphRAG Indexing Stages

Goal:

- remove the remaining entity/community/report/embedding pipeline stages once
  the minimal Source handoff exists

Primary changes:

- remove graph extraction/finalization workflows:
  - `backend/retrieval/index/workflows/extract_graph.py`
  - `backend/retrieval/index/workflows/extract_graph_nlp.py`
  - `backend/retrieval/index/workflows/finalize_graph.py`
  - `backend/retrieval/index/workflows/prune_graph.py`
- remove community/report workflows:
  - `backend/retrieval/index/workflows/create_communities.py`
  - `backend/retrieval/index/workflows/create_community_reports.py`
  - `backend/retrieval/index/workflows/create_community_reports_text.py`
- remove covariate/claim extraction when it is no longer needed by Source
  handoff:
  - `backend/retrieval/index/workflows/extract_covariates.py`
- remove text embedding generation when no retained Source capability still
  needs it:
  - `backend/retrieval/index/workflows/generate_text_embeddings.py`
- delete now-orphaned retrieval operations and prompt/config slices that only
  served those stages
- simplify `backend/retrieval/index/workflows/factory.py` to the reduced
  Source-normalization pipeline

Exit criteria:

- indexing no longer produces entity/community/report artifacts by default
- indexing no longer produces GraphRAG embeddings by default
- output directories still support:
  - document profiles
  - evidence cards
  - comparison rows
  - conditional protocol generation

### Wave E: Clean Product-Facing Residual Flags

Goal:

- remove backend-facing vocabulary that still reflects legacy indexing
  byproducts rather than current product semantics

Primary changes:

- decide whether `graphml_generated` and `graphml_ready` remain meaningful in
  workspace/task payloads now that GraphML is generated on demand from Core
- if not meaningful, retire those fields from:
  - `backend/application/workspace/artifact_registry_service.py`
  - `backend/controllers/schemas/task.py`
  - `backend/controllers/schemas/workspace.py`
  - associated tests and docs

Exit criteria:

- workspace/task readiness reflects current product capability rather than
  legacy pipeline side effects

## File Change Plan

### Phase 1: Low-Risk Immediate Deletions

- remove `backend/infra/graphrag/`
- remove update-only runtime and workflow paths
- update retrieval pipeline registration and enums accordingly
- update docs/tests that still describe hidden update behavior if any exist

### Phase 2: Minimal Source Handoff Refactor

- refactor `create_final_text_units.py`
- verify app-layer documents/evidence/protocol flows against reduced outputs
- reduce pipeline registration to only the stages still needed for handoff

### Phase 3: Residual Workflow Retirement

- delete graph/community/report/embedding stages
- delete now-dead retrieval operations and helpers
- clean config defaults that only exist for retired stages
- clean workspace/task residual readiness fields if they no longer describe a
  real product capability

## Verification

- `documents.parquet` and `text_units.parquet` still exist after indexing
- document profiles still build from the reduced Source handoff
- evidence cards still build from the reduced Source handoff
- comparison rows still build from the reduced Source handoff
- protocol artifacts still gate on Core suitability and still build when
  appropriate
- graph and report routes continue to consume only Core artifacts
- `rg "infra\\.graphrag|update_communities|update_community_reports|update_text_units|update_covariates" backend --glob '!backend/docs/**'`
  returns no runtime references after the relevant waves
- `rg "entities\\.parquet|relationships\\.parquet|communities\\.parquet|community_reports\\.parquet|graph\\.graphml|embeddings\\." backend/application backend/controllers backend/infra --glob '!backend/docs/**'`
  only returns intentionally retained compatibility or cleanup targets

## Risks

- `documents.parquet` and `text_units.parquet` are still part of the current
  app-layer dependency chain, so removing GraphRAG-owned workflows in the wrong
  order can break Core post-processing
- some retrieval operations are deeply shared by indexing workflows, so
  retirement should follow actual dependency edges rather than folder-level
  assumptions
- `generate_text_embeddings.py` may still support hidden Source capabilities
  such as vector-store maintenance; that dependency should be explicitly
  decided before deletion
- `graph.graphml` still appears in workspace/task readiness today, so deleting
  pipeline generation without cleaning those flags can leave misleading product
  semantics behind
- this plan can be mistaken for a full Source replacement; it only retires the
  residual GraphRAG-shaped implementation that is no longer justified by the
  current backend contract

## Recommended Execution Order

1. Wave A: remove dead `infra/graphrag` helpers.
2. Wave B: retire hidden incremental update behavior.
3. Wave C: reduce Source outputs to the minimal Core handoff.
4. Wave D: retire graph/community/report/embedding indexing stages.
5. Wave E: clean any residual product-facing readiness flags.

## Related Docs

- [`query-retirement-and-graphrag-query-decoupling-plan.md`](../derived/query-retirement-and-graphrag-query-decoupling-plan.md)
- [`goal-core-source-implementation-plan.md`](../backend-wide/goal-core-source-implementation-plan.md)
- [`source-collection-builder-normalization-plan.md`](source-collection-builder-normalization-plan.md)
- [`core-first-product-surface-cutover-plan.md`](../backend-wide/core-first-product-surface-cutover-plan.md)
- [`current-api-surface-migration-checklist.md`](../backend-wide/current-api-surface-migration-checklist.md)
- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
