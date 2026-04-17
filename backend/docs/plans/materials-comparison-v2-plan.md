# Materials Comparison V2 Plan

## Summary

This document records the backend-local implementation plan for upgrading the
current claim-centric comparison backbone into a sample- and measurement-centric
materials comparison backbone.

The goal is not to replace the five-layer architecture.

The goal is to use the architecture that already exists:

- Goal defines what the user wants to study
- Source normalizes observable evidence from documents
- Core remains the only producer of research facts
- comparison, graph, and reports continue to consume Core outputs

This plan therefore focuses on one narrow backend question:

how to expand the Source evidence surface and the Core comparison backbone so
materials papers can be compared as sample groups, variable axes, baselines,
test conditions, and results rather than only as isolated claim sentences.

The revised direction in this page assumes one additional materials-specific
rule:

materials comparison is not only a `sample -> result` problem.

It is a `sample -> structure/characterization -> condition -> result ->
baseline -> comparability support` problem.

Read this plan after:

- [`../architecture/goal-core-source-layering.md`](../architecture/goal-core-source-layering.md)
- [`source-collection-builder-normalization-plan.md`](source-collection-builder-normalization-plan.md)
- [`born-digital-source-parser-first-plan.md`](born-digital-source-parser-first-plan.md)

## Status

Status as of 2026-04-17:

- planned
- not started in code
- intended as the next Core-and-Source expansion wave after Source/GraphRAG
  runtime shrink

## Problem

The current backend can already produce:

- `documents.parquet`
- `text_units.parquet`
- `document_profiles.parquet`
- `evidence_cards.parquet`
- `comparison_rows.parquet`

That is enough for a narrow evidence-first backbone, but it is still too thin
for typical materials research comparison work.

Today the comparison layer is still mostly built from:

- one document
- a small number of section-derived or sentence-derived evidence cards
- one normalized comparison row per eligible evidence card

That works for:

- document type judgment
- protocol suitability gating
- basic property/process/characterization evidence
- narrow comparability warnings

It does not yet work well for:

- multiple sample variants in one paper
- variable sweeps such as `0 wt% / 1 wt% / 3 wt%`
- table-centric result extraction
- baseline type discrimination
- condition-rich measurement comparison
- sample-level result grouping across one document
- structure-processing-property linkage
- characterization evidence as a first-class research object
- non-scalar results such as retention, trends, fitted values, and curve points

The main materials-specific gaps are:

- the sample model is still too thin and risks treating `1 wt%` or similar
  labels as standalone objects instead of as variants of a host material system
- structure and morphology evidence is not yet modeled as part of the Core
  backbone
- test conditions are too weak if they remain only flat normalized strings
- baseline semantics are under-specified for materials papers
- comparability risks being over-automated if it is represented only as a hard
  rule outcome rather than as decision support

## Scope

This plan covers:

- expanding the Source handoff beyond only documents and text units
- introducing Source-owned `sections`, `table_cells`, and
  `figure_captions` artifacts
- introducing Core-owned `sample_variants`, `characterization_observations`,
  `structure_features`, `test_conditions`, `baseline_references`, and
  `measurement_results`
- adding a materials-specific ontology and normalization layer for variable
  axes, characterization types, structure feature categories, result types,
  baseline types, and test-condition templates
- rebuilding `comparison_rows` from sample/result objects rather than directly
  from individual claim cards
- updating graph and report projections to consume the stronger comparison
  backbone after cutover

This plan does not cover:

- redesign of Goal Brief or Goal Consumer
- image-native chart understanding
- OCR engine replacement
- frontend IA redesign
- protocol redesign beyond consuming the stronger Core backbone
- long-lived compatibility paths for old comparison semantics
- expert-level scientific judgment replacement; comparability remains decision
  support rather than a final scientific ruling

## Architecture Rules

- keep Source responsible for observable document evidence, not research
  judgment
- keep Core responsible for sample, structure, characterization, measurement,
  baseline, and comparability semantics
- do not let Source emit final `comparison_rows` directly
- do not introduce `/comparisons-v2` or other long-lived parallel product
  surfaces
- cut the existing `/comparisons` surface over once the new backbone is stable
- keep graph and reports downstream of Core rather than letting them redefine
  research facts
- treat sample variants as multi-part objects, not only as labels
- treat characterization evidence as first-class Core input, not as a loose
  note attached to performance results
- represent test conditions and baseline references as structured objects before
  they are flattened into comparison-facing summaries
- represent comparability as an evidence-backed assessment with review flags,
  not as an unqualified automated verdict

## Target Contracts

### Materials Ontology And Normalization Layer

Before the Core artifact set grows, the backend should freeze a minimal
materials-specific normalization layer.

This is not a new product surface.

It is the domain schema that prevents `sample_variants`,
`characterization_observations`, `measurement_results`, and
`comparison_rows` from turning into free-form text buckets.

The minimum normalization families are:

- `material_family_type`
- `variable_axis_type`
- `property_type`
- `characterization_type`
- `structure_feature_type`
- `baseline_type`
- `result_type`
- `test_condition_template_type`

The first implementation may be a direct taxonomy module or direct constants in
the owning Core packages.

It should not become a new service layer.

Wave A must keep this ontology intentionally narrow.

Phase 1 should support only one or two concrete subdomain templates rather than
attempting a full materials-wide ontology.

Recommended initial scope in this repository:

- `mechanics`
- `electrochemistry`

If product priority changes before implementation starts, these two templates
may be replaced, but Wave A should still freeze no more than two initial
subdomain templates.

All other subdomains should explicitly remain `unresolved` or unsupported in
phase 1 rather than being partially modeled.

### Core Epistemic Status

Every Core object that is not purely a Source-observed artifact should carry an
explicit epistemic state so users and downstream consumers can distinguish
between what the paper directly states and what the system normalized or
inferred.

The shared status vocabulary should begin with:

- `directly_observed`
- `normalized_from_evidence`
- `inferred_from_characterization`
- `inferred_with_low_confidence`
- `unresolved`

At minimum, the following Core objects must carry this field:

- `sample_variants`
- `characterization_observations`
- `structure_features`
- `test_conditions`
- `baseline_references`
- `measurement_results`
- comparison assessment payloads

The goal is not to make every object uncertain.

The goal is to prevent the system from presenting normalized or inferred
objects as if they had been stated directly in the source paper.

### Source Evidence Surface

The Source layer should emit the following collection-local artifacts:

- `documents.parquet`
- `text_units.parquet`
- `sections.parquet`
- `table_cells.parquet`
- `figure_captions.parquet`

The first two already exist.

The new Source artifacts should expose observable evidence only.

#### `sections.parquet`

Minimum intended columns:

- `section_id`
- `document_id`
- `title`
- `section_type`
- `heading`
- `text`
- `text_unit_ids`
- `page`
- `char_range`
- `confidence`
- `section_role_hint`

#### `table_cells.parquet`

Minimum intended columns:

- `cell_id`
- `document_id`
- `table_id`
- `row_index`
- `col_index`
- `cell_text`
- `row_header_path`
- `column_header_path`
- `cell_role`
- `table_caption`
- `page`
- `bbox`
- `char_range`
- `unit_hint`

The table contract must be rich enough to support:

- sample group identification
- variable axis detection
- baseline row or column detection
- condition extraction from caption or header context

#### `figure_captions.parquet`

This plan still does not require image-native chart understanding.

It does require figure-caption evidence because many materials papers express
structure and characterization meaning in captions even when pixel-level parsing
is deferred.

Minimum intended columns:

- `figure_id`
- `document_id`
- `caption_text`
- `figure_type_hint`
- `page`
- `bbox`
- `char_range`

### Core Research Objects

The Core layer should own these new research objects:

- `sample_variants.parquet`
- `characterization_observations.parquet`
- `structure_features.parquet`
- `test_conditions.parquet`
- `baseline_references.parquet`
- `measurement_results.parquet`
- upgraded `comparison_rows.parquet`

#### `sample_variants.parquet`

Minimum intended columns:

- `variant_id`
- `document_id`
- `collection_id`
- `variant_label`
- `host_material_system`
- `composition`
- `variable_axis_type`
- `variable_value`
- `synthesis_context`
- `post_treatment_context`
- `structure_feature_ids`
- `source_anchor_ids`
- `confidence`
- `epistemic_status`

The sample object must remain anchored to the host material system and variant
definition. A label such as `1 wt%` is not sufficient on its own.

#### `characterization_observations.parquet`

Minimum intended columns:

- `observation_id`
- `document_id`
- `collection_id`
- `variant_id`
- `characterization_type`
- `observation_text`
- `observed_value`
- `observed_unit`
- `condition_context`
- `evidence_anchor_ids`
- `confidence`
- `epistemic_status`

This artifact exists so the system can represent characterization evidence as a
research object rather than as incidental prose.

#### `structure_features.parquet`

Minimum intended columns:

- `feature_id`
- `document_id`
- `collection_id`
- `variant_id`
- `feature_type`
- `feature_value`
- `feature_unit`
- `qualitative_descriptor`
- `source_observation_ids`
- `confidence`
- `epistemic_status`

The first pass should support at least these feature categories:

- phase
- morphology
- grain_size
- thickness
- surface_area

The first pass should stay narrow.

The following feature categories should be explicitly deferred until later
waves unless a very narrow, high-confidence extraction path already exists:

- porosity
- interface
- oxidation_state
- defect_state

#### `test_conditions.parquet`

Minimum intended columns:

- `test_condition_id`
- `document_id`
- `collection_id`
- `property_type`
- `template_type`
- `scope_level`
- `condition_payload`
- `condition_completeness`
- `missing_fields`
- `evidence_anchor_ids`
- `confidence`
- `epistemic_status`

`condition_payload` is intentionally structured rather than flattened because
materials comparability depends on different fields in different subdomains.

The scope levels should begin with:

- `experiment`
- `table`
- `measurement`

Cardinality rules for results and conditions:

- one `measurement_result` may reference at most one resolved
  `test_condition_id`
- many `measurement_results` may share the same `test_condition_id`
- when multiple candidate conditions exist and the correct one cannot be
  resolved confidently, `test_condition_id` should remain empty and the result
  should carry unresolved condition context in its uncertainty payload rather
  than being force-normalized
- incomplete conditions should be represented through sparse payloads plus
  completeness and missing-field metadata, not by manufacturing a fake complete
  condition object

The condition template types should start narrow and explicit, for example:

- electrochemistry
- catalysis
- thin_film_device
- mechanics
- thermal
- optical

#### `baseline_references.parquet`

Minimum intended columns:

- `baseline_id`
- `document_id`
- `collection_id`
- `variant_id`
- `baseline_type`
- `baseline_label`
- `baseline_scope`
- `evidence_anchor_ids`
- `confidence`
- `epistemic_status`

The baseline taxonomy should at least distinguish:

- pristine_or_undoped
- same_process_without_additive
- commercial_benchmark
- literature_benchmark
- blank_or_substrate_control
- best_prior_art
- implicit_within_document_control

#### `measurement_results.parquet`

Minimum intended columns:

- `result_id`
- `document_id`
- `collection_id`
- `variant_id`
- `property_normalized`
- `result_type`
- `value_payload`
- `unit`
- `test_condition_id`
- `baseline_id`
- `structure_feature_ids`
- `characterization_observation_ids`
- `evidence_anchor_ids`
- `traceability_status`
- `result_source_type`
- `epistemic_status`

`value_payload` exists because materials results are not always single scalar
values.

The first result types should at least cover:

- scalar
- range
- retention
- curve_point
- fitted_value
- trend
- optimum

#### Comparability Semantics

`comparison_rows.parquet` should continue to expose `comparability_status`, but
that field must be treated as an assessment, not a scientific final answer.

The upgraded comparison contract should therefore also carry:

- `requires_expert_review`
- `comparability_basis`
- `missing_critical_context`
- `assessment_epistemic_status`

#### Upgraded `comparison_rows.parquet`

The existing comparison artifact should be upgraded rather than duplicated.

Minimum intended additions over the current row contract:

- `variant_id`
- `variant_label`
- `variable_axis`
- `variable_value`
- `baseline_reference`
- `result_source_type`
- `requires_expert_review`
- `comparability_basis`
- `missing_critical_context`
- `assessment_epistemic_status`

Existing useful fields should remain:

- `property_normalized`
- `test_condition_normalized`
- `comparability_status`
- `comparability_warnings`
- `value`
- `unit`

### Comparison Consumer Contract

The comparison route should keep the same endpoint path, but the consuming
contract should clearly separate four different things:

- display fields shown to the user
- evidence bundle that supports the row
- system assessment
- unresolved or missing context

That means the route response model should evolve toward a structure like:

- `display`
- `evidence_bundle`
- `assessment`
- `uncertainty`

The purpose of this separation is to prevent a comparison row from being read
as if it were already the final scientific conclusion.

The minimum logical split is:

- `display`
  - sample label
  - variable axis and value
  - property
  - summarized result
  - summarized test condition
- `evidence_bundle`
  - evidence IDs
  - anchor IDs
  - related characterization observations
  - related structure features
- `assessment`
  - comparability status
  - comparability basis
  - requires expert review
  - assessment epistemic status
- `uncertainty`
  - missing critical context
  - unresolved fields
  - unresolved baseline or condition links

## Execution Waves

### Wave A: Freeze Materials V2 Contracts And Ontology

Goal:

- make the expanded Source and Core artifact contracts explicit before any new
  parser logic is added
- freeze the materials-specific ontology families that later waves will use

Primary changes:

- add Source artifact column definitions to
  `backend/retrieval/data_model/schemas.py`
- extend collection artifact path resolution in
  `backend/application/documents/input_service.py`
- add or record the normalization families for:
  - variable axes
  - characterization types
  - structure feature types
  - baseline types
  - result types
  - test condition template types
- freeze the phase-1 subdomain scope to no more than two concrete templates
- record the upgraded comparison contract in
  `backend/controllers/schemas/comparisons.py`
- keep this wave documentation-first and contract-first

Files expected to change:

- `backend/retrieval/data_model/schemas.py`
- `backend/application/documents/input_service.py`
- `backend/controllers/schemas/comparisons.py`
- this plan page

Exit criteria:

- new artifact names and minimum fields are frozen
- the materials-specific normalization families are frozen
- the phase-1 subdomain scope is frozen and intentionally narrow
- later implementation waves no longer need to redefine what Source hands off
- controller schema direction is clear even if runtime cutover has not yet
  happened

### Wave B: Expand Source Evidence Surface

Goal:

- make the default Source indexing pipeline produce richer observable evidence
  while still staying Source-only

Primary changes:

- extend default pipeline registration in
  `backend/retrieval/index/workflows/factory.py`
- add `create_sections.py`
- add `create_table_cells.py`
- add `create_figure_captions.py`
- persist `sections.parquet`
- persist `table_cells.parquet`
- persist `figure_captions.parquet`
- update `application/documents/section_service.py` to prefer Source-produced
  sections instead of local-only heuristics

Files expected to change:

- `backend/retrieval/index/workflows/factory.py`
- `backend/retrieval/index/workflows/create_sections.py`
- `backend/retrieval/index/workflows/create_table_cells.py`
- `backend/retrieval/index/workflows/create_figure_captions.py`
- `backend/application/documents/section_service.py`
- `backend/tests/unit/services/test_source_handoff_contracts.py`
- `backend/tests/integration/test_processing_pipeline.py`

Design rules:

- keep page, bbox, or char-range locator data whenever available
- keep Source output descriptive, not interpretive
- do not let these workflows emit sample-level or comparison-level semantics

Exit criteria:

- the default indexing pipeline emits `sections.parquet`
- the default indexing pipeline emits `table_cells.parquet`
- the default indexing pipeline emits `figure_captions.parquet`
- every section, table cell, or figure caption record can trace back to a
  document locator

### Wave C: Build Characterization And Structure Bridge Objects

Goal:

- introduce structure and characterization as first-class Core objects so the
  system does not collapse into a performance-table extractor

Primary changes:

- extend `application/evidence/service.py` to build:
  - `characterization_observations.parquet`
  - `structure_features.parquet`
  - `test_conditions.parquet`
  - `baseline_references.parquet`
- assemble characterization observations from sections, tables, and figure
  captions
- derive structure features from characterization observations with explicit
  confidence and provenance
- normalize test conditions into template-shaped payloads rather than strings
- normalize baseline references into explicit baseline taxonomy buckets
- add epistemic-status assignment rules for each derived Core object

Files expected to change:

- `backend/application/evidence/service.py`
- `backend/application/workspace/artifact_registry_service.py`
- `backend/tests/unit/services/test_evidence_backbone_services.py`

Fixture requirements:

- include at least one materials-paper fixture with characterization evidence
  that matters to result interpretation
- cover at least one phase or morphology statement
- cover at least one structured condition template
- cover at least one explicit and one implicit baseline form

Exit criteria:

- characterization evidence survives as a distinct artifact
- structure features can be traced back to characterization observations
- test conditions are stored as structured payloads
- baseline references use explicit baseline taxonomy values
- epistemic-status fields are populated for derived Core artifacts

### Wave D: Build Sample-Centric Measurement Objects

Goal:

- promote materials comparison from claim-centric evidence cards to
  sample-centric measurement objects

Primary changes:

- extend `application/evidence/service.py` further to build:
  - `sample_variants.parquet`
  - `measurement_results.parquet`
- keep `application/documents/service.py` focused on document profiling and
  protocol suitability only
- assemble sample variants from text sections and table evidence
- assemble measurement results from table cells and supporting textual context
- link each result to:
  - sample variants
  - test conditions
  - baseline references
  - relevant structure features when available
- make result-to-condition linkage obey the one-result-to-zero-or-one-resolved-
  condition rule

Files expected to change:

- `backend/application/evidence/service.py`
- `backend/application/documents/service.py`
- `backend/application/workspace/artifact_registry_service.py`
- `backend/tests/unit/services/test_evidence_backbone_services.py`

Fixture requirements:

- include at least one materials-paper fixture with multiple sample groups
- cover a variable sweep such as `0 wt% / 1 wt% / 3 wt%`
- cover at least one explicit baseline sample
- cover at least one table-derived property result
- cover at least one non-scalar result shape such as retention or fitted value

Exit criteria:

- one document with multiple sample groups produces multiple variants
- property results attach to the correct variant
- result types are not limited to one scalar value representation
- traceability survives from sample/result objects back to Source anchors
- unresolved conditions remain explicitly unresolved instead of being forced
  into flat normalized strings

### Wave E: Rebuild Comparison Rows From Samples And Results

Goal:

- make `comparison_rows.parquet` a sample/result-backed artifact rather than a
  direct evidence-card projection

Primary changes:

- rewrite `backend/application/comparisons/service.py` to consume
  `sample_variants.parquet` and `measurement_results.parquet`
- keep the existing `/collections/{collection_id}/comparisons` route and cut
  it over in place
- split the consumer-facing comparison payload into display, evidence bundle,
  assessment, and uncertainty zones
- update task orchestration so the Core order becomes:
  `document_profiles -> evidence_cards -> sample_variants/measurement_results -> comparison_rows -> protocol branch`

Files expected to change:

- `backend/application/comparisons/service.py`
- `backend/application/indexing/index_task_runner.py`
- `backend/controllers/schemas/comparisons.py`
- `backend/controllers/comparisons.py`
- `backend/tests/unit/services/test_evidence_backbone_services.py`
- `backend/tests/integration/test_app_layer_api.py`

Cutover rules:

- do not add `/comparisons-v2`
- do not keep long-lived dual logic inside comparison generation
- remove the old direct evidence-card-to-row path in the same task when the new
  path is proven
- keep `comparability_status` but pair it with review flags and basis fields
- do not represent comparability as a final scientific ruling when condition or
  baseline context is incomplete

Exit criteria:

- `/comparisons` returns sample-level rows
- one document may contribute multiple rows for multiple variants
- comparison rows expose structured uncertainty and review needs
- the route response no longer conflates the display object with the assessment
  object
- current consumers do not depend on the old claim-row assumption

### Wave F: Align Downstream Core Consumers

Goal:

- ensure graph and reports consume the stronger comparison backbone without
  inventing their own semantics

Primary changes:

- update `backend/application/graph/core_projection_service.py`
- update `backend/application/reports/service.py`
- preserve Core-first downstream consumption

Files expected to change:

- `backend/application/graph/core_projection_service.py`
- `backend/application/reports/service.py`
- downstream tests for graph and report projections

Exit criteria:

- graph nodes and edges reflect sample/result-backed comparison rows
- reports summarize the stronger comparison backbone without reverting to
  GraphRAG-era semantics

## Recommended Order

Run the waves in this order:

1. Wave A
2. Wave B
3. Wave C
4. Wave D
5. Wave E
6. Wave F

The most important sequencing rule is:

do not start changing Core sample/result logic before the Source evidence
surface is explicit and stable enough to support it.

## Verification Plan

Minimum verification expected across the plan:

- unit tests for Source handoff artifacts and column normalization
- integration tests proving default indexing emits new artifacts
- unit tests for characterization observation extraction
- unit tests for structure-feature derivation
- unit tests for structured test-condition normalization
- unit tests for baseline taxonomy classification
- unit tests for sample-variant assembly
- unit tests for measurement-result extraction from table-centric fixtures
- unit tests for non-scalar result types
- unit tests for epistemic-status propagation on derived Core objects
- unit tests for result-to-condition cardinality and unresolved-condition
  handling
- integration tests proving `/comparisons` returns upgraded rows after cutover
- graph/report tests proving downstream Core consumers still function

## Risks

Main risks:

- Source may overfit to one PDF layout if table extraction is too parser-specific
- Core may start depending on weak Source guesses instead of explicit evidence
- comparison contract growth may exceed what current frontend consumers expect
- section heuristics may conflict with future born-digital parser improvements
- structure-feature inference may overclaim more certainty than the underlying
  characterization evidence supports
- comparability outputs may be misread as expert-equivalent scientific judgment
- ontology scope may sprawl too early and block actual backbone delivery

Mitigations:

- keep Source outputs observable and locator-backed
- keep Core as the only layer that assigns sample/result semantics
- keep characterization and structure evidence explicit rather than burying it
  inside result summaries
- add fixture coverage with multi-variant materials tables early
- add fixtures where property comparison depends on condition or structure
  differences
- cut the route contract only after one full end-to-end fixture passes
- expose review flags whenever critical context is missing
- keep phase-1 ontology limited to one or two concrete subdomain templates

## Applicability And Limits

This backbone is expected to fit best for:

- battery-material result comparison
- catalysis and electrocatalysis variable sweeps
- sensor or optoelectronic device result tables
- doping, composition, and annealing comparison papers

It is expected to remain weaker for:

- image-dominant microstructure interpretation
- spectrum-heavy mechanism papers
- phase-diagram-driven work
- fracture or in-situ evolution studies

Those weaker cases are not excluded from the system, but they should be treated
as future expansion areas rather than silently over-claimed as fully solved.

## Follow-up Relationship

This plan should lead directly to:

- contract freeze work in the Core and Source handoff
- Source parser expansion for section, table, and figure-caption evidence
- structure/characterization bridge artifacts inside Core
- sample/result-backed comparison cutover on the existing collection APIs

If Source parser replacement or OCR engine replacement is revisited later, that
work should plug into the Source evidence surface defined here rather than
changing Core comparison semantics directly.
