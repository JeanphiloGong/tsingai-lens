# Docling-First Source Parser Cutover Plan

## Summary

This document records the concrete next Source parser wave after
[`source-parser-evaluation-plan.md`](source-parser-evaluation-plan.md) and
[`born-digital-source-parser-first-plan.md`](born-digital-source-parser-first-plan.md).

The target is narrow:

run a Docling-first parser spike against the fixed Source handoff contract, and
hard-cut the active Source runtime to the winning Docling-backed path if it
meets the benchmark and contract gates.

This plan exists because the current confusion in downstream Core extraction is
not only a Core problem. It is also a Source evidence-quality problem. The
backend should therefore improve parser quality first instead of continuing to
optimize Core semantics against weak section, table, and locator recovery.

Read this plan with:

- [`source-parser-evaluation-plan.md`](source-parser-evaluation-plan.md)
- [`born-digital-source-parser-first-plan.md`](born-digital-source-parser-first-plan.md)
- [`../backend-wide/materials-comparison-v2/implementation-plan.md`](../backend-wide/materials-comparison-v2/implementation-plan.md)

## Decision

- use Docling as the first concrete replacement route for born-digital Source
  parsing
- keep the Source-to-Core handoff contract fixed in this wave:
  `documents.parquet`, `text_units.parquet`, `sections.parquet`, and
  `table_cells.parquet`
- do not keep a long-lived dual-parser production path after cutover
- do not treat token chunking as the primary parser substrate on the active
  born-digital path
- hard-cut the active Source runtime only after Docling passes the benchmark
  and contract gates
- treat broader handoff simplification such as `text_blocks` or `table_rows`
  as a separate follow-up proposal rather than silently mixing it into this
  cutover

## Why This Plan Exists

The current Source runtime still reaches the final handoff through a path that
starts with generic ingest and chunking before section and table recovery.

That path is stable enough to keep the current artifacts on disk, but it is too
weak for the next materials-comparison wave because it still loses important
document structure:

- reading order in born-digital multi-column PDFs
- reliable heading hierarchy and section boundaries
- table row and cell structure
- page, span, and box locators needed for downstream traceback
- layout-sensitive evidence where methods, characterization, process variables,
  and results are scattered across headings, captions, and tables

The current `sections.parquet` and `table_cells.parquet` builders also still
depend heavily on Source-local heuristics in
[`../../../infra/source/runtime/source_evidence.py`](../../../infra/source/runtime/source_evidence.py).
Those heuristics were acceptable as a stopgap, but they are too weak to remain
the primary parsing path for the active born-digital runtime.

The next move should therefore be:

fix parser quality under the current Source contract before doing deeper
downstream Core simplification.

## Scope

This plan covers:

- benchmark freeze for born-digital parser comparison
- an isolated Docling parser spike under the Source seam
- mapping Docling output into the fixed Source handoff contract
- a hard cut of the active Source runtime if Docling passes the gates
- cleanup of superseded parser heuristics after cutover

This plan does not cover:

- scanned PDFs or OCR
- image-native chart extraction
- Core semantic redesign
- `comparison_rows` v2 redesign
- removal of the current `sections.parquet` and `table_cells.parquet` contract
- a new public Source artifact such as `text_blocks` or `table_rows`
- long-lived compatibility layers or dual-parser production execution

## Boundary Rules

- Source remains an observable-evidence layer, not a research-fact producer.
- Core remains the only producer of semantic objects such as sample variants,
  test conditions, baselines, and results.
- Docling-native objects must not leak into the Source public contract.
- Any parser-rich transient structure must stay internal to Source.
- If Docling wins, the backend should cut over in place and remove the old
  parser-first heuristics rather than preserving them behind a compatibility
  branch.

## Fixed Target Contract

This wave keeps the current collection-local Source artifacts defined in
[`../../../infra/source/contracts/artifact_schemas.py`](../../../infra/source/contracts/artifact_schemas.py):

- `documents.parquet`
- `text_units.parquet`
- `sections.parquet`
- `table_cells.parquet`

The key rule is:

the parser path may change aggressively, but the handoff contract to current
consumers does not change in this wave.

That means Docling must improve the quality of the same final Source outputs
rather than quietly introducing a second contract.

## Current Runtime Problem

Today the standard Source runtime in
[`../../../infra/source/runtime/workflows/factory.py`](../../../infra/source/runtime/workflows/factory.py)
still builds the handoff from this chain:

- `load_input_documents`
- `create_base_text_units`
- `create_final_documents`
- `create_final_text_units`
- `create_sections`
- `create_table_cells`

That sequence leaves three problems on the active path:

1. `create_base_text_units` still anchors the runtime in generic chunk-first
   logic rather than document-structure-aware parsing.
2. `create_sections` and `create_table_cells` must recover too much structure
   after the fact from already-degraded text.
3. `source_evidence.py` still contains primary heuristics for section recovery
   and table recovery instead of acting as a thin mapper over stronger parser
   output.

## Proposed Runtime Shape

The active born-digital runtime should become parser-first internally while
keeping the existing handoff externally.

The preferred active sequence after cutover is:

- `load_input_documents`
- one Docling-backed parsing step that recovers block, heading, and table
  structure
- `create_final_documents`
- `create_final_text_units`
- `create_sections`
- `create_table_cells`

The exact workflow names may change, but the important ownership rule is:

generic chunking stops being the substrate that section and table recovery sit
on top of.

### Internal Transient Object

This cutover should reuse the parser-first design direction already recorded in
[`born-digital-source-parser-first-plan.md`](born-digital-source-parser-first-plan.md):

- Source may build one parser-neutral transient object such as `source_blocks`
- that object stays internal to Source
- the active handoff remains the current four artifacts

This keeps parser richness inside the owning seam without introducing new
public layers.

### `documents.parquet`

- rebuild `text` from Docling-backed reading order instead of from generic
  chunker output
- prefer parser-derived title when available
- preserve existing provenance fields where they already exist

### `text_units.parquet`

- build text units from normalized structural blocks or small block groups
- compute `n_tokens` from final unit text rather than from chunker state
- stop treating token chunks as the primary parsing artifact

### `sections.parquet`

- derive sections from Docling heading and layout structure first
- keep the current output schema, but stop relying on heuristic recovery as the
  primary parser path
- retain only conservative normalization helpers when current consumers still
  need labels such as `methods` or `characterization`

### `table_cells.parquet`

- derive rows, columns, header paths, and unit hints from Docling-backed table
  structure first
- preserve page, box, and char-range locators when available
- avoid rebuilding table structure from flat body text except as a rejected
  spike fallback

## Execution Waves

### Wave A: Benchmark Freeze

- select 10 to 20 born-digital PDFs from `backend/data/test_file/`
- label the benchmark mix by layout type, paper type, and table density
- freeze a small scoring rubric for:
  - reading order
  - heading and section recovery
  - table row and cell quality
  - locator fidelity
  - runtime weight
- capture current-pipeline baseline outputs before the Docling spike begins

### Wave B: Isolated Docling Spike

- add the `docling` dependency under `backend/`
- implement one isolated Docling-backed parser path under
  `backend/infra/source/runtime/`
- map Docling output into one internal parser-neutral transient structure
- emit temporary benchmark versions of:
  - `documents.parquet`
  - `text_units.parquet`
  - `sections.parquet`
  - `table_cells.parquet`
- do not cut over the active standard pipeline in this wave

### Wave C: Contract Mapping Review

- compare the Docling spike against the current runtime on the frozen benchmark
- measure section boundary quality, heading fidelity, table quality, and
  locator quality
- record mapping pain and runtime cost explicitly
- reject the spike if it improves raw parser richness but still maps poorly to
  the fixed Source contract

### Wave D: Active Runtime Hard Cut

- update the standard Source pipeline in
  [`../../../infra/source/runtime/workflows/factory.py`](../../../infra/source/runtime/workflows/factory.py)
  to use the Docling-backed path
- rewrite the active implementations of `create_final_documents`,
  `create_final_text_units`, `create_sections`, and `create_table_cells` so
  they consume parser-first Source data instead of degraded generic chunks
- remove `create_base_text_units` from the active born-digital path if it still
  exists only to preserve the old generic parser flow
- keep the fixed handoff contract intact for current consumers

### Wave E: Cleanup

- remove superseded heuristics in
  [`../../../infra/source/runtime/source_evidence.py`](../../../infra/source/runtime/source_evidence.py)
  that were only needed because the parser substrate was weak
- delete temporary spike-only scripts or dead workflow branches
- keep one active born-digital parser path in production

## Expected Change Surface

The concrete implementation wave is expected to touch these Source-owned files:

- [`../../../pyproject.toml`](../../../pyproject.toml)
- [`../../../infra/source/runtime/workflows/factory.py`](../../../infra/source/runtime/workflows/factory.py)
- [`../../../infra/source/runtime/source_evidence.py`](../../../infra/source/runtime/source_evidence.py)
- [`../../../infra/source/runtime/workflows/create_base_text_units.py`](../../../infra/source/runtime/workflows/create_base_text_units.py)
- [`../../../infra/source/runtime/workflows/create_final_documents.py`](../../../infra/source/runtime/workflows/create_final_documents.py)
- [`../../../infra/source/runtime/workflows/create_final_text_units.py`](../../../infra/source/runtime/workflows/create_final_text_units.py)
- [`../../../infra/source/runtime/workflows/create_source_artifacts.py`](../../../infra/source/runtime/workflows/create_source_artifacts.py)
- [`../../../infra/source/runtime/workflows/create_table_cells.py`](../../../infra/source/runtime/workflows/create_table_cells.py)
- new Docling-backed parser implementation files under
  `backend/infra/source/runtime/`
- Source-owned tests under `backend/tests/`

## Acceptance Gates

Docling should become the active born-digital parser only if all of the
following are true:

- section recovery quality is materially better than the current runtime
- table row and cell recovery quality is materially better than the current
  runtime
- page, char-range, and box locator quality are materially better than the
  current runtime
- the fixed Source handoff contract is still emitted without a compatibility
  shim
- current downstream consumers can continue to read the Source artifacts
  without a second contract path
- runtime cost is acceptable for the expected local batch size

## Explicit Non-Goals For This Wave

This plan deliberately does not bless the current Core object model as the
final design.

The point of this wave is narrower:

fix Source parsing first so later Core cleanup can happen against better
observable evidence.

That means this wave does not answer:

- whether `document_profile_service` should shrink further
- whether `evidence_cards` should remain a first-class Core artifact
- whether `comparison_rows` should be rebuilt directly from sample and result
  objects
- whether the long-term Source contract should move from
  `sections/table_cells` toward `text_blocks/table_rows`

Those are follow-up decisions that should be recorded after the parser cutover
is measured, not silently mixed into this Source parser plan.

## Follow-up Docs

After this plan, the backend should record separate follow-up docs for:

- a cross-layer proposal on whether the long-term Source handoff should shift
  toward `documents`, `text_blocks`, and `table_rows`
- a Core object-model cleanup plan centered on:
  - `sample_variants`
  - `characterization_observations`
  - `test_conditions`
  - `baseline_references`
  - `measurement_results`
- a `comparison_rows` v2 plan that consumes sample and result objects directly

## Risks

- Docling may improve parser richness while still being too heavy for the local
  runtime budget
- Docling table output may still require non-trivial normalization before it
  fits the current Source contract
- the fixed `sections.parquet` and `table_cells.parquet` contract may still
  preserve some old assumptions until a later cross-layer handoff redesign
- downstream Core work may still need conservative `methods` and
  `characterization` labels in the short term even after parser quality
  improves
