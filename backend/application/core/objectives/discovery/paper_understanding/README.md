# Paper Understanding

This package owns the paper-level understanding step before a researcher
confirms an Objective. It maps bounded Source windows to paper-stated research
scope; it does not extract experimental measurements or create Findings.

## Files

- `common.py`
  Owns shared Paper Map limits, bounded-list handling, warnings, and the base
  Pydantic response contract.
- `paper_map_outputs.py`
  Defines the direct `*ModelOutput` contracts returned by the LLM, including
  their window-local nested objects and Source labels.
- `paper_map_results.py`
  Defines the Source-bound, normalized Paper Map results consumed by discovery,
  including identity checks.
- `normalization.py`
  Owns the explicit conversion that downgrades an unsupported relationship to
  an unresolved, Source-linked signal before result validation.
- `workflow.py`
  Builds the paper-understanding prompts, validates and repairs bounded model
  output, binds window-local Source labels to backend Source identities, and
  returns the normalized `StructuredPaperResearchMap`.

## Boundary

`paper_map_sources.py` chooses which Sources to inspect. The parent discovery
services aggregate paper maps and generate Objective candidates. Confirmed
Objective Evidence extraction and Finding synthesis remain downstream and are
not owned by this package.
