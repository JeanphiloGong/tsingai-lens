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

The default desktop layout should be a three-column review workspace when
screen width allows it:

```text
Document Evidence Review
├─ Top bar
│  ├─ paper title, source filename, and return action
│  ├─ optional source mode: parsed text now, PDF later
│  └─ secondary actions such as open result detail or open original source
└─ Review view
   ├─ Left: Source Reader
   │  ├─ continuous parsed paper text by default
   │  ├─ PDF facsimile later
   │  ├─ unique section navigation
   │  ├─ active quote or anchor highlight
   │  └─ source-first reading width
   ├─ Middle: Evidence Review Panel
      ├─ paper summary
      ├─ traceback status and source anchors
      ├─ variant dossiers
      ├─ result series
      ├─ result chains
      ├─ baseline, test-condition, missing-context cues
      └─ result detail and related result links
   └─ Right: Local Evidence Graph
      ├─ selected material
      ├─ selected variant or sample state
      ├─ selected result chain
      ├─ baseline and traceability state
      └─ selected source anchor
```

The local graph should collapse below the source and evidence columns on medium
screens, and all regions should stack on small screens. The desktop acceptance
surface should keep source text, extracted chains, and the selected local graph
visible without route switching.

## Source Reader

The left source reader should stay the primary reading surface. It should show
the full parsed paper text available from the document content route, not only
the excerpt that supports the selected evidence chain.

`blocks` are backend locator units. They should not be presented as the main
reader model, and the UI should not create one visible card or navigation chip
per block. A block can still provide an internal scroll target, degraded
precision fallback, or anchor boundary, but users should experience the source
as a coherent paper.

Required first-slice behavior:

- render `content_text` from the document content route as continuous source
  text
- derive section navigation from unique `heading_path` values or true heading
  blocks, rather than from every paragraph block
- highlight the active traceback range or quote when available
- keep source-location status and anchor controls in the right evidence panel
- preserve the user's return path to comparison or result drilldown surfaces

Traceback highlight order:

1. Use `char_range` when the traceback response provides it.
2. If `char_range` is unavailable, search for the returned `quote` inside
   `content_text`.
3. If the quote cannot be found globally, use `block_id` as a fallback scroll
   target and show that the location is block-level only.
4. If no source location can be resolved, keep the document open and show an
   explicit source-unavailable state.

PDF rendering should not block the first implementation slice. The page should
use continuous parsed text first, then add a PDF mode only after the backend
exposes a stable source-file URL and enough page or bounding-box metadata for
useful navigation.

Future PDF behavior:

- add a PDF source mode when the backend can provide the original source file
  or a safe blob URL
- use page anchors when only page-level precision is available
- use bounding-box highlights when page-region anchors exist
- keep parsed text fallback available because OCR, PDF layout, and figure or
  table precision will not be uniformly reliable

Review papers need additional care. When the document profile is `review`, the
reader can still support source verification, but the frontend should avoid
framing review-derived, weakly bound rows as clean comparable experimental
results. Backend filtering or marking should prevent review-summary claims
from appearing as normal comparison rows by default.

## Evidence Review Panel

The middle evidence review panel should organize the paper's extracted chain
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

## Local Evidence Graph

The right local graph should be a compact relationship view for the selected
result chain, not a whole-collection graph.

Required first-slice behavior:

- derive the graph directly from backend-authored variant dossiers and result
  chains
- show material, variant, result value, result series, baseline, and source
  anchor nodes
- fall back to the first available chain when no chain is selected
- avoid adding a graph library until node interactions or layout complexity
  justify it
- keep the graph secondary to source verification and evidence review

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
supporting source context in the left reader without exposing locator blocks as
the primary UI object.

Preferred selection flow:

1. Set the selected chain ID.
2. Read `evidence.evidence_ids` and `evidence.direct_anchor_ids` from the
   chain.
3. Fetch traceback for the first usable evidence ID if the needed anchor is not
   already loaded.
4. Select the best anchor by `direct_anchor_ids` first, then by first returned
   anchor.
5. Scroll the left reader to the matching character range or quote.
6. Highlight the quote in the continuous source text.
7. Fall back to block-level scrolling only when range and quote resolution are
   unavailable.
8. Show an explicit source-unavailable message if no source can be resolved.

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
anchor has only block-level precision, the UI should still scroll near that
source region and make the degraded precision visible instead of failing
silently. The block ID itself should remain an implementation detail unless it
is needed for diagnostics.

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

1. Convert the document page to a split view with continuous parsed source text
   on the left and evidence review on the right.
2. Move the existing variant dossier and result-series rendering into the right
   evidence review panel.
3. Add chain selection state and a visible selected-chain style.
4. Replace per-block navigation with unique section navigation derived from
   headings or heading paths.
5. Add `Locate source` behavior that fetches traceback from the chain's first
   usable evidence ID and highlights by `char_range`, then `quote`, then
   block-level fallback.
6. Keep `Open result detail` available as a secondary drilldown action.
7. Keep PDF rendering out of the first slice unless stable source-file URLs and
   anchors already exist.
8. Coordinate with backend follow-up work so review documents do not produce
   normal comparison rows from review-summary claims by default.

## Acceptance Checks

The split-view document page is accepted when these checks pass:

- desktop document reading uses a side-by-side source reader and evidence
  review panel
- the source reader shows continuous paper text instead of one visible card per
  backend block
- section navigation does not repeat the same heading for every paragraph under
  that heading
- right panel shows `variant dossier -> result series -> result chain`
- selecting a chain visibly marks it as selected
- selecting a chain attempts to locate source context without leaving the page
- a resolvable anchor highlights the matching range or quote in the left source
  reader
- an unresolved anchor shows an explicit unavailable state
- each chain still links to result detail for deeper inspection
- mobile layout degrades deliberately instead of hiding either source or
  evidence context
- review documents do not appear to offer clean comparable experimental rows
  when their results are review-summary or weakly material-bound claims

## Related Docs

- [`document-result-evidence-chain-proposal.md`](document-result-evidence-chain-proposal.md)
  Parent reading-model proposal for document and result evidence chains
- [`claim-traceback-navigation-contract.md`](claim-traceback-navigation-contract.md)
  Source-navigation rules for anchor-based document verification
- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
  Collection route-family product hierarchy and broad page responsibilities
