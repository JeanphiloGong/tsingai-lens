# Objective Discovery

This package owns the scientific judgments used before a researcher confirms a
collection Objective. It does not own confirmed-Objective Evidence analysis.

## Reading Order

1. `study_window.py` maps one bounded group of high-level Source units into the
   paper-owned material, intervention, and outcome axes that can support an
   Objective candidate. A returned relationship describes stated research
   scope, not a validated effect or comparable experiment. If structured
   mapping fails after subdivision reaches one Source, the compact contract
   retains only explicit axes for bounded reconciliation. Review papers retain
   only synthesis explicitly authored by the review; individually cited
   experiments remain leads back to primary literature. The backend binds
   Source identity. One high-level experimental study may retain up to six
   explicitly linked factor-to-outcome relationships so that a dense abstract
   or conclusion does not silently lose a stated research axis.
2. `paper_research_map_service.py` in the parent package selects how a
   researcher reads before choosing a question: bounded abstract, conclusion or
   summary, overview, and table/figure caption Sources. The initial pass excludes
   detailed Methods, Results text, and table rows. If the map is incomplete, the
   service spends a bounded 24-Source expansion budget over relevant Methods or
   Results Sources and captions. It prioritizes Sources that mention unresolved
   concrete metrics, repeats the highest-value reading step, and stops early
   when a round adds no new scope. It still does not reconstruct table rows or
   experiment details. The paper map therefore records that a result axis
   exists without reconstructing detailed table structure or values; those
   rows are read only after the researcher confirms an Objective. The
   service groups the selected Sources by broad reading role, retries technical
   failures under one small per-paper budget, and consolidates the results into
   one paper map.
3. `signal_reconciliation.py` decides whether compatible incomplete signals
   found in different high-level windows describe the same paper-owned research
   scope. It does not reconstruct experiment conditions or results.
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
the former maps explicitly linked paper-scope axes, while the latter screens
only explicit variable and outcome signals. Neither reconstructs samples,
controls, fixed conditions, test settings, or measurement values. Review
`PaperResearchMap` retains only review-author synthesis; individually cited
studies are primary-literature navigation leads and do not become map scopes or
signals.
`llm/structured_response.py` provides only the shared provider, structured JSON,
trace, usage, and token-counting mechanics.

Source selection, batching, recursive failed-batch subdivision, stable Source
identity, selected-Source coverage, scope consolidation, and persistence remain
outside these model contracts. A valid model response is therefore an input to
discovery, not proof that a collection Objective or durable Evidence exists.
The model sees each selected Source only as a short window-local label plus its
section path and scientific content. Collection, Document, window, Source, and
parser identities remain backend-owned and are rebound after model validation.
The backend also enforces paper ownership: a primary research paper may retain
supported `current_work`, while a review retains only `synthesis`. Explicit
numbered citations, named prior authors, generic background, and ambiguous
ownership are discarded from review discovery and require inspection of the
primary Source before they can support an experiment relationship.
