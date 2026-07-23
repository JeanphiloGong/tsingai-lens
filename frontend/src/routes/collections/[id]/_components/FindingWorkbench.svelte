<script lang="ts">
	import { resolve } from '$app/paths';
	import { errorMessage } from '../../../_shared/api';
	import {
		createFindingFeedback,
		type FindingFeedbackIssueType,
		type FindingFeedbackStatus,
		type ObjectiveEvidence,
		type ObjectiveFinding
	} from '../../../_shared/researchView';

	export let finding: ObjectiveFinding;
	export let evidence: ObjectiveEvidence[] = [];
	export let collectionId = '';

	let feedbackOpen = false;
	let feedbackStatus: FindingFeedbackStatus = 'correct';
	let feedbackIssue: FindingFeedbackIssueType = 'none';
	let feedbackNote = '';
	let feedbackSaving = false;
	let feedbackMessage = '';
	let feedbackError = '';

	const feedbackStatuses: Array<{ value: FindingFeedbackStatus; label: string }> = [
		{ value: 'correct', label: '正确' },
		{ value: 'partial', label: '部分正确' },
		{ value: 'incorrect', label: '不正确' },
		{ value: 'unclear', label: '暂不确定' }
	];
	const feedbackIssues: Array<{ value: FindingFeedbackIssueType; label: string }> = [
		{ value: 'none', label: '无问题' },
		{ value: 'wrong_variable', label: '变量错误' },
		{ value: 'wrong_outcome', label: '结果错误' },
		{ value: 'wrong_direction', label: '方向错误' },
		{ value: 'wrong_context', label: '适用条件错误' },
		{ value: 'wrong_relation', label: '关系错误' },
		{ value: 'evidence_not_grounded', label: '证据不支持' },
		{ value: 'missing_evidence', label: '缺少证据' },
		{ value: 'insufficient_evidence', label: '证据不足' },
		{ value: 'overclaim', label: '结论过度推广' },
		{ value: 'unclear_statement', label: '表述不清' },
		{ value: 'other', label: '其他' }
	];

	$: if (feedbackStatus === 'correct') feedbackIssue = 'none';

	function sourceHref(item: ObjectiveEvidence) {
		const base = resolve('/collections/[id]/documents/[document_id]', {
			id: collectionId,
			document_id: item.document_id
		});
		const returnTo = resolve('/collections/[id]/objectives/[objective_id]', {
			id: collectionId,
			objective_id: finding.objective_id
		});
		const params = new URLSearchParams({
			view: 'parsed-paper',
			source_ref: item.source_ref
		});
		if (item.page_numbers[0]) params.set('page', String(item.page_numbers[0]));
		params.set('quote', item.source_excerpt);
		params.set('return_to', returnTo);
		return `${base}?${params.toString()}`;
	}

	function displayValue(value: unknown) {
		if (value === null || value === undefined || value === '') return '-';
		if (typeof value === 'string' || typeof value === 'number') return String(value);
		return JSON.stringify(value);
	}

	async function submitFeedback() {
		feedbackSaving = true;
		feedbackError = '';
		feedbackMessage = '';
		try {
			await createFindingFeedback(collectionId, finding.objective_id, finding.finding_id, {
				analysis_version: finding.analysis_version,
				review_status: feedbackStatus,
				issue_type: feedbackIssue,
				note: feedbackNote.trim() || null
			});
			feedbackMessage = '反馈已记录。';
			feedbackNote = '';
		} catch (err) {
			feedbackError = errorMessage(err);
		} finally {
			feedbackSaving = false;
		}
	}
</script>

<article class="finding-detail">
	<header>
		<div>
			<span>{finding.finding_level === 'cross_paper' ? '跨文献 Finding' : '单篇文献 Finding'}</span>
			<h2>{finding.statement}</h2>
		</div>
		<button
			class="btn btn--ghost btn--small"
			type="button"
			on:click={() => (feedbackOpen = !feedbackOpen)}
		>
			{feedbackOpen ? '关闭反馈' : '反馈'}
		</button>
	</header>

	<div class="metrics" aria-label="Finding 证据概览">
		<div><span>证据强度</span><strong>{finding.evidence_strength}</strong></div>
		<div><span>文献数</span><strong>{finding.paper_count}</strong></div>
		<div><span>泛化状态</span><strong>{finding.generalization_status}</strong></div>
		<div><span>置信度</span><strong>{Math.round(finding.confidence * 100)}%</strong></div>
	</div>

	{#if feedbackOpen}
		<form class="feedback" on:submit|preventDefault={submitFeedback}>
			<div>
				<label for="feedback-status">判断</label>
				<select id="feedback-status" bind:value={feedbackStatus}>
					{#each feedbackStatuses as option}
						<option value={option.value}>{option.label}</option>
					{/each}
				</select>
			</div>
			<div>
				<label for="feedback-issue">问题类型</label>
				<select
					id="feedback-issue"
					bind:value={feedbackIssue}
					disabled={feedbackStatus === 'correct'}
				>
					{#each feedbackIssues as option}
						<option value={option.value}>{option.label}</option>
					{/each}
				</select>
			</div>
			<label class="feedback-note" for="feedback-note">
				<span>说明</span>
				<textarea id="feedback-note" rows="3" bind:value={feedbackNote}></textarea>
			</label>
			<button class="btn btn--primary btn--small" type="submit" disabled={feedbackSaving}>
				{feedbackSaving ? '提交中...' : '提交反馈'}
			</button>
			{#if feedbackMessage}<p class="success" role="status">{feedbackMessage}</p>{/if}
			{#if feedbackError}<p class="error" role="alert">{feedbackError}</p>{/if}
		</form>
	{/if}

	<section>
		<h3>研究关系</h3>
		{#if finding.relations.length}
			<ol class="relations">
				{#each finding.relations as relation}
					<li>
						<strong>{relation.source_term}</strong>
						<span>{relation.relation_type}</span>
						<strong>{relation.target_term}</strong>
						<small
							>{relation.assertion_strength}{relation.direction
								? ` · ${relation.direction}`
								: ''}</small
						>
					</li>
				{/each}
			</ol>
		{:else}
			<p class="empty">当前 Finding 没有可展示的关系。</p>
		{/if}
	</section>

	<section>
		<h3>适用条件</h3>
		<div class="context-grid">
			<div>
				<span>材料体系</span>
				<p>{displayValue(finding.context.material_system)}</p>
			</div>
			<div>
				<span>样品状态</span>
				<p>{displayValue(finding.context.sample_state)}</p>
			</div>
			<div>
				<span>工艺条件</span>
				<p>{displayValue(finding.context.process_conditions)}</p>
			</div>
			<div>
				<span>测试条件</span>
				<p>{displayValue(finding.context.test_conditions)}</p>
			</div>
		</div>
		{#if finding.context.limitations.length}
			<ul class="limitations">
				{#each finding.context.limitations as limitation}<li>{limitation}</li>{/each}
			</ul>
		{/if}
	</section>

	<section>
		<div class="section-heading">
			<h3>原文证据</h3>
			<span>{evidence.length} 条</span>
		</div>
		{#if evidence.length}
			<div class="evidence-list">
				{#each evidence as item (item.evidence_id)}
					<article class="evidence-item">
						<div class="evidence-meta">
							<span>{item.evidence_role}</span>
							<span>{item.source_kind}</span>
							<span
								>{item.page_numbers.length ? `p.${item.page_numbers.join(', ')}` : '页码未知'}</span
							>
							<a href={sourceHref(item)}>打开原文</a>
						</div>
						<blockquote>{item.source_excerpt}</blockquote>
						{#if item.interpretation}<p>{item.interpretation}</p>{/if}
					</article>
				{/each}
			</div>
		{:else}
			<p class="empty">该 Finding 没有返回可审计的原文证据。</p>
		{/if}
	</section>

	<details class="derivation">
		<summary>推导审计</summary>
		<p>{finding.derivation.rationale}</p>
		<dl>
			<div>
				<dt>比较状态</dt>
				<dd>{finding.derivation.comparison_status}</dd>
			</div>
			<div>
				<dt>贡献文献</dt>
				<dd>{finding.derivation.contributing_document_ids.join(', ')}</dd>
			</div>
		</dl>
	</details>
</article>

<style>
	.finding-detail {
		display: grid;
		gap: 24px;
	}
	header,
	.section-heading {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 16px;
	}
	header span,
	.section-heading span,
	.metrics span,
	.context-grid span,
	.evidence-meta {
		color: var(--text-secondary);
		font-size: 12px;
	}
	h2,
	h3,
	p {
		margin: 0;
	}
	h2 {
		margin-top: 5px;
		max-width: 900px;
		font-size: 22px;
		line-height: 1.45;
	}
	h3 {
		font-size: 15px;
		margin-bottom: 12px;
	}
	.metrics {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		border-block: 1px solid var(--border-default);
	}
	.metrics div {
		padding: 12px 14px;
		display: grid;
		gap: 3px;
		border-right: 1px solid var(--border-default);
	}
	.metrics div:last-child {
		border-right: 0;
	}
	.feedback {
		display: grid;
		grid-template-columns: 180px 220px 1fr auto;
		align-items: end;
		gap: 12px;
		padding: 16px;
		border: 1px solid var(--border-default);
		background: var(--surface-subtle);
	}
	.feedback label,
	.feedback > div {
		display: grid;
		gap: 5px;
		font-size: 12px;
	}
	.feedback select,
	.feedback textarea {
		width: 100%;
		border: 1px solid var(--border-default);
		background: var(--surface-primary);
		color: var(--text-primary);
		padding: 8px;
	}
	.feedback-note {
		min-width: 220px;
	}
	.feedback .success,
	.feedback .error {
		grid-column: 1 / -1;
	}
	.success {
		color: #256346;
	}
	.error {
		color: var(--danger, #b42318);
	}
	.relations {
		margin: 0;
		padding: 0;
		list-style: none;
		border-top: 1px solid var(--border-default);
	}
	.relations li {
		display: grid;
		grid-template-columns: minmax(140px, 1fr) minmax(120px, auto) minmax(140px, 1fr) auto;
		gap: 12px;
		align-items: center;
		padding: 12px 0;
		border-bottom: 1px solid var(--border-default);
	}
	.relations small {
		color: var(--text-secondary);
	}
	.context-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1px;
		background: var(--border-default);
	}
	.context-grid > div {
		background: var(--surface-primary);
		padding: 12px;
		min-width: 0;
	}
	.context-grid p {
		margin-top: 5px;
		overflow-wrap: anywhere;
	}
	.limitations {
		margin: 10px 0 0;
		color: var(--text-secondary);
	}
	.evidence-list {
		display: grid;
		gap: 10px;
	}
	.evidence-item {
		border-left: 3px solid #3a7d5d;
		padding: 12px 14px;
		background: var(--surface-subtle);
	}
	.evidence-meta {
		display: flex;
		gap: 10px;
		align-items: center;
		flex-wrap: wrap;
	}
	.evidence-meta a {
		margin-left: auto;
		color: var(--accent);
	}
	blockquote {
		margin: 10px 0 0;
		padding: 0;
		line-height: 1.65;
		white-space: pre-wrap;
	}
	.evidence-item > p {
		margin-top: 8px;
		color: var(--text-secondary);
	}
	.empty {
		color: var(--text-secondary);
		padding: 16px 0;
	}
	.derivation {
		border-top: 1px solid var(--border-default);
		padding-top: 12px;
	}
	.derivation summary {
		cursor: pointer;
		font-weight: 600;
	}
	.derivation p {
		margin-top: 12px;
		line-height: 1.6;
	}
	.derivation dl {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 12px;
	}
	.derivation dt {
		color: var(--text-secondary);
		font-size: 12px;
	}
	.derivation dd {
		margin: 4px 0 0;
	}
	@media (max-width: 820px) {
		.metrics,
		.context-grid {
			grid-template-columns: 1fr 1fr;
		}
		.feedback {
			grid-template-columns: 1fr;
			align-items: stretch;
		}
		.relations li {
			grid-template-columns: 1fr;
			gap: 4px;
		}
		.evidence-meta a {
			margin-left: 0;
		}
	}
</style>
