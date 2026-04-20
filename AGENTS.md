# AGENTS.md (Project Rules: TsingAI-Lens)

## Overview

TsingAI-Lens is a self-hosted literature intelligence system for paper
collections. The current Lens v1 primary job is traceable cross-paper
comparison, not generic paper chat.

- Project purpose:
  preserve an evidence-first, comparison-first product and keep the shared
  repository rules aligned with that boundary.
- Approval authority:
  `repo-maintainers` are the default project owners in repository governance.
  When a risky path is not explicitly delegated, the current human operator
  must provide approval for the active task.
- Default focus area:
  shared product boundary, shared docs governance, and repository-wide safety
  rules.
- Default operating mode:
  single-agent. Do not delegate or run multi-agent work unless the human
  explicitly asks for it.
- Module-specific rules:
  use `backend/AGENTS.md` for backend-specific work and `frontend/AGENTS.md`
  for frontend-specific work.

## Core Principles

- Evidence before fluent summary.
- Comparison before isolated paper chat.
- Traceability before opaque generation.
- Prefer direct changes to the owning implementation and direct caller updates.
- Avoid adding layers unless the human explicitly approves them.
- Keep one authoritative doc path for each contract surface.

## Domain Philosophies (Master-Level)

### Product

- Goal:
  support research decisions with traceable cross-paper evidence.
- Constraints:
  the collection comparison workspace is the primary Lens v1 acceptance
  surface; graph, report, and protocol remain secondary or conditional.
- Evidence:
  shared product docs and implementation choices preserve document profiles,
  evidence cards, comparison rows, and source traceback.
- Failure cost:
  product drift toward opaque generation or the wrong primary workflow.
- Tradeoffs:
  reduce breadth to protect the comparison backbone.
- Non-negotiables:
  do not reframe Lens v1 as a generic paper chat product without explicit
  approval.

### Docs / Enablement

- Goal:
  keep durable knowledge in the correct owned doc path with a clear
  source-of-truth boundary.
- Constraints:
  root `docs/` stays shared and cross-module; module docs stay with the owning
  module; node-local `README.md` files own local purpose and navigation.
- Evidence:
  governance stays current, links resolve, and doc placement matches the repo
  model.
- Failure cost:
  contradictory guidance and repo drift.
- Tradeoffs:
  keep docs trees small and explicit instead of broad and redundant.
- Non-negotiables:
  no duplicate authority for the same contract surface.

### Security

- Goal:
  avoid secret leakage and unsafe repository-wide changes.
- Constraints:
  no secrets, tokens, credentials, or PII in committed content; release and
  deployment paths are approval-gated.
- Evidence:
  sensitive values stay out of the repo and risky operational changes are
  explicit.
- Failure cost:
  security exposure, broken release mechanics, and irreproducible operations.
- Tradeoffs:
  accept slower approval on high-risk repository paths.
- Non-negotiables:
  do not commit secrets or edit release/deployment paths without approval.

## Product & Project Standards

- The Lens v1 backbone order is
  `document_profiles -> paper facts family -> comparison_rows /
  evidence_cards -> protocol branch`.
- Materials science is the first proving vertical, not the permanent product
  boundary.
- Protocol output is conditional downstream value, not the default Lens v1
  center.
- Root `docs/` holds shared governance, architecture, contracts, decisions,
  overview, and research context.
- `backend/docs/` and `frontend/docs/` hold formal module-local docs.
- Shared product scope belongs in shared product and architecture docs, not in
  module-local workarounds.

## 12 Golden Rules (Why / How / Check)

1. Protect the Lens v1 boundary.
   Why: this repo exists to support traceable research comparison work.
   How: keep changes aligned with evidence-backed collection workflows.
   Check: no task quietly promotes graph, report, or protocol to the primary
   acceptance surface without approval.

2. Change the real implementation.
   Why: wrappers and forwarding layers hide ownership and slow cleanup.
   How: edit the owning module and update callers directly.
   Check: no new adapter, wrapper, shim, facade, bridge, or compatibility
   layer appears without explicit approval.

3. Do not keep compatibility baggage by default.
   Why: dual paths and fallback branches create silent drift.
   How: remove migration code, forwarding helpers, and old interfaces in the
   same task when possible.
   Check: no temporary compatibility logic remains unless it is explicitly
   approved, labeled, and justified.

4. Choose the simpler design with fewer layers.
   Why: this repository already spans backend, frontend, and formal docs.
   How: prefer small direct edits over generalized abstractions.
   Check: the final report states whether any new abstraction was added and
   whether it is temporary or permanent.

5. Respect the owning contract surface.
   Why: this repo uses explicit source-of-truth boundaries across docs and
   code.
   How: update the owning doc or module instead of creating parallel guidance.
   Check: no duplicate authority is introduced across root docs, module docs,
   specs, or node-local entry pages.

6. Keep shared docs in their owning path.
   Why: shared docs are a repository-level contract, not a dumping ground.
   How: put cross-module knowledge in root `docs/` and local knowledge in the
   owning module or node.
   Check: new docs land in the correct doc root and links remain valid.

7. Treat release and deployment paths as approval-gated.
   Why: workflow, compose, and image changes can affect shared operations.
   How: ask before touching `.github/workflows/`, `docker-compose*.yml`, or
   release mechanics.
   Check: no release-path change proceeds without explicit approval.

8. Do not hand-edit generated or vendor paths.
   Why: generated outputs and vendored dependencies will drift or be
   overwritten.
   How: edit owned source files instead of build outputs, caches, environments,
   or vendored trees.
   Check: changes land in maintained source paths.

9. Verify what you touch.
   Why: this repo spans FastAPI, SvelteKit, and governed docs.
   How: run the smallest relevant checks for the changed surface.
   Check: the final report names what ran, or says `not run` with the reason.

10. Follow local module AGENTS for module work.
    Why: backend and frontend each have stricter local constraints than the
    shared root.
    How: apply `backend/AGENTS.md` or `frontend/AGENTS.md` when the task enters
    those trees.
    Check: module-specific edits follow the owning local rules.

11. Escalate on unclear ownership.
    Why: risky work should not proceed on guesswork.
    How: stop and ask when approval, ownership, or scope is ambiguous.
    Check: the output names the ambiguity instead of inventing a rule.

12. Clean up before finishing.
    Why: dead code, stale files, and broken links mislead later work.
    How: remove obsolete exports, redundant branches, unused helpers, and stale
    doc links caused by the task.
    Check: the final report names the cleanup that was performed.

## Scope Boundaries

### Default-safe work

- Targeted updates in shared docs, repository entry pages, and repository-level
  governance files when directly requested.
- Scoped module work when directly requested and when the owning local
  `AGENTS.md` is also followed.
- Local cleanup required to complete the requested task.

### Approval-gated work

- Any new adapter, wrapper, shim, facade, bridge, or compatibility layer.
- Breaking shared contract changes that affect multiple modules.
- Cross-cutting refactors that span backend, frontend, and docs without an
  explicit request.
- Dependency, toolchain, Docker, compose, workflow, or release-image changes.
- Deleting large doc families or retained historical records unless the human
  explicitly approved the cleanup.

### Out of scope by default

- Secret creation, credential handling, or PII management beyond safe removal.
- Publishing releases, pushing images, or operating external infrastructure.
- Force-push, history rewrite, or destructive git cleanup.

## Permission Model

- Safe to execute when directly requested:
  scoped edits inside one owned surface plus required local cleanup.
- Ask before proceeding:
  when the task expands beyond the requested surface, conflicts with local
  changes, or touches a high-risk path.
- Stop and escalate:
  when the change requires a new compatibility layer, breaks a published
  contract, or needs deployment/release action.

## Execution Rules

- Read the owning README or formal doc before changing behavior in a surface
  you have not just touched.
- When touching governed docs or node-local `README.md` entry pages, run
  `python3 scripts/check_docs_governance.py`.
- For backend or frontend code changes, follow the owning local `AGENTS.md`
  verification rules in addition to these root rules.
- If verification cannot run, say `not run` and give the operational reason.
- Keep repository governance files in English unless the owning file family
  clearly uses another default.

## Quality Bar

- Diffs must be reviewable, scoped, and traceable to an explicit request.
- Changes must preserve clear ownership and avoid undocumented coupling.
- Product-facing behavior must stay aligned with the Lens v1 evidence/comparison
  contract unless explicitly re-scoped.
- Do not leave dead code, obsolete exports, stale links, or redundant branches
  introduced by the task.
- Final reports must state whether any new abstraction was added, whether it is
  temporary or permanent, and what cleanup was performed.

## Decision & Accountability

- Root `docs/` owns shared governance, architecture, contracts, decisions, and
  research context.
- `backend/docs/` and `frontend/docs/` own formal module-local docs.
- Node-local `README.md` files own local purpose, boundary, and navigation.
- Shared docs default to `repo-maintainers`; module-local risky approvals
  default to the active human operator when no narrower owner is named.
- When ownership or approval is unclear, do not guess; surface the ambiguity in
  the task output and ask the human for the decision on risky paths.

## Risks & Open Questions

- Repository governance names `repo-maintainers`, the backend maintainer set,
  and the frontend maintainer set, but it does not identify individual people
  in-repo.
- Deployment and release approval rules for `.github/workflows/` and release
  compose flows are not separately documented, so they should remain
  approval-gated.
