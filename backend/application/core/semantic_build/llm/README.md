# Core Semantic Build LLM

This package owns the Core-side LLM contract for semantic build.

It defines the prompt text, structured schemas, and extractor orchestration
used to turn Source structural artifacts into Core semantic extraction inputs
for `document_profiles`, `research_objectives`, objective evidence units, and
`paper_facts`. It also owns the final confirmed-goal Finding synthesis prompt:
one structured call compares the bounded, relationship-bucketed evidence
ledger and returns evidence-bound agreement, conflict, condition-dependent, or
insufficient-confirmation Findings.

It does not own:

- Source structural artifact production
- Core artifact materialization, deduplication, or persistence
- downstream comparison, report, graph, or protocol projection

## Local Components

- `prompts.py`
  prompt builders for document-profile, objective, text-window, table-row, and
  goal-level Finding synthesis
- `schemas.py`
  structured response models for the Core extraction contract
- `extractor.py`
  provider call orchestration and response parsing for the Core extraction path

The goal-level synthesis is not a paper-Finding aggregation stage. Candidate
papers have already been traversed before this call; the model receives
eligible direct-result units grouped by exact source axes and target property,
with source-document provenance retained inside each relationship bucket, and
directly produces final Findings. Only cited `direct_result` units count toward
`paper_count`. The backend requires an explicit source axis and target property
and grants eligibility only to `high` or `medium`
`primary_experiment`/`mixed` paper frames; low-relevance and background papers
remain visible as traversal context but cannot independently support a Finding.

The default extraction mode is `provider_parse`, which uses the configured
OpenAI-compatible provider's structured parse endpoint. Set
`CORE_LLM_EXTRACTION_MODE=json_text` only when the provider does not support
structured parsing and the caller accepts local JSON text parsing risk.

## Local Docs

- [`docs/structured-extraction/README.md`](docs/structured-extraction/README.md)
  live plan family for the structured-extraction cutover, boundary cleanup,
  and prompt-hardening work under this package
