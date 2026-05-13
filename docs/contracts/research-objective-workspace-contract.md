# Research Objective Workspace Contract

## Purpose

This document records the shared backend and frontend contract for moving the
collection workspace from material-first navigation to research-objective-first
navigation without rewriting the whole browser experience in one step.

It follows
[`rfc-research-objective-first-product-flow.md`](../decisions/rfc-research-objective-first-product-flow.md):
the primary user-facing analysis object becomes a research objective, while
material remains a facet inside that objective.

The implementation strategy is deliberately mixed:

- the data and API contract should be cleanly objective-first
- the frontend may reuse the current material workspace layout and interaction
  patterns
- the old material routes may remain during transition, but they should not
  become the long-lived home for objective-first semantics

## Product Boundary

The objective workspace should answer a scoped research question such as:

```text
How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?
```

That question owns the workspace context:

- material scope
- process, treatment, or variable axes
- property or outcome axes
- comparison intent
- relevant and excluded papers
- relevant sections and tables
- later evidence routes, evidence units, and logic chains

Material names should remain visible as chips, filters, and facets. They should
not be used as the primary resource identity for the new workspace.

## API Surfaces

The first shared API slice should add objective-first read surfaces under the
same-origin `/api/v1/*` browser contract.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/collections/{collection_id}/objectives` | List discovered research objectives for a collection, including readiness and lightweight axis metadata. |
| `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/research-view` | Read one objective workspace payload with objective detail and paper frames. |

The existing material endpoints should not be repurposed to return research
objectives. In particular:

- do not treat `objective_id` as a fake `material_id`
- do not make `/materials` return objective records
- do not add `ObjectivePaperFrame` fields to material payloads while keeping
  material-shaped names

This avoids making the frontend fast at the cost of a confusing long-lived
contract.

## Workspace Payload

The first objective research-view response should be small enough to support
frontend migration before evidence-unit extraction is complete.

Minimum shape:

```text
ObjectiveResearchView
- collection_id
- objective
- objective_context
- readiness
- paper_frames
- evidence_routes
- evidence_units
- logic_chain
- existing_comparison_rows
- warnings
```

### Objective

Minimum shape:

```text
ObjectiveSummary
- objective_id
- question
- material_scope
- process_axes
- property_axes
- comparison_intent
- confidence
```

### Readiness

Minimum shape:

```text
ObjectiveWorkspaceReadiness
- objectives_ready
- frames_ready
- routes_ready
- evidence_units_ready
- logic_chain_ready
```

`routes_ready`, `evidence_units_ready`, and `logic_chain_ready` may be false in
the first frontend slice. The response should still include empty arrays or
nulls for those future fields so the browser can keep stable tabs and empty
states.

### Objective Context

Minimum shape:

```text
ObjectiveContext
- objective_id
- question
- material_scope
- variable_process_axes
- process_context_axes
- target_property_axes
- excluded_property_axes
- routing_hints
- extraction_guidance
- confidence
```

### Paper Frames

The first visible evidence structure should be the persisted
`ObjectivePaperFrame` records.

Minimum shape:

```text
ObjectivePaperFrameView
- frame_id
- objective_id
- document_id
- title
- source_filename
- relevance
- paper_role
- background
- material_match
- changed_variables
- measured_property_scope
- test_environment_scope
- relevant_sections
- relevant_tables
- excluded_tables
```

`relevant_tables` and `excluded_tables` should use real Source table ids. The
backend should filter out hallucinated ids before returning them.

### Evidence Fields

The objective research-view response includes the evidence fields produced by
the objective-first Core pipeline:

```text
ObjectiveEvidenceRoute[]
ObjectiveEvidenceUnit[]
ObjectiveLogicChain | null
```

The backend now has builders for routes, evidence units, and logic chains.
These fields may still be empty for collections built before the objective
pipeline ran, failed builds, or objectives with no extractable evidence. The
frontend should render those as empty states and should not infer routes or
evidence units from raw material payloads.

## Frontend Migration

The browser should reuse the current material workspace shell where it remains
ergonomic:

- the current material list region becomes a research-objective list
- the material detail header becomes objective question and axis context
- the existing evidence or card region first renders paper frames
- tabs may show routes, evidence units, logic chain, and objective report as
  the frontend adopts the landed backend fields
- existing comparison rows can remain in a lower section labeled as current
  extracted evidence until the objective-scoped projections replace them in the
  browser workflow

The frontend should prefer a clean route for the new resource:

```text
/collections/:collectionId/objectives/:objectiveId
```

The old material route may keep working during transition. It should not become
the canonical objective workspace route.

## Parallel Development

Backend and frontend can proceed in parallel after this contract is accepted,
because their first deliverables have a stable boundary.

Backend first slice:

- add the objective list endpoint
- add the objective research-view endpoint
- return persisted `ResearchObjective`, `ObjectiveContext`, and
  `ObjectivePaperFrame` data
- include `evidence_routes`, `evidence_units`, and `logic_chain` fields from
  the objective pipeline when available
- expose readiness flags that match the available builders

Frontend first slice:

- add objective API helpers under the existing same-origin client pattern
- adapt the current material workspace layout to read objectives instead of
  materials
- show objective list, objective detail, and paper frames
- render routes, evidence units, and logic chain from the backend fields, with
  empty states when a collection has not produced them
- keep old material navigation available until the objective route is usable

The two slices should meet at mocked or fixture-backed payloads with the
`ObjectiveResearchView` shape above.

## Out Of Scope

The first contract does not require:

- replacing all material pages immediately
- deleting existing material APIs
- generating final objective reports
- changing graph, report, or goal-session contracts

The first contract has since grown beyond paper-frame-only rendering: route,
evidence-unit, and logic-chain fields are part of the backend payload. Replacing
all material pages, deleting material APIs, and generating final objective
reports remain follow-up work.

## Verification

Backend checks should cover:

- objective list response for a built collection
- objective research-view response with paper frames, routes, evidence units,
  and logic-chain readiness
- empty route, evidence-unit, and logic-chain states for collections built
  before those records exist
- no material endpoint returns objective records by accident

Frontend checks should cover:

- objective list loading from `/api/v1/collections/{collection_id}/objectives`
- objective detail and paper frames rendering from the objective research-view
- route, evidence-unit, and logic-chain rendering plus empty states
- continued access to old material pages during transition

End-to-end acceptance for the first wave is:

```text
build collection
-> open objective workspace
-> select a research objective
-> see objective axes and paper frames
-> inspect relevant and excluded tables
-> inspect routed evidence, extracted evidence units, and logic-chain readiness
```
