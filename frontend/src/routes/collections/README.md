# Collection Routes

This node owns the collection workspace route family in the frontend.

## Scope

- `collections/[id]/+layout.svelte`
- `collections/[id]/+page.svelte`

## Responsibilities

- render the collection workspace
- coordinate file upload and task-start actions
- poll task status and artifact readiness
- surface graph, protocol, and report capabilities to the user

## Local Docs

- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
  Collection-facing interface spec for the Lens v1 workspace flow
- [`core-derived-graph-structure-and-drilldown-frontend-alignment-plan.md`](core-derived-graph-structure-and-drilldown-frontend-alignment-plan.md)
  Frontend-local graph cutover plan for the lean graph contract, canonical
  drilldown, and neighbors expansion
- [`graph-exploration-interaction-and-layout-proposal.md`](graph-exploration-interaction-and-layout-proposal.md)
  Follow-on proposal for graph focus, neighborhood expansion gestures, and
  in-node card layout on the Cytoscape graph page
- [`comparable-result-semantic-artifact-frontend-alignment-plan.md`](comparable-result-semantic-artifact-frontend-alignment-plan.md)
  Frontend-local plan for preserving semantic comparison artifact state and
  graph readiness semantics during the comparable-result rollout
- [`materials-comparison-v2-frontend-alignment-plan.md`](materials-comparison-v2-frontend-alignment-plan.md)
  Frontend-local contract cutover plan for the nested comparisons response
- [`collection-ui-restructure-proposal.md`](collection-ui-restructure-proposal.md)
  Follow-on collection UI restructuring proposal for state hierarchy and page
  information architecture
- [`claim-traceback-navigation-contract.md`](claim-traceback-navigation-contract.md)
  Claim-to-source navigation contract for comparison/evidence to document
  traceback behavior

## Dependency Rule

Route components here should use shared helpers from `../_shared/` for API
access, formatting, and cross-route support rather than re-implementing those
concerns locally.
