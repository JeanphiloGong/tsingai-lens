# AGENTS.md (Backend Rules: TsingAI-Lens)

## Overview

These rules apply to work under `backend/`. Follow the repository root
`AGENTS.md` first, then apply this file for backend-specific boundaries,
approval gates, and verification rules.

- Module purpose:
  own collection ingestion, indexing orchestration, artifact generation,
  protocol extraction, persistence seams, and the browser-facing API contract.
- Default focus:
  preserve the Lens v1 evidence/comparison backbone and the explicit backend
  split across `goal/`, `source/`, `core/`, and `derived/`.
- Primary authorities:
  `backend/README.md`, `backend/docs/specs/api.md`,
  `backend/docs/architecture/overview.md`, and local node `README.md` files.

## Core Principles

- Keep backend ownership explicit across `controllers/`, `application/`,
  `domain/`, and `infra/`.
- Preserve `/api/*` and `/api/v1/*` behavior unless the human explicitly
  approves a contract change.
- Keep protocol as a conditional downstream branch, not the primary product
  center.
- Prefer direct changes to the owning implementation over indirection.
- Treat persisted collection state and generated artifacts as high-risk data.

## Domain Philosophies (Master-Level)

### Backend Contract Safety

- Goal:
  keep the backend a stable source of truth for collection workflows and
  browser integration.
- Constraints:
  route semantics, response shapes, task states, and artifact contracts are
  high-risk surfaces.
- Evidence:
  `backend/docs/specs/api.md`, controller schemas, and integration tests stay
  aligned.
- Failure cost:
  broken frontend behavior, stale docs, and hard-to-trace regressions.
- Tradeoffs:
  prefer correctness and explicit ownership over convenience abstractions.
- Non-negotiables:
  no breaking contract change without explicit approval.

### Data and Runtime State

- Goal:
  protect collection state, generated artifacts, and local runtime data from
  accidental corruption.
- Constraints:
  `backend/data/**` mixes committed structure and local stateful content.
- Evidence:
  data-path edits are deliberate, scoped, and human-approved when destructive.
- Failure cost:
  data loss, invalid local runs, and irreproducible debugging.
- Tradeoffs:
  move slower on data-path changes than on pure code refactors.
- Non-negotiables:
  do not mass rewrite or delete `backend/data/**` without explicit approval.

### Backend Docs and Operations

- Goal:
  keep backend docs, runbooks, and local entry pages aligned with behavior.
- Constraints:
  formal backend docs live under `backend/docs/`; node-local ownership lives in
  nearby `README.md` files.
- Evidence:
  changed contract or operational behavior updates the owning backend docs in
  the same task.
- Failure cost:
  drift between code, runbooks, and API expectations.
- Tradeoffs:
  prefer smaller code+doc updates over large undocumented code-only changes.
- Non-negotiables:
  no silent backend behavior change that leaves the owning docs stale.

## Product & Module Standards

- The backend should keep the Lens v1 backbone order
  `document_profiles -> evidence_cards -> comparison_rows -> protocol branch`.
- Collection-facing behavior should stay explicit through
  `controllers/source/*`, `controllers/core/*`, `controllers/derived/*`, and
  `controllers/goal/*`.
- `backend/docs/specs/api.md` is the backend API authority for frontend
  integration.
- Source runtime should remain under `infra/source/*`; persistence seams belong
  under `infra/persistence/*`.
- Node-local `README.md` files define local purpose and navigation for owned
  backend seams.

## 12 Golden Rules (Why / How / Check)

1. Keep handlers thin and ownership clear.
   Why: controller code is the public route boundary, not the business layer.
   How: keep orchestration in handlers and move behavior into owning backend
   modules.
   Check: controllers do not absorb domain logic that belongs elsewhere.

2. Preserve the explicit layer split.
   Why: this backend relies on readable ownership across
   `controllers/application/domain/infra`.
   How: add logic to the owning layer and keep dependencies directional.
   Check: no new cross-layer shortcut bypasses the intended seam.

3. Treat API contracts as approval-gated.
   Why: frontend behavior and docs depend on stable backend contracts.
   How: ask before changing endpoint semantics, response schema, or public task
   states.
   Check: contract changes are explicitly approved and documented.

4. Keep artifact semantics honest.
   Why: Lens value depends on traceable artifact meaning, not just file
   presence.
   How: preserve real semantics for document profiles, evidence cards,
   comparison rows, and protocol artifacts.
   Check: names, readiness states, and payload fields still match the owning
   docs.

5. Do not add compatibility layers by default.
   Why: backend cleanup slows down when old interfaces linger behind wrappers.
   How: update the real implementation and direct callers instead.
   Check: no shim, bridge, facade, wrapper, or dual-path logic remains without
   approval.

6. Protect `backend/data/**`.
   Why: local collection data, tasks, logs, and vector-store state are easy to
   damage.
   How: treat destructive or bulk data-path changes as approval-gated.
   Check: data rewrites only happen when the human explicitly asked for them.

7. Keep docs and code in sync.
   Why: stale backend docs create contract drift.
   How: update `backend/docs/` or local `README.md` files when behavior or
   ownership changes.
   Check: the owning doc path changed in the same task, or the final report
   explains why it did not.

8. Prefer targeted verification.
   Why: backend checks can be expensive, but untouched surfaces should not
   block focused work.
   How: run the smallest relevant backend verification for the changed surface.
   Check: the final report names the actual command run, or says `not run` with
   a real blocker.

9. Keep error semantics explicit.
   Why: collection workflows need diagnosable failures and recoverable client
   behavior.
   How: return meaningful status and structured failure information at trust
   boundaries.
   Check: changed failure paths stay interpretable in tests, code, or docs.

10. Avoid hidden persistence coupling.
    Why: persistence changes can silently break artifact readers and task flows.
    How: keep storage shape changes scoped and visible in the owning seam.
    Check: data-shape changes are reflected in the owning repositories, schemas,
    or docs.

11. Do not hand-edit generated or environment paths.
    Why: `.venv`, caches, and generated artifacts are not stable source files.
    How: edit owned source under `backend/` instead of generated outputs.
    Check: changes stay out of `.venv`, `__pycache__`, and other generated
    paths.

12. Clean up backend drift before finishing.
    Why: obsolete helpers and stale docs make later backend work harder.
    How: remove dead code, stale imports, redundant branches, and broken local
    links caused by the task.
    Check: the final report names the cleanup performed.

## Scope Boundaries

### Default-safe work

- Scoped edits under `backend/controllers/`, `backend/application/`,
  `backend/domain/`, `backend/infra/`, `backend/docs/`, and `backend/tests/`
  when directly requested.
- Targeted updates to backend node-local `README.md` files and backend runbooks.
- Local cleanup required to complete an approved backend task.

### Approval-gated work

- Breaking route, schema, artifact, or task-state changes.
- Bulk or destructive changes under `backend/data/**`.
- Toolchain, dependency, Dockerfile, or release-path changes from the backend
  side.
- Cross-cutting refactors that change both backend contracts and other modules
  without an explicit request.

## Permission Model

- Safe to execute:
  scoped backend implementation, test, and doc changes within one owned seam.
- Ask before proceeding:
  when the change affects public contracts, runtime data, or multiple backend
  seams with unclear ownership.
- Stop and escalate:
  when the task needs a compatibility layer, a breaking contract change, or a
  destructive data rewrite.

## Execution Rules

- Read the owning backend README or formal doc before changing a backend seam
  you have not just touched.
- When changing governed docs or node-local backend `README.md`, run
  `python3 ../scripts/check_docs_governance.py` from `backend/` or the
  equivalent root command.
- When changing backend Python code, run the smallest relevant verification
  available from `backend/`, usually targeted `pytest` or another scoped check.
- If the backend environment or dependencies block verification, report
  `not run` and name the blocker precisely.

## Quality Bar

- Backend diffs must preserve ownership clarity and contract readability.
- Docs, schemas, and tests should move with real backend behavior when the task
  changes them.
- Final reports must state whether any new abstraction was added, whether it is
  temporary or permanent, and what cleanup was performed.

## Decision & Accountability

- `backend/docs/specs/api.md` owns the backend HTTP contract.
- `backend/docs/` owns formal backend architecture, plans, and runbooks.
- Local backend `README.md` files own local purpose and navigation.
- If a backend change overlaps root shared docs, update the owning shared doc
  path instead of creating a second authority.

## Risks & Open Questions

- `backend/data/**` still mixes committed structure and runtime local state, so
  destructive changes should remain approval-gated.
- The repository does not name individual backend approvers in-repo, so risky
  approval defaults to the active human operator.
