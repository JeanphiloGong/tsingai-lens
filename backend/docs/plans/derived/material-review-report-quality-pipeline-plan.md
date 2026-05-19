# Material Review Report Quality Pipeline Plan

## Summary

Material review report generation should move from one-shot long-form drafting
to a staged, evidence-reviewed writing pipeline.

The current service already builds a `MaterialReviewContextPack` from material
research-view data, but a single LLM call can still produce a generic review
that underuses sample, process, property, trend, and evidence data. The target
pipeline should spend more time organizing and reviewing the report so the
output is slower but materially better grounded.

The desired shape follows the same broad pattern as long-form research systems:

- STORM-style pre-writing, outline generation, and cited article writing
- PaperQA-style answer grounding over scientific documents with citations
- AutoSurvey-style outline planning, section drafting, evaluation, and
  iteration

This remains a backend derived-surface plan. It improves generated material
review reports without moving primary evidence ownership out of Core
research-view artifacts.

## Current Problem

The material review report endpoint can generate a review that is formally
structured but too shallow:

- concrete sample and property values are available in the context pack but may
  not appear in the main text
- broad statements such as "process parameters significantly affect
  performance" can appear without sample IDs, property values, or evidence IDs
- single-paper collections can receive review-like phrasing that implies broader
  cross-literature support than the collection contains
- evidence IDs may appear only sparsely, while most numerical claims are left
  unbound
- PDF generation is downstream of whatever Markdown the model produces, so the
  renderer cannot repair missing analysis

The fix should not be only "force a table into the output." Deterministic tables
are useful as an appendix or fallback, but the report body itself should be
planned, written, reviewed, and revised around the structured evidence.

## Target Pipeline

The report generator should become a multi-stage pipeline:

```text
Research-view artifacts
  -> Data Pack Builder
  -> Outline Planner
  -> Section Context Selector
  -> Section Writer
  -> Evidence Binder
  -> Critic / Reviewer
  -> Revision Pass
  -> Final Integrator
  -> PDF Renderer
```

Each stage should write a durable intermediate artifact under the material
review report output directory. The service can then explain progress, retry
failed stages, and expose warnings without forcing users to inspect raw logs.

## Data Pack Builder

The data pack builder should be deterministic. It should transform
research-view payloads into a writing-oriented `MaterialReviewDataPack` instead
of passing the full raw profile directly to a drafting model.

Inputs:

- material research-view profile
- sample matrix rows
- comparison groups when available
- evidence references
- document profiles and paper metadata
- optional table cell and measurement artifacts when more detailed trace is
  needed

Output artifact:

```text
material_review_reports/{material_id}/data_pack.json
```

Minimum shape:

```json
{
  "material": {
    "canonical_name": "316L stainless steel",
    "aliases": ["316L"],
    "material_family": "stainless steel"
  },
  "literature_scope": {
    "paper_count": 1,
    "included_papers": [],
    "scope_warning": "single_paper_only"
  },
  "sample_design": {
    "sample_count": 16,
    "process_parameters": [
      "energy_density_j_mm3",
      "scan_speed_mm_s",
      "hatch_spacing_um",
      "scan_strategy"
    ],
    "sample_rows": []
  },
  "property_matrix": {
    "properties": [
      "density",
      "hardness",
      "yield_strength",
      "tensile_strength",
      "elongation"
    ],
    "rows": []
  },
  "computed_summaries": {
    "property_ranges": [],
    "best_values": [],
    "worst_values": [],
    "paired_comparisons": [],
    "trend_candidates": []
  },
  "evidence_index": {},
  "quality_flags": []
}
```

The builder should compute, rather than ask the model to infer:

- property ranges for every core property
- best and worst values with sample IDs and evidence IDs
- complete sample-process rows
- sample-property matrix rows
- comparable sample pairs from controlled variables
- trend candidates such as same energy density with different scan strategy,
  same scan strategy with different energy density, and high/low property
  contrasts
- quality flags for single-paper scope, missing values, duplicate values,
  conflicted cells, weak comparability, and absent comparison groups

## Outline Planner

The outline planner should generate a structured outline before any full prose
is written.

Input:

- material summary
- literature scope
- computed summaries
- quality flags
- supported section types

Output artifact:

```text
material_review_reports/{material_id}/outline.json
```

Expected shape:

```json
{
  "title": "316L stainless steel selective laser melting process-property review",
  "sections": [
    {
      "id": "literature_scope",
      "title": "Literature Scope and Evidence Boundary",
      "purpose": "State the collection size and avoid unsupported cross-literature claims.",
      "required_data": ["literature_scope"],
      "required_claims": ["paper_count", "sample_count"]
    },
    {
      "id": "property_results",
      "title": "Performance Results and Sample-Level Differences",
      "purpose": "Summarize the measured property ranges and named sample contrasts.",
      "required_data": [
        "property_ranges",
        "property_matrix",
        "best_values",
        "worst_values"
      ],
      "required_claims": [
        "density_range",
        "hardness_range",
        "yield_strength_range",
        "tensile_strength_range",
        "elongation_range"
      ]
    }
  ]
}
```

Planning rules:

- if `paper_count < 3`, do not create a substantive
  "cross-paper consistency" section; create an evidence-boundary section
  instead
- if there are no comparison groups, do not claim controlled cross-paper
  comparison support
- if there are at least five core property groups, plan a property matrix
  analysis section
- if there are multiple samples, plan a sample design and process-parameter
  section
- every planned section must name the data it needs and the claims it must
  cover

## Section Context Selector

The section context selector should provide only the data required for one
section. This keeps the section writer from drowning in the full context pack.

For example, the property-results section should receive:

- property ranges
- best and worst values
- relevant property matrix rows
- relevant trend candidates
- the evidence subset needed for those rows

The mechanism section should receive:

- trend candidates
- source-supported claims
- quality flags
- limitations

It should not receive unrelated table rows simply because they exist in the
collection.

Output artifact:

```text
material_review_reports/{material_id}/section_contexts.json
```

## Section Writer

The section writer should write one section at a time. Each section should
return both Markdown and structured claim metadata.

Output artifact:

```text
material_review_reports/{material_id}/sections.json
```

Expected section shape:

```json
{
  "section_id": "property_results",
  "markdown": "...",
  "claims": [
    {
      "claim": "Sample 2 reaches the highest density of 97.7%, but its elongation is only 1.79%.",
      "claim_type": "direct_observation",
      "sample_ids": ["2"],
      "properties": ["density", "elongation"],
      "values": ["97.7 %", "1.79 %"],
      "evidence_ids": ["E06", "E09"]
    }
  ]
}
```

Writing rules:

- every results section should include concrete values, not only qualitative
  summaries
- broad sentences such as "the property changes significantly" must be followed
  by sample IDs, property values, and evidence IDs
- mechanism language must distinguish direct observation, trend observation,
  hypothesis, and research gap
- single-paper reports must say "in the current paper" or "in the current
  collection" rather than imply literature-wide consensus
- section Markdown should not introduce values outside the section context

## Evidence Binder

The evidence binder should verify the claims returned by the writer against the
data pack.

Output artifact:

```text
material_review_reports/{material_id}/bound_claims.json
```

Binding result shape:

```json
{
  "claim": "...",
  "binding_status": "bound",
  "bound_evidence": ["E06", "E09"],
  "sample_ids": ["2"],
  "properties": ["density", "elongation"],
  "values": ["97.7 %", "1.79 %"],
  "problems": []
}
```

Binding statuses:

- `bound`
  The claim matches data pack values and cites valid evidence.
- `weak`
  The claim is plausible but generalized beyond the cited values.
- `unsupported`
  The claim lacks matching evidence or concrete data.
- `contradicted`
  The claim conflicts with the data pack.

The binder should detect:

- invalid evidence IDs
- missing evidence IDs on key claims
- values that do not exist in the data pack
- sample IDs that do not match the cited value
- property labels that drift from canonical groups
- generalizations that overstate single-paper or weak-comparison evidence

## Critic and Reviewer

The reviewer should not write new content. It should identify quality failures
and create revision instructions.

Output artifact:

```text
material_review_reports/{material_id}/review_notes.json
```

Expected shape:

```json
{
  "section_id": "property_results",
  "status": "failed",
  "blocking_issues": [
    {
      "type": "missing_required_data",
      "message": "The section does not list hardness, yield strength, tensile strength, and elongation ranges."
    },
    {
      "type": "generic_language",
      "message": "The sentence 'performance differs significantly' is not tied to concrete values."
    }
  ],
  "revision_instructions": [
    "Add min and max values for every core property.",
    "Bind every result sentence to evidence IDs."
  ]
}
```

Reviewer rules:

- the abstract should include at least two concrete, evidence-backed data points
- the property-results section should cover all core property groups present in
  the data pack
- the conclusion should cite evidence IDs
- mechanism discussion should not make causal claims beyond the data support
- single-paper reports should not include substantive cross-paper consensus
  claims
- if the property matrix has many rows but the section cites only a few values,
  the section should be revised

## Revision Pass

Failed sections should go through a bounded revision loop.

Inputs:

- the original section
- reviewer notes
- bound claims
- section data context

Output artifact:

```text
material_review_reports/{material_id}/revisions.json
```

The service should allow at most two automatic revision rounds per section. If a
section still fails after the revision limit, the report can finish as
`ready_with_warnings` and include reviewer notes in the appendix.

## Final Integrator

The final integrator should assemble approved sections into a single Markdown
document.

Output artifact:

```text
material_review_reports/{material_id}/review.md
```

Integrator responsibilities:

- preserve the planned section order
- standardize terminology such as SLM, LPBF, and material aliases
- remove duplicate prose
- avoid adding new facts not present in section outputs
- add deterministic appendices:
  - sample-process matrix
  - sample-property matrix
  - evidence table
  - reviewer warnings when present

The deterministic tables are still useful, but they should support the reviewed
main text rather than compensate for a generic body.

## PDF Renderer

The PDF renderer should only render final Markdown. It should not create or
repair report content.

Output artifact:

```text
material_review_reports/{material_id}/review.pdf
```

Renderer requirements:

- preserve the AI-assisted draft disclaimer
- render section headings and appendices predictably
- include warnings when the report is `ready_with_warnings`
- avoid hiding reviewer or evidence-binding failures behind a polished PDF

## Task Status Model

The report task should expose granular progress:

```text
building_data_pack
planning_outline
selecting_section_contexts
writing_sections
binding_evidence
reviewing
revising
integrating
rendering_pdf
ready
ready_with_warnings
failed
```

This lets the frontend show that a slower generation run is doing meaningful
quality work rather than hanging.

## 316L Acceptance Bar

For the 316L stainless steel SLM case, a generated report should satisfy these
minimum checks:

- the data pack includes all 16 samples
- the property matrix includes all five core properties:
  - density
  - hardness
  - yield strength
  - tensile strength
  - elongation
- the sample design section states the actual process parameter space
- the property-results section gives ranges or extrema for every core property
- the report contains at least three sample-level comparisons with concrete
  values
- each key conclusion cites evidence IDs
- single-paper scope is described as a limitation, not hidden
- the text does not claim cross-paper consensus when only one paper is present

An acceptable paragraph should look more like:

```text
The current collection contains one experimental paper and 16 SLM samples.
Sample 2 reaches the highest density of 97.7% [E06], but its elongation is only
1.79% [E09]. Sample 1 shows lower density at 95.4% [E01] while retaining higher
elongation at 7.21% [E04]. This supports a sample-level observation that the
highest-density condition is not necessarily the best ductility condition in
this collection; broader mechanism claims still require more evidence.
```

It should not look like:

```text
Different process parameters have a significant impact on the properties of
316L stainless steel.
```

unless the sentence is immediately grounded in specific samples, values, and
evidence IDs.

## Implementation Phases

### Phase 1: Data Pack and Sectioned Generation

Primary outcomes:

- add `MaterialReviewDataPackBuilder`
- add `OutlinePlanner`
- add `SectionContextSelector`
- add `SectionWriter`
- write `data_pack.json`, `outline.json`, `section_contexts.json`, and
  `sections.json`
- keep the current Markdown/PDF endpoint contract stable

Verification:

- unit tests for 316L-style data pack construction
- tests that single-paper scope produces a boundary section rather than
  cross-paper consensus language
- tests that each planned section declares required data

### Phase 2: Evidence Binding and Review

Primary outcomes:

- add `EvidenceBinder`
- add `ReportReviewer`
- add `RevisionService`
- write `bound_claims.json`, `review_notes.json`, and `revisions.json`
- mark reports as `ready_with_warnings` when review issues remain

Verification:

- generic unsupported claims are rejected or revised
- invalid evidence IDs remain warnings
- values not present in the data pack are rejected
- conclusion sections without evidence citations are downgraded

### Phase 3: Integration and Frontend Visibility

Primary outcomes:

- add final Markdown integration over approved sections
- preserve deterministic appendices
- expose granular generation stages in report status metadata
- allow frontend to display warnings and intermediate availability

Verification:

- existing report routes remain stable
- report status transitions are deterministic
- generated Markdown includes data-backed main text and appendix tables

### Phase 4: Quality Evaluation

Primary outcomes:

- add a 316L golden report evaluation fixture
- score reports for data coverage, evidence coverage, generic language, and
  unsupported claims
- compare one-shot generation against the staged pipeline before default
  cutover

Verification:

- the 316L report covers all core property ranges
- reviewer catches generic summaries
- evidence binder catches sample/value/evidence mismatches

## Ownership and Boundaries

This plan belongs to the backend derived layer because the report is a
downstream product surface derived from Core research-view artifacts.

This plan does not change:

- Core paper-facts ownership
- research-view artifact contracts
- frontend report display semantics beyond status and warning visibility
- PDF rendering into a content-generation stage

If future work changes the public report API shape, update
`backend/docs/specs/api.md` in the same implementation wave.

## Related Documents

- [`../../../application/derived/README.md`](../../../application/derived/README.md)
- [`../backend-wide/research-view-aggregation/README.md`](../backend-wide/research-view-aggregation/README.md)
- [`../../specs/api.md`](../../specs/api.md)
- [`../../../../docs/contracts/research-view-aggregation-contract.md`](../../../../docs/contracts/research-view-aggregation-contract.md)
- [`../../../../docs/decisions/rfc-research-view-aggregation-layer.md`](../../../../docs/decisions/rfc-research-view-aggregation-layer.md)
