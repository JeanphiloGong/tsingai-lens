# Source Parser Evaluation Plan

## Summary

This document records the next backend-local decision plan for improving Source
PDF parsing quality after the current Source contract freeze.

The target is narrow:

evaluate and select a better born-digital PDF parsing route for Source without
changing the current Source-to-Core handoff contract.

This plan exists before another implementation wave because the backend has
already finished the more important boundary decision:

- Goal defines the research problem
- Source normalizes observable document evidence
- Core remains the only producer of research facts
- downstream comparison, graph, report, and protocol views consume Core

That means the next Source question is no longer "what should Source mean".
The next Source question is "which parser path gives the cleanest observable
evidence for the fixed Source contract".

Read this plan with:

- [`born-digital-source-parser-first-plan.md`](born-digital-source-parser-first-plan.md)
- [`materials-comparison-v2-plan.md`](../backend-wide/materials-comparison-v2-plan.md)
- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)

## Status

Status as of 2026-04-18:

- Source contract freeze is complete for the current handoff surface
- the default Source runtime now emits:
  `documents.parquet`, `text_units.parquet`, `sections.parquet`, and
  `table_cells.parquet`
- the active path still rides generic GraphRAG-era ingest and chunk
  infrastructure
- parser quality, reading order, heading recovery, and table structure quality
  are therefore still below the level needed for robust materials comparison

This page is therefore a parser-selection plan, not a Core redesign plan.

## Why This Plan Exists

The current Source outputs are now stable enough for downstream work.

The problem is that the runtime still reaches those outputs through a path that
was originally designed for generic ingest and chunking, not for scientific PDF
structure recovery.

Today the default pipeline in
[`../../../infra/source/runtime/workflows/factory.py`](../../../infra/source/runtime/workflows/factory.py)
is:

- `load_input_documents`
- `create_base_text_units`
- `create_final_documents`
- `create_final_text_units`
- `create_sections`
- `create_table_cells`

The later two outputs are now correct in ownership terms, but the earlier
parser path is still too weak for:

- multi-column reading order
- clean section boundary recovery
- reliable heading hierarchy
- table boundary and cell structure recovery
- precise locators for section and table evidence
- materials-paper patterns where methods, characterization, processing
  variables, and results are often scattered across layout-driven structures

The next move should therefore be:

freeze the Source contract and improve only the parser quality under it.

## Scope

This plan covers:

- evaluation of born-digital PDF parsing routes for Source
- comparison of parser candidates against the current fixed Source contract
- selection criteria for replacing the current generic parser path
- planning the cutover of the active Source runtime once one route is selected

This plan does not cover:

- scanned PDFs
- OCR engines
- image-native chart extraction
- Core semantic redesign
- `comparison_rows` v2 implementation
- Goal or Goal Consumer changes
- restoration of any GraphRAG graph, community, or query product surface
- long-lived compatibility paths or dual parser execution in production

## Fixed Target Contract

This evaluation is constrained by the existing Source handoff.

The parser is allowed to change.
The contract is not.

The selected route must still emit collection-local artifacts matching the
current backend contract:

- `documents.parquet`
- `text_units.parquet`
- `sections.parquet`
- `table_cells.parquet`

Those final columns are currently defined in
[`../../../infra/source/contracts/artifact_schemas.py`](../../../infra/source/contracts/artifact_schemas.py).

The selected route must therefore improve parsing quality while still
supporting:

- stable document-level text reconstruction
- text-unit construction without reintroducing graph artifacts
- section extraction with heading and locator support
- table-cell extraction with header-path and locator support

No candidate should be judged by how much extra ontology it can invent.
It should be judged by how cleanly it can supply observable evidence into this
fixed Source surface.

## Current Runtime Boundary

The current Source evidence generation point is
[`../../../infra/source/runtime/source_evidence.py`](../../../infra/source/runtime/source_evidence.py).

That means the parser-evaluation target is not abstract.
It is the concrete runtime path that eventually feeds:

- document text
- text unit grouping
- section recovery
- table-cell recovery

The replacement route should therefore be evaluated on whether it makes those
four artifacts materially better without changing ownership boundaries.

## Evaluation Corpus

The evaluation set should come from the existing born-digital PDFs already in
`backend/data/test_file/`.

The first benchmark set should intentionally include:

- review papers
- methods-heavy experimental papers
- multi-column layouts
- papers with process-parameter tables
- papers with characterization sections and test-method headings
- at least one Chinese-language born-digital PDF already present in the corpus

Recommended first benchmark size:

- 10 to 20 PDFs

The benchmark set should overrepresent the real domain already driving the
backend:

- metal additive manufacturing
- process parameter comparison
- thermal-history and in-situ heating papers
- structure and mechanical-property reporting

This keeps evaluation grounded in the actual papers the system already sees,
instead of in a generic document benchmark that does not reflect the product.

## Evaluation Dimensions

Each candidate route should be scored on these dimensions:

### Document Reconstruction

- title recovery quality
- reading-order stability
- paragraph continuity
- boilerplate leakage control
- reference-section isolation

### Section Recovery

- heading detection precision
- heading hierarchy quality
- section boundary quality
- ability to recover method and characterization sections
- quality of `sections.parquet` mapping to `text_unit_ids`
- page and char-range locator fidelity

### Table Recovery

- table boundary detection
- row and column stability
- header-path reconstruction quality
- cell text cleanliness
- unit recovery quality
- quality of `table_cells.parquet` for comparison-oriented tables

### Layout Robustness

- multi-column stability
- caption and footnote noise handling
- numbered heading stability
- handling of review papers versus experimental papers

### Contract Mapping Cost

- difficulty of mapping parser output into the current Source schemas
- amount of custom normalization code required
- risk of hidden compatibility layers or parser-specific shims

### Runtime And Operations

- local deployment complexity
- CPU and memory cost
- throughput on a small local batch
- failure visibility and debuggability
- ease of deterministic test coverage

## Candidate Routes

The evaluation should start with a short, opinionated candidate list rather
than a broad parser survey.

### Route A: Docling-First

Why it is a top candidate:

- strong document-structure orientation
- promising table and layout support for born-digital PDFs
- likely the best fit when `sections` and `table_cells` matter more than raw
  chunk throughput

Primary concerns:

- runtime weight
- mapping discipline is still required so Source does not absorb parser-native
  abstractions into its public contract

### Route B: PyMuPDF-First

Why it is a top candidate:

- strong low-level PDF access
- good control over page text, blocks, coordinates, and reading order
- likely the cleanest route if the team wants maximal control and minimal
  parser framework dependency

Primary concerns:

- more in-house logic is required for heading, section, and table structure
- table extraction quality may need more custom work than Docling

### Route C: GROBID

Why it remains worth evaluating:

- mature scholarly-document parsing orientation
- useful if section hierarchy and bibliographic structure prove more valuable
  than layout flexibility

Primary concerns:

- deployment and operational complexity
- TEI-centric output may add translation cost to the Source contract
- table extraction is not obviously the strongest fit for the current target

### Second-Tier Candidates

These can be tested only if the first three fail to meet the contract-quality
bar:

- `pdfplumber`
- `Marker`
- `Unstructured`

These should not be the first wave unless a concrete blocker appears.

## Recommendation

The recommended evaluation order is:

1. Docling-first spike
2. PyMuPDF-first spike
3. GROBID control comparison

This is the best ordering for the current repository because:

- the product now depends heavily on section and table quality
- the active corpus is born-digital and layout-sensitive
- the team does not currently need OCR or scanned-PDF handling
- Source contract mapping discipline matters more than generic extraction
  breadth

If Docling clearly wins on section and table quality without unacceptable
runtime cost, it should become the default replacement target.

If Docling is too heavy or too opaque, PyMuPDF should be the fallback primary
direction because it gives the cleanest direct control while keeping Source
ownership explicit.

## Execution Waves

### Wave A: Benchmark Freeze

- select 10 to 20 born-digital PDFs from `backend/data/test_file/`
- label the benchmark mix by layout type and paper type
- define one lightweight scoring sheet for sections, tables, reading order,
  and locator quality
- freeze the Source contract fields that each candidate must populate

### Wave B: Candidate Spikes

- build one isolated parsing spike for Docling
- build one isolated parsing spike for PyMuPDF
- optionally build one narrower GROBID comparison spike
- do not cut over the active pipeline in this wave

### Wave C: Contract Mapping Review

- map each candidate to `documents`, `text_units`, `sections`, and
  `table_cells`
- measure how much parser-specific glue code each route requires
- reject routes that force hidden compatibility layers or unstable abstractions

### Wave D: Selection And Active-Path Cutover

- choose one parser route
- replace the current upstream parsing path directly
- update the real Source workflows and their callers
- remove dead code from the rejected route and from the old path

## Exit Criteria

This plan is complete when one parser route is selected because it shows:

- materially better reading order than the current path
- better section recovery for methods and characterization content
- better table-cell recovery for parameter and result tables
- acceptable locator quality for page, bbox, or char-range fields
- clean mapping to the current Source contract
- no new product-facing parser abstraction
- no restored GraphRAG leakage into application or Core layers

## Decision Rule

Do not choose the parser with the most features.

Choose the parser that most cleanly improves the current Source evidence
surface while preserving the architecture rule that Source provides observable
evidence and Core alone produces research facts.
