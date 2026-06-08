# Objective Report Sectioned Generation Plan

## Summary

Objective report generation should move from one large prompt over the whole
objective workspace to a sectioned, evidence-packet pipeline.

The report should remain a projection over `ObjectiveEvidenceUnit` and
`ObjectiveLogicChain`. It should not become a second semantic authority, and
it should not ask the model to rediscover facts from raw papers. The model's
job is to explain already-resolved evidence in a reader-facing report while
preserving traceability.

The intended flow is:

```text
ObjectiveEvidenceUnit / ObjectiveLogicChain
  -> report plan
  -> section-specific evidence packets
  -> section drafts
  -> claim verification
  -> assembled objective report
  -> persisted ObjectiveReport artifact
```

This plan is inspired by GraphRAG-style map/reduce report generation: build
small scoped contexts, generate local answers, then reduce them into one
grounded answer. It is not a plan to import Microsoft GraphRAG code or add a
new retrieval framework. The implementation should stay inside the existing
Core objective service and persistence boundary.

## Why The Current Shape Is Not Enough

The current persisted report reader proves the route and storage surface:

```text
POST /api/v1/collections/{collection_id}/objectives/{objective_id}/report
GET  /api/v1/collections/{collection_id}/objectives/{objective_id}/report
```

The first generation path also proved that a compact context can fit a small
OpenAI-compatible model such as the local `merged-qwen` service on port `8008`.
However, one-shot generation still has three limits:

- the prompt must compress too much scientific structure into one context
- the output can become a short summary instead of a material-science logic
  report
- there is no section-level verifier to catch unsupported values, missing
  comparisons, or omitted limitations before persistence

The product target is a research logic-chain report. It should answer:

- what the objective asks
- what the collection proves for that objective
- which papers contribute which evidence
- which samples, process variables, test conditions, observations, and
  measurements support the conclusion
- where comparisons are controlled, weak, conflicting, or not directly
  comparable
- which source records support each claim

That shape is better generated section by section than through one large
prompt.

## Report Structure

The first sectioned report should produce this stable Markdown structure:

```text
# Research Objective Report

## 研究目标
## Collection-Level Conclusion
## Paper Contribution Map
## Evidence Matrix
## Controlled Comparisons
## Mechanism Chain
## Source Traceback
## Limitations / Uncertainties
```

The section names can be localized later, but the generation pipeline should
keep a stable internal section key for each report part.

Each section should receive only the evidence it needs:

- `objective_header`: objective question, material scope, process axes,
  property axes, readiness, confidence, and known gaps
- `collection_conclusion`: cross-paper logic-chain claims, agreement,
  conflict, and representative hard measurements
- `paper_contribution_map`: objective-paper frames, paper roles, and paper
  logic-chain summaries
- `evidence_matrix`: counts and grouped facts from objective evidence units
- `controlled_comparisons`: comparison units and measurements with matched
  process, condition, baseline, and property context
- `mechanism_chain`: process variables, characterization observations,
  measured outcomes, and author interpretations
- `source_traceback`: source references, table or figure anchors, document
  identifiers, page or block references, and evidence-unit identifiers
- `limitations`: unresolved joins, missing units, incomparable test
  conditions, weak routes, unsupported claims, and low-confidence evidence

## Pipeline

### 1. Build Report Plan

The report plan is deterministic. It selects the section keys, expected
question each section must answer, and required evidence families.

Inputs:

- `ResearchObjective`
- `ObjectiveContext`
- objective readiness fields
- available `ObjectiveLogicChain` records
- grouped `ObjectiveEvidenceUnit` counts

Output:

```json
{
  "report_version": "objective_report_sectioned_v1",
  "sections": [
    {
      "key": "collection_conclusion",
      "question": "What does this collection prove for the objective?",
      "required_evidence": ["logic_chain", "measurement", "comparison", "limitation"]
    }
  ]
}
```

This step should not call the LLM in the first implementation. Keeping it
deterministic makes tests and failures easier to reason about.

### 2. Build Section Evidence Packets

Each section receives a compact packet, not the whole objective workspace.

Rules:

- include only objective-scoped records
- prefer resolved evidence units over raw route payloads
- include hard numeric measurements as compact rows
- include source references as identifiers and short labels, not long raw
  text
- include unresolved or missing fields explicitly so the model can report
  uncertainty instead of inventing detail

For example, the controlled-comparison packet should contain:

- compared samples or conditions
- changed axis and held context
- property and value pairs
- units
- direction of change
- source references
- whether the comparison is controlled, partial, or weak

### 3. Generate Section Drafts

The LLM generates one Markdown section at a time.

Prompt rules:

- answer only the section question
- use only packet evidence
- include required numeric rows when supplied
- mark missing evidence as uncertain instead of filling it in
- never cite an evidence unit that is not in the packet

This is where smaller local models become more usable. The model sees a small,
high-signal packet instead of the entire objective payload.

### 4. Verify Section Claims

Before assembly, a verifier checks each section draft against its packet.

The first verifier should be deterministic and conservative:

- required numbers from the packet appear in the section when the section
  calls for them
- unsupported numeric values are flagged
- source identifiers mentioned by the draft exist in the packet
- required section subsections or tables are present
- limitation sections include unresolved fields when unresolved fields exist

The verifier should return warnings that can be persisted with the report
artifact. It should not silently rewrite unsupported claims.

### 5. Assemble Objective Report

The assembler concatenates verified section drafts in report-plan order.

Assembly should add:

- a generated timestamp
- collection and objective identifiers
- report version
- model identifier
- section warnings
- source evidence count summary

The final artifact remains a report projection. If a report claim needs better
evidence, the fix belongs upstream in objective routing, evidence-unit
extraction, evidence resolution, or logic-chain assembly.

## Persistence

The existing persisted report artifact surface is the right owner for the
final output. The sectioned pipeline should continue writing the ready report
through the objective report artifact path.

The first implementation does not need new SQLite tables for every section.
The persisted payload can include structured debug metadata:

```json
{
  "report_version": "objective_report_sectioned_v1",
  "generation_strategy": "sectioned",
  "sections": [
    {
      "key": "controlled_comparisons",
      "status": "ready",
      "warnings": [],
      "evidence_unit_ids": ["..."]
    }
  ]
}
```

If section-level audit becomes a product requirement later, durable section
records can be added as a separate approved data-layer slice.

## Implementation Slices

### Slice 1: Deterministic Section Planner And Packet Builder

Add report section definitions and evidence-packet builders inside
`ResearchObjectiveService`.

Expected checks:

- objective report context stays within the target token budget
- every section packet is objective-scoped
- representative measurements are present in the collection conclusion and
  controlled-comparison packets
- unresolved fields are carried into the limitations packet

### Slice 2: Per-Section LLM Generation

Replace one-shot Markdown generation with section-by-section generation.

Expected checks:

- the same report route persists one assembled Markdown artifact
- the service calls the configured report model once per generated section
- generated sections are ordered by the deterministic report plan
- model reasoning markup such as `<think>...</think>` is stripped before
  persistence

### Slice 3: Section Claim Verifier

Add deterministic verification before report assembly.

Expected checks:

- required representative numbers missing from a section produce warnings
- unsupported numeric values produce warnings
- unknown evidence IDs produce warnings
- warnings are visible in the persisted report metadata

### Slice 4: Expert Report Regression Fixture

Use the local P001/P002/P004/P006 objective report examples as regression
fixtures for report shape and required claim coverage.

Expected checks:

- the generated report includes the target section headings
- PBF/SLM 316L objective reports include table-backed measurements when
  representative measurements exist
- limitations mention missing or weakly comparable evidence when the objective
  packets contain those warnings
- report generation still works against the local `merged-qwen` model with a
  small context window

## Verification

Run the smallest relevant checks for each implementation slice:

```bash
cd backend
./.venv/bin/python -m pytest tests/unit/services/test_research_objective_service.py -q
git diff --check
```

For real-model verification, use an existing built collection and the local
OpenAI-compatible report model:

```bash
cd backend
LLM_BASE_URL=http://localhost:8008/v1 \
LLM_API_KEY=not-needed \
LLM_MODEL=merged-qwen \
OBJECTIVE_REPORT_LLM_MODEL=merged-qwen \
./.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8011
```

Then regenerate one objective report with `force_regenerate=true` and compare
the Markdown with the hand-authored target report for:

- section coverage
- scientific logic-chain clarity
- required numeric claim coverage
- controlled-comparison readability
- explicit limitations and uncertainty
- source traceback presence

Generated local artifacts should stay out of committed source.

## Boundaries

- Do not import GraphRAG or add a new retrieval framework for this slice.
- Do not make the report a new semantic source of truth.
- Do not ask the LLM to re-extract facts from raw PDF text in the report step.
- Do not change public API route names in this plan.
- Do not add section persistence tables unless section-level audit becomes a
  separate approved requirement.
- Do not keep a long-term compatibility path from old collection-wide
  comparison rows into objective reports.
