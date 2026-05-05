# Research View Aggregation Frontend Implementation Plan

## Goal

Implement the frontend side of research-view aggregation so the collection
workspace behaves like a research workbench rather than a raw extraction record
browser.

The product target is material-centric. A completed collection should be
readable through:

- collection overview
- material summaries
- material profile pages
- paper coverage
- material-scoped comparison
- paper detail sample matrix
- paper detail material views
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
- Documents tab uses `paper_coverage` from research-view directly. It no
  longer renders the old document-profile list on this page.
- Comparison tab uses `comparable_groups` and cross-paper matrix rows from
  research-view directly. It no longer renders the previous raw comparison
  review on this page.
- Paper detail attempts to load paper research aggregation and renders paper
  overview, sample matrix, condition series, and evidence detail before the
  existing extraction workbench. If paper aggregation is unavailable, the page
  renders an explicit unavailable state instead of making the old workbench the
  main page.

Target material-centric update:

- Collection shell navigation should become Overview, Materials, Papers,
  Graph, and More.
- `Materials` should become the primary research entry and list canonical
  materials with aliases merged.
- Material detail should render the material profile: overview, papers, sample
  matrix, process ranges, property summaries, comparisons, condition series,
  and evidence.
- `Papers` should replace the `Documents` label in primary navigation while
  keeping paper coverage and paper detail entry behavior.
- Global comparison browsing should move to `More / All Comparisons`.

Runtime dependency:

- Collection papers and global all-comparisons pages require the collection
  research-view endpoint.
- Collection materials pages require the material-list and material-profile
  endpoints.
- Paper detail requires the paper research-view endpoint for the primary paper
  result surface.
- Paper detail may use document-scoped material endpoints when the UI needs a
  direct material drilldown inside one paper. That drilldown remains local to
  the document and does not replace collection material profiles.
- Raw extracted facts and old evidence/debug views remain secondary surfaces
  under More or inside the document workbench. They do not replace the
  research-view pages when the aggregation endpoint is unavailable.

## Current Owning Seams

Use the current frontend seams directly:

| Concern                   | Owning seam                                                     |
| ------------------------- | --------------------------------------------------------------- |
| Collection shell and tabs | `frontend/src/routes/collections/[id]/+layout.svelte`           |
| Collection overview       | `frontend/src/routes/collections/[id]/+page.svelte`             |
| Collection materials      | `frontend/src/routes/collections/[id]/materials/`               |
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
MaterialSummary
MaterialPaperCoverage
ProcessParameterRange
PropertySummary
MaterialProfile
PaperMaterialSummary
DocumentMaterialProfile
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
fetchCollectionMaterials(collectionId: string): Promise<MaterialSummary[]>
fetchMaterialResearchView(
    collectionId: string,
    materialId: string,
): Promise<MaterialProfile>
fetchDocumentResearchView(
    collectionId: string,
    documentId: string,
): Promise<PaperAggregation>
fetchDocumentMaterials(collectionId: string, documentId: string): Promise<PaperMaterialSummary[]>
fetchDocumentMaterialResearchView(
    collectionId: string,
    documentId: string,
    materialId: string,
): Promise<DocumentMaterialProfile>
normalizeCollectionAggregation(value: unknown, collectionId: string): CollectionAggregation
normalizeMaterialSummary(value: unknown): MaterialSummary | null
normalizeMaterialProfile(
    value: unknown,
    collectionId: string,
    materialId: string,
): MaterialProfile
normalizePaperAggregation(
    value: unknown,
    collectionId: string,
    documentId: string,
): PaperAggregation
normalizePaperMaterialSummary(value: unknown): PaperMaterialSummary | null
normalizeDocumentMaterialProfile(
    value: unknown,
    collectionId: string,
    documentId: string,
    materialId: string,
): DocumentMaterialProfile
normalizeEvidenceBackedValue(value: unknown): EvidenceBackedValue
normalizeSampleMatrix(value: unknown): SampleMatrix
normalizeSampleMatrixRow(value: unknown): SampleMatrixRow | null
normalizeConditionSeries(value: unknown): ConditionSeries | null
normalizeComparableGroup(value: unknown): ComparableGroup | null
normalizeCrossPaperMatrix(value: unknown): CrossPaperMatrix
normalizeProcessParameterRange(value: unknown): ProcessParameterRange | null
normalizePropertySummary(value: unknown): PropertySummary | null
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
- keep primary tabs as `Overview`, `Materials`, `Papers`, `Graph`, `More`
- make `More` active for evidence, protocol, exports, reports, settings, and
  extraction debug routes
- make `More` active for the global `All Comparisons` route
- keep `loadWorkspace()` only for collection status, document count, and
  capability gating
- add research-view links only through the new helper or workspace links, not
  by hardcoding alternate API roots

Translation keys to update in `frontend/src/routes/_shared/i18n.ts`:

```text
collection.tabs.overview
collection.tabs.materials
collection.tabs.papers
collection.tabs.graph
collection.moreLabel
collection.more.allComparisons
collection.tabs.evidence
collection.tabs.protocol
```

The old `collection.tabs.results`, `collection.tabs.documents`, and
`collection.tabs.comparison` keys may remain only if existing secondary routes
still use them. They should not drive the primary collection navigation.

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
- make the ready primary action point to `Materials`
- show partial-state warnings instead of falling back to raw result cards

### Materials Tab

Add `frontend/src/routes/collections/[id]/materials/+page.svelte`.

New state and functions:

```text
let materials: MaterialSummary[] = []
let materialsError = ''

async function loadMaterials()
function materialHref(material: MaterialSummary)
function materialStateTone(material: MaterialSummary)
function materialEvidenceLabel(material: MaterialSummary)
```

Target behavior:

- fetch `/api/v1/collections/{collection_id}/materials`
- render one row or card per canonical material
- show aliases, paper count, sample count, process families, measured
  properties, comparison count, evidence coverage, state, and warnings
- link each material to `/collections/{collectionId}/materials/{materialId}`
- render explicit loading, empty, partial, failed, and unavailable states
- do not show global comparison groups as the primary content of this page

### Material Detail Page

Add `frontend/src/routes/collections/[id]/materials/[material_id]/+page.svelte`.

New state and functions:

```text
let materialProfile: MaterialProfile | null = null
let selectedEvidenceValue: EvidenceBackedValue | null = null

async function loadMaterialProfile()
function materialPapers(): MaterialPaperCoverage[]
function materialSampleRows(): SampleMatrixRow[]
function processRanges(): ProcessParameterRange[]
function propertySummaries(): PropertySummary[]
function materialComparisonGroups(): ComparableGroup[]
function materialConditionSeries(): ConditionSeries[]
function openEvidenceDrawer(value: EvidenceBackedValue)
function closeEvidenceDrawer()
```

Target behavior:

- render material overview first, including canonical name and aliases
- render papers using the material
- render the material-scoped sample matrix
- render process-parameter ranges and property summaries
- render comparisons as a module inside the material profile
- render condition series for the material
- keep evidence drawer and debug links available from the profile
- show warnings for weak material binding instead of hiding uncertainty

### Papers Tab

Modify `frontend/src/routes/collections/[id]/documents/+page.svelte`, or move
the primary route to `frontend/src/routes/collections/[id]/papers/+page.svelte`
if route names are updated with the tab label.

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
- render an explicit loading, empty, or error state when the research-view
  endpoint is not ready
- link each row to `/collections/{collectionId}/documents/{documentId}`
- do not render sample matrices or condition series inside this collection tab

### More / All Comparisons

Modify `frontend/src/routes/collections/[id]/comparisons/+page.svelte` as the
global all-comparisons browser under `More`, or move it under a `more`
subroute if the route tree is renamed.

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

- render `ComparableGroup` cards or rows as an advanced global comparison
  browser
- render the selected group's `CrossPaperMatrix`
- keep fixed conditions, variable axis, comparability status, and warnings
  close to the group
- keep old `fetchComparisons()` raw-row browsing outside this page; it belongs
  only to secondary evidence/debug routes
- do not keep this route as a top-level primary navigation tab

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
let selectedPaperMaterialId = ''
let selectedMatrixValue: EvidenceBackedValue | null = null

async function loadPaperResearchView()
function paperMaterials(): PaperMaterialSummary[]
function selectedPaperMaterial(): PaperMaterialSummary | null
function sampleMatrixRows(): SampleMatrixRow[]
function conditionSeries(): ConditionSeries[]
function selectPaperMaterial(materialId: string)
function openMatrixEvidence(value: EvidenceBackedValue)
function closeMatrixEvidence()
function matrixCellStatus(value: EvidenceBackedValue)
```

Target changes:

- fetch `PaperAggregation` along with document content and traceback data
- render paper overview before the existing workbench panels
- render detected paper materials as a document-scoped research entry when
  available
- let users inspect "Material In This Paper" without entering the collection
  material profile
- render `SampleMatrix` as the main paper result surface
- render `ConditionSeries` as grouped series
- keep paper material selection scoped to the current `document_id`; do not
  merge aliases across papers or show cross-paper trends in this page
- keep the existing document reader, source traceback, and structured
  extraction panels as evidence/debug surfaces

### Optional Route Components

Add route-local components only if they keep page files smaller without
creating new contract ownership:

```text
frontend/src/routes/collections/[id]/_components/EvidenceDrawer.svelte
frontend/src/routes/collections/[id]/_components/ResearchStateNotice.svelte
frontend/src/routes/collections/[id]/materials/_components/MaterialSummaryList.svelte
frontend/src/routes/collections/[id]/materials/[material_id]/_components/MaterialProfileSections.svelte
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
| `frontend/src/routes/collections/[id]/materials/materials-page.svelte.spec.ts`                     | material summaries, alias display, profile links             |
| `frontend/src/routes/collections/[id]/materials/material-detail-page.svelte.spec.ts`               | material profile modules, material-scoped comparisons        |
| `frontend/src/routes/collections/[id]/comparisons/comparisons-page.svelte.spec.ts`                 | advanced all-comparisons browser, matrix rendering, evidence drawer opening |
| `frontend/src/routes/collections/[id]/documents/[document_id]/document-detail-page.svelte.spec.ts` | sample matrix, condition series, evidence detail affordance  |

## Phase 1: Shared API Helper And Types

Implementation:

- add frontend types for `CollectionAggregation`, `PaperAggregation`,
  `MaterialSummary`, `MaterialProfile`, `PaperMaterialSummary`,
  `DocumentMaterialProfile`, `SampleMatrix`, `ConditionSeries`,
  `ComparableGroup`, `CrossPaperMatrix`, and `EvidenceBackedValue`
- add same-origin API helpers for:
  - `GET /api/v1/collections/{collection_id}/research-view`
  - `GET /api/v1/collections/{collection_id}/materials`
  - `GET /api/v1/collections/{collection_id}/materials/{material_id}/research-view`
  - `GET /api/v1/collections/{collection_id}/documents/{document_id}/research-view`
  - optional `GET /api/v1/collections/{collection_id}/documents/{document_id}/materials`
  - optional `GET /api/v1/collections/{collection_id}/documents/{document_id}/materials/{material_id}/research-view`
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
  - `Materials`
  - `Papers`
  - `Graph`
  - `More`
- remove `Results` as a primary tab
- remove `Comparison` as a primary tab
- place evidence, protocol, exports, evaluation reports, and debug surfaces
  under `More`
- place global all-comparisons browsing under `More`
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
- ready collections point to `Materials` as the primary research action

## Phase 4: Materials Tab

Implementation:

- render `MaterialSummary` rows or cards as the primary collection research
  entry
- show aliases, paper count, sample count, processes, measured properties,
  comparison count, evidence coverage, state, and warnings
- link each material to material detail
- avoid showing global comparison groups as the primary content of this page

Verification:

- one material appears once when aliases are merged in the payload
- material cards expose enough context to decide which material to inspect
- clicking a material opens material detail
- empty or weak material extraction states are explicit

## Phase 5: Material Detail

Implementation:

- fetch `MaterialProfile`
- render material overview, papers, sample matrix, process-parameter ranges,
  property summaries, comparisons, condition series, evidence, and warnings
- render comparable groups as a module inside the material profile
- open evidence details from matrix cells, property summaries, series points,
  and comparison rows

Verification:

- material detail does not include samples or comparisons from other materials
- material-scoped comparisons render fixed conditions, variable axes,
  properties, status, and warnings
- evidence drawer works from each material-profile module
- weak material binding renders a warning close to the affected module

## Phase 6: Papers Tab

Implementation:

- render `PaperCoverageRow` as the document list table
- include paper state, sample count, process parameter count, measurement
  count, condition count, evidence count, and issue count
- link each paper to its paper detail research view
- avoid duplicating paper-specific sample matrices inside the collection papers
  tab

Verification:

- each paper row has a clear state and issue signal
- clicking a paper opens paper detail
- the papers tab answers paper coverage, not paper-level analysis

## Phase 7: More / All Comparisons

Implementation:

- render `ComparableGroup` as the global all-comparisons browser under `More`
- let the user inspect the group's cross-paper matrix
- keep fixed conditions, variable axis, property, comparability status, and
  warnings visible
- open evidence details from matrix cells
- treat condition series as trends when they span the group

Verification:

- raw `measurement_results` are not rendered as the primary result cards
- groups can be filtered or scanned by material, process, property, and status
- matrix values can open evidence detail or show missing-evidence warnings
- the route is not exposed as a primary top-level tab

## Phase 8: Paper Detail Research View

Implementation:

- fetch `PaperAggregation` for document detail
- render paper overview first
- render paper-scoped material summaries when available
- support a local "Material In This Paper" drilldown that shows samples,
  process conditions, test conditions, result matrix, within-paper
  comparisons, condition series, and evidence for one material inside the
  current document
- render `SampleMatrix` as the primary paper result surface
- render `ConditionSeries` as grouped series, not separate scalar result cards
- link to the collection material profile only as a cross-paper follow-up; the
  paper detail page remains the owner of document-scoped material facts
- keep evidence and extraction debug reachable as secondary paper views

Verification:

- P001-style paper shows one row per real sample
- paper material summaries show what materials appear in the document
- a paper-scoped material drilldown does not include facts from other papers
- core property values appear as matrix cells
- duplicate raw facts are represented inside cell evidence details
- generic material or process concepts do not appear as sample rows

## Phase 9: Evidence Drawer And Debug Placement

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

## Phase 10: Frontend Tests

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

- collection primary navigation is `Overview / Materials / Papers / Graph / More`
- collection materials render canonical material summaries
- material detail renders material profile modules and material-scoped
  comparisons
- collection overview and papers tab render aggregation contract data
- `More / All Comparisons` renders comparable groups and cross-paper matrices
- paper detail renders paper-scoped materials, sample matrices, and condition
  series
- raw extracted records are demoted to evidence/debug surfaces
- loading, empty, partial, ready, and failed states are explicit
