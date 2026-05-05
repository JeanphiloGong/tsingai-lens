# RFC Research View Aggregation Layer

## Summary

This RFC records the product and architecture direction for turning extracted
paper facts into research-facing views.

The main decision is:

- raw `measurement_results`, `evidence_anchors`, `test_conditions`, and related
  paper facts remain the traceable fact layer
- paper pages should default to aggregated research objects such as sample
  matrices and condition series
- collection pages should default to material profiles, with comparable groups
  presented inside material context
- raw extracted records should stay available as evidence, QA, and debugging
  views rather than acting as the primary product surface

This direction preserves the Lens v1 evidence-first and comparison-first
boundary while correcting the product shape that appears when every extracted
fact is displayed as a standalone result card.

## Context

The current extraction output can produce hundreds of result-like records for a
single paper. That shape is useful for tracing and quality assurance, but it is
not the form a researcher needs for decision making.

For example, a paper may produce many `measurement_results`, including
duplicate scalar values, text-derived paraphrases, generic observations, and
table-grounded facts. Listing those records directly answers:

- what did the extractor emit?
- where can each emitted record be traced?
- which emitted records need correction?

It does not directly answer:

- which samples or variants does this paper study?
- what process parameters define each sample?
- which properties were measured for each sample?
- what changed across the compared samples?
- what evidence supports each cell in the research table?

The product needs both layers. The raw layer supports trust and correction. The
aggregation layer supports comprehension and comparison.

## Product Boundary

The system should distinguish three user-facing meanings.

### Research Views

Research views are the default experience for users trying to understand a
paper or compare a collection. They organize extracted facts into durable
research objects:

- material profiles
- sample matrices
- comparison groups
- cross-paper matrices
- condition series
- evidence-backed values

### Evidence Views

Evidence views explain why a value, row, group, or comparison should be trusted.
They expose source anchors, table rows, source text, confidence, conflicts, and
duplicate facts.

### Extraction Debug Views

Extraction debug views show the raw fact inventory. They are for QA, annotation,
and system repair. They may display individual `measurement_results`,
`sample_variants`, `test_conditions`, `evidence_anchors`, and unresolved
artifacts directly.

Raw facts should remain inspectable, but they should not be the default
research workspace.

## Paper Detail Shape

A paper detail page should use the source document as the ownership boundary for
single-paper research understanding.

Recommended paper detail structure:

```text
Paper Detail
- Overview
- Materials
- Sample Matrix
- Condition Series
- Evidence Records
- Extraction Debug
```

The current extracted-record list belongs under `Evidence Records` or
`Extraction Debug`. It should not be the default paper result surface.

Paper detail should also expose material-scoped views, but only within the
single source document. A document-scoped material view answers:

- which materials does this paper study?
- how is this material prepared in this paper?
- which samples or variants belong to this material in this paper?
- which process conditions, test conditions, and measurement results are bound
  to those samples?
- which within-paper comparisons or condition series can be assembled?

It should not answer cross-paper material questions. Cross-paper alias merging,
collection-wide process ranges, cross-paper trends, and collection-level
comparability belong to the collection material profile.

### Paper Overview

The overview should summarize the paper's detected research structure:

- material systems
- sample or variant count
- main process variables
- measured properties
- condition families
- extraction and evidence warnings

For a PBF-metal paper, this might say that the paper studies 316L stainless
steel, sixteen sample variants, scanning strategy, scan speed, energy density,
hatch spacing, and five core performance metrics.

### Paper Materials

The paper `Materials` section should be the main entry when one paper contains
more than one material system or when users need to inspect one material inside
the source document before looking at the full collection profile.

Recommended document-scoped material structure:

```text
Material In This Paper
- Overview
- Samples / Variants
- Sample Matrix
- Process Conditions
- Test Conditions
- Results Matrix
- Within-Paper Comparisons
- Condition Series
- Evidence
```

This view should reuse the paper's extracted facts and evidence anchors. It may
perform local material-name normalization inside the document, but it should
not create a second cross-paper material hierarchy. The same material can link
out to the collection-scoped material profile when that profile exists.

### Sample Matrix

The sample matrix is the first paper-level aggregation target.

It should organize one paper into rows by sample or variant and columns by
process variables and measured properties:

```text
Sample | Material | Strategy | Speed | Energy Density | Density | Hardness | YS | UTS | Elongation
```

Each property cell should be an evidence-backed value, not a bare scalar. The
cell should retain links to:

- one or more `measurement_result` ids
- evidence anchor ids
- source table or text context
- duplicate or conflict status
- confidence or epistemic status

Duplicate raw facts should not create duplicate visible rows. They should
appear as duplicate badges or evidence details inside the relevant cell.

### Condition Series

A paper may report values along a condition axis such as temperature, strain
rate, time, frequency, or heat-treatment condition.

Those facts should not be displayed as independent result cards when they form
a coherent series. They should become a condition series such as:

```text
Sample A - yield strength vs test temperature
25 C -> 940 MPa
200 C -> 820 MPa
400 C -> 650 MPa
```

The primary object is the series. Individual points remain traceable through
their linked facts and anchors.

## Collection Workspace Shape

A collection workspace should use the collection as the ownership boundary for
cross-paper comparison.

Recommended collection structure:

```text
Collection Workspace
- Overview
- Materials
- Papers
- Graph
- More
```

The collection page should not directly list every `measurement_result` from
every paper as the main comparison surface.

### Collection Overview

The overview should explain the collection's comparison readiness:

- number of papers
- paper types and coverage
- material systems
- process families
- properties
- main variable axes
- common missing context or warnings

### Materials

Materials should be the primary collection research entry. Users normally think
from a material or paper before they think from an internal comparison group
identifier.

The material list should show one row or card per canonical material:

```text
Material | Papers | Samples | Processes | Properties | Comparisons | Evidence
```

Each material entry should link to a material detail page. That page is the
right home for material-specific samples, process ranges, measured properties,
comparison groups, condition series, and evidence.

### Material Detail

Material detail should act as the collection-scoped material profile.

Recommended material detail structure:

```text
Material Profile
- Overview
- Papers
- Sample Matrix
- Process Parameters
- Property Summary
- Comparisons
- Condition Series
- Evidence
```

The material profile should summarize:

- canonical material name and aliases
- papers where the material appears
- samples and variants bound to the material
- process families and process-parameter ranges
- measured properties and evidence coverage
- comparison groups for this material
- unresolved warnings and weak bindings

For a 316L stainless steel collection, this page should answer what papers
studied 316L, which samples and process parameters were extracted, what
properties were measured, and which variables appear to affect those
properties.

### Papers

The paper list should show whether each paper has enough structured facts to
support material profiling and comparison.

Typical columns:

```text
Paper | Samples | Process Params | Results | Conditions | Evidence | Issues
```

This view helps users decide which papers are usable, partial, or blocked
before entering cross-paper comparison.

### Comparable Groups

Comparable groups are evidence-backed comparison questions under a material
context. A group represents a question such as:

- 316L LPBF: energy density vs density
- 316L LPBF: scan speed vs hardness
- Ti-6Al-4V LPBF: heat treatment vs yield strength
- sample family: yield strength vs test temperature

Each group should preserve:

- material system
- process family
- variable axis
- fixed conditions
- property or properties
- involved papers and samples
- comparability status
- missing context and warnings
- evidence-backed rows

Comparable groups should normally appear inside a material profile. A global
`All Comparisons` surface may remain under `More` for advanced search, QA, or
debugging, but it should not be the default collection entry.

### Cross-Paper Matrix

A cross-paper matrix should make the comparable group inspectable:

```text
Paper | Sample | Material | Process | Variable | Test Condition | Property | Result | Evidence
```

This matrix is where the user compares normalized facts across papers. It
should not hide missing context. Warnings should stay close to the row or group
they constrain.

## Frontend Collection Navigation

The collection workspace should expose a small set of primary tabs. The tabs
are navigation groups over the collection aggregation, not separate data
hierarchies.

Recommended collection tabs:

| Tab | Localized label | Primary job |
| --- | --- | --- |
| Overview | 概览 | Show collection status, comparison readiness, coverage, material systems, process variables, measured properties, and warnings. |
| Materials | 材料 | Show canonical materials as the primary research entry and link to material profiles. |
| Papers | 文献 | Show the paper list, each paper's processing state, coverage quality, issue count, and entry point into paper detail. |
| Graph | 图谱 | Support relationship exploration across papers, materials, processes, properties, and evidence; this remains secondary to comparison. |
| More | 更多 | Hold lower-frequency surfaces such as all comparisons, evidence records, extraction debug, exports, evaluation reports, and collection settings. |

The `Papers` tab should avoid creating a second literature hierarchy. It
should own the paper list and link into paper detail pages. Paper-specific
sample matrices, condition series, evidence, and debug views should belong to
the paper detail page rather than being duplicated as collection-level
navigation.

The `Materials` tab is the primary research tab at collection level. It should
organize results by canonical material and material profile instead of listing
raw `measurement_results` or global comparable groups as cards.

The `Comparison` concept remains useful, but it is no longer a primary
top-level tab in this direction. It should appear as a module inside material
detail and as `More / All Comparisons` for advanced global browsing.

The `More` tab is the right home for the current extracted-record browser if
that browser is retained at collection level. Users should still be able to
trace or QA raw facts, but the raw fact inventory should not be presented as
the collection's main result surface.

## Shared Object Direction

The aggregation layer should be understood as a derived view over paper facts,
not a replacement for the paper-facts family.

Recommended shared object families:

```text
PaperAggregation
PaperMaterialSummary
DocumentMaterialProfile
SampleMatrix
SampleMatrixRow
EvidenceBackedValue
ConditionSeries
CollectionAggregation
MaterialSummary
MaterialProfile
PaperCoverageRow
ComparableGroup
CrossPaperMatrix
```

These names describe product-facing aggregation objects. They may be
implemented as backend service responses first and later promoted to persisted
artifacts when the shape stabilizes.

The first implementation should avoid forcing the frontend to reconstruct this
layer from raw artifacts in route components. Frontend code should render the
aggregation and open evidence details; backend or shared aggregation services
should own the grouping, deduplication, and trace-preserving shape.

## Evidence And Debug Relationship

Every aggregated value should preserve traceback to the raw facts that produced
it.

For a matrix cell, evidence details should include:

- linked `measurement_result` ids
- linked `evidence_anchor` ids
- source table or text context
- duplicate count
- conflict status
- missing fields
- confidence or epistemic status

This keeps the product readable without weakening traceability.

## First Delivery Slice

The first delivery slice should target table-heavy PBF-metal papers and produce
a single-paper sample matrix.

The minimal useful result is:

- one paper detail research view
- sixteen sample rows for the P001-style case
- core performance columns for density, hardness, yield strength, ultimate
  tensile strength, and elongation
- process columns for strategy, scan speed, energy density, and hatch spacing
  when confidently available
- duplicate facts shown inside evidence details rather than as repeated visible
  results
- generic material or process concepts excluded from matrix rows
- a path back to raw extracted facts for QA

Collection-level comparable groups should follow after the paper matrix is
stable, because collection comparison depends on trustworthy paper-level
sample, process, condition, and result binding.

## Acceptance Signals

For the first PBF-metal slice, the paper detail research view should satisfy:

- paper-scoped materials are visible when the source document contains
  material bindings
- sample matrix rows match the real experimental sample set
- core property cells preserve evidence links
- duplicate raw results do not duplicate visible matrix cells
- generic material names and process concepts do not become sample rows
- unresolved test conditions are visible as warnings rather than hidden
- the raw extraction record list remains reachable as a debug view

For the first collection slice, the collection workspace should satisfy:

- materials are the default collection research objects
- material summaries and paper coverage are visible before advanced
  comparison browsing
- material profiles expose their sample matrices, process ranges, property
  summaries, comparable groups, condition series, and evidence
- comparable groups appear under material profiles or advanced global browsing
- cross-paper matrices are grouped by research question
- raw extracted records are available only as evidence or debug views
- missing context and comparability warnings remain visible

## Boundaries

This RFC does not define final API schemas, database storage shape, or detailed
frontend component layout. Those belong in module-owned backend and frontend
plans after the shared product direction is accepted.

This RFC also does not require full pairwise expert comparison matching in the
first delivery slice. Pairwise comparison should come after sample matrices,
condition families, and measurement deduplication are reliable enough to
support it.

## Related Docs

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
- [Paper Facts And Comparison Current State](../architecture/paper-facts-and-comparison-current-state.md)
- [Lens Core Artifact Contracts](../contracts/lens-core-artifact-contracts.md)
- [Research View Aggregation Contract](../contracts/research-view-aggregation-contract.md)
- [RFC Paper-Facts Primary Domain Model and Derived Comparison Views](rfc-paper-facts-primary-domain-model.md)
- [RFC Comparison-Result-Document Product Flow](rfc-comparison-result-document-product-flow.md)
- [Backend Research View Aggregation Plan](../../backend/docs/plans/backend-wide/research-view-aggregation/README.md)
- [Frontend Research View Aggregation Plan](../../frontend/docs/research-view-aggregation/README.md)
