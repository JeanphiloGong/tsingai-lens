<script lang="ts">
	import { resolve } from '$app/paths';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
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
	export let documentTitles: Record<string, string> = {};

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
	].filter((group) => group.items.length > 0);
	$: comparisonRows = evidence
		.filter(
			(item) =>
				item.evidence_role === 'direct_result' || item.evidence_role === 'contradictory_result'
		)
		.map((item) => ({
			evidence: item,
			binding: directEvidenceBinding(item.evidence_id),
			variables: item.changed_variables.map((variable) => variable.name),
			baselines: item.changed_variables.map(
				(variable) =>
					formatValue(variable.baseline_value, variable.unit) ||
					item.comparison?.baseline_label ||
					'未报告'
			),
			targets: item.changed_variables.map(
				(variable) =>
					formatValue(variable.target_value, variable.unit) ||
					item.comparison?.target_label ||
					'未报告'
			),
			result: resultLabel(item),
			direction: item.reported_result ? directionLabel(item.reported_result.direction) : '方向未知',
			comparability: comparabilityLabel(item)
		}));
	$: contributionGroups = finding.paper_contributions.map((contribution) => ({
		contribution,
		paperEvidence: evidenceFor(contribution)
	}));
	$: evidencedContributionGroups = contributionGroups.filter(
		(group) => group.paperEvidence.length > 0
	);
	$: emptyContributions = contributionGroups
		.filter((group) => group.paperEvidence.length === 0)
		.map((group) => group.contribution);
	$: emptyContributionSummary = summarizeEmptyContributions(emptyContributions);

	function sourceHref(item: ObjectiveEvidence): `/collections/${string}/documents/${string}` {
		const base: `/collections/${string}/documents/${string}` = `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(item.document_id)}`;
		const objectiveHref = resolve('/collections/[id]/objectives/[objective_id]', {
			id: collectionId,
			objective_id: finding.objective_id
		});
		const returnTo = `${objectiveHref}?${new SvelteURLSearchParams({ finding_id: finding.finding_id })}`;
		const params = new SvelteURLSearchParams({
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

	function directEvidenceBinding(evidenceId: string) {
		for (const contribution of finding.paper_contributions) {
			if (contribution.supporting_evidence_ids.includes(evidenceId)) return '支持结果';
			if (contribution.contradicting_evidence_ids.includes(evidenceId)) return '反向结果';
		}
		return '未绑定';
	}

	function evidenceByIds(evidenceIds: string[]) {
		const ids = new Set(evidenceIds);
		return evidence.filter((item) => ids.has(item.evidence_id));
	}

	function paperTitle(documentId: string, index?: number) {
		const title = documentTitles[documentId]?.trim();
		if (title) return title;
		const contributionIndex =
			index ??
			evidencedContributionGroups.findIndex(
				(group) => group.contribution.document_id === documentId
			);
		return `文献 ${Math.max(contributionIndex, 0) + 1}`;
	}

	function paperLabel(
		contribution: ObjectiveFindingPaperContribution,
		index: number,
		paperEvidence: ObjectiveEvidence[]
	) {
		const pages = paperEvidence.flatMap((item) => item.page_numbers);
		const firstPage = pages.length ? Math.min(...pages) : null;
		const title = paperTitle(contribution.document_id, index);
		return firstPage ? `${title} · p.${firstPage}` : title;
	}

	function formatValue(
		value: string | number | boolean | null | undefined,
		unit: string | null | undefined
	) {
		if (value === null || value === undefined || value === '') return '';
		return `${String(value)}${unit ? ` ${unit}` : ''}`;
	}

	function resultLabel(item: ObjectiveEvidence) {
		if (!item.reported_result) return '未报告';
		const baseline = formatValue(item.reported_result.baseline_value, item.reported_result.unit);
		const target = formatValue(item.reported_result.target_value, item.reported_result.unit);
		if (baseline && target) {
			return `${item.reported_result.outcome}: ${baseline} → ${target}`;
		}
		const value = formatValue(item.reported_result.value, item.reported_result.unit);
		return `${item.reported_result.outcome}: ${value || item.reported_result.result_text}`;
	}

	function evidenceSourceLabel(item: ObjectiveEvidence) {
		const page = item.page_numbers[0];
		return page ? `${paperTitle(item.document_id)} · p.${page}` : paperTitle(item.document_id);
	}

	function comparabilityLabel(item: ObjectiveEvidence) {
		if (!item.comparison) return '可比性未报告';
		if (item.comparison.comparable) return '可直接比较';
		return item.comparison.incomparability_reasons.length
			? `不可直接比较：${item.comparison.incomparability_reasons.join('；')}`
			: '不可直接比较';
	}

	function contributionStatus(status: ObjectiveFindingPaperContribution['analysis_status']) {
		if (status === 'analyzed') return '已分析';
		if (status === 'excluded') return '已排除';
		return '分析失败';
	}

	function summarizeEmptyContributions(contributions: ObjectiveFindingPaperContribution[]) {
		if (!contributions.length) return '';
		const counts = { analyzed: 0, excluded: 0, failed: 0 };
		for (const contribution of contributions) counts[contribution.analysis_status] += 1;
		const states = [
			counts.analyzed ? `已分析但无 Evidence ${counts.analyzed} 篇` : '',
			counts.excluded ? `已排除 ${counts.excluded} 篇` : '',
			counts.failed ? `分析失败 ${counts.failed} 篇` : ''
		].filter(Boolean);
		return `另有 ${contributions.length} 篇文献未形成可审计 Evidence：${states.join('，')}。`;
	}

	function directionLabel(value: ObjectiveFinding['direction']) {
		return {
			increase: '增加',
			decrease: '降低',
			improve: '改善',
			worsen: '恶化',
			changed: '发生变化',
			no_change: '无变化',
			mixed: '结果不一致',
			unknown: '方向未知'
		}[value];
	}

	function assertionLabel(value: ObjectiveFinding['assertion_strength']) {
		return { causal: '因果', associative: '关联', descriptive: '描述' }[value];
	}

	function relationLabel(value: string) {
		return (
			{
				associated_with: '相关联',
				correlated_with: '相关',
				causes: '导致',
				affects: '影响',
				influences: '影响',
				contributes_to: '促成',
				mediates: '介导',
				mediated_by: '由中介作用连接',
				moderates: '调节',
				depends_on: '取决于'
			}[value] ?? value.replaceAll('_', ' ')
		);
	}

	function certaintyLabel(value: number) {
		if (value >= 0.8) return '较高';
		if (value >= 0.6) return '中等';
		return '较低';
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
		<div><span>证据确定性</span><strong>{certaintyLabel(finding.certainty)}</strong></div>
		<div><span>直接文献</span><strong>{directPaperCount} 篇</strong></div>
	</div>

	<section aria-labelledby="evidence-comparison-title">
		<div class="section-heading">
			<h3 id="evidence-comparison-title">证据对比</h3>
			<span>{comparisonRows.length} 条结构化 Evidence</span>
		</div>
		{#if comparisonRows.length}
			<div class="comparison-table-wrap">
				<table class="comparison-table">
					<thead>
						<tr>
							<th scope="col">文献</th>
							<th scope="col">证据关系</th>
							<th scope="col">变量</th>
							<th scope="col">参照条件</th>
							<th scope="col">比较条件</th>
							<th scope="col">报告结果</th>
							<th scope="col">方向</th>
							<th scope="col">可比性</th>
						</tr>
					</thead>
					<tbody>
						{#each comparisonRows as row, rowIndex (`${row.evidence.evidence_id}:${rowIndex}`)}
							<tr>
								<td>{paperTitle(row.evidence.document_id)}</td>
								<td>{row.binding}</td>
								<td><span class="condition-values">{row.variables.join('\n')}</span></td>
								<td><span class="condition-values">{row.baselines.join('\n')}</span></td>
								<td><span class="condition-values">{row.targets.join('\n')}</span></td>
								<td>{row.result}</td>
								<td>{row.direction}</td>
								<td>{row.comparability}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else}
			<p class="empty">当前证据没有可展示的基线、目标或测量结果。</p>
		{/if}
	</section>

	<section>
		<h3>适用条件</h3>
		{#if contextGroups.length}
			<div class="context-grid">
				{#each contextGroups as group (group.label)}
					<div>
						<span>{group.label}</span>
						<ul>
							{#each attributes(group.items) as value, attributeIndex (`${group.label}:${attributeIndex}`)}<li
								>
									{value}
								</li>{/each}
						</ul>
					</div>
				{/each}
			</div>
		{:else}
			<p class="empty">未报告共同适用条件。</p>
		{/if}
		<div class="limitations">
			<strong>分析边界</strong>
			{#if finding.limitations.length}
				<ul>
					{#each finding.limitations as limitation, limitationIndex (limitationIndex)}<li>
							{limitation}
						</li>{/each}
				</ul>
			{:else}
				<p>未识别额外分析边界。</p>
			{/if}
		</div>
	</section>

	<section>
		<h3>作用机制</h3>
		{#if finding.mechanisms.length}
			<ol class="mechanisms" aria-label="作用机制关系">
				{#each finding.mechanisms as mechanism, mechanismIndex (`${mechanism.source_term}:${mechanism.target_term}:${mechanismIndex}`)}
					{@const mechanismEvidence = evidenceByIds(mechanism.supporting_evidence_ids)}
					<li>
						<strong>{mechanism.source_term}</strong>
						<span>{relationLabel(mechanism.relation_type)}</span>
						<strong>{mechanism.target_term}</strong>
						<small
							>{assertionLabel(mechanism.assertion_strength)}{mechanism.direction
								? ` · ${directionLabel(mechanism.direction)}`
								: ''}</small
						>
						{#if mechanismEvidence.length}
							<div class="mechanism-sources" aria-label="机制支撑证据">
								{#each mechanismEvidence as item (item.evidence_id)}
									<a href={resolve(sourceHref(item))}>{evidenceSourceLabel(item)}</a>
								{/each}
							</div>
						{/if}
					</li>
				{/each}
			</ol>
		{:else}
			<p class="empty">未报告可由原文证据支持的作用机制。</p>
		{/if}
	</section>

	<section>
		<div class="section-heading">
			<h3>文献贡献与原文证据</h3>
			<span>{evidence.length} 条证据 · {evidencedContributionGroups.length} 篇文献</span>
		</div>
		{#if evidencedContributionGroups.length}
			<div class="paper-groups">
				{#each evidencedContributionGroups as group, index (group.contribution.document_id)}
					{@const contribution = group.contribution}
					{@const paperEvidence = group.paperEvidence}
					<section class="paper-group">
						<header>
							<a href={resolve(sourceHref(paperEvidence[0]))}
								>{paperLabel(contribution, index, paperEvidence)}</a
							>
							<span
								>{contributionStatus(contribution.analysis_status)} · {paperEvidence.length} 条证据</span
							>
						</header>
						<div class="evidence-list">
							{#each paperEvidence as item (item.evidence_id)}
								<article class="evidence-item">
									<div class="evidence-meta">
										{#each evidenceBindings(contribution, item.evidence_id) as binding (binding)}
											<strong>{binding}</strong>
										{/each}
										<span>{evidenceRoleLabel(item.evidence_role)}</span>
										<span>{evidenceAttributionLabel(item.attribution_scope)}</span>
										<span
											>{item.page_numbers.length
												? `p.${item.page_numbers.join(', ')}`
												: '页码未知'}</span
										>
										<a href={resolve(sourceHref(item))}>打开原文</a>
									</div>
									<blockquote>{item.source_excerpt}</blockquote>
								</article>
							{/each}
						</div>
					</section>
				{/each}
			</div>
		{:else}
			<p class="empty">当前 Finding 没有可审计的原文 Evidence。</p>
		{/if}
		{#if emptyContributionSummary}
			<p class="empty-contribution-summary">{emptyContributionSummary}</p>
		{/if}
	</section>

	<section class="review-section" aria-labelledby="finding-review-title">
		<div class="section-heading">
			<div>
				<h3 id="finding-review-title">专家审阅</h3>
				<p>记录这条 Finding 的科学准确性和证据问题。</p>
			</div>
			<button
				class="btn btn--ghost btn--small"
				type="button"
				aria-expanded={feedbackOpen}
				aria-controls="finding-feedback-form"
				on:click={toggleFeedback}
			>
				{feedbackOpen ? '关闭反馈' : '反馈'}
			</button>
		</div>
		{#if feedbackOpen}
			<form
				id="finding-feedback-form"
				class="feedback"
				aria-busy={feedbackLoading}
				on:submit|preventDefault={submitFeedback}
			>
				<div>
					<label for="feedback-status">判断</label>
					<select id="feedback-status" bind:value={feedbackStatus}>
						{#each feedbackStatuses as option (option.value)}
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
						{#each feedbackIssues as option (option.value)}
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
	</section>
</article>

<style>
	.finding-detail {
		display: grid;
		gap: 24px;
		min-width: 0;
	}
	.finding-detail > section {
		min-width: 0;
	}
	header,
	.section-heading,
	.paper-group > header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 16px;
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
	.comparison-table-wrap {
		min-width: 0;
		max-width: 100%;
		overflow-x: auto;
		border-block: 1px solid var(--border-default);
	}
	.comparison-table {
		width: 100%;
		min-width: 960px;
		border-collapse: collapse;
		font-size: 13px;
	}
	.comparison-table th,
	.comparison-table td {
		padding: 10px 12px;
		border-bottom: 1px solid var(--border-default);
		text-align: left;
		vertical-align: top;
	}
	.comparison-table th {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 500;
		background: var(--surface-subtle);
	}
	.comparison-table tbody tr:last-child td {
		border-bottom: 0;
	}
	.condition-values {
		white-space: pre-line;
	}
	.feedback {
		display: grid;
		grid-template-columns: minmax(140px, 0.7fr) minmax(180px, 0.9fr) minmax(240px, 1.4fr);
		align-items: end;
		gap: 12px;
		margin-top: 12px;
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
	.feedback > button {
		grid-column: 3;
		justify-self: end;
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
	.mechanism-sources {
		grid-column: 1 / -1;
		display: flex;
		gap: 8px 16px;
		flex-wrap: wrap;
		padding-top: 8px;
		border-top: 1px solid var(--border-default);
		font-size: 12px;
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
	.empty {
		color: var(--text-secondary);
		padding: 10px 0;
	}
	.empty-contribution-summary {
		margin-top: 10px;
		padding-top: 10px;
		border-top: 1px solid var(--border-default);
		color: var(--text-secondary);
		font-size: 12px;
	}
	.review-section {
		padding-top: 18px;
		border-top: 1px solid var(--border-default);
	}
	.review-section .section-heading p {
		margin-top: 4px;
		color: var(--text-secondary);
		font-size: 13px;
	}
	@media (max-width: 820px) {
		.result-line {
			grid-template-columns: 1fr;
			gap: 12px;
		}
		.result-line b {
			display: none;
		}
		.metrics,
		.context-grid {
			grid-template-columns: 1fr 1fr;
		}
		.feedback {
			grid-template-columns: 1fr;
			align-items: stretch;
		}
		.feedback > button {
			grid-column: auto;
			justify-self: start;
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
