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

The confirmed Objective chain screens and routes Sources, builds a bounded
Source bundle, and uses
[`PaperExperimentExtractor`](../objectives/analysis/paper_experiment_extraction.py)
to extract paper-reported experiments. The former text-window and table-batch
mention contracts, complete fact bundle, and their benchmark have been removed.

Provider-parse output can fall back to bounded JSON-text repair for malformed
JSON, schema rejection, explicit output rejection, or output saturation.
Authentication, transport failures, provider refusals, and programming errors
propagate without a second format-repair request.

Table repair changes parsed layout, not scientific values. It does not own
Objective confirmation, versioned analysis, Finding synthesis, HTTP schemas,
or persistence implementations.
