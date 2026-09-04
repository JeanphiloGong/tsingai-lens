# Backend Research Layers

## Summary

Lens supports paper-first and question-first research while preserving one
evidence-backed Core. The layers are:

1. Goal Brief
2. Collection and Document Source
3. Research Intelligence Core
4. Goal Consumer and expert decision
5. Derived views and follow-up work

## Layer Responsibilities

### Goal Brief

Captures what the researcher wants to decide, the material/process/outcome
scope, constraints, and uncertainty. It may create an empty Collection or draft
an Objective. It cannot claim Evidence or a Finding.

### Collection and Document Source

A Collection assembles papers. Each Document independently owns its current
bytes, preparation task, Source structure, coarse Profile, and lightweight Paper
Map. Adding one paper does not rebuild existing papers.

### Research Intelligence Core

The Core receives an explicit selection of ready Documents. It forms or accepts
an Objective, extracts Source-local facts, reconstructs within-paper
experiments, preserves non-comparability, and synthesizes published Findings
only from grounded Evidence.

### Goal Consumer and expert decision

The researcher reviews Findings, exact Evidence, conflicts, gaps, and limits.
The Agent may organize these records and propose next Objectives, but user
approval controls Objective creation and analysis start.

### Derived views and follow-up

Comparison pages, Evidence Maps, exports, and experiment plans consume the same
published Objective analysis. They do not create another scientific truth.

## Two Entry Paths

Paper-first exploration:

```text
upload papers
  -> independently prepare papers
  -> select ready papers
  -> discover Objective candidates
  -> user confirms one
  -> analyze selected papers
```

Question-first work:

```text
researcher question
  -> Objective candidate
  -> inspect/select relevant ready papers
  -> user confirms exact scope
  -> analyze selected papers
```

Both paths converge on the same ObjectiveAnalysis, Evidence, and Finding
records.

## Invariants

- Relevance means a paper should be inspected, not that it proves an outcome.
- Paper Map relationships are proposal context, not Evidence.
- Source/Profile/PaperMap belong to one Document.
- Objective scope is explicit and records preparation fingerprints.
- Evidence must be grounded in the cited Source before normalization or
  comparison.
- Explicit Source claims about jointly varied factors remain joint effects;
  deterministic row-derived multi-factor contrasts remain association-only.
- Missing or incompatible conditions remain visible.
- Provider failure is technical failure, not scientific absence.

## Related Docs

- [`overview.md`](overview.md)
- [`domain-architecture.md`](domain-architecture.md)
- [`../specs/api.md`](../specs/api.md)
- [`../../../docs/architecture/lens-v1-architecture-boundary.md`](../../../docs/architecture/lens-v1-architecture-boundary.md)
