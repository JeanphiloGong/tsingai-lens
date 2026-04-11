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
- [`collection-ui-restructure-proposal.md`](collection-ui-restructure-proposal.md)
  Follow-on collection UI restructuring proposal for state hierarchy and page
  information architecture

## Dependency Rule

Route components here should use shared helpers from `../_shared/` for API
access, formatting, and cross-route support rather than re-implementing those
concerns locally.
