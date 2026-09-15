# Objective Discovery

This package helps a researcher form candidate questions from prepared papers.
It does not own confirmed-Objective Evidence analysis. A mapped relationship
describes a paper's stated research scope, not a validated effect.

## Reading Flow

A researcher exploring how processing affects an alloy first reads the abstract,
conclusions, and high-level captions together. If these name a varied parameter
but do not establish its measured response, the researcher opens relevant
Methods or Results passages and reads them with the original context. Different
experiments, fixed settings, and cited work must not become one invented
factor-to-outcome relationship.

The implementation follows that reading sequence:

1. `../paper_map_sources.py` selects high-level Sources and keeps their original
   text and section paths together when the complete prompt fits the token
   budget. It splits only oversized input, preserving stable Source references
   and distinct fragment identities.
2. `paper_understanding/workflow.py` makes one bounded reading judgment.
   Experimental papers yield explicit research relationships and unresolved
   scope; reviews yield review-author synthesis, disputes, gaps, and citation
   leads. Full experiment reconstruction remains downstream.
3. `../paper_research_map_service.py` consolidates the reading and, when scope
   remains incomplete, schedules relevant passages alongside the original
   unresolved context using the same extractor. It permits at most three
   expansion rounds and 24 new Sources. Identical or subset-only rereading is
   skipped because it adds no information. Reading can stop with uncertainty.
4. `axis_equivalence.py` classifies backend-proposed terminology pairs.
   `../objective_candidate_service.py` groups compatible paper relationships
   into candidate questions. The researcher decides which question to pursue.

Source selection remains bounded. A sufficient map supports navigation and
candidate discovery; it does not establish full-paper coverage, comparability,
or a Finding.

## Ownership

`paper_understanding/paper_map_outputs.py` owns the direct `*ModelOutput`
contracts. `paper_map_results.py` owns normalized results with backend-bound
Source identities. The model sees short labels, section paths, and scientific
content; it cannot invent Collection, Document, or Source identities.

Unresolved signals guide further reading. There is no separate signal-pairing
model, distance-based candidate pairing, or compact single-Source fallback.
The original passages, not a list of previously extracted labels, supply the
authority for a new relationship.

`../paper_map_extraction.py` owns token preflight, bounded transport recovery,
and Source coverage. `../llm/structured_response.py` owns
provider calls, JSON handling, traces, usage, and token accounting. Each actual
provider attempt consumes the document budget, including repair and provider
fallback; budgeted calls disable hidden SDK retries and use the remaining
document deadline.

A transport failure can retry the same reading once. Invalid or truncated
output does not trigger recursive subdivision or a different scientific task.
Valid bounded output retains supported relationships even when some scope was
omitted, with incomplete coverage. An overflowing joint factor set is omitted
as a whole, never shortened into a different relationship. Failures in later
reading do not erase earlier supported relationships.

Persisted Paper Map and public API shapes are unchanged. The map policy
fingerprint invalidates reuse of old-policy maps on the next requested map
build; it does not delete saved data.

For model/result responsibilities, see
[`paper_understanding/README.md`](paper_understanding/README.md).
