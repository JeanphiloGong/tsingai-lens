# Source & Collection Builder Normalization Plan

## Summary

This document records the next backend child plan for the five-layer research
architecture:

harden the `Source & Collection Builder` seam so upload, goal seeding, and
future adapters all converge on one normalized import handoff before the Core.

This remains a backend-wide child plan under `docs/plans/`. It does not
justify a deeper documentation subtree yet because the affected ownership still
spans one backend seam across `application/collections/` and
`infra/ingestion/`.

For the broader five-layer roadmap, read
[`goal-core-source-implementation-plan.md`](goal-core-source-implementation-plan.md).
For the parent contract freeze, read
[`goal-core-source-contract-follow-up-plan.md`](goal-core-source-contract-follow-up-plan.md).

## Context

The five-layer architecture is now explicit:

- Goal Brief
- Source & Collection Builder
- Research Intelligence Core
- Goal Consumer / Decision Layer
- Derived Views / Downstream

The next missing backend seam is not a bigger Goal layer. It is a more stable
Source & Collection Builder contract.

Current backend facts:

- `application/collections/service.py` still mixes collection lifecycle,
  upload handling, PDF-to-text conversion, and stored-file registration in one
  method
- `infra/ingestion/` currently exposes only a thin `pdf_to_text` helper
- goal intake currently creates a `seed_collection`, but that handoff stops at
  an empty collection record
- indexing still expects collection input files under `collections/<id>/input`
  and should not be broken by this refactor

If search, crawler, or connector work is added before this seam is frozen, the
backend will likely accumulate source-specific import paths that bypass each
other and eventually pressure the Core contract.

## Scope

This child plan covers:

- one normalized import handoff contract for `Source & Collection Builder`
- ownership split between `infra/ingestion/` and `application/collections/`
- upload-path refactor onto that normalized seam
- explicit compatibility rules for future search, connector, and crawler
  adapters
- tests that enforce collection-boundary termination before Core work begins

This child plan does not cover:

- external search provider selection
- crawler ranking or orchestration
- changing Core artifact schemas
- introducing Goal Consumer outputs
- replacing the current GraphRAG indexing input contract in one pass

## Proposed Change

### Execution Goal

Any source channel should end in the same collection-backed import handoff.

That means:

- Goal Brief may request or annotate collection-building work
- Source & Collection Builder may gather, normalize, and store material
- Core remains the first layer allowed to emit `document_profiles`,
  `evidence_cards`, or `comparison_rows`

### Normalized Import Handoff

The handoff contract should be frozen as one batch-shaped object with three
top-level parts:

- `documents`
- `text_units`
- `source_metadata`

The purpose of this shape is not to mimic Core artifacts. Its purpose is to
give upload, search, and crawler adapters one shared pre-Core language.

#### `documents`

Collection-builder document records should identify the imported source object
before Core profiling.

Minimum target fields:

- `source_document_id`
- `origin_channel`
- `original_filename` or source title
- `stored_filename`
- `media_type`
- `storage_relpath`
- `checksum` when available
- `language` when available
- `ingest_status`

#### `text_units`

Normalized text payloads should be attached to source documents without
claiming any Core semantics.

Minimum target fields:

- `text_unit_id`
- `source_document_id`
- `sequence`
- `text`
- `page_ref` or equivalent locator when available
- `char_count`

#### `source_metadata`

Batch metadata should explain where the import came from and how it was
normalized.

Minimum target fields:

- `channel`
- `adapter_name`
- `adapter_version` when available
- `ingested_at`
- `warnings`
- `raw_locator` when available
- optional `goal_context` when the batch was created from Goal Brief seeding

### Ownership Split

#### `infra/ingestion/`

This layer should own source-specific normalization work:

- decode upload bytes
- parse PDFs or other raw formats
- normalize adapter outputs into the shared handoff shape
- surface parsing warnings without deciding research meaning

#### `application/collections/`

This layer should own collection assembly:

- create or resolve the target collection
- accept a normalized import batch
- write collection input files and collection file membership
- persist collection-owned import metadata when needed
- keep route-facing collection semantics stable

#### Goal Brief Boundary

`application/goals/` should remain outside this import implementation seam.

Its role here is limited to:

- creating or selecting a collection handoff
- passing optional goal context into Source & Collection Builder
- never writing import payloads or Core artifacts directly

### Staged Compatibility Rule

This refactor should preserve the current indexing contract while the seam is
introduced.

Stage-1 compatibility rule:

- continue writing collection input payloads under `collections/<id>/input`
- continue letting indexing read from the collection `input/` directory
- add the normalized import seam in front of that storage path rather than
  replacing the indexing contract immediately

This keeps the Source seam explicit without forcing a second large migration in
the same wave.

### Execution Phases

#### Phase 1: Introduce Normalized Import Models

Goal:

- define one ingestion-owned application seam that every source channel can
  target

Primary changes:

- add normalized import models under `infra/ingestion/`
- add one adapter-facing entry such as `normalize_upload(...)` or a similarly
  narrow ingestion service
- keep the models explicitly pre-Core and collection-builder-facing

Exit criteria:

- one batch-shaped object exists for upload and future adapters
- ingestion code no longer returns ad hoc one-off payloads

#### Phase 2: Refactor Collection Upload Through The New Seam

Goal:

- make `CollectionService.add_file` a thin collection-builder flow rather than
  a format-specific parser

Primary changes:

- move PDF conversion decisions behind the ingestion seam
- add a collection-owned import method that consumes normalized batches
- keep current route behavior and response shape stable

Exit criteria:

- upload path uses the shared normalization contract
- route-level upload behavior remains unchanged for clients

#### Phase 3: Persist Collection-Owned Import Context

Goal:

- keep enough source context at the collection boundary for debugging and
  future adapter parity without polluting Core ownership

Primary changes:

- decide and implement one collection-owned persistence point for normalized
  import context
- keep route-facing `files.json` lightweight
- record source-channel metadata without changing Core artifact storage

Preferred direction:

- preserve `files.json` as the route-facing file list
- add a separate collection-owned import manifest only if needed for audit or
  future adapter parity

Exit criteria:

- collection state captures source provenance consistently
- Core still reads collection inputs, not adapter-native payloads

#### Phase 4: Align Goal Seeding With Collection Builder

Goal:

- keep `seed_collection` explicit as a collection-builder handoff rather than
  an empty placeholder with unclear future meaning

Primary changes:

- document that Goal Brief may create an empty collection or collection draft
- route any future goal-seeded acquisition through the same normalized import
  seam
- keep `seed_collection` free of Core semantics

Exit criteria:

- goal-first and paper-first flows converge on the same collection-builder
  contract

#### Phase 5: Prepare Adapter Expansion Without Core Leakage

Goal:

- make future search, connector, or crawler work a source-adapter problem
  rather than a Core rewrite

Primary changes:

- define adapter expectations against the normalized import handoff
- prohibit adapters from writing Core readiness or Core artifacts
- require adapters to terminate at collection boundaries

Exit criteria:

- a new source adapter can be added by targeting the normalized handoff only

## File Change Plan

### Primary Code Areas

- `infra/ingestion/__init__.py`
- new normalized import models or services under `infra/ingestion/`
- `infra/ingestion/pdf_ingest.py`
- `application/collections/service.py`
- `application/collections/README.md`
- `application/goals/service.py` only if goal-side handoff wording needs minor
  clarification

### Possible HTTP Touch Points

- `controllers/collections.py`
- `controllers/schemas/collection.py`

HTTP changes should be avoided unless the normalized seam requires new
client-visible metadata.

### Test Coverage

- `tests/unit/services/test_collection_service.py`
- new ingestion seam unit tests under `tests/unit/services/` or a nearby
  ingestion-owned test slice
- `tests/integration/test_app_layer_api.py`

## Verification

### Contract Verification

- upload reaches a collection boundary without emitting Core artifacts
- source imports do not set `document_profiles_*`, `evidence_cards_*`, or
  `comparison_rows_*` readiness flags
- goal-first handoff still returns `seed_collection` only, not research facts

### Regression Verification

- existing collection creation and upload routes keep their response shape
- indexing still reads collection input files successfully
- Core services continue to run unchanged after collection import

### Future-Facing Verification

- a second adapter path can reuse the same normalized import models without
  changing Core code

## Risks And Guardrails

- If normalized import shape becomes too rich too early, Source will start
  impersonating Core semantics. Keep the contract operational and provenance-
  oriented only.
- If upload refactor changes collection input storage too early, indexing will
  regress. Keep Stage-1 compatibility explicit.
- If `seed_collection` grows hidden semantics, Goal Brief and Source &
  Collection Builder will blur again. Keep that object as a handoff pointer,
  not a research object.

## Outcome Target

After this wave:

- Goal Brief remains thin
- Source & Collection Builder has one explicit normalization seam
- Core keeps one collection-backed fact model
- future source expansion becomes a replaceable adapter problem rather than a
  semantic rewrite
