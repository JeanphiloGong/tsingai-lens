# Core Application Layer

This package owns the research-fact backbone produced from normalized Source
artifacts.

- `document_profile_service.py`
  LLM structured document typing, protocol suitability, and collection summaries
- `evidence_card_service.py`
  facts-first extraction and materialization for evidence anchors, method
  facts, sample/result/condition/baseline facts, plus derived evidence-card
  projections
- `comparison_service.py`
  deterministic comparison-row generation and comparability evaluation from
  paper facts
- `workspace_overview_service.py`
  Collection-facing overview assembled from Source state and Core artifacts
