# Goal Copilot Proposal

## Purpose

This document records a frontend proposal for introducing a goal-first chat
entry without turning Lens into a generic research chatbot.

The proposal is to build a collection-scoped, Core-grounded Goal Copilot with
chat-like interaction and workflow-first control.

It should help users:

- express a research objective in natural language
- converge that objective into a structured Goal Brief
- enter the normal collection and workspace flow
- ask goal-oriented questions only after Core artifacts are ready

It should not replace the collection workspace, Core backbone, or evidence
traceability model.

## Scope

In scope:

- frontend product shape for a goal-first conversational entry
- interaction states before and after Core readiness
- user-facing boundaries between goal intake and Core-grounded analysis
- minimum backend-facing contract expectations needed by the frontend
- phased rollout guidance for a narrow, controlled first implementation

Out of scope:

- implementing a generic agent framework
- replacing the current collection-first flow
- redesigning backend Goal Brief or Goal Consumer architecture authority
- locking the backend to one exact future endpoint shape
- free-form open-domain chat that bypasses collection and Core artifacts

## Companion Docs

- [`../README.md`](../README.md)
  Frontend module entry page
- [`frontend-plan.md`](frontend-plan.md)
  Current frontend same-origin API and product flow guide
- [`../src/routes/collections/lens-v1-interface-spec.md`](../src/routes/collections/lens-v1-interface-spec.md)
  Current collection route-family spec
- [`../../backend/docs/architecture/goal-core-source-layering.md`](../../backend/docs/architecture/goal-core-source-layering.md)
  Backend layer authority for Goal Brief, Core, and Goal Consumer boundaries
- [`../../backend/docs/specs/api.md`](../../backend/docs/specs/api.md)
  Current public contract for `goals/intake`, workspace, and Core surfaces

## Why This Needs A Separate Proposal

The current frontend docs already describe:

- same-origin API rules
- collection-first Lens v1 route structure
- workspace, comparisons, evidence, and documents as primary product surfaces

What they do not yet define is how a goal-first conversational experience
should fit into that model without weakening Core ownership or drifting into a
generic chat shell.

This proposal narrows to that product and interaction question.

## Product Position

The Goal Copilot should be a specialized research assistant for one Lens
workflow:

`goal definition -> collection handoff -> Core build -> Core-grounded analysis`

It should not behave like a generic bot that decides ad hoc whether to search,
answer, browse, or synthesize from arbitrary sources.

The key product rule is:

chat may be the interaction shell, but Core remains the fact source.

## Core Design Decision

The frontend should treat one user-visible conversational experience as having
two distinct internal phases:

1. Goal Brief phase
2. Core-grounded analysis phase

The user may experience this as one continuous conversation, but the system
must not treat both phases as one undifferentiated chatbot behavior.

### Phase 1: Goal Brief

Purpose:

- clarify what the user wants to study
- shape the request into a structured goal
- create or seed a collection handoff

Primary backend dependency:

- `POST /api/v1/goals/intake`

Allowed outputs:

- structured research brief
- coarse intake-side coverage hint
- seeded collection identity
- entry recommendation

Not allowed in this phase:

- evidence-backed scientific conclusions
- comparison judgments as if Core were already available
- answers that imply collection-derived facts before indexing exists

### Phase 2: Core-Grounded Analysis

Purpose:

- answer goal-oriented questions using real Core artifacts
- organize evidence, comparisons, and gaps around the user's objective

Required data basis:

- `document_profiles`
- `evidence_cards`
- `comparison_rows`
- traceback, uncertainty, and review-related fields exposed by those surfaces

Allowed outputs:

- goal-oriented filtering
- evidence-backed summaries
- gap and missing-context guidance
- next-step recommendations grounded in Core outputs

Not allowed in this phase:

- answers that bypass Core facts
- opaque model-only conclusions with no artifact grounding
- a second fact model parallel to Core artifacts

## Why This Split Exists

This proposal separates Goal Brief from Core-grounded analysis for four
reasons.

### 1. Goal definition and evidence-backed judgment are different jobs

The user can describe an objective before any papers are uploaded or indexed.
The system can only produce grounded comparison and evidence answers after the
collection has been turned into Core artifacts.

### 2. Goal-first and paper-first paths must converge

Lens v1 is collection- and workspace-centered. A goal-first entry must still
land in the same collection-backed workflow as upload-first entry, rather than
creating a parallel chat-only product path.

### 3. Core must stay the only stable fact source

If the conversational surface is allowed to answer directly from loose
retrieval or model memory, the product will drift away from the traceable Core
backbone that Lens is built around.

### 4. The first implementation should stay controlled

A workflow-first copilot can deliver a useful goal-first experience without
requiring a full agent runtime, planner, or unrestricted tool-calling bot.

## Proposed Frontend Experience

The Goal Copilot may look like a chat interface, but it should operate as a
stateful guided assistant.

### State A: Clarify Goal

The user enters a natural-language research objective.

Example:

- compare residual-stress control strategies for Ti alloy DED with induction
  assistance

Frontend behavior:

- ask only the narrow follow-up questions needed to complete the Goal Brief
- present editable structured fields for:
  - material system
  - target property
  - intent
  - constraints
  - context
- show the normalized research brief before handoff

Primary action:

- create or continue a goal-seeded collection

### State B: Prepare Collection

If the seeded collection has no source material or no finished indexing yet,
the copilot should not pretend it can answer the research question already.

Frontend behavior:

- show collection creation success
- guide the user to upload files or connect a source path when available
- show task progress and readiness state
- route the user into workspace as the collection home

Primary action:

- finish collection preparation and wait for Core readiness

### State C: Answer From Core

Once Core artifacts are ready, the same conversational surface can shift into
analysis mode.

Frontend behavior:

- answer questions against collection-scoped Core data
- ground responses in comparisons, evidence, and document facts
- expose links back to workspace, comparisons, evidence, and source context
- make missingness, uncertainty, and expert-review conditions explicit

Primary actions:

- inspect comparisons
- inspect evidence
- open source context
- refine the current question

## UX Rules

- the interface may resemble chat, but it should not behave like an
  unconstrained assistant
- the current state must always be visible: clarifying goal, preparing
  collection, processing, or answering from Core
- the system should never imply evidence-backed conclusions before Core is
  ready
- each answer in analysis mode should link naturally back to collection
  surfaces instead of trapping the user inside chat
- warnings, uncertainty, and review flags must remain explicit
- user-facing language should describe research workflow, not backend engine
  internals

## Recommended Backend Interaction Model

This proposal intentionally favors a controlled workflow over a generic chat
agent in the first implementation wave.

Recommended model:

- keep `goals/intake` as the Goal Brief and collection-handoff endpoint
- keep workspace as the collection entry surface after handoff
- add a narrow collection-scoped analysis endpoint only when the Core-grounded
  chat phase is ready
- keep that future analysis surface restricted to Core-backed answers

Avoid in the first wave:

- one generic chat endpoint that decides on its own when to call every backend
  surface
- a broad tool-calling runtime with planner-style orchestration
- mixing goal clarification and evidence-backed answering into one opaque
  backend step

## Suggested Route Strategy

Possible frontend route shape:

- dedicated goal-first entry page at a module-level route such as `/goal`
- after handoff, redirect into `/collections/[id]`
- analysis chat may either live:
  - inside workspace as a guided panel, or
  - in a collection-scoped assistant route such as `/collections/[id]/assistant`

This proposal does not freeze the exact route yet.

The main rule is:

the assistant becomes collection-scoped once it starts consuming Core.

## Phased Rollout

### Phase 1: Goal Brief Copilot

Deliver:

- goal-first natural-language entry
- structured Goal Brief editing
- `goals/intake` integration
- collection handoff confirmation
- workspace redirect

Do not deliver yet:

- evidence-grounded conversational answering

### Phase 2: Processing And Readiness Guidance

Deliver:

- collection preparation state in the copilot shell
- upload and indexing guidance
- progress and readiness explanation

Do not deliver yet:

- free-form research answers before Core readiness

### Phase 3: Core-Grounded Analysis Chat

Deliver:

- collection-scoped chat against Core outputs
- grounded answers with links back to comparisons, evidence, and source
- explicit handling of uncertainty and review-required cases

## Verification Plan

The proposal should be considered successful when:

- a user can start from a natural-language goal without falling into a generic
  chat dead end
- goal-first entry still converges on the normal collection and workspace flow
- the copilot does not claim evidence-backed conclusions before Core readiness
- analysis-mode answers are visibly grounded in Core artifacts
- users can navigate from a chat answer into comparisons, evidence, and source
  context
- the assistant remains collection-scoped rather than becoming a global chat
  shell

## Risks

Main risks:

- the UI may look like a generic chatbot and create the wrong user expectation
- a single all-purpose chat endpoint would blur Goal Brief and Goal Consumer
  responsibilities
- conversational convenience could tempt the product to bypass traceable Core
  surfaces
- the assistant could become a parallel navigation surface instead of a guide
  into workspace and Core artifacts

Mitigations:

- make state transitions explicit in the UI
- keep the first wave workflow-first rather than agent-first
- keep Core-backed answering collection-scoped and traceable
- route users back into workspace, comparisons, evidence, and document context
  instead of replacing those surfaces

## Non-Goals

- building a general-purpose scientific chatbot
- replacing comparisons, evidence, documents, or workspace with one chat view
- introducing a new fact source outside Core
- treating `goals/intake` as if it already were the full Goal Consumer layer
