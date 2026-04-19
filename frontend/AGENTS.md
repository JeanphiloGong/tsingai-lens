# AGENTS.md (Frontend Rules: TsingAI-Lens)

## Overview

These rules apply to work under `frontend/`. Follow the repository root
`AGENTS.md` first, then apply this file for frontend-specific boundaries,
approval gates, and verification rules.

- Module purpose:
  own the SvelteKit browser application for collections, workspace browsing,
  evidence/comparison views, graph/report surfaces, and conditional protocol
  browsing through the same-origin backend contract.
- Default focus:
  keep the collection workspace and evidence/comparison flows aligned with the
  Lens v1 product boundary.
- Primary authorities:
  `frontend/README.md`, `frontend/docs/frontend-plan.md`,
  `frontend/src/routes/collections/README.md`, and
  `frontend/src/routes/_shared/README.md`.

## Core Principles

- Keep browser requests on same-origin `/api/*` and `/api/v1/*`.
- Treat the collection workspace as the primary Lens v1 frontend surface.
- Prefer explicit loading, empty, limited, and error states over silent fallbacks.
- Keep shared browser contract code under `frontend/src/routes/_shared/`.
- Preserve accessibility and i18n when touching visible UI.

## Domain Philosophies (Master-Level)

### Frontend Contract Safety

- Goal:
  keep the browser aligned with the backend contract and the shared Lens v1
  workflow.
- Constraints:
  browser-visible API entrypoints stay on `/api/*` and `/api/v1/*`; alternate
  browser contracts are high-risk.
- Evidence:
  `frontend/docs/frontend-plan.md`, `_shared/api.ts`, and route behavior stay
  aligned.
- Failure cost:
  broken UI flows, hidden contract drift, and operator confusion.
- Tradeoffs:
  prefer contract clarity and flow stability over convenience shortcuts.
- Non-negotiables:
  do not introduce a second browser-facing API contract without approval.

### Product Flow and UX

- Goal:
  keep the UI centered on collection creation, indexing, workspace review,
  evidence, documents, and comparisons.
- Constraints:
  graph, report, and protocol remain secondary or conditional surfaces.
- Evidence:
  navigation, calls to action, and state handling keep the workspace and core
  artifact views primary.
- Failure cost:
  the UI starts optimizing for the wrong product surface.
- Tradeoffs:
  reduce decorative or exploratory breadth to protect the primary workflow.
- Non-negotiables:
  do not make graph or protocol the primary acceptance path without approval.

### Frontend Docs and Shared Helpers

- Goal:
  keep route ownership, browser helpers, and frontend docs readable and
  discoverable.
- Constraints:
  `_shared/` owns reusable browser-side helpers; `collections/` owns workspace
  route behavior; formal frontend docs live in `frontend/docs/`.
- Evidence:
  changes update the owning helper, route family, or doc path directly.
- Failure cost:
  duplicated client logic, stale guidance, and route confusion.
- Tradeoffs:
  prefer smaller direct edits over additional abstraction.
- Non-negotiables:
  no duplicate browser helper or doc authority for the same flow.

## Product & Module Standards

- Browser requests must stay on same-origin `/api/*` and `/api/v1/*`.
- `frontend/src/routes/_shared/` owns shared API clients, i18n, and route
  support logic.
- `frontend/src/routes/collections/` owns collection workspace route behavior.
- `frontend/docs/frontend-plan.md` is the frontend same-origin contract guide.
- Retired debug-style routes remain explanatory only and should not reintroduce
  alternate browser contracts.

## 12 Golden Rules (Why / How / Check)

1. Keep the workspace primary.
   Why: the collection workspace is the Lens v1 acceptance center.
   How: keep page hierarchy, entry points, and main calls to action oriented
   around collection workflows.
   Check: new UI work does not demote workspace, evidence, documents, or
   comparisons behind secondary surfaces.

2. Preserve the same-origin browser contract.
   Why: product traffic should not depend on ad hoc base URLs or alternate
   clients.
   How: route browser calls through the existing same-origin API helpers.
   Check: visible product requests still resolve through `/api/*` or
   `/api/v1/*`.

3. Keep `_shared/` as the shared browser seam.
   Why: duplicated request and state helpers create frontend drift.
   How: extend the owning shared helper instead of adding parallel wrappers.
   Check: no second helper family appears for the same browser concern.

4. Make UI states explicit.
   Why: collection workflows depend on clear processing, limited, and failure
   signals.
   How: render loading, empty, limited, and error states deliberately.
   Check: the touched UI has an explicit state model instead of silent failure.

5. Preserve i18n and user-facing copy discipline.
   Why: hardcoded strings drift quickly across the app.
   How: update the owning translation path when changing user-facing copy.
   Check: newly introduced visible strings do not bypass the existing i18n
   approach without approval.

6. Keep accessibility intact.
   Why: the primary workspace flow must remain usable and reviewable.
   How: preserve semantic structure, labels, focus behavior, and keyboard
   access when editing UI.
   Check: the touched UI still exposes usable interaction cues.

7. Do not add alternate frontend contracts by default.
   Why: debug-only flows and extra API entrypoints confuse ownership.
   How: change the real flow instead of adding a side path.
   Check: no new debug-style browser path or alternate API route appears
   without approval.

8. Keep route ownership clear.
   Why: this frontend relies on explicit route-family boundaries.
   How: place collection workspace behavior under `collections/` and shared
   support under `_shared/`.
   Check: ownership remains obvious from the file location.

9. Update the owning frontend docs when behavior changes.
   Why: frontend flow drift is hard to recover from without current docs.
   How: update `frontend/docs/` or the relevant local `README.md` in the same
   task when route or contract behavior changes.
   Check: doc updates ship with behavior changes, or the final report explains
   why they did not.

10. Prefer targeted verification.
    Why: full browser suites are expensive, but focused changes still need real
    feedback.
    How: run the smallest relevant frontend command from `package.json`.
    Check: the final report names the actual command run, or says `not run`
    with the blocker.

11. Do not hand-edit generated or vendor paths.
    Why: `build/`, `.svelte-kit/`, and `node_modules/` are not stable source
    files.
    How: edit `src/`, `docs/`, `static/`, and config source files instead.
    Check: changes stay out of generated or vendored output.

12. Clean up frontend drift before finishing.
    Why: stale routes, helpers, and copy create user-facing confusion.
    How: remove dead UI branches, obsolete helpers, and stale docs caused by
    the task.
    Check: the final report names the cleanup performed.

## Scope Boundaries

### Default-safe work

- Scoped edits under `frontend/src/`, `frontend/docs/`, `frontend/static/`, and
  `frontend/e2e/` when directly requested.
- Targeted updates to frontend route-family `README.md` files and contract
  docs.
- Local cleanup required to complete an approved frontend task.

### Approval-gated work

- Alternate browser contracts, new public API entry styles, or same-origin
  bypasses.
- Cross-cutting changes that require backend contract drift without an explicit
  request.
- Large dependency or toolchain changes from the frontend side.
- Destructive changes to built artifacts or release-path behavior.

## Permission Model

- Safe to execute:
  scoped frontend implementation, test, and doc changes within one owned seam.
- Ask before proceeding:
  when the change affects public browser contracts, multiple route families, or
  frontend/backend integration semantics.
- Stop and escalate:
  when the task needs a second browser contract, a breaking integration change,
  or release/deployment changes.

## Execution Rules

- Read the owning frontend README or local route README before changing a seam
  you have not just touched.
- When changing governed docs or node-local frontend `README.md`, run
  `python3 ../scripts/check_docs_governance.py` from `frontend/` or the
  equivalent root command.
- When changing frontend source, use the commands defined in
  `frontend/package.json`, usually `npm run check` plus the smallest relevant
  test command.
- If environment, browser dependencies, or install state block verification,
  report `not run` and name the blocker precisely.

## Quality Bar

- Frontend diffs must preserve route ownership, explicit state handling, and
  same-origin contract clarity.
- UI changes should not quietly shift Lens v1 toward the wrong primary surface.
- Final reports must state whether any new abstraction was added, whether it is
  temporary or permanent, and what cleanup was performed.

## Decision & Accountability

- `frontend/docs/frontend-plan.md` owns the frontend same-origin contract guide.
- `frontend/src/routes/_shared/README.md` owns shared browser helper guidance.
- `frontend/src/routes/collections/README.md` owns collection route-family
  guidance.
- If a frontend change overlaps shared product docs, update the owning shared
  doc path instead of creating a second authority.

## Risks & Open Questions

- The repo does not define individual frontend approvers in-repo, so risky
  approval defaults to the active human operator.
- Frontend contract and UX decisions often couple to backend semantics, so
  approval is still needed when the change crosses that boundary.
