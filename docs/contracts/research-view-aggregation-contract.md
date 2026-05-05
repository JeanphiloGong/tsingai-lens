# Research View Aggregation Contract

## Purpose

This document defines the target shared contract for turning paper facts into
research-facing aggregation views.

It follows the direction in
[`rfc-research-view-aggregation-layer.md`](../decisions/rfc-research-view-aggregation-layer.md):
raw paper facts remain traceable, paper pages should render sample matrices and
condition series, and collection pages should use material profiles as the
primary research surface.

## Status

The backend first slice is now an active runtime API surface for collection and
paper research-view reads. Frontend adoption is still tracked by the frontend
implementation plan.

Backend and frontend implementation plans should continue to use this page as
the shared shape while the UI migrates away from raw result-card lists.

## Contract Rules

- Research aggregation is a derived view over `document_profiles`, the
  `paper_facts` family, `comparison_rows`, and evidence anchors.
- Raw `measurement_results` should not be listed directly as the primary
  collection or paper result surface.
- The backend owns material canonicalization, grouping, deduplication,
  condition-series assembly, and evidence-preserving aggregation.
- The frontend owns rendering, interaction state, evidence drawers, and tab
  placement.
- Every visible value that comes from extracted facts must preserve evidence
  references or an explicit missing-evidence warning.
- Missing fields, weak binding, duplicate facts, and conflicts must remain
  visible as structured warnings.
- Browser requests must stay on the same-origin `/api/v1/*` contract.

## Target API Surfaces

The target contract should expose four read surfaces.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/collections/{collection_id}/research-view` | Collection-level aggregation for overview, material summaries, paper coverage, advanced comparison links, trends, and debug links. |
| `GET /api/v1/collections/{collection_id}/materials` | Collection-level material summaries for the primary `Materials` tab. |
| `GET /api/v1/collections/{collection_id}/materials/{material_id}/research-view` | Collection-scoped material profile with papers, samples, process ranges, properties, comparisons, condition series, evidence, and warnings. |
| `GET /api/v1/collections/{collection_id}/documents/{document_id}/research-view` | Paper-level aggregation for paper overview, paper-scoped materials, sample matrix, condition series, and paper-scoped evidence/debug links. |

These endpoints should not require the browser to reconstruct sample matrices or
material profiles from raw `measurement_results`.

Document-scoped material endpoints may be added when the paper detail page
needs a separate material entry or a deep link into one material inside one
paper:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/collections/{collection_id}/documents/{document_id}/materials` | Paper-scoped materials detected in one document. |
| `GET /api/v1/collections/{collection_id}/documents/{document_id}/materials/{material_id}/research-view` | Paper-scoped material profile for one document. This is not a collection material profile. |

Optional query parameters may be added only when they are directly needed by
the UI:

| Parameter | Meaning |
| --- | --- |
| `include_evidence_refs` | Include evidence reference payloads for matrix cells and series points. |
| `include_debug_counts` | Include duplicate, conflict, and unresolved raw-fact counts. |

## Shared State Model

All aggregation responses should use the same top-level state meanings.

| State | Meaning |
| --- | --- |
| `empty` | The collection, material, or document has no source material to aggregate. |
| `processing` | The required upstream artifacts are still being built. |
| `partial` | Enough data exists to render the view, but important context is missing or weak. |
| `ready` | The view has enough structured facts and evidence to support normal use. |
| `failed` | The system attempted to build the view and failed. |

Warnings should be structured objects rather than collapsed prose:

```text
warning_id
severity
scope
code
message
related_object_ids
```

## Evidence Reference

Every aggregate cell, row, series point, and comparable-group row should be able
to point back to evidence.

Minimum shape:

```text
EvidenceReference
- evidence_ref_id
- fact_ids
- anchor_ids
- source_kind
- document_id
- locator
- confidence
- traceability_status
```

`locator` may point to page, table, row, paragraph, figure, or fallback source
context. The contract does not require precise PDF region coordinates in the
first slice.

## Evidence Backed Value

`EvidenceBackedValue` is the common value cell used by sample matrices,
condition series, comparable groups, and cross-paper matrices.

Minimum shape:

```text
EvidenceBackedValue
- display_value
- value
- unit
- normalized_value
- normalized_unit
- status
- confidence
- evidence_refs
- duplicate_count
- conflict_status
- warnings
```

Allowed `status` values:

| Status | Meaning |
| --- | --- |
| `observed` | Directly supported by extracted evidence. |
| `normalized` | Derived from observed evidence through unit or label normalization. |
| `inferred` | Inferred from nearby structure or table context. |
| `missing` | Expected for the row or group but unavailable. |
| `conflicted` | Multiple facts disagree and cannot be resolved automatically. |

## Paper Aggregation

`PaperAggregation` is the target response object for paper detail research
views.

Minimum shape:

```text
PaperAggregation
- collection_id
- document_id
- paper_title
- state
- overview
- materials
- sample_matrix
- condition_series
- evidence_links
- debug_links
- warnings
```

### Paper Overview

The paper overview should summarize:

- material systems
- detected sample or variant count
- main process variables
- measured properties
- condition families
- evidence and extraction warnings

### Paper Materials

`PaperMaterialSummary` is the material entry inside one paper. It is scoped by
`document_id`, not by the whole collection.

Minimum shape:

```text
PaperMaterialSummary
- material_id
- canonical_name
- aliases
- sample_count
- process_families
- measured_properties
- comparison_count
- evidence_coverage
- links
- warnings
```

`DocumentMaterialProfile` is the optional drilldown object for one material
inside one paper. It should answer how the paper studied that material without
performing collection-wide material merging or cross-paper comparison.

Minimum shape:

```text
DocumentMaterialProfile
- collection_id
- document_id
- material_id
- canonical_name
- aliases
- state
- overview
- sample_matrix
- process_conditions
- test_conditions
- measured_properties
- within_paper_comparisons
- condition_series
- evidence_refs
- debug_links
- warnings
```

The same canonical material may link from `DocumentMaterialProfile` to the
collection-scoped `MaterialProfile`, but the two objects have different
ownership boundaries:

- `DocumentMaterialProfile` is one paper's view of one material.
- `MaterialProfile` is the collection's cross-paper view of one material.

### Sample Matrix

`SampleMatrix` should organize one paper into sample or variant rows.

Minimum shape:

```text
SampleMatrix
- matrix_id
- document_id
- state
- columns
- rows
- warnings
```

`SampleMatrixRow` minimum shape:

```text
SampleMatrixRow
- row_id
- sample_id
- sample_label
- material
- process_context
- variable_axis
- variable_value
- values
- evidence_refs
- warnings
```

`values` should be keyed by normalized property or process column. Duplicate
raw facts should increase `duplicate_count` inside the relevant
`EvidenceBackedValue`; they should not create duplicate visible rows.

### Condition Series

`ConditionSeries` should group values that share a sample, property, and
condition axis.

Minimum shape:

```text
ConditionSeries
- series_id
- document_id
- sample_id
- property
- condition_axis
- points
- warnings
```

`ConditionSeriesPoint` minimum shape:

```text
ConditionSeriesPoint
- point_id
- condition_value
- condition_unit
- result
- evidence_refs
- warnings
```

## Collection Aggregation

`CollectionAggregation` is the target response object for the collection
workspace research view.

Minimum shape:

```text
CollectionAggregation
- collection_id
- state
- overview
- materials
- paper_coverage
- comparable_groups
- cross_paper_matrices
- trend_series
- evidence_links
- debug_links
- warnings
```

### Material Summary

`MaterialSummary` is the row or card object for the collection `Materials` tab.

Minimum shape:

```text
MaterialSummary
- material_id
- canonical_name
- aliases
- paper_count
- sample_count
- process_families
- measured_properties
- comparison_count
- evidence_coverage
- state
- links
- warnings
```

`material_id` should be stable within the collection and derived from the
canonical material key. It should not be the display name when aliases or
normalization may change.

### Material Profile

`MaterialProfile` is the collection-scoped research object for one material.
It is the normal parent surface for material-specific sample matrices,
process summaries, property summaries, comparable groups, condition series, and
evidence.

Minimum shape:

```text
MaterialProfile
- collection_id
- material_id
- canonical_name
- aliases
- state
- overview
- papers
- sample_matrix
- process_parameter_ranges
- measured_properties
- comparison_groups
- condition_series
- evidence_refs
- debug_links
- warnings
```

`MaterialPaperCoverage` minimum shape:

```text
MaterialPaperCoverage
- document_id
- title
- state
- sample_count
- process_families
- measured_properties
- evidence_count
- issue_count
- links
- warnings
```

`ProcessParameterRange` minimum shape:

```text
ProcessParameterRange
- parameter
- display_range
- min_value
- max_value
- unit
- sample_count
- document_count
- evidence_refs
- warnings
```

`PropertySummary` minimum shape:

```text
PropertySummary
- property
- display_range
- min_value
- max_value
- unit
- sample_count
- document_count
- evidence_refs
- warnings
```

Material canonicalization should prefer, in order:

- normalized material fields from comparison rows when available
- normalized sample-variant material fields
- raw sample-variant material names or composition strings
- explicit missing-material warnings when no reliable material key exists

Aliases should preserve common names found in source facts, such as `316L`,
`SS316L`, `AISI 316L`, and `316L stainless steel`, without making each alias a
separate material profile.

### Paper Coverage

`PaperCoverageRow` should show whether each paper is usable for comparison.

Minimum shape:

```text
PaperCoverageRow
- document_id
- title
- state
- sample_count
- process_param_count
- measurement_count
- condition_count
- evidence_count
- issue_count
- primary_warnings
- links
```

### Comparable Group

`ComparableGroup` is a material-context research object. It answers how one
variable axis relates to properties under a material, process, test-condition,
and baseline context.

Minimum shape:

```text
ComparableGroup
- group_id
- title
- material_system
- process_family
- variable_axis
- fixed_conditions
- properties
- documents
- samples
- comparability_status
- matrix
- evidence_refs
- warnings
```

`comparability_status` should distinguish at least:

| Status | Meaning |
| --- | --- |
| `comparable` | Enough aligned context exists for direct comparison. |
| `limited` | Some comparison is possible, but important context is missing. |
| `blocked` | The group should not be compared without more curation. |

### Cross-Paper Matrix

`CrossPaperMatrix` should make one comparable group inspectable.

Minimum shape:

```text
CrossPaperMatrix
- matrix_id
- group_id
- columns
- rows
- warnings
```

Rows should preserve:

```text
document_id
sample_id
material
process_context
variable_value
test_condition
property
result
evidence_refs
warnings
```

## Frontend Navigation Mapping

The collection tabs should map to this contract as follows.

| Tab | Localized label | Contract data |
| --- | --- | --- |
| Overview | 概览 | `overview`, readiness `state`, summary warnings, material summary, and paper coverage summary. |
| Materials | 材料 | `materials` or `/materials` summaries and links to `MaterialProfile` pages. |
| Papers | 文献 | `paper_coverage` rows and links to paper detail research views. |
| Graph | 图谱 | Existing graph endpoints; graph remains a secondary exploration surface. |
| More | 更多 | all comparisons, `evidence_links`, `debug_links`, exports, evaluation reports, and settings. |

Paper detail pages should use `PaperAggregation` rather than collection
navigation to show sample matrices and condition series for one document.

Material detail pages should use `MaterialProfile` rather than a global
comparison list. The comparison module inside material detail should render
`comparison_groups`, `cross_paper_matrices`, and `trend_series` filtered to
that material. `More / All Comparisons` may render global comparison search and
debugging, but it is not the primary collection navigation.

## Migration Boundary

This contract should be added as a direct product contract, not as a browser
compatibility layer over old raw-result card pages.

During migration, existing endpoints may remain available for evidence, debug,
and deep-link stability, but the primary collection and paper pages should move
to this contract once the backend and frontend plans are implemented.

## Verification Expectations

Backend contract verification should cover:

- paper aggregation builds one row per real sample or variant
- paper aggregation exposes paper-scoped material summaries when material
  bindings exist
- document material profiles stay inside one `document_id` and do not include
  cross-paper facts
- duplicate `measurement_results` do not duplicate matrix rows
- every observed value has evidence references or a warning
- collection aggregation exposes material summaries before advanced comparison
  links
- material summaries merge aliases instead of splitting one material into many
  rows
- material profiles expose papers, sample matrices, process ranges, property
  summaries, comparison groups, condition series, evidence refs, and warnings
- comparable groups preserve fixed conditions, variable axes, and warnings
  under material context

Frontend verification should cover:

- collection tabs render as `Overview / Materials / Papers / Graph / More`
- `Materials` links to material profile pages
- `Papers` links to paper detail rather than duplicating paper internals
- paper detail can render document-scoped material views without treating them
  as collection material profiles
- material detail renders comparison groups and matrices rather than raw fact
  cards
- `More / All Comparisons` remains available for global comparison browsing
- `More` contains evidence/debug surfaces
- loading, empty, partial, ready, and failed states are explicit

## Related Docs

- [RFC Research View Aggregation Layer](../decisions/rfc-research-view-aggregation-layer.md)
- [Lens Core Artifact Contracts](lens-core-artifact-contracts.md)
- [Lens V1 Definition](lens-v1-definition.md)
- [Backend Research View Aggregation Plan](../../backend/docs/plans/backend-wide/research-view-aggregation/README.md)
- [Frontend Research View Aggregation Plan](../../frontend/docs/research-view-aggregation/README.md)
