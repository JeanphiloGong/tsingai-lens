# Objective Analysis

This package owns the research work performed after a user confirms one
`ResearchObjective`.

Read the analysis responsibilities in real research order:

1. `source_screening.py` decides which Source units require inspection for the
   confirmed question. Its `PaperAnalysisFrame` is transient screening state,
   not proof that a paper contains usable Evidence.
2. Evidence routing currently remains in the parent Objective service and will
   move here as the transient queue between screening and Source-local fact
   extraction.
3. Source extraction, validation, within-paper experiment reconstruction,
   Evidence materialization, and cross-paper Finding synthesis currently remain
   in their existing owners until their responsibility slices move here.

`source_screening.py` owns complete Source-unit accounting, bounded framing
batches, prompt preflight, model/repaired/fallback dispositions, and frame
aggregation. Later stages may consume a frame, but they may not reinterpret a
screening decision as scientific Evidence.

Technical JSON parsing, provider retries, prompt schemas, and token accounting
support this process but do not define its scientific order.
