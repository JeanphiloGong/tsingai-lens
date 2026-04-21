# Derived Application Layer

This package owns downstream views that consume Core outputs.

- `graph_service.py`
  Core-derived graph read model and GraphML export
- `graph_projection_service.py`
  Graph projection from document profiles, evidence cards, and
  `comparison_rows.parquet` projection cache during comparable-result Phase 1
- `report_service.py`
  Core-pattern reports derived from the comparison backbone and still reading
  row projection cache during comparable-result Phase 1
- `protocol/`
  Conditional protocol branch derived from Source artifacts and Core readiness
