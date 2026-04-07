---
id: POLICY-2026-001
title: Repository Documentation Governance
type: policy
level: system
domain: shared
status: active
owner: repo-maintainers
created_at: 2026-04-07
updated_at: 2026-04-07
last_verified_at: 2026-04-07
review_by: 2026-07-07
version: v1
source_of_truth: true
related_issues: [62]
related_docs:
  - docs/README.md
supersedes: []
superseded_by: []
tags:
  - docs
  - governance
  - file-management
---

# Repository Documentation Governance

## Governance Goal

Establish a lightweight, maintainable documentation and file management system
for this repository so durable knowledge has:

- a clear location
- a named owner
- a lifecycle state
- a single source-of-truth boundary

This policy is project-specific. It governs repository documentation, not every
possible project artifact.

## Current State

Classification: `existing-governance`

What already works:

- the repository has clear high-level entrypoints in the root README
- backend and frontend already have their own `docs/` roots
- the repository now has a typed root docs structure plus module-local docs
  indexes
- backend and frontend both contain at least one active, classified contract or
  guide doc
- GitHub issue templates already define some structure for incoming work

Current failure modes:

- root-level docs mix durable project docs with research material and other
  operationally sensitive or low-governance content
- legacy docs and research assets still do not all follow the metadata and
  placement rules
- legacy PDFs, research references, and notes still live in pre-governance
  locations that need gradual cleanup
- source-of-truth boundaries for legacy files are still only partially explicit

## Target Taxonomy

This repository needs the following document types.

| Type | Purpose | Source of truth |
| --- | --- | --- |
| `policy` | repository rules such as doc governance and file placement | yes |
| `architecture` | current design of a system, domain, or module | yes |
| `spec` | stable contract such as API behavior or state behavior | yes |
| `guide` | human-facing usage, extension, or contributor instructions | yes |
| `runbook` | repeatable operational procedure | yes |
| `rfc` | proposed change before or during implementation | no, until accepted |
| `adr` | durable record of a decision and its tradeoffs | yes |
| `research-note` | external domain context, literature notes, or problem framing | no |

Project scope levels:

- `system`: cross-cutting repository or product behavior
- `domain`: backend, frontend, AI, ops, or shared domain scope
- `module`: one bounded module or workflow
- `component`: one narrow component or adapter

Approved domains for now:

- `shared`
- `backend`
- `frontend`
- `ai`
- `ops`
- `research`

## Metadata Standard

Apply YAML front matter to all new formal docs in:

- `docs/`
- `backend/docs/`
- `frontend/docs/`

Required fields:

- `id`
- `title`
- `type`
- `level`
- `domain`
- `status`
- `owner`
- `created_at`
- `updated_at`

Strongly recommended fields:

- `last_verified_at`
- `review_by`
- `version`
- `reviewers`
- `source_of_truth`
- `related_issues`
- `related_docs`
- `system`
- `module`
- `supersedes`
- `superseded_by`
- `tags`

Allowed lightweight exceptions:

- `README.md` index files
- short folder guide files
- untouched legacy docs during migration

Current governed baseline:

- `docs/05-policies/documentation-governance.md`
- active source-of-truth docs in `backend/docs/` and `frontend/docs/`
- any new project-level `policy`, `architecture`, `spec`, `guide`, `runbook`,
  `rfc`, or `adr`

Front matter example:

```yaml
---
id: SPEC-2026-001
title: Example Spec
type: spec
level: module
domain: backend
status: active
owner: repo-maintainers
created_at: 2026-04-07
updated_at: 2026-04-07
last_verified_at: 2026-04-07
review_by: 2026-07-07
version: v1
source_of_truth: true
related_issues: [61]
related_docs: []
supersedes: []
superseded_by: []
tags: [example]
---
```

## Lifecycle Model

Shared lifecycle states:

- `draft`
- `review`
- `accepted`
- `implemented`
- `active`
- `deprecated`
- `superseded`
- `archived`

Operational meaning:

- `draft`: not ready to rely on
- `review`: actively being reviewed
- `accepted`: approved, usually for RFC or ADR
- `implemented`: the implementation has landed according to the RFC
- `active`: authoritative current doc
- `deprecated`: still available but no longer preferred
- `superseded`: replaced by a newer doc
- `archived`: historical only

Recommended flows:

- `rfc`: `draft -> review -> accepted -> implemented`
- `adr`: `draft -> review -> active -> superseded`
- `architecture/spec/guide/runbook/policy`: `draft -> review -> active -> deprecated -> superseded -> archived`
- `research-note`: `draft -> active -> archived`

Replacement rule:

1. Do not delete decision-grade docs by default.
2. Mark the old doc `superseded`.
3. Fill `superseded_by`.
4. Link back from the replacement doc with `supersedes`.

## Source of Truth Rules

- Issues track why work exists, current scope, and execution progress.
- Repository docs hold durable knowledge: architecture, contracts, operational
  procedures, and approved decisions.
- Code comments explain local implementation details only.
- For the same contract surface, only one doc may be authoritative with
  `source_of_truth: true`.
- Research notes are context, not implementation authority.
- Secrets, credentials, tokens, and plaintext operational access notes are
  never valid documentation content.

## Storage and Ownership

### Root-level storage model

| Path | Allowed content | Notes |
| --- | --- | --- |
| `docs/05-policies/` | shared governance and policy docs | project-level policy source of truth |
| `docs/10-rfcs/` | project-level RFCs | proposed cross-module changes |
| `docs/20-adrs/` | project-level ADRs | durable decision records |
| `docs/30-architecture/` | shared architecture docs | current cross-module design |
| `docs/40-specs/` | shared specs and contracts | stable shared source of truth |
| `docs/50-guides/` | shared contributor and operator guides | current usage and extension guidance |
| `docs/60-runbooks/` | shared operational runbooks | repeatable procedures |
| `docs/70-postmortems/` | durable incident learnings | historical analysis |
| `docs/90-archive/` | superseded or archived shared docs | retained history |
| `backend/docs/` | backend specs, backend architecture, backend runbooks, backend RFCs and ADRs | backend source of truth |
| `frontend/docs/` | frontend guides, specs, architecture, RFCs and ADRs | frontend source of truth |
| `docs/research/` | external research notes and curated references | not authoritative for implementation |
| `docs/paper/` | supporting research binaries | asset storage only, never source of truth |

### File placement rules

- New project-level policy docs belong in `docs/05-policies/`.
- New project-level RFCs belong in `docs/10-rfcs/`.
- New project-level ADRs belong in `docs/20-adrs/`.
- New shared architecture docs belong in `docs/30-architecture/`.
- New shared specs belong in `docs/40-specs/`.
- New shared guides belong in `docs/50-guides/`.
- New shared runbooks belong in `docs/60-runbooks/`.
- New shared postmortems belong in `docs/70-postmortems/`.
- Superseded shared docs move to `docs/90-archive/` unless a lighter pointer is
  sufficient.
- New backend-only docs belong in `backend/docs/`.
- New frontend-only docs belong in `frontend/docs/`.
- New external domain notes belong in `docs/research/`.
- New files should not be added to ad hoc root-level buckets without first
  updating this policy.

### Naming and indexing rules

- New formal doc filenames use lowercase kebab case.
- Prefer ASCII filenames unless a local module already standardizes on another
  language.
- Use stable topic-based names rather than generic names like `spec-1.md`.
- Each active docs root should have a lightweight `README.md` index when the
  folder contains source-of-truth docs.
- Root and module indexes should link only to current or intentionally retained
  legacy docs.

### Promotion rule

- If a module-local doc becomes the authoritative contract or decision for
  multiple modules, promote it to root `docs/`.
- Leave a pointer in the old module-local location when the old path is already
  referenced by contributors or tooling.
- Do not create parallel authorities for the same contract surface across root
  and module docs.

### Asset rules

- Do not place binary research assets directly in `docs/` root.
- If a binary reference must live in the repo, store it in a dedicated research
  asset folder and make its purpose explicit.
- If the asset is large or replaceable, prefer external storage plus a link.

### Sensitive content rule

- No secrets under `docs/`, `backend/docs/`, or `frontend/docs/`.
- Operational credentials belong in a password manager, secret manager, or
  local-only environment file that is not committed.

### Ownership rule

- Every formal doc must name one accountable owner.
- Shared docs default to `repo-maintainers` until finer ownership exists.
- Backend docs default to the backend maintainer set.
- Frontend docs default to the frontend maintainer set.

### Governance operations

- This policy is required for all new formal docs added on or after
  `2026-04-07`.
- Touched high-value docs should be upgraded during normal work rather than in
  a separate repo-wide rewrite.
- Fast-moving module docs should set `review_by` within 1 to 3 months.
- Stable policy and architecture docs should set `review_by` within 3 to
  6 months unless the surface is unusually volatile.
- Changes that introduce a new doc type, a new docs root, or a new
  source-of-truth surface must update this policy or a linked ADR/RFC in the
  same PR.

## Validation and Automation

Short-term manual checks:

- new formal docs are placed in the correct doc root
- new formal docs include required front matter
- doc indexes are updated when a new governed doc root or active doc is added
- docs do not duplicate the same source-of-truth scope
- PRs do not add secrets or opaque random files into docs roots

Recommended automation after adoption stabilizes:

- front matter validation for new formal docs
- broken-link checks
- `review_by` expiry checks
- duplicate `source_of_truth` detection within the same scope
- secret scanning on docs paths as part of repository-wide security checks

## Rollout Plan

1. Adopt this policy and [`docs/README.md`](../README.md) immediately.
2. Require front matter for all new formal docs and for currently active
   source-of-truth docs in `backend/docs/` and `frontend/docs/`.
3. Add or maintain a lightweight `README.md` index in each docs root that owns
   active governed docs.
4. Reclassify existing docs when they are touched:
   - `backend/docs/api.md` -> backend `spec`
   - `frontend/docs/frontend-plan.md` -> frontend `guide` or `spec`
   - legacy research notes -> `research-note`
5. Migrate legacy research material out of root-level catch-all locations into
   `docs/research/` or external storage.
6. Remove any sensitive operational notes from documentation roots and move
   them to a proper secret-management path.
7. Add automated checks only after at least a few high-value docs follow the
   new contract.

## Open Questions

- Should this policy be advisory only, or required in review for all doc PRs?
- Should research PDFs be versioned in git at all, or replaced with links plus
  short summaries?
- Who is the long-term owner of shared cross-cutting docs across backend and
  frontend?
