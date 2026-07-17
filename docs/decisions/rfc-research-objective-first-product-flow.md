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
- the final product object should be a traceable research logic chain, not
  only a comparison table or a set of evidence cards
- comparison rows, evidence cards, research-understanding workspaces, graph
  nodes, and workspace panels
  should be projections or support views over resolved evidence units and
  research logic chains, not separate final answers
- the old collection-wide `ComparisonRowRecord` should be retired as a Core
  semantic surface; controlled comparisons may still exist, but only as
  objective-scoped projections over resolved evidence units
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
-> objective-scoped evidence units
-> paper-level and cross-paper research logic chain
-> research understanding and workspace projections
```

The intended backend semantic flow becomes:

```text
Source artifacts
-> paper skim
-> research objective discovery
-> objective workspace refinement
-> objective-paper framing
-> objective-aware table and evidence routing
-> objective-scoped evidence-unit extraction
-> evidence resolution
-> research logic-chain assembly
-> objective-scoped comparison and research-understanding projections
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

### Make The Research Logic Chain The Final Product

Objective-scoped comparison rows and evidence cards are supporting views. They
are not the final product object by themselves.

The objective workspace should assemble a traceable research logic chain:

```text
research objective
-> paper relevance and contribution
-> material system
-> sample preparation or treatment route
-> changed variables and resolved sample conditions
-> characterization or test method
-> measured results
-> author interpretation
-> cross-paper agreement, conflict, and gaps
```

This chain is not just a fluent report. It is the resolved answer structure
that explains why a comparison is valid, which experimental route produced
each value, and where the claim traces back into the source paper.

For table-heavy papers, this means table identifiers such as `condition
number` and `sample number` should be retained as paper-local join and
traceback keys, but downstream logic-chain evidence should expose the resolved
experimental condition. For example, a mechanical-property objective should
not leave later stages with only `condition number = 1`; it should join the
condition table and result table so the evidence unit carries the actual SLM
condition, such as scan strategy, scanning speed, energy density, and the
measured mechanical properties.

Evidence resolution is therefore a required product boundary, not an optional
cleanup step. A comparison row may keep the paper-local key for traceback, but
the user-facing chain should resolve that key into the real preparation,
processing, test, or sample condition whenever the source paper provides the
join information.

Comparison matrices, evidence cards, reports, graph nodes, and future material
database views should be projections over this resolved evidence chain. The
research logic chain is the reader-facing answer structure.

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
-> resolved evidence units and research logic chains
-> objective, material, benchmark, and report projections
```

## Backend Semantic Model

Core should stop treating material-scoped artifacts as the primary extraction
shape.

The durable implementation should be database-record first. Research-objective
data should be stored through the Core persistence boundary rather than written
as standalone repository artifacts.

New primary Core records should be:

- `PaperSkim`
- `ResearchObjective`
- `ObjectiveContext`
- `ObjectivePaperFrame`
- `ObjectiveEvidenceRoute`
- `ObjectiveEvidenceUnit`
- `ObjectiveMeasurementResult`
- `ObjectiveComparisonRow`
- `ObjectiveLogicChain`
- `ResearchUnderstanding`

The SQLite-backed Core repository should persist those records in tables such
as:

- `core_paper_skims`
- `core_research_objectives`
- `core_objective_contexts`
- `core_objective_paper_frames`
- `core_objective_evidence_routes`
- `core_objective_evidence_units`
- `core_objective_measurement_results`
- `core_objective_comparison_rows`
- `core_objective_logic_chains`
- research-understanding artifacts owned by the collection build pipeline

These records should carry objective provenance, but the final facts should
still normalize reusable material, process, property, condition, baseline, and
evidence fields. They should not become unstructured objective-local text
results.

`ObjectiveEvidenceUnit` and `ObjectiveLogicChain` are the authoritative Core
outputs for the objective-first path. Evidence cards, research-understanding
workspaces, graph nodes, workspace panels, material views, and any comparison
matrix should be generated from those records as projections for review,
navigation, and presentation.

The old collection-wide `ComparisonRowRecord` shape should not be retained as
an authoritative semantic surface. It is too flat for objective-first
comparison because it forces each fact into material, property, process, test
condition, and result columns before the scientific question has defined what
is comparable. Paper-local row identifiers such as `Case`, `condition number`,
or `sample number` may be retained as sample keys or traceback keys, but they
must not become user-facing test-condition semantics merely because the old row
projection had no better place to store them.

Existing material-first Core records should no longer be the primary source of
truth after cutover:

- `SampleVariant`
- `MeasurementResult`
- `ComparisonRowRecord`
- `CollectionComparableResult`

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

Table routing should also identify table roles, column roles, and join plans.
For example, in an SLM parameter paper, a preparation table can define sample
conditions while a mechanical-property table reports results for the same
`condition number` and `sample number`. Those identifiers are not the final
condition semantics; they are keys used to resolve the real sample condition
before the logic chain is assembled.

### Objective-Scoped Evidence-Unit Extraction

Final extraction should emit evidence units under the objective that authorized
extraction:

```text
objective
-> material scope
-> sample or variant
-> process or treatment
-> resolved sample or experimental condition
-> test condition
-> property
-> value and unit
-> baseline or comparison relation
-> author interpretation where available
-> evidence anchor
```

Evidence units should keep traceback to document, section, table, row, cell,
quote, and page or bounding box where available.

The objective field should be provenance and organization context. It should
not replace material, sample, process, property, condition, baseline, or
evidence identity.

### Evidence Resolution, Logic Chain, And Finding Synthesis

Core should resolve fragments before presenting them as the objective answer.
Resolution includes joining preparation and result tables, binding text
interpretations to measured results, and keeping source traceback for every
resolved claim.

The objective logic chain preserves the ordered evidence-unit inventory,
measurement ranges, source documents, and context needed for downstream
reasoning. It does not by itself upgrade paper-local observations into a
cross-paper conclusion.

After all candidate papers have been traversed, Core performs one goal-level
Finding synthesis over evidence units grouped by document. That pass directly
decides whether cited direct results show agreement, conflict, a
condition-dependent relationship, or insufficient confirmation. Core must not
create paper Findings and then cluster them by normalized fields.

### Objective-Scoped Comparison

Comparison assembly should project rows from resolved evidence units and group
them by objective first, then by property, material facet, process axis,
condition, and baseline.

The same paper can contribute to multiple objectives, but each contribution
must preserve the objective-specific route and evidence.

## Backend API Cutover

The public backend API should move from material routes to research-objective
routes.

The landed first read routes use the `/objectives` collection family documented
in the backend API spec:

```text
GET /api/v1/collections/{collection_id}/objectives
GET /api/v1/collections/{collection_id}/objectives/{objective_id}/research-view
```

Future objective-scoped comparison and evidence routes should stay in that
objective route family unless the API spec explicitly renames the resource.
Research-understanding data is returned from `research-view`; old report routes
are retired and should not be reintroduced as a parallel Markdown answer path.
The intended follow-up surfaces are:

```text
GET /api/v1/collections/{collection_id}/objectives/{objective_id}/comparison-rows
GET /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence
```

Material-first routes should be removed from the primary product contract after
the cutover:

```text
GET /api/v1/collections/{collection_id}/materials
GET /api/v1/collections/{collection_id}/materials/{material_id}/research-view
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
- paper-level and cross-paper research logic chain
- comparison matrix
- evidence cards and source traceback
- routed tables and skipped-table reasons when useful for debugging
- objective report

Material should remain visible as filters, chips, and facets inside objective
views, not as the route owner.

## Implementation Sequence

1. Extend Core domain records, `CoreFactSet`, and `CoreFactRepository` for
   paper skims and research objectives.
2. Add SQLite persistence tables and repository methods for objective records.
3. Add Core objective schemas, prompts, and extractor methods.
4. Add `research_objective_service.py` for paper skim and objective discovery.
5. Add objective-paper framing, routing, and objective-scoped evidence-unit
   extraction under the Core semantic-build owner.
6. Add objective-aware table routing, table schema understanding, and
   whole-table extraction for relevant tables.
7. Add evidence resolution and research logic-chain assembly from routed text,
   table, and figure evidence.
8. Add objective-scoped controlled-comparison projections over resolved
   evidence units and logic chains.
9. Retire collection-wide `ComparisonRowRecord` usage from graph, material,
   research-view, workspace, and report semantics instead of keeping it as a
   compatibility path.
10. Bump Core semantic version to an objective-facts generation, such as
   `objective_facts_v1`.
11. Add backend `/objectives/*` routes and tests.
12. Replace frontend material workspace navigation with objective workspace
   navigation.
13. Remove material-first route usage from frontend clients.
14. Remove or disable material-first backend paths once objective-first routes
    pass contract tests.

## Verification

The cutover should be verified at three levels.

Backend semantic tests should prove:

- one collection can produce multiple research objectives
- one paper can contribute differently to multiple objectives
- objective-local context does not leak across objectives
- objective-guided extraction still emits normalized reusable material facts
- table routing uses objective context before fact extraction
- table routing resolves paper-local join keys into real sample or
  experimental conditions before logic-chain assembly
- composition, modeling, literature comparison, and fitting-only tables do not
  produce current-work measurements for unrelated objectives
- objective facts keep evidence anchors
- paper-level and cross-paper logic chains preserve evidence traceback

Backend API tests should prove:

- `/objectives` returns stable objective summaries
- objective detail, controlled comparisons, evidence, and report routes are
  collection-scoped and do not depend on collection-wide comparison rows
- removed or retired material routes are not still treated as the primary
  contract

Frontend tests should prove:

- the collection workspace opens on objective navigation
- objective cards and detail pages render from the new routes
- controlled-comparison and evidence drilldown still preserve source traceback
- material appears as a facet, not as the top-level route owner

## Acceptance Criteria

The cutover is complete when:

- the collection workspace is research-objective-first
- material-first pages are no longer the main product entry
- Core extraction produces objective-scoped facts, controlled comparisons, and
  logic chains from resolved evidence units
- Core preserves resolved evidence units in the objective logic chain and
  directly synthesizes goal-level Findings across their per-paper provenance
- graph, material, research-view, workspace, and report surfaces no longer use
  collection-wide `ComparisonRowRecord` as their semantic source
- Core facts still normalize into a reusable material fact substrate
- objective routes are the public backend contract
- frontend calls objective routes rather than material routes
- evidence traceability remains available for every surfaced result
- irrelevant tables and paper-local row labels no longer pollute controlled
  comparisons or test-condition graph nodes merely because they share a
  material label
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
