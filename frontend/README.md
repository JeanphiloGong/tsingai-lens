# TsingAI-Lens Frontend

The frontend is a SvelteKit browser application for collection creation,
independent paper preparation, ready-paper selection, Objective discovery and
analysis, published Finding comparison, Objective Evidence Map inspection, and exact Source
verification through the same-origin `/api/*` and `/api/v1/*` contract.

This file is the frontend module entry page. Formal frontend docs live in
`frontend/docs/`. Shared route ownership seams use local `README.md` files next
to code.

## Ownership Map

- `src/routes/+page.svelte`
  Home page and collection list flow
- `src/routes/+layout.svelte`
  Global Research Agent launcher; outside a collection it asks the user to
  select the collection that defines the research workspace.
- `src/routes/collections/`
  Collection paper, Objective, Finding, Evidence Map, and Source route family
- `src/routes/_shared/`
  Shared browser-side API clients, i18n, and route support code
- `docs/frontend-plan.md`
  Same-origin browser contract and product-flow guide
- `e2e/`
  Browser end-to-end tests

## Key Docs

- [`docs/frontend-plan.md`](docs/frontend-plan.md)
  Frontend same-origin API integration guide
- [`docs/research-agent-chat.md`](docs/research-agent-chat.md)
  Collection-bound Research Agent Chat and approval presentation contract
- [`src/routes/collections/lens-v1-interface-spec.md`](src/routes/collections/lens-v1-interface-spec.md)
  Maintained Lens v1 collection interface for papers, Objectives, published
  Findings, and Source documents
- [`src/routes/collections/collection-ui-restructure-proposal.md`](src/routes/collections/collection-ui-restructure-proposal.md)
  Narrow proposal for collection UI information architecture, state machine,
  and page hierarchy cleanup after the first Lens v1 frontend wave
- [`src/routes/_shared/README.md`](src/routes/_shared/README.md)
  Shared route helper ownership and boundaries
- [`src/routes/collections/README.md`](src/routes/collections/README.md)
  Collection route ownership and boundaries

## Local Development

```bash
cd frontend
npm install
npm run dev
```

## Commands

```bash
npm run dev
npm run build
npm run preview
npm run check
npm run lint
npm run test:unit -- --run
npm run test:e2e
```

## Frontend Contract Rules

- Browser requests must stay on same-origin `/api/*` and `/api/v1/*`.
- Research Agent Chat requires a collection but does not wait for Objective
  discovery or every paper preparation to finish. Data-backed capabilities report
  unavailable collection artifacts explicitly while processing continues.
- Upload and per-paper preparation remain available independently. Ready papers
  may be selected for Objective discovery or analysis while other papers are
  processing or failed.
- Objective discovery and analysis send exact `document_ids`; the browser never
  infers a hidden all-Collection scope.
- Shared API helpers live under `src/routes/_shared/`.
- The collection Evidence Map is a read-only projection of one published
  Objective analysis. It does not use the retired collection-wide Graph API or
  restore a Graph persistence model.
- Retired debug-style routes remain explanatory only and should not introduce
  alternate browser contracts.
