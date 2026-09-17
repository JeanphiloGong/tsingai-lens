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

Repeated identical calls within one model response execute once. Retained calls
are assigned contiguous positions so checkpointed requests and results stay paired.

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

Persistence intent is scoped to the requested action: saving error feedback
while declining curation or publication exposes only the feedback write.
Read-only requests and a prohibition on all saving still disable every write.
Feedback and curation keep separate exact-argument approvals. Their explicit
save requests require the actual approval-producing tool call; a prose request
for confirmation is not a completed deliverable. Discovery remains available
when the target needs identification. Their successful
approval replies render the saved result directly, without a model continuation
that could incorrectly report another pending approval.
Before a curation write, the runner carries forward the complete Finding envelope
from the exact inspection. Only the proposed scientific wording and other
reviewed fields may change; identity, Evidence bindings, paper coverage, and
lineage remain subject to the canonical validator and the user's approval.

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
The review obtains the prepared outline for linked papers, then reads the exact
Sources already linked by that Finding before broad navigation. The outline
reports section headings, pages and counts independently of search filters;
initial navigation also supplies first Source references for those sections.
Exact `heading_path` filters and offsets support progressive
section reading. The current turn's complete Source reads are counted per section;
reading one passage does not mark the whole paper or scientific check complete.
The per-paper reading ledger also retains papers from earlier searches in the
same request, even when later searches narrow their scope. A paper without an
inspected outline remains visible with unknown prepared coverage; a failed
inspection is not treated as an empty paper. Prepared pages, completely read
passages, and unread sections remain distinct. The runner regenerates this
ledger from the complete request trajectory before context selection, so model
compaction notes cannot erase a pending paper. Browsing a Collection alone does
not select every listed paper for investigation. The ledger supplies coverage
facts; the model still decides which sections address the research question.
For requested sections, the ledger preserves unfinished batch offsets and the
returned parser block types through compaction. Reading a section heading is
recorded separately from other passages. The model can continue the exact
section from its offset, or reduce parallel requests when the result allowance
only fits headings; a successful heading read does not complete a Methods check.
Source placeholders also remain pending after the last section page; their
exact text/table reader clears them only when whole-source coverage is recorded.
Section reads retain all outline headings, pages and counts, while repeating
detailed size and locator metadata only for the selected section to leave room
for its body. Final result-size checks still enforce the supplied context budget.

The comparison instructions apply these checks to ordinary paper comparisons as
well as Finding corrections: inspect available material/feedstock, fabrication,
treatment, control and measurement details before deciding comparability.
Finding one difference does not finish the other requested checks; unavailable
prepared content remains an explicit limitation for that paper.

For example, a researcher challenges a claim that annealing reduces elongation
in every paper. The Agent checks the disputed Finding and Evidence, identifies
the relevant methods and tensile-results sections, and reads the available
treatment conditions, comparators and outcomes before drafting a correction.
When an untruncated outline contains only front matter, the Agent reads the
relevant abstract once and identifies the missing body check. Prepared coverage
does not describe the original publication's total page count or prove scientific
absence. Resolved questions and genuinely unavailable checks permit a bounded
partial draft; available but unchecked relevant body sections require further
investigation. Reading within the authorized Collection needs no write approval.
The correction checks the prepared outlines for every contributing paper,
including papers with no Evidence. Reading the linked Sources does not close
the reading tools or mark the investigation complete. The Agent can inspect
remaining relevant sections before drafting; fully read passages from an outline
batch count as reads and do not require a duplicate individual read. Unavailable
checks remain explicit in a partial draft. The visible reading step stays active
until a reviewed draft is actually produced.
The review compares stored Evidence fields with their Source before choosing a
draft. Incorrect extraction requires an Evidence draft, its exact approved
publication, and then a new Finding synthesized from current eligible Evidence.
Correct Evidence remains unchanged when only the synthesis needs revision.
Discovered Evidence tools stay available throughout Finding review. An Evidence
draft can fulfill the immediate correction-draft request while the dependent
Finding remains pending; a draft-only request cannot publish either record.
Feedback and curation are separately requested annotations, not substitutes for
correcting canonical facts or publishing their dependent conclusion.
Compaction notes retain attributed results of completed checks; a partial archive
batch does not reopen every earlier check. Re-reading addresses a disputed detail
or a missing exact authoring input. Notes never replace canonical Source digest,
excerpt and ownership validation for Evidence authoring.
An explicit Evidence or Finding publication request must reach its actual approval
proposal, including when its draft belongs to an earlier turn. Discovery remains
available for required reads and drafts. A failed proposal may be explained or
repaired; a prose confirmation cannot satisfy a write that has not been attempted.
If an Evidence proposal lacks a complete Source read in the active request, its
rejection reopens the exact Source reader. Successful reading restores the normal
proposal flow; a failed read remains a technical failure, never write authority.
After a requested publication's draft succeeds, the execution hint carries that
exact draft forward to approval instead of restarting the investigation. A new
concrete uncertainty can still require reading; compaction alone does not require
another draft, and the draft remains subject to canonical write validation.
Finding draft parameters describe Evidence roles relative to the proposed
conclusion, including when it corrects a disputed parent. Missing supporting
Evidence returns `finding_supporting_evidence_required` so argument repair can
identify the failed prerequisite without exposing exception text or input values.

Finding inspection returns saved feedback and curation for the exact Collection,
Objective, analysis version, and Finding. A fresh conversation can therefore
recall persisted corrections while distinguishing them from the original
published result and from unsaved drafts.
Readback attributes scientific statements to those saved records; it does not
claim the current turn independently reverified their papers. The Agent checks
this attribution against the inspected record; new scientific judgments still
require their Source basis. A completed Finding publication does not require an
additional, unrequested feedback or curation approval.

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

Research turns use one Codex-style decision loop: the model chooses a currently
available capability, receives its result, and decides whether to read more,
revise its answer or finish. Source observations, user feedback and failed calls
are ordinary conversation records in that loop. The runner does not insert a
second claim-review model or a correction-only capability whitelist into an
ordinary turn; this keeps a correction free to re-read the published Finding,
its Evidence, and any relevant Source under the same read policy.

The agent instructions require explicit paper scope, preserved measurement
identity, evidence gaps bounded to inspected material, and a reason for each
Finding. Cross-paper synthesis starts from each paper's observed conditions,
comparator and outcome; each clause of a shared claim must hold for all papers
it names. Objective draft parameters keep distinct measurement endpoints
separate even when their units match. These scientific judgments are fallible
model decisions, not facts certified by the runner's deterministic validation.
Collection ownership, Source identity, version checks and write approval remain
backend responsibilities. An explicit review task may still be added later, but
it must return its findings to this same loop rather than silently replacing it.
The curation tool describes the canonical direction values and reports an invalid
direction at `curated_finding.direction` with the allowed values. This gives the
Agent a concrete argument repair without changing or approving its proposal.

When repeated operations stop making progress, finalization reports unfinished
work. It does not claim a structured deliverable exists or that a resource budget
was exhausted merely because the current response cannot perform more reads.
Repeated Source batches do not become new progress when pagination, reading
coverage counters, or the context-dependent batch token budget changes. New
passages, partial-page content and changed Source versions still count as progress.

Proposed experimental measurements remain distinct from reported paper results.
An experiment may specify new measurements and clearly separate auxiliary
endpoints without claiming the literature already contains those measurements.
Missing extracted numeric values do not establish that the paper reports no
numbers. An equipment ceiling also does not establish a researcher-selected
operating setpoint; proposed values retain their proposed status.

When a plan draft succeeds and no further capability is available for the
request, the runner returns the capability's complete existing Markdown draft
with an explicit unsaved status. It does not ask the model to rewrite that
existing deliverable. This preserves its actual wording, source basis
and pending researcher-review status while avoiding another generation
cycle. Unresolved references and requested saving still follow their normal
correction and approval paths.

A Finding draft similarly finishes with a deterministic unsaved-status
message. The structured result presents the proposed statement and limitations
for researcher review. This remains a transient conversation draft,
not published Evidence or a saved scientific correction.

Answer-only finalization cannot restart tool work. Its response must distinguish
completed observations from unresolved checks. Tool activity remains visible
separately. Explicit evidence, evaluation against real research scenarios and
researcher review remain necessary to assess scientific correctness.

Whole-turn time, tool-call count, cumulative model tokens and total model cycles
have no default ceiling. Their optional environment settings accept a positive
limit; unset or zero disables that ceiling. Usage remains observable telemetry.
Individual model/read requests retain a 180-second timeout, cancellation and
the repeated-observation guard.
Provider failures use structured HTTP status, known stream error codes and
chained transport exceptions. HTTP 408/429/5xx and known transient stream or
connection failures receive up to five retries with exponential jittered
backoff; authentication, malformed requests, exhausted quota and unclassified
errors stop visibly. Successful tool observations remain in the trajectory
during retries. Trace records contain normalized reasons, status, attempt and
delay, never exception messages, response bodies or tracebacks.
Model requests recheck the remaining output allowance after context preparation;
an exhausted optional cumulative allowance cannot produce a zero or negative
provider output limit.
`LENS_AGENT_CONTEXT_TOKENS` defaults to 65,536 for the entire model request,
including system instructions, tool schemas, observations, output reserve and
protocol margin. Token counts use the existing cl100k tokenizer with 20% reserve;
operators must choose a window supported by their configured model. Both normal
decisions and context compaction are checked at the provider boundary.

Section inspection packs complete Sources into the available result allowance
and exposes canonical lengths and estimated tokens in the outline. It defaults
to at most 200 records, rather than eight truncated previews; token capacity
usually determines the batch size. Oversized Sources remain explicitly unread
and provide their exact reference for individual paginated reading. Independent
reads share the allowance while retaining their individual provenance.

When older operations leave context, the runner creates provisional working
notes containing scope, comparison conditions, conclusions, basis message IDs,
uncertainties and next actions. It validates references before retiring those
operations from model input. The full trajectory remains in storage. Working
notes are not primary evidence, approval or published results. Source claims require
their actual passages. A failed compaction preserves history and fails visibly.
Recent user requests receive a reserved share of the context before tool
outputs. Adding one paper or deferring a review preserves other paper choices;
compaction retains those choices separately from Agent recommendations.
The active request is also identified after historical records and runtime hints,
including during compaction. Its token cost is reserved in context selection.
A later request for detailed results supersedes an earlier identification-only
request while preserving the selected paper.
Across user requests, a bounded reading summary is rebuilt from successful
historical Source results, including versioned references, verbatim excerpts
and explicit omissions. A new empty search cannot erase an earlier abstract
read. Historical reading is context, not scientific validation or current-turn
write authority: exact Evidence publication prerequisites remain independent.
Comparisons distinguish supported agreement, supported difference and unresolved
attributes. An unspecified ELI grade is unresolved, not a demonstrated grade
difference; each paper's treatment variables and result remain attributed to it.
The compaction instructions preserve the same uncertainty and attribution, so
working notes must not strengthen a claim while the original operations retire.
The comparison answer exposes an attribute-by-paper table so inspected values,
confirmed differences and unconfirmed conditions remain distinguishable to the
researcher. Shared conclusions and paper-specific counterexamples use separate
attributed statements. This answer structure does not certify model correctness.

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

A researcher may leave while the Agent explains the conditions needed to compare
LPBF tensile results, then return from history to read what has already been
generated and continue waiting for the answer. `ChatSessionService` captures
the exact partial response and current progress independently of its browser
connection. The runner allocates each assistant message ID before emitting text;
the final checkpoint keeps that identity. A bounded PostgreSQL snapshot permits
another worker to serve reconnecting readers. Ordinary turns and approved
continuations share this lifecycle, and reconnecting never repeats either action.
If execution stops unexpectedly, partial text remains explicitly incomplete.
Snapshots support observation of the research work; they do not replace source
checks, certify a scientific stage, or automatically restart interrupted work.

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
  together. Selection uses the token capacity remaining after request overhead
  and answer/reading reserves. Explicit character/message caps remain available
  to local callers; the production default uses token capacity. The same model
  message representation is counted and transmitted. Omitted operations have
  validated provisional working notes while stored history remains complete.
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
