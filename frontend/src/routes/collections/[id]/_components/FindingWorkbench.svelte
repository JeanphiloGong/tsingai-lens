<script lang="ts">
	import { resolve } from '$app/paths';
	import { errorMessage } from '../../../_shared/api';
	import {
		createFindingFeedback,
		fetchFindingFeedback,
		type FindingFeedback,
		type FindingFeedbackIssueType,
		type FindingFeedbackStatus,
		type ObjectiveEvidence,
		type ObjectiveFinding,
		type ObjectiveFindingPaperContribution,
		type ObjectiveScientificAttribute
	} from '../../../_shared/researchView';

	export let finding: ObjectiveFinding;
	export let evidence: ObjectiveEvidence[] = [];
	export let collectionId = '';

	let feedbackOpen = false;
	let feedbackStatus: FindingFeedbackStatus = 'correct';
	let feedbackIssue: FindingFeedbackIssueType = 'none';
	let feedbackNote = '';
	let feedbackSaving = false;
	let feedbackLoading = false;
	let feedbackMessage = '';
	let feedbackError = '';
	let feedbackFindingKey = '';
	let feedbackRequestSequence = 0;

	const feedbackStatuses: Array<{ value: FindingFeedbackStatus; label: string }> = [
		{ value: 'correct', label: '正确' },
		{ value: 'partial', label: '部分正确' },
		{ value: 'incorrect', label: '不正确' },
		{ value: 'unclear', label: '暂不确定' }
	];
	const feedbackIssues: Array<{ value: FindingFeedbackIssueType; label: string }> = [
		{ value: 'none', label: '无问题' },
		{ value: 'wrong_factor', label: '影响因素错误' },
		{ value: 'wrong_outcome', label: '结果错误' },
		{ value: 'wrong_direction', label: '方向错误' },
		{ value: 'wrong_context', label: '适用条件错误' },
		{ value: 'wrong_mechanism', label: '机制错误' },
		{ value: 'wrong_attribution', label: '归因错误' },
		{ value: 'wrong_synthesis', label: '跨文献综合错误' },
		{ value: 'evidence_not_grounded', label: '证据不支持' },
		{ value: 'missing_evidence', label: '缺少证据' },
		{ value: 'insufficient_evidence', label: '证据不足' },
		{ value: 'overclaim', label: '结论过度推广' },
		{ value: 'unclear_statement', label: '表述不清' },
		{ value: 'other', label: '其他' }
	];

	$: if (feedbackStatus === 'correct') feedbackIssue = 'none';
	$: if (
		(feedbackStatus === 'partial' || feedbackStatus === 'incorrect') &&
		feedbackIssue === 'none'
	)
		feedbackIssue = 'other';
	$: findingKey = `${finding.objective_id}:${finding.analysis_version}:${finding.finding_id}`;
	$: if (findingKey !== feedbackFindingKey) {
		feedbackFindingKey = findingKey;
		feedbackRequestSequence += 1;
		feedbackOpen = false;
		resetFeedback();
	}
	$: directPaperCount = finding.paper_contributions.filter(
		(item) => item.supporting_evidence_ids.length || item.contradicting_evidence_ids.length
	).length;
	$: contextGroups = [
		{ label: '材料体系', items: finding.scientific_context.material },
		{ label: '样品状态', items: finding.scientific_context.sample },
		{ label: '工艺条件', items: finding.scientific_context.process },
		{ label: '测试条件', items: finding.scientific_context.test }
	];

	function sourceHref(item: ObjectiveEvidence) {
		const base = resolve('/collections/[id]/documents/[document_id]', {
			id: collectionId,
			document_id: item.document_id
		});
		const objectiveHref = resolve('/collections/[id]/objectives/[objective_id]', {
			id: collectionId,
			objective_id: finding.objective_id
		});
		const returnTo = `${objectiveHref}?${new URLSearchParams({ finding_id: finding.finding_id })}`;
		const params = new URLSearchParams({
			view: 'parsed-paper',
			evidence_id: item.evidence_id,
			source_ref: item.source_ref,
			quote: item.source_excerpt,
			return_to: returnTo
		});
		if (item.page_numbers[0]) params.set('page', String(item.page_numbers[0]));
		return `${base}?${params.toString()}`;
	}

	function attributes(items: ObjectiveScientificAttribute[]) {
		return items.map((item) => `${item.name}: ${item.value}${item.unit ? ` ${item.unit}` : ''}`);
	}

	function evidenceFor(contribution: ObjectiveFindingPaperContribution) {
		const ids = new Set([
			...contribution.supporting_evidence_ids,
			...contribution.contradicting_evidence_ids,
			...contribution.context_evidence_ids,
			...contribution.condition_boundary_evidence_ids
		]);
		return evidence.filter((item) => ids.has(item.evidence_id));
	}

	function evidenceBindings(
		contribution: ObjectiveFindingPaperContribution,
		evidenceId: string
	): string[] {
		const labels: string[] = [];
		if (contribution.supporting_evidence_ids.includes(evidenceId)) labels.push('支持结果');
		if (contribution.contradicting_evidence_ids.includes(evidenceId)) labels.push('反向结果');
		if (contribution.context_evidence_ids.includes(evidenceId)) labels.push('上下文');
		if (contribution.condition_boundary_evidence_ids.includes(evidenceId)) {
			labels.push('条件边界');
		}
		return labels;
	}

	function paperLabel(index: number, paperEvidence: ObjectiveEvidence[]) {
		const pages = paperEvidence.flatMap((item) => item.page_numbers);
		const firstPage = pages.length ? Math.min(...pages) : null;
		return firstPage ? `文献 ${index + 1} · p.${firstPage}` : `文献 ${index + 1}`;
	}

	function contributionStatus(status: ObjectiveFindingPaperContribution['analysis_status']) {
		if (status === 'analyzed') return '已分析';
		if (status === 'excluded') return '已排除';
		return '分析失败';
	}

	function directionLabel(value: ObjectiveFinding['direction']) {
		return {
			increase: '增加',
			decrease: '降低',
			improve: '改善',
			worsen: '恶化',
			no_change: '无变化',
			mixed: '结果不一致',
			unknown: '方向未知'
		}[value];
	}

	function assertionLabel(value: ObjectiveFinding['assertion_strength']) {
		return { causal: '因果', associative: '关联', descriptive: '描述' }[value];
	}

	function attributionLabel(value: ObjectiveFinding['attribution_scope']) {
		return {
			isolated_effect: '单变量归因',
			joint_effect: '联合变化',
			association_only: '仅关联',
			descriptive_only: '仅描述'
		}[value];
	}

	function synthesisLabel(value: ObjectiveFinding['synthesis_status']) {
		return {
			agreement: '多文献一致',
			conflict: '文献冲突',
			condition_dependent: '条件依赖',
			insufficient_confirmation: '证据待确认'
		}[value];
	}

	function evidenceRoleLabel(value: string) {
		return (
			{
				direct_result: '直接结果',
				condition_context: '条件上下文',
				mechanism_context: '机制上下文',
				baseline_context: '基线信息',
				comparison_context: '比较上下文',
				background_context: '背景信息',
				contradictory_result: '反向结果',
				irrelevant: '不相关'
			}[value] ?? value
		);
	}

	function evidenceAttributionLabel(value: ObjectiveEvidence['attribution_scope']) {
		if (value === 'not_attributable') return '不可归因';
		return attributionLabel(value);
	}

	function resetFeedback() {
		feedbackStatus = 'correct';
		feedbackIssue = 'none';
		feedbackNote = '';
		feedbackLoading = false;
		feedbackMessage = '';
		feedbackError = '';
	}

	function applyFeedback(item: FindingFeedback) {
		feedbackStatus = item.review_status;
		feedbackIssue = item.issue_type;
		feedbackNote = item.note ?? '';
	}

	async function toggleFeedback() {
		if (feedbackOpen) {
			feedbackOpen = false;
			return;
		}
		feedbackOpen = true;
		const requestSequence = ++feedbackRequestSequence;
		feedbackLoading = true;
		feedbackError = '';
		try {
			const items = await fetchFindingFeedback(
				collectionId,
				finding.objective_id,
				finding.analysis_version,
				finding.finding_id
			);
			if (requestSequence !== feedbackRequestSequence) return;
			const latest = [...items].sort((left, right) =>
				right.created_at.localeCompare(left.created_at)
			)[0];
			if (latest) applyFeedback(latest);
		} catch (err) {
			if (requestSequence === feedbackRequestSequence) feedbackError = errorMessage(err);
		} finally {
			if (requestSequence === feedbackRequestSequence) feedbackLoading = false;
		}
	}

	async function submitFeedback() {
		feedbackSaving = true;
		feedbackError = '';
		feedbackMessage = '';
		try {
			const saved = await createFindingFeedback(
				collectionId,
				finding.objective_id,
				finding.finding_id,
				{
					analysis_version: finding.analysis_version,
					review_status: feedbackStatus,
					issue_type: feedbackIssue,
					note: feedbackNote.trim() || null
				}
			);
			applyFeedback(saved);
			feedbackMessage = '反馈已记录。';
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
			<span>{directPaperCount >= 2 ? '跨文献研究发现' : '单篇直接证据'}</span>
			<h2>{finding.statement}</h2>
		</div>
		<button
			class="btn btn--ghost btn--small"
			type="button"
			aria-expanded={feedbackOpen}
			on:click={toggleFeedback}
		>
			{feedbackOpen ? '关闭反馈' : '反馈'}
		</button>
	</header>

	<section class="result-line" aria-label="Finding 核心结果">
		<div>
			<span>影响因素</span>
			<strong>{finding.factors.join(' + ')}</strong>
		</div>
		<b aria-hidden="true">→</b>
		<div>
			<span>结果</span>
			<strong>{finding.outcome}</strong>
		</div>
		<div class="direction">
			<span>方向</span>
			<strong>{directionLabel(finding.direction)}</strong>
		</div>
	</section>

	<div class="metrics" aria-label="Finding 科学判断">
		<div><span>表述强度</span><strong>{assertionLabel(finding.assertion_strength)}</strong></div>
		<div><span>归因范围</span><strong>{attributionLabel(finding.attribution_scope)}</strong></div>
		<div><span>综合状态</span><strong>{synthesisLabel(finding.synthesis_status)}</strong></div>
		<div><span>确定性</span><strong>{Math.round(finding.certainty * 100)}%</strong></div>
		<div><span>直接文献</span><strong>{directPaperCount} 篇</strong></div>
	</div>

	{#if feedbackOpen}
		<form class="feedback" aria-busy={feedbackLoading} on:submit|preventDefault={submitFeedback}>
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
						<option
							value={option.value}
							disabled={option.value === 'none' &&
								(feedbackStatus === 'partial' || feedbackStatus === 'incorrect')}
							>{option.label}</option
						>
					{/each}
				</select>
			</div>
			<label class="feedback-note" for="feedback-note">
				<span>说明</span>
				<textarea id="feedback-note" rows="3" bind:value={feedbackNote}></textarea>
			</label>
			<button
				class="btn btn--primary btn--small"
				type="submit"
				disabled={feedbackSaving || feedbackLoading}
			>
				{feedbackSaving ? '提交中...' : '提交反馈'}
			</button>
			{#if feedbackMessage}<p class="success" role="status">{feedbackMessage}</p>{/if}
			{#if feedbackError}<p class="error" role="alert">{feedbackError}</p>{/if}
		</form>
	{/if}

	<section>
		<h3>作用机制</h3>
		{#if finding.mechanisms.length}
			<ol class="mechanisms">
				{#each finding.mechanisms as mechanism}
					<li>
						<strong>{mechanism.source_term}</strong>
						<span>{mechanism.relation_type}</span>
						<strong>{mechanism.target_term}</strong>
						<small
							>{assertionLabel(mechanism.assertion_strength)}{mechanism.direction
								? ` · ${directionLabel(mechanism.direction)}`
								: ''}</small
						>
					</li>
				{/each}
			</ol>
		{:else}
			<p class="empty">未报告可由原文证据支持的作用机制。</p>
		{/if}
	</section>

	<section>
		<h3>适用条件</h3>
		<div class="context-grid">
			{#each contextGroups as group}
				<div>
					<span>{group.label}</span>
					{#if group.items.length}
						<ul>
							{#each attributes(group.items) as value}<li>{value}</li>{/each}
						</ul>
					{:else}
						<p>未报告</p>
					{/if}
				</div>
			{/each}
		</div>
		<div class="limitations">
			<strong>证据边界</strong>
			{#if finding.limitations.length}
				<ul>
					{#each finding.limitations as limitation}<li>{limitation}</li>{/each}
				</ul>
			{:else}
				<p>未报告额外限制。</p>
			{/if}
		</div>
	</section>

	<section>
		<div class="section-heading">
			<h3>文献贡献与原文证据</h3>
			<span>{evidence.length} 条证据 · {finding.paper_contributions.length} 篇文献</span>
		</div>
		<div class="paper-groups">
			{#each finding.paper_contributions as contribution, index}
				{@const paperEvidence = evidenceFor(contribution)}
				<section class="paper-group">
					<header>
						{#if paperEvidence[0]}
							<a href={sourceHref(paperEvidence[0])}>{paperLabel(index, paperEvidence)}</a>
						{:else}
							<strong>{paperLabel(index, paperEvidence)}</strong>
						{/if}
						<span
							>{contributionStatus(contribution.analysis_status)} · {paperEvidence.length} 条证据</span
						>
					</header>
					{#if paperEvidence.length}
						<div class="evidence-list">
							{#each paperEvidence as item (item.evidence_id)}
								<article class="evidence-item">
									<div class="evidence-meta">
										{#each evidenceBindings(contribution, item.evidence_id) as binding}
											<strong>{binding}</strong>
										{/each}
										<span>{evidenceRoleLabel(item.evidence_role)}</span>
										<span>{evidenceAttributionLabel(item.attribution_scope)}</span>
										<span
											>{item.page_numbers.length
												? `p.${item.page_numbers.join(', ')}`
												: '页码未知'}</span
										>
										<a href={sourceHref(item)}>打开原文</a>
									</div>
									<blockquote>{item.source_excerpt}</blockquote>
									{#if item.reported_result}<p>{item.reported_result.result_text}</p>{/if}
								</article>
							{/each}
						</div>
					{:else}
						<p class="empty">该文献未绑定到此 Finding 的可审计证据。</p>
					{/if}
				</section>
			{/each}
		</div>
	</section>
</article>

<style>
	.finding-detail {
		display: grid;
		gap: 24px;
	}
	header,
	.section-heading,
	.paper-group > header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 16px;
	}
	.finding-detail > header > button {
		flex: 0 0 auto;
		white-space: nowrap;
	}
	header span,
	.section-heading span,
	.metrics span,
	.result-line span,
	.context-grid > div > span,
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
	.result-line {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) minmax(120px, auto);
		align-items: center;
		gap: 18px;
		padding: 16px 0;
		border-block: 1px solid var(--border-default);
	}
	.result-line div {
		display: grid;
		gap: 4px;
		min-width: 0;
	}
	.result-line strong {
		overflow-wrap: anywhere;
	}
	.result-line b {
		color: var(--text-secondary);
		font-size: 20px;
	}
	.metrics {
		display: grid;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		border-bottom: 1px solid var(--border-default);
	}
	.metrics div {
		padding: 0 14px 12px;
		display: grid;
		gap: 3px;
		border-right: 1px solid var(--border-default);
	}
	.metrics div:first-child {
		padding-left: 0;
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
	.mechanisms {
		margin: 0;
		padding: 0;
		list-style: none;
		border-top: 1px solid var(--border-default);
	}
	.mechanisms li {
		display: grid;
		grid-template-columns: minmax(140px, 1fr) minmax(120px, auto) minmax(140px, 1fr) auto;
		gap: 12px;
		align-items: center;
		padding: 12px 0;
		border-bottom: 1px solid var(--border-default);
	}
	.mechanisms small {
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
	.context-grid ul,
	.limitations ul {
		margin: 6px 0 0;
		padding-left: 18px;
	}
	.context-grid p {
		margin-top: 6px;
		color: var(--text-secondary);
	}
	.limitations {
		margin-top: 12px;
		padding-left: 12px;
		border-left: 3px solid #a97022;
	}
	.limitations p {
		margin-top: 6px;
		color: var(--text-secondary);
	}
	.paper-groups {
		border-top: 1px solid var(--border-default);
	}
	.paper-group {
		padding: 14px 0 18px;
		border-bottom: 1px solid var(--border-default);
	}
	.paper-group > header {
		margin-bottom: 10px;
	}
	.paper-group > header > a {
		color: var(--accent);
		font-weight: 600;
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
	.evidence-meta strong {
		color: var(--text-primary);
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
		padding: 10px 0;
	}
	@media (max-width: 820px) {
		.result-line {
			grid-template-columns: 1fr auto 1fr;
		}
		.result-line .direction {
			grid-column: 1 / -1;
		}
		.metrics,
		.context-grid {
			grid-template-columns: 1fr 1fr;
		}
		.feedback {
			grid-template-columns: 1fr;
			align-items: stretch;
		}
		.mechanisms li {
			grid-template-columns: 1fr;
			gap: 4px;
		}
		.evidence-meta a {
			margin-left: 0;
			width: 100%;
		}
	}
</style>
