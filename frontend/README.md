# TsingAI-Lens Frontend

The frontend is a SvelteKit browser application for collection creation,
workspace browsing, file upload, task polling, graph export, protocol browsing,
and report access through the same-origin `/api/*` and `/api/v1/*` contract.

This file is the frontend module entry page. Formal frontend docs live in
`frontend/docs/`. Shared route ownership seams use local `README.md` files next
to code.

## Ownership Map

- `src/routes/+page.svelte`
  Home page and collection list flow
- `src/routes/collections/`
  Collection workspace route family
- `src/routes/_shared/`
  Shared browser-side API clients, i18n, graph helpers, and route support code
- `docs/frontend-plan.md`
  Same-origin browser contract and product-flow guide
- `e2e/`
  Browser end-to-end tests

## Key Docs

- [`docs/frontend-plan.md`](docs/frontend-plan.md)
  Frontend same-origin API integration guide
- [`src/routes/collections/lens-v1-interface-spec.md`](src/routes/collections/lens-v1-interface-spec.md)
  Lens v1 collection UI migration spec for workspace, comparisons, evidence,
  documents, protocol, and graph surfaces
- [`src/routes/collections/collection-ui-restructure-proposal.md`](src/routes/collections/collection-ui-restructure-proposal.md)
  Narrow proposal for collection UI information architecture, state machine,
  and page hierarchy cleanup after the first Lens v1 frontend wave
- [`src/routes/_shared/README.md`](src/routes/_shared/README.md)
  Shared route helper ownership and boundaries
- [`src/routes/collections/README.md`](src/routes/collections/README.md)
  Collection workspace route ownership and boundaries

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
- Shared API helpers live under `src/routes/_shared/`.
- Retired debug-style routes remain explanatory only and should not introduce
  alternate browser contracts.
