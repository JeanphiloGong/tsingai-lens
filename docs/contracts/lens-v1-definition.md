# Lens V1 Definition

## Scope

This document defines the Lens v1 product boundary for the current delivery
phase.

It defines the user-facing value, acceptance scope, and success bar of Lens
v1. It does not define shared system object relationships or backend
implementation sequencing.

It answers:

- who v1 is for
- which job v1 must do well
- which outputs count as the core product value
- what v1 explicitly does not promise

It does not define:

- the shared object model or artifact dependency graph
- the detailed backend implementation plan
- the final API schema

## Target User and Primary Job

Lens v1 is for researchers working across a collection of papers who need to
make evidence-backed comparison judgments faster and with fewer mistakes.

For the first vertical, the target user is a materials researcher who needs to:

- compare 20-50 papers without rereading each one repeatedly
- identify which results are genuinely comparable
- spot weak-evidence claims and conflict sources
- trace each important judgment back to original evidence and conditions

The primary job is not "summarize papers". The primary job is "support a
research decision with traceable cross-paper evidence".

## V1 Product Contract

Lens v1 should let a researcher complete in about one hour the kind of
cross-paper comparison work that would otherwise take most of a day, while
keeping each important judgment traceable back to original evidence and
conditions.

For the first vertical, the clearest value statement is:

> Lens v1 helps materials researchers compare 20-50 papers, identify genuinely
> comparable results, spot weak-evidence claims and conflict sources, and trace
> each decision back to original paper evidence and conditions.

## Primary Surface

The collection comparison workspace is the primary Lens v1 surface and the
primary acceptance surface.

That surface should let a user inspect:

- document type distribution and suitability warnings
- collection-facing comparison rows
- weak-evidence and conflict flags
- direct traceback from a surfaced result to source evidence and conditions

Other surfaces may exist in v1, but they are not the acceptance center.

## Core V1 Outputs

The outputs that define v1 value are:

- document profiling that distinguishes `experimental`, `review`, `mixed`, and
  `uncertain` papers
- comparison-ready rows as the primary collection-facing view for material,
  process, structure, property, and baseline inspection
- evidence-backed units such as claim, evidence, and condition/context
- source traceback into original spans or equivalent evidence anchors
- explicit warnings when a collection or paper is not suitable for protocol
  extraction or direct comparison

Protocol output remains useful, but it is not the primary definition of v1
value.

## In Scope

Lens v1 is in scope for:

- evidence-grounded comparison across a collection
- document typing and protocol suitability signals
- traceable evidence outputs
- comparability warnings and weak-evidence warnings
- materials science as the first proving vertical
- conditional protocol browsing for methods-heavy papers when the corpus
  supports it

## Out Of Scope

Lens v1 is explicitly out of scope for:

- turning every uploaded paper into final protocol steps
- auto-generating trustworthy SOPs from arbitrary corpora
- acting as a generic paper chat interface
- treating graph exploration as the primary acceptance surface
- positioning the product as an autonomous research agent
- promising full scientific understanding of every paper type
- prioritizing graph presentation over evidence quality

## V1 Success Measures

Lens v1 is successful when:

- a user can compare a collection through normalized evidence-backed outputs
  rather than raw summaries
- important outputs remain traceable to original evidence and conditions
- mixed or review-heavy collections can still produce useful outputs without
  fake protocol steps
- the system can say `not_comparable`, `insufficient`, or `not_extractable`
  when the evidence does not support a stronger result
- the rate at which non-comparable results are surfaced as directly comparable
  outputs decreases versus unstructured manual review
- materials users can identify likely comparison candidates, weak claims, and
  conflict sources faster than with manual reading alone

## First-Vertical Boundary

The first vertical should prove that the Lens product loop works in materials
science, not that Lens is permanently limited to materials.

Materials v1 should emphasize:

- baseline-aware comparison
- condition-aware evidence tracing
- support for experiment planning and literature review

It should not redefine the whole product as a materials-only protocol system.

## Boundary With Later Docs

This document is the v1 product boundary.

- shared object relationships and artifact roles belong in architecture docs
- minimum artifact contracts belong in shared specs
- implementation sequencing belongs in backend-local plans
- long-term product identity belongs in the mission and positioning guide

## Related Docs

- [Lens Mission and Positioning](../overview/lens-mission-positioning.md)
- [Lens Core Artifact Contracts](lens-core-artifact-contracts.md)
- [Lens Evidence-First Direction and Conditional Protocol Generation](../decisions/rfc-evidence-first-literature-parsing.md)
- [Lens Agent-Era Positioning and Evidence Layer Direction](../decisions/rfc-lens-agent-era-positioning.md)
- [System Overview](../overview/system-overview.md)
