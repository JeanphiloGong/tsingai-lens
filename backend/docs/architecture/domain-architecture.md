# Backend Domain Architecture

## Purpose

This document records the implemented backend domain boundaries. Code follows
the research process rather than a collection-wide technical build graph.

## Domain Map

### Source

Owns Collection membership and one paper's preparation:

- create, read, and delete Collections;
- upload and list current Documents;
- prepare one Document into Source, Profile, and Paper Map;
- expose per-document task status and failure;
- provide exact Source content for verification.

### Core

Owns scientific records and decisions:

- document triage and Paper Map construction;
- Objective discovery from an explicit ready-paper selection;
- Objective confirmation and versioned analysis;
- per-paper framing, Source routing, extraction, and experiment binding;
- grounded Evidence, comparability, and cross-paper Findings.

Paper Maps are scope/navigation artifacts. Only Objective analysis may publish
Evidence and Findings.

### Chat

Owns Research Agent sessions, ordered messages, typed capability calls,
structured results, and exact approval decisions. It reads and invokes Source
or Core application services; it does not persist another scientific model.

### Goal

Owns initial research brief intake and Objective-scoped experiment plans. Intake
may create an empty Collection, but it does not manufacture evidence.

### Derived views

Frontend comparison and Evidence Map routes read published Objective Findings
and Evidence. They are projections, not alternate conclusion identities.

## Package Shape

```text
controllers/
  source/       Collection, Document, preparation task, Source reference
  core/         Document reads, Objectives, Findings, Evidence, review
  chat/         Research Agent sessions and approval
  goal/         intake and experiment plans

application/
  source/       current Document preparation and Source use cases
  core/         scientific interpretation and Objective analysis
  chat/         Agent loop and capability handlers
  goal/         research brief and plan use cases

domain/
  source/       Collection, Document, Source, Task
  core/         Profile, Paper Map, Objective, Evidence, Finding
  chat/         trajectory and approval records

infra/
  source/       parsers and Source runtime
  persistence/  explicit PostgreSQL and test-memory repositories
```

## Boundary Rules

- Controllers call owning application services; they do not assemble scientific
  state from repository internals.
- Collection groups Documents but does not own preparation readiness.
- Document preparation performs no Objective-specific Evidence extraction.
- Objective discovery and analysis accept explicit ready `document_ids`.
- Analysis freezes preparation fingerprints and rejects stale inputs.
- Agent writes stop for exact user approval and then call the same application
  service as the HTTP flow.
- Technical retry state remains separate from scientific absence or uncertainty.
- Do not add compatibility shims or generic service layers.

## Related Docs

- [`overview.md`](overview.md)
- [`persistence-model.md`](persistence-model.md)
- [`goal-core-source-layering.md`](goal-core-source-layering.md)
- [`../specs/api.md`](../specs/api.md)
