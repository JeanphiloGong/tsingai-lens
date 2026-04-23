# Comparable Result Historical Plans

This family keeps the retained lineage behind the current comparable-result
substrate.

These pages explain how the backend moved from row-centered comparison plans to
the current `ComparableResult` plus `CollectionComparableResult` model. They are
not the current source of truth.

## Start Here

- [`../../../architecture/core-comparison/README.md`](../../../architecture/core-comparison/README.md)
  Current architecture entry for the accepted semantic center and implemented
  substrate

## Retained Lineage

- [`core-comparable-result-domain-model-plan.md`](core-comparable-result-domain-model-plan.md)
  Origin decision plan that corrected the comparison-semantic center
- [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
  Retained rollout roadmap across persistence, read-path, policy, and retrieval
  waves
- [`core-comparable-result-phase1-persistence-split-plan.md`](core-comparable-result-phase1-persistence-split-plan.md)
  Historical storage split wave
- [`core-comparable-result-phase1-read-path-cutover-plan.md`](core-comparable-result-phase1-read-path-cutover-plan.md)
  Historical collection-first read-path cutover wave
- [`core-comparable-result-phase1-service-boundary-plan.md`](core-comparable-result-phase1-service-boundary-plan.md)
  Historical ownership-split wave for the phase 1 rollout
- [`core-comparable-result-phase2-document-first-semantic-inspection-plan.md`](core-comparable-result-phase2-document-first-semantic-inspection-plan.md)
  Historical document-first inspection wave
- [`core-comparable-result-phase2-policy-lifecycle-plan.md`](core-comparable-result-phase2-policy-lifecycle-plan.md)
  Historical policy-metadata and reassessment wave
- [`core-comparable-result-phase3-corpus-retrieval-plan.md`](core-comparable-result-phase3-corpus-retrieval-plan.md)
  Historical corpus retrieval wave

## Rule

Do not start new current-state interpretation from this family. Use it only for
lineage, migration rationale, or superseded rollout detail.
