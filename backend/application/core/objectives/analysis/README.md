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
6. Evidence materialization and cross-paper Finding synthesis remain in their
   existing owners until their responsibility slices move here.

`source_screening.py` owns complete Source-unit accounting, bounded framing
batches, prompt preflight, model/repaired/fallback dispositions, and frame
aggregation. Later stages may consume a frame, but they may not reinterpret a
screening decision as scientific Evidence.

`evidence_routing.py` owns transient route records, Source-tree candidate
ordering, model or deterministic route decisions, selection hints, and the
document round-robin extraction queue. It preserves Source identity and cannot
redirect a route to another paper or Source.

`source_extraction.py` owns the inspection of one exact Source at a time. It
passes every schema-valid model draft directly to `source_validation.py` before
updating the accepted state supplied to the next Source prompt. Provider or
irrecoverable structured-output failures remain technical failed drafts.

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

Technical JSON parsing, provider retries, prompt schemas, and token accounting
support this process but do not define its scientific order.
