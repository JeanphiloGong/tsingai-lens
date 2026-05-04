# Research View Aggregation Frontend Implementation Plan

## Goal

Implement the frontend side of research-view aggregation so the collection
workspace behaves like a research workbench rather than a raw extraction record
browser.

The first slice should make one completed collection readable through:

- collection overview
- document coverage
- grouped comparison
- paper detail sample matrix
- paper detail condition series
- evidence and debug drilldown

## Current Implementation Status

The first frontend wave is implemented in source.

Implemented:

- `frontend/src/routes/_shared/researchView.ts` owns the browser contract
  helper, normalization, state tone mapping, and evidence-backed value
  formatting.
- Collection shell navigation now exposes the primary tabs as Overview,
  Documents, Comparison, Graph, and More.
- Raw extracted results moved out of primary collection navigation and are
  reachable from More as extracted facts.
- Collection overview attempts to load collection research aggregation and
  renders material systems, process families, variable axes, measured
  properties, coverage counts, and warnings when available.
- Documents tab uses `paper_coverage` as its primary table when research-view
  data is available, with document profiles retained as fallback context while
  the backend endpoint is unavailable.
- Comparison tab uses `comparable_groups` and cross-paper matrix rows as the
  primary view when research-view data is available, with the previous raw
  comparison review retained as fallback/debug behavior.
- Paper detail attempts to load paper research aggregation and renders paper
  overview, sample matrix, condition series, and evidence detail before the
  existing extraction workbench.

Still dependent on backend work:

- Runtime data appears only after the target research-view endpoints are
  implemented.
- Until then, pages explicitly fall back to existing workspace, profile,
  comparison, evidence, and document-detail data.

## Current Owning Seams

Use the current frontend seams directly:

| Concern                   | Owning seam                                                     |
| ------------------------- | --------------------------------------------------------------- |
| Collection shell and tabs | `frontend/src/routes/collections/[id]/+layout.svelte`           |
| Collection overview       | `frontend/src/routes/collections/[id]/+page.svelte`             |
| Collection documents      | `frontend/src/routes/collections/[id]/documents/`               |
| Collection comparisons    | `frontend/src/routes/collections/[id]/comparisons/`             |
| Paper detail              | `frontend/src/routes/collections/[id]/documents/[document_id]/` |
| Shared API helpers        | `frontend/src/routes/_shared/`                                  |
| Route-local tests         | `frontend/src/routes/collections/`                              |

Do not create route-level compatibility pages for old raw-result navigation.
Move the primary UI to the new contract and keep raw fact browsing under
evidence or debug entry points.

## File And Function Change Map

This section records the concrete frontend file and function-level plan for the
first implementation wave.

### New Shared Helper

Add `frontend/src/routes/_shared/researchView.ts`.

Types to add:

```text
ResearchViewState
ResearchViewWarning
EvidenceReference
EvidenceBackedValue
SampleMatrixColumn
SampleMatrixRow
SampleMatrix
ConditionSeriesPoint
ConditionSeries
PaperCoverageRow
ComparableGroup
CrossPaperMatrixRow
CrossPaperMatrix
PaperAggregation
CollectionAggregation
```

Functions to add:

```text
fetchCollectionResearchView(collectionId: string): Promise<CollectionAggregation>
fetchDocumentResearchView(
    collectionId: string,
    documentId: string,
): Promise<PaperAggregation>
normalizeCollectionAggregation(value: unknown, collectionId: string): CollectionAggregation
normalizePaperAggregation(
    value: unknown,
    collectionId: string,
    documentId: string,
): PaperAggregation
normalizeEvidenceBackedValue(value: unknown): EvidenceBackedValue
normalizeSampleMatrix(value: unknown): SampleMatrix
normalizeSampleMatrixRow(value: unknown): SampleMatrixRow | null
normalizeConditionSeries(value: unknown): ConditionSeries | null
normalizeComparableGroup(value: unknown): ComparableGroup | null
normalizeCrossPaperMatrix(value: unknown): CrossPaperMatrix
normalizeResearchWarning(value: unknown): ResearchViewWarning | null
getResearchViewStateTone(state: ResearchViewState): string
hasObservedValue(value: EvidenceBackedValue): boolean
formatEvidenceBackedValue(value: EvidenceBackedValue): string
```

Tests to add:

```text
frontend/src/routes/_shared/researchView.spec.ts
```

The helper should use `requestJson` from
`frontend/src/routes/_shared/api.ts` and same-origin `/api/v1/*` paths only.

### Collection Shell

Modify `frontend/src/routes/collections/[id]/+layout.svelte`.

Current functions and reactive values to update:

```text
resultsVisible
protocolVisible
evidenceHref
moreActive
loadWorkspace()
```

Target changes:

- remove `Results` as a primary tab
- keep primary tabs as `Overview`, `Documents`, `Comparison`, `Graph`, `More`
- make `More` active for evidence, protocol, exports, reports, settings, and
  extraction debug routes
- keep `loadWorkspace()` only for collection status, document count, and
  capability gating
- add research-view links only through the new helper or workspace links, not
  by hardcoding alternate API roots

Translation keys to update in `frontend/src/routes/_shared/i18n.ts`:

```text
collection.tabs.overview
collection.tabs.documents
collection.tabs.comparison
collection.tabs.graph
collection.moreLabel
collection.tabs.evidence
collection.tabs.protocol
```

The old `collection.tabs.results` key may remain only if an existing secondary
route still uses it; it should not drive the primary collection navigation.

### Collection Overview Page

Modify `frontend/src/routes/collections/[id]/+page.svelte`.

Current functions and state to extend:

```text
loadWorkspace()
refreshAll()
startBuildRun()
submitUpload()
readinessTitle()
readinessBody()
surfaceStatusTone()
```

New state and functions:

```text
let researchView: CollectionAggregation | null = null
let researchViewError = ''

async function loadResearchView(showLoading = true)
function overviewWarnings()
function primaryResearchHref()
function coverageSummary()
function formatResearchViewState(state: ResearchViewState)
```

Target changes:

- fetch workspace and collection research view together
- keep upload and build task controls for empty and processing states
- show material systems, process families, variable axes, properties, and
  warnings from `CollectionAggregation.overview`
- make the ready primary action point to `Comparison`
- show partial-state warnings instead of falling back to raw result cards

### Documents Tab

Modify `frontend/src/routes/collections/[id]/documents/+page.svelte`.

Current functions and state to update:

```text
loadProfiles()
displayTitle()
rowStatusKey()
documentMetaParts()
surfaceStatusTone()
```

New state and functions:

```text
let researchView: CollectionAggregation | null = null

async function loadPaperCoverage()
function coverageRows(): PaperCoverageRow[]
function paperDetailHref(row: PaperCoverageRow)
function coverageStateTone(row: PaperCoverageRow)
function issueLabel(row: PaperCoverageRow)
```

Target changes:

- use `CollectionAggregation.paper_coverage` as the primary table
- keep document profiles as fallback context only if the research-view endpoint
  is not ready
- link each row to `/collections/{collectionId}/documents/{documentId}`
- do not render sample matrices or condition series inside this collection tab

### Comparison Tab

Modify `frontend/src/routes/collections/[id]/comparisons/+page.svelte`.

Current functions and state to update:

```text
loadComparisons()
startComparisonGeneration()
updateMaterialRoute()
uniqueSorted()
safeErrorText()
```

New state and functions:

```text
let researchView: CollectionAggregation | null = null
let selectedGroupId = ''
let selectedEvidenceValue: EvidenceBackedValue | null = null

async function loadResearchComparison()
function comparisonGroups(): ComparableGroup[]
function selectedGroup(): ComparableGroup | null
function groupStatusTone(group: ComparableGroup)
function matrixRows(group: ComparableGroup): CrossPaperMatrixRow[]
function openEvidenceDrawer(value: EvidenceBackedValue)
function closeEvidenceDrawer()
```

Target changes:

- render `ComparableGroup` cards or rows as the primary comparison objects
- render the selected group's `CrossPaperMatrix`
- keep fixed conditions, variable axis, comparability status, and warnings
  close to the group
- demote old `fetchComparisons()` raw row list to a fallback or debug-only path
  during the migration

### Paper Detail Page

Modify `frontend/src/routes/collections/[id]/documents/[document_id]/+page.svelte`.

Current functions and state to update:

```text
loadWorkbench()
rebuildWorkbenchModel()
applyRequestedSelection()
selectItem()
ensureTracebackForItem()
```

New state and functions:

```text
let paperAggregation: PaperAggregation | null = null
let selectedMatrixValue: EvidenceBackedValue | null = null

async function loadPaperResearchView()
function sampleMatrixRows(): SampleMatrixRow[]
function conditionSeries(): ConditionSeries[]
function openMatrixEvidence(value: EvidenceBackedValue)
function closeMatrixEvidence()
function matrixCellStatus(value: EvidenceBackedValue)
```

Target changes:

- fetch `PaperAggregation` along with document content and traceback data
- render paper overview before the existing workbench panels
- render `SampleMatrix` as the main paper result surface
- render `ConditionSeries` as grouped series
- keep the existing document reader, source traceback, and structured
  extraction panels as evidence/debug surfaces

### Optional Route Components

Add route-local components only if they keep page files smaller without
creating new contract ownership:

```text
frontend/src/routes/collections/[id]/_components/EvidenceDrawer.svelte
frontend/src/routes/collections/[id]/_components/ResearchStateNotice.svelte
frontend/src/routes/collections/[id]/documents/[document_id]/_components/SampleMatrix.svelte
frontend/src/routes/collections/[id]/documents/[document_id]/_components/ConditionSeriesPanel.svelte
frontend/src/routes/collections/[id]/comparisons/_components/CrossPaperMatrix.svelte
```

These components should receive already-normalized data. They should not fetch
or normalize API payloads themselves.

### Tests To Add Or Extend

| File                                                                                               | Test focus                                                   |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `frontend/src/routes/_shared/researchView.spec.ts`                                                 | helper normalization, state mapping, value formatting        |
| `frontend/src/routes/collections/[id]/workspace-page.svelte.spec.ts`                               | overview ready/partial/processing states and primary action  |
| `frontend/src/routes/collections/[id]/comparisons/comparisons-page.svelte.spec.ts`                 | comparable groups, matrix rendering, evidence drawer opening |
| `frontend/src/routes/collections/[id]/documents/[document_id]/document-detail-page.svelte.spec.ts` | sample matrix, condition series, evidence detail affordance  |

## Phase 1: Shared API Helper And Types

Implementation:

- add frontend types for `CollectionAggregation`, `PaperAggregation`,
  `SampleMatrix`, `ConditionSeries`, `ComparableGroup`,
  `CrossPaperMatrix`, and `EvidenceBackedValue`
- add same-origin API helpers for:
  - `GET /api/v1/collections/{collection_id}/research-view`
  - `GET /api/v1/collections/{collection_id}/documents/{document_id}/research-view`
- keep the helper under `frontend/src/routes/_shared/`
- model `empty`, `processing`, `partial`, `ready`, and `failed` states

Verification:

- type checks pass
- API helpers only call `/api/v1/*`
- helper tests cover ready, partial, empty, and failed payloads

## Phase 2: Collection Navigation

Implementation:

- update the collection shell tabs to:
  - `Overview`
  - `Documents`
  - `Comparison`
  - `Graph`
  - `More`
- remove `Results` as a primary tab
- place evidence, protocol, exports, evaluation reports, and debug surfaces
  under `More`
- keep graph visible but secondary to comparison in product copy and layout

Verification:

- the route shell exposes exactly the five primary tabs
- active states still work for nested routes
- `More` owns evidence/debug/protocol-style secondary links
- no tab label exposes backend object names as the primary user-facing
  navigation

## Phase 3: Collection Overview

Implementation:

- render collection aggregation state, summary counts, readiness, and warnings
- show material systems, process families, variable axes, measured properties,
  and coverage quality
- keep upload/build task controls where they are useful, but do not let them
  obscure research readiness

Verification:

- empty collections show upload action
- processing collections show task progress
- partial collections show warnings and available research surfaces
- ready collections point to `Comparison` as the primary research action

## Phase 4: Documents Tab

Implementation:

- render `PaperCoverageRow` as the document list table
- include paper state, sample count, process parameter count, measurement
  count, condition count, evidence count, and issue count
- link each paper to its paper detail research view
- avoid duplicating paper-specific sample matrices inside the collection
  documents tab

Verification:

- each document row has a clear state and issue signal
- clicking a document opens paper detail
- the documents tab answers paper coverage, not paper-level analysis

## Phase 5: Comparison Tab

Implementation:

- render `ComparableGroup` as the main comparison object
- let the user inspect the group's cross-paper matrix
- keep fixed conditions, variable axis, property, comparability status, and
  warnings visible
- open evidence details from matrix cells
- treat condition series as trends when they span the group

Verification:

- raw `measurement_results` are not rendered as the primary result cards
- groups can be filtered or scanned by material, process, property, and status
- matrix values can open evidence detail or show missing-evidence warnings

## Phase 6: Paper Detail Research View

Implementation:

- fetch `PaperAggregation` for document detail
- render paper overview first
- render `SampleMatrix` as the primary paper result surface
- render `ConditionSeries` as grouped series, not separate scalar result cards
- keep evidence and extraction debug reachable as secondary paper views

Verification:

- P001-style paper shows one row per real sample
- core property values appear as matrix cells
- duplicate raw facts are represented inside cell evidence details
- generic material or process concepts do not appear as sample rows

## Phase 7: Evidence Drawer And Debug Placement

Implementation:

- build a shared evidence drawer or panel for matrix cells, series points, and
  comparable group rows
- show source text/table context, evidence ids, fact ids, confidence, duplicate
  count, conflicts, and missing fields
- move the current extracted-record browser to a debug or evidence route under
  `More`

Verification:

- every observed value has a visible traceback affordance
- missing evidence renders as a warning, not a broken interaction
- debug records remain reachable but are no longer the primary collection
  result page

## Phase 8: Frontend Tests

Implementation:

- add route-local tests for navigation and state rendering
- add unit tests for API helper normalization
- update existing workspace tests where the old primary result tab assumption
  changes

Suggested commands:

```bash
cd frontend
npm run check
npm run test:unit -- --run
```

Use Playwright only when the implementation changes browser interaction beyond
unit-test coverage.

## Exit Criteria

The frontend topic is complete when:

- collection primary navigation is `Overview / Documents / Comparison / Graph / More`
- collection overview and documents tab render aggregation contract data
- comparison tab renders comparable groups and cross-paper matrices
- paper detail renders sample matrices and condition series
- raw extracted records are demoted to evidence/debug surfaces
- loading, empty, partial, ready, and failed states are explicit
