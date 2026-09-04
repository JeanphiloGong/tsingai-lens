# Objective Analysis

This package owns the research work performed after a user confirms one
`ResearchObjective`.

Read the analysis responsibilities in real research order:

1. `source_screening.py` decides which Source units require inspection for the
   confirmed question. Its `PaperAnalysisFrame` is transient screening state,
   not proof that a paper contains usable Evidence.
2. `evidence_routing.py` turns screened Source units into the transient
   inspection queue consumed by Source-local fact extraction. A route is an
   instruction to inspect a Source, not a scientific finding.
3. `source_extraction.py` exposes `extract_and_validate_source_facts`, which
   inspects routed Sources one at a time and produces transient, source-local
   `ExtractedEvidenceDraft` records. It owns text and complete Markdown table
   payload construction, bounded continuous-row structural table repair,
   deterministic table parsing, model extraction, and route-scoped technical
   failures. A PDF table Source carries both the Docling logical grid and an
   optional clipped page-layout view. The grid preserves cell identity and
   numeric tokens; the layout view preserves the continuous row wrapping a
   researcher sees in the PDF. Repair may use the latter to resolve a split
   label or uncertainty, but it must conserve the supplied tokens and numeric
   column sequence. Oversized repair inputs repeat the caption and flattened
   header on every slice, then merge in Source row order. A final row
   containing only carried label and uncertainty fragments may merge into the
   preceding logical row. Mean-plus-uncertainty result columns are rebound from
   their complete top-to-bottom Source number sequence; missing, duplicated,
   reordered, or changed result numbers invalidate the repair. If neither
   view can support a safe repair, the Source remains unresolved or technically
   failed and cannot be presented as a scientific absence.
4. `source_validation.py` immediately checks each model-authored draft against
   the exact Source being inspected. Extraction and validation therefore
   alternate per Source; they are not two collection-wide passes. When that
   same Source uniquely names the Objective material, validation may restore
   the omitted material identity with that Source as its lineage. Unsupported
   results abstain, while supported results with incomplete variable or
   comparison support become `association_only` or descriptive drafts before
   they can enter the next Source prompt's document state. Association drafts
   may name the confirmed Objective variable while leaving baseline and target
   endpoints empty; they support an observed relationship, not an isolated
   causal effect.
5. `paper_experiment.py` runs after all routed Sources have been inspected. It
   fills only missing scope from validated facts in those same-paper Sources,
   binds Methods and Results through exact sample identities, and derives
   bounded pairwise comparisons. When all inspected context Sources establish
   one compatible paper material, a result missing material identity inherits
   that value and its supporting Source reference. Conflicting materials remain
   unresolved. It never reads preliminary map scope as experiment context.
6. `evidence_materialization.py` turns reconstructed drafts into durable
   `ObjectiveEvidence`, deduplicates replayed scientific claims by stable
   Evidence identity, and derives each paper's `PaperContribution` from that
   final Evidence set.
7. `finding_synthesis.py` groups durable Evidence into backend-owned result
   sets, asks the bounded assertion judge only for claim strength and supported
   context, and publishes traceable cross-paper `Finding` records.

`source_screening.py` owns complete Source-unit accounting, bounded framing
batches, the screening prompt and response schema, prompt preflight, bounded
repair, model/repaired/fallback dispositions, and frame aggregation. Its
`ObjectiveSourceScreener` performs only the current bounded relevance judgment.
Independent batches across the selected papers run with the bounded
`OBJECTIVE_PAPER_FRAMING_MAX_CONCURRENCY` setting (default `10`), while their
results are aggregated in Source order so execution timing cannot change the
scientific frame.
Its optional `screening_note` explains only the current selection decision and
is normalized after parsing so an overlong note cannot discard valid Source
accounting. Later stages may consume a frame, but they may not reinterpret a
screening decision or note as scientific Evidence or a paper-level conclusion.
When the paper-level discovery record classifies a document as a review, frame
aggregation preserves that role; a local Source judgment cannot promote one
cited experiment into a primary experiment paper.

`evidence_routing.py` owns transient route records, Source-tree candidate
ordering, selection hints, the bounded routing prompt and response schema, the
one-Source model call, deterministic fallback, and the document round-robin
extraction queue. The model decides only whether and how to inspect the current
Source; the backend preserves its identity, so a route cannot redirect work to
another paper or Source or become durable Evidence. A review frame remains a
secondary synthesis or citation-lead source and does not enter the primary
Evidence extraction queue. Review synthesis produced during discovery remains
available upstream; a cited experiment must be inspected in its primary paper
before it can support an Objective Finding.

For a `primary_experiment` paper, framing relevance is a ranking signal rather
than an exclusion boundary. All tables and all text candidates with an explicit
Objective result remain in the inspection queue even when the frame is only
medium relevance or lists different sections. If an experimental frame is marked
irrelevant but the concrete Source tree contains a direct Objective signal,
routing records a recall override and inspects that Source. Only papers with no
source-local Objective signal remain skipped. This keeps model false negatives
from removing facts that a researcher would have found by reading the paper.
Before any Source-routing model call, the selected Sources must collectively
establish at least one confirmed Objective variable and one confirmed Objective
outcome. They may occur in different Sources, as they commonly do across Methods
and Results. A paper that reports the broad outcome but studies a different
variable is recorded in the internal trace and does not enter deep extraction.
An exact Paper Map relationship lineage preserves an abbreviated Source for
inspection, but the lineage is still only a recall reason: Source-local
extraction and grounding must establish every fact before it can become
Evidence.
For text Sources, an explicit result statement or a result-bearing Results or
Conclusion passage is required before an outcome mention can become a direct
result route. A Methods sentence that merely names the measured outcome remains
background context and is inspected source-locally.

`source_extraction.py` owns the inspection of one exact Source at a time. It
owns that judgment's prompt, response schema, scientific validation, bounded
repair instructions, completion budget, and direct model call. It passes every
schema-valid model draft directly to `source_validation.py` before updating the
accepted state supplied to the next Source prompt. Provider or irrecoverable
structured-output failures remain technical failed drafts. Shared provider
invocation, JSON parsing, usage accounting, and trace capture stay outside this
scientific responsibility. When a grounded result is partial or lacks material,
condition, or comparison context, it performs an adaptive same-paper context
expansion over Methods, specimen, processing, characterization, and test
Sources. It ranks explicit condition values, group identities, and Objective
terms, selecting the smallest candidate set that covers the missing field
families. The expansion adds those Sources to the same transient Evidence
Bundle; field-bearing adaptive routes are placed ahead of incidental routes
when the bundle has a bounded source budget, while document order remains the
stable tie-breaker. It never imports context from another paper or invents the
missing value. If no remaining Source can close the gap, or a technical
execution budget ends inspection, the omission remains an explicit scope gap
and the original result remains descriptive, associative, or `needs_context`.
Rows that report the same outcome from the same result Source share one context
decision: the service selects one Evidence Bundle for that result series rather
than rereading Methods independently for every table row. A different result
Source or outcome starts a separate decision, so unrelated experiments cannot
inherit the series context.

Only a result anchor receives a same-paper bundle. A Methods, sample, process,
characterization, or test Source is inspected source-locally and therefore
receives an empty bundle; its facts can enter the accepted document state only
after validation against that exact Source. The result anchor's bundle contains
those condition-bearing Sources plus complete result tables, but not another
independent result-text Source or an unscoped background Source. Those result
Sources remain separate experiment anchors. The extraction bundle is a recall
aid, not blanket lineage: a bundle Source is attached to the resulting Evidence
only when it explicitly contains a returned condition endpoint, comparison
label, sample value, material value, or test value. This keeps the final
provenance narrower than the candidate reading scope and prevents every Source
in one paper from appearing to support every result.

An extractable context Source that was routed and inspected but yields no
structured context is retained only as an internal inspection trace. It is not
materialized as scientific Evidence, because an empty model response is not a
fact. Its locator and route reason remain available to the coverage ledger, so
the Source is counted as inspected rather than silently treated as unread. A
provider or irrecoverable parsing exception remains `extraction_failed` instead;
technical failure and scientific absence are never merged.

The same retention rule applies to a Source explicitly routed as
`current_experimental_evidence`: a valid empty extraction becomes an unresolved
`direct_result` candidate and can trigger same-paper context expansion. This
avoids losing a result because a synonym, abbreviation, or OCR form escaped a
second keyword detector. When a first read found the measured result but left
its comparison or study context partial, the service may reread that exact
result Source once after grounded Methods or condition Sources are available.
The reread is bounded by route identity and never replaces the result Source as
the authority for measured values. If explicit sample/group labels already let
deterministic reconstruction bind the result, no reread is made. When lexical
matching cannot identify a context Source, the expansion may read a small
structural-neighbour window around the result Source. Those routes are marked
as structural candidates with no claimed field coverage; only source extraction
and validation can close the missing context.

Adaptive same-paper closure is limited to two progress rounds per extraction
run. This is a research-scope budget, not a scientific conclusion: if the
inspected Sources still cannot establish the missing fields, the result keeps
its source-backed observation and records an explicit scope gap for review.

Context Sources may contain several independent condition facts for one paper
(for example one row for S1 and one for S2). Their transient evidence IDs
include the source-grounded context payload so one fact cannot be discarded as
a duplicate of another fact from the same Source. Result IDs remain stable as
same-paper context is attached during reconstruction.

`diagnostics.py` captures private technical traces for one analysis execution.
Each attempted structural table repair records the Source identity, row counts,
model and deterministic repair counts, number-sequence verification, and a
final `verified`, `rejected`, or `provider_failed` disposition. These traces are
persisted with the internal analysis record for debugging but are deliberately
absent from Objective API responses, Evidence, and user-visible warnings.

`source_validation.py` owns deterministic Source acceptance, demotion, or
abstention. It checks the reported result, comparison labels, changed
variables, and scientific context independently and records which field
families each Source supports. For a grounded text result whose comparison is
still absent, it keeps the exact Source excerpt as transient reconstruction
input. During a bounded same-document context revisit, it may validate
condition and context fields against the explicit Evidence Bundle assembled
from that paper's Methods, Results, tables, and figures; measured result values
and result wording remain grounded in the primary result Source. It never
imports context from another document, identifies experiment groups, or calls
the model.

Comparison labels are not automatically variable levels. A label may identify a
specimen, group, run, or categorical condition, and its meaning belongs to the
paper rather than to a backend vocabulary. When a result Source has comparison
labels but the extraction does not include complete factor endpoints, validation
retains the source-backed result with those labels marked non-comparable and
`descriptive_only`; a later same-paper condition registry may upgrade it only
after the paper explicitly binds each label to source-grounded process values or
categorical conditions. Numeric or semantic levels such as `150 W`/`200 W` and
`without preheating`/`preheating at 400 C` are eligible only when the extraction
itself records those explicit endpoints and Source validation confirms them.
Resolving those endpoints makes the observation comparable; attribution still
follows the Source's supported factor structure and control statements.
When Methods assigns ordered group labels with an explicit `respectively`
statement, deterministic reconstruction may materialize that exact mapping as
same-paper condition context. Missing ordering, unequal list lengths, duplicate
labels, or conflicting definitions remain unresolved rather than being inferred.

Outcome labels are canonicalized only after Source grounding. If a table or
caption explicitly defines an abbreviation (for example, `DIDX means
densification index`), that local definition may map the model's Source label
to the confirmed Objective axis. An unexplained abbreviation is retained as an
unresolved label and cannot pass Objective-axis matching by resemblance alone.

`paper_experiment.py` owns same-document reconstruction after Source inspection
finishes. Deterministic parsing may reconstruct an experiment condition from a
multi-level Methods table only when the table's parent headers, leaf headers,
caption-defined symbols, units, and row values jointly define it. The paper
reconstruction then builds a registry keyed by exact condition label, merges
complementary same-label context, and rejects conflicting definitions. A result
may join registered conditions only when its own Source mentions those exact
labels. The result retains its own context and fills only missing material,
sample, process, or test fields that are identical across both bound conditions;
an explicit result-local value is never overwritten. An unchanged series becomes
an isolated effect only when its first and last registered conditions have
complete process context and differ by exactly one factor; incomplete,
multi-factor, missing, or conflicting conditions remain associative or
descriptive. No label spelling convention and no cross-document binding supplies
scientific meaning. For same-table row comparisons, numeric results retain
ordered increase/decrease semantics, while categorical results retain both raw
endpoints and report only `changed` or `no_change`. A numeric/category mismatch
or any incompatible material, sample, or test context remains explicitly
non-comparable.

A text Source that itself supports a factor and explicit endpoints retains that
comparison even when no separate Methods condition registry defines the groups.
Without the controlled-condition binding it is associative, not an isolated or
joint effect. An unrelated or incomplete condition registry cannot erase the
Source-local observation.

Deterministic pairwise comparisons from result tables are generated only for the
confirmed Objective's outcome when material, sample, process, and test context is
otherwise compatible. A row pair with one changed process factor may support an
isolated effect; a row pair with multiple changed factors is retained as an
`association_only` contrast with its complete changed-factor tuple. It is never
promoted to a joint or causal effect merely because two rows are adjacent. Missing
context or a changed material/test/sample condition remains non-comparable. The
same rule applies to explicit Source-grounded comparisons: coupled variables stay
visible, while the attribution scope records whether the Source supports an
isolated effect or only an association.

When a result table uses a generic row axis, reconstruction may replace it with
an Objective variable only if one same-paper process fact uniquely names that
variable and explicitly describes the two row endpoints as opposite sides of a
contrast. Merely mentioning the variable, one endpoint, or two similar words is
insufficient. Without that source-grounded bridge, both measurements remain
descriptive Evidence and no comparison is generated.

The fallback row comparator is deliberately narrower than a researcher's
manual reading: without a confirmed Objective it may generate only a single
process-axis contrast, and multi-axis row contrasts require a concrete row
locator for each measurement. Missing process columns are not treated as a
changed factor. This keeps table values visible while preventing row order from
becoming an unsupported causal or joint-effect claim.

`PaperResearchMap` is not an input to this reconstruction. Analysis may use the
map earlier to prioritize Source inspection and later to report preliminary
coverage gaps, but a map material, process, variable, or outcome label cannot
fill, overwrite, or validate an `ExtractedEvidenceDraft`.

`evidence_materialization.py` owns the trust boundary from transient paper
facts to durable Evidence. It keeps the confirmed Objective's result details,
canonicalizes uniquely matching axes, resolves exact Source excerpts and
related locators, and deduplicates only replayed drafts with the same stable
`evidence_id`. Distinct claims from one Source remain separate because a table,
figure, or paragraph can support several measurements or comparisons.
`PaperContribution` route, extracted, failed, and comparable counts are computed
from that complete claim set, and its contribution summary is assembled only
from grounded result text in the final Evidence records. Contribution warnings
count only final framing fallback, deterministic evidence-routing fallback,
`PaperResearchMap` coverage gaps, and failed Evidence Sources; successful repair
is not a warning. It does not persist artifacts or synthesize a cross-paper
claim. Its private materialization trace records only bounded counts and paper
dispositions, so an empty result can be distinguished from filtering and
technical extraction failure without storing Source content in diagnostics.
For factor/outcome candidates excluded only by material scope, material-scope
decisions record the Source locator, Objective material scope, grounded Evidence
material values, and mismatched or unresolved status without storing Source
text. Detail records are capped at 100 per analysis and any remainder is kept as
status counts.

Each durable Evidence also carries a deterministic research status: `comparable`
has complete source-grounded variables, comparison, material scope, result, and
an attributable factor relationship. `association_only` preserves an observed
relationship that is weaker than an isolated causal effect. When its endpoint
labels, outcome, material, and fixed scientific context are complete, and the
same condition stratum is supported by at least two papers, it may enter an
associative cross-paper Finding. It remains `association_only` and is never
promoted to `causal` or `isolated_effect`. If endpoints or context are missing,
the result remains paper-scoped until a researcher supplies the missing
evidence. `descriptive` preserves a reported result without enough comparison
context; `needs_context` marks a target-result Source that still needs same-paper
Methods, sample, or condition context; `non_comparable` preserves complete facts
whose material, process, or test context cannot be aligned; and
`extraction_failed` records a technical failure. The Evidence Map exposes all of
these records, including ones not used by a Finding, with their exact Source and
reason. A missing Finding therefore means a scientific abstention only when the
status distribution and paper dispositions show why, not an unreported failure.

An analysis that inspects its paper scope but finds no grounded Objective
Evidence publishes an empty Finding set as a scientific abstention. This is not
a provider failure. If every relevant paper instead ends in technical extraction
failure, the analysis run fails and remains retryable. A partial technical
failure may still publish surviving paper outcomes with explicit contribution
warnings.

The first six stages run and persist independently per Document. A checkpoint is
reused only when Objective intent, Document preparation fingerprint, extraction
version, and model identity still match. Scientific absence and
non-comparability are successful inspections; provider, parsing, or unexpected
execution errors are failed checkpoints. On retry, successful papers are reused
and failed papers are inspected again. Only after the selected checkpoint set is
assembled does `finding_synthesis.py` run once, followed by the existing atomic
analysis publication.

`finding_synthesis.py` owns cross-paper comparison after durable Evidence and
paper outcomes exist. `FindingSynthesisService` deterministically selects
comparable Evidence, constructs atomic factor/outcome result sets, balances the
bounded model input across papers, assigns all supporting and opposing Evidence,
and derives the published statement, status, certainty, limitations, identity,
and provenance. When an Objective declares a material scope, direct-result
Evidence is comparable only after its source-local or same-study material
identity resolves to that scope. Missing, broad-only, mixed, or conflicting
material identity remains Evidence but cannot enter a result set or Finding.
An observation with a direction but no source-bound condition pair remains
available as a separate paper-scoped result; it never supplements a strict
comparison result set, and it cannot create a cross-paper result set by
itself. This keeps an incomplete observation visible without allowing it to
weaken or contaminate a complete comparison. A complete `association_only`
contrast follows a separate, equally conservative path: it can form an
associative cross-paper result set only when the same factor, outcome, endpoint
pair, and fixed context recur in at least two papers. Different treatment
endpoints (for example, as-fabricated -> HIP versus as-built -> stress-relieved)
remain separate paper-scoped results even when their directions agree.
Within one paper Source, compatible row-pair comparisons belong to one
experimental condition series rather than one Finding per endpoint pair. The
series factors are the exact union of the source-grounded changed factors, and
opposing directions remain visible inside that Finding with every comparison
Evidence id retained. Objective-axis values are condition coordinates within
the series, so they neither split the result set nor appear again as fixed
scientific context. When that Source already yields a comparable relationship,
its scalar, directionless row measurements remain available in the Evidence
Map but do not become duplicate descriptive Findings. A separate aggregate
observation or explicitly reported association remains eligible because it is a
different scientific claim, not merely a table coordinate.
When a source-backed result is relevant to the Objective but cannot safely enter
a cross-paper result set, synthesis keeps it as a paper-scoped descriptive
Finding and carries the deterministic material or condition gap in
`limitations`. A grounded result for a neighboring outcome remains in the
Evidence Bundle with an explicit out-of-scope reason, but is excluded from the
current Objective's Finding result sets; if no in-scope result remains, the
Objective ends in a visible scientific abstention rather than silently losing
the paper's reported fact.
Coverage distinguishes navigation candidates from selected scientific work.
Framing-positive Sources remain an auditable recall prior, but they do not all
become mandatory deep-reading work. An extractable route is selected work and
must have a materialized extracted-or-failed Evidence record. Therefore
`uninspected_source_count` counts selected Sources without an extracted,
failed, or inspection-only record, not every unread framing-positive candidate.
A paper with
`evidence_disposition=coverage_incomplete` or a positive
`uninspected_source_count` retains its already extracted result Evidence for
review, but cannot contribute to a cross-paper Finding until those selected
Sources are inspected. Complete papers may still be compared with one another,
and the analysis diagnostic records the excluded papers, uninspected Source
count, and paper-scoped result count.
`FindingAssertionJudge` decides only assertion strength and
optional context or mechanism annotations for one backend-owned result set. It
cannot change result-set membership, scientific direction, Evidence bindings,
or any published Finding identity. Because a result set already contains
source-backed direct results, an empty judge response is treated as an
annotation abstention: the backend publishes that result set as a conservative
descriptive Finding and records a private recovery diagnostic. If the optional
judge fails at the provider or structured-response boundary, the same
conservative recovery applies. Only the absence of a backend-owned result set
produces an empty Finding set, and that scientific abstention remains visible
through Evidence statuses, paper dispositions, and coverage counts. Repeated
semantic rejection of a non-empty candidate still aborts the analysis version.
When an analysis completes without a Finding, `ObjectiveAnalysis` persists the
derived scientific reason (`no_grounded_evidence`, `no_comparable_evidence`, or
`insufficient_evidence`) and a deterministic note. This is a successful,
auditable research outcome, not a provider or JSON failure; the note tells the
researcher whether to inspect missing source grounding, incompatible study
conditions, or an incomplete comparison.

Technical JSON parsing, provider retries, usage accounting, and trace capture
live in `llm/structured_response.py`; they support this process but do not
define its scientific order.

## Researcher-parity acceptance

The acceptance question is not whether the model produced fluent prose or
valid JSON. Given the same papers and the same confirmed Objective, a researcher
must be able to reach a conclusion in the same scientific direction and scope
from the published Lens result. The run is acceptable only when all of these
conditions hold:

1. **Recall:** every paper-local Source that explicitly reports an Objective
   variable, condition, or outcome is inspected, even when framing relevance is
   wrong or only medium. A Source with no such signal is recorded as out of
   scope; it is not silently lost.
2. **Fact completeness:** each reported result keeps its exact Source excerpt,
   locator, values, units, condition labels, and any jointly varied factors.
   Missing material, sample, method, or control context is represented as
   `needs_context`, `descriptive`, or `association_only`, never filled from
   general knowledge.
3. **Within-paper binding:** Methods, Results, tables, figures, and captions
   may complete one another only inside the same document and only through
   explicit sample or condition identities. A paper-level map is navigation,
   not experimental proof.
4. **Comparison discipline:** Findings compare only context-compatible
   Evidence. Different material states, processes, test conditions, or outcomes
   remain separate or `non_comparable`; coupled factors remain visible as an
   `association_only` stratum and never become a convenient pooled causal
   average.
5. **Calibrated conclusion:** a Finding cannot be stronger than its Evidence.
   Controlled one-factor comparisons may support an isolated effect; otherwise
   the result remains associative or descriptive. An empty Finding means
   grounded scientific abstention only when the Evidence and paper dispositions
   explain the gap.
6. **Failure visibility:** provider, parsing, and technical failures remain
   `extraction_failed` with trace and contribution warning. They cannot be
   presented as scientific absence or as a positive/negative result.

Verification uses an expert-reviewed paper bundle, not a synthetic model-only
fixture. The bundle must check Source recall, measurement and comparison recall,
source-locator correctness, context compatibility, and conclusion direction;
the four-paper integration fixture is the minimum regression gate for review
paper separation and sample-state stratification.
