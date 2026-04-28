# RAG-Anything Source Reference Plan

## Summary

This document records a conservative Source-layer plan after reviewing
[`HKUDS/RAG-Anything`](https://github.com/HKUDS/RAG-Anything) as an external
reference.

The target is narrow:

borrow parser-evaluation, including an explicit MinerU comparison, cache,
direct pre-parsed-content, and multimodal context ideas without turning
TsingAI-Lens into an all-in-one RAG framework.

This plan keeps the existing Lens boundary:

- Source preserves observable document evidence and locators.
- Core remains the only producer of research facts.
- evidence cards, comparable results, and comparison rows remain the Lens v1
  acceptance backbone.
- graph, generic RAG query, and multimodal chat do not become the primary
  workflow.

Read this plan with:

- [`source-parser-evaluation-plan.md`](source-parser-evaluation-plan.md)
- [`docling-first-source-parser-cutover-plan.md`](docling-first-source-parser-cutover-plan.md)
- [`source-structure-first-substrate-plan.md`](source-structure-first-substrate-plan.md)
- [`source-figure-asset-extraction-plan.md`](source-figure-asset-extraction-plan.md)
- [`../../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)

## Context

RAG-Anything is a multimodal RAG framework built around parser selection,
content-list insertion, modality-specific processors, LightRAG storage, graph
construction, and query modes.

That is a different product shape from TsingAI-Lens.

TsingAI-Lens currently needs a traceable literature-comparison Source
substrate, not a generic answer engine. The active Source direction is already
closer to the right shape:

- the PDF path is Docling-backed
- Source emits structure-first artifacts such as `blocks.parquet`,
  `figures.parquet`, `table_rows.parquet`, and `table_cells.parquet`
- Core post-processing builds document profiles, paper facts, evidence cards,
  and comparison rows after Source finishes

The useful comparison is therefore not "replace Source with RAG-Anything".
The useful comparison is "which RAG-Anything engineering ideas improve the
Source evidence substrate without changing product ownership".

## Comparison Notes

RAG-Anything is broader than the Source seam:

- it supports multiple parsers such as MinerU, Docling, PaddleOCR, and custom
  parser registration
- it separates text from images, tables, equations, and generic multimodal
  items
- it can insert a pre-parsed content list directly
- it processes multimodal items through modality-specific LLM or VLM
  processors
- it stores processed chunks, entities, and relationships in LightRAG
- it supports hybrid and VLM-enhanced query paths

TsingAI-Lens should keep a narrower Source layer:

- one active production parser path at a time
- fixed Source artifacts instead of parser-native public objects
- locator-first evidence rows instead of generated multimodal descriptions
- direct Core handoff instead of a LightRAG graph/query layer

## Borrowed Ideas

### Parser Benchmarking

Borrow the multi-parser evaluation idea, but keep it out of the production
runtime until a parser wins a measured gate.

RAG-Anything makes MinerU a first-class parser choice. Lens should compare
MinerU directly against the active Docling path, but only as an offline
benchmark candidate.

The first benchmark should include:

- the active Docling path as the baseline
- MinerU with automatic parsing as the primary external comparison
- PaddleOCR only when the fixture set includes OCR-heavy or scanned inputs

The comparison must judge the normalized Source artifacts, not parser-native
demos. MinerU only wins if its output maps more cleanly into Lens evidence
artifacts than the current path.

The benchmark should score:

- reading order
- heading and section recovery
- table row and cell recovery
- figure and caption linkage
- page, box, and character-span locators
- runtime cost and failure visibility
- mapping cost into the existing Source artifacts

The benchmark should not create a long-lived production parser switch.

The benchmark should record a clear result for MinerU:

- adopt later, if it clearly improves the Lens artifact scores and operational
  cost is acceptable
- reject, if mapping cost, runtime cost, or locator quality is worse
- keep inconclusive, if the corpus is too small or the setup is not
  reproducible

### Parse Cache

Borrow the parse-cache idea for repeated Source builds.

The cache key should be based on:

- source file checksum
- parser name and parser version
- parser configuration
- Source artifact schema version

The cache value should remain Source-owned intermediate or final evidence data,
not RAG-Anything content-list or LightRAG state.

### Direct Pre-Parsed Input

Borrow the direct content-list insertion idea through the existing normalized
Source import seam.

In Lens, this should mean allowing trusted pre-parsed document evidence to
still normalize into:

- `documents.parquet`
- `blocks.parquet`
- `figures.parquet`
- `table_rows.parquet`
- `table_cells.parquet`

This path must not bypass the Source artifact contract or write Core facts
directly.

### Local Context For Multimodal Evidence

Borrow the context-window idea for downstream extraction, not for generic RAG
answers.

When Core extracts from a table row, figure caption, or equation-like block, it
should be able to receive nearby Source context such as:

- heading path
- same-page neighboring blocks
- table caption
- figure caption
- row and cell header context

This improves evidence interpretation while keeping Core responsible for the
semantic decision.

## Rejected Paths

Do not add RAG-Anything as a backend dependency for the current Source wave.

Do not introduce LightRAG storage, graph construction, or query modes as part
of the Source runtime.

Do not keep MinerU, Docling, and PaddleOCR as parallel production parser
branches without a measured and approved reason.

Do not let Source-generated image, table, or equation descriptions become
research facts.

Do not add adapters, wrappers, shims, bridges, or compatibility layers around
the active Source runtime just to preserve optional parser paths.

## Delivery Sequence

### 1. Freeze A Source Parser Benchmark

Add an offline benchmark script for 10 to 20 representative born-digital
materials PDFs.

Suggested owned path:

- `backend/scripts/benchmarks/source_parser_benchmark.py`

The benchmark should emit comparable score summaries for the active Docling
path, a MinerU comparison spike, and any later candidate parser spike.

Minimum first matrix:

- Docling active path
- MinerU automatic parsing

Do not add MinerU to the backend dependency set or active runtime as part of
this benchmark freeze. Treat the MinerU run as an isolated measurement until a
separate implementation decision is approved.

Verification:

- benchmark can run against a small fixture set
- score output includes parser name, document id, dimensions, warnings, and
  runtime
- no production parser path changes

### 2. Add Source Parse Caching

Add a Source-owned cache around expensive parser output or mapped Source
artifacts.

The cache should invalidate when the input checksum, parser configuration, or
artifact schema changes.

Verification:

- first build parses and writes artifacts
- second build with the same source and config hits the cache
- changed PDF bytes miss the cache
- changed parser or schema version misses the cache

### 3. Harden Docling Mapping In Place

Improve the current Docling mapping directly in the Source runtime rather than
introducing a general parser abstraction.

Priority fixes:

- table caption to table id linkage
- figure caption matching and fallback limits
- heading path stability
- equation-like block preservation where Docling exposes it
- clearer parser warnings in artifact metadata

Verification:

- Source evidence workflow tests cover table, figure, and equation-like inputs
- `documents`, `blocks`, `figures`, `table_rows`, and `table_cells` schemas
  remain stable
- no parser-native object leaks into public artifacts

### 4. Pass Source Context Into Core Extraction

Let Core extraction consume structured Source context when interpreting table,
figure, and equation-like evidence.

This should be implemented as direct Core extraction input shaping, not as a
Source semantic layer.

Verification:

- evidence cards keep source locators
- comparison rows retain evidence linkage
- Source artifacts do not gain sample, result, baseline, or comparison facts

## Success Criteria

This plan is successful when:

- parser alternatives can be evaluated without production dual paths
- MinerU has a documented win, reject, or inconclusive result against Docling
- repeated Source builds avoid unnecessary parser work
- Docling mapping quality improves for tables, figures, headings, and
  equation-like blocks
- Core extraction receives better local evidence context
- the Source-to-Core boundary remains explicit and testable

It is not successful if the result becomes a generic RAG system, a LightRAG
integration, or a multi-parser compatibility layer.

## Risks

Parser benchmarks can become misleading if the fixture set is too generic.
The corpus should overrepresent the materials papers that drive Lens v1.

MinerU may require extra model downloads, runtime dependencies, or GPU-specific
configuration. Those costs should be part of the benchmark result rather than
hidden behind a production parser switch.

Parse caching can hide parser bugs if the cache key does not include parser
and schema versions.

Pre-parsed input can blur ownership if external content is allowed to skip
Source normalization. It must normalize into the same artifacts as uploads and
local PDFs.

Multimodal context can become untraceable if generated captions are treated as
facts. Generated descriptions should remain auxiliary unless Core extracts a
fact with source locator evidence.
