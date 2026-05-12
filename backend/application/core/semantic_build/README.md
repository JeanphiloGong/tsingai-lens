# Core Semantic Build

This package consumes normalized Source artifacts and produces Core semantic
artifacts.

- `document_profile_service.py`
  LLM-structured document typing and collection summaries
- `research_objective_service.py`
  collection-level paper skim, research objective, objective context, evidence
  route, evidence-unit, and logic-chain records
- `paper_facts_service.py`
  objective-aware semantic extraction for evidence anchors, method facts,
  variants, test conditions, baselines, and measurement results
- `core_semantic_version.py`
  manifest-based invalidation for Core semantic artifacts
- [`llm/README.md`](llm/README.md)
  Core-owned prompt, schema, extractor, and structured-extraction plan
  contracts
