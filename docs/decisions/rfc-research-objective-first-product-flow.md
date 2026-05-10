# RFC Research-Objective-First Product Flow

## Summary

This RFC records the full cutover direction from a material-first collection
workspace to a research-objective-first workspace.

The core judgment is:

- the top-level analysis unit should be a research objective, not a material
- a research objective should combine material scope, process or variable
  axes, property or outcome axes, and comparison intent
- material should remain an important facet inside a research objective, but
  should not be the product's primary navigation object
- research objectives should guide reading, routing, extraction, and
  comparison, but should not become the only owner of extracted facts
- the durable data goal remains a normalized, reusable, evidence-backed
  material fact substrate
- Core extraction, comparison assembly, backend APIs, and frontend workspace
  navigation should all be reorganized around research objectives
- the old material-first path should not remain as a second long-lived product
  path after the cutover

The intended product flow becomes:

```text
collection
-> research objectives
-> objective workspace
-> objective-scoped evidence, facts, comparisons, and report
```

The intended backend semantic flow becomes:

```text
Source artifacts
-> paper skim
-> research objective discovery
-> objective workspace refinement
-> objective-paper framing
-> objective-aware evidence routing
-> objective-scoped fact extraction
-> objective-scoped comparison
```

## Relationship To Current Docs

Read this RFC with:

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
- [Paper Facts And Comparison Current State](../architecture/paper-facts-and-comparison-current-state.md)
- [RFC Comparison-Result-Document Product Flow](rfc-comparison-result-document-product-flow.md)
- [RFC Comparable-Result Substrate and Materials Database Direction](rfc-comparable-result-substrate-and-materials-database-direction.md)
- [RFC Paper-Facts Primary Domain Model and Derived Comparison Views](rfc-paper-facts-primary-domain-model.md)

Backend implementation companions should live under `backend/docs/` and the
owning Core semantic-build package. Frontend implementation companions should
live under `frontend/docs/` or the owning collection route family.

This RFC changes shared product direction if adopted. It does not by itself
update the current backend API contract, frontend routes, or persisted
artifacts before implementation work lands.

## Context

The current product shape has drifted toward material-first navigation in the
first materials-science vertical:

```text
collection -> materials -> material research view -> comparison rows
```

That shape helped the first vertical because materials are a familiar anchor.
It also made the system easier to demo while the paper-facts and comparison
substrate were still stabilizing.

The limitation is now visible. A material is often too broad to define the
scientific comparison being performed. One material can carry several unrelated
questions:

- heat treatment and corrosion behavior
- additive-manufacturing parameters and tensile properties
- composition and phase structure
- porosity and fatigue behavior
- processing atmosphere and defect formation

If all of those are grouped primarily by material, the system can still mix
unrelated values and route irrelevant tables into the same review surface.

## Problem Statement

Material-first organization creates four structural problems.

### 1. The Top-Level Object Is Too Coarse

Researchers rarely ask only:

```text
What exists for 316L stainless steel?
```

They more often ask:

```text
How does heat treatment affect corrosion resistance of LPBF 316L?
How do energy density and scan speed affect tensile properties?
Which processing route improves density without sacrificing elongation?
```

Those are objective-shaped questions. Material is one dimension of the
question, not the whole question.

### 2. Table Meaning Depends On The Objective

The same table can have different meaning under different objectives.

For a heat-treatment corrosion objective, a chemical composition table is
background. For a composition-phase objective, it may be central evidence. For
a current-work performance objective, a literature-comparison table should not
be treated as current experimental measurements.

This cannot be solved cleanly by material grouping alone.

### 3. Comparisons Need Question Boundaries

Comparison rows should be grouped by the scientific question they answer.

When corrosion current density, tensile strength, hardness, composition
percentages, and fitting parameters all sit under one material workspace, the
workspace can look structured while still mixing different comparison intents.

### 4. Product Language Leaks The First Vertical

Materials science is the first proving vertical, not the permanent product
ceiling.

Keeping material as the top-level product object makes Lens look more like a
materials catalog than an evidence-backed research-comparison system. Research
objectives preserve the materials vertical while fitting broader experimental
research domains.

## Proposed Direction

### Promote Research Objective To The Top-Level Product Object

The primary collection workspace should list research objectives discovered
from the paper set or defined by the user.

A research objective should include:

- the question being answered
- material scope
- process, treatment, or variable axes
- property, result, or outcome axes
- comparison intent
- relevant and excluded papers
- evidence coverage and confidence

Example:

```json
{
  "objective_id": "obj_lpbf_316l_heat_treatment_corrosion",
  "question": "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?",
  "material_scope": ["316L stainless steel"],
  "process_axes": ["LPBF", "SLM", "heat treatment"],
  "property_axes": ["corrosion", "EIS", "polarization"],
  "comparison_intent": "compare as-built and heat-treated LPBF 316L corrosion behavior",
  "included_papers": ["P001", "P003"],
  "excluded_papers": ["P005"],
  "confidence": 0.86
}
```

### Demote Material To A Facet

Material remains important, but it becomes a facet inside an objective:

```text
research objective
  -> material scope
  -> process axes
  -> property axes
  -> evidence routes
  -> objective-scoped comparisons
```

The UI can still expose material filters and material chips. It should not make
material the object that owns the whole workspace.

### Replace Material Workspace With Objective Workspace

The main workspace should become:

```text
research objectives list
-> objective detail
-> paper relevance map
-> evidence routes
-> comparison matrix
-> evidence drilldown
-> report
```

The objective page should answer:

- what question is being compared
- which materials, processes, and properties define the scope
- which papers contribute evidence
- which tables and sections were accepted or rejected
- which facts and comparison rows support the answer
- where each fact traces back into the source documents

## Durable Fact Substrate

Research-objective-first does not mean facts only live under objectives.

The objective is the reading and extraction frame:

```text
Which research question is being answered?
Which papers, sections, and tables are relevant?
Which evidence should be skipped for this question?
Which facts are comparable under this question?
```

The durable data goal remains a normalized fact substrate:

```text
material
-> sample or variant
-> process or treatment
-> test condition
-> property
-> value and unit
-> baseline or comparison relation
-> evidence anchor
```

Each extracted fact should preserve two kinds of identity:

- objective provenance: which objective authorized and contextualized the
  extraction
- reusable fact identity: material, process, property, condition, baseline, and
  evidence fields that can be reused outside that one objective

This keeps the system compatible with later material database and material
benchmark views. Objective workspaces, material databases, material benchmarks,
reports, and future retrieval surfaces should all be projections over the same
evidence-backed fact substrate.

In short:

```text
research objective guided extraction
-> normalized material fact substrate
-> objective, material, benchmark, and report projections
```

## Backend Semantic Model

Core should stop treating material-scoped artifacts as the primary extraction
shape.

New primary internal artifacts should be:

- `paper_skims.parquet`
- `research_objectives.parquet`
- `objective_contexts.parquet`
- `objective_paper_frames.parquet`
- `objective_evidence_routes.parquet`
- `objective_measurement_results.parquet`
- `objective_comparison_rows.parquet`
- `objective_reports.parquet`

These artifacts should carry objective provenance, but the final facts should
still normalize reusable material, process, property, condition, baseline, and
evidence fields. They should not become unstructured objective-local text
results.

Existing material-first artifacts should no longer be the primary source of
truth after cutover:

- `sample_variants.parquet`
- `measurement_results.parquet`
- `comparison_rows.parquet`
- `collection_comparable_results.parquet`

They may be removed, replaced, or generated only as short-lived migration
diagnostics during the cutover. They should not remain as a second authoritative
semantic path.

## Core Extraction Pipeline

The objective-first Core pipeline should run in this order.

### Paper Skim

Each paper is scanned for a compact map:

- document type
- candidate materials
- candidate process and treatment families
- candidate property or outcome families
- changed variables
- table and figure evidence density
- possible objective candidates

This stage extracts a research map, not final measurement facts.

### Objective Discovery

Core summarizes paper skims into multiple research objectives.

The output should be question-shaped. It should not be only a list of
materials.

### Objective Workspace Refinement

Each objective receives its own context:

- aliases
- include rules
- exclude rules
- known process axes
- known property axes
- likely table roles
- relevance thresholds
- known gaps

This context is objective-local. Rules discovered for one objective should not
silently affect another objective.

### Objective-Paper Framing

For every objective and every paper, Core determines:

- whether the paper is relevant
- whether the paper is primary evidence, supporting background, review,
  modeling-only, or irrelevant
- which sections, tables, and figures may contribute
- which tables and sections should be skipped
- what variables and outcomes matter for that objective

### Objective-Aware Evidence Routing

Core routes text windows, tables, and figures using the objective context.

For tables, the router should classify the whole table before row extraction.
Small relevant tables can be sent as whole-table context while preserving
row-indexed evidence anchors. Large tables should use bounded global context
plus chunk rows.

### Objective-Scoped Fact Extraction

Final facts should be emitted under the objective that authorized extraction:

```text
objective
-> material scope
-> sample or variant
-> process or treatment
-> test condition
-> property
-> value and unit
-> baseline or comparison relation
-> evidence anchor
```

Facts should keep traceback to document, section, table, row, cell, quote, and
page or bounding box where available.

The objective field should be provenance and organization context. It should
not replace material, sample, process, property, condition, baseline, or
evidence identity.

### Objective-Scoped Comparison

Comparison assembly should group rows by objective first, then by property,
material facet, process axis, condition, and baseline.

The same paper can contribute to multiple objectives, but each contribution
must preserve the objective-specific route and evidence.

## Backend API Cutover

The public backend API should move from material routes to research-objective
routes.

New primary routes:

```text
GET /api/v1/collections/{collection_id}/research-objectives
GET /api/v1/collections/{collection_id}/research-objectives/{objective_id}
GET /api/v1/collections/{collection_id}/research-objectives/{objective_id}/comparison-rows
GET /api/v1/collections/{collection_id}/research-objectives/{objective_id}/evidence
GET /api/v1/collections/{collection_id}/research-objectives/{objective_id}/report
```

Material-first routes should be removed from the primary product contract after
the cutover:

```text
GET /api/v1/collections/{collection_id}/materials
GET /api/v1/collections/{collection_id}/materials/{material_id}/research-view
GET /api/v1/collections/{collection_id}/materials/{material_id}/review-report
```

If a temporary migration bridge is unavoidable during rollout, it must be
explicitly labeled, time-bounded, and removed in the same delivery wave or a
separate tracked cleanup wave. It should not become a long-lived compatibility
layer.

## Frontend Cutover

The collection workspace should replace the material list with a research
objective list.

Each objective card should show:

- question
- material scope
- process axes
- property axes
- relevant paper count
- evidence coverage
- comparison row count
- confidence or review status

The objective detail page should show:

- objective summary
- paper relevance map
- process and property axes
- comparison matrix
- evidence cards and source traceback
- routed tables and skipped-table reasons when useful for debugging
- objective report

Material should remain visible as filters, chips, and facets inside objective
views, not as the route owner.

## Implementation Sequence

1. Add Core objective artifacts, schemas, prompts, and extractor methods.
2. Add `research_objective_service.py` for paper skim and objective discovery.
3. Add `objective_facts_service.py` for objective-paper framing, routing, and
   objective-scoped fact extraction.
4. Add objective-aware table routing and whole-table extraction for relevant
   tables.
5. Add `objective_comparison_service.py` for objective-scoped comparison rows.
6. Bump Core semantic version to an objective-facts generation, such as
   `objective_facts_v1`.
7. Add backend `/research-objectives/*` routes and tests.
8. Replace frontend material workspace navigation with objective workspace
   navigation.
9. Remove material-first route usage from frontend clients.
10. Remove or disable material-first backend paths once objective-first routes
    pass contract tests.

## Verification

The cutover should be verified at three levels.

Backend semantic tests should prove:

- one collection can produce multiple research objectives
- one paper can contribute differently to multiple objectives
- objective-local context does not leak across objectives
- objective-guided extraction still emits normalized reusable material facts
- table routing uses objective context before fact extraction
- composition, modeling, literature comparison, and fitting-only tables do not
  produce current-work measurements for unrelated objectives
- objective facts keep evidence anchors

Backend API tests should prove:

- `/research-objectives` returns stable objective summaries
- objective detail, comparison rows, evidence, and report routes are
  collection-scoped
- removed or retired material routes are not still treated as the primary
  contract

Frontend tests should prove:

- the collection workspace opens on objective navigation
- objective cards and detail pages render from the new routes
- comparison and evidence drilldown still preserve source traceback
- material appears as a facet, not as the top-level route owner

## Acceptance Criteria

The cutover is complete when:

- the collection workspace is research-objective-first
- material-first pages are no longer the main product entry
- Core extraction produces objective-scoped facts and comparison rows
- Core facts still normalize into a reusable material fact substrate
- objective routes are the public backend contract
- frontend calls objective routes rather than material routes
- evidence traceability remains available for every surfaced result
- irrelevant tables no longer pollute comparison rows merely because they share
  a material label
- material database and material benchmark projections remain possible over
  the normalized fact substrate

## Deferred Work

This RFC does not require:

- autonomous objective creation from outside the collection workflow
- cross-collection objective reuse
- a generic agent planning surface
- abandoning materials science as the first proving vertical
- removing material filters or material labels from the product

Those can follow later if the objective-first workspace proves cleaner for
real research comparison work.
