# Lens Mission and Positioning

## Purpose

Lens exists to help researchers and research agents make better literature
judgments by organizing evidence, conditions, and comparisons into durable
research objects.

The system should reduce common research mistakes such as:

- comparing results that are not actually comparable
- treating weak evidence as if it were a strong conclusion
- losing the conditions under which a claim holds
- relying on fluent generated text that cannot be traced back to source evidence

Lens should therefore be judged less by how well it summarizes papers and more
by how well it preserves evidence, comparison context, and traceability.

## Scope

This document defines the long-lived product position for Lens across the
repository. It applies to shared product language, backend and frontend
boundaries, and future agent integration.

It does not define:

- the current implementation plan
- the v1 feature boundary
- the backend artifact or API design

Those belong in the v1 spec, shared architecture docs, and backend-local
implementation plans.

## Responsibilities

Lens is responsible for:

- turning literature collections into evidence-backed research objects
- preserving provenance from outputs back to spans, sections, figures, tables,
  and paper context
- making cross-paper comparison explicit rather than implicit
- recording the conditions, baselines, and scope that constrain each claim
- surfacing `insufficient`, `not_comparable`, or `not_extractable` outcomes
  when the literature does not support a stronger conclusion
- accumulating collection memory so work compounds over time instead of
  resetting on every run

Lens should become a stable evidence and judgment layer that both researchers
and agents can rely on.

## Positioning

Lens should be positioned as research infrastructure rather than a generic
"research agent".

In the agent era:

- models can read and summarize
- agents can search, orchestrate, and call tools
- Lens should define what counts as durable evidence, what is comparable, and
  what is safe to carry forward

The practical rule is:

Researchers and agents can explore; Lens constrains, stores, compares, and
traces.

## What Lens Is Not

Lens should not be positioned as:

- a paper chat shell
- a single-paper summary product
- an autonomous "AI scientist"
- a system whose primary value is SOP generation
- a graph demo whose visual polish outruns evidence quality

These may exist as supporting surfaces, but they are not the product's center.

## First Vertical

Materials science is the first vertical because it sharply exposes the need for
evidence-backed comparison:

- process conditions and baselines often decide whether results are comparable
- structure-processing-properties-performance reasoning benefits from explicit
  evidence chains
- experiment planning depends on understanding conditions, controls, and weak
  evidence regions rather than only reading summaries

Materials should shape the first schema and workflow, but Lens should remain a
broader literature intelligence system rather than a materials-only protocol
tool.

## Related Areas

This mission should drive:

- the evidence-first parsing direction
- the v1 comparison-first workflow
- future agent-callable tools that operate on evidence and judgment objects
- collection memory and provenance design

## Related Docs

- [Lens V1 Definition](../40-specs/lens-v1-definition.md)
- [Lens Evidence-First Direction and Conditional Protocol Generation](../10-rfcs/evidence-first-literature-parsing.md)
- [Lens Agent-Era Positioning and Evidence Layer Direction](../10-rfcs/lens-agent-era-positioning.md)
- [System Overview](../30-architecture/system-overview.md)
