# Legacy Route Alias Cleanup Plan

## Summary

This plan records the cleanup boundary for redirect-only collection routes that
remain after the collection information architecture moved to the Lens v1
workspace, protocol, document, result, comparison, evidence, and graph pages.

The cleanup is frontend-local. It removes stale browser route aliases, but it
does not remove backend APIs or shared clients that still support active
workspace, protocol, task, graph, document, result, comparison, or evidence
flows.

## Context

The collection route family now has canonical page routes for the active Lens
v1 surfaces:

- `/collections/[id]`
- `/collections/[id]/protocol`
- `/collections/[id]/protocol/steps`
- `/collections/[id]/protocol/sop`
- `/collections/[id]/documents`
- `/collections/[id]/documents/[document_id]`
- `/collections/[id]/results`
- `/collections/[id]/results/[resultId]`
- `/collections/[id]/comparisons`
- `/collections/[id]/evidence`
- `/collections/[id]/graph`

Several older routes no longer owned visible pages. They only redirected to
newer routes or to workspace anchors:

- `/collections/[id]/steps`
- `/collections/[id]/sop`
- `/collections/[id]/search`
- `/collections/[id]/tasks`
- `/collections/[id]/reports`
- `/collections/[id]/settings`

These routes were compatibility aliases from earlier page organization.
Keeping them indefinitely made the route tree look broader than the product
surface actually is.

## Cleanup Scope

The first cleanup slice deletes the redirect-only frontend page files:

- `frontend/src/routes/collections/[id]/steps/+page.ts`
- `frontend/src/routes/collections/[id]/sop/+page.ts`
- `frontend/src/routes/collections/[id]/search/+page.ts`
- `frontend/src/routes/collections/[id]/tasks/+page.ts`
- `frontend/src/routes/collections/[id]/reports/+page.ts`
- `frontend/src/routes/collections/[id]/settings/+page.ts`

The same slice updates collection-route docs that describe transitional
aliases, especially references that say `/steps` and `/sop` may remain as
compatibility routes.

## Backend Boundary

Do not delete backend APIs in the same cleanup slice.

The following backend and shared frontend API surfaces are still active
capabilities, not route-alias residue:

- source task APIs used by the workspace to start and monitor processing
- protocol steps, search, and SOP APIs used by the protocol pages
- graph APIs used by the graph workspace and GraphML export
- document, result, comparison, and evidence APIs used by source verification
  and evidence-chain review

Reports should be treated as a separate API-retirement decision if the product
chooses to remove that capability. The current frontend workspace already
keeps reports degraded and out of the primary workflow, but that is not the
same as proving every reports backend path is dead.

## Expected Result

After this cleanup slice:

- the frontend route tree no longer contains redirect-only `steps`, `sop`,
  `search`, `tasks`, `reports`, or `settings` pages under
  `collections/[id]`
- canonical collection pages remain available
- old deep links to the deleted frontend aliases return normal route-not-found
  behavior instead of redirecting
- active backend API contracts remain unchanged
- collection-route docs describe the canonical route family rather than
  migration aliases

## Verification

Run the focused frontend and docs checks after the cleanup:

- `find frontend/src/routes/collections/[id] -maxdepth 2 -type d | sort`
- `rg "/collections/.*(/steps|/sop|/search|/tasks|/reports|/settings)" frontend/src/routes`
- `npm run check`
- `python3 scripts/check_docs_governance.py`
- `git diff --check`

The search check should allow API helper paths such as protocol search and task
APIs when they are still used by canonical pages.

## Related Docs

- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
  Collection route-family interface authority and cleanup wave notes
- [`collection-ui-restructure-proposal.md`](collection-ui-restructure-proposal.md)
  Earlier information-architecture proposal that moved legacy surfaces behind
  the workspace and protocol routes
