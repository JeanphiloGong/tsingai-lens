# Research View Aggregation Backend Implementation Plan

## Goal

Implement the backend side of the research-view aggregation contract so the
frontend can render paper matrices and collection comparison views without
rebuilding them from raw extracted facts.

The first useful slice is PBF-metal focused:

- one paper-level `SampleMatrix`
- one paper-level `ConditionSeries` path when condition axes exist
- one collection-level `PaperCoverage` view
- one collection-level comparable group or an explicit partial-state reason

## Current Owning Seams

Use the current backend seams directly:

| Concern | Candidate owning seam |
| --- | --- |
| Paper facts loading and evidence anchors | `backend/application/core/semantic_build/paper_facts_service.py` |
| Comparison inputs and rows | `backend/application/core/comparison_service.py` and `backend/application/core/comparison_*.py` |
| Workspace readiness and artifact links | `backend/application/core/workspace_overview_service.py` |
| Core read endpoints | `backend/controllers/core/` |
| Response schemas | `backend/controllers/schemas/core/` |
| Service tests | `backend/tests/unit/services/` |
| Router and contract tests | `backend/tests/unit/routers/` and `backend/tests/integration/test_app_layer_api.py` |

Create new files only when they represent a real backend concern, such as a
research-view aggregation service or schema module. Do not add compatibility
wrappers around old raw-result responses.

## File And Function Change Map

This section records the concrete backend file and function-level plan for the
first implementation wave.

### New Service File

Add `backend/application/core/research_view_aggregation_service.py`.

Recommended permanent service:

```text
class ResearchViewAggregationService
```

Public methods:

```text
get_collection_research_view(collection_id: str) -> dict
get_document_research_view(collection_id: str, document_id: str) -> dict
```

Core helper methods:

```text
_load_fact_frames(collection_id: str) -> dict[str, DataFrame]
_load_comparison_projection(collection_id: str)
_build_collection_overview(collection_id, frames, projection) -> dict
_build_paper_coverage(collection_id, frames) -> list[dict]
_build_document_aggregation(collection_id, document_id, frames) -> dict
_build_sample_matrix(collection_id, document_id, frames) -> dict
_build_sample_matrix_row(variant_row, measurements, frames) -> dict
_is_real_sample_variant(variant_row) -> bool
_measurement_cell_key(measurement_row) -> tuple
_dedupe_measurements_for_cell(measurements) -> list[dict]
_build_evidence_backed_value(measurements, frames) -> dict
_build_evidence_refs(fact_ids, anchor_ids, frames) -> list[dict]
_build_condition_series(collection_id, document_id, frames) -> list[dict]
_condition_axis_from_payload(condition_payload) -> dict | None
_build_comparable_groups(collection_id, projection, frames) -> list[dict]
_build_cross_paper_matrix(group_rows, frames) -> dict
_warning(code, severity, scope, message, related_object_ids=None) -> dict
```

The service should call existing services directly. It should not be a
compatibility wrapper around old raw-result card responses.

### Existing Service Calls To Reuse

Use these existing functions as inputs rather than duplicating artifact reads:

| File | Function | Use |
| --- | --- | --- |
| `backend/application/core/semantic_build/paper_facts_service.py` | `PaperFactsService.read_paper_fact_frames` | Load `sample_variants`, `measurement_results`, `test_conditions`, evidence anchors, and related paper facts. |
| `backend/application/core/semantic_build/paper_facts_service.py` | `PaperFactsService.read_evidence_cards` | Load evidence-card projections when evidence refs need display context. |
| `backend/application/core/semantic_build/paper_facts_service.py` | `PaperFactsService.get_evidence_traceback` | Keep detail traceback available from evidence drawer links. |
| `backend/application/core/comparison_service.py` | `ComparisonService.read_comparison_projection` | Load semantic comparison artifacts without requiring stale row caches. |
| `backend/application/core/comparison_service.py` | `ComparisonService.read_comparison_rows` | Reuse current row cache when available for collection matrix grouping. |
| `backend/application/core/comparison_service.py` | `ComparisonService.read_comparable_results` | Load normalized comparable-result records for group assembly. |
| `backend/application/core/comparison_service.py` | `ComparisonService.read_collection_comparable_results` | Load collection-scoped overlays and policy metadata. |
| `backend/application/core/workspace_overview_service.py` | `WorkspaceService.get_workspace_overview` | Reuse collection state and artifact readiness. |

### Existing Functions To Extend

Extend these existing functions only where they own the contract surface:

| File | Function | Change |
| --- | --- | --- |
| `backend/application/core/workspace_overview_service.py` | `WorkspaceService._build_links` | Add `research_view` and `research_documents` links when the new endpoints are available. |
| `backend/application/core/workspace_overview_service.py` | `WorkspaceService._build_capabilities` | Add capability flags such as `can_view_research_view` only if the frontend needs capability-gated UI. |
| `backend/application/core/workspace_overview_service.py` | `WorkspaceService.get_workspace_overview` | Return the new links/capabilities through the existing overview payload after schemas are updated. |
| `backend/application/core/semantic_build/paper_facts_service.py` | `PaperFactsService._deduplicate_measurement_results_table` | Tighten fact-level dedupe only if aggregation exposes remaining duplicate cells that should be fixed upstream. |
| `backend/application/core/semantic_build/paper_facts_service.py` | `PaperFactsService._measurement_result_dedupe_key` | Include unit-normalized and evidence-aware fields only if needed to prevent obvious duplicate facts. |
| `backend/application/core/semantic_build/paper_facts_service.py` | `PaperFactsService._filter_generic_text_sample_variants` | Tighten generic sample filtering only if generic material/process concepts still become matrix rows. |
| `backend/application/core/semantic_build/paper_facts_service.py` | `PaperFactsService._build_table_row_process_context_from_cells` | Fix table column binding if the sample matrix still shows wrong process values such as speed/energy swaps. |

Aggregation should first collapse duplicate display cells without hiding the
raw duplicate count. Upstream extraction fixes should be limited to clear fact
quality bugs found by the matrix.

### New Schema File

Add `backend/controllers/schemas/core/research_view.py`.

Recommended response classes:

```text
ResearchViewWarningResponse
EvidenceReferenceResponse
EvidenceBackedValueResponse
SampleMatrixColumnResponse
SampleMatrixRowResponse
SampleMatrixResponse
ConditionSeriesPointResponse
ConditionSeriesResponse
PaperAggregationOverviewResponse
PaperAggregationResponse
PaperCoverageRowResponse
ComparableGroupResponse
CrossPaperMatrixRowResponse
CrossPaperMatrixResponse
CollectionAggregationOverviewResponse
CollectionAggregationResponse
```

Keep schemas direct and explicit. Do not reuse old result-card response models
when their semantics no longer match the research-view contract.

### New Controller File

Add `backend/controllers/core/research_view.py`.

Recommended module-level service and route functions:

```text
research_view_service = ResearchViewAggregationService()

def _research_view_not_ready_detail(collection_id: str) -> dict[str, str]

async def get_collection_research_view(collection_id: str) -> CollectionAggregationResponse

async def get_collection_document_research_view(
    collection_id: str,
    document_id: str,
) -> PaperAggregationResponse
```

Routes:

```text
GET /api/v1/collections/{collection_id}/research-view
GET /api/v1/collections/{collection_id}/documents/{document_id}/research-view
```

Update `backend/main.py`:

```text
from controllers.core import research_view
app.include_router(research_view.router, prefix=PUBLIC_API_V1_PREFIX)
```

### Tests To Add Or Extend

Add focused tests before broad integration work:

| File | Test focus |
| --- | --- |
| `backend/tests/unit/services/test_research_view_aggregation_service.py` | service-level sample matrix, condition series, paper coverage, comparable groups, evidence refs, warnings |
| `backend/tests/unit/routers/test_research_view_api.py` | endpoint status codes, top-level response fields, not-ready and not-found behavior |
| `backend/tests/integration/test_app_layer_api.py` | route registration and end-to-end same-origin API behavior |
| `backend/tests/unit/services/test_workspace_service.py` | workspace links and optional capabilities after endpoint links are exposed |
| `backend/tests/unit/services/test_paper_facts_services.py` | only upstream dedupe, sample filtering, or table binding changes proven necessary by aggregation tests |

## Phase 1: Contract Skeleton

Implementation:

- add response schemas for the shared contract under
  `backend/controllers/schemas/core/`
- add a backend aggregation service under `backend/application/core/`
- add read methods for:
  - collection research view
  - document research view
- add direct API endpoints:
  - `GET /api/v1/collections/{collection_id}/research-view`
  - `GET /api/v1/collections/{collection_id}/documents/{document_id}/research-view`

Verification:

- router tests assert both endpoints return the shared top-level fields
- empty and processing states are explicit
- responses use `/api/v1/*` links only

## Phase 2: Paper Sample Matrix

Implementation:

- load `sample_variants`, `measurement_results`, `test_conditions`,
  `method_facts`, and `evidence_anchors`
- build one `SampleMatrixRow` per real experimental sample or variant
- exclude generic material names, process families, and mechanism-only concepts
  from sample rows
- bind process columns such as material, strategy, scan speed, energy density,
  and hatch spacing when confidently available
- group core property values into `EvidenceBackedValue` cells
- collapse duplicate raw facts into duplicate counts inside the cell
- preserve fact ids, anchor ids, confidence, and warnings

Verification:

- P001-style fixture produces sixteen visible sample rows
- duplicate density, hardness, tensile, and elongation facts do not duplicate
  visible rows
- every observed property cell has evidence refs or a structured warning
- unresolved process or condition binding appears as a row or cell warning

## Phase 3: Paper Condition Series

Implementation:

- group result facts by document, sample, property, and condition axis
- support axes such as temperature, time, strain rate, frequency, and
  heat-treatment condition
- keep individual series points evidence-backed
- avoid rendering independent result cards when a coherent series exists

Verification:

- values such as `25 C`, `200 C`, and `400 C` become one series when they share
  sample and property context
- missing sample or condition binding blocks the series and emits a warning
- each point preserves source evidence references

## Phase 4: Collection Paper Coverage

Implementation:

- derive one `PaperCoverageRow` per document
- count samples, process parameters, measurement results, conditions, evidence,
  and issues
- classify each document as `empty`, `processing`, `partial`, `ready`, or
  `failed`
- expose links to paper detail research views and debug surfaces

Verification:

- collection research view renders paper coverage before comparable groups
- papers with weak fact binding are marked `partial`, not silently hidden
- the frontend has enough links to enter paper detail without reconstructing
  document routes

## Phase 5: Comparable Groups And Cross-Paper Matrices

Implementation:

- use comparison inputs and existing comparison rows as source material
- group rows by material system, process family, variable axis, fixed
  conditions, property family, and test condition family
- generate `ComparableGroup` objects with comparability status
- generate a `CrossPaperMatrix` for each group
- keep missing context and comparability warnings close to group rows

Verification:

- direct groups are marked `comparable`
- weak groups are marked `limited`
- insufficient groups are marked `blocked`
- row-level evidence references and warnings survive serialization

## Phase 6: Workspace Links And Debug Boundaries

Implementation:

- add workspace links to the collection research view and paper research view
  when the endpoints are ready
- keep raw evidence and extraction-debug entry points available as debug links
- do not make raw `measurement_results` the main result surface

Verification:

- workspace overview can link to research-view endpoints
- raw result browser remains reachable only through evidence/debug links
- old raw-card flows are not treated as the primary collection result view

## Phase 7: Expert Gold Evaluation

Implementation:

- run the expert gold exporter and evaluator against the P001 collection output
- compare the aggregation result with the expert sample and measurement tables
- record remaining quality gaps before expanding to more papers

Verification:

- sample recall remains complete for the P001-style paper
- visible sample rows match the expert sample set
- duplicate raw measurement results no longer inflate visible result counts
- extra generic sample rows are excluded or reported as warnings

## Suggested Test Commands

Run focused backend checks for the files touched in each phase. Expected
commands include:

```bash
cd backend
python3 -m pytest tests/unit/services/test_paper_facts_services.py
python3 -m pytest tests/unit/routers/test_documents_api.py tests/unit/routers/test_comparisons_api.py
python3 -m pytest tests/integration/test_app_layer_api.py
python3 scripts/evaluation/expert_gold/evaluate_gold_vs_prediction.py --gold-paper-id P001
```

Use smaller targeted selections while developing, then run the broader checks
before merging.

## Exit Criteria

The backend topic is complete when:

- the two research-view endpoints exist and follow the shared contract
- paper detail aggregation can render a sample matrix without duplicate visible
  rows
- collection aggregation can render paper coverage and comparable groups
- every observed value has evidence references or warnings
- expert gold evaluation shows that aggregation reduces the current duplicate
  result problem instead of hiding it
