# Core Semantic Build

This package consumes normalized Source artifacts and produces Core semantic
artifacts.

- `document_profile_service.py`
  LLM-structured document typing, protocol suitability, and collection
  summaries
- `paper_facts_service.py`
  semantic extraction for evidence anchors, method facts, variants, test
  conditions, baselines, and measurement results
- `core_semantic_version.py`
  manifest-based invalidation for Core semantic artifacts
- [`llm/README.md`](llm/README.md)
  Core-owned prompt, schema, extractor, and structured-extraction plan
  contracts
