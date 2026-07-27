# Research Objective First

Research-objective analysis is now implemented by one versioned Core aggregate:

```text
ResearchObjective
  -> ObjectiveAnalysis
     -> PaperContribution
     -> ObjectiveEvidence
     -> Finding
        -> Relation / Context / Derivation
```

This directory no longer owns an implementation plan. Its earlier plan pages
were removed after the direct aggregate cutover because their model and
persistence assumptions no longer matched the runtime contract.

## Current Authorities

- [`../../../../application/core/README.md`](../../../../application/core/README.md)
  Current Core application ownership and runtime flow
- [`../../../../application/core/semantic_build/README.md`](../../../../application/core/semantic_build/README.md)
  Objective-scoped evidence extraction and Finding synthesis
- [`../../../architecture/persistence-model.md`](../../../architecture/persistence-model.md)
  PostgreSQL aggregate identity, versioning, and publication rules
- [`../../../specs/api.md`](../../../specs/api.md)
  Browser-facing Objective, Finding, Evidence, and review API contract
- [`../../../../../docs/contracts/research-objective-workspace-contract.md`](../../../../../docs/contracts/research-objective-workspace-contract.md)
  Shared product contract for the Objective workspace

New changes should update the owning current-state document above instead of
adding another plan authority in this directory.
