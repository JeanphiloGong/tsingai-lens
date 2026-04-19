# Source Plans

This family owns backend plans for the Source layer: collection construction,
ingestion, runtime preparation, parser quality, and retirement of historical
GraphRAG-era Source seams.

## Reading Order

- [`source-collection-builder-normalization-plan.md`](source-collection-builder-normalization-plan.md)
  Normalize the collection-builder and import handoff seam
- [`source-residual-graphrag-retirement-plan.md`](source-residual-graphrag-retirement-plan.md)
  Retire residual GraphRAG-shaped Source runtime and indexing logic
- [`source-parser-evaluation-plan.md`](source-parser-evaluation-plan.md)
  Evaluate parser routes against the fixed Source handoff contract
- [`born-digital-source-parser-first-plan.md`](born-digital-source-parser-first-plan.md)
  Cut the active Source runtime over to a parser-first born-digital path
- [`retrieval-package-retirement-plan.md`](retrieval-package-retirement-plan.md)
  Finish retirement of the historical `backend/retrieval/` package after
  Source runtime cutover

## Boundary Rule

Keep parser, runtime, ingestion, and handoff-contract waves here. Move a plan
to `backend-wide/` only when it freezes backend-wide contracts rather than the
Source seam itself.
