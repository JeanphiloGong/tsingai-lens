# Core Semantic Build

This package consumes normalized Source artifacts and produces Core semantic
artifacts.

- `document_profile_service.py`
  LLM-structured document typing and collection summaries
- `research_objective_service.py`
  collection-level paper skim, research objective, objective context, evidence
  route, evidence-unit, and logic-chain records; objective evidence routing now
  walks Source document trees as bounded current-source decisions instead of
  sending large flat candidate batches to the model. Route prompts are
  classification-only: the model sees compact source hints and returns only
  route role, extractability, and confidence while backend code binds source
  ids and persistence fields. Confirmed Objective analysis persists each
  completed objective stage so a failed rerun can reuse paper frames, routes,
  evidence units, or logic chains that already exist for that objective. Evidence-unit
  extraction carries a bounded structured document state forward so later
  blocks and tables can see prior sample, process, test, measurement, and
  open-join context without putting prior raw text back into the prompt.
  Objective logic chains include traceable measurement value ranges assembled
  from resolved measurement units. For a confirmed Objective, traversal
  accumulates these units by document. The downstream research-understanding
  service then aligns eligible direct results into transient exact-condition
  result sets and keeps multiple outcomes from the same controlled contrast
  together. One objective-level synthesis directly emits multi-outcome
  Findings. Reverse comparisons are reoriented before synthesis, and dominated
  contrasts are omitted. These result sets are prompt inputs only: the service
  does not persist paper Findings or run a second clustering stage. Model
  candidates that cite the same direct-result unit set collapse into one
  Finding. The final calibration may restore same-document qualification or
  mechanism context only when it explicitly matches a selected outcome, then
  orders structural results, performance results, regime limits, mechanisms,
  and the single-paper evidence boundary into one expert-readable statement
- `paper_facts_service.py`
  objective-aware semantic extraction for evidence anchors, method facts,
  variants, test conditions, baselines, and measurement results
- `core_semantic_version.py`
  manifest-based invalidation for Core semantic artifacts
- [`llm/README.md`](llm/README.md)
  Core-owned prompt, schema, extractor, and structured-extraction plan
  contracts
