# Backend Docs

This directory contains the maintained backend architecture, HTTP contract, and
operations documentation. Proposed work belongs in issues and pull requests,
not in a parallel plan-doc tree.

## Reading Order

1. [`architecture/overview.md`](architecture/overview.md) for ownership and the
   end-to-end research flow.
2. [`specs/api.md`](specs/api.md) for browser and Agent contracts.
3. [`architecture/persistence-model.md`](architecture/persistence-model.md) for
   identities, document ownership, and deletion behavior.
4. [`runbooks/backend-ops.md`](runbooks/backend-ops.md) for local operation and
   verification.

## Code-Owned Neighbors

- [`../application/source/README.md`](../application/source/README.md): current
  Document preparation.
- [`../application/core/README.md`](../application/core/README.md): Objective,
  Evidence, and Finding orchestration.
- [`../application/core/objectives/README.md`](../application/core/objectives/README.md):
  detailed Objective analysis behavior.
- [`../infra/source/README.md`](../infra/source/README.md): parser boundary and
  Source artifacts.
- [`../infra/persistence/README.md`](../infra/persistence/README.md): repository
  ownership.

Shared product and cross-module contracts remain under repository root
[`docs/`](../../docs/README.md).
