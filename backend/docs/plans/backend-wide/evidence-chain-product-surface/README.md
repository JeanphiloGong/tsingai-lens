# Evidence-Chain Product Surface

## Purpose

This topic family records the backend-owned implementation wave for exposing
variant dossiers, result chains, and result-series read models over the
current semantic backbone.

## Authority Boundary

- [`../../../../../docs/decisions/rfc-evidence-chain-product-surface-delivery-roadmap.md`](../../../../../docs/decisions/rfc-evidence-chain-product-surface-delivery-roadmap.md)
  owns the shared delivery order and acceptance ladder
- [`../../../../../docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md`](../../../../../docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md)
  owns the shared additive drilldown contract
- [`../../../specs/api.md`](../../../specs/api.md) remains the long-lived
  backend API authority after the routes land
- this family owns only the backend implementation companion, not the shared
  proposal or contract freeze

## Reading Order

- [`backend-implementation-plan.md`](backend-implementation-plan.md)
  Backend file areas, phases, verification, and backend-local acceptance

## Related Docs

- [`../../core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md`](../../core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md)
- [`../../../../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md`](../../../../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md)
- [`../../../specs/api.md`](../../../specs/api.md)
