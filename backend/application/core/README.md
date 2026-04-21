# Core Application Layer

This package owns the research-fact backbone produced from normalized Source
artifacts.

- `semantic_build/`
  Source-artifact consumption and Core semantic build for document profiles,
  paper facts, prompt/schema ownership, and Core semantic version invalidation
- `comparison_service.py`
  deterministic comparable-result assembly, collection-scoped comparability
  evaluation, and collection-first comparison-row projection from
  `collection_comparable_results` plus `comparable_results`
- `workspace_overview_service.py`
  Collection-facing overview assembled from Source state and Core artifacts
