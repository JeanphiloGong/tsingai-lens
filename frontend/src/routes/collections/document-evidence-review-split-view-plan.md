# Document Evidence Review Split-View Plan

## Purpose

This document records the frontend-local implementation plan for turning the
document detail page into a source-evidence review workspace.

The document page should not behave as a generic metadata page or as a
standalone PDF reader. Its primary job is to let a researcher compare what the
paper source says with what Lens extracted as evidence chains.

This plan is the concrete document-page child of
[`document-result-evidence-chain-proposal.md`](document-result-evidence-chain-proposal.md).
The parent proposal owns the reading model. This page owns the split-view
layout, interaction model, state model, and acceptance checks for the document
page.

## Review Workspace

The default desktop layout should be a two-column review workspace:

```text
Document Evidence Review
├─ Top bar
│  ├─ paper title, source filename, and return action
│  ├─ optional source mode: parsed text now, PDF later
│  └─ secondary actions such as open result detail or open original source
└─ Split view
   ├─ Left: Source Reader
   │  ├─ full parsed source blocks by default
   │  ├─ PDF facsimile later
   │  ├─ block navigation
   │  ├─ active anchor highlight
   │  └─ source-first reading width
   └─ Right: Evidence Review Panel
      ├─ paper summary
      ├─ traceback status and source anchors
      ├─ variant dossiers
      ├─ result series
      ├─ result chains
      ├─ baseline, test-condition, missing-context cues
      └─ result detail and related result links
```

The right panel may become top-stacked on small screens, but the desktop
acceptance surface should remain side-by-side so source text and extracted
chains can be compared without route switching.

## Source Reader

The left source reader should stay the primary reading surface. It should show
the full parsed paper blocks that are available from the document content
route, not only the excerpt that supports the selected evidence chain.

Required first-slice behavior:

- render parsed `blocks` from the document content route
- provide block navigation for quick movement through the paper
- highlight the active traceback quote or block when available
- keep source-location status and anchor controls in the right evidence panel
- preserve the user's return path to comparison or result drilldown surfaces

PDF rendering should not block the first implementation slice. The page should
use parsed blocks first, then add a PDF mode only after the backend exposes a
stable source-file URL and enough page or bounding-box metadata for useful
navigation.

Future PDF behavior:

- add a PDF source mode when the backend can provide the original source file
  or a safe blob URL
- use page anchors when only page-level precision is available
- use bounding-box highlights when page-region anchors exist
- keep parsed text fallback available because OCR, PDF layout, and figure or
  table precision will not be uniformly reliable

## Evidence Review Panel

The right evidence review panel should organize the paper's extracted chain
model while keeping source-location actions close to each chain.

The first implementation does not need a tab system if a single scrollable
panel is clearer. Whether rendered as cards or tabs, the panel should cover:

- paper overview
- traceback status and source anchors for the selected chain
- variant dossiers
- result series under each dossier
- result chains under each series
- missingness and comparability warnings
- source-location and result-detail actions

## Paper Overview

The overview section should summarize:

- paper scope
- material system
- process route
- primary properties covered
- number of variants
- number of result chains
- paper-level missingness or traceability warnings

## Variant Dossiers

The variant section should list one card per variant dossier.

Each card should show:

- normalized variant label
- material system
- shared process or sample state
- properties covered
- shared evidence summary
- shared missingness badges

Selecting a dossier should expand its child result series without losing the
left source-reader position.

## Result Series

Inside one dossier, result chains should be grouped into series when possible.

Example:

```text
Variant S3 = optimized VED + HIP

Shared state
P=280 W, v=1200 mm/s, h=100 um, t=30 um
HIP=yes

Tensile vs test temperature
25 C  -> YS 940, UTS 1040, EL 15%
400 C -> YS 780, UTS 860, EL 18%
650 C -> YS 520, UTS 610, EL 22%
```

Each row should expose:

- the varying axis value
- primary result values
- baseline label
- comparability status
- missingness or warning badges
- an action to locate source context in the left reader
- an action to open full result detail

## Chain Selection

Clicking a result chain should select that chain and attempt to locate its
supporting source context in the left reader.

Preferred selection flow:

1. Set the selected chain ID.
2. Read `evidence.evidence_ids` and `evidence.direct_anchor_ids` from the
   chain.
3. Fetch traceback for the first usable evidence ID if the needed anchor is not
   already loaded.
4. Select the best anchor by `direct_anchor_ids` first, then by first returned
   anchor.
5. Scroll the left reader to the matching source block.
6. Highlight the quote or active block.
7. Show an explicit source-unavailable message if no source can be resolved.

This interaction should not require opening a result detail page. Result detail
is a deeper drilldown, not the only way to verify the source for a chain.

## Chain Detail

The selected chain should expose a compact detail surface in the right panel or
a drawer. It should show:

- variant summary
- process or sample state
- test condition
- structure or defect evidence
- result values
- baseline
- mechanism claim
- support evidence
- comparability warnings
- source anchors

Each anchor should support direct jump back into the source reader. When the
anchor has only block-level precision, the UI should still scroll to that block
and make the degraded precision visible instead of failing silently.

## First-Slice State Model

The first implementation can use simple page-local state:

```ts
let selectedChainId = '';
let selectedEvidenceId = '';
let selectedAnchorId = '';

$: selectedChain = findChain(variantDossiers, selectedChainId);
$: selectedAnchor =
	traceback?.anchors.find((anchor) => anchor.anchor_id === selectedAnchorId) ?? null;
```

The page should prefer URL parameters for durable navigation when possible:

- `result_id` for selecting a result chain
- `evidence_id` for loading traceback
- `anchor_id` for selecting a source anchor

The URL parameters should be additive to the split-view behavior, not a reason
to turn document reading back into a single-purpose traceback route.

## Implementation Order

1. Convert the document page to a split view with parsed source text on the
   left and evidence review on the right.
2. Move the existing variant dossier and result-series rendering into the right
   evidence review panel.
3. Add chain selection state and a visible selected-chain style.
4. Add `Locate source` behavior that fetches traceback from the chain's first
   usable evidence ID and scrolls or highlights the left source reader.
5. Keep `Open result detail` available as a secondary drilldown action.
6. Keep PDF rendering out of the first slice unless stable source-file URLs and
   anchors already exist.

## Acceptance Checks

The split-view document page is accepted when these checks pass:

- desktop document reading uses a side-by-side source reader and evidence
  review panel
- right panel shows `variant dossier -> result series -> result chain`
- selecting a chain visibly marks it as selected
- selecting a chain attempts to locate source context without leaving the page
- a resolvable anchor scrolls or highlights the left source reader
- an unresolved anchor shows an explicit unavailable state
- each chain still links to result detail for deeper inspection
- mobile layout degrades deliberately instead of hiding either source or
  evidence context

## Related Docs

- [`document-result-evidence-chain-proposal.md`](document-result-evidence-chain-proposal.md)
  Parent reading-model proposal for document and result evidence chains
- [`claim-traceback-navigation-contract.md`](claim-traceback-navigation-contract.md)
  Source-navigation rules for anchor-based document verification
- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
  Collection route-family product hierarchy and broad page responsibilities
