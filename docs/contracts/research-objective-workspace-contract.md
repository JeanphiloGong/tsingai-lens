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

## Product Spec: Research Direction Workspace

This section is the phase-one specification for productizing the research
objective route into the research-direction workspace. It is intentionally
written before implementation so backend and frontend changes can be judged
against the same target.

### Assumptions

1. The user is a researcher reviewing a built paper collection in the existing
   browser workspace, not a public anonymous visitor.
2. The primary object is a research objective / research direction. Material is
   a facet inside that direction.
3. The backend owns semantic assembly. The frontend may format, filter, and
   navigate evidence, but it should not infer scientific logic from raw records.
4. The first optimized target is read-only review and source traceback. Editing
   objectives, approving evidence, or launching rebuilds can follow later.
5. The route stays inside the existing same-origin `/api/v1/*` browser
   contract.

### Objective

Build a research-direction workspace that lets a researcher answer:

```text
For this research objective, what did the collection actually prove, which
papers support it, which experimental conditions and measurements are involved,
and where is every claim grounded in the source PDFs?
```

The workspace should not be a generic evidence dump. Its primary user-facing
shape is a research logic chain:

```text
objective
-> paper coverage and paper role
-> material / sample / process context
-> test or characterization condition
-> measured result
-> comparison or observed trend
-> interpretation, agreement, conflict, and gaps
-> source traceback
```

The user should be able to start from the objective, inspect the chain at a
high level, drill into evidence groups, and jump to the source document without
losing the objective context.

### Tech Stack

- Frontend: SvelteKit 2, Svelte 5, TypeScript, Vite, Playwright.
- Backend: FastAPI-style Python backend, Core semantic-build records, SQLite
  persistence through the Core repository boundary.
- Browser contract: same-origin `/api/v1/*` requests through shared frontend
  API helpers.
- Existing route family:
  `frontend/src/routes/collections/[id]/objectives/`.

### Commands

Frontend checks:

```bash
cd frontend
npm run check
npm run test:e2e -- --reporter=line
npm run build
```

Backend checks for objective read-model changes:

```bash
cd backend
./.venv/bin/python -m pytest tests/unit/services/test_research_objective_service.py -q
./.venv/bin/python -m ruff check application/core/semantic_build tests/unit/services
```

P001 objective benchmark check when semantic payloads change:

```bash
cd backend
./.venv/bin/python scripts/evaluation/expert_gold/run_objective_gold_benchmark.py \
  --output-dir <objective-run-output-dir> \
  --gold-paper-id P001
```

Docs governance check when this contract changes:

```bash
python3 scripts/check_docs_governance.py
```

### Project Structure

```text
docs/contracts/research-objective-workspace-contract.md
  Shared product/API/interaction contract for the objective workspace.

backend/application/core/semantic_build/
  Owns objective discovery, evidence-unit assembly, and logic-chain assembly.

backend/controllers/core/ and backend application services
  Own objective list and objective research-view read models.

frontend/src/routes/_shared/researchView.ts
  Owns browser-side TypeScript types and same-origin API helpers.

frontend/src/routes/collections/[id]/objectives/+page.svelte
  Owns the collection objective list.

frontend/src/routes/collections/[id]/objectives/[objective_id]/+page.svelte
  Owns the objective workspace page.

frontend/e2e/
  Owns browser-level route checks and screenshot-oriented coverage.
```

### Code Style

Frontend code should keep semantic decisions in backend payloads and use Svelte
only for state, grouping, and presentation:

```svelte
{#if view.readiness.logic_chain_ready && view.logic_chain}
	<LogicChainSummary chain={view.logic_chain} />
{:else}
	<EmptyState message={$t('research.objectiveWorkspace.noLogicChain')} />
{/if}
```

Backend read models should return product-shaped fields directly when the UI
would otherwise have to reconstruct scientific meaning:

```python
return ObjectiveResearchView(
    objective=objective_summary,
    readiness=readiness,
    logic_chain=assembled_chain,
    evidence_units=resolved_units,
    warnings=diagnostics,
)
```

### Frontend Interaction Design

The optimized objective page should be organized around review workflow rather
than raw object type order.

1. Objective header:
   show the question, material/process/property axes, confidence, and readiness
   state. This stays compact and scannable.
2. Logic-chain overview:
   first primary section. Show the chain as ordered steps with counts,
   completeness, conflicts, and gaps. This is the answer scaffold.
3. Evidence matrix / grouped evidence:
   group resolved evidence units by scientific role: process context,
   test condition, measurement, comparison, characterization, interpretation.
   Filters should narrow by paper, property, sample, and evidence kind.
4. Paper coverage:
   show which papers are primary, supporting, background, or excluded for this
   objective. Paper cards or rows should expose changed variables, measured
   scope, relevant tables, unit count, and route count.
5. Evidence inspector:
   selecting any chain step or evidence row opens a side inspector with
   payload details, source refs, confidence, warnings, and document links.
6. Source traceback:
   source links open the document route with `page`, `source`,
   `evidence_unit_id`, and `return_to` query parameters so the user can jump
   back to the same objective workspace.
7. Diagnostics:
   extraction routes, skipped sources, unresolved joins, and warnings should be
   available but secondary. They should help debug extraction without becoming
   the main product surface.

### Backend / Frontend Coordination

Backend responsibilities:

- Persist and expose objective-first records:
  `ResearchObjective`, `ObjectiveContext`, `ObjectivePaperFrame`,
  `ObjectiveEvidenceRoute`, `ObjectiveEvidenceUnit`, and `ObjectiveLogicChain`.
- Return a stable objective research-view read model with readiness flags.
- Resolve condition IDs and sample IDs into real experimental context before
  the frontend sees final evidence rows.
- Provide source refs that can drive document navigation without browser-side
  guessing.
- Provide warnings and completeness states for partial, failed, or stale
  objective builds.
- Prefer product-shaped logic-chain summaries over requiring the frontend to
  assemble scientific conclusions from raw evidence units.

Frontend responsibilities:

- Use the existing same-origin API helper path in
  `frontend/src/routes/_shared/researchView.ts`.
- Render explicit loading, empty, partial, ready, and failed states.
- Keep the research logic chain as the primary first-screen object.
- Provide dense review interactions: filters, selection, side inspection,
  source navigation, and return navigation.
- Avoid treating material routes or material ids as objective resources.
- Avoid inferring scientific semantics that should be provided by backend
  read models.

### Testing Strategy

Backend tests should verify:

- objective research-view payloads include readiness, paper frames, evidence
  routes, evidence units, logic chain, warnings, and source refs
- logic-chain payloads preserve material, process context, test condition,
  result, comparison, interpretation, and gaps
- empty and partial objective states are represented explicitly
- no material endpoint returns objective records as a disguised compatibility
  path

Frontend tests should verify:

- objective list loads from the objective endpoint
- objective workspace renders header, logic-chain overview, paper coverage,
  evidence groups, and source links from a fixture payload
- loading, empty, partial, failed, and ready states are visible
- selecting evidence updates the inspector without losing page context
- source links include `page`, `source`, `evidence_unit_id`, and `return_to`
- Playwright desktop and mobile screenshots show no overlap, blank primary
  regions, or unreadable text

### Boundaries

- Always:
  use `/api/v1/*` same-origin helpers, show source traceback for claims, keep
  readiness and warning states visible, and verify with focused backend,
  frontend, and Playwright checks.
- Ask first:
  changing public API shapes, adding dependencies, introducing editable
  evidence approval, adding rebuild controls, deleting material routes, or
  changing database table shape.
- Never:
  make `/materials` return objective records, treat `objective_id` as a fake
  `material_id`, hide missing evidence behind fluent summary text, run LLM
  logic in the browser, or add a parallel browser API client.

### Success Criteria

The first optimized version is acceptable when:

- Opening `/collections/:collectionId/objectives/:objectiveId` shows the
  objective question, axes, readiness, and confidence without needing any
  material route.
- The first primary section is a research logic chain, not raw diagnostics.
- A P001-backed objective can show 3 test-condition families, 80 core
  measurements, 19 pairwise comparisons, characterization observations, and
  source links without overwhelming the first viewport.
- Every visible claim or evidence item can navigate to a document route with a
  source-aware query string and a return path.
- Partial or missing objective data is explicit through readiness, empty
  states, and warnings.
- The frontend does not derive scientific conclusions from raw payload text;
  backend read models provide the logic-chain summary or mark it unavailable.
- `npm run check`, targeted frontend tests, relevant backend tests, docs
  governance, and Playwright screenshots pass for the touched surface.

### Open Questions

- Should the first optimized page include cross-objective switching in the
  detail route, or should switching stay on the objective list page?
- Should evidence approval, rejection, or correction be part of this wave, or
  remain a later curation workflow?
- Should backend add a more product-shaped `logic_chain.steps` read model now,
  or should the first frontend optimization continue using the existing
  `chain_payload` plus evidence-unit groups?
- Should comparison rows be shown as a compact result matrix in this page, or
  only inside the evidence inspector until the comparison projection is fully
  cut over?

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
