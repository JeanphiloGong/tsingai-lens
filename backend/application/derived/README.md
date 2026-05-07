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
- `material_review_report_service.py`
- `material_review_pipeline.py`
  staged material-review generation pipeline that builds a deterministic data
  pack, plans an outline, writes section-scoped drafts, binds evidence, reviews
  and revises sections, then integrates Markdown appendices before PDF rendering
- `material_review_report_service.py`
  AI-assisted material review drafts derived from the material research-view
  context pack, with pipeline artifact persistence, evidence-id validation, and
  Markdown/PDF artifacts
- `protocol/`
  Conditional protocol branch derived from Source artifacts and Core readiness
