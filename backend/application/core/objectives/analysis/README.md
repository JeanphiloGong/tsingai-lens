# Objective Analysis

This package owns the research work performed after a user confirms one
`ResearchObjective`.

Read the analysis responsibilities in real research order:

1. `source_screening.py` decides which Source units require inspection for the
   confirmed question. Its `PaperAnalysisFrame` is transient screening state,
   not proof that a paper contains usable Evidence.
2. `evidence_routing.py` turns screened Source units into the transient
   inspection queue consumed by Source-local fact extraction. A route is an
   instruction to inspect a Source, not a scientific finding.
3. `source_extraction.py` inspects each routed Source and produces transient,
   source-local `ExtractedEvidenceDraft` records. It owns text and table payload
   construction, structural table repair, deterministic table parsing, model
   extraction, and route-scoped technical failures.
4. `source_validation.py` immediately checks each model-authored draft against
   the exact Source being inspected. Unsupported results abstain; supported
   results with incomplete variable or comparison support become descriptive
   drafts before they can enter the next Source prompt's document state.
5. `paper_experiment.py` runs after all routed Sources have been inspected. It
   fills only missing scope from the same paper, binds Methods and Results only
   through exact sample identities, and derives bounded pairwise comparisons.
6. `evidence_materialization.py` turns reconstructed drafts into durable
   `ObjectiveEvidence`, resolves duplicate candidates by stable Source identity,
   and derives each paper's `PaperContribution` from that final Evidence set.
7. `finding_synthesis.py` groups durable Evidence into backend-owned result
   sets, asks the bounded assertion judge only for claim strength and supported
   context, and publishes traceable cross-paper `Finding` records.

`source_screening.py` owns complete Source-unit accounting, bounded framing
batches, the screening prompt and response schema, prompt preflight, bounded
repair, model/repaired/fallback dispositions, and frame aggregation. Its
`ObjectiveSourceScreener` performs only the current bounded relevance judgment.
Later stages may consume a frame, but they may not reinterpret a screening
decision as scientific Evidence.

`evidence_routing.py` owns transient route records, Source-tree candidate
ordering, selection hints, the bounded routing prompt and response schema, the
one-Source model call, deterministic fallback, and the document round-robin
extraction queue. The model decides only whether and how to inspect the current
Source; the backend preserves its identity, so a route cannot redirect work to
another paper or Source or become durable Evidence.

`source_extraction.py` owns the inspection of one exact Source at a time. It
owns that judgment's prompt, response schema, scientific validation, bounded
repair instructions, completion budget, and direct model call. It passes every
schema-valid model draft directly to `source_validation.py` before updating the
accepted state supplied to the next Source prompt. Provider or irrecoverable
structured-output failures remain technical failed drafts. Shared provider
invocation, JSON parsing, usage accounting, and trace capture stay outside this
scientific responsibility.

`source_validation.py` owns deterministic source-local acceptance, demotion,
or abstention. It checks the reported result, comparison labels, changed
variables, and scientific context independently and records which field
families each Source supports. It does not call the model or bind information
from another Source.

`paper_experiment.py` owns same-document reconstruction after Source inspection
finishes. It may join process conditions from Methods to a result only when the
baseline and target sample identities resolve unambiguously inside that paper.
Missing or conflicting identities remain descriptive, and no cross-document
binding is allowed.

`evidence_materialization.py` owns the trust boundary from transient paper
facts to durable Evidence. It keeps the confirmed Objective's result details,
canonicalizes uniquely matching axes, resolves exact Source excerpts and
related locators, and retains at most one winner for each Objective, document,
Source kind, and Source ref. `PaperContribution` route, extracted, failed, and
comparable counts are computed from that same final Source-keyed set. It does
not persist artifacts or synthesize a cross-paper claim.

`finding_synthesis.py` owns cross-paper comparison after durable Evidence and
paper outcomes exist. `FindingSynthesisService` deterministically selects
comparable Evidence, constructs atomic factor/outcome result sets, balances the
bounded model input across papers, assigns all supporting and opposing Evidence,
and derives the published statement, status, certainty, limitations, identity,
and provenance. `FindingAssertionJudge` decides only assertion strength and
optional context or mechanism annotations for one backend-owned result set. It
cannot change result-set membership, scientific direction, Evidence bindings,
or any published Finding identity.

Technical JSON parsing, provider retries, usage accounting, and trace capture
live in `llm/structured_response.py`; they support this process but do not
define its scientific order.
