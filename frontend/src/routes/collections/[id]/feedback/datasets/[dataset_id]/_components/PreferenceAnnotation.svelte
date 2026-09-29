<script lang="ts">
	import { Check, ChevronDown, FileText, RotateCcw, Save, ShieldCheck, Trash2, TriangleAlert } from '@lucide/svelte';
	import { createEventDispatcher } from 'svelte';
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
		confirm: { next: boolean };
		action: { action: DatasetSampleAction; reason?: string };
	}>();

	let loadedRevisionId = '';
	let responseA = '';
	let responseB = '';
	let humanPreference: PreferenceChoice | null = null;
	let evidence: Array<{ document_title: string; text: string }> = [];
	let rebuildReason = '';
	const preferenceOptions: Array<[PreferenceChoice, string]> = [
		['a', 'A 更好'],
		['b', 'B 更好'],
		['tie', '相当'],
		['unclear', '无法判断']
	];

	$: if (sample?.current_revision?.revision_id && sample.current_revision.revision_id !== loadedRevisionId) {
		loadedRevisionId = sample.current_revision.revision_id;
		const content = sample.current_revision.content as PreferenceRevisionContent;
		responseA = content.response_a;
		responseB = content.response_b;
		humanPreference = content.human_preference;
		evidence = content.evidence.map((item) => ({ ...item }));
	}

	$: currentRevision = sample?.current_revision ?? null;
	$: currentContent = currentRevision?.content as PreferenceRevisionContent | undefined;
	$: draftChanged = Boolean(currentContent && (
		responseA.trim() !== currentContent.response_a ||
		responseB.trim() !== currentContent.response_b ||
		humanPreference !== currentContent.human_preference ||
		JSON.stringify(evidence) !== JSON.stringify(currentContent.evidence)
	));
	$: canEdit = sample?.sample.status === 'needs_confirmation' || sample?.sample.status === 'confirmed';
	$: canConfirm = Boolean(
		currentRevision &&
		sample?.sample.status === 'needs_confirmation' &&
		!draftChanged &&
		humanPreference &&
		responseA.trim() &&
		responseB.trim() &&
		responseA.trim() !== responseB.trim() &&
		!saving && !confirming && !acting
	);

	function content(): PreferenceRevisionContent | null {
		if (!currentContent) return null;
		return {
			schema_version: 'literature-preference.v1',
			messages: currentContent.messages,
			context: currentContent.context,
			response_a: responseA.trim(),
			response_b: responseB.trim(),
			suggested_preference: currentContent.suggested_preference,
			rationale: currentContent.rationale,
			evidence: evidence.map((item) => ({ document_title: item.document_title.trim(), text: item.text.trim() })),
			human_preference: humanPreference
		};
	}

	function save() {
		const next = content();
		if (!next || !next.response_a || !next.response_b || next.response_a === next.response_b || next.evidence.some((item) => !item.document_title || !item.text)) return;
		dispatch('save', { content: next });
	}

	function act(action: DatasetSampleAction) {
		if (acting || saving || confirming) return;
		if (action === 'rebuild' && !rebuildReason.trim()) return;
		dispatch('action', { action, reason: rebuildReason.trim() || undefined });
	}
</script>

{#if !sample}
	<section class="empty"><FileText size={28} aria-hidden="true" /><h2>选择一个样本</h2><p>左侧队列中的候选会在这里显示同一问题下的两个回答。</p></section>
{:else}
	<div class="annotation-grid">
		<section class="question-column" aria-labelledby="preference-question-title">
			<div class="section-kicker">输入条件</div>
			<h2 id="preference-question-title">研究问题</h2>
			<p class="question">{sample.source_case.question || '暂无可读问题'}</p>
			<details class="original-answer"><summary><ChevronDown size={15} aria-hidden="true" />原始回答</summary><p>{sample.source_case.answer || '暂无原始回答'}</p></details>
			<div class="source-meta"><span>建议偏好仅供参考</span><small>{currentContent?.suggested_preference ?? '未提供'}</small></div>
		</section>

		<section class="editor-column" aria-labelledby="preference-answer-title">
			<div class="section-heading"><div><div class="section-kicker">人工选择</div><h2 id="preference-answer-title">回答对照</h2></div>{#if sample.sample.status === 'confirmed'}<span class="status status--confirmed"><ShieldCheck size={14} aria-hidden="true" />已确认</span>{:else}<span class="status">{sample.sample.status === 'needs_confirmation' ? '待确认' : sample.sample.status === 'needs_input' ? '待补充' : sample.sample.status === 'build_failed' ? '构建失败' : sample.sample.status === 'discarded' ? '已丢弃' : '构建中'}</span>{/if}</div>
			{#if currentRevision}
				<div class="response-grid">
					<label><span>回答 A</span><textarea aria-label="回答 A" bind:value={responseA} rows="8" disabled={!canEdit || saving || confirming || acting}></textarea></label>
					<label><span>回答 B</span><textarea aria-label="回答 B" bind:value={responseB} rows="8" disabled={!canEdit || saving || confirming || acting}></textarea></label>
				</div>
				<fieldset class="choice-field"><legend>哪一个回答更好？</legend><div class="choice-grid">
					{#each preferenceOptions as option}
						<label class:selected={humanPreference === option[0]}><input type="radio" name="preference-choice" value={option[0]} bind:group={humanPreference} disabled={!canEdit || saving || confirming || acting} /><span>{option[1]}</span></label>
					{/each}
				</div></fieldset>
			{:else}<p class="missing">当前还没有完整的回答对。请补充输入条件后重新构建。</p>{/if}
			{#if canEdit}<div class="actions"><button class="primary" type="button" on:click={save} disabled={saving || confirming || acting || !draftChanged || !responseA.trim() || !responseB.trim() || responseA.trim() === responseB.trim()}><Save size={16} aria-hidden="true" />{saving ? '保存中…' : '保存修改'}</button><button type="button" on:click={() => dispatch('confirm', { next: false })} disabled={!canConfirm}><Check size={16} aria-hidden="true" />{confirming ? '确认中…' : '确认样本'}</button><button type="button" on:click={() => dispatch('confirm', { next: true })} disabled={!canConfirm}>确认并下一条</button></div>{/if}
			{#if draftChanged}<p class="draft-note" role="status">有未保存的修改，保存后才能确认。</p>{/if}
			{#if sample.sample.status === 'needs_confirmation' || sample.sample.status === 'confirmed' || sample.sample.status === 'needs_input'}<div class="rebuild-area"><label for="preference-rebuild-reason">退回意见</label><textarea id="preference-rebuild-reason" bind:value={rebuildReason} rows="3" maxlength="2000" placeholder="说明应核对的条件或缺失来源" disabled={acting}></textarea><button type="button" on:click={() => act('rebuild')} disabled={acting || saving || confirming || !rebuildReason.trim()}><RotateCcw size={16} aria-hidden="true" />退回重建</button></div>{/if}
			<div class="recovery-actions">{#if sample.sample.status === 'build_failed'}<button type="button" on:click={() => act('retry')} disabled={acting}><RotateCcw size={16} aria-hidden="true" />重试构建</button>{/if}{#if sample.sample.status === 'discarded'}<button type="button" on:click={() => act('restore')} disabled={acting}><RotateCcw size={16} aria-hidden="true" />恢复样本</button>{:else}<button type="button" on:click={() => act('discard')} disabled={acting || saving || confirming}><Trash2 size={16} aria-hidden="true" />丢弃样本</button>{/if}</div>
			{#if notice}<p class="notice" role="status">{notice}</p>{/if}{#if error}<p class="error" role="alert"><TriangleAlert size={15} aria-hidden="true" />{error}</p>{/if}
		</section>

		<aside class="evidence-column" aria-labelledby="preference-evidence-title"><div class="section-kicker">核对</div><h2 id="preference-evidence-title">共同证据</h2><p class="aside-note">两个回答必须使用同一问题、上下文和可读证据；内部来源编号不会进入训练内容。</p><div class="evidence-list">{#each evidence as item, index}<article class="evidence-card"><label for={`preference-evidence-title-${index}`}>文献标题</label><input id={`preference-evidence-title-${index}`} bind:value={item.document_title} disabled={!canEdit || saving || confirming || acting} /><label for={`preference-evidence-text-${index}`}>片段</label><textarea id={`preference-evidence-text-${index}`} bind:value={item.text} rows="6" disabled={!canEdit || saving || confirming || acting}></textarea></article>{:else}<p class="missing">当前候选没有可读证据，不能确认。</p>{/each}</div>{#if sample.sample.missing_reasons.length}<div class="missing-box"><strong>还需要补充</strong><ul>{#each sample.sample.missing_reasons as reason}<li>{reason}</li>{/each}</ul></div>{/if}</aside>
	</div>
{/if}

<style>
	:global(button), :global(input), :global(textarea) { font: inherit; }
	.annotation-grid { display: grid; grid-template-columns: minmax(190px, .72fr) minmax(390px, 1.5fr) minmax(250px, .95fr); gap: 1px; background: #dbe3ec; border: 1px solid #dbe3ec; border-radius: 10px; overflow: hidden; }
	.question-column, .editor-column, .evidence-column { background: #fff; padding: 24px; min-width: 0; }.editor-column { background: #fbfcfe; }
	.section-kicker { color: #0f766e; font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; } h2 { margin: 5px 0 14px; color: #172033; font-size: 19px; line-height: 1.25; }.question { color: #172033; font-size: 16px; line-height: 1.65; white-space: pre-wrap; }
	.original-answer { margin-top: 28px; border-top: 1px solid #e7edf3; padding-top: 14px; }.original-answer summary { display: flex; align-items: center; gap: 6px; color: #506176; cursor: pointer; font-size: 13px; font-weight: 700; }.original-answer p { color: #5b687a; font-size: 14px; line-height: 1.65; white-space: pre-wrap; }.source-meta { display: flex; justify-content: space-between; gap: 8px; margin-top: 32px; padding-top: 14px; border-top: 1px solid #e7edf3; color: #7b8796; font-size: 12px; }.source-meta small { color: #0f766e; font-weight: 700; }
	.section-heading { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; } label { display: block; margin: 12px 0 6px; color: #536174; font-size: 12px; font-weight: 700; } textarea, input { box-sizing: border-box; width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; color: #172033; padding: 10px 11px; line-height: 1.55; resize: vertical; } textarea:focus, input:focus { outline: 3px solid #99f6e4; border-color: #0f766e; } textarea:disabled, input:disabled { background: #f1f5f9; color: #526174; }
	.status { display: inline-flex; align-items: center; gap: 5px; border: 1px solid #e2e8f0; border-radius: 999px; padding: 5px 9px; color: #64748b; font-size: 12px; white-space: nowrap; }.status--confirmed { border-color: #99f6e4; color: #0f766e; background: #f0fdfa; }.response-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }.response-grid textarea { min-height: 170px; }.choice-field { border: 0; margin: 18px 0 0; padding: 0; }.choice-field legend { color: #536174; font-size: 12px; font-weight: 700; }.choice-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; margin-top: 8px; }.choice-grid label { display: flex; align-items: center; justify-content: center; gap: 6px; min-height: 38px; margin: 0; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; color: #40506a; cursor: pointer; }.choice-grid label.selected { border-color: #0f766e; background: #f0fdfa; color: #0f766e; }.choice-grid input { width: auto; }
	.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }.actions button, .rebuild-area button, .recovery-actions button { display: inline-flex; align-items: center; gap: 7px; min-height: 36px; border: 1px solid #b8c4d3; border-radius: 6px; background: #fff; color: #304057; padding: 7px 11px; cursor: pointer; }.actions button:hover:not(:disabled), .rebuild-area button:hover:not(:disabled), .recovery-actions button:hover:not(:disabled) { border-color: #0f766e; color: #0f766e; }.actions button.primary { border-color: #0f766e; background: #0f766e; color: #fff; }.actions button:disabled, .rebuild-area button:disabled, .recovery-actions button:disabled { cursor: not-allowed; opacity: .48; }.draft-note { color: #9a6700; font-size: 13px; }.rebuild-area { margin-top: 22px; border-top: 1px solid #e7edf3; padding-top: 10px; }.recovery-actions { display: flex; gap: 8px; margin-top: 12px; }.notice { margin: 14px 0 0; color: #0f766e; font-size: 13px; }.error { display: flex; gap: 7px; align-items: flex-start; margin: 14px 0 0; color: #b42318; font-size: 13px; }.aside-note { margin: -4px 0 18px; color: #68778a; font-size: 12px; line-height: 1.55; }.evidence-list { display: grid; gap: 14px; }.evidence-card { border-left: 3px solid #0f766e; padding-left: 12px; }.evidence-card label { margin-top: 0; }.evidence-card textarea { min-height: 120px; }.missing, .missing-box { color: #a15c00; font-size: 13px; line-height: 1.55; }.missing-box { margin-top: 16px; border: 1px solid #fed7aa; border-radius: 6px; background: #fff7ed; padding: 11px 12px; }.missing-box ul { margin: 7px 0 0; padding-left: 18px; }.empty { display: grid; justify-items: center; padding: 72px 24px; border: 1px dashed #cbd5e1; border-radius: 10px; background: #fff; color: #64748b; text-align: center; }.empty h2 { margin-bottom: 5px; }.empty p { margin: 0; max-width: 380px; line-height: 1.6; }
	@media (max-width: 1080px) { .annotation-grid { grid-template-columns: minmax(180px, .7fr) minmax(320px, 1.3fr); } .evidence-column { grid-column: 1 / -1; border-top: 1px solid #dbe3ec; } .evidence-list { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
	@media (max-width: 760px) { .response-grid, .choice-grid { grid-template-columns: 1fr 1fr; } }
	@media (max-width: 680px) { .annotation-grid { display: block; } .question-column, .editor-column, .evidence-column { padding: 19px; } .evidence-column { border-top: 1px solid #dbe3ec; } .evidence-list { grid-template-columns: 1fr; } .response-grid, .choice-grid { grid-template-columns: 1fr; } .actions button { flex: 1 1 auto; justify-content: center; } }
</style>
