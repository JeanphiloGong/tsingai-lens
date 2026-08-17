# Objective Discovery

This package owns the scientific judgments used before a researcher confirms a
collection Objective. It does not own confirmed-Objective Evidence analysis.

## Reading Order

1. `study_window.py` inspects one bounded group of Source units and returns the
   studies, relationships, and unresolved signals supported by those Sources.
2. `paper_skim_service.py` in the parent package batches all Sources, retries
   failed batches, and consolidates window results into one paper map.
3. `signal_reconciliation.py` decides whether compatible signals found in
   different windows belong to the same within-paper experiment.
4. `objective_candidate_service.py` in the parent package groups compatible
   paper relationships into collection-level Objective candidates.

## Ownership

`study_window.py` and `signal_reconciliation.py` each keep one model judgment's
prompt, response schema, validation, repair policy, token bounds, and call next
to each other. `extraction.py` in the parent package provides only the shared
provider, structured JSON, trace, usage, and token-counting mechanics.

Source batching, recursive failed-batch subdivision, stable Source identity,
paper-wide coverage, study consolidation, and persistence remain outside these
model contracts. A valid model response is therefore an input to discovery,
not proof that a collection Objective or durable Evidence exists.
