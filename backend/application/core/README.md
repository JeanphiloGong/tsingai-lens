# Core Application Layer

This package owns the research-fact backbone produced from normalized Source
artifacts.

- `document_profile_service.py`
  LLM structured document typing, protocol suitability, and collection summaries
- `evidence_card_service.py`
  LLM structured extraction for evidence/sample/result/test/baseline artifacts
- `comparison_service.py`
  Deterministic comparison-row generation and comparability evaluation
- `workspace_overview_service.py`
  Collection-facing overview assembled from Source state and Core artifacts
