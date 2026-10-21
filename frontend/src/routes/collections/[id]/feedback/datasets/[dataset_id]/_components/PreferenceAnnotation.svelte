<script lang="ts">
	import { Check, ChevronDown, FileText, Plus, RotateCcw, Save, ShieldCheck, Trash2, TriangleAlert } from '@lucide/svelte';
	import { initialAnnotationEvidence, initialAnnotationMessages } from './annotationInput';
	import { createEventDispatcher } from 'svelte';
	$: missingReasons = (sample?.sample.missing_reasons ?? []).filter(reason => reason !== 'readable_evidence_missing');
	import { t } from '../../../../../../_shared/i18n';
	import type {
		DatasetSampleAction,
		DatasetSampleDetail,
		PreferenceChoice,
		PreferenceRevisionContent
	} from '../../../../../../_shared/feedbackDatasets';

	export let sample: DatasetSampleDetail | null = null;
	export let saving = false;
	export let confirming = false;
	export let acting = false;
	export let error = '';
	export let notice = '';

	const dispatch = createEventDispatcher<{
		save: { content: PreferenceRevisionContent };
		confirm: { next: boolean; content?: PreferenceRevisionContent };
		action: { action: DatasetSampleAction; reason?: string };
	}>();

	let loadedRevisionId = '';
	let responseA = '';
	let question = '';
	let responseB = '';
	let humanPreference: PreferenceChoice | null = null;
	let evidence: Array<{ document_title: string; text: string }> = [];
	let rebuildReason = '';
	$: preferenceOptions = (['a', 'b', 'tie', 'unclear'] as PreferenceChoice[]).map(choice =>
		[choice, $t(`taskDatasets.preferenceChoices.${choice}`)] as const
	);

	$: inputKey = sample ? `${sample.sample.sample_id}:${sample.current_revision?.revision_id ?? sample.sample.generation}` : '';
	$: if (sample && inputKey !== loadedRevisionId) {
		loadedRevisionId = inputKey;
		const content = sample.current_revision?.content as PreferenceRevisionContent | undefined;
		question = content?.messages.filter(item => item.role === 'user').at(-1)?.content ?? sample.source_case.question;
		responseA = content?.response_a ?? sample.source_case.answer;
		responseB = content?.response_b ?? String(sample.source_case.context_snapshot.corrected_answer ?? sample.source_case.context_snapshot.candidate_target ?? '');
		humanPreference = content?.human_preference ?? null;
		evidence = content ? content.evidence.map((item) => ({ ...item })) : initialAnnotationEvidence(sample);
		rebuildReason = '';
	}

	$: currentRevision = sample?.current_revision ?? null;
	$: currentContent = currentRevision?.content as PreferenceRevisionContent | undefined;
	$: suggestedPreference = currentContent?.suggested_preference ?? null;
	$: draftChanged = (canEdit && !currentContent) || Boolean(currentContent && (
		responseA.trim() !== currentContent.response_a ||
		responseB.trim() !== currentContent.response_b ||
		humanPreference !== currentContent.human_preference ||
		JSON.stringify(evidence) !== JSON.stringify(currentContent.evidence)
	));
	$: canEdit = sample?.sample.status === 'needs_confirmation' || sample?.sample.status === 'confirmed' || sample?.sample.status === 'needs_input';
	$: complete = Boolean(question.trim() && responseA.trim() && responseB.trim() && responseA.trim() !== responseB.trim() && evidence.every(item => item.document_title.trim() && item.text.trim()));
	$: canConfirm = Boolean(
		currentRevision &&
		sample?.sample.status === 'needs_confirmation' &&
		complete &&
		humanPreference &&
		responseA.trim() &&
		responseB.trim() &&
		responseA.trim() !== responseB.trim() &&
		!saving && !confirming && !acting
	);

	function content(): PreferenceRevisionContent | null {
		if (!sample) return null;
		return {
			schema_version: 'literature-preference.v1',
			messages: currentContent?.messages ?? initialAnnotationMessages(sample),
			context: evidence.map(item => ({ document_title: item.document_title.trim(), text: item.text.trim() })),
			response_a: responseA.trim(),
			response_b: responseB.trim(),
			suggested_preference: currentContent?.suggested_preference ?? null,
			rationale: currentContent?.rationale ?? '',
			evidence: evidence.map((item) => ({ document_title: item.document_title.trim(), text: item.text.trim() })),
			human_preference: humanPreference
		};
	}

	function save() {
		const next = content();
		if (!canEdit || !complete || !next) return;
		dispatch('save', { content: next });
	}

	function confirm(next: boolean) {
		if (!canConfirm) return;
		const draft = draftChanged ? content() : null;
		dispatch('confirm', { next, ...(draft ? { content: draft } : {}) });
	}

	function act(action: DatasetSampleAction) {
		if (acting || saving || confirming) return;
		if (action === 'rebuild' && !rebuildReason.trim()) return;
		dispatch('action', { action, reason: rebuildReason.trim() || undefined });
	}
</script>

{#if !sample}
	<section class="empty"><FileText size={28} aria-hidden="true" /><h2>{$t('taskDatasets.labels.selectASample')}</h2><p>{$t('taskDatasets.labels.preferenceEmptyDescription')}</p></section>
{:else}
	<div class="annotation-grid">
		<section class="question-column" aria-labelledby="preference-question-title">
			<div class="section-kicker">{$t('taskDatasets.labels.inputConditions')}</div>
			<h2 id="preference-question-title">{$t('taskDatasets.labels.researchQuestion')}</h2>
			{#if !currentRevision && canEdit}<label for="preference-question">{$t('taskDatasets.questionContent')}</label><textarea id="preference-question" bind:value={question} rows="3" disabled={saving || confirming || acting}></textarea>{:else}<p class="question">{question || $t('taskDatasets.labels.noReadableQuestionAvailable')}</p>{/if}
			<details class="original-answer"><summary><ChevronDown size={15} aria-hidden="true" />{$t('taskDatasets.labels.originalAnswer')}</summary><p>{sample.source_case.answer || $t('taskDatasets.labels.noOriginalAnswerAvailable')}</p></details>
		</section>

		<section class="editor-column" aria-labelledby="preference-answer-title">
			<div class="section-heading"><div><div class="section-kicker">{$t('taskDatasets.labels.humanSelection')}</div><h2 id="preference-answer-title">{$t('taskDatasets.labels.answerComparison')}</h2></div>{#if sample.sample.status === 'confirmed'}<span class="status status--confirmed"><ShieldCheck size={14} aria-hidden="true" />{$t('taskDatasets.labels.confirmed')}</span>{:else}<span class="status">{sample.sample.status === 'needs_confirmation' ? $t('taskDatasets.labels.awaitingConfirmation') : sample.sample.status === 'needs_input' ? $t('taskDatasets.labels.needsInput') : sample.sample.status === 'build_failed' ? $t('taskDatasets.labels.buildFailed') : sample.sample.status === 'discarded' ? $t('taskDatasets.labels.discarded') : $t('taskDatasets.labels.building')}</span>{/if}</div>
			{#if currentRevision || canEdit}
				<div class="response-grid">
					<label><span>{$t('taskDatasets.labels.answerA')}</span><textarea aria-label={$t('taskDatasets.labels.answerA')} bind:value={responseA} rows="8" disabled={!canEdit || saving || confirming || acting}></textarea></label>
					<label><span>{$t('taskDatasets.labels.answerB')}</span><textarea aria-label={$t('taskDatasets.labels.answerB')} bind:value={responseB} rows="8" disabled={!canEdit || saving || confirming || acting}></textarea></label>
				</div>
				<section class="worker-recommendation" aria-labelledby="preference-recommendation-title">
					<div class="recommendation-heading">
						<h3 id="preference-recommendation-title">{$t('taskDatasets.workerRecommendation')}</h3>
						<strong>{suggestedPreference ? $t(`taskDatasets.preferenceChoices.${suggestedPreference}`) : $t('taskDatasets.noRecommendation')}</strong>
						{#if suggestedPreference && canEdit}<button type="button" on:click={() => humanPreference = suggestedPreference} disabled={saving || confirming || acting || humanPreference === suggestedPreference}><Check size={15} aria-hidden="true" />{$t('taskDatasets.acceptRecommendation')}</button>{/if}
					</div>
					{#if currentContent?.rationale}<p>{currentContent.rationale}</p>{/if}
				</section>
				<fieldset class="choice-field"><legend>{$t('taskDatasets.labels.whichAnswerIsBetter')}</legend><div class="choice-grid">
					{#each preferenceOptions as option}
						<label class:selected={humanPreference === option[0]}><input type="radio" name="preference-choice" value={option[0]} bind:group={humanPreference} disabled={!canEdit || saving || confirming || acting} /><span>{option[1]}</span></label>
					{/each}
				</div></fieldset>
			{:else}<p class="missing">{$t('taskDatasets.labels.noCompleteAnswerPairYetAddInput')}</p>{/if}
			{#if canEdit}<div class="actions"><button type="button" on:click={save} disabled={saving || confirming || acting || !draftChanged || !complete}><Save size={16} aria-hidden="true" />{saving ? $t('taskDatasets.labels.saving') : $t('taskDatasets.labels.saveChanges')}</button><button class="primary" type="button" on:click={() => confirm(false)} disabled={!canConfirm}><Check size={16} aria-hidden="true" />{confirming ? $t('taskDatasets.labels.confirming') : $t('taskDatasets.labels.confirmSample')}</button><button type="button" on:click={() => confirm(true)} disabled={!canConfirm}>{$t('taskDatasets.labels.confirmAndNext')}</button></div>{/if}
			<details class="sample-options"><summary>{$t('taskDatasets.moreActions')}</summary>
			{#if sample.sample.status === 'needs_confirmation' || sample.sample.status === 'confirmed' || sample.sample.status === 'needs_input'}<div class="rebuild-area"><label for="preference-rebuild-reason">{$t('taskDatasets.labels.rebuildFeedback')}</label><textarea id="preference-rebuild-reason" bind:value={rebuildReason} rows="3" maxlength="2000" placeholder={$t('taskDatasets.labels.describeConditionsToCheckOrMissingSources')} disabled={acting}></textarea><button type="button" on:click={() => act('rebuild')} disabled={acting || saving || confirming || !rebuildReason.trim()}><RotateCcw size={16} aria-hidden="true" />{$t('taskDatasets.labels.sendBackForRebuild')}</button></div>{/if}
			<div class="recovery-actions">{#if sample.sample.status === 'build_failed'}<button type="button" on:click={() => act('retry')} disabled={acting}><RotateCcw size={16} aria-hidden="true" />{$t('taskDatasets.labels.retryBuild')}</button>{/if}{#if sample.sample.status === 'discarded'}<button type="button" on:click={() => act('restore')} disabled={acting}><RotateCcw size={16} aria-hidden="true" />{$t('taskDatasets.labels.restoreSample')}</button>{:else}<button type="button" on:click={() => act('discard')} disabled={acting || saving || confirming}><Trash2 size={16} aria-hidden="true" />{$t('taskDatasets.labels.discardSample')}</button>{/if}</div>
			</details>
			{#if notice}<p class="notice" role="status">{notice}</p>{/if}{#if error}<p class="error" role="alert"><TriangleAlert size={15} aria-hidden="true" />{error}</p>{/if}
		</section>

		<aside class="evidence-column" aria-labelledby="preference-evidence-title">
			<div class="section-kicker">{$t('taskDatasets.labels.review')}</div><h2 id="preference-evidence-title">{$t('taskDatasets.labels.sharedEvidence')}</h2><p class="aside-note">{$t('taskDatasets.labels.paperExcerptsCount', { count: evidence.length })}</p>
			<div class="evidence-list">
				{#each evidence as item, index}<article class="evidence-card">
					<label for={`preference-evidence-title-${index}`}>{$t('taskDatasets.labels.paperTitle')}</label><input id={`preference-evidence-title-${index}`} bind:value={item.document_title} disabled={!canEdit || saving || confirming || acting} />
					<label for={`preference-evidence-text-${index}`}>{$t('taskDatasets.labels.excerpt')}</label><textarea id={`preference-evidence-text-${index}`} bind:value={item.text} rows="6" disabled={!canEdit || saving || confirming || acting}></textarea>
					{#if canEdit}<button class="evidence-remove" type="button" aria-label={`${$t('taskDatasets.removeEvidence')} ${index + 1}`} title={$t('taskDatasets.removeEvidence')} on:click={() => evidence = evidence.filter((_, i) => i !== index)} disabled={saving || confirming || acting}><Trash2 size={15} aria-hidden="true" /></button>{/if}
				</article>{:else}<p class="aside-note">{$t('taskDatasets.noEvidence')}</p>{/each}
			</div>
			{#if canEdit}<button class="evidence-add" type="button" on:click={() => evidence = [...evidence, { document_title: '', text: '' }]} disabled={saving || confirming || acting}><Plus size={15} aria-hidden="true" />{$t('taskDatasets.addEvidence')}</button>{/if}
			{#if missingReasons.length}<div class="missing-box"><strong>{$t('taskDatasets.labels.additionalInputNeeded')}</strong><ul>{#each missingReasons as reason}<li>{reason}</li>{/each}</ul></div>{/if}
		</aside>
	</div>
{/if}

<style>
	.worker-recommendation { margin-top: 18px; padding: 14px 0; border-top: 1px solid var(--border-default); border-bottom: 1px solid var(--border-default); }
	.recommendation-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
	.recommendation-heading h3 { margin: 0; color: var(--text-secondary); font-size: 12px; font-weight: 600; }
	.recommendation-heading strong { color: var(--brand-primary); font-size: 13px; }
	.recommendation-heading button { display: inline-flex; align-items: center; gap: 6px; margin-left: auto; padding: 7px 10px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); cursor: pointer; }
	.recommendation-heading button:disabled { cursor: not-allowed; opacity: .48; }
	.worker-recommendation p { margin: 10px 0 0; color: var(--text-secondary); font-size: 13px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
	.evidence-add, .evidence-remove { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 8px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-secondary); cursor: pointer; }
	.evidence-add { margin-top: 12px; }
	.evidence-remove { width: 32px; height: 32px; margin-top: 6px; }
	.sample-options { margin-top: 24px; border-top: 1px solid var(--border-default); padding-top: 12px; }
	.sample-options > summary { cursor: pointer; color: var(--text-secondary); font-size: 13px; }
	.sample-options .rebuild-area { border-top: 0; margin-top: 12px; }
	:global(button), :global(input), :global(textarea) { font: inherit; }
	.annotation-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 1px; background: var(--border-default); border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; }
	.question-column, .editor-column, .evidence-column { background: var(--surface-card); padding: 24px; min-width: 0; }.editor-column { background: var(--bg-subtle); }
	.section-kicker { color: var(--brand-primary); font-size: 11px; font-weight: 800; letter-spacing: 0; text-transform: uppercase; } h2 { margin: 5px 0 14px; color: var(--text-primary); font-size: 19px; line-height: 1.25; }.question { color: var(--text-primary); font-size: 16px; line-height: 1.65; white-space: pre-wrap; }
	.original-answer { margin-top: 28px; border-top: 1px solid var(--border-default); padding-top: 14px; }.original-answer summary { display: flex; align-items: center; gap: 6px; color: var(--text-secondary); cursor: pointer; font-size: 13px; font-weight: 700; }.original-answer p { color: var(--text-secondary); font-size: 14px; line-height: 1.65; white-space: pre-wrap; }
	.section-heading { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; } label { display: block; margin: 12px 0 6px; color: var(--text-secondary); font-size: 12px; font-weight: 700; } textarea, input { box-sizing: border-box; width: 100%; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); padding: 10px 11px; line-height: 1.55; resize: vertical; } textarea:focus, input:focus { outline: 3px solid var(--brand-border); border-color: var(--brand-primary); } textarea:disabled, input:disabled { background: var(--bg-subtle); color: var(--text-secondary); }
	.status { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--border-strong); border-radius: 999px; padding: 5px 9px; color: var(--text-secondary); font-size: 12px; white-space: nowrap; }.status--confirmed { border-color: var(--brand-border); color: var(--brand-primary); background: var(--brand-soft); }.response-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }.response-grid textarea { min-height: 170px; }.choice-field { border: 0; margin: 18px 0 0; padding: 0; }.choice-field legend { color: var(--text-secondary); font-size: 12px; font-weight: 700; }.choice-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; margin-top: 8px; }.choice-grid label { display: flex; align-items: center; justify-content: center; gap: 6px; min-height: 38px; margin: 0; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); cursor: pointer; }.choice-grid label.selected { border-color: var(--brand-primary); background: var(--brand-soft); color: var(--brand-primary); }.choice-grid input { width: auto; }
	.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }.actions button, .rebuild-area button, .recovery-actions button { display: inline-flex; align-items: center; gap: 7px; min-height: 36px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); padding: 7px 11px; cursor: pointer; }.actions button:hover:not(:disabled), .rebuild-area button:hover:not(:disabled), .recovery-actions button:hover:not(:disabled) { border-color: var(--brand-primary); color: var(--brand-primary); }.actions button.primary { border-color: var(--brand-primary); background: var(--brand-primary); color: white; }.actions button:disabled, .rebuild-area button:disabled, .recovery-actions button:disabled { cursor: not-allowed; opacity: .48; }.rebuild-area { margin-top: 22px; border-top: 1px solid var(--border-default); padding-top: 10px; }.recovery-actions { display: flex; gap: 8px; margin-top: 12px; }.notice { margin: 14px 0 0; color: var(--brand-primary); font-size: 13px; }.error { display: flex; gap: 7px; align-items: flex-start; margin: 14px 0 0; color: var(--danger-text); font-size: 13px; }.aside-note { margin: -4px 0 18px; color: var(--text-secondary); font-size: 12px; line-height: 1.55; }.evidence-list { display: grid; gap: 14px; }.evidence-card { border-left: 3px solid var(--brand-primary); padding-left: 12px; }.evidence-card label { margin-top: 0; }.evidence-card textarea { min-height: 120px; }.missing, .missing-box { color: var(--warning-text); font-size: 13px; line-height: 1.55; }.missing-box { margin-top: 16px; border: 1px solid var(--warning-border); border-radius: 6px; background: var(--warning-bg); padding: 11px 12px; }.missing-box ul { margin: 7px 0 0; padding-left: 18px; }.empty { display: grid; justify-items: center; padding: 72px 24px; border: 1px dashed var(--border-strong); border-radius: 8px; background: var(--surface-card); color: var(--text-secondary); text-align: center; }.empty h2 { margin-bottom: 5px; }.empty p { margin: 0; max-width: 380px; line-height: 1.6; }

	@media (max-width: 760px) { .response-grid, .choice-grid { grid-template-columns: 1fr 1fr; } }
	@media (max-width: 680px) { .annotation-grid { display: block; } .question-column, .editor-column, .evidence-column { padding: 19px; } .evidence-column { border-top: 1px solid var(--border-default); } .evidence-list { grid-template-columns: 1fr; } .response-grid, .choice-grid { grid-template-columns: 1fr; } .actions button { flex: 1 1 auto; justify-content: center; } }
	.question-column { grid-column: 1 / -1; padding: 20px; border-bottom: 1px solid var(--border-default); }
	.editor-column, .evidence-column { padding: 20px; }
	.question { font-size: 14px; margin: 0; }
	.original-answer { margin-top: 16px; padding-top: 12px; }

	.section-kicker { color: var(--text-secondary); font-weight: 600; }
	h2 { font-size: 16px; }
	.status--confirmed { color: var(--success-text); background: var(--success-bg); border-color: var(--success-border); }
	button:focus-visible, summary:focus-visible { outline: 2px solid var(--brand-primary); outline-offset: 3px; }
	input[type="radio"] { accent-color: var(--brand-primary); }
	.actions button.primary:hover:not(:disabled) { color: white; background: var(--brand-primary-hover); }
	@media (max-width: 760px) { .annotation-grid { display: block; } .evidence-column { border-top: 1px solid var(--border-default); } }

	/* P1 keeps both answers together while the evidence rail stays visible beside them. */
	.annotation-grid { grid-template-columns: minmax(0, 1fr) minmax(280px, .38fr); align-items: stretch; }
	.question-column { grid-column: 1; grid-row: 1; border-bottom: 1px solid var(--border-default); }
	.editor-column { grid-column: 1; grid-row: 2; }
	.evidence-column { grid-column: 2; grid-row: 1 / span 2; border-left: 1px solid var(--border-default); }
	@media (max-width: 760px) { .annotation-grid { display: block; } .question-column, .editor-column, .evidence-column { grid-column: auto; grid-row: auto; } .evidence-column { border-left: 0; } }
</style>
