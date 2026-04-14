# Graph Surface Current State

## Purpose

This document records the current shared decision for the collection graph
surface and the execution order for the next stabilization wave.

It exists to keep the graph page aligned with the Lens v1 evidence-first,
comparison-first boundary without prematurely turning the graph into a new
primary product surface.

## Current Decision

The current collection graph page remains a secondary derived analytical
surface.

That means:

- the graph page stays available as an advanced view
- it should not define the primary Lens v1 workflow
- evidence and comparison remain the primary collection-facing surfaces
- the current graph implementation should first be stabilized before any new
  product-direction investment

## Why The Current Graph Still Feels Misaligned

The current graph page is still useful as a retained GraphRAG artifact browser,
but it does not yet behave like a core Lens research judgment surface.

Current gaps:

- the backend graph payload is still centered on retained graph artifacts
  rather than Lens-native research objects such as claim, evidence,
  condition/context, and comparability
- the current page interaction model is still closer to graph inspection and
  debugging than to evidence-backed research judgment
- the frontend graph page had contract drift against the hardened backend
  payload and error model
- layout and detail behavior still need basic stabilization before bigger
  product bets are made

## Near-Term Execution Order

The next implementation wave should stay narrow:

1. fix frontend and backend graph contract mismatch
2. fix frontend handling of stable backend graph error codes
3. fix current graph page usability issues as a secondary surface
4. revisit the product decision only after the current page is stable enough
   to evaluate honestly

This wave is intentionally about stabilization, not repositioning.

## Explicit Non-Goals For This Wave

Do not do the following in the current bug-fix pass:

- do not switch the graph rendering framework yet
- do not redefine the graph page as the main Lens v1 interface
- do not rebuild the graph around evidence/comparison-derived objects yet
- do not treat the retained GraphRAG graph as proof of final product fit

## Deferred Product Decision

After the current graph page is stabilized, the product team should make an
explicit decision between two directions:

- continue treating graph as a GraphRAG-oriented advanced surface
- design a stronger Lens-native graph derived from evidence cards,
  comparison rows, and document profiles

That later decision should be made as a product and architecture choice, not
hidden inside small UI or backend cleanup work.

## Decision Rule For Revisit

Revisit the graph product direction when the current page is no longer blocked
by basic contract drift or surface bugs and the team is ready to evaluate one
of these questions directly:

- should graph remain a secondary inspection view only
- should graph become a first-class research judgment surface
- if it becomes first-class, should its object model be GraphRAG-native or
  Lens-native

## Related Docs

- [System Overview](../overview/system-overview.md)
- [Lens V1 Architecture Boundary](lens-v1-architecture-boundary.md)
- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens V1 Frontend Interface Spec](../../frontend/src/routes/collections/lens-v1-interface-spec.md)
