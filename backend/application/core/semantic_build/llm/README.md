# Core Semantic Build LLM

This package owns the Core-side LLM contract for semantic build.

It defines the prompt text, structured schemas, and extractor orchestration
used to turn Source structural artifacts into Core semantic extraction inputs
for `document_profiles` and `paper_facts`.

It does not own:

- Source structural artifact production
- Core artifact materialization, deduplication, or persistence
- downstream comparison, report, graph, or protocol projection

## Local Components

- `prompts.py`
  prompt builders for document-profile, text-window, and table-row extraction
- `schemas.py`
  structured response models for the Core extraction contract
- `extractor.py`
  provider call orchestration and response parsing for the Core extraction path

## Local Docs

- [`docs/structured-extraction/README.md`](docs/structured-extraction/README.md)
  live plan family for the structured-extraction cutover, boundary cleanup,
  and prompt-hardening work under this package
