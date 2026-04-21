# Core Plans

This family owns backend plans for the Core research-fact backbone: artifact
stabilization, parsing and evidence quality, traceback reviewability, and
domain-semantic backfill.

## Reading Order

- [`core-stabilization-and-seam-extraction-plan.md`](core-stabilization-and-seam-extraction-plan.md)
  Earlier stabilization wave for the shared parsing seam
- [`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md)
  Current Core quality hardening wave
- [`core-llm-structured-extraction-hard-cutover-plan.md`](core-llm-structured-extraction-hard-cutover-plan.md)
  Child implementation plan for hard-cutting Core semantic extraction to
  schema-bound LLM parsing
- [`core-semantic-build-packaging-alignment-plan.md`](core-semantic-build-packaging-alignment-plan.md)
  Child implementation plan for packaging the Source-to-Core semantic build
  slice into one explicit Core-owned submodule
- [`core-llm-structured-extraction-id-boundary-plan.md`](core-llm-structured-extraction-id-boundary-plan.md)
  Child implementation plan for removing backend/internal identifiers from the
  Core LLM extraction contract and moving identity resolution back into the
  backend
- [`document-profile-lightweight-triage-plan.md`](document-profile-lightweight-triage-plan.md)
  Child plan for narrowing `document_profiles` to lightweight triage with
  enum-stable routing outputs
- [`claim-traceback-navigation-implementation-plan.md`](claim-traceback-navigation-implementation-plan.md)
  Core traceback vertical slice for reviewable evidence grounding
- [`minimal-core-domain-backfill-plan.md`](minimal-core-domain-backfill-plan.md)
  Backfill stable Core research semantics into `backend/domain/`
- [`core-comparable-result-domain-model-plan.md`](core-comparable-result-domain-model-plan.md)
  Child plan for re-centering comparison semantics on `ComparableResult`,
  treating collection as scope, and demoting `ComparisonRow` to projection
- [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
  Child roadmap plan for persistence, identity, policy, read-path, and
  projection-cache evolution after the comparable-result model decision

## Boundary Rule

Keep artifact-quality and research-semantic work here. If a wave primarily
changes graph, reports, or protocol as downstream views, move it to
`../derived/`.
