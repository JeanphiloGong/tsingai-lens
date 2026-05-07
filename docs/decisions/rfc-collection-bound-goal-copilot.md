# RFC Collection-Bound Goal Copilot

## Summary

This RFC proposes a collection-bound AI research copilot for Lens.

The copilot may use a conversational interface, but the product contract is
not generic open-domain chat. A user first binds a collection, optionally
focuses a material or paper, and then asks questions in a goal session. Each
answer must clearly distinguish collection-grounded evidence from general
model background.

The core rule is:

Lens should answer from the bound collection first. If the collection has no
usable result for the question, Lens may provide general background only when
it is explicitly labeled as not supported by the current collection.

## Relationship To Current Docs

This RFC complements existing Goal and Core documents:

- [Lens V1 Definition](../contracts/lens-v1-definition.md) remains the product
  boundary for evidence-backed collection comparison.
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
  remains the shared Core artifact boundary.
- [Backend Five-Layer Research Architecture](../../backend/docs/architecture/goal-core-source-layering.md)
  remains the backend authority for Goal Brief, Source, Core, Goal Consumer,
  and downstream layer separation.
- [Goal Copilot Proposal](../../frontend/docs/goal-copilot-proposal.md) remains
  the frontend-local interaction proposal.

This RFC narrows the missing shared product contract: how a conversational
goal session binds to a collection, how it remembers context, and how it may
fall back to general knowledge without weakening evidence-first behavior.

## Problem

Users often want to ask research questions before they know which exact
workspace surface contains the answer.

Examples:

- Which 316L samples show the clearest strength-ductility tradeoff?
- What does this collection say about LPBF scan strategy?
- Is the current evidence enough to support a review draft?
- If the collection has no result, what is the general background?

The workspace already exposes structured surfaces, but a user still benefits
from a goal-aware conversational layer that can route across those surfaces.

The risk is that a normal chatbot would blur three different things:

- findings supported by the bound collection
- gaps or absence of evidence in the bound collection
- general model knowledge outside the collection

Lens must keep those boundaries visible.

## Product Position

The feature should be described as a collection-bound research copilot.

It should not be described as:

- a generic paper chatbot
- an autonomous research agent
- a replacement for material, comparison, evidence, or document workspaces
- a source of evidence-backed conclusions before Core artifacts exist

It should be described as:

- a goal session over one collection
- a conversational router across Core artifacts
- an evidence-first explanation layer
- a controlled fallback path for general background when collection evidence is
  absent

## Goal Session

The central object is a `GoalSession`.

It records the working context for one conversational research thread:

```text
GoalSession
- bound_collection_id
- focused_material_id?
- focused_paper_id?
- goal_text?
- goal_brief_json?
- answer_mode
- rolling_summary?
- last_evidence_ids
- last_material_ids
- last_paper_ids
- collection_data_version?
- created_at
- updated_at
```

The first implementation only needs:

- bound collection
- optional focused material
- optional goal text
- answer mode
- rolling summary
- recent evidence references

The session should make context explicit instead of relying on the model to
remember it implicitly.

## Answer Modes

The copilot should support three answer modes.

### Grounded

Grounded mode only answers from the bound collection.

If the collection has no usable Core result, the answer should say that the
current collection does not contain sufficient evidence.

Grounded mode is appropriate for reviewable research decisions, material
comparisons, and evidence-backed conclusions.

### Hybrid

Hybrid mode is the default.

The system first queries the bound collection. If collection evidence exists,
the answer is grounded and must cite the relevant artifacts. If collection
evidence is empty or insufficient, the system may provide general background
only after an explicit boundary statement.

Example boundary:

```text
The current collection does not contain structured evidence for this question.
The following answer is general background and should not be treated as a
collection-supported conclusion.
```

Hybrid mode is appropriate for ordinary user exploration because it avoids a
dead end while preserving provenance.

### General

General mode does not use collection evidence as the basis of the answer.

It can be useful for background explanation, terminology, and brainstorming,
but it must not present its answer as a finding from the bound collection.

## Source Labels

Every assistant answer should carry a source label.

Recommended labels:

```text
collection_grounded
collection_limited
general_fallback
general_only
```

The UI should expose this distinction plainly:

- collection-grounded answers show evidence chips, comparison links, material
  links, paper links, or source anchors
- limited answers say which collection result is missing
- general fallback answers are marked as outside the current collection
- general-only answers do not display evidence chips

## Context Retrieval

Each answer should retrieve fresh context from the bound collection instead of
depending only on chat history.

Relevant Core and derived surfaces include:

- collection workspace readiness
- document profiles
- material profiles
- sample and process matrices
- property results
- comparison rows
- evidence cards
- graph or report outputs when they are derived from Core artifacts

The retrieval step should be scoped by the session:

- collection id is required
- focused material narrows material and property questions
- focused paper narrows source-specific questions
- goal text can rank or filter relevant artifacts

## Context Memory

The copilot should use layered memory.

### Session Memory

Session memory stores explicit state:

- current collection
- focused material
- focused paper
- current goal
- current answer mode
- recently used evidence ids

### Evidence Context

Evidence context is not stored as permanent chat memory. It is retrieved from
the current collection for each answer.

This keeps answers aligned with the latest Core artifacts and avoids stale
facts when the collection is rebuilt.

### Rolling Summary

A rolling summary stores the useful conversation state without preserving the
entire transcript in every model call.

It may record:

- properties the user has chosen to prioritize
- materials or samples the user has excluded
- earlier identified evidence gaps
- user-confirmed research framing

If a previous answer used general fallback, the rolling summary must preserve
that source boundary. General background must not become collection evidence in
later turns.

### Long-Term Preferences

Long-term preferences are out of scope for the first implementation.

Language preference, preferred table style, and recurring research area may be
added later with explicit user controls.

## Command Shape

The interface may accept lightweight commands as shortcuts.

Possible commands:

```text
$collection paper-ab
$material 316L stainless steel
$paper Paper A
$goal Compare LPBF process effects on strength and elongation.
$mode grounded
$mode hybrid
$mode general
$clear focus
```

Commands should update the `GoalSession` directly. They are a convenience
layer, not a second backend contract.

Natural language should remain supported:

```text
Use the current 316L material as focus.
Only answer from this collection.
Switch to general background mode.
```

## Backend Contract Direction

The first backend surface should be narrow and session-based.

Possible API shape:

```text
POST /api/v1/goal-sessions
GET /api/v1/goal-sessions/{session_id}
PATCH /api/v1/goal-sessions/{session_id}

POST /api/v1/goal-sessions/{session_id}/messages
GET /api/v1/goal-sessions/{session_id}/messages
```

Message requests should allow page context:

```json
{
  "message": "Does this material show a strength-ductility tradeoff?",
  "page_context": {
    "route": "material_detail",
    "material_id": "mat_316l"
  }
}
```

Message responses should expose source mode and evidence use:

```json
{
  "answer": "...",
  "source_mode": "collection_grounded",
  "used_evidence_ids": ["E01", "E02"],
  "warnings": []
}
```

When collection evidence is absent:

```json
{
  "answer": "The current collection does not contain structured evidence for this question. The following is general background...",
  "source_mode": "general_fallback",
  "used_evidence_ids": [],
  "warnings": ["no_collection_evidence_found"]
}
```

The exact route names may change during implementation, but the contract
boundary should remain:

- session state is explicit
- collection lookup happens before answer generation in grounded and hybrid
  modes
- source mode is returned to the frontend
- evidence ids are never fabricated
- general fallback is labeled and non-authoritative

## Frontend Product Shape

The frontend should present the copilot as a contextual research assistant.

The top of the panel or page should show:

```text
Knowledge Base: paper-ab
Focus: 316L stainless steel
Mode: Hybrid
Goal: Compare process effects on strength and elongation.
```

The assistant may live in:

- a goal-first entry page
- a collection-scoped assistant page
- a workspace side panel
- a material detail side panel with automatic material focus

When the user opens a material detail page, the frontend may update the active
session with the current material as page context. This should be explicit in
the UI so the user understands why the assistant answers about that material.

Answers should link back to the product surfaces that own the evidence:

- material profile
- comparison rows
- evidence drawer
- paper detail or source context
- review report draft when available

The copilot should not trap the workflow inside chat.

## Answer Flow

Each user message should follow this flow:

1. Load the `GoalSession`.
2. Parse commands or natural-language context changes.
3. Update collection, focus, goal, or mode if needed.
4. Retrieve scoped Core and derived artifacts from the bound collection.
5. Decide whether collection evidence is sufficient.
6. Generate an answer under the selected mode.
7. Return source mode, evidence ids, links, warnings, and display text.
8. Update rolling summary and recent artifact references.

This flow keeps conversational continuity without creating a second research
fact system.

## MVP

The first implementation should include:

- create and load a goal session
- bind one collection
- focus one material from page context
- support `grounded`, `hybrid`, and `general` modes
- retrieve collection Core results before answering in grounded and hybrid
  modes
- return source mode and used evidence ids
- save a rolling summary
- show evidence chips and fallback labels in the frontend

The first implementation should not include:

- multi-collection reasoning
- long-term user preference memory
- autonomous planning agents
- broad tool-calling orchestration
- unbounded external retrieval
- automatic claims that bypass Core artifacts

## Evidence Boundary

Collection-grounded answers may say:

```text
The current collection shows...
The evidence cards support...
S001 and S002 differ in...
```

General fallback answers should use language such as:

```text
In general materials-science background...
Commonly, LPBF process parameters can...
This is not established by the current collection.
```

General fallback answers must not:

- cite fake evidence ids
- imply the current collection contains the fact
- update Core artifacts
- become evidence in later turns
- support report conclusions unless separately grounded by collection evidence

## Phased Rollout

### Phase 1: Session And Binding

Deliver:

- goal session creation
- collection binding
- mode selection
- simple commands
- page-context material focus

### Phase 2: Collection-Grounded Answers

Deliver:

- scoped retrieval from material, comparison, and evidence surfaces
- grounded and limited answer generation
- evidence chips and links back to owning workspace surfaces

### Phase 3: Hybrid Fallback

Deliver:

- general fallback only when collection evidence is empty or insufficient
- visible fallback labels
- rolling summary that preserves source boundaries

### Phase 4: Review Draft Integration

Deliver:

- goal-aware review draft prompts
- report generation that uses only collection-grounded claims for evidence
  sections
- explicit separation between grounded conclusions and background discussion

## Risks

Main risks:

- users may mistake general fallback for collection evidence
- chat convenience may hide the structured workspaces that own the facts
- rolling summaries may accidentally promote general knowledge into evidence
- a broad agent runtime may introduce a second fact model beside Core

Mitigations:

- show source labels on every answer
- require evidence chips for collection-grounded claims
- preserve source boundaries in rolling summaries
- route answers back to material, comparison, evidence, and paper surfaces
- keep Core artifacts as the only durable research fact source

## Verification

This direction is successful when:

- a user can bind a collection and ask a contextual question
- material detail page context can narrow the active session
- grounded mode refuses to answer when collection evidence is absent
- hybrid mode gives useful background only with a visible fallback label
- no answer fabricates evidence ids, sample ids, paper names, or property
  values
- evidence-backed answers link back to Core-owned surfaces
- rolling summaries keep general fallback separate from collection-supported
  findings

## Related Docs

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
- [Lens Agent-Era Positioning and Evidence Layer Direction](rfc-lens-agent-era-positioning.md)
- [Backend Five-Layer Research Architecture](../../backend/docs/architecture/goal-core-source-layering.md)
- [Goal Copilot Proposal](../../frontend/docs/goal-copilot-proposal.md)
