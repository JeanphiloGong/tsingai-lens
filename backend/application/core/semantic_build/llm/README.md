# Core Semantic Build LLM

This package owns the Core-side LLM contract for semantic build.

It defines the prompt text, structured schemas, and extractor orchestration
used to turn Source structural artifacts into Core semantic extraction inputs
for `document_profiles`, `research_objectives`, objective evidence units, and
`paper_facts`. It also owns the final confirmed-goal Finding synthesis prompt.
One structured call compares bounded transient result sets and returns
evidence-bound agreement, conflict, condition-dependent, or
insufficient-confirmation Findings. Each returned Finding has one source
concept and `outcomes[]`, so one controlled process contrast can retain several
measured results without being split into unrelated conclusions.

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
papers have already been traversed before this call. The model receives
eligible direct-result units aligned by exact process conditions, with
source-document provenance retained inside each result set, plus separately
bounded condition and mechanism context. Each outcome must cite its own direct
evidence-unit ids; condition and mechanism ids are returned in their dedicated
fields. The backend reorients reverse-stored comparisons, removes dominated
contrasts, validates model numbers against selected evidence, and calibrates a
Finding statement back to the aligned direct results when needed. Prompt v11
asks for structural results before performance results, keeps narrow-range
regime qualifications out of the headline effect, and makes a one-paper
boundary explicit. The backend also collapses duplicate model candidates that
cite the same direct-result unit set. If the model omits context, calibration
may restore only same-document qualification or mechanism units that explicitly
match a selected outcome. Only cited `direct_result` units count toward
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
