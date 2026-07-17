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
  ids and persistence fields. Confirmed-goal analysis persists each completed
  objective stage so a failed rerun can reuse paper frames, routes, evidence
  units, or logic chains that already exist for that objective. Evidence-unit
  extraction carries a bounded structured document state forward so later
  blocks and tables can see prior sample, process, test, measurement, and
  open-join context without putting prior raw text back into the prompt.
  Objective logic chains include traceable measurement value ranges assembled
  from resolved measurement units. For a confirmed goal, traversal accumulates
  these units by document; the downstream research-understanding service groups
  eligible direct results by exact source axes and target property, performs one
  goal-level synthesis over that bounded ledger, and directly emits Findings.
  It does not create paper Findings and cluster them later
- `paper_facts_service.py`
  objective-aware semantic extraction for evidence anchors, method facts,
  variants, test conditions, baselines, and measurement results
- `core_semantic_version.py`
  manifest-based invalidation for Core semantic artifacts
- [`llm/README.md`](llm/README.md)
  Core-owned prompt, schema, extractor, and structured-extraction plan
  contracts
