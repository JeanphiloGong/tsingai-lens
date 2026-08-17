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
   extraction, current Source grounding, and route-scoped technical failures.
4. Within-paper experiment reconstruction, Evidence materialization, and
   cross-paper Finding synthesis remain in their existing owners until their
   responsibility slices move here.

`source_screening.py` owns complete Source-unit accounting, bounded framing
batches, prompt preflight, model/repaired/fallback dispositions, and frame
aggregation. Later stages may consume a frame, but they may not reinterpret a
screening decision as scientific Evidence.

`evidence_routing.py` owns transient route records, Source-tree candidate
ordering, model or deterministic route decisions, selection hints, and the
document round-robin extraction queue. It preserves Source identity and cannot
redirect a route to another paper or Source.

`source_extraction.py` owns the inspection of one exact Source at a time. A
schema-valid model response is still only a draft: unsupported results abstain,
unsupported comparison fields are retained only as descriptive evidence, and
provider or irrecoverable structured-output failures remain technical failed
drafts. Same-paper Methods/Results binding occurs only after this stage.

Technical JSON parsing, provider retries, prompt schemas, and token accounting
support this process but do not define its scientific order.
