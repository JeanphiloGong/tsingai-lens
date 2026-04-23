# Derived Application Layer

This package owns downstream views that consume Core outputs.

- `graph_service.py`
  Core-derived graph read model and GraphML export
- `graph_projection_service.py`
  Graph projection from document profiles, evidence cards, and the Core-owned
  comparison-row read model projected from semantic/scope artifacts
- `report_service.py`
  Core-pattern reports derived from the comparison backbone via the Core-owned
  comparison-row read model rather than direct row-cache reads
- `protocol/`
  Conditional protocol branch derived from Source artifacts and Core readiness
