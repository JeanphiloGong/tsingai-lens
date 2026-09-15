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

## Candidate Question Evaluation

`ObjectiveCandidateService.propose_candidate_questions()` is an explicitly
invoked, nonpersistent evaluation path. Default discovery still calls
`discover_candidate_facts()` and its existing axis-equivalence grouping.
Neither the HTTP workflow nor Agent tools call the evaluation method.

Consider three papers on one alloy's porosity: A varies laser power, B varies
scan speed, and C varies both. They can motivate one reading question without
sharing an identical experimental design. The evaluation reads supplied maps
and original excerpts, proposes up to three questions, and retains each selected
paper's relevance reason, limitations, original map, and cited Source text.
Power and speed remain different factors; C remains a joint-factor study.
Missing map relationships do not veto relevance supported by original passages.

`question_formation.py` owns the prompt and direct `*ModelOutput` contracts.
The candidate service binds returned document/Source pairs to supplied text;
the model does not reproduce quotations. Its application result reuses
`ResearchObjective` and `PaperResearchMap` rather than changing domain records.
Inspection papers populate question `seed_document_ids`; background selections
are retained separately. These are reading leads, not Evidence, validated
comparability, or a frozen analysis scope. No relationship equivalence is inferred
from selection, and no new `source_relationship_ids` are invented.

Input is limited to 12 prepared papers and a 32,000-token prompt budget. Oversized
input is rejected rather than silently dropping papers or text. One structured
request uses an 8,192-token output budget by default, with no schema repair,
subdivision, or hidden SDK retries. Technical and reference failures propagate
with model-call traces; a valid empty proposal needs an abstention explanation.
Callers must supply authorized paper snapshots and original excerpts.

The evaluation can omit research interest for automatic exploration. Replacing
default discovery and deciding how reviewed reading selections enter scope
screening remain separate decisions. Current scope screening still has its
existing complete-variable matching behavior; this evaluation does not bypass
it or claim end-to-end analysis readiness.
