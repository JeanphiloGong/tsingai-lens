# Paper Facts

This package retains the model-assisted table-structure repair used by
Objective analysis. It does not run a separate paper-fact extraction pipeline.

## Owner

- `extraction.py`
  Owns the table-repair prompt, the two `TableMatrixRepair*ModelOutput`
  contracts, model requests, completion limits, retries, and traces.
- [`../objectives/analysis/table_repair.py`](../objectives/analysis/table_repair.py)
  Selects tables needing repair and checks that repaired labels, headers,
  numeric sequences, and units preserve the Source before extraction continues.

## Boundary

Text and table facts are extracted by
[`../objectives/analysis/source_extraction.py`](../objectives/analysis/source_extraction.py)
for a confirmed Objective. The former text-window and table-batch mention
contracts, complete fact bundle, and their benchmark have been removed.

Table repair changes parsed layout, not scientific values. It does not own
Objective confirmation, versioned analysis, Finding synthesis, HTTP schemas,
or persistence implementations.
