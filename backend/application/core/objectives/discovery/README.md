# Objective Discovery

This package owns the scientific judgments used before a researcher confirms a
collection Objective. It does not own confirmed-Objective Evidence analysis.

## Reading Order

1. `study_window.py` inspects one bounded group of Source units and returns the
   studies, relationships, and unresolved signals supported by those Sources.
   If full study reconstruction saturates after subdivision reaches one Source,
   its compact source-signal contract extracts only explicit axes and minimal
   context for later reconciliation. For review papers, this model judgment
   instead screens only scientific synthesis explicitly authored by the review;
   individually cited experiments remain leads back to primary literature. The
   backend binds Source identity.
2. `paper_skim_service.py` in the parent package batches all Sources, retries
   failed batches, invokes compact singleton recovery for recoverable structured
   output failures, and consolidates window results into one paper map. A shared
   per-paper deadline and recovery-call budget bound technical recovery while
   preserving successful windows and explicit coverage for unfinished Sources.
3. `signal_reconciliation.py` decides whether compatible signals found in
   different windows belong to the same within-paper experiment.
4. `axis_equivalence.py` classifies only backend-proposed label pairs as the
   same or different scientific axis.
5. `objective_candidate_service.py` in the parent package applies those pair
   decisions and groups compatible paper relationships into collection-level
   Objective candidates.

## Ownership

`study_window.py`, `signal_reconciliation.py`, and `axis_equivalence.py` each
keep one model judgment's prompt, response schema, validation, repair policy,
token bounds, and call next to each other. The full-window and compact
single-Source contracts in `study_window.py` have different responsibilities:
the former may reconstruct supported study relationships, while the latter may
only screen explicit variable and outcome signals. Review PaperSkim retains
only review-author synthesis; individually cited studies are primary-literature
navigation leads and do not become PaperSkim studies or signals.
`llm/structured_response.py` provides only the shared provider, structured JSON,
trace, usage, and token-counting mechanics.

Source batching, recursive failed-batch subdivision, stable Source identity,
paper-wide coverage, study consolidation, and persistence remain outside these
model contracts. A valid model response is therefore an input to discovery,
not proof that a collection Objective or durable Evidence exists. The backend
also enforces paper ownership: a primary research paper may retain supported
`current_work`, while a review retains only `synthesis`. Explicit numbered
citations, named prior authors, generic background, and ambiguous ownership are
discarded from review discovery and require inspection of the primary Source
before they can support an experiment relationship.
