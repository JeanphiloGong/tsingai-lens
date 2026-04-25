# RFC Document-Result Evidence-Chain Contract Freeze

## Summary

This RFC freezes the next additive contract wave for the two drilldown routes
that have to support evidence-chain reading:

- `GET /api/v1/collections/{collection_id}/documents/{document_id}/comparison-semantics`
- `GET /api/v1/collections/{collection_id}/results/{result_id}`

The goal is narrow:

- keep the current Lens v1 product flow
- keep the current Core semantic backbone
- freeze the shared payload shape that backend and frontend should implement
  next for evidence-chain reading

This RFC is a shared contract-freeze page. It does not replace the backend API
authority, but it does freeze the intended additive payload for the next wave
so backend and frontend can execute against the same target.

## Relationship To Current Docs

Read this RFC with:

- [RFC Evidence-Chain Product Surface Delivery Roadmap](rfc-evidence-chain-product-surface-delivery-roadmap.md)
- [RFC Comparison-Result-Document Product Flow](rfc-comparison-result-document-product-flow.md)
- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Paper Facts And Comparison Current State](../architecture/paper-facts-and-comparison-current-state.md)
- [`../../backend/docs/specs/api.md`](../../backend/docs/specs/api.md)
- [`../../backend/docs/plans/core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md`](../../backend/docs/plans/core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md)
- [`../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md`](../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md)

This RFC should be treated as the shared freeze point for the next additive
read contract. The backend API spec remains the long-lived authority after the
routes land.

## Problem

The repository already agrees on the high-level product flow:

`workspace -> comparisons -> result detail -> document detail`

The repository also already agrees on the semantic backbone:

`document_profiles -> paper facts family -> comparable_results -> collection_comparable_results -> row projection`

What is still underspecified is the exact payload contract for the next
evidence-chain drilldown wave.

Today:

- the backend-local plan already proposes grouped document drilldown
- the frontend-local proposal already expects variant dossiers, result chains,
  and result series
- the shared roadmap already says single-chain trustworthiness comes before
  collection aggregation

But there is still no single shared page that freezes the exact additive
contract for the two routes that have to carry that model.

Without this freeze, two failures remain likely:

1. the backend may ship grouped payloads that the frontend has to reinterpret
2. the frontend may invent dossier or chain groupings that the backend never
   actually resolved

## Decision

The next-wave contract is frozen by these rules.

### 1. Keep The Existing Route Hierarchy

The next wave does not add a new top-level browser route family.

The user-facing flow remains:

`comparison row -> result -> document`

The route roles remain:

- `comparisons` is the collection-facing analysis layer
- `results` is the product-facing chain drilldown layer
- `documents` is the source-verification layer

### 2. Keep Existing Flat Semantic Payloads Intact

The document semantic route keeps the current flat `items` list as part of the
response.

Grouped dossier and series payloads are additive projections over the same
underlying semantic truth. They must not become a conflicting second truth.

### 3. Freeze Grouped Document Drilldown As An Additive Projection

The document semantic route is the canonical backend source for document-side
variant dossier and result-series grouping.

The frontend should not invent unsupported semantic grouping from raw text when
the backend has not resolved it.

### 4. Freeze Result Detail As A Chain-First Product Projection

The result detail route remains the product-facing object contract, but its
next additive fields must make one result readable as one evidence chain rather
than only as one measurement card.

## Frozen Route 1: Document Comparison Semantics

### Route

`GET /api/v1/collections/{collection_id}/documents/{document_id}/comparison-semantics`

### Existing Behavior To Preserve

The route keeps these current top-level fields:

- `collection_id`
- `document_id`
- `total`
- `count`
- `items`

The route also keeps the existing optional `include_row_projections` behavior.

### New Query Parameter

Freeze one additive query parameter:

- `include_grouped_projections: bool = false`

Rules:

- when omitted or `false`, the route may omit grouped fields
- when `true`, the route must include `variant_dossiers`
- grouped fields remain derived from the same semantic facts as `items`

### New Top-Level Additive Field

When `include_grouped_projections=true`, the response must add:

- `variant_dossiers`

### Frozen `variant_dossiers` Shape

Each dossier must contain:

- `variant_id`
- `variant_label`
- `material`
- `shared_process_state`
- `shared_missingness`
- `series`

Frozen object shape:

```json
{
  "variant_id": "var_x",
  "variant_label": "optimized VED + HIP",
  "material": {
    "label": "Ti-6Al-4V",
    "composition": "Ti-6Al-4V",
    "host_material_system": {
      "family": "titanium alloy",
      "composition": "Ti-6Al-4V"
    }
  },
  "shared_process_state": {
    "laser_power_w": 280,
    "scan_speed_mm_s": 1200,
    "layer_thickness_um": 30,
    "hatch_spacing_um": 100,
    "build_orientation": "vertical",
    "post_treatment_summary": "HIP"
  },
  "shared_missingness": [
    "powder_oxygen_not_reported"
  ],
  "series": []
}
```

Rules:

- `shared_process_state` carries dossier-level process or sample-state facts
- test-side fields do not belong in `shared_process_state`
- `shared_missingness` is for gaps that affect all child chains of the dossier

### Frozen `series` Shape

Each dossier `series` item must contain:

- `series_key`
- `property_family`
- `test_family`
- `varying_axis`
- `chains`

Frozen object shape:

```json
{
  "series_key": "tensile:test_temperature_c",
  "property_family": "tensile",
  "test_family": "tensile",
  "varying_axis": {
    "axis_name": "test_temperature_c",
    "axis_unit": "C"
  },
  "chains": []
}
```

Rules:

- one series groups sibling chains only when the same dossier is fixed
- one series groups sibling chains only when one explicit test-side axis varies
- process or sample-state changes must split into different dossiers, not into
  one series

### Frozen `chains` Shape Inside A Series

Each chain item must contain:

- `result_id`
- `source_result_id`
- `measurement`
- `test_condition`
- `baseline`
- `assessment`
- `value_provenance`
- `evidence`

Frozen object shape:

```json
{
  "result_id": "cmp_x",
  "source_result_id": "mr_x",
  "measurement": {
    "property": "yield_strength",
    "value": 940.0,
    "unit": "MPa",
    "result_type": "scalar",
    "summary": "YS 940 MPa",
    "statistic_type": null,
    "uncertainty": null
  },
  "test_condition": {
    "test_method": "tensile",
    "test_temperature_c": 25.0,
    "strain_rate_s-1": 0.001,
    "loading_direction": "vertical",
    "sample_orientation": "vertical"
  },
  "baseline": {
    "label": "S2",
    "reference": "optimized VED without HIP",
    "baseline_type": "same_paper_control",
    "resolved": true
  },
  "assessment": {
    "comparability_status": "comparable",
    "warnings": [],
    "basis": [
      "variant_linked",
      "baseline_resolved",
      "test_condition_resolved"
    ],
    "missing_context": [],
    "requires_expert_review": false,
    "assessment_epistemic_status": "normalized_from_evidence"
  },
  "value_provenance": {
    "value_origin": "reported",
    "source_value_text": "940",
    "source_unit_text": "MPa",
    "derivation_formula": null,
    "derivation_inputs": null
  },
  "evidence": {
    "evidence_ids": [
      "evi_x"
    ],
    "direct_anchor_ids": [
      "anc_x"
    ],
    "contextual_anchor_ids": [],
    "structure_feature_ids": [
      "sf_x"
    ],
    "characterization_observation_ids": [
      "obs_x"
    ],
    "traceability_status": "direct"
  }
}
```

Rules:

- `measurement` is the display-facing measurement summary for the chain row
- `test_condition` is chain-local and may differ across siblings in one series
- `baseline.resolved=false` is allowed when the link remains unresolved
- `assessment` stays collection-scoped when collection overlays exist
- `value_provenance` must distinguish reported and derived values explicitly
- `evidence` keeps ids needed for traceback and drilldown; frontend should use
  these ids rather than infer anchors from text

## Frozen Route 2: Result Detail

### Route

`GET /api/v1/collections/{collection_id}/results/{result_id}`

### Existing Behavior To Preserve

The route keeps these current top-level fields:

- `result_id`
- `document`
- `material`
- `measurement`
- `context`
- `assessment`
- `evidence`
- `actions`

The route remains the product-facing projection over:

- one `ComparableResult`
- one current-collection `CollectionComparableResult`

It must not expose raw semantic substrate fields such as:

- `binding`
- `normalized_context`
- `collection_overlays`

as the primary page contract.

### New Top-Level Additive Fields

Freeze these additive fields:

- `variant_dossier`
- `test_condition_detail`
- `baseline_detail`
- `structure_support`
- `value_provenance`
- `series_navigation`

### Frozen `variant_dossier` Shape

```json
{
  "variant_id": "var_x",
  "variant_label": "optimized VED + HIP",
  "material": {
    "label": "Ti-6Al-4V",
    "composition": "Ti-6Al-4V"
  },
  "shared_process_state": {
    "laser_power_w": 280,
    "scan_speed_mm_s": 1200,
    "build_orientation": "vertical",
    "post_treatment_summary": "HIP"
  },
  "shared_missingness": []
}
```

Rules:

- this object is the parent dossier summary for the current chain
- it is not a second page model; it is supporting context for the result page

### Frozen `test_condition_detail` Shape

```json
{
  "test_method": "tensile",
  "test_temperature_c": 25.0,
  "strain_rate_s-1": 0.001,
  "loading_direction": "vertical",
  "sample_orientation": "vertical",
  "environment": null,
  "frequency_hz": null,
  "specimen_geometry": null,
  "surface_state": null
}
```

### Frozen `baseline_detail` Shape

```json
{
  "label": "S2",
  "reference": "optimized VED without HIP",
  "baseline_type": "same_paper_control",
  "baseline_scope": "current_paper",
  "resolved": true
}
```

### Frozen `structure_support` Shape

`structure_support` must be a list of support summaries. Each item must
contain:

- `support_id`
- `support_type`
- `summary`
- `condition`

Example:

```json
[
  {
    "support_id": "obs_x",
    "support_type": "characterization_observation",
    "summary": "Porosity 0.1% with fracture SEM support",
    "condition": {
      "characterization_temperature_c": null
    }
  }
]
```

Rule:

- characterization temperature belongs inside support condition, not under
  `test_condition_detail` and not under dossier process state

### Frozen `value_provenance` Shape

```json
{
  "value_origin": "reported",
  "source_value_text": "940",
  "source_unit_text": "MPa",
  "derivation_formula": null,
  "derivation_inputs": null
}
```

### Frozen `series_navigation` Shape

```json
{
  "series_key": "tensile:test_temperature_c",
  "varying_axis": {
    "axis_name": "test_temperature_c",
    "axis_unit": "C"
  },
  "siblings": [
    {
      "result_id": "cmp_x",
      "axis_value": 25.0,
      "axis_unit": "C",
      "measurement": {
        "property": "yield_strength",
        "value": 940.0,
        "unit": "MPa"
      }
    }
  ]
}
```

Rules:

- `series_navigation` is optional when no sibling series exists
- siblings must stay inside the same dossier and property or test family
- process-side variation must not be collapsed into one series

## Compatibility Rules

These freezes are additive.

The next implementation wave must preserve:

- current route paths
- current top-level route purposes
- current flat `items` response on the document semantic route
- current result detail root contract

The next implementation wave must not:

- add a new top-level `variant-dossiers` browser resource
- replace result detail with raw comparable-result retrieval payloads
- make the frontend compute authoritative dossier or chain identity from raw
  source text

## Non-Goals

This contract freeze does not define:

- experiment-planning payloads
- collection-level synthesis payloads
- new comparison row contracts
- corpus-wide material dossier contracts
- extraction prompt wording

## Adoption Rule

The intended adoption order is:

1. implement backend fact thickening and provenance support
2. implement backend grouped projections for the document semantic route
3. implement backend additive chain-first fields for result detail
4. implement frontend dossier, series, and chain reading surfaces against
   these frozen payloads
5. absorb the landed route shapes back into the long-lived backend API spec

## Open Question Left Intentionally Narrow

This RFC intentionally does not freeze a separate top-level paper overview
payload for the document route.

For the first wave:

- the frontend may derive paper-level counts from `items` and
  `variant_dossiers`
- if later implementation proves that a backend-authored paper summary is
  necessary, that should be a follow-up additive RFC instead of a silent
  expansion here

## Related Docs

- [RFC Evidence-Chain Product Surface Delivery Roadmap](rfc-evidence-chain-product-surface-delivery-roadmap.md)
- [RFC Comparison-Result-Document Product Flow](rfc-comparison-result-document-product-flow.md)
- [`../../backend/docs/specs/api.md`](../../backend/docs/specs/api.md)
- [`../../backend/docs/plans/core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md`](../../backend/docs/plans/core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md)
- [`../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md`](../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md)
