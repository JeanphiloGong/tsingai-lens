# Retrieval Package Retirement Plan

## Summary

This document records the final backend-local plan for removing the historical
`backend/retrieval/` package from the repository after the active Source
runtime has already been cut over to `infra/source/*`.

The purpose of this plan is not to redesign Source contracts again.
It is to finish the package retirement work that remains after runtime
decoupling:

- remove the last non-`retrieval` code dependency
- delete the retired `backend/retrieval/` subtree in one cut
- update living backend docs that still describe `retrieval/` as an active
  package
- verify that no runtime or tests still depend on it

Read this plan with:

- [`source-residual-graphrag-retirement-plan.md`](source-residual-graphrag-retirement-plan.md)
- [`goal-source-core-business-layer-alignment-plan.md`](goal-source-core-business-layer-alignment-plan.md)

## Status

Status as of 2026-04-19:

- active `infra/source/*` runtime no longer imports `retrieval.*`
- retired GraphRAG public surfaces have already been removed
- `backend/retrieval/` still exists as a historical package subtree
- the last known non-`retrieval` code dependency is:
  [`../../tests/unit/utils/test_lancedb_vector_store.py`](../../tests/unit/utils/test_lancedb_vector_store.py)
- several living backend entry and architecture docs still mention
  `retrieval/` as an active package

This means the repository has completed runtime cutover but not repository
retirement.

## Why This Needs Its Own Plan

This work should not be left implicit inside broader Source-retirement plans.

The remaining task is narrower and more operational:

- it deletes a whole historical package subtree
- it changes backend entry-page and architecture wording
- it removes the last direct test dependency on `retrieval.*`

That is a different scope from Source handoff shaping or parser-engine
evaluation.

## Current State

### What Is Already True

- Source runtime ownership now lives under `infra/source/config`,
  `infra/source/contracts`, `infra/source/ingestion`, and
  `infra/source/runtime`
- active Source runtime package code no longer imports `retrieval.*`
- Core-first graph/report cutover has already happened
- public query surfaces backed by GraphRAG have already been retired

### What Still Remains

- `backend/retrieval/` still contains historical engine code:
  - cache and callback helpers
  - config and data models
  - legacy indexing operations
  - tokenizer and language-model support
  - vector-store implementations
- one backend test still imports `retrieval.*`
- backend entry and architecture docs still list `retrieval/` as a live owned
  package

## Scope

This plan covers:

- removing the final direct test dependency on `retrieval.*`
- deleting the entire `backend/retrieval/` subtree
- updating living backend docs that still describe `retrieval/` as active
- verifying repository-level retirement

This plan does not cover:

- new Source contract changes
- parser-engine replacement work
- new vector-store architecture under a different ownership node
- new retrieval or query product capabilities

## Retirement Rules

- do not preserve `backend/retrieval/` as a compatibility shell
- do not add wrappers, aliases, or forwarding imports
- do not keep dead tests just to preserve the old package
- if a future capability still needs tokenizer, vector-store, or model support,
  it must reappear under a new active ownership node rather than keeping
  `retrieval/` alive

## Proposed Change

### Wave A: Remove Final External Dependency

Goal:

- remove the last backend test that still imports `retrieval.*`

Primary changes:

- delete
  [`../../tests/unit/utils/test_lancedb_vector_store.py`](../../tests/unit/utils/test_lancedb_vector_store.py)

Reason:

- no active backend runtime path depends on `retrieval.vector_stores.*`
- keeping this test would force the historical package to remain reachable

Exit criteria:

- `rg "from retrieval\\.|import retrieval\\." backend --glob '*.py' --glob '!backend/retrieval/**'`
  returns no matches

### Wave B: Delete The Historical Package

Goal:

- remove the retired engine subtree in one cut

Primary changes:

- delete `backend/retrieval/` entirely, including:
  - `cache/`
  - `callbacks/`
  - `config/`
  - `data_model/`
  - `factory/`
  - `index/`
  - `language_model/`
  - `logger/`
  - `prompts/`
  - `storage/`
  - `tokenizer/`
  - `utils/`
  - `vector_stores/`
  - `README.md`
  - `__init__.py`

Reason:

- the package no longer owns any active backend runtime responsibility
- leaving it in place would keep the repository tree inconsistent with the
  business-layer cut that has already been implemented

Exit criteria:

- `backend/retrieval/` no longer exists

### Wave C: Update Living Backend Docs

Goal:

- remove active-package wording that still points readers at `retrieval/`

Primary changes:

- update [`../../README.md`](../../README.md)
- update [`../README.md`](../README.md)
- update [`../architecture/overview.md`](../architecture/overview.md)
- update
  [`../architecture/application-layer-boundary.md`](../architecture/application-layer-boundary.md)
- adjust plan-family docs only where they still speak about `retrieval/` as a
  currently present active subtree rather than historical lineage

Reason:

- backend entry and architecture pages should match the actual code tree

Exit criteria:

- living backend entry and architecture docs no longer describe `retrieval/`
  as an active owned package

### Wave D: Verify Retirement

Goal:

- prove that the repository no longer depends on the retired package

Verification:

- `rg "from retrieval\\.|import retrieval\\." backend --glob '*.py'`
  returns no matches
- `python3 -m compileall backend/application backend/controllers backend/infra backend/tests`
- targeted pytest for:
  - Source runtime
  - indexing task orchestration
  - workspace/document/evidence/comparison services
  - app-layer API smoke paths touched by config loading

Exit criteria:

- no runtime or tests import `retrieval.*`
- `backend/retrieval/` is gone
- backend docs and code tree tell the same story

## Risks

- if any hidden test fixture or optional local tool still imports
  `retrieval.*`, the delete cut will expose it immediately
- if future vector-store support is still wanted, it must be reintroduced under
  a new active ownership node such as `infra/source/*` or another explicit
  backend-owned package, not by reviving `retrieval/`

## Recommended Execution Order

1. Wave A
2. Wave B
3. Wave C
4. Wave D

This order keeps the cut simple:

- remove the last external dependency first
- delete the package second
- rewrite living docs only after the code tree matches the target state
- finish with repository-level verification
