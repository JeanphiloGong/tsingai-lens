# Chat Application Layer

This package owns the collection-bound Research Agent conversation. It turns
an authenticated user's message into resource-bounded model decisions, ordered
typed capability calls, and a durable, reviewable trajectory.

The prompt frames conversation as professional research collaboration: explain
the research question, supporting observations, limits, progress, and next
researcher decision. Ordinary replies translate tool and status identifiers
into that research meaning, including when explaining pending approval.

## Start Here

- HTTP entry: `controllers/chat/sessions.py`
- Turn orchestration: `ChatSessionService.post_message_for_user()`
- Agent loop: `ResearchAgentRunner.run_turn()`
- Tool lookup: `CapabilityRegistry`
- Approval continuation: `ChatSessionService.decide_tool_call_for_user()`

One turn follows this sequence:

```text
user message -> bounded model decision -> capability call
  -> capability result -> trajectory checkpoint -> final answer or approval
```

Read capabilities may inspect canonical collection resources. Write
capabilities stop for exact user approval. Chat never owns a second Objective,
Evidence, Finding, or Analysis record; it calls the Source and Core services.

## Boundary Checklist

| Concern | Owner | Scientific authority |
|---|---|---|
| Conversation and checkpointing | `session_service.py` | none |
| Context selection | `context_builder.py` | none |
| Model/tool loop | `agent_runner.py` | none; execution only |
| Tool discovery and execution prerequisites | `capabilities/tool_discovery.py` and `capability_policy.py` | approval only |
| Explicit write requests | `intent_policy.py` | no execution authority |
| Objective, Evidence, Finding data | `application/core/` | Core services |

When adding a capability, define its typed input/output and approval risk first;
do not add scientific state to the Chat trajectory.

## Main Flow

```text
authenticated user + collection
  -> ChatSessionService validates and persists the user message
  -> ChatContextBuilder selects a bounded trajectory for the model
  -> ResearchAgentRunner exposes short read/draft descriptions and explicit writes
  -> ChatModel selects names through discover_research_tools when needed
  -> Runner exposes the selected registered parameter schemas for this request
  -> ChatModel returns an answer, independent reads, or one draft/write call
  -> Runner checkpoints the complete ordered request before execution
  -> capabilities return paired observations or exact approval_required
  -> ChatSessionService checkpoints the trajectory and final response
```

Source context attached from the document reader is resolved against the
canonical Source before the model runs. A quote is inspection material, not
Evidence or permission to mutate a scientific record.

Read and draft capabilities can execute during the turn. Write capabilities
persist their exact arguments and digest, stop for the authenticated user's
approval, and execute only that approved call once. Rejection, provider
failure, malformed model output, and resource limits remain technical trajectory
outcomes; they are not scientific conclusions.

Read and transient-draft discovery uses the model's interpretation of the
request, including filenames, paper identifiers, and conversational references.
It does not require words such as "paper" or "source" to unlock inspection.
Greetings, general knowledge, and application explanations can finish without
discovery. An explicit no-tools request exposes no capabilities.

`discover_research_tools` is an ordinary typed function call, not a provider's
native ToolSearch API. Its short catalog comes from registered read/draft
handlers. It loads up to six named schemas per call and performs no scientific
read, write, or approval. Successful results with the current catalog version
load definitions only for the active user request. Automatically selected
prerequisite readers remain available after execution in that request too.
The next user request starts with a fresh catalog.

Discovery also records whether the request needs a particular paper's claims
or measurements inspected. That model-selected obligation survives later
discovery calls within the request. After a survey, it requires Source
navigation and complete reading, including for a claim attributed to a review;
paper selection alone does not impose this obligation. This is an execution
prerequisite, not a determination that the inspected passage supports the claim.
Source-reading stages use that recorded request rather than comparison or
reading keywords. Selecting papers for a later comparison therefore remains
a navigation task. Existing-conclusion review reads the Finding and Evidence
before the Source requirement can advance to paper inspection.

At mandatory action stages the model context requests a provider tool call
(`tool_choice=required`). The runner independently checks that a required
action occurred, and suppresses answer deltas that would otherwise appear
before that check. Provider failures remain failures: the deterministic reply
preserves the reading ledger and distinguishes unread papers and failed reads
from scientific absence. Empty-response diagnostics contain only model name,
normalized stop reason, reasoning presence, and token count.

Answer finalization separates the current request's reading ledger from earlier
complete Source inspections. Zero new reads cannot erase the preceding research
context; historical references alone cannot recover omitted text or authorize a
new Evidence write. Filtered filename counts are not reported as collection
totals, including when a literal filename search has no matches.

Scientific answers following Source or published-result inspection, and question,
scope, and research-plan proposals, receive a separate claim review before their
text is emitted or their draft calls execute. The review checks per-paper claim
scope, the requested measurement identity, and the scope of evidence-gap claims.
Its input contains the original user request, available observations and exact
candidate and observation field paths. The reviewer selects those paths; the
runner checks that every selected field and reference exists and retrieves the
original value for correction feedback. The reviewer does not copy or rewrite
source excerpts. A proposal cannot serve as its own independent support.

For example, a third paper with no reported deterioration cannot establish a
shared upper-temperature limit, yield strength cannot replace requested ultimate
tensile strength, and an unresolved equipment transfer in the inspected papers
cannot establish field-wide novelty. These checks cover draft fields as well
as the final explanation. One correction receives the specific rejected fields
and their basis, and is reviewed again. Draft corrections retain their action;
they cannot silently substitute a different operation. Unresolved claims,
invalid review output or unavailable review stop the unchecked content while
preserving completed reads. Normal capability and exact approval checks still
apply after the correction.

Proposed experimental measurements remain distinct from reported paper results.
An experiment may specify new measurements and clearly separate auxiliary
endpoints without claiming the literature already contains those measurements.
Missing extracted numeric values do not establish that the paper reports no
numbers. An equipment ceiling also does not establish a researcher-selected
operating setpoint; proposed values retain their proposed status.

When a checked plan succeeds and no further capability is available for the
request, the runner returns the capability's complete existing Markdown draft
with an explicit unsaved status. It does not ask the model to rewrite that
already reviewed deliverable. This preserves its actual wording, source basis
and pending researcher-review status while avoiding another generation/review
cycle. Unresolved references and requested saving still follow their normal
correction and approval paths.

The reviewer uses the existing provider with no executable tools. Its requests,
correction and usage count toward the same run. The existing answer-only
finalization allowance also covers its bounded review and one correction after
the reading allowance is exhausted; finalization cannot restart tool work and
still shares the original elapsed-time deadline. Scientific text is buffered
until accepted, so its first visible text may arrive later. Tool activity remains
visible separately. A model review is fallible and does not certify scientific
truth; explicit evidence, adversarial evaluation and researcher review remain
necessary.

The default whole-turn deadline is 600 seconds and the cumulative model-token
admission threshold is 240,000 to include claim review and one correction.
`LENS_AGENT_MAX_TURN_SECONDS` and `LENS_AGENT_MAX_MODEL_TOKENS` can override them.
The 24-tool-call allowance is unchanged. Review is sequential, so long comparisons
and plans can take several minutes before accepted text appears and use more
model tokens. Exhausting an explicitly smaller allowance still stops unchecked
drafts; it does not bypass review.

For example, a researcher asking to inspect the P002 group definitions can load
paper navigation, locate the canonical Methods Source, and read its exact
document/kind/reference tuple. Search previews do not satisfy the complete
Source prerequisite for Evidence. A failed read permits discovery of navigation
tools for recovery or an honest failure explanation; it grants no Evidence
authoring authority. Successful navigation restores the exact-read requirement
for located Sources; an earlier failed reference cannot waive that requirement.
Source handlers still validate Collection ownership.

Only the latest successful search batch supplies pending reading candidates.
Each independent query in that batch needs one matching complete Source; its
matches remain alternatives, not a requirement to read every search hit. A
previous Methods read cannot satisfy a later search for an unread results
table. A complete read of the same Source and digest can be reused in the
active request. The candidate display is bounded, but matching checks all
returned candidates.

Complete reading includes contiguous `read_source` character pages or intact
`inspect_table` row windows from offset zero through the canonical length or
row count. Pages must agree on document, Source kind/reference, digest, and
length; character offsets and row offsets never mix. Missing pages, oversized
row previews, other versions, and earlier user requests cannot fill a gap.
Reading only the final table window is not a complete read. Evidence requests
must match the digest that was actually read. The final reading ledger uses
this same check, so a partial read is not reported as a complete Source.

Discovery excludes writes. Explicit write selection, exact argument validation,
and authenticated approval remain separate. Revising a saved plan additionally
requires its exact Objective and parent plan ID in this request's successful
inspection results; the runner checks this again after approval. A completed
approved write is not offered again during its continuation.

Explicit no-save/no-publish requests suppress all persistent capabilities,
including feedback, Evidence, plan revision, and analysis publication, before
schemas are offered. Discovery and transient drafts do not lift that limit.
Keeping an old version unchanged can still allow an explicitly requested new
immutable version; a prohibition on saving, creating, or publishing the new
version takes precedence. Creating an Objective candidate, confirming it, and
starting analysis remain separate approval decisions.

If an approved write fails, its continuation explains that failure without
starting more capability work. A fresh user decision can inspect changed
Sources or propose a new exact approval; the failed action is not retried
implicitly.

Before a plan proposal, the stage instruction lists the inspected Finding and
Evidence relationships. An Evidence ID in the collection-wide overview is not
automatically eligible for every Finding. A plan proposal with missing or
unlinked references remains an abstention, not a completed draft. The Agent may
correct that selection once using the valid
subset of its selected Finding IDs and their linked Evidence from one current
version. Rejected Findings, extraction failures, and a selection with no valid
current support do not qualify for that correction. If that
correction has invalid argument structure, one further attempt can address
the reported field names and error types; argument values are not echoed in
validation errors. An unresolved abstention cannot expose a saving capability;
the final answer explains the missing basis without claiming a draft is ready
or promising an unexecuted resubmission. An answer-only response must deliver
the requested result or explain a concrete evidence gap, rather than announce
another inspection.

Research-plan proposals distinguish condition-dependent trends from conflicting
measurements under comparable conditions. Small-sample uncertainty can leave a
hypothesis unresolved; the researcher's sample cap is neither a standards
requirement nor proof of sufficient statistical power. Drafts retain the
review status of their supporting Findings and unverified feasibility checks.

## Responsibilities

- keep one ordered trajectory of user and assistant messages, capability calls,
  structured results, and approval decisions;
- bound model context, capability exposure, elapsed time, tools, model usage, and continuation
  behavior for each turn;
- authorize capabilities by risk and bind writes to the exact stored arguments,
  user, and pending call;
- preserve canonical resource references so collection observations can be
  traced back to Source and Core records; and
- checkpoint durable state after each meaningful transition so refresh and
  interrupted streams remain understandable.

## Key Areas

- `session_service.py`: owns session reads, source-context validation, turn
  persistence, streaming, and approval execution.
- `agent_runner.py`: runs the bounded model, capability, and continuation loop
  and reports `completed`, `approval_required`, or `failed`. Completion records
  why work stopped: a model answer, resource budget, repeated observations, or
  the emergency cycle ceiling. One private request path enforces model
  deadlines and output allowances for both decisions and answer-only
  finalization. Technical limits permit finalization with scope warnings only
  while turn time remains; a failed finalization remains a failure.
- `context_builder.py`: selects a bounded, protocol-safe conversation context
  while pinning the active question and keeping whole request/result batches
  together. The default 128,000-character allowance accommodates a batch of
  eight detailed published Findings and their Evidence for a research-plan
  decision. Omitted history contributes deterministic lineage, not paper text
  or scientific claims, to a transient rollover summary.
- `model.py`: defines the asynchronous provider-neutral model contract,
  request timeout/output limits, reported usage (including invalid responses),
  and the Research Agent instructions. Implementations must propagate
  cancellation and close in-flight streams without background thread work.
- `intent_policy.py`: supplies explicit write-request vocabulary and research
  prerequisite signals. Its legacy read-name groups do not grant read access.
  It has no model, persistence, or capability side effects.
- `capability_policy.py`: selects discovered tools from the request and completed
  observations, validates batches and exact Source prerequisites, and maps
  capability risk to automatic execution or exact user approval. The Runner
  consumes these decisions; it does not define a second permission path.
- `capabilities/tool_discovery.py`: derives the short catalog from registered
  read/draft handlers and validates selected names and catalog version.
- `capabilities/`: contains the explicit typed capability registry and handlers
  for collection and Source inspection, Objective work, Finding and Evidence
  authoring, analysis review, and research-plan drafts or writes.

## Boundaries

- `application/source/` owns Collection membership, Document preparation, and
  canonical Source loading.
- `application/core/` owns Objective discovery and analysis, Evidence, and
  Findings.
- `application/goal/` owns research briefs and Objective-scoped plans after an
  approved Chat or workspace action.
- `domain/chat/` owns the durable session, message, capability-call, result,
  and approval records.
- `controllers/chat/` owns the HTTP route and response boundary.

Do not add arbitrary tools, network access, shell access, or untyped scientific
state to this package. New capabilities need a real research responsibility,
an explicit input and result contract, authorization semantics, and an
end-to-end scenario that preserves Source traceability.

## Changing This Module

For ordinary response wording, start with `model.py`; for request vocabulary,
start with `intent_policy.py`. For prerequisite reads or approval, use
`capability_policy.py`. Change `agent_runner.py` only when execution order,
continuation, checkpointing, or stopping behavior must change.

To add a capability, implement its typed handler under `capabilities/` and
register it in the existing registry. Read/draft handlers enter the catalog
automatically; writes need explicit request and approval policy.
The handler calls the owning Source, Core, or Goal service. The Runner does not
need a branch for each new capability. A read or draft returns an observation;
an approved write may persist a scientific resource through its existing owner.

Provider and capability exception logs contain sanitized metadata only, without
exception text or tracebacks. Model failure, invalid tool arguments, rejected approval, and incomplete work
are recorded in the trajectory. They never become Evidence or a negative
scientific answer. After a turn stops, the next user message or exact approval
decision starts its continuation through `ChatSessionService`.

## Tests

From `backend/`, run:

```bash
.venv/bin/python -m pytest -q tests/unit/application/test_research_tool_discovery.py tests/unit/application/test_research_agent_runner.py tests/unit/application/test_chat_session_service.py tests/unit/routers/test_chat_sessions_api.py
```

Capability tests are under `tests/unit/application/test_chat_research_*.py`.
`tests/unit/application/test_chat_source_read_policy.py` exercises P002 Methods
and Table 2 navigation, paginated Evidence drafts, incomplete reads, version
changes, and the request boundary through the production Source capabilities.
The real-Source and PostgreSQL research-cycle case is
`tests/integration/test_deep_path_research_flow.py`; its prerequisites and
scientific assertions are described in
[`../../tests/objective-analysis-verification.md`](../../tests/objective-analysis-verification.md).

## Related Docs

- [`../../docs/specs/api.md`](../../docs/specs/api.md): HTTP and capability
  contracts, including the approval lifecycle.
- [`../../docs/architecture/overview.md`](../../docs/architecture/overview.md):
  backend ownership and runtime boundaries.
- [`../../docs/runbooks/backend-ops.md`](../../docs/runbooks/backend-ops.md):
  budget settings, cancellation, and finalization limits.
- [`../../../docs/decisions/rfc-collection-bound-research-agent.md`](../../../docs/decisions/rfc-collection-bound-research-agent.md):
  accepted Research Agent design and real-world scenario mapping.
- [`../core/README.md`](../core/README.md): scientific Objective, Evidence, and
  Finding ownership referenced by Chat.
