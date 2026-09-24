# Conversation Case Analysis Contract Audit

Status: deferred pending a domain contract. This audit records why the
`conversation_case_analysis` task type is not implemented in the current
checkpoint (`fc0c73a7`). It is a decision boundary, not an implementation
specification.

## What the production code already means

The feedback workbench currently has two different signals:

1. `ChatMessageFeedback` records an explicit thumbs rating and optional reason
   or comment. `feedback_analysis` reads that signal and produces a candidate
   analysis.
2. A user message immediately following a final assistant answer can be an
   explicit natural-language challenge. `correction_signal_analysis` verifies
   the session, message order, final-answer shape, content digest, and
   challenge marker before producing an unresolved candidate.

The second path deliberately does not classify every follow-up as a problem.
Its result cannot modify Chat, declare the answer wrong, supply a training
target, or bypass annotation and review. The implementation is owned by:

- `backend/application/feedback/correction_signal_handler.py`
- `backend/application/feedback/correction_signal_worker.py`
- `backend/domain/feedback/correction_signal.py`
- `backend/infra/persistence/postgres/analysis_job_repository.py`
- `backend/migrations/versions/20260925_0076_feedback_signal_analysis.py`

The shared `analysis_jobs` table is an execution envelope. A job's
`job_type`, `payload_version`, and type-specific JSON payload are validated by
the owning handler. Adding a new type does not by itself define its domain
meaning.

## Real conversation sequences

| Sequence | What a researcher observes | Current meaning |
| --- | --- | --- |
| `Q -> A -> follow-up` | The researcher asks for another comparison, scope, or explanation. | Ordinary Chat. No analysis job is created. |
| `Q -> A -> explicit challenge` | The researcher says “不对”, “你漏了图注”, or an equivalent challenge immediately after `A`. | A correction-signal candidate may be queued. It remains unresolved evidence. |
| `Q -> A -> follow-up -> A2` | The conversation continues before anyone challenges `A`. | It is unclear whether `A` or `A2` is the case anchor and whether the earlier exchange should be grouped. |
| `Q -> A -> challenge -> correction` | A challenge is followed by a later corrected answer. | The correction-signal path can identify the challenge, but the canonical corrected target and merge policy are a separate human-reviewed contract. |
| branch/retry/edit | The message tree contains alternate answers or revisions. | A linear session window is insufficient to choose one causal conversation. |

These sequences show that “conversation case” is not a synonym for “all
messages after an answer.” It must represent a real observation or decision
that a human can inspect and act on.

## Missing decisions

No current source defines the following behavior. Implementing a worker before
these decisions would invent a domain model and make its checkpoint impossible
to verify.

### Trigger and boundary

- Is a job created for every completed answer, for every later user message,
  after an idle/end-of-conversation boundary, or only for a non-explicit
  follow-up that remains unresolved?
- Does an ordinary follow-up create a candidate, remain context for another
  signal, or produce an explicit abstention result?
- Can one conversation create multiple cases, and what closes one case?

### Identity and input window

- What is the canonical anchor: the first answer, the latest answer, a user
  message, or a conversation segment?
- Is the input a contiguous message range, a branch path, or a selected set of
  messages? How are edits, retries, and forks represented?
- What digest makes a queued job stale when a later message changes the
  context?

### Purpose and result

- Is the task grouping context, classifying dissatisfaction, reconstructing a
  correction sequence, or detecting an evidence gap? These are different
  domain decisions.
- Which problem types, confidence semantics, evidence coverage, and
  abstention states are valid?
- Does it write a new result table, attach to the existing correction result,
  or create a `FeedbackCase` directly? What makes results idempotent?

### Case merge and downstream behavior

- When an explicit challenge appears after a conversation candidate, are the
  results merged, linked, or kept as separate source signals?
- What does the workbench show to a human, and what action can that human take?
- Which annotation, review, and dataset rules apply to a multi-turn case?

### Runtime behavior

- Which caller creates the job and at what durable event boundary?
- What does withdrawal, deletion, branch creation, or a failed provider call do
  to an existing candidate?
- What are the retry and cancellation semantics for a stale conversation
  window?

## Decision

Do not add `conversation_case_analysis` code, migration, repository methods,
or a placeholder worker at this checkpoint. The existing correction-signal
implementation already handles the only currently specified post-answer
conversation signal. A speculative implementation would either classify
ordinary Chat as feedback without user evidence or duplicate and compete with
that path.

The tutorial's fixed-checkpoint rule applies here as follows: no version
checkpoint is valid until the contract can be tested against one complete
conversation scenario and one alternate/failure path. The current checkpoint
therefore freezes the audit only; it does not claim the future task is
implemented.

## Entry criteria for a future implementation checkpoint

Before coding, the owning design document must state, with examples:

1. one trigger event and one explicit case boundary;
2. the anchor, message window/branch rule, and stale-input digest;
3. the result schema, problem vocabulary, abstention semantics, and case
   identity;
4. how ordinary follow-ups differ from explicit correction signals;
5. merge, withdrawal, retry, and duplicate behavior; and
6. the user-visible workbench outcome and downstream dataset restrictions.

The implementation checkpoint must then include the domain object, migration,
repository contract, caller integration, worker, unit tests, persistence
tests, and a complete scenario test. Its commit record should name the base
ref, changed files, test results, and any unavailable PostgreSQL/provider
checks. Until those entry criteria are met, the correct result is this audit,
not a new task type.
