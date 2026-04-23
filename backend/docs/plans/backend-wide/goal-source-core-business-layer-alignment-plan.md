# Goal Source Core Business-Layer Alignment Plan

## Summary

This document records the backend-local restructuring plan for making the
business layers explicit inside the existing technical layers.

The important clarification is:

- `controllers / application / infra` remain the outer technical layers
- `goal / source / core / derived` become the inner business layers inside
  those technical layers

This plan does not replace the backend's technical layering.
It makes the already chosen five-layer research architecture visible in code
organization.

Read this plan with:

- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
- [`../architecture/application-layer-boundary.md`](../../architecture/application-layer-boundary.md)
- [`../../application/docs/application-layer-one-shot-cutover-plan.md`](../../../application/docs/application-layer-one-shot-cutover-plan.md)

## Status

Status as of 2026-04-19:

- the five-layer research architecture is already defined in docs
- Source contracts are already being frozen in runtime
- Core-first graph and report cutover has already happened
- public query has already been retired
- `application/`, `controllers/`, and `infra/` now expose the business-layer
  split explicitly
- active Source entrypoints now live under `infra/source/*`
- active Source runtime support code now also lives under `infra/source/*`
  instead of importing `retrieval` runtime helpers directly
- retired GraphRAG public surfaces such as `retrieval/__main__`,
  `retrieval/api`, `retrieval/cli`, and `retrieval/prompt_tune` have already
  been removed

The main remaining mismatch is no longer package visibility.
It is residual engine ownership:

- active Source runtime package layout is clean, but historical `retrieval/*`
  still remains in the repository as a non-Source engine subtree
- some backend docs still describe the old tree more loosely than the code now
  does

## Why This Plan Exists

The backend currently has a clear architecture at the concept level, but not
yet at the package-layout level.

Today the code still reads as a mix of:

- technical layers such as `controllers`, `application`, and `infra`
- historical domain packages such as `documents`, `evidence`, and
  `comparisons`
- historical engine packaging under `retrieval`

That causes one specific problem:

the business-layer split that the backend now relies on is not explicit in the
code tree.

The result is visible in several places:

- Goal logic already has a package, but it sits beside unrelated groupings
- Source logic is scattered across collection lifecycle, indexing orchestration,
  artifact loading, artifact readiness, ingestion helpers, and retrieval-era
  runtime code
- Core logic is split across `documents`, `evidence`, `comparisons`, and part
  of `workspace`
- Derived logic is split across `graph`, `reports`, and `protocol`
- Goal Consumer / Decision logic is still intentionally absent, but the code
  tree gives no obvious placeholder rule for that absence

The purpose of this plan is to make the following truth visible in code:

- Goal defines the problem
- Source gathers and normalizes observable evidence
- Core produces research facts
- Derived views consume Core outputs

## Scope

This plan covers:

- backend-local package reorganization across `controllers`, `application`,
  and `infra`
- import rewrites needed by that reorganization
- relocation of still-active Source runtime code out of the historical
  `retrieval` package
- test and docs updates required by the package cutover

This plan does not cover:

- public API path changes
- Source contract changes
- parser-engine replacement work
- new Goal Consumer / Decision functionality
- long-lived compatibility layers, aliases, or forwarding packages

## Design Rules

- keep `controllers`, `application`, and `infra` as the outer technical layers
- make `goal`, `source`, `core`, and `derived` explicit inside those layers
- do not add compatibility shims or alternate import paths
- rewrite callers directly and delete old paths in the same wave
- do not create `decision/` yet; only add it when real goal-consumer logic
  exists
- keep current HTTP paths and response contracts stable during the package move
- keep the current Source handoff contract stable during this restructuring
- keep Core as the only producer of stable research facts
- keep `protocol`, `graph`, and `reports` downstream of Core
- retire `retrieval` rather than preserving it as a renamed shell

## Target Structure

The target structure is two-dimensional:

- outer layer: technical responsibility
- inner layer: business responsibility

The intended end state is:

```text
backend/
  controllers/
    goal/
    source/
    core/
    derived/

  application/
    goal/
    source/
    core/
    derived/

  infra/
    source/
      ingestion/
      runtime/
      config/
      contracts/
    derived/
      graph/
    persistence/
```

`decision/` is intentionally omitted from this target because there is not yet
enough real runtime logic to justify a package.

## Current-To-Target Mapping

### Application Layer

Goal:

- `application/goals/service.py`
  -> `application/goal/brief_service.py`

Source:

- `application/collections/service.py`
  -> `application/source/collection_service.py`
- `application/indexing/index_task_runner.py`
  -> `application/source/index_task_runner.py`
- `application/indexing/task_service.py`
  -> `application/source/task_service.py`
- `application/documents/input_service.py`
  -> `application/source/artifact_input_service.py`
- `application/workspace/artifact_registry_service.py`
  -> `application/source/artifact_registry_service.py`

Core:

- `application/documents/service.py`
  -> `application/core/document_profile_service.py`
- `application/evidence/service.py`
  -> `application/core/paper_facts_service.py`
- `application/comparisons/service.py`
  -> `application/core/comparison_service.py`
- `application/workspace/service.py`
  -> `application/core/workspace_overview_service.py`

Derived:

- `application/graph/service.py`
  -> `application/derived/graph_service.py`
- `application/graph/core_projection_service.py`
  -> `application/derived/graph_projection_service.py`
- `application/reports/service.py`
  -> `application/derived/report_service.py`
- `application/protocol/*`
  -> `application/derived/protocol/*`

### Controller Layer

Goal:

- `controllers/goals.py`
  -> `controllers/goal/intake.py`

Source:

- `controllers/collections.py`
  -> `controllers/source/collections.py`
- `controllers/tasks.py`
  -> `controllers/source/tasks.py`
- `controllers/schemas/collection.py`
  -> `controllers/schemas/source/collection.py`
- `controllers/schemas/task.py`
  -> `controllers/schemas/source/task.py`

Core:

- `controllers/documents.py`
  -> `controllers/core/documents.py`
- `controllers/evidence.py`
  -> `controllers/core/evidence.py`
- `controllers/comparisons.py`
  -> `controllers/core/comparisons.py`
- `controllers/workspace.py`
  -> `controllers/core/workspace.py`
- `controllers/schemas/documents.py`
  -> `controllers/schemas/core/documents.py`
- `controllers/schemas/evidence.py`
  -> `controllers/schemas/core/evidence.py`
- `controllers/schemas/comparisons.py`
  -> `controllers/schemas/core/comparisons.py`
- `controllers/schemas/workspace.py`
  -> `controllers/schemas/core/workspace.py`

Derived:

- `controllers/graph.py`
  -> `controllers/derived/graph.py`
- `controllers/reports.py`
  -> `controllers/derived/reports.py`
- `controllers/protocol.py`
  -> `controllers/derived/protocol.py`
- `controllers/schemas/graph.py`
  -> `controllers/schemas/derived/graph.py`
- `controllers/schemas/report.py`
  -> `controllers/schemas/derived/report.py`
- `controllers/schemas/protocol.py`
  -> `controllers/schemas/derived/protocol.py`

### Infrastructure Layer

Source ingestion:

- `infra/ingestion/normalized_import.py`
  -> `infra/source/ingestion/normalized_import.py`
- `infra/ingestion/pdf_ingest.py`
  -> `infra/source/ingestion/pdf_ingest.py`
- `infra/ingestion/source_adapter.py`
  -> `infra/source/ingestion/source_adapter.py`

Source runtime:

- `retrieval/index/run/run_pipeline.py`
  -> `infra/source/runtime/run_pipeline.py`
- `retrieval/index/run/utils.py`
  -> `infra/source/runtime/run_context.py`
- `retrieval/index/workflows/*`
  -> `infra/source/runtime/workflows/*`
- `retrieval/index/operations/source_evidence.py`
  -> `infra/source/runtime/source_evidence.py`
- `retrieval/index/typing/*`
  -> `infra/source/runtime/typing/*`

Source config and contracts:

- `retrieval/config/load_config.py`
  -> `infra/source/config/load_config.py`
- `retrieval/config/models/graph_rag_config.py`
  -> `infra/source/config/source_runtime_config.py`
- active indexing-mode definitions from `retrieval/config/enums.py`
  -> `infra/source/config/pipeline_mode.py`
- `retrieval/data_model/schemas.py`
  -> `infra/source/contracts/artifact_schemas.py`

Derived infrastructure:

- `infra/graph/graphml.py`
  -> `infra/derived/graph/graphml.py`

## Wave Plan

### Wave A: Application Business-Layer Cut

Objective:

make `application/` reflect `goal / source / core / derived` explicitly.

Actions:

- move Goal, Source, Core, and Derived implementations to their target package
  paths
- rewrite all runtime callers inside `application/`, `controllers/`, and
  `tests/` to the new application paths
- delete the old application package paths immediately after caller rewrites

Acceptance:

- no runtime or test import points at the old application package layout
- `application/` exposes business-layer packages rather than historical domain
  scattering

### Wave B: Controller Business-Layer Cut

Objective:

make the HTTP layer reflect the same business split without changing API
routes.

Actions:

- move controller modules into `goal / source / core / derived`
- move schema modules into matching grouped schema subtrees
- update router registration imports to the new controller paths

Acceptance:

- public API paths stay unchanged
- controller module names and schema locations reflect business-layer
  ownership

### Wave C: Infrastructure Source Runtime Cut

Objective:

turn active Source runtime code into an explicit `infra/source` subtree and
retire the still-active `retrieval` runtime seams.

Actions:

- move active ingestion helpers into `infra/source/ingestion`
- move active pipeline runner, workflows, typing, and Source evidence builders
  into `infra/source/runtime`
- move active config and Source artifact contracts into `infra/source/config`
  and `infra/source/contracts`
- update `application/source/index_task_runner.py` to call the new Source
  runtime entrypoint directly
- delete the replaced `retrieval` active runtime paths immediately after the
  cut

Acceptance:

- `application/source` no longer imports active runtime code from
  `retrieval.*`
- Source runtime is visible under `infra/source/*`
- the repository no longer relies on `retrieval/api/index.py` as an app-facing
  entry seam

### Wave D: Residual Retirement And Documentation Closure

Objective:

remove dead leftovers and make the new reading path explicit.

Actions:

- delete retired `retrieval/api`, `retrieval/cli`, `retrieval/prompt_tune`,
  `retrieval/prompts`, and any inactive engine support code not needed by the
  active Source runtime
- rewrite remaining tests still importing old paths
- update backend and application documentation to the new business-layer-aware
  tree

Acceptance:

- no active runtime or tests import `retrieval.*`
- no compatibility aliases remain
- docs describe the code tree in the same terms as the architecture

## Recommended Execution Order

The recommended implementation order is:

1. Wave A
2. Wave B
3. Wave C
4. Wave D

This order keeps the most important business-layer cut first:

- application semantics become readable first
- controller grouping follows without changing API behavior
- infra/runtime cutover happens only after the higher-level business split is
  visible
- retrieval retirement becomes the final cleanup step rather than the first
  destabilizing move

## Verification

Structural checks after the full cut:

- `find backend/application -maxdepth 2 -type d`
  should show `goal`, `source`, `core`, and `derived` groupings
- `find backend/controllers -maxdepth 2 -type d`
  should show `goal`, `source`, `core`, and `derived` groupings
- `find backend/infra -maxdepth 2 -type d`
  should show `source` and `derived` groupings
- `rg "from retrieval|import retrieval" backend --glob '!backend/docs/**'`
  should return no active runtime or test imports

Runtime checks:

- `python3 -m compileall backend/application backend/controllers backend/infra backend/tests`
- targeted pytest for:
  - indexing task orchestration
  - documents, evidence, and comparisons services
  - workspace API
  - graph/report/protocol derived surfaces

## Non-Goals And Guardrails

- do not create `decision/` just for symmetry
- do not mix this plan with parser-engine replacement work
- do not change Source contract fields during the package move
- do not preserve `retrieval` as a renamed compatibility shell
- do not introduce new wrappers, facades, or forwarding modules
- do not let Derived packages redefine Core facts

## Relationship To Existing Plans

This plan is not a duplicate of
[`../../application/docs/application-layer-one-shot-cutover-plan.md`](../../../application/docs/application-layer-one-shot-cutover-plan.md).

The earlier application-layer plan cleaned flat application shims and clarified
domain-packaged imports.

This plan goes one level deeper:

- keep the technical layers
- make the business layers explicit inside them

That is why this page belongs under backend-wide plans rather than only under
the application subtree.
