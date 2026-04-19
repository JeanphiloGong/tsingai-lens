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

- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
- [`source-collection-builder-normalization-plan.md`](../source/source-collection-builder-normalization-plan.md)
- [`born-digital-source-parser-first-plan.md`](../source/born-digital-source-parser-first-plan.md)

## Status

Status as of 2026-04-18:

- Wave A contract freeze is complete in code
- Wave B Source evidence runtime is complete in code
- Wave C characterization, structure, test-condition, and baseline artifacts
  are complete in code
- Wave D sample-variant and measurement-result artifacts are complete in code
- Wave E comparison-row cutover to the sample/result backbone is complete in
  code
- Wave F does not currently require a separate backend migration wave; graph
  and report consumers continue to pass on the stronger comparison backbone
- the primary backend-local rollout recorded in this plan is complete; the
  remaining work is follow-up verification, parser quality improvement, and
  consumer adoption rather than unfinished backbone construction

## Implementation Outcome

As implemented in the backend runtime, this plan now yields:

- Source-owned persisted handoff artifacts for `sections.parquet` and
  `table_cells.parquet`, which are consumed directly by documents and evidence
  flows rather than being rebuilt at read time
- Core-owned `characterization_observations.parquet`,
  `structure_features.parquet`, `test_conditions.parquet`, and
  `baseline_references.parquet`
- Core-owned `sample_variants.parquet` and `measurement_results.parquet`
- `comparison_rows.parquet` rebuilt from sample/result objects rather than from
  direct evidence-card projection
- `/collections/{collection_id}/comparisons` cut over in place to consume the
  stronger Core backbone and expose separate `display`, `evidence_bundle`,
  `assessment`, and `uncertainty` zones
- downstream graph and report projections continuing to consume Core-derived
  comparison rows without reverting to legacy GraphRAG-era semantics

The implemented Core order is now:

- `document_profiles -> evidence_cards -> sample_variants /
  measurement_results -> comparison_rows -> protocol branch`

No long-lived compatibility path remains from direct evidence-card projection
to `comparison_rows.parquet`.

## Reference Corpus Fit

The current client-provided papers under `backend/data/test_file/` are not a
generic materials corpus.

They are strongly concentrated around:

- metal additive manufacturing
- field-assisted or hybrid additive manufacturing
- in-situ heating and thermal-history control
- microstructure evolution
- residual stress control
- mechanical-property and fatigue outcomes

The strongest recurring patterns in the current reference set are:

- Ti-alloy directed energy deposition with induction-assisted or hybrid process
  control
- LPBF or SLM with in-situ heating strategies for residual-stress reduction and
  process stabilization
- review papers on field-assisted metal additive manufacturing, in-situ heat
  treatment, and powder-bed-fusion process families

That means phase 1 should not start from a broad all-materials comparison
template.

It should start with a default enabled profile that matches the real papers
already in hand.

That default profile does not define the whole system ontology.

It only defines which profile is optimized first, which fixtures are used
first, and which extraction paths are hardened first.

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

- keeping the Core backbone generic enough to support multiple materials-domain
  profiles
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

This plan treats domain profiles as pluggable specializations layered on top of
the generic backbone.

The current reference corpus only sets phase-1 priority. It does not lock the
system to metal additive manufacturing forever.

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

### Core-Neutral Backbone And Domain Profiles

This plan distinguishes two layers:

- a Core-neutral backbone contract
- profile-specific ontology and normalization overlays

The Core-neutral backbone owns:

- `sample_variants`
- `characterization_observations`
- `structure_features`
- `test_conditions`
- `baseline_references`
- `measurement_results`
- `comparison_rows`
- `evidence_bundle / assessment / uncertainty`

Domain profiles define how those objects are specialized for one subdomain.

Examples of future profiles include:

- `metal_additive_manufacturing`
- `electrochemistry`
- `catalysis`
- `thin_film_device`
- `general_mechanics`

The current client corpus only justifies enabling one profile by default in
phase 1. It should not be treated as the only supported long-term direction.

### Materials Ontology And Normalization Layer

Before the Core artifact set grows, the backend should freeze a minimal
materials-specific normalization layer.

This is not a new product surface.

It is the domain schema that prevents `sample_variants`,
`characterization_observations`, `measurement_results`, and
`comparison_rows` from turning into free-form text buckets.

The minimum Core-neutral normalization families are:

- `material_family_type`
- `process_family_type`
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

- default enabled profile: `metal_additive_manufacturing`

Within that phase-1 default profile, the first two scenario templates
should be:

- `ded_field_assisted_ti_alloy`
- `lpbf_in_situ_heating_stress_control`

If product priority changes before implementation starts, these two templates
may be replaced, but Wave A should still freeze no more than one default
enabled profile and two initial scenario templates.

All other profiles should explicitly remain available-but-not-enabled in phase 1
rather than being partially modeled.

Each enabled profile may register narrower profile-specific vocabularies on top
of the Core-neutral families.

For the current reference corpus, the phase-1 default profile should register
metal-additive-manufacturing specializations such as:

Examples of profile-specific extensions:

- `alloy_system_type`
  - `ti_6al_4v`
  - `316l`
  - `al_cu`
- `process_route_type`
  - `lpbf`
  - `slm`
  - `ded`
  - `laser_deposition`
  - `eb_pbf`
  - `hybrid_wire_arc_laser`
- `auxiliary_field_type`
  - `induction_heating`
  - `surface_layer_heating`
  - `multi_beam_strategy`
  - `intrinsic_heat_treatment`
  - `hybrid_energy_input`
- `property_type`
  - `yield_strength`
  - `ultimate_tensile_strength`
  - `elongation`
  - `hardness`
  - `fatigue_life`
  - `residual_stress`
- `characterization_type`
  - `sem`
  - `xrd`
  - `neutron_diffraction`
  - `contour_method`
  - `microhardness_map`
- `variable_axis_type`
  - `laser_power`
  - `scan_strategy`
  - `induction_current`
  - `surface_heating_interval`
  - `beam_strategy`
  - `layer_interval`

Those examples belong to the phase-1 default profile. They are not mandatory
global vocabularies for every future profile.

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
- `domain_profile`
- `variant_label`
- `host_material_system`
- `composition`
- `variable_axis_type`
- `variable_value`
- `process_context`
- `profile_payload`
- `structure_feature_ids`
- `source_anchor_ids`
- `confidence`
- `epistemic_status`

The sample object must remain anchored to the host material system and variant
definition. A label such as `1 wt%` is not sufficient on its own.

`profile_payload` is where one enabled profile may keep extra normalized fields
that are not required by the Core-neutral backbone.

For the current reference corpus, a phase-1 sample variant will often be a
process variant rather than a composition-only variant.

Examples include:

- same alloy with different induction current
- same LPBF alloy with or without in-situ surface heating
- same alloy with different multi-beam strategy
- same DED alloy under different laser-induction parameter combinations

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

For the metal-AM phase-1 corpus, the first pass should explicitly prioritize:

- prior-β grain size or morphology when available
- α-lath size when available
- columnar versus equiaxed morphology
- melt-pool-related morphology cues

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
- `domain_profile`
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

- tensile_mechanics
- fatigue
- residual_stress_measurement
- microhardness

The current reference corpus does not justify starting from electrochemistry or
thin-film-device condition templates.

The first phase should optimize the default metal-AM profile for conditions such
as:

- loading mode
- specimen orientation
- build direction
- stress measurement method
- layer interval of in-situ heating
- auxiliary heating schedule
- post-heat-treatment presence or absence

#### `baseline_references.parquet`

Minimum intended columns:

- `baseline_id`
- `document_id`
- `collection_id`
- `domain_profile`
- `variant_id`
- `baseline_type`
- `baseline_label`
- `baseline_scope`
- `evidence_anchor_ids`
- `confidence`
- `epistemic_status`

The baseline taxonomy should at least distinguish:

- as_built_reference
- same_process_without_auxiliary_field
- post_heat_treated_reference
- literature_benchmark
- conventional_process_reference
- implicit_within_document_control

These are phase-1 default-profile examples, not universal baseline categories
for every future materials profile.

#### `measurement_results.parquet`

Minimum intended columns:

- `result_id`
- `document_id`
- `collection_id`
- `domain_profile`
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

For the current reference corpus, the phase-1 default profile should explicitly
support these result families first:

- tensile strength and yield strength
- elongation
- hardness
- residual stress magnitude
- fatigue life or damage-tolerance metrics

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

The wave definitions below remain as delivery lineage.

As of 2026-04-18, Waves A through E are complete in code, and Wave F is
currently satisfied by downstream regression passing on the stronger
comparison backbone.

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
- freeze the Core-neutral backbone contract
- freeze the phase-1 default enabled profile as
  `metal_additive_manufacturing`
- freeze the phase-1 scenario scope to no more than two concrete templates
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
- the Core-neutral normalization families are frozen
- the phase-1 default profile is frozen around the current metal-AM corpus
- the phase-1 scenario scope is frozen and intentionally narrow
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
- preserve process-parameter tables and method-section evidence because the
  phase-1 default corpus expresses many variants through laser power, induction
  current, heating mode, and beam strategy rather than through composition
  labels

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
- for phase 1, prefer fixtures taken from or shaped after the current metal-AM
  corpus rather than synthetic generic materials examples

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

For the current default profile, this wave should also cover process-centric sample
variants such as:

- induction current sweep
- with versus without in-situ heating
- beam-strategy variants
- laser-parameter combinations

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

Current implementation status against this verification plan:

- backend unit and integration tests now cover Source handoff persistence,
  Wave C Core artifacts, Wave D sample/result artifacts, Wave E comparison
  cutover, and downstream graph/report consumers
- the remaining notable verification gap is environment-dependent route and
  app-layer execution where `fastapi` is not installed in the current runtime;
  those checks belong to follow-up validation rather than unfinished backbone
  implementation

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

## Remaining Follow-Up After This Plan

The following items are still worth doing, but they are not unfinished core
rollout waves in this plan:

- run the `fastapi`-dependent router and app-layer tests in an environment that
  has the API stack installed
- update any frontend or external consumer that still assumes the old flat
  `/comparisons` response shape rather than the implemented
  `display/evidence_bundle/assessment/uncertainty` structure
- continue Source parser quality and extraction-depth work in the dedicated
  follow-up plans rather than reopening this backbone rollout plan:
  `source-parser-evaluation-plan.md` and
  `born-digital-source-parser-first-plan.md`
- continue domain-depth quality work, such as richer structure features,
  stronger non-scalar result handling, and profile-specific extraction
  refinement, as follow-up quality waves rather than as remaining cutover work

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
- the phase-1 design may drift back into generic materials schemas that do not
  match the actual metal-AM reference papers

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
- keep phase-1 enablement limited to one default profile and two concrete
  scenario templates
- use the client-provided metal-AM papers as phase-1 fixtures, not as the
  system-wide ontology boundary

## Current Phase-1 Fit

The generic backbone is intended to remain extendable beyond one domain.

The current phase-1 default profile is expected to fit best for:

- field-assisted or hybrid metal additive manufacturing
- Ti-alloy DED and laser-deposition process comparison
- LPBF or SLM residual-stress and mechanics studies
- in-situ heating and thermal-history control papers
- metal-AM review corpora organized around process, microstructure, and
  mechanical outcomes

It is expected to remain weaker for:

- image-dominant microstructure interpretation
- spectrum-heavy mechanism papers
- phase-diagram-driven work
- fracture or in-situ evolution studies
- non-metal materials domains such as electrochemistry or photocatalysis before
  dedicated domain profiles are added

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
