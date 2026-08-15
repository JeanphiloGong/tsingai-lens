# Backend Docs

This directory contains the maintained backend-wide architecture, HTTP
contract, and operations documentation. Use [../README.md](../README.md) for
the module overview and local setup summary.

Implementation tasks and migration sequencing are tracked in GitHub issues and
pull requests. They are not maintained as a second source of truth here.

## Start Here

- Runtime setup and recovery:
  [`runbooks/backend-ops.md`](runbooks/backend-ops.md)
- Public HTTP contract:
  [`specs/api.md`](specs/api.md)
- Backend ownership and main flow:
  [`architecture/overview.md`](architecture/overview.md)
- Persistence identities and build lineage:
  [`architecture/persistence-model.md`](architecture/persistence-model.md)

## Runtime Flow

- General pipeline runtime and mode configuration:
  [`../application/pipeline/README.md`](../application/pipeline/README.md)
- Collection build graph, node order, and execution state:
  [`../application/pipeline/collection_build/README.md`](../application/pipeline/collection_build/README.md)
- Source parser/runtime ownership:
  [`../infra/source/README.md`](../infra/source/README.md)
- Podman deployment and service startup:
  [`../../deploy/README.md`](../../deploy/README.md)

## Architecture

- [`architecture/overview.md`](architecture/overview.md)
  Backend-wide boundaries and runtime flow
- [`architecture/persistence-model.md`](architecture/persistence-model.md)
  Implemented PostgreSQL, object-storage, scratch, identity, and build-lineage
  model
- [`architecture/core-comparison/README.md`](architecture/core-comparison/README.md)
  Comparison-semantic substrate and current read paths
- [`architecture/goal-core-source-layering.md`](architecture/goal-core-source-layering.md)
  Goal, Source, Core, consumer, and derived responsibility boundaries
- [`architecture/domain-architecture.md`](architecture/domain-architecture.md)
  Backend business-domain ownership map
- [`architecture/application-layer-boundary.md`](architecture/application-layer-boundary.md)
  Controller, application, domain, and infrastructure dependency direction

## Scope

- Keep backend-wide contracts, current architecture, and operations guidance in
  this directory.
- Keep package-local purpose and navigation beside the owning code in a local
  `README.md`.
- Keep shared product and cross-module contracts in the repository root
  [`docs/`](../../docs/README.md).
- Track proposed work, task breakdowns, and delivery history in GitHub issues
  and pull requests.
