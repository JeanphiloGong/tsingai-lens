# Target-Centric Collection Extraction Plan

## Summary

Core extraction should start by discovering multiple research targets from the
paper collection, not by extracting final facts directly from each paper or
table row.

The target flow is:

```text
collection paper skim
      |
      v
research target discovery
      |
      v
one independent target process per research target
      |
      v
target-paper framing
      |
      v
target context refinement
      |
      v
target-aware section and table routing
      |
      v
target-scoped evidence-unit extraction
      |
      v
evidence resolution
      |
      v
target logic-chain assembly
      |
      v
comparison, report, and workspace projections inside each target
```

This plan belongs to the Core semantic-build pipeline because it changes the
order and ownership of Core extraction decisions. It does not change Source
parser selection, public API routes, frontend contracts, or downstream report,
graph, and protocol ownership.

Read this with:

- [`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md)
- [`../../../application/core/semantic_build/llm/docs/structured-extraction/semantic-routing-targeted-extraction-plan.md`](../../../application/core/semantic_build/llm/docs/structured-extraction/semantic-routing-targeted-extraction-plan.md)
- [`../../../application/core/semantic_build/llm/docs/structured-extraction/table-first-extraction-plan.md`](../../../application/core/semantic_build/llm/docs/structured-extraction/table-first-extraction-plan.md)

## Why The Flow Changes

The current extraction shape is still mostly paper-centric:

```text
paper -> text windows and table rows -> facts -> comparison
```

That order makes the model decide too much from local fragments. It can see a
number, a row label, or a table header before it knows the research question
the collection is trying to answer. The result is predictable noise:

- environment terms can become materials
- composition tables can become performance results
- modeling or prior-work tables can leak into current-work measurements
- fragmented sample labels can become variants
- comparison rows can mix unrelated scientific questions

The collection should instead be read like a researcher reads a literature
set. First identify the research questions that the papers can support, then
open a separate analysis process for each question.

## Coarse Extraction And Fact Extraction

This plan uses two different extraction levels.

Coarse extraction builds a research map. It extracts:

- candidate materials
- process and treatment families
- measured property families
- changed variables
- paper role and relevance
- relevant sections, tables, and figures
- skip reasons for background, composition, modeling, review, or low-value
  blocks

Final extraction builds logic-chain-ready evidence. It extracts:

- material
- sample or variant
- process or treatment
- resolved sample or experimental condition
- test condition
- measured property
- value and unit
- baseline or comparison relation
- author interpretation when available
- evidence anchor

The first rounds should not emit final measurement facts. They should produce
the target and paper frames that decide where final fact extraction is allowed
to run.

## First Pass: Collection Paper Skim

The first pass scans every paper quickly and produces a compact paper map.

Inputs should come from Source and existing Core profile context:

- title
- abstract
- keywords
- introduction and conclusion windows when available
- section headings
- table captions
- figure captions
- source filename
- document profile

The paper skim output should be coarse:

```json
{
  "paper_id": "P001",
  "doc_type": "experimental",
  "candidate_materials": ["316L stainless steel"],
  "candidate_processes": ["LPBF", "heat treatment"],
  "candidate_properties": ["corrosion", "tensile strength"],
  "main_variables": ["heat treatment temperature", "scan speed"],
  "possible_targets": [
    "heat treatment effect on corrosion",
    "process parameter effect on tensile properties"
  ],
  "evidence_density": {
    "tables": 6,
    "figures": 8,
    "experimental_results": "high"
  }
}
```

This pass is still extraction, but it extracts the collection reading map, not
the final fact chain.

## Research Target Discovery

After paper skim, Core should summarize the collection into multiple research
targets.

A research target is a question-shaped workspace. It should define what the
later process is trying to compare, not just name a material.

Example:

```json
{
  "target_id": "target_heat_treatment_corrosion_316l",
  "question": "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?",
  "material_scope": ["316L stainless steel"],
  "process_scope": ["LPBF", "SLM", "heat treatment"],
  "property_scope": ["corrosion resistance", "electrochemical behavior"],
  "why_this_target": "Multiple papers compare as-built and heat-treated LPBF 316L under corrosion testing.",
  "seed_papers": ["P001", "P003", "P006"]
}
```

The target discovery stage should return several target candidates when the
collection supports several scientific questions. The system should not force
the collection into a single material or single property question.

## Independent Target Processes

Once targets are discovered, each target should start an independent process.
Those processes may run in parallel because they share Source artifacts but
own separate target state.

```text
target_1 process
  -> scan papers for target_1
  -> refine target_1 context
  -> route evidence for target_1
  -> extract facts for target_1

target_2 process
  -> scan papers for target_2
  -> refine target_2 context
  -> route evidence for target_2
  -> extract facts for target_2
```

Each target process owns a workspace:

```json
{
  "target_id": "target_heat_treatment_corrosion_316l",
  "question": "How does heat treatment affect corrosion resistance of LPBF 316L?",
  "material_scope": ["316L stainless steel"],
  "process_scope": ["LPBF", "SLM", "heat treatment"],
  "property_scope": ["corrosion", "EIS", "polarization"],
  "aliases": {},
  "include_rules": [],
  "exclude_rules": [],
  "paper_relevance": {},
  "evidence_map": {},
  "known_gaps": []
}
```

This workspace starts from target discovery output, then changes as the target
process reads the papers.

## Target-Paper Framing

For every target and every paper, Core should extract how that paper relates
to that specific target.

The target-paper framing output should answer:

- whether the paper is relevant to this target
- whether it is a primary experiment, supporting method paper, background
  paper, review, modeling-only paper, or irrelevant paper
- which materials match the target
- which variables matter for the target
- which properties and test environments matter for the target
- which sections, tables, and figures should be routed later
- which tables or sections should be excluded and why

Example:

```json
{
  "target_id": "target_heat_treatment_corrosion_316l",
  "paper_id": "P001",
  "relevance": "high",
  "paper_role": "primary_experiment",
  "background": "The paper studies corrosion behavior of LPBF 316L after heat treatment.",
  "material_match": ["316L stainless steel"],
  "changed_variables": ["heat treatment temperature", "holding time"],
  "measured_property_scope": ["corrosion potential", "corrosion current density", "EIS"],
  "test_environment_scope": ["3.5 wt.% NaCl"],
  "relevant_sections": ["Experimental", "Electrochemical measurements", "Results"],
  "relevant_tables": [
    {
      "table_id": "table_3",
      "role": "corrosion_result_table",
      "why_relevant": "Contains Ecorr and Icorr for as-built and heat-treated samples."
    }
  ],
  "excluded_tables": [
    {
      "table_id": "table_1",
      "role": "chemical_composition",
      "why_excluded": "Only describes nominal alloy composition."
    }
  ]
}
```

This is the stage that makes the target richer. It is not just collecting
document chunks for later. It extracts a target-specific reading frame that
controls later extraction.

## Target Context Refinement

After target-paper framing, the target process should refine its own context.

Refinement should update:

- material aliases
- process aliases
- property aliases
- known variable axes
- known test-condition axes
- include rules
- exclude rules
- common table roles
- known gaps or ambiguous papers

Example refinements:

- `LPBF`, `SLM`, and `selective laser melting` are equivalent for this target.
- `316L SS`, `AISI 316L`, and `316L stainless steel` are equivalent for this
  target.
- corrosion evidence should include polarization and EIS sections.
- chemical composition tables are background for this target.
- equivalent-circuit fitting tables are supporting corrosion interpretation,
  not primary material-property measurements unless the target explicitly asks
  for fitting behavior.

This context is target-local. It should not become one global rule set for all
targets because the same table can be relevant for one target and background
for another.

## Target-Aware Evidence Routing

Only after the target context is refined should Core route sections and tables
for final fact extraction.

Routing should include the target context and classify each source unit:

- current experimental evidence for this target
- process or treatment definition
- material composition or background
- test condition description
- result table or result paragraph
- characterization evidence
- literature comparison
- modeling or prediction
- low-value or irrelevant content

For tables, this plan aligns with the table-first extraction plan. A table
should be classified before row-level fact extraction runs, and small relevant
tables can be passed to the model as whole-table context while preserving
row-indexed evidence anchors.

Routing should also identify table role, column roles, and join keys before
values are extracted. Paper-local identifiers such as `condition number` and
`sample number` should be treated as join and traceback keys, not as the final
condition semantics. If one table defines preparation conditions and another
table reports results for the same keys, routing should record the join plan
so the later evidence unit can expose the actual process condition instead of
only an author-assigned row number.

## Target-Scoped Evidence-Unit Extraction

Final extraction should run only on routed source units that are relevant to
the target.

The extractor should receive:

- target workspace context
- target-paper framing for the paper
- routed section or table role
- table schema and join plan when table evidence is involved
- Source evidence context
- row and cell locators for tables

The output should stay evidence-chain shaped:

```text
material
-> sample or variant
-> process or treatment
-> resolved preparation or experimental condition
-> test condition
-> measured property
-> value and unit
-> baseline or comparison
-> author interpretation where available
-> evidence anchor
```

Evidence units should remain target-scoped. A paper can contribute different
evidence to different targets, and each contribution should preserve the
target that authorized the extraction.

## Evidence Resolution And Target Logic Chain

The target process should resolve source fragments before downstream views use
them. Resolution includes:

- joining condition or preparation tables with result tables
- expanding paper-local identifiers into actual sample or process conditions
- binding text explanations to table or figure measurements
- preserving source traceback for every resolved value and claim

The primary target output is a research logic chain, not just comparison-ready
rows:

```text
research target
-> paper contribution and relevance
-> material system
-> preparation, process, or treatment route
-> changed variables and resolved sample conditions
-> characterization or test method
-> measured result
-> author interpretation
-> cross-paper agreement, conflict, and gaps
```

Comparison rows, evidence cards, reports, and future API views should be
projections over these resolved evidence units and target logic chains.

## Core Records

The first implementation can keep routing and target state internal to the
rebuild run while logging enough detail for diagnosis.

Once the flow is stable, Core should persist target state as database records
through the Core persistence boundary rather than as standalone repository records.
The first record families should be:

- `PaperSkim`
- `ResearchObjective`
- `ObjectivePaperFrame`
- `EvidenceRoute`
- resolved evidence units and target logic chains
- target-scoped measurement and comparison records

The SQLite implementation should store them in Core-owned tables such as
`core_paper_skims`, `core_research_objectives`,
`core_objective_paper_frames`, and `core_objective_evidence_routes`. These
records should remain Core internal in the first wave. They should not become
public frontend API contracts until the product surface is explicitly designed
around target selection.

## Execution Order

1. Extend Core domain records, `CoreFactSet`, and `CoreFactRepository` for
   paper skim and research-objective records.
2. Add SQLite persistence tables and repository methods for those records.
3. Add collection paper skim over existing Source records and document
   profiles.
4. Add collection research-target discovery from paper skim records.
5. Start one target process per discovered target.
6. Add target-paper framing for every target and paper.
7. Add target context refinement from target-paper frames.
8. Feed refined target context into section and table routing.
9. Add table schema routing for table roles, column roles, join keys, and
   join plans.
10. Run target-scoped evidence-unit extraction only on target-authorized source
    units.
11. Resolve table and text fragments into paper-level target logic chains.
12. Assemble comparison rows within each target as projections before any
    cross-target merge.

## Verification

The first implementation should be checked with targeted tests and one
collection rebuild.

Unit and integration tests should cover:

- a collection can produce multiple research targets
- one paper can be relevant to multiple targets with different roles
- target-paper framing distinguishes coarse map extraction from final fact
  extraction
- target context refinement adds aliases and exclusions without leaking them
  into unrelated targets
- table routing receives target context before final fact extraction
- table routing distinguishes join keys from real experimental conditions and
  records how condition/result tables should be joined
- composition, modeling, and literature-comparison content can be excluded for
  one target while remaining available as background or evidence for another
  target
- resolved target logic chains preserve material, condition, result,
  interpretation, and source traceback
- comparison rows are grouped by research target as projections over resolved
  evidence units

Collection rebuild checks should confirm:

- final facts are attached to a target
- condition IDs and sample IDs are resolved into actual process or preparation
  conditions before downstream comparison
- material and sample noise drops for the target under review
- irrelevant tables no longer generate current-work measurements for that
  target
- each retained measurement still has document, section/table, row/cell, and
  quote evidence

## Deferred Work

This plan does not require:

- frontend target selection UI in the first implementation
- public API response-shape changes
- Source parser changes
- sending raw PDFs directly to the model
- durable route records before the process is stable
- cross-target report generation

Those can follow after the target-centric Core extraction path proves that it
improves fact quality and comparison coherence on real collections.
