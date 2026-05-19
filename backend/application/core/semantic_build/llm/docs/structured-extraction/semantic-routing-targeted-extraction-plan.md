# Semantic Routing And Targeted Extraction Plan

## Summary

Core semantic extraction should move from broad prompt-driven extraction to a
paper-reading flow that first classifies what a source unit is, then runs only
the extractors that match that unit.

The target flow is:

```text
semantic routing -> targeted extraction -> deterministic binding
```

This plan is a Core-internal extraction redesign for the
`application/core/semantic_build/llm/` prompt, schema, and extractor boundary.
It does not change Source artifacts, public API routes, parser selection, or
frontend contracts.

## Context

The current Core LLM path has already moved away from heuristic extraction and
now consumes Source artifacts through bounded text windows and table batches.
That improves evidence locality, but the model-facing prompts still ask one
call to handle too many semantic decisions at once.

The active text-window prompt extracts:

- methods
- materials
- variants
- conditions
- baselines
- result claims

The active table-batch prompt extracts:

- target-row subjects
- process mentions
- test-condition mentions
- baseline mentions
- result claims

This mixed responsibility creates predictable failure modes:

- process conditions can be confused with test conditions
- characterization methods can be treated as result tests
- prior-work or literature-summary statements can leak into current-work
  measurements
- broad table context can help interpretation but still requires row-specific
  result binding
- schema-valid responses can still classify facts into the wrong semantic
  family

## Proposed Flow

Core should add a lightweight semantic-routing stage before fact extraction.
Routing classifies each candidate text window or table batch and returns the
extractors that are allowed to run for that unit.

```text
Source artifacts
  documents / blocks / tables / table_rows / table_cells
        |
        v
Document profile
        |
        v
Semantic routing
  text-window routes
  table-batch routes
        |
        v
Targeted extraction
  method/sample extraction
  result/test/baseline extraction
  characterization extraction
        |
        v
Deterministic binding
  method_facts
  sample_variants
  test_conditions
  baseline_references
  measurement_results
  evidence_anchors
```

The model should not directly emit final backend artifacts. It should emit
lightweight mentions, and `PaperFactsService` should keep binding those mentions
into the existing Core artifact family.

## Routing Artifact

The first durable Core artifact for this design should be:

```text
semantic_routes.parquet
```

Recommended fields:

```text
route_id
document_id
source_kind
source_ref
role
recommended_extractors
current_work_likelihood
confidence
reason_codes
```

`source_kind` should distinguish:

- `text_window`
- `table_batch`

`role` should be enum-stable:

- `methods`
- `results`
- `characterization`
- `comparison`
- `background`
- `references`
- `noise`
- `mixed`

`recommended_extractors` should stay narrow:

- `method_sample`
- `result_measurement`
- `characterization`
- `skip`

`current_work_likelihood` should be:

- `yes`
- `partial`
- `no`
- `uncertain`

The routing artifact is an internal Core artifact. It is useful for trace
debugging and rebuild diagnosis, but it should not become a frontend API
contract in the first wave.

## Routing Prompt

The routing prompt should classify one candidate unit and avoid fact extraction.

Text-window input shape:

```json
{
  "document_profile": {},
  "source_kind": "text_window",
  "heading_path": "Results > Mechanical properties",
  "block_type": "paragraph",
  "text_preview": "The tensile strength increased to 950 MPa..."
}
```

Table-batch input shape:

```json
{
  "document_profile": {},
  "source_kind": "table_batch",
  "table_context": {
    "caption_text": "Table 1 Mechanical properties.",
    "column_headers": ["Sample", "Tensile strength (MPa)", "Baseline"]
  },
  "target_rows": [
    {
      "row_index": 1,
      "row_summary": "A1 | 950 | as-built"
    }
  ]
}
```

Routing output shape:

```json
{
  "role": "results",
  "recommended_extractors": ["result_measurement"],
  "current_work_likelihood": "yes",
  "reason_codes": ["results_heading", "numeric_property_value"],
  "confidence": 0.86
}
```

Routing must not emit materials, methods, variants, baselines, measurements,
or evidence anchors.

## Targeted Extractors

The first implementation should replace broad extraction prompts with two
targeted extractors and leave deeper characterization observation extraction
for a later wave.

### Method And Sample Extraction

This extractor should handle:

- material system mentions
- sample and variant definitions
- preparation and process methods
- process parameters
- post-treatment
- characterization method descriptions when the text explains how
  characterization was performed

It should not emit measurement results or comparison-ready property claims.

### Result And Measurement Extraction

This extractor should handle:

- property results
- numeric values and units
- trends
- baselines
- test conditions
- current-work versus prior-work classification
- variant/result binding

It should not emit process preparation facts unless they are required only as
short local context for result binding.

### Characterization Extraction

The first wave may keep characterization observations out of scope. A later
wave can add a narrower characterization extractor for morphology, phase,
microstructure, spectroscopy, and imaging observations.

## Table Handling

Table batches should keep the current row-index evidence boundary.

Routing should classify table batches into categories such as:

- process parameter table
- result table
- characterization summary table
- literature comparison table
- metadata or noise table

Recommended extractor behavior:

- process parameter table -> method/sample extractor
- result table -> result/measurement extractor
- literature comparison table -> no current-work measurement extraction by
  default
- mixed table -> both method/sample and result/measurement extractors may run,
  but every row result must stay under the matching `row_index`

The table context should remain shared across the batch so headers, captions,
units, group labels, and footnotes are available without repeating them once
per row.

## Execution Rules

The first implementation should use direct hard cutover rather than keeping
the broad extraction prompts as a compatibility path.

Recommended Core version:

```text
paper_facts_v6
```

When the manifest version does not match, Core should purge stale semantic
artifacts and rebuild through the new routing and targeted-extraction flow.

Execution rules:

- `background`, `references`, and `noise` routes default to `skip`
- `methods` routes run method/sample extraction only
- `results` routes run result/measurement extraction only
- `mixed` routes may run both targeted extractors
- review documents should not produce current-work measurements unless routing
  and extraction both support that conclusion with explicit evidence
- model outputs remain lightweight mention shapes, not final backend artifact
  rows

## Implementation Slices

1. Add routing schema, prompt, and extractor method.
   - Add `StructuredSemanticRoute`.
   - Add `extract_semantic_route(...)`.
   - Normalize unknown enum values to stable fallback values.

2. Add routing to `PaperFactsService`.
   - Route selected text windows and table batches before extraction.
   - Persist `semantic_routes.parquet`.
   - Log route counts by role and recommended extractor.

3. Split text-window extraction.
   - Replace the broad text-window prompt with method/sample and
     result/measurement prompts.
   - Keep deterministic backend binding for artifacts and evidence anchors.

4. Split table-batch extraction.
   - Replace the broad table-batch prompt with table method/sample and table
     result/measurement prompts.
   - Preserve the existing batch input shape and row-index binding.

5. Update binding.
   - Method/sample outputs feed `method_facts` and `sample_variants`.
   - Result outputs feed `test_conditions`, `baseline_references`, and
     `measurement_results`.
   - Evidence anchors remain generated in Core backend code.

6. Bump artifact version and tests.
   - Set `CURRENT_CORE_SEMANTIC_VERSION` to `paper_facts_v6`.
   - Update fake extractor support, service tests, extractor tests, and docs.

## Verification

The implementation should prove:

- methods windows do not produce measurement results
- results windows do not produce process methods unless explicitly routed as
  mixed
- background, references, and noise units are skipped
- literature comparison tables do not enter current-work measurement artifacts
- table batches still return row-specific results under `row_index`
- method/sample context can still bind to results from the same paper
- existing comparison rows still build from the resulting artifacts
- `semantic_routes.parquet` explains why each unit was extracted or skipped

Targeted checks should cover:

```text
tests/unit/services/test_core_llm_extractor.py
tests/unit/services/test_paper_facts_services.py
tests/integration/services/test_task_runner.py
python3 scripts/check_docs_governance.py
```

## Boundaries

This plan should not:

- change Source artifacts
- change public API routes or frontend contracts
- introduce MinerU as a production parser dependency
- add a parser switch
- split extraction into one prompt per individual field
- keep the old broad prompts as a long-lived compatibility path
- let the model emit final backend artifact rows

The purpose is to make Core extraction more like evidence-first paper reading:
identify what a unit is, extract only the facts appropriate to that unit, and
let deterministic backend code keep the artifact contract stable.
