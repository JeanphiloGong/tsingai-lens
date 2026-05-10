# Table-First Extraction Plan

## Summary

Core table extraction should move from row-first selection to table-first
routing, then use the full table as model context when the table is small
enough.

The target flow is:

```text
Source table artifacts
      |
      v
table or section routing
      |
      v
whole-table extraction for small candidate tables
contextual chunk extraction for large candidate tables
      |
      v
deterministic row and cell binding
```

This is a Core LLM structured-extraction plan for
`application/core/semantic_build/llm/` and
`application/core/semantic_build/paper_facts_service.py`. It does not change
public API routes, frontend contracts, parser selection, or Source ownership of
observable table structure.

Read this with:

- [`semantic-routing-targeted-extraction-plan.md`](semantic-routing-targeted-extraction-plan.md)
- [`prompt-hardening-and-extraction-mode.md`](prompt-hardening-and-extraction-mode.md)
- [`../../../../../../docs/plans/source/source-table-artifact-plan.md`](../../../../../../docs/plans/source/source-table-artifact-plan.md)
- [`../../../../../../docs/plans/core/core-parsing-quality-hardening-plan.md`](../../../../../../docs/plans/core/core-parsing-quality-hardening-plan.md)

## Current Behavior

Source currently parses PDF tables into structural artifacts:

- `tables.parquet`
- `table_rows.parquet`
- `table_cells.parquet`

Core then loads those artifacts and selects table rows for paper-fact
extraction. The current selection path is row-first:

1. `PaperFactsService` groups rows and cells by document.
2. `_select_table_rows_for_extraction(...)` scores each row using row text,
   header text, unit hints, and keyword signals.
3. `_batch_table_rows_for_extraction(...)` groups selected rows into small
   batches.
4. The LLM receives table context plus the selected target rows.

This means the model sees table context, but Core has already decided which
rows matter before it has classified what the whole table is. That creates
predictable failures on scientific PDFs:

- composition tables can leak into performance results
- modeling, prediction, equivalent-circuit, or literature-summary tables can be
  mistaken for current-work measurements
- fragmented row labels can become false sample variants
- table-wide caption, section, unit, and header meaning is underused
- small row batches lose neighboring rows that repair broken sample names or
  grouped conditions

## Proposed Flow

Core should classify the table before selecting extraction rows.

```text
document profile
      |
      v
table context
  caption_text
  heading_path
  column_headers
  table_matrix
  table_markdown
  table_text
  row and cell previews
      |
      v
table routing
      |
      +-- skip non-current-work or non-extractable tables
      |
      +-- route process tables to method/sample extraction
      |
      +-- route result tables to result/measurement extraction
      |
      +-- route mixed tables to both targeted extractors
```

Routing should decide whether the table is extractable before fact extraction
starts. It should not emit materials, samples, process facts, measurement
results, evidence anchors, or backend artifact rows.

## Table Routing

The table router should classify one complete table or one bounded large-table
view.

Recommended table roles:

- `process_parameters`
- `experimental_results`
- `mixed_process_and_results`
- `characterization_summary`
- `composition`
- `literature_comparison`
- `modeling_prediction`
- `equivalent_circuit_or_fit`
- `metadata_or_noise`

Recommended routing output:

```json
{
  "table_role": "experimental_results",
  "extractable": true,
  "recommended_extractors": ["result_measurement"],
  "current_work_likelihood": "yes",
  "reason_codes": ["results_caption", "property_columns", "numeric_units"],
  "confidence": 0.86
}
```

The first implementation should use deterministic rules before calling the
model:

- skip obvious composition tables when columns are primarily element symbols or
  chemical composition percentages
- skip obvious literature comparison, review, prior-work, or reference-summary
  tables by caption and heading
- skip obvious modeling or prediction-only tables unless the table also
  contains current experimental measurements
- skip equivalent-circuit fitting parameter tables unless they are explicitly
  needed as current corrosion measurement evidence
- route tables with sample, process, heat-treatment, power, speed, hatch,
  layer, density, hardness, tensile, fatigue, wear, corrosion, or similar
  experimental signals to targeted extraction

The LLM router should handle ambiguous tables that pass deterministic filters.

## Whole-Table Extraction

For small extractable tables, Core should send the whole table to the targeted
extractor instead of only sending five-row batches.

Initial threshold:

```text
selected rows <= 40
table context <= current table-context character budget
```

The model-facing payload should include:

- document title and source filename
- document profile
- routing result
- caption and heading path
- column headers
- complete `table_matrix`
- complete `table_markdown` or `table_text`
- all target rows with row indexes
- row cells with header paths, units, and values
- nearby supporting text windows only when useful

The model may use the full table to interpret:

- grouped rows
- repeated or omitted sample labels
- multi-row headers
- table-wide units
- footnotes and caption constraints
- baseline rows and condition rows

The model must still emit each extracted mention under the matching
`row_index`. Whole-table context is interpretive context, not permission to
copy facts across rows.

## Large Tables

Large tables should not be sent blindly as one prompt. Core should build a
bounded table view that keeps global meaning without exceeding the prompt
budget:

- caption and heading path
- full column headers
- first five rows
- last three rows
- current chunk rows
- immediate previous and next rows
- row-group or section rows that apply to the chunk when available

Large-table extraction should still use row-indexed target rows. The difference
from the current path is that routing happens before extraction and each chunk
receives enough table-level context to avoid treating broken row fragments as
standalone entities.

## Text Sections

The same routing idea should apply to text sections, but with a different
granularity.

Text-window routing should classify the section or window before targeted
extraction. It should decide whether the text is methods, current results,
characterization, background, prior work, references, or noise. It should not
run a separate LLM call before every sentence or every extracted mention.

The practical routing grain should be:

- one table for table artifacts
- one bounded text window or section for prose artifacts

This avoids a call explosion while still preventing broad extraction prompts
from running on irrelevant source units.

## Source And Core Boundary

Source should continue to own observable document structure:

- table detection
- rows, cells, captions, headings, pages, bounding boxes
- complete table matrix preservation
- Markdown or plain-text table rendering
- structural repair where the parser exposes enough matrix information

Core should own semantic decisions:

- whether a table is current-work evidence
- which targeted extractor should run
- how table rows become method, sample, condition, baseline, and measurement
  mentions
- how mentions bind into Core paper-fact artifacts

Source should not decide scientific importance. Core should not reconstruct
missing table structure when Source can preserve it directly. Core should only
derive bounded views, chunks, and model payloads from the complete Source
structure.

## Guardrails

The first implementation should add backend guardrails before materializing
paper facts:

- atmosphere or environment terms such as `argon`, `ar`, `air`, `nitrogen`,
  `n2`, and `vacuum` must not become material families
- pure numbers, unmatched parenthesis fragments, and obvious split labels must
  not become standalone sample variants
- composition-only fields such as `C`, `Cr`, `Ni`, `Mn`, `Mo`, `Si`, `P`, `S`,
  and `Fe` must not become performance measurements by themselves
- review, prior-work, and modeling tables should not produce current-work
  measurement results unless routing marks them as mixed and current-work
  evidence is explicit

These guardrails should stay deterministic and close to materialization. They
are not a replacement for table routing.

## Execution Order

1. Keep Source table-row de-duplication and table artifact loading stable.
2. Add table-level deterministic routing in `PaperFactsService`.
3. Add an LLM table-routing schema and prompt for ambiguous candidate tables.
4. Change small candidate tables to extract with whole-table context.
5. Add bounded contextual chunks for large candidate tables.
6. Add deterministic materialization guardrails for atmospheres, fragments, and
   composition-only fields.
7. Add regression tests against the observed PBF-metal failure cases.

## Verification

The first implementation should be verified with focused unit tests and one
real collection rebuild.

Unit tests should cover:

- PDF table rows remain one row per source row
- composition tables are skipped for measurement extraction
- modeling or prediction-only tables are skipped for current-work measurement
  extraction
- small experimental result tables are passed as one whole-table extraction
  unit
- large tables receive global context plus bounded chunk rows
- atmosphere terms do not materialize as material families
- split row-label fragments do not materialize as sample variants

Collection rebuild checks should confirm:

- `table_rows` total count matches unique `row_id` count
- extracted sample count drops from the inflated failure state
- material families no longer include atmosphere terms such as `argon`
- comparison rows no longer include composition-only or prediction-only rows as
  current experimental measurements
- evidence anchors still preserve `document_id`, `table_id`, `row_index`, and
  cell/header context

## Deferred Work

This plan does not require:

- a public API change
- frontend changes
- a production parser switch
- a new Source semantic artifact
- sending raw PDFs directly to the model
- replacing row and cell evidence anchors

Future work can add richer table-footnote handling, parser-specific table HTML,
and a durable `semantic_routes.parquet` artifact once table routing has proved
useful in rebuild diagnostics.
