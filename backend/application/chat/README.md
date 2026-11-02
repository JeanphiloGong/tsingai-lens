# Chat Application Layer

This package owns the collection-bound Research Agent conversation. It turns
an authenticated user's message into resource-bounded model decisions, ordered
typed capability calls, and a durable, reviewable trajectory.

The prompt frames conversation as professional research collaboration around a
research decision. It keeps the research question, current understanding,
traceable facts, and runtime control distinct. Ordinary replies translate tool
and status identifiers into that research meaning, including when explaining
pending approval.

## Initialization Prompt

`model.py` owns the runtime prompt and its version. Named sections cover identity,
collaboration and continuity, research information, tool decisions, scientific
reading, recovery, write authority, response style, and boundary examples. They
compose one system message; this README does not duplicate the prompt text.
The registered capability descriptions and schemas remain authoritative for
available tools and their specific fields, prerequisites, and write contracts.

The reference scenario is a researcher deciding what to investigate, combining
scientific knowledge, user materials, paper Sources, calculations and
comparisons, then deciding what evidence or experiment is needed next. Filename
and Profile help select candidates; Paper Map is optional navigation. When
canonical Source is readable, missing maps or unrecognized abstract headings do
not block original section reading or automatically require expert review.
Preparation progress, classification failure with readable Source, actual read
failure, unread content, and information absent from inspected content have
different next actions.
Ordinary Source reading also grounds any filename/content conflict note in the
inspected content; it adds no preparation stage or identity-checking tool call.

Scientific background knowledge is available by default for explanations and
hypotheses. Explicit restrictions to supplied materials also constrain their
scientific premises while preserving reasoning and arithmetic from those
materials. A restriction on web search alone does not impose that knowledge
boundary. Context compaction preserves the researcher's explicit restrictions.

When complete Source reads reconstruct an actual paper experiment, the Agent may
propose a PaperExperiment draft for review without a confirmed Objective or
published Objective analysis. The formal paper-fact path is complete Source ->
PaperExperiment draft -> researcher review -> PaperExperiment revision. A later
Objective analysis selects one or more fixed revisions -> comparison or Finding.
Future validation experiments are proposals, not PaperExperiment records, and
runtime checkpoints or tool status are never scientific evidence.

Prompt validation combines protocol/authorization regressions with opt-in live
model scenarios using real Source fixtures. It checks actual reads, recovery,
attribution, continuation, and final answers rather than treating prompt-string
assertions as proof of model behavior. The warning-generation policy is owned
by the browsing capability and tracked separately from this prompt refactor.
The opt-in knowledge-scope checks compare ordinary discussion, no-web requests,
and supplied-material-only requests using the same controlled trend. They check
that arithmetic remains possible and mechanisms use only the allowed premises.

## Start Here

- HTTP entry: `controllers/chat/chat_session_routes.py`
- Turn orchestration: `application.chat.session_service.send_message()`
- Agent loop: `ResearchAgentRunner.run_turn()`
- Tool lookup: `CapabilityRegistry`
- Approval continuation: `application.chat.session_service.decide_tool_call_for_user()`

One turn follows this sequence:

Finding lookup is not limited to the latest bounded query results. The exact
handler validates collection ownership and the requested record identity. A
transient draft remains an observation: the model may read again or revise its
answer; draft success does not synthesize an automatic final response.

```text
user message -> bounded model decision -> capability call
  -> capability result -> trajectory checkpoint -> final answer or approval
```

Read capabilities may inspect canonical collection resources. Write
capabilities stop for exact user approval by default. Collection defaults can
choose read-only, confirmation, or an automatic grant for new sessions; a
session permission can then override that authority. An automatic grant may
be persistent (`expires_at: null`, until revoked or changed) or temporary (up
to 24 hours). Both scopes can authorize any currently registered write action
selected by the user, and the backend expands an all-actions request. application.chat.session_service
claims every automatic write in the repository before resuming the same Runner;
it never sends write calls through the parallel read executor. Revocation and
claim share the session row lock. Chat never owns a second Objective,
Evidence, Finding, or Analysis record; it calls the Source and Core services.

## Boundary Checklist

| Concern | Owner | Scientific authority |
|---|---|---|
| Conversation and checkpointing | `session_service.py` | none |
| Context selection | `context_builder.py` | none |
| Model/tool loop | `agent_runner.py` | none; execution only |
| Tool discovery and execution prerequisites | `capabilities/tool_discovery.py` and `capability_policy.py` | approval only |
| Tool discovery and requested actions | `tool_discovery.py`, `model.py` | model selects registered capabilities; no execution authority |
| Objective, Evidence, Finding data | `application/core/` | Core services |

When adding a capability, define its typed input/output and approval risk first;
do not add scientific state to the Chat trajectory.

Agent-authored experiment records use `propose_paper_experiment_draft` followed
by the separately approved `create_paper_experiment_revision`. The capability
does not own experiment persistence: it reloads canonical Sources and delegates
identity, revision, and atomic paper-revision writes to `application/core/`.
Saving a revision does not create an Objective Selection or publish an analysis.

## Main Flow

When an answer completes normally, `session_service.py` names an untitled
conversation from the first question and the answer using the request's model
connection. This optional background call has no tools and a 45-second timeout;
the answer and next question do not wait for it. The service owns and cancels
pending naming tasks on shutdown. It supplies
navigation metadata only; the title is not appended to the research trajectory.
The repository fills only a null title, preserving concurrent manual edits.
Once a title exists it is kept across later turns. Naming failure leaves the
answer intact and the first-question label available for navigation.

```text
authenticated user + collection
  -> application.chat.session_service validates and persists the user message
  -> ChatContextBuilder selects a bounded trajectory for the model
  -> ResearchAgentRunner exposes a catalog of registered read, draft and write tools
  -> ChatModel selects names through discover_research_tools when needed
  -> Runner exposes the selected registered parameter schemas for this request
  -> ChatModel returns an answer, independent reads, or one draft/write call
  -> Runner checkpoints the complete ordered request before execution
  -> capabilities return paired observations or exact approval_required
  -> application.chat.session_service checkpoints the trajectory and final response
```

Exact Finding reads return review_scope:
feedback lists belong to that version only and do not include ancestors.
A new Finding's empty feedback list cannot erase an older version's reviews.

Source context attached from the document reader is resolved against the
canonical Source before the model runs. A quote is inspection material, not
Evidence or permission to mutate a scientific record.

An authenticated user can stop the exact active response through
`stop_response_for_user()`. Its request is saved on the existing response
snapshot, so a different Web process can receive the stop. Snapshot writes
preserve that request for the same response identity. The owning turn polls
for it while waiting and at trajectory checkpoints, cancels model/read waits,
closes unfinished call/result pairs, and saves a `cancelled` response with
`user_cancelled`. Completed observations and partial streamed text remain saved;
partial text is not promoted into a completed model answer. An already claimed
write finishes and checkpoints before the stop is delivered. The next user
message supplies the revised direction without replaying completed writes.
This uses the existing Web execution and database; it introduces no task queue
or Worker. User cancellation is excluded from tool-failure analysis candidates.

Collection paper screening prefers an explicitly labelled abstract section.
When a parser retains `Abstract:` or an equivalent dash/Chinese label at the
start of a paragraph instead of in its heading, browsing reads that paragraph
as the bounded abstract excerpt. Reference-section entries and incidental
mentions are excluded from this paragraph-label path. Excerpts remain screening
signals tied to the existing Document reference, not an exact Source read or
scientific Evidence; genuinely missing abstracts remain explicit limitations.

Repeated identical calls within one model response execute once. Retained calls
are assigned contiguous positions so checkpointed requests and results stay paired.

Independent read calls whose capability is marked `parallel_safe` run behind the
configured read semaphore. Their completion timing cannot reorder the model's
request positions or the persisted tool-result messages; a read capability that
is not marked safe stays sequential. Draft and write calls are never mixed into
that read batch.

Read and draft capabilities can execute during the turn. Write capabilities
persist their exact arguments and digest, stop for the authenticated user's
approval or a current scoped grant, and execute only that authorized call once.
Automatic authority records its permission revision and scope_grant basis.
Rejection, provider
failure, malformed model output, and resource limits remain technical trajectory
outcomes; they are not scientific conclusions.

Research tool discovery uses the model's interpretation of the
request, including filenames, paper identifiers, and conversational references.
It does not require words such as "paper" or "source" to unlock inspection.
Greetings, general knowledge, and application explanations can finish without
discovery. Tool visibility is controlled by the caller's explicit per-turn
`permission_mode`: `confirm` keeps the normal discovery and exact write
approval path, `read_only` removes durable writes while retaining reads and
transient drafts, and `none` exposes no capabilities. A phrase such as “do not
search” is conversational guidance for the model, not an authorization switch.

`discover_research_tools` loads missing schemas from the current registry. Core
search, browsing, reading and execution-plan schemas are exposed immediately.
The discovery catalog lists only definitions not already exposed under the
current permission mode. Loaded definitions remain available for this user
request and leave that catalog; when it is empty, discovery is not exposed.
The next user request starts a fresh discovery scope for non-core tools.

Its request contains only `tool_names`. Discovery performs no task
classification, scientific read, scope declaration or authorization. Researcher
choices and excluded deliverables stay in the original conversation. Backend
permission mode, exact write approvals and canonical Source prerequisites remain
the deterministic boundaries. Previously recorded discovery metadata remains
history and does not change the current tool contract.

Persistence intent is scoped to the requested action: saving error feedback
while declining curation or publication exposes only the feedback write.
Read-only requests and a prohibition on all saving still disable every write.
Feedback and curation keep separate exact-argument approvals. Their explicit
save requests require the actual approval-producing tool call; a prose request
for confirmation is not a completed deliverable. Discovery remains available
when the target needs identification. After an approved feedback or curation
write, the runner resumes the same research loop so remaining requested work
can finish. If response generation then fails, the saved result remains
authoritative while the turn stays `failed` with the technical error.
Before a curation write, the capability validates the complete canonical Finding
arguments. Missing fields and the retired singular `limitation` alias are rejected
before approval; the runner does not fill them from earlier inspections. Identity,
Evidence bindings, paper coverage, and lineage remain subject to the canonical
validator and the user's approval.

Existing-conclusion review reads the Finding and Evidence before deciding which
original Sources need checking. Only the PaperExperiment draft validator has a
deterministic complete-Source prerequisite; an ordinary answer reports the
available support and gaps without being forced through an authoring pipeline.
Exact `heading_path` filters and offsets support progressive section reading.
The current turn's complete Source reads are counted per section; reading one
passage does not mark the whole paper or scientific check complete.
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
Section reads return the selected section's outline and size the complete result
once, including Source locators, warnings and pagination. Oversized passages
remain explicitly unread with an exact-reader instruction. Independent body-read
batches are sized to the available context; deferred calls keep their exact
arguments in a runtime note and are never recorded as executed. This changes the
batch size, not the number of papers a research task may inspect.

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

Ordinary research decisions use `tool_choice=auto`: the model can read,
update a meaningful plan transition, or answer from existing observations.
Provider failures remain technical failures; completed reads and their source
attribution stay in the durable trajectory.

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
completed observations from unresolved checks. When an operator configures a
whole-turn deadline, the research phase reserves 20% of that deadline, capped by
the finalization allowance when one is explicitly configured. Normal
model calls, retries, compaction and reads use the research remainder; finalization
uses the total remainder. This does not extend the deadline or guarantee provider
availability. The answer is buffered and validated before emitting it. Tool activity remains visible
separately. Explicit evidence, evaluation against real research scenarios and
researcher review remain necessary to assess scientific correctness.

Whole-turn time and cumulative model tokens have no default cutoff. A long,
progressing study can continue past 300 seconds and 1,000,000 accumulated tokens;
cumulative usage is not the size of one model context. Operators can opt into
these ceilings with positive `LENS_AGENT_MAX_TURN_SECONDS` and
`LENS_AGENT_MAX_MODEL_TOKENS` settings; unset or zero leaves them disabled.
Tool-call count and total model cycles retain defaults of 96 calls and 64 cycles.
Their environment settings accept positive limits or zero to disable the ceiling.
Approval waiting time is excluded; active usage survives approval.
Individual model/read requests and answer finalization have no default elapsed
deadline. `LENS_AGENT_MAX_REQUEST_SECONDS` and
`LENS_AGENT_MAX_FINALIZATION_SECONDS` accept positive operator limits; unset or
zero leaves them disabled. The selected connection can impose its own explicit
request limit. Chat passes `timeout=None` to the SDK when no limit applies, so
neither the SDK default nor `LLM_REQUEST_TIMEOUT_SECONDS` can silently cut off a
long answer. That shared variable remains available to Core and feedback clients.
Connection/stream failures and the explicit Stop action still terminate a wait;
browser disconnection continues to leave research running. Cancellation and
the repeated-observation guard remain active. Before stopping for repeated observations, the
runner gives one correction decision with tools still available and the actual
recent calls plus reading ledger. Restating a plan does not count as new
evidence; if the correction still makes no progress, the guard stops the turn.
Other resource ceilings still apply during that correction.
Context compaction is runtime memory rather
than evidence: when the provider cannot produce its optional working-notes
JSON, the runner keeps bounded raw records with their message IDs and
continues from the durable trajectory. A failed compaction counter is reset
for each approval or Continue slice so a recoverable context failure cannot
block later work.
The OpenAI request and stream boundaries classify supported SDK failures once
and expose reason, retryability, HTTP status, and retry delay through
`ModelResponseError`. The runner consumes these fields directly. HTTP 408/429/5xx and known transient stream or
connection failures receive up to five retries with exponential jittered
backoff and `Retry-After`. The retry allowance is shared across the turn and its
approval continuations. Missing streamed tool arguments retry without streaming
before executing any tool; partial visible text is not replayed as a new answer.
Authentication, malformed requests, exhausted quota and unclassified
errors stop visibly. Successful tool observations remain in the trajectory
during retries. Trace records contain normalized reasons, status, attempt and
delay. Failure logs use operation, call identity, known reason, and exception
type, without scanning arbitrary exception messages, causes, or tracebacks.
Known capability business rejections return explicit tool error codes at their
owning operation; unexpected internal failures use a fixed technical message.
Permission denials retain their distinct error code. Provider bodies and
credentials do not enter these diagnostics.
Model requests recheck the remaining output allowance after context preparation;
an exhausted optional cumulative allowance cannot produce a zero or negative
provider output limit.
`LENS_AGENT_CONTEXT_TOKENS` defaults to 200,000 for the entire model request,
including system instructions, tool schemas, observations, output reserve and
protocol margin. Token counts use the existing cl100k tokenizer with 20% reserve;
operators must choose a window supported by their configured model. Both normal
decisions and context compaction are checked at the provider boundary.
Explicit provider context-size rejections receive up to two recovery attempts
within the existing retry allowance. Each reduces the smaller of the effective
window and the rejected input plus reserved output by 20%,
rebuilds notes and complete exchanges, and sends again only if the actual input
is smaller. The effective window and recovery count survive approval
continuations alongside usage and elapsed time. A pinned request that cannot
fit, input unchanged after the allowed reductions, exhausted recovery, or
partial visible output stops visibly. Recovery sends model requests only; successful capabilities are not
replayed. Output truncation, authentication failures and rate limits retain
their separate handling.

Section inspection packs complete Sources into the available result allowance
and exposes canonical lengths and estimated tokens in the outline. One complete
tool-envelope size check includes warnings and continuation metadata; selected
section reads repeat only that section's outline. Context-sized independent read
batches retain deferred names and arguments as explicitly unexecuted runtime notes
in the existing assistant trajectory. It defaults
to at most 200 records, rather than eight truncated previews; token capacity
usually determines the batch size. Oversized Sources remain explicitly unread
and provide their exact reference for individual paginated reading. Independent
reads share the allowance while retaining their individual provenance.

Context preparation follows an explicit select -> compact -> rebuild loop.
`context_builder.py` owns pure budget and complete-exchange selection;
`agent_runner.py` owns model calls and publishes the replacement notes with
the retired message IDs after construction succeeds.
When capacity is sufficient, original messages stay in context. When it is not,
selection retains a continuous suffix of complete exchanges alongside pinned
researcher inputs; it does not skip a large recent exchange to fill space with
older small ones. Only the omitted prefix enters model compaction. Earlier
compaction, the number of omitted exchanges and time remaining do not switch
normal preparation to fixed excerpts. Bounded archived records are used only
when optional model summary construction fails. State retains every original
message throughout; the context projection never overwrites that history.

When older operations leave context, the runner creates provisional working
notes containing scope, comparison conditions, conclusions, basis message IDs,
uncertainties and next actions. It validates references before retiring those
operations from model input. The full trajectory remains in storage. Working
notes are not primary evidence, approval or published results. Source claims require
their actual passages. Repeated archival compaction merges previous notes with
recent result excerpts instead of replacing the previous investigation. Notes
have a bounded budget and explicitly mark omitted or truncated details; retiring
a message means it is archived, not that every fact was retained. Failed note
construction leaves previous notes and retired IDs unchanged. Invalid optional
summary output can fall back to excerpts; transport and persistence failures
remain failures.
Working notes and retired message IDs are checkpointed in the existing response
snapshot for approval and interruption recovery, without copying notes to logs.
Pinned execution hints retain draft references and saved revision identities;
full scientific payloads remain in durable tool results. Identical, current,
unexpired experiment drafts reuse their stored reference after Source validation.
Unknown document identities return `document_not_found` with navigation advice;
only known papers without Source content return `document_sources_not_ready`.
All researcher input messages are pinned verbatim before tool outputs. If the
inputs cannot fit, selection fails explicitly rather than summarizing parameter
numbers. Ordinary new requests may inherit validated notes from the previous
terminal snapshot and unfinished plan actions as historical runtime work. They
receive fresh counters and plan scope; earlier approval is never inherited.
Same-request approval continuations retain their existing consumed budgets. Adding one paper or deferring a review preserves other paper choices;
compaction retains those choices separately from Agent recommendations.
Researcher inputs remain in their original order and are pinned during context
selection. Runtime observations precede that history; the current question is
not reissued after every tool result. The latest plan is supplied as factual
state only when its tool exchange is absent from the selected history.
A later request for detailed results supersedes an earlier identification-only
request while preserving the selected paper. An ordinary model answer does not
complete an active execution plan: the model must continue or explicitly report
completed, waiting_for_clarification, or scientific_refusal. One corrective
opportunity precedes a stalled finalization; technical stops retain their reason.
The browsing tool fits up to 100 paper identities into the available model
context instead of requiring a fixed twelve-paper page. It returns an exact
`next_offset` when another page is needed. The runtime reconstructs covered
identity ranges and a compact paper list from successful page records, grouped
by query and catalog identity. This ledger survives compaction and continued
requests; revisiting an earlier page cannot move its next unread position back.
It reports navigation only and does not certify relevance or Source coverage.
When fallback compaction receives new observations, it retires earlier next-action
suggestions and points to the current ledgers; uncertainties stay in attributed
checks. For archived Source batches, fallback notes retain bounded verbatim
passages with their document IDs, Source references, digests, pages, and truncation
flags, instead of losing body text behind an outline JSON prefix. These excerpts
are explicitly incomplete, untrusted paper content, not scientific summaries.
Model-visible Source results retain complete text, digests, labels, pages
and citation links while omitting duplicated locator metadata. Selecting a
parent heading reads its child sections as well, so a Methods heading cannot
stand in for its unread Powder and Process paragraphs. Pending section offsets
remain explicit until their selected subtree has been read. Durable tool
results retain their complete original shape. Read batching sizes this same
model representation.
Reading a selected section merges its outline into the known document outline;
it cannot hide unread sibling sections. A changed Source version replaces the
old outline. On reaching the no-progress threshold, the runner reports recent
actions and gives the model one corrective decision with its current tools.
Only a new observation resets this opportunity; another plan-only or repeated
action closes with `no_progress`. Time, tool, token, and cycle exhaustion still
take precedence over this correction.
Plan reminders are sent after an attempted final answer leaves an active plan,
not after every read. Rewording the same plan receives an explicit instruction
to continue the actual checks. A collection search presents a first hit from
each ranked paper before additional hits from one paper; its paper summaries
cover the returned page. Reworded searches and smaller subsets of the same
Source previews do not count as new observations.

Source reading history is rebuilt from complete tool records in the current
request and earlier requests, even after their messages are compacted. Bounded
verbatim excerpts retain conditions, units, Source references, digests and pages.
Fallback notes preserve paper passages rather than serialized envelope prefixes;
omissions remain explicit and do not establish scientific absence. Attributed
working checks remain provisional, distinct from formal Evidence or approval.

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
generated and continue waiting for the answer. `application.chat.session_service` captures
the exact partial response and current progress independently of its browser
connection. The runner allocates each assistant message ID before emitting text;
the final checkpoint keeps that identity. A bounded PostgreSQL snapshot permits
another worker to serve reconnecting readers. Ordinary turns and approved
continuations share this lifecycle, and reconnecting never repeats either action.
If execution stops unexpectedly, partial text remains explicitly incomplete.
Snapshots support observation of the research work; they do not replace source
checks, certify a scientific stage, or automatically restart interrupted work.

Each complex run may expose a model-authored `execution_plan` in progress
snapshots and the turn response. The Agent updates it through the registered
`update_execution_plan` capability after framing the request and when new
observations change a step status, the research route or final disposition.
Several reads within one step need no plan update. Rephrasing a plan is saved
but does not count as progress. Discovery counts only newly available schemas;
permutations and subsets of already available tools do not reset stall detection.
An accepted transition to a final disposition clears the consecutive-stall
counter so its answer can be delivered; it grants no new read coverage or
another plan-update allowance. Repeating that disposition does not clear it.
On entry or resume, the runtime restores
the latest plan once from successful durable plan updates. Each successful plan
result then updates the current plan and its version directly. Final result
assembly applies approval, resource, and technical status to that current plan
without rescanning the trajectory or inventing a version;
it does not infer research steps from a metadata read or a local draft result.
Simple answers may have no plan. It is operational state only; it never becomes
Evidence, permission, or a Finding.

## Key Areas

Cycle diagnostics and response snapshots include the successful Source-content
character count, nonempty Source-entry batch count, batches containing entries
but no body text, reading-token allowance, and remaining request time alongside
the stop reason. These counters reset per runner invocation and measure transfer
volume: repeated reads count repeatedly and are not independent scientific
evidence. Empty entry lists do not count as batches. Diagnostics contain counts,
not raw Source text; an unlimited time budget is recorded as `null`.

- `session_service.py`: `ChatSessionService` owns session reads, source-context
  validation, turn persistence, streaming, and approval execution. The current
  app owns its runner, model-call observer, and active stream tasks. Its shutdown
  cancels and awaits those tasks before the database engine closes. Repository
  access uses the concrete module instances directly.
- `agent_runner.py`: runs the bounded model, capability, and continuation loop
  and reports `completed`, `approval_required`, or `failed`. Completion records
  why work stopped: a model answer, resource budget, repeated observations, or
  the emergency cycle ceiling. One private request path enforces model
  explicit deadlines and output allowances for both decisions and answer-only
  finalization. With a finite total deadline, research uses at most 80% of it;
  the reserve is capped when a finalization allowance is configured. Decisions, retries,
  compaction and tools stop at that research deadline, leaving time to explain
  partial results within the same total time. Answer-only finalization is
  validated before streaming; tool invocation envelopes are not displayed as
  completed answers. A response or finalization failure remains a failure
  even when an approved durable write in the current continuation already has a
  matching successful result. The runner checkpoints a short deterministic
  confirmation that the saved result remains authoritative, while preserving the
  technical failure status for the incomplete turn.
- `context_builder.py`: selects a bounded, protocol-safe conversation context
  while pinning the active question and keeping whole request/result batches
  together. Selection uses the token capacity remaining after request overhead
  and reserved output. Explicit character/message caps remain available
  to local callers; the production default uses token capacity. The same model
  message representation is counted and transmitted. Omitted operations have
  validated provisional working notes while stored history remains complete;
  the runner may retain bounded raw records when optional note synthesis is
  unavailable.
- `model.py`: defines the asynchronous provider-neutral model contract,
  request timeout/output limits, reported usage (including invalid responses),
  and the Research Agent instructions. Implementations must propagate
  cancellation and close in-flight streams without background thread work.
- `capability_policy.py`: selects tools loaded by discovery and completed
  observations, validates batches and exact Source prerequisites, and maps
  capability risk to automatic execution or exact user approval. The Runner
  consumes these decisions; it does not define a second permission path.
- `capabilities/tool_discovery.py`: derives the short catalog from registered
  read/draft/write handlers and validates selected names against that catalog.
- `capabilities/`: contains the explicit typed capability registry and handlers
  for collection and Source inspection, Objective work, Finding and Evidence
  authoring, analysis review, and research-plan drafts or writes.

Collection context, paper browsing, research-scope preview, and Source inspection
handlers import their owning business modules and concrete repositories directly.
Their classes implement the tool protocol and need no dependency-only constructors.
Objective proposal, creation, confirmation, derivation and inspection follow the
same direct calls. Starting an analysis directly calls the queue function; the independent
analysis worker owns execution. Preparation submission uses the same direct calls.
Finding review, Finding authoring, and paper-experiment authoring also call their
owning modules directly. Draft validation always checks the canonical selections;
experiment writes read their approved draft and digest from the actual Chat store.
Published-Finding reads and research-plan proposals, writes and revisions use the
same direct calls. Plan writes recheck the current source snapshot against the
approved draft before persisting an immutable revision.

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

For ordinary response wording and tool-selection guidance, start with
`model.py`. For tool visibility, Source prerequisites, or approval, use
`tool_discovery.py` and `capability_policy.py`. Change `agent_runner.py` only
when execution order, continuation, checkpointing, or stopping behavior must
change.

To add a capability, implement its typed handler under `capabilities/` and
register it in the existing registry. Read, draft, and write handlers enter the
current discovery catalog automatically. The model selects a registered action
from its description and the conversation; the backend then enforces its risk,
permission mode, typed contract, and scientific prerequisites. Writes still
require the exact approval or scoped grant required by their risk.
The handler calls the owning Source, Core, or Goal service. The Runner does not
need a branch for each new capability. A read or draft returns an observation;
an approved write may persist a scientific resource through its existing owner.

Resource, state-conflict and request rejections from the shared business
exceptions retain their public message, reason and data in the tool observation.
Objective creation and confirmation preserve their existing tool rejection codes
and include the owning operation's reason and correction guidance. Ordinary
`ValueError`, file and unexpected dependency failures remain internal errors.

Provider and capability exception logs contain sanitized metadata only. Provider
and capability messages, response bodies and tracebacks are omitted; low-risk
structural model errors may retain a bounded message and source location for
diagnosis. Model failure, invalid tool arguments, rejected approval, and incomplete work
are recorded in the trajectory. They never become Evidence or a negative
scientific answer. After a turn stops, the next user message or exact approval
decision starts its continuation through `application.chat.session_service`.

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
