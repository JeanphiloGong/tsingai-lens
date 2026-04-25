# Lens Mission and Positioning

## Purpose

This document defines the long-lived identity of Lens and should remain stable
across implementation phases.

Lens exists to help researchers and research agents make better literature
judgments by organizing scientific work around evidence, comparison, and
traceable reasoning rather than around fluent summary text alone.

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

- the v1 feature boundary
- the shared object model
- the backend artifact or API design
- the current implementation plan

Those belong in the v1 spec, shared architecture docs, and module-local
implementation plans.

## Core Principles

Lens should stay grounded in four durable principles:

- evidence before fluent generation
- comparability before isolated summary
- traceability before opaque convenience
- judgment support before automation theater

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

## Long-Term Substrate Direction

Lens v1 should remain collection-first at the product surface, but the
underlying architecture should be able to grow beyond one collection workspace.

The intended direction is to keep the evidence-backed comparison backbone clean
enough that it can later support:

- a reusable literature-backed materials facts substrate
- cross-collection and corpus-level retrieval over structured research facts
- benchmark, landscape, and agent-readable views derived from the same
  traceable backbone

That direction should extend the evidence-and-comparison philosophy rather than
replace it with generic chat or opaque database convenience.

## Post-V1 Workflow Direction

Beyond the current Lens v1 comparison foundation, Lens should move toward
supporting how professional materials researchers actually work with papers and
follow-up experiments.

That workflow is not "read a paper and summarize it". It is:

- identify the research problem and the decision the paper is trying to support
- reconstruct sample variants, controlled variables, process parameters, test
  conditions, and baselines
- connect process, structure, defects, properties, and evidence into one
  inspectable chain
- judge which results are genuinely comparable and which remain weak,
  incomplete, or baseline-misaligned
- turn the literature into candidate hypotheses, control groups, parameter
  matrices, characterization plans, and decision criteria for the next
  experiment

If Lens grows in this direction, it should help users treat one paper as an
experimental design and evidence object rather than only as prose. It should
help them review literature as variable tables, condition-bound results,
baseline-aware comparisons, and mechanism-backed evidence chains.

The output of that later workflow should remain human-reviewable. Lens should
help researchers propose and evaluate experiment plans, not pretend to replace
scientific judgment with a generic autonomous agent.

## Related Docs

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens Core Artifact Contracts](../contracts/lens-core-artifact-contracts.md)
- [Lens Evidence-First Direction and Conditional Protocol Generation](../decisions/rfc-evidence-first-literature-parsing.md)
- [Lens Agent-Era Positioning and Evidence Layer Direction](../decisions/rfc-lens-agent-era-positioning.md)
- [RFC Comparable-Result Substrate and Materials Database Direction](../decisions/rfc-comparable-result-substrate-and-materials-database-direction.md)
- [System Overview](system-overview.md)
