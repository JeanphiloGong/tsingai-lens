# Repository Documentation Governance

## Governance Goal

Establish a lightweight documentation system so durable knowledge has:

- a clear location
- a named owner
- a visible source-of-truth boundary
- a readable start path for contributors

This policy governs repository docs, not every possible project artifact.

## Current Model

The repository uses a three-layer documentation model:

- root `README.md`
  repository landing page and quick orientation
- root `docs/`
  shared or cross-module knowledge only
- module and node docs
  `backend/README.md`, `frontend/README.md`, module-local `docs/`, and
  code-owned `README.md` entry pages

The root shared docs tree stays intentionally small:

- `docs/governance.md`
- `docs/overview/`
- `docs/architecture/`
- `docs/contracts/`
- `docs/decisions/`
- `docs/research/`

Supporting research binaries belong under `docs/research/assets/`.

## Document Types

| Type | Purpose | Source of truth |
| --- | --- | --- |
| `policy` | repository rules such as doc governance and file placement | yes |
| `architecture` | current design of a system, domain, or module | yes |
| `spec` | stable contract such as API behavior or state behavior | yes |
| `guide` | human-facing usage, extension, or contributor instructions | yes |
| `runbook` | repeatable operational procedure | yes |
| `rfc` | proposed change before or during implementation | no, until accepted |
| `adr` | durable record of a decision and its tradeoffs | yes |
| `postmortem` | durable incident learning | yes |
| `research-note` | external domain context, literature notes, or problem framing | no |

Project scope levels:

- `system`
- `domain`
- `module`
- `component`

## Document Header Rule

Do not add YAML front matter to repository docs by default.

Formal docs should usually:

- start directly with an H1
- use intent-appropriate sections in the body
- keep status, ownership, and source-of-truth notes in prose only when they
  help the reader or an operational workflow

Front matter is only acceptable when a specific renderer, generator, or
automation workflow actually consumes it.

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

Recommended flows:

- `rfc`: `draft -> review -> accepted -> implemented`
- `adr`: `draft -> review -> active -> superseded`
- `architecture/spec/guide/runbook/policy`: `draft -> review -> active -> deprecated -> superseded -> archived`
- `research-note`: `draft -> active -> archived`

Replacement rule:

1. Do not delete decision-grade docs by default.
2. Mark the old doc as superseded in body prose when replacement context matters.
3. Link forward to the replacement doc.
4. Link back from the replacement doc when lineage matters.

## Source of Truth Rules

- Issues track why work exists, current scope, and delivery progress.
- Repository docs hold durable knowledge: architecture, contracts, operational
  procedure, and approved decisions.
- Code comments explain local implementation detail only.
- For the same contract surface, there should be one authoritative doc path.
- Research notes are context, not implementation authority.
- Secrets and plaintext credentials are never valid documentation content.

## Storage and Ownership

### Root-level storage model

| Path | Allowed content | Notes |
| --- | --- | --- |
| `docs/governance.md` | shared documentation governance and placement rules | project-level doc policy source of truth |
| `docs/overview/` | shared system overview, product framing, and orientation docs | start here for cross-module understanding |
| `docs/architecture/` | shared architecture and current-state boundary docs | current cross-module design only |
| `docs/contracts/` | shared product and artifact contracts | stable shared source of truth |
| `docs/decisions/` | shared RFCs, ADRs, and postmortems | use filename prefixes such as `rfc-`, `adr-`, or `postmortem-` |
| `docs/research/` | external research notes and curated references | not authoritative for implementation |
| `docs/research/assets/` | supporting research binaries | asset storage only, never source of truth |
| `backend/README.md` | backend module purpose, boundary, and navigation | primary backend entry page |
| `frontend/README.md` | frontend module purpose, boundary, and navigation | primary frontend entry page |
| `<owned-node>/README.md` | local node purpose, boundary, and navigation | only for real code-owned seams |
| `backend/docs/` | backend formal specs, architecture docs, runbooks, ADRs | backend formal-doc source of truth |
| `frontend/docs/` | frontend formal guides, specs, architecture docs, ADRs | frontend formal-doc source of truth |

### File placement rules

- New shared governance changes belong in `docs/governance.md` unless the
  governance surface becomes large enough to justify a child doc.
- New shared orientation, framing, or reader-start docs belong in
  `docs/overview/`.
- New shared architecture or current-state docs belong in `docs/architecture/`.
- New shared product or artifact contracts belong in `docs/contracts/`.
- New shared RFCs, ADRs, and postmortems belong in `docs/decisions/` with a
  filename prefix that exposes the subtype.
- Superseded shared docs may move to `docs/archive/` when historical retention
  needs a dedicated shelf; do not pre-create archive buckets for symmetry
  alone.
- Backend module purpose and navigation belong in `backend/README.md`.
- Frontend module purpose and navigation belong in `frontend/README.md`.
- Node-local purpose and navigation belong in `<node>/README.md`.
- New backend-only formal docs belong in `backend/docs/`.
- New frontend-only formal docs belong in `frontend/docs/`.
- New external domain notes belong in `docs/research/`.
- Supporting research binaries belong in `docs/research/assets/`.
- Shared operational procedures should stay with the owning module unless they
  are truly cross-module and durable enough to justify their own shared shelf.
- New files should not be added to ad hoc root-level buckets without first
  updating this policy.

### Naming and indexing rules

- New formal doc filenames use lowercase kebab case.
- Prefer ASCII filenames unless a local module already standardizes otherwise.
- Use stable topic-based names rather than generic names such as `spec-1.md`.
- Use filename prefixes in `docs/decisions/` so readers can identify the
  decision subtype before opening the file.
- Root `docs/` keeps a lightweight `README.md` index.
- `backend/README.md` and `frontend/README.md` are the primary module entry
  pages.
- Local `docs/README.md` is optional and should only be added when that local
  docs subtree needs a real secondary index.
- Root and module entry pages should link only to current or intentionally
  retained legacy docs.
- Do not create a new top-level shared docs bucket until multiple durable docs
  and a distinct reading path justify it.

### Promotion rule

- If a module-local doc becomes the authoritative contract or decision for
  multiple modules, promote it to root `docs/`.
- Leave a pointer in the old module-local location when the old path is
  already referenced by contributors or tooling.
- Do not create parallel authorities for the same contract surface across root
  and module docs.

### Asset rules

- Do not place binary research assets directly in `docs/` root.
- If a binary reference must live in the repo, store it in
  `docs/research/assets/` and make its purpose explicit.
- If the asset is large or replaceable, prefer external storage plus a link.

### Sensitive content rule

- No secrets under `docs/`, `backend/docs/`, or `frontend/docs/`.
- Operational credentials belong in a password manager, secret manager, or
  local-only environment file that is not committed.
- Research assets do not relax the sensitive-content rule.

### Ownership rule

- Every formal doc should have one accountable owner in practice, even if that
  owner is only stated in prose or team convention.
- Shared docs default to `repo-maintainers` until finer ownership exists.
- Backend docs default to the backend maintainer set.
- Frontend docs default to the frontend maintainer set.

## Governance Operations

- Apply this policy to all new formal docs now.
- Upgrade touched high-value docs during normal work rather than through a
  perpetual repo-wide rewrite.
- Any change that introduces a new doc type, a new shared docs root, or a new
  source-of-truth surface must update this policy in the same change.

## Validation and Automation

Short-term checks:

- new formal docs are placed in the correct doc root
- shared indexes are updated when discoverability changes
- docs do not duplicate the same source-of-truth scope
- docs trees do not accumulate secrets or opaque random files

Implemented automation baseline:

- `scripts/check_docs_governance.py` validates local markdown links
- `scripts/check_docs_governance.py` validates selected node-local `README.md`
  entry pages
- `scripts/check_docs_governance.py` blocks suspicious docs-path filenames and
  high-signal secret patterns
