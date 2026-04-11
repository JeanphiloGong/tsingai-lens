---
id: RFC-2026-002
title: Lens Agent-Era Positioning and Evidence Layer Direction
type: rfc
level: system
domain: shared
status: draft
owner: repo-maintainers
created_at: 2026-04-11
updated_at: 2026-04-11
last_verified_at: 2026-04-11
review_by: 2026-07-11
version: v1
source_of_truth: false
related_issues: [63]
related_docs:
  - docs/10-rfcs/evidence-first-literature-parsing.md
  - docs/30-architecture/system-overview.md
  - backend/docs/api.md
supersedes: []
superseded_by: []
tags:
  - rfc
  - agents
  - positioning
  - evidence
  - comparison
---

# Lens Agent-Era Positioning and Evidence Layer Direction

## Summary

This RFC proposes that Lens should not compete as another generic "research
agent". In the agent era, Lens becomes more valuable as the evidence layer,
judgment layer, and memory layer that both researchers and agents rely on.

The core idea is simple:

- agents can execute research workflows
- Lens should define what counts as structured evidence
- Lens should decide what is comparable, traceable, and safe to carry forward
- Lens should preserve collection-level memory so work compounds instead of
  resetting on every run

This RFC complements
[`evidence-first-literature-parsing.md`](evidence-first-literature-parsing.md):
that RFC defines the parsing direction, while this RFC defines Lens's product
position in an agent-heavy stack.

## Context

### Why this matters in the agent era

Agent systems are making paper retrieval, batch reading, extraction, and
summary generation cheaper every month. That does not mean they automatically
produce reliable scientific judgment.

What remains scarce is:

- stable evidence structure across papers
- comparability rules between claims and experiments
- provenance and auditability for every important judgment
- explicit abstain paths when the evidence is weak or the papers are not
  comparable
- durable collection memory that later runs can build on

If Lens only offers "an agent that reads papers", it will collapse into
commodity model capability. If Lens owns the evidence structure and judgment
rules, it remains valuable even when model and agent capabilities improve.

### What generic agents are good at

Generic agents are useful for:

- searching and retrieving papers
- orchestrating multi-step workflows
- producing first-pass extraction and summaries
- calling tools in batch
- drafting possible next steps

### What generic agents are not enough for

Generic agents do not reliably provide:

- a durable schema for claim, evidence, condition, and baseline storage
- consistent cross-paper comparability decisions
- explicit "do not conclude" behavior when conditions are missing
- strong provenance back to spans, sections, figures, and tables
- collection memory that survives beyond a single run
- a clear separation between extracted text and decision-grade research objects

These gaps are where Lens should concentrate.

## Scope

This RFC covers:

- system-level positioning for Lens in the agent era
- the responsibilities Lens should own versus what agents should own
- the architectural role of Lens as a callable evidence and judgment layer
- the phased path from human-first product value to agent-callable tooling

This RFC does not cover:

- detailed API schemas for every tool
- specific model vendor choices
- workflow engine or orchestration framework selection
- frontend interaction design
- replacing the evidence-first parsing RFC

## Proposed Change

### 1. Define Lens as research infrastructure, not another agent

Lens should be positioned as a research evidence engine for agents and
researchers.

Lens should not be framed as:

- a generic paper chat shell
- a single-paper summary product
- an autonomous "AI scientist"
- a system whose value comes from agent personality or orchestration alone

Lens should be framed as:

- an evidence layer
- a judgment layer
- a tool layer
- a collection memory layer
- an audit and traceability layer

The practical rule is:

Agents can execute; Lens constrains, stores, compares, and traces.

### 2. Make Lens responsible for what agents cannot safely improvise

Lens should own the system responsibilities that should not be re-invented in
every agent run:

- schema for `claim`, `evidence`, `condition`, `baseline`, and `comparability`
- provenance requirements for stored outputs
- evidence-strength and confidence gating
- abstain and refusal semantics such as `insufficient`, `not_comparable`, and
  `not_extractable`
- collection-level memory and accumulation rules
- comparison logic for cross-paper reasoning

This is the layer that determines whether agent output becomes durable research
signal or disposable chat text.

### 3. Place Lens in the stack above model capability and below final workflow decisions

The target stack should be:

1. foundation models
2. agent orchestration and workflow execution
3. Lens evidence and judgment layer
4. researcher or downstream decision workflow

The responsibilities of each layer are:

1. foundation models
   Understand text, figures, terminology, and local relationships.
2. agent orchestration
   Search, retrieve, sequence tools, and batch process documents.
3. Lens
   Normalize outputs, enforce structure, decide comparability, preserve
   provenance, gate confidence, and persist collection memory.
4. researcher workflow
   Review evidence-backed outputs and decide what to test, compare, or trust
   next.

Lens should become the stable layer that prevents the system from degenerating
into a pile of summaries, CSVs, and transient chats.

### 4. Design internal capabilities as future agent-callable tools

Lens should first be useful for humans, but its internal boundaries should be
designed so agents can call them later without reinterpreting the system.

Representative future tool surfaces include:

- `profile_document`
- `extract_claims_evidence`
- `store_structured_units`
- `check_comparability`
- `retrieve_evidence_trace`
- `rank_clues`
- `decide_protocol_extractable`

The important constraint is not the exact endpoint list. The important
constraint is that each capability has a stable input and output contract
centered on evidence and judgment objects rather than free-form chat.

### 5. Keep protocol and SOP generation as a downstream branch

Protocol extraction remains useful, but it should stay downstream of the
evidence layer.

In the agent-era positioning:

- protocol output is conditional
- evidence-backed comparison is primary
- extraction quality gates must block unsafe procedural generation
- review or mixed literature may produce comparison value without producing any
  final protocol steps

This keeps the system aligned with the evidence-first direction rather than
reverting to a procedure-first identity.

### 6. Follow a phased path instead of jumping straight to agent platform claims

The recommended sequence is:

1. prove Lens as a human-usable evidence and comparison system
2. harden the internal evidence, provenance, and comparability boundaries
3. expose stable tools and APIs for agents
4. let external or internal agents use Lens as their research runtime

This avoids a common failure mode where a product claims to be an "agent
platform" before it has a stable evidence model underneath.

## Verification

This direction is successful when the system can demonstrate the following:

- a human workflow can compare a collection of papers through evidence-backed
  outputs instead of raw summaries
- agent-produced outputs are stored with provenance, confidence, and collection
  identity
- the system can explicitly return `not_comparable`, `insufficient`, or
  `not_extractable` rather than forcing every flow into a positive answer
- repeated work adds to collection memory instead of recreating temporary
  summaries from scratch
- protocol generation remains a conditional branch rather than the required
  result of every upload

## Risks

- If Lens is presented primarily as an agent shell, it will be hard to
  differentiate from rapidly improving general-purpose agents.
- If schema and provenance remain weak, agent integration will amplify errors
  instead of compounding value.
- If the system tries to expose too many tools before the evidence model is
  stable, the tool layer will freeze the wrong abstractions.
- If product messaging over-promises autonomous research behavior, trust will
  erode faster than the evidence layer matures.

## Follow-On Work

This RFC should feed the next layer of work:

- a concrete Lens tool and API boundary definition
- first-class data objects for evidence and comparison
- collection-memory rules for incremental agent runs
- confidence and refusal contracts across ingestion, parsing, comparison, and
  protocol generation
