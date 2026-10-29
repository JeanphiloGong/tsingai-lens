<script lang="ts">
	import { Check, ChevronDown, FileText, Plus, RotateCcw, Save, ShieldCheck, Trash2, TriangleAlert } from '@lucide/svelte';
	import { initialAnnotationEvidence, initialAnnotationMessages } from './annotationInput';
	import { createEventDispatcher } from 'svelte';
	import { t } from '../../../../../../_shared/i18n';
	import type { DatasetSampleAction, DatasetSampleDetail, SftRevisionContent } from '../../../../../../_shared/feedbackDatasets';

	export let sample: DatasetSampleDetail | null = null;
	export let saving = false;
	export let confirming = false;
	export let acting = false;
	export let error = '';
	export let notice = '';

	const dispatch = createEventDispatcher<{
		save: { content: SftRevisionContent };
		confirm: { next: boolean };
		action: { action: DatasetSampleAction; reason?: string };
	}>();

	let loadedRevisionId = '';
	let target = '';
	let question = '';
	let evidence: Array<{ document_title: string; text: string }> = [];
	let rebuildReason = '';

	$: inputKey = sample ? `${sample.sample.sample_id}:${sample.current_revision?.revision_id ?? sample.sample.generation}` : '';
	$: if (sample && inputKey !== loadedRevisionId) {
		loadedRevisionId = inputKey;
		const content = sample.current_revision?.content as SftRevisionContent | undefined;
		question = content?.messages.filter(item => item.role === 'user').at(-1)?.content ?? sample.source_case.question;
		target = content?.target ?? (sample.source_case.context_snapshot.corrected_answer as string | undefined) ?? (sample.source_case.context_snapshot.candidate_target as string | undefined) ?? (sample.source_case.context_snapshot.rating === 'helpful' ? sample.source_case.answer : '');
		evidence = content ? content.evidence.map((item) => ({ ...item })) : initialAnnotationEvidence(sample);
		rebuildReason = '';
	}

	$: currentRevision = sample?.current_revision ?? null;
	$: missingReasons = (sample?.sample.missing_reasons ?? []).filter(reason => reason !== 'readable_evidence_missing');
	$: currentContent = currentRevision?.content as SftRevisionContent | undefined;
	$: draftChanged = (canEdit && !currentRevision) || Boolean(currentRevision && (
		target.trim() !== currentContent?.target ||
		JSON.stringify(evidence) !== JSON.stringify(currentContent?.evidence)
	));
	$: canConfirm = Boolean(currentRevision && sample?.sample.status === 'needs_confirmation' && !draftChanged && complete && !saving && !confirming && !acting);
	$: canEdit = sample?.sample.status === 'needs_confirmation' || sample?.sample.status === 'confirmed' || sample?.sample.status === 'needs_input';
	$: complete = Boolean(question.trim() && target.trim() && evidence.every(item => item.document_title.trim() && item.text.trim()));

	function content(): SftRevisionContent | null {
		if (!sample) return null;
		return {
			schema_version: currentContent?.schema_version ?? 'literature-sft.v1',
			messages: currentContent?.messages ?? initialAnnotationMessages(sample),
			context: evidence.map(item => ({ document_title: item.document_title.trim(), text: item.text.trim() })),
			target: target.trim(),
			evidence: evidence.map((item) => ({
				document_title: item.document_title.trim(),
				text: item.text.trim()
			}))
		};
	}

	function save() {
		const next = content();
		if (!canEdit || !complete || !next) return;
		dispatch('save', { content: next });
	}

	function confirm(next: boolean) {
		if (canConfirm) dispatch('confirm', { next });
	}

	function act(action: DatasetSampleAction) {
		if (acting || saving || confirming) return;
		if (action === 'rebuild' && !rebuildReason.trim()) return;
		dispatch('action', { action, reason: rebuildReason.trim() || undefined });
	}

	function formatSource(source: Record<string, unknown>) {
		return source.document_title as string | undefined ?? $t('taskDatasets.labels.untitledPaper');
	}
</script>

{#if !sample}
	<section class="empty" aria-live="polite">
		<FileText size={28} aria-hidden="true" />
		<h2>{$t('taskDatasets.labels.selectASample')}</h2>
		<p>{$t('taskDatasets.labels.sftEmptyDescription')}</p>
	</section>
{:else}
	<div class="annotation-grid">
		<section class="question-column" aria-labelledby="question-title">
			<div class="section-kicker">{$t('taskDatasets.labels.input')}</div>
			<h2 id="question-title">{$t('taskDatasets.labels.researchQuestion')}</h2>
			{#if !currentRevision && canEdit}<label for="sft-question">{$t('taskDatasets.questionContent')}</label><textarea id="sft-question" bind:value={question} rows="3" disabled={saving || confirming || acting}></textarea>{:else}<p class="question">{question || $t('taskDatasets.labels.noReadableQuestionAvailable')}</p>{/if}
			<details class="original-answer">
				<summary><ChevronDown size={15} aria-hidden="true" />{$t('taskDatasets.labels.originalAnswer')}</summary>
				<p>{sample.source_case.answer || $t('taskDatasets.labels.noOriginalAnswerAvailable')}</p>
			</details>
			<div class="source-meta">
				<span>{$t('taskDatasets.labels.caseSource')}</span>
				<small>{sample.source_case.status}</small>
			</div>
		</section>

		<section class="editor-column" aria-labelledby="answer-title">
			<div class="section-heading">
				<div>
					<div class="section-kicker">{$t('taskDatasets.labels.humanConfirmation')}</div>
					<h2 id="answer-title">{$t('taskDatasets.labels.correctAnswer')}</h2>
				</div>
				{#if sample.sample.status === 'confirmed'}
					<span class="status status--confirmed"><ShieldCheck size={14} aria-hidden="true" />{$t('taskDatasets.labels.confirmed')}</span>
				{:else}
					<span class="status">{sample.sample.status === 'needs_confirmation' ? $t('taskDatasets.labels.awaitingConfirmation') : sample.sample.status === 'needs_input' ? $t('taskDatasets.labels.needsInput') : sample.sample.status === 'build_failed' ? $t('taskDatasets.labels.buildFailed') : sample.sample.status === 'discarded' ? $t('taskDatasets.labels.discarded') : $t('taskDatasets.labels.building')}</span>
				{/if}
			</div>
			{#if currentRevision || canEdit}
				<label for="sft-target">{$t('taskDatasets.labels.answerContent')}</label>
				<textarea id="sft-target" bind:value={target} rows="12" disabled={!canEdit || saving || confirming || acting}></textarea>
			{:else}
				<p class="missing">{$t('taskDatasets.labels.noCompleteCandidateYetReviewTheMissing')}</p>
			{/if}

			{#if canEdit}<div class="actions" aria-label={$t('taskDatasets.labels.sampleActions')}>
				<button class:primary={draftChanged} type="button" on:click={save} disabled={saving || confirming || acting || !draftChanged || !complete}>
					<Save size={16} aria-hidden="true" />{saving ? $t('taskDatasets.labels.saving') : $t('taskDatasets.labels.saveChanges')}
				</button>
				<button class:primary={!draftChanged} type="button" on:click={() => confirm(false)} disabled={!canConfirm}>
					<Check size={16} aria-hidden="true" />{confirming ? $t('taskDatasets.labels.confirming') : $t('taskDatasets.labels.confirmSample')}
				</button>
				<button type="button" on:click={() => confirm(true)} disabled={!canConfirm}>
					{$t('taskDatasets.labels.confirmAndNext')}
				</button>
			</div>{/if}
			{#if draftChanged}<p class="draft-note" role="status">{$t('taskDatasets.labels.saveYourChangesBeforeConfirming')}</p>{/if}
			<details class="sample-options"><summary>{$t('taskDatasets.moreActions')}</summary>
			{#if sample.sample.status === 'needs_confirmation' || sample.sample.status === 'confirmed' || sample.sample.status === 'needs_input'}
				<div class="rebuild-area">
					<label for="rebuild-reason">{$t('taskDatasets.labels.rebuildFeedback')}</label>
					<textarea id="rebuild-reason" bind:value={rebuildReason} rows="3" maxlength="2000" placeholder={$t('taskDatasets.labels.describeConditionsToCheckOrMissingSources')} disabled={acting}></textarea>
					<button type="button" on:click={() => act('rebuild')} disabled={acting || saving || confirming || !rebuildReason.trim()}><RotateCcw size={16} aria-hidden="true" />{$t('taskDatasets.labels.sendBackForRebuild')}</button>
				</div>
			{/if}
			<div class="recovery-actions">
				{#if sample.sample.status === 'build_failed'}<button type="button" on:click={() => act('retry')} disabled={acting}><RotateCcw size={16} aria-hidden="true" />{$t('taskDatasets.labels.retryBuild')}</button>{/if}
				{#if sample.sample.status === 'discarded'}<button type="button" on:click={() => act('restore')} disabled={acting}><RotateCcw size={16} aria-hidden="true" />{$t('taskDatasets.labels.restoreSample')}</button>{:else}<button type="button" on:click={() => act('discard')} disabled={acting || saving || confirming}><Trash2 size={16} aria-hidden="true" />{$t('taskDatasets.labels.discardSample')}</button>{/if}
			</div>
			</details>
			{#if notice}<p class="notice" role="status">{notice}</p>{/if}
			{#if error}<p class="error" role="alert"><TriangleAlert size={15} aria-hidden="true" />{error}</p>{/if}
		</section>

		<aside class="evidence-column" aria-labelledby="evidence-title">
			<div class="section-kicker">{$t('taskDatasets.labels.review')}</div>
			<h2 id="evidence-title">{$t('taskDatasets.labels.originalEvidence')}</h2>
			<p class="aside-note">{$t('taskDatasets.optionalEvidence')}</p>
			<div class="evidence-list">
				{#each evidence as item, index}
					<article class="evidence-card">
						<label for={`evidence-title-${index}`}>{$t('taskDatasets.labels.paperTitle')}</label>
						<input id={`evidence-title-${index}`} bind:value={item.document_title} disabled={!canEdit || saving || confirming || acting} />
						<label for={`evidence-text-${index}`}>{$t('taskDatasets.labels.excerpt')}</label>
						<textarea id={`evidence-text-${index}`} bind:value={item.text} rows="6" disabled={!canEdit || saving || confirming || acting}></textarea>
						{#if canEdit}<button class="evidence-remove" type="button" aria-label={`${$t('taskDatasets.removeEvidence')} ${index + 1}`} title={$t('taskDatasets.removeEvidence')} on:click={() => evidence = evidence.filter((_, i) => i !== index)} disabled={saving || confirming || acting}><Trash2 size={15} aria-hidden="true" /></button>{/if}
					</article>
				{:else}
					<p class="aside-note">{$t('taskDatasets.noEvidence')}</p>
				{/each}
			</div>
			{#if canEdit}<button class="evidence-add" type="button" on:click={() => evidence = [...evidence, { document_title: '', text: '' }]} disabled={saving || confirming || acting}><Plus size={15} aria-hidden="true" />{$t('taskDatasets.addEvidence')}</button>{/if}
			{#if missingReasons.length}
				<div class="missing-box">
					<strong>{$t('taskDatasets.labels.additionalInputNeeded')}</strong>
					<ul>{#each missingReasons as reason}<li>{reason}</li>{/each}</ul>
				</div>
			{/if}
			{#if sample.source_case.omitted_candidates.length}
				<details class="omitted">
					<summary>{$t('taskDatasets.labels.unreadCandidateSourcesCount', { count: sample.source_case.omitted_candidates.length })}</summary>
					{#each sample.source_case.omitted_candidates as source}
						<p>{formatSource(source)}：{String(source.reason ?? $t('taskDatasets.labels.notRead'))}</p>
					{/each}
				</details>
			{/if}
		</aside>
	</div>
{/if}

<style>
	.evidence-add, .evidence-remove { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 8px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-secondary); cursor: pointer; }
	.evidence-add { margin-top: 12px; }
	.evidence-remove { width: 32px; height: 32px; margin-top: 6px; }
	.sample-options { margin-top: 24px; border-top: 1px solid var(--border-default); padding-top: 12px; }
	.sample-options > summary { cursor: pointer; color: var(--text-secondary); font-size: 13px; }
	.sample-options .rebuild-area { border-top: 0; margin-top: 12px; }
	:global(button), :global(input), :global(textarea) { font: inherit; }
	.annotation-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 1px; background: var(--border-default); border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; }
	.question-column, .editor-column, .evidence-column { background: var(--surface-card); padding: 24px; min-width: 0; }
	.editor-column { background: var(--bg-subtle); }
	.section-kicker { color: var(--brand-primary); font-size: 11px; font-weight: 800; letter-spacing: 0; text-transform: uppercase; }
	h2 { margin: 5px 0 14px; color: var(--text-primary); font-size: 19px; line-height: 1.25; }
	.question { color: var(--text-primary); font-size: 16px; line-height: 1.65; white-space: pre-wrap; }
	.original-answer { margin-top: 28px; border-top: 1px solid var(--border-default); padding-top: 14px; }
	.original-answer summary, .omitted summary { display: flex; align-items: center; gap: 6px; color: var(--text-secondary); cursor: pointer; font-size: 13px; font-weight: 700; }
	.original-answer summary :global(svg) { transition: transform .15s ease; }
	.original-answer[open] summary :global(svg), .omitted[open] summary :global(svg) { transform: rotate(180deg); }
	.original-answer p { color: var(--text-secondary); font-size: 14px; line-height: 1.65; white-space: pre-wrap; }
	.source-meta { display: flex; justify-content: space-between; align-items: center; margin-top: 32px; padding-top: 14px; border-top: 1px solid var(--border-default); color: var(--text-secondary); font-size: 12px; }
	.source-meta small { color: var(--text-secondary); }
	.section-heading { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
	label { display: block; margin: 12px 0 6px; color: var(--text-secondary); font-size: 12px; font-weight: 700; }
	textarea, input { box-sizing: border-box; width: 100%; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); padding: 10px 11px; line-height: 1.55; resize: vertical; }
	textarea:focus, input:focus { outline: 3px solid var(--brand-border); border-color: var(--brand-primary); }
	textarea:disabled, input:disabled { background: var(--bg-subtle); color: var(--text-secondary); }
	.status { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--border-strong); border-radius: 999px; padding: 5px 9px; color: var(--text-secondary); font-size: 12px; white-space: nowrap; }
	.status--confirmed { border-color: var(--brand-border); color: var(--brand-primary); background: var(--brand-soft); }
	.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
	.actions button { display: inline-flex; gap: 7px; align-items: center; min-height: 36px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); padding: 7px 11px; cursor: pointer; }
	.actions button:hover:not(:disabled) { border-color: var(--brand-primary); color: var(--brand-primary); }
	.actions button.primary { border-color: var(--brand-primary); background: var(--brand-primary); color: white; }
	.actions button:disabled { cursor: not-allowed; opacity: .48; }
	.draft-note { color: var(--warning-text); font-size: 13px; }
	.rebuild-area { margin-top: 22px; border-top: 1px solid var(--border-default); padding-top: 10px; }
	.rebuild-area button, .recovery-actions button { display: inline-flex; align-items: center; gap: 7px; min-height: 36px; margin-top: 10px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); padding: 7px 11px; cursor: pointer; }
	.rebuild-area button:disabled, .recovery-actions button:disabled { cursor: not-allowed; opacity: .48; }
	.recovery-actions { display: flex; gap: 8px; margin-top: 12px; }
	.notice { margin: 14px 0 0; color: var(--brand-primary); font-size: 13px; }
	.error { display: flex; gap: 7px; align-items: flex-start; margin: 14px 0 0; color: var(--danger-text); font-size: 13px; }
	.aside-note { margin: -4px 0 18px; color: var(--text-secondary); font-size: 12px; line-height: 1.55; }
	.evidence-list { display: grid; gap: 14px; }
	.evidence-card { border-left: 3px solid var(--brand-primary); padding-left: 12px; }
	.evidence-card label { margin-top: 0; }
	.evidence-card textarea { min-height: 120px; }
	.missing, .missing-box { color: var(--warning-text); font-size: 13px; line-height: 1.55; }
	.missing-box { margin-top: 16px; border: 1px solid var(--warning-border); border-radius: 6px; background: var(--warning-bg); padding: 11px 12px; }
	.missing-box ul { margin: 7px 0 0; padding-left: 18px; }
	.omitted { margin-top: 18px; border-top: 1px solid var(--border-default); padding-top: 13px; }
	.omitted p { color: var(--text-secondary); font-size: 12px; line-height: 1.5; }
	.empty { display: grid; justify-items: center; padding: 72px 24px; border: 1px dashed var(--border-strong); border-radius: 8px; background: var(--surface-card); color: var(--text-secondary); text-align: center; }
	.empty h2 { margin-bottom: 5px; }
	.empty p { margin: 0; max-width: 380px; line-height: 1.6; }

	@media (max-width: 680px) { .annotation-grid { display: block; } .question-column, .editor-column, .evidence-column { padding: 19px; } .evidence-column { border-top: 1px solid var(--border-default); } .evidence-list { grid-template-columns: 1fr; } .actions button { flex: 1 1 auto; justify-content: center; } }
	.question-column { grid-column: 1 / -1; padding: 20px; border-bottom: 1px solid var(--border-default); }
	.editor-column, .evidence-column { padding: 20px; }
	.question { font-size: 14px; margin: 0; }
	.original-answer { margin-top: 16px; padding-top: 12px; }
	.source-meta { margin-top: 12px; padding-top: 12px; }
	.section-kicker { color: var(--text-secondary); font-weight: 600; }
	h2 { font-size: 16px; }
	.status--confirmed { color: var(--success-text); background: var(--success-bg); border-color: var(--success-border); }
	button:focus-visible, summary:focus-visible { outline: 2px solid var(--brand-primary); outline-offset: 3px; }
	.actions button.primary:hover:not(:disabled) { color: white; background: var(--brand-primary-hover); }
	@media (max-width: 760px) { .annotation-grid { display: block; } .evidence-column { border-top: 1px solid var(--border-default); } }

	/* SFT A uses the center column for the candidate and reserves the right rail for evidence. */
	.annotation-grid { grid-template-columns: minmax(0, 1fr) minmax(280px, .38fr); align-items: stretch; }
	.question-column { grid-column: 1; grid-row: 1; border-bottom: 1px solid var(--border-default); }
	.editor-column { grid-column: 1; grid-row: 2; }
	.evidence-column { grid-column: 2; grid-row: 1 / span 2; border-left: 1px solid var(--border-default); }
	@media (max-width: 760px) { .annotation-grid { display: block; } .question-column, .editor-column, .evidence-column { grid-column: auto; grid-row: auto; } .evidence-column { border-left: 0; } }
</style>
