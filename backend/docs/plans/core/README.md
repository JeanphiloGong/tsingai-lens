# Core Plans

This family owns backend plans for the Core research-fact backbone: artifact
stabilization, parsing and evidence quality, traceback reviewability, and
domain-semantic backfill.

## Reading Order

- [`core-stabilization-and-seam-extraction-plan.md`](core-stabilization-and-seam-extraction-plan.md)
  Earlier stabilization wave for the shared parsing seam
- [`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md)
  Current Core quality hardening wave
- [`target-centric-collection-extraction-plan.md`](target-centric-collection-extraction-plan.md)
  Core plan for discovering multiple collection research targets, running
  independent target processes, and extracting target-scoped facts
- [`research-objective-domain-model-plan.md`](research-objective-domain-model-plan.md)
  First implementation slice for adding pure Core domain objects before
  objective discovery services and artifacts
- [`pbf-metal-extraction-and-comparison-validation/README.md`](pbf-metal-extraction-and-comparison-validation/README.md)
  Topic family for the PBF-metal validation wave, including the proposal,
  parameter-registry and report-scope note, and executable implementation plan
- [`../../../application/core/semantic_build/llm/docs/structured-extraction/README.md`](../../../application/core/semantic_build/llm/docs/structured-extraction/README.md)
  Node-local LLM structured-extraction plan family for cutover, boundary
  cleanup, and prompt hardening under the owning Core package
- [`core-semantic-build-packaging-alignment-plan.md`](core-semantic-build-packaging-alignment-plan.md)
  Child implementation plan for packaging the Source-to-Core semantic build
  slice into one explicit Core-owned submodule
- [`core-text-window-atomic-mentions-plan.md`](core-text-window-atomic-mentions-plan.md)
  Child implementation plan for narrowing text-window extraction to atomic
  mentions plus deterministic backend binding
- [`core-benchmark-script-consolidation-plan.md`](core-benchmark-script-consolidation-plan.md)
  Child implementation plan for moving Core benchmark probes into one
  repo-owned backend benchmark directory
- [`document-profile-lightweight-triage-plan.md`](document-profile-lightweight-triage-plan.md)
  Child plan for narrowing `document_profiles` to lightweight triage with
  enum-stable routing outputs
- [`claim-traceback-navigation-implementation-plan.md`](claim-traceback-navigation-implementation-plan.md)
  Core traceback vertical slice for reviewable evidence grounding
- [`minimal-core-domain-backfill-plan.md`](minimal-core-domain-backfill-plan.md)
  Backfill stable Core research semantics into `backend/domain/`
- [`core-api-pandas-retirement-plan.md`](core-api-pandas-retirement-plan.md)
  Remove pandas from Core/API runtime paths while leaving Source parser
  internals as the temporary allowed pandas boundary

## Comparable-Result Family

- Current architecture authority:
  [`../../architecture/core-comparison/README.md`](../../architecture/core-comparison/README.md)
- Historical rollout lineage:
  [`../historical/comparable-result/README.md`](../historical/comparable-result/README.md)

## Boundary Rule

Keep artifact-quality and research-semantic work here. If a wave primarily
changes graph, reports, or protocol as downstream views, move it to
`../derived/`.
