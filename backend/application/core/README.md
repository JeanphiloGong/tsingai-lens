# Core Application Layer

This package owns scientific interpretation after one Document has parseable
Source artifacts. It does not own Collection membership, file storage, task
admission, or Agent conversation.

## Document Preparation

For one Document:

```text
SourceDocument
  -> DocumentProfile
  -> PaperMap
```

`document_profiles/service.py` classifies the paper for research triage.
`objectives/paper_research_map_service.py` creates one bounded
`PaperResearchMap` that describes paper role, material and process themes,
variable-to-outcome research axes, review synthesis, gaps, Source lineage, and
uncertainty. It cannot represent samples, tests, comparators, fixed conditions,
parameter levels, or measurements. The map is a navigation and proposal input,
not proven Evidence.

## Objective Discovery

```text
explicit ready document_ids
  -> current Profiles and Paper Maps
  -> candidate Objectives
```

Discovery never chooses hidden Collection scope and never prepares papers. The
caller supplies the exact ready Documents. The stored discovery result records
their `(document_id, preparation_fingerprint)` inputs.

## Objective Analysis

```text
confirmed Objective + explicit ready document_ids
  -> freeze PreparedDocumentInput values
  -> frame each paper, using its map only as a navigation prior
  -> route likely Sources
  -> extract and ground Source-local facts
  -> reconstruct within-paper experiments
  -> compare compatible results across papers
  -> publish Findings and Evidence
```

Analysis checks that every frozen fingerprint still equals the current prepared
Document before work begins. It records excluded, failed, descriptive, and
non-comparable papers instead of turning technical success into scientific
support. Source-local facts inspected after Objective confirmation are the only
inputs allowed to reconstruct experiment context or create Evidence.

## Owners

- `document_profiles/`: document-level type and warning profile.
- `objectives/paper_research_map_service.py`: lightweight Paper Map construction.
- `objectives/objective_candidate_service.py`: candidate formation from selected
  Paper Maps.
- `objectives/research_objective_service.py`: selected-input loading and
  scientific analysis orchestration.
- `objectives/analysis_service.py`: version allocation, background dispatch,
  publication state, and reads.
- `objectives/analysis/`: framing, routing, extraction, grounding, paper-level
  experiment binding, and cross-paper Finding synthesis.
- `paper_facts/`: extraction helpers used inside Objective analysis, including
  deterministic table repair; it is not a persisted paper-fact aggregate.
