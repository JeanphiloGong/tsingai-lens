<script lang="ts">
	import { Check, ChevronDown, FileText, Plus, RotateCcw, Save, ShieldCheck, Trash2, TriangleAlert } from '@lucide/svelte';
	import { initialAnnotationEvidence } from './annotationInput';
	import { createEventDispatcher } from 'svelte';
	import { t } from '../../../../../../_shared/i18n';
	import type { DatasetSampleAction, DatasetSampleDetail, EvaluationRevisionContent } from '../../../../../../_shared/feedbackDatasets';

	export let sample: DatasetSampleDetail | null = null;
	export let saving = false;
	export let confirming = false;
	export let acting = false;
	export let error = '';
	export let notice = '';

	const dispatch = createEventDispatcher<{
		save: { content: EvaluationRevisionContent };
		confirm: { next: boolean };
		action: { action: DatasetSampleAction; reason?: string };
	}>();

	let loadedRevisionId = '';
	let reference = '';
	let question = '';
	let criteriaText = '';
	let evaluationMode: 'reference' | 'rubric' = 'reference';
	let evidence: Array<{ document_title: string; text: string }> = [];
	let rebuildReason = '';

	$: inputKey = sample ? `${sample.sample.sample_id}:${sample.current_revision?.revision_id ?? sample.sample.generation}` : '';
	$: if (sample && inputKey !== loadedRevisionId) {
		loadedRevisionId = inputKey;
		const content = sample.current_revision?.content as EvaluationRevisionContent | undefined;
		question = content?.messages.filter(item => item.role === 'user').at(-1)?.content ?? sample.source_case.question;
		reference = content?.reference ?? String(sample.source_case.context_snapshot.evaluation_reference ?? sample.source_case.context_snapshot.corrected_answer ?? '');
		criteriaText = content?.criteria.join('\n') ?? '';
		evaluationMode = content?.evaluation_mode ?? 'reference';
		evidence = content ? content.evidence.map((item) => ({ ...item })) : initialAnnotationEvidence(sample);
		rebuildReason = '';
	}

	$: currentRevision = sample?.current_revision ?? null;
	$: currentContent = currentRevision?.content as EvaluationRevisionContent | undefined;
	$: criteria = criteriaText.split('\n').map((item) => item.trim()).filter(Boolean);
	$: draftChanged = (canEdit && !currentContent) || Boolean(currentContent && (
		reference.trim() !== currentContent.reference ||
		JSON.stringify(criteria) !== JSON.stringify(currentContent.criteria) ||
		evaluationMode !== currentContent.evaluation_mode ||
		JSON.stringify(evidence) !== JSON.stringify(currentContent.evidence)
	));
	$: canEdit = sample?.sample.status === 'needs_confirmation' || sample?.sample.status === 'confirmed' || sample?.sample.status === 'needs_input';
	$: complete = Boolean(question.trim() && criteria.length && (evaluationMode === 'rubric' || reference.trim()) && evidence.length && evidence.every(item => item.document_title.trim() && item.text.trim()));
	$: canConfirm = Boolean(
		currentRevision && sample?.sample.status === 'needs_confirmation' && !draftChanged && complete &&
		criteria.length && (evaluationMode === 'rubric' || reference.trim()) &&
		!saving && !confirming && !acting
	);

	function content(): EvaluationRevisionContent | null {
		if (!sample) return null;
		return {
			schema_version: 'literature-evaluation.v1',
			messages: currentContent?.messages ?? [{ role: 'user', content: question.trim() }],
			context: evidence.map(item => ({ document_title: item.document_title.trim(), text: item.text.trim() })),
			reference: reference.trim(),
			criteria,
			evaluation_mode: evaluationMode,
			evidence: evidence.map((item) => ({ document_title: item.document_title.trim(), text: item.text.trim() }))
		};
	}

	function save() {
		const next = content();
		if (!canEdit || !complete || !next) return;
		dispatch('save', { content: next });
	}

	function act(action: DatasetSampleAction) {
		if (acting || saving || confirming) return;
		if (action === 'rebuild' && !rebuildReason.trim()) return;
		dispatch('action', { action, reason: rebuildReason.trim() || undefined });
	}
</script>

{#if !sample}
	<section class="empty"><FileText size={28} aria-hidden="true" /><h2>选择一个样本</h2><p>左侧队列中的候选会在这里显示测试问题、参考答案和评分标准。</p></section>
{:else}
	<div class="annotation-grid">
		<section class="question-column" aria-labelledby="evaluation-question-title">
			<div class="section-kicker">测试输入</div><h2 id="evaluation-question-title">研究问题</h2>
			{#if !currentRevision && canEdit}<label for="evaluation-question">{$t('taskDatasets.questionContent')}</label><textarea id="evaluation-question" bind:value={question} rows="3" disabled={saving || confirming || acting}></textarea>{:else}<p class="question">{question || '暂无可读问题'}</p>{/if}
			<details class="original-answer"><summary><ChevronDown size={15} aria-hidden="true" />原始回答</summary><p>{sample.source_case.answer || '暂无原始回答'}</p></details>
			<div class="source-meta"><span>评测模式</span><small>{evaluationMode === 'rubric' ? '评分标准' : '参考答案'}</small></div>
		</section>

		<section class="editor-column" aria-labelledby="evaluation-editor-title">
			<div class="section-heading"><div><div class="section-kicker">人工确认</div><h2 id="evaluation-editor-title">评测标准</h2></div>{#if sample.sample.status === 'confirmed'}<span class="status status--confirmed"><ShieldCheck size={14} aria-hidden="true" />已确认</span>{:else}<span class="status">{sample.sample.status === 'needs_confirmation' ? '待确认' : sample.sample.status === 'needs_input' ? '待补充' : sample.sample.status === 'build_failed' ? '构建失败' : sample.sample.status === 'discarded' ? '已丢弃' : '构建中'}</span>{/if}</div>
			{#if currentRevision || canEdit}
				<label for="evaluation-mode">评测模式</label><select id="evaluation-mode" bind:value={evaluationMode} disabled={!canEdit || saving || confirming || acting}><option value="reference">参考答案</option><option value="rubric">评分标准</option></select>
				<label for="evaluation-reference">参考答案{evaluationMode === 'rubric' ? '（可选）' : ''}</label><textarea id="evaluation-reference" bind:value={reference} rows="6" disabled={!canEdit || saving || confirming || acting} placeholder="写出可判定的参考结果"></textarea>
				<label for="evaluation-criteria">评分标准（每行一条）</label><textarea id="evaluation-criteria" aria-label="评分标准" bind:value={criteriaText} rows="8" disabled={!canEdit || saving || confirming || acting} placeholder="必须指出文献 B 的预热条件\n引用对应图注证据\n不能推广到未测试的工艺条件"></textarea>
			{:else}<p class="missing">当前还没有可判定的评测标准。请补充标准后重新构建。</p>{/if}
			{#if canEdit}<div class="actions"><button class:primary={draftChanged} type="button" on:click={save} disabled={saving || confirming || acting || !draftChanged || !complete}><Save size={16} aria-hidden="true" />{saving ? '保存中…' : '保存修改'}</button><button class:primary={!draftChanged} type="button" on:click={() => dispatch('confirm', { next: false })} disabled={!canConfirm}><Check size={16} aria-hidden="true" />{confirming ? '确认中…' : '确认样本'}</button><button type="button" on:click={() => dispatch('confirm', { next: true })} disabled={!canConfirm}>确认并下一条</button></div>{/if}
			{#if draftChanged}<p class="draft-note" role="status">有未保存的修改，保存后才能确认。</p>{/if}
			<details class="sample-options"><summary>{$t('taskDatasets.moreActions')}</summary>
			{#if sample.sample.status === 'needs_confirmation' || sample.sample.status === 'confirmed' || sample.sample.status === 'needs_input'}<div class="rebuild-area"><label for="evaluation-rebuild-reason">退回意见</label><textarea id="evaluation-rebuild-reason" bind:value={rebuildReason} rows="3" maxlength="2000" placeholder="说明应核对的条件或缺失来源" disabled={acting}></textarea><button type="button" on:click={() => act('rebuild')} disabled={acting || saving || confirming || !rebuildReason.trim()}><RotateCcw size={16} aria-hidden="true" />退回重建</button></div>{/if}
			<div class="recovery-actions">{#if sample.sample.status === 'build_failed'}<button type="button" on:click={() => act('retry')} disabled={acting}><RotateCcw size={16} aria-hidden="true" />重试构建</button>{/if}{#if sample.sample.status === 'discarded'}<button type="button" on:click={() => act('restore')} disabled={acting}><RotateCcw size={16} aria-hidden="true" />恢复样本</button>{:else}<button type="button" on:click={() => act('discard')} disabled={acting || saving || confirming}><Trash2 size={16} aria-hidden="true" />丢弃样本</button>{/if}</div>
			</details>
			{#if notice}<p class="notice" role="status">{notice}</p>{/if}{#if error}<p class="error" role="alert"><TriangleAlert size={15} aria-hidden="true" />{error}</p>{/if}
		</section>

		<aside class="evidence-column" aria-labelledby="evaluation-evidence-title">
			<div class="section-kicker">核对</div><h2 id="evaluation-evidence-title">参考证据</h2><p class="aside-note">文献片段（{evidence.length}）</p>
			<div class="evidence-list">
				{#each evidence as item, index}<article class="evidence-card">
					<label for={`evaluation-evidence-title-${index}`}>文献标题</label><input id={`evaluation-evidence-title-${index}`} bind:value={item.document_title} disabled={!canEdit || saving || confirming || acting} />
					<label for={`evaluation-evidence-text-${index}`}>片段</label><textarea id={`evaluation-evidence-text-${index}`} bind:value={item.text} rows="6" disabled={!canEdit || saving || confirming || acting}></textarea>
					{#if canEdit}<button class="evidence-remove" type="button" aria-label={`${$t('taskDatasets.removeEvidence')} ${index + 1}`} title={$t('taskDatasets.removeEvidence')} on:click={() => evidence = evidence.filter((_, i) => i !== index)} disabled={saving || confirming || acting}><Trash2 size={15} aria-hidden="true" /></button>{/if}
				</article>{:else}<p class="missing">当前候选没有可读证据，不能确认。</p>{/each}
			</div>
			{#if canEdit}<button class="evidence-add" type="button" on:click={() => evidence = [...evidence, { document_title: '', text: '' }]} disabled={saving || confirming || acting}><Plus size={15} aria-hidden="true" />{$t('taskDatasets.addEvidence')}</button>{/if}
			{#if sample.sample.missing_reasons.length}<div class="missing-box"><strong>还需要补充</strong><ul>{#each sample.sample.missing_reasons as reason}<li>{reason}</li>{/each}</ul></div>{/if}
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
	:global(button), :global(input), :global(textarea), :global(select) { font: inherit; }
	.annotation-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 1px; background: var(--border-default); border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; }.question-column, .editor-column, .evidence-column { background: var(--surface-card); padding: 24px; min-width: 0; }.editor-column { background: var(--bg-subtle); }
	.section-kicker { color: var(--brand-primary); font-size: 11px; font-weight: 800; letter-spacing: 0; text-transform: uppercase; } h2 { margin: 5px 0 14px; color: var(--text-primary); font-size: 19px; line-height: 1.25; }.question { color: var(--text-primary); font-size: 16px; line-height: 1.65; white-space: pre-wrap; }.original-answer { margin-top: 28px; border-top: 1px solid var(--border-default); padding-top: 14px; }.original-answer summary { display: flex; align-items: center; gap: 6px; color: var(--text-secondary); cursor: pointer; font-size: 13px; font-weight: 700; }.original-answer p { color: var(--text-secondary); font-size: 14px; line-height: 1.65; white-space: pre-wrap; }.source-meta { display: flex; justify-content: space-between; gap: 8px; margin-top: 32px; padding-top: 14px; border-top: 1px solid var(--border-default); color: var(--text-secondary); font-size: 12px; }.source-meta small { color: var(--brand-primary); font-weight: 700; }
	.section-heading { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; } label { display: block; margin: 12px 0 6px; color: var(--text-secondary); font-size: 12px; font-weight: 700; } textarea, input, select { box-sizing: border-box; width: 100%; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); padding: 10px 11px; line-height: 1.55; resize: vertical; } textarea:focus, input:focus, select:focus { outline: 3px solid var(--brand-border); border-color: var(--brand-primary); } textarea:disabled, input:disabled, select:disabled { background: var(--bg-subtle); color: var(--text-secondary); }
	.status { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--border-strong); border-radius: 999px; padding: 5px 9px; color: var(--text-secondary); font-size: 12px; white-space: nowrap; }.status--confirmed { border-color: var(--brand-border); color: var(--brand-primary); background: var(--brand-soft); }.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }.actions button, .rebuild-area button, .recovery-actions button { display: inline-flex; align-items: center; gap: 7px; min-height: 36px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); padding: 7px 11px; cursor: pointer; }.actions button:hover:not(:disabled), .rebuild-area button:hover:not(:disabled), .recovery-actions button:hover:not(:disabled) { border-color: var(--brand-primary); color: var(--brand-primary); }.actions button.primary { border-color: var(--brand-primary); background: var(--brand-primary); color: white; }.actions button:disabled, .rebuild-area button:disabled, .recovery-actions button:disabled { cursor: not-allowed; opacity: .48; }.draft-note { color: var(--warning-text); font-size: 13px; }.rebuild-area { margin-top: 22px; border-top: 1px solid var(--border-default); padding-top: 10px; }.recovery-actions { display: flex; gap: 8px; margin-top: 12px; }.notice { margin: 14px 0 0; color: var(--brand-primary); font-size: 13px; }.error { display: flex; gap: 7px; align-items: flex-start; margin: 14px 0 0; color: var(--danger-text); font-size: 13px; }.aside-note { margin: -4px 0 18px; color: var(--text-secondary); font-size: 12px; line-height: 1.55; }.evidence-list { display: grid; gap: 14px; }.evidence-card { border-left: 3px solid var(--brand-primary); padding-left: 12px; }.evidence-card label { margin-top: 0; }.evidence-card textarea { min-height: 120px; }.missing, .missing-box { color: var(--warning-text); font-size: 13px; line-height: 1.55; }.missing-box { margin-top: 16px; border: 1px solid var(--warning-border); border-radius: 6px; background: var(--warning-bg); padding: 11px 12px; }.missing-box ul { margin: 7px 0 0; padding-left: 18px; }.empty { display: grid; justify-items: center; padding: 72px 24px; border: 1px dashed var(--border-strong); border-radius: 8px; background: var(--surface-card); color: var(--text-secondary); text-align: center; }.empty h2 { margin-bottom: 5px; }.empty p { margin: 0; max-width: 380px; line-height: 1.6; }

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
</style>
