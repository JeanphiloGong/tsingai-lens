<script lang="ts">
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onDestroy } from 'svelte';
	import FindingWorkbench from '../../_components/FindingWorkbench.svelte';
	import { errorMessage } from '../../../../_shared/api';
	import {
		confirmObjective,
		fetchObjective,
		fetchObjectiveAnalysis,
		fetchObjectiveEvidence,
		fetchObjectiveFindings,
		runObjectiveAnalysis,
		type ObjectiveAnalysis,
		type ObjectiveEvidence,
		type ObjectiveFinding
	} from '../../../../_shared/researchView';

	const POLL_DELAY_MS = 2500;
	let analysis: ObjectiveAnalysis | null = null;
	let findings: ObjectiveFinding[] = [];
	let evidence: ObjectiveEvidence[] = [];
	let selectedFindingId = '';
	let loading = false;
	let findingLoading = false;
	let actionRunning = false;
	let error = '';
	let actionError = '';
	let loadedKey = '';
	let pollTimer: ReturnType<typeof setTimeout> | null = null;

	$: collectionId = $page.params.id ?? '';
	$: objectiveId = $page.params.objective_id ?? '';
	$: currentUrl = $page.url;
	$: requestedFindingId = $page.url.searchParams.get('finding_id') ?? '';
	$: active = analysis?.active_analysis ?? null;
	$: published = analysis?.published_analysis ?? null;
	$: selectedFinding = findings.find((item) => item.finding_id === selectedFindingId) ?? null;
	$: isProcessing = active?.status === 'queued' || active?.status === 'running';
	$: if (browser && collectionId && objectiveId && `${collectionId}:${objectiveId}` !== loadedKey) {
		loadedKey = `${collectionId}:${objectiveId}`;
		void loadObjective();
	}

	onDestroy(clearPoll);

	async function loadObjective() {
		loading = true;
		error = '';
		clearPoll();
		try {
			analysis = await fetchObjective(collectionId, objectiveId);
			await loadFindings();
			schedulePoll();
		} catch (err) {
			error = errorMessage(err);
			analysis = null;
			findings = [];
			evidence = [];
		} finally {
			loading = false;
		}
	}

	async function loadFindings() {
		if (!analysis?.objective.published_analysis_version) {
			findings = [];
			evidence = [];
			selectedFindingId = '';
			return;
		}
		const page = await fetchObjectiveFindings(
			collectionId,
			objectiveId,
			analysis.objective.published_analysis_version
		);
		findings = page.items;
		const nextId =
			(requestedFindingId && findings.some((item) => item.finding_id === requestedFindingId)
				? requestedFindingId
				: selectedFindingId && findings.some((item) => item.finding_id === selectedFindingId)
					? selectedFindingId
					: findings[0]?.finding_id) ?? '';
		await selectFinding(nextId, false);
	}

	async function selectFinding(findingId: string, updateUrl = true) {
		selectedFindingId = findingId;
		evidence = [];
		if (!findingId || !analysis?.objective.published_analysis_version) return;
		findingLoading = true;
		try {
			const page = await fetchObjectiveEvidence(
				collectionId,
				objectiveId,
				analysis.objective.published_analysis_version,
				findingId
			);
			evidence = page.items;
			if (updateUrl) {
				const url = new URL(currentUrl);
				url.searchParams.set('finding_id', findingId);
				await goto(`${url.pathname}${url.search}`, {
					replaceState: true,
					noScroll: true,
					keepFocus: true
				});
			}
		} catch (err) {
			actionError = errorMessage(err);
		} finally {
			findingLoading = false;
		}
	}

	async function startAnalysis() {
		if (!analysis || actionRunning || isProcessing) return;
		actionRunning = true;
		actionError = '';
		try {
			if (analysis.objective.confirmation_status === 'candidate') {
				analysis = await confirmObjective(collectionId, objectiveId);
			}
			analysis = await runObjectiveAnalysis(collectionId, objectiveId);
			schedulePoll();
		} catch (err) {
			actionError = errorMessage(err);
		} finally {
			actionRunning = false;
		}
	}

	function schedulePoll() {
		clearPoll();
		if (!browser || !isProcessing) return;
		pollTimer = setTimeout(refreshAnalysis, POLL_DELAY_MS);
	}

	async function refreshAnalysis() {
		try {
			analysis = await fetchObjectiveAnalysis(collectionId, objectiveId);
			if (analysis.active_analysis?.status === 'succeeded') await loadFindings();
			schedulePoll();
		} catch (err) {
			actionError = errorMessage(err);
			clearPoll();
		}
	}

	function clearPoll() {
		if (!pollTimer) return;
		clearTimeout(pollTimer);
		pollTimer = null;
	}

	function actionLabel() {
		if (actionRunning) return '正在启动...';
		if (active?.status === 'failed') return '重试分析';
		if (published) return '重新分析';
		return '确认并分析';
	}

	function joined(items: string[]) {
		return items.length ? items.join(', ') : '-';
	}

	function datasetUrl() {
		return `/api/v1/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/finding-dataset?format=training_jsonl`;
	}
</script>

<svelte:head><title>{analysis?.objective.question ?? '研究目标'}</title></svelte:head>

{#if loading}
	<p class="page-state" aria-busy="true">正在加载研究目标...</p>
{:else if error || !analysis}
	<p class="page-state page-state--error" role="alert">{error || '研究目标不存在。'}</p>
{:else}
	<section class="objective-page">
		<header class="objective-header">
			<div>
				<a href={`/collections/${collectionId}/objectives`}>研究目标</a>
				<h1>{analysis.objective.question}</h1>
				<p>{analysis.objective.comparison_intent || '尚未设置比较意图'}</p>
			</div>
			<div class="header-actions">
				<a class="btn btn--ghost btn--small" href={datasetUrl()}>导出训练数据</a>
				{#if !isProcessing}
					<button
						class="btn btn--primary btn--small"
						type="button"
						disabled={actionRunning}
						on:click={startAnalysis}
					>
						{actionLabel()}
					</button>
				{/if}
			</div>
		</header>

		<div class="scope-strip">
			<div><span>材料</span><strong>{joined(analysis.objective.material_scope)}</strong></div>
			<div><span>变量</span><strong>{joined(analysis.objective.process_axes)}</strong></div>
			<div><span>结果</span><strong>{joined(analysis.objective.property_axes)}</strong></div>
			<div><span>文献</span><strong>{analysis.objective.seed_document_ids.length} 篇</strong></div>
		</div>

		{#if active}
			<section class:failed={active.status === 'failed'} class="analysis-state" role="status">
				<div>
					<strong
						>{active.status === 'failed'
							? '本次分析失败'
							: active.status === 'succeeded'
								? '分析完成'
								: '正在分析'}</strong
					>
					<span>{active.progress_message || active.error_message || active.phase}</span>
				</div>
				{#if active.total_document_count > 0}
					<span>{active.processed_document_count}/{active.total_document_count} 篇</span>
				{/if}
			</section>
		{/if}
		{#if actionError}<p class="action-error" role="alert">{actionError}</p>{/if}

		{#if published && findings.length}
			<section class="findings-section">
				<div class="findings-heading">
					<div>
						<h2>Findings</h2>
						<p>选择一条研究发现查看关系、适用条件和原文证据。</p>
					</div>
					<span>{findings.length} 条 · v{published.analysis_version}</span>
				</div>
				<div class="finding-list" role="list">
					{#each findings as item (item.finding_id)}
						<button
							type="button"
							class:selected={item.finding_id === selectedFindingId}
							on:click={() => selectFinding(item.finding_id)}
						>
							<span>{item.statement}</span>
							<small>{joined(item.variables)} → {joined(item.outcomes)}</small>
							<em>{item.evidence_strength} · {item.paper_count} 篇</em>
						</button>
					{/each}
				</div>
			</section>

			<section class="finding-workspace">
				{#if findingLoading}
					<p class="page-state" aria-busy="true">正在加载原文证据...</p>
				{:else if selectedFinding}
					<FindingWorkbench finding={selectedFinding} {evidence} {collectionId} />
				{/if}
			</section>
		{:else if published}
			<p class="page-state">该版本没有可展示的 Findings。</p>
		{:else if !isProcessing}
			<p class="page-state">确认并开始分析后，这里将展示可追溯的 Findings。</p>
		{/if}
	</section>
{/if}

<style>
	.objective-page {
		width: min(1160px, 100%);
		margin: 0 auto;
		display: grid;
		gap: 22px;
	}
	.objective-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 20px;
	}
	.objective-header a {
		color: var(--text-secondary);
		font-size: 13px;
	}
	h1,
	h2,
	p {
		margin: 0;
	}
	h1 {
		margin-top: 8px;
		max-width: 850px;
		font-size: 25px;
		line-height: 1.4;
	}
	.objective-header p,
	.findings-heading p {
		margin-top: 6px;
		color: var(--text-secondary);
	}
	.header-actions {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.scope-strip {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		border-block: 1px solid var(--border-default);
	}
	.scope-strip div {
		padding: 12px 14px;
		display: grid;
		gap: 4px;
		border-right: 1px solid var(--border-default);
	}
	.scope-strip div:last-child {
		border-right: 0;
	}
	.scope-strip span {
		color: var(--text-secondary);
		font-size: 12px;
	}
	.scope-strip strong {
		font-size: 13px;
		overflow-wrap: anywhere;
	}
	.analysis-state {
		padding: 12px 14px;
		display: flex;
		justify-content: space-between;
		gap: 16px;
		border-left: 3px solid #3676a8;
		background: var(--surface-subtle);
	}
	.analysis-state > div {
		display: grid;
		gap: 3px;
	}
	.analysis-state span {
		color: var(--text-secondary);
	}
	.analysis-state.failed {
		border-color: #b42318;
	}
	.action-error,
	.page-state--error {
		color: var(--danger, #b42318);
	}
	.findings-section {
		display: grid;
		gap: 12px;
	}
	.findings-heading {
		display: flex;
		justify-content: space-between;
		gap: 16px;
		align-items: flex-end;
	}
	.findings-heading > span {
		color: var(--text-secondary);
		font-size: 12px;
	}
	.finding-list {
		border-top: 1px solid var(--border-default);
	}
	.finding-list button {
		width: 100%;
		border: 0;
		border-bottom: 1px solid var(--border-default);
		background: transparent;
		color: inherit;
		display: grid;
		grid-template-columns: minmax(0, 1fr) 220px 130px;
		gap: 14px;
		text-align: left;
		align-items: center;
		padding: 13px 10px;
		cursor: pointer;
	}
	.finding-list button:hover,
	.finding-list button.selected {
		background: var(--surface-subtle);
	}
	.finding-list button.selected {
		box-shadow: inset 3px 0 #3a7d5d;
	}
	.finding-list small,
	.finding-list em {
		color: var(--text-secondary);
		font-style: normal;
	}
	.finding-list em {
		text-align: right;
	}
	.finding-workspace {
		border-top: 1px solid var(--border-default);
		padding-top: 22px;
	}
	.page-state {
		padding: 30px 0;
		color: var(--text-secondary);
	}
	@media (max-width: 820px) {
		.objective-header,
		.findings-heading {
			flex-direction: column;
			align-items: flex-start;
		}
		.scope-strip {
			grid-template-columns: 1fr 1fr;
		}
		.finding-list button {
			grid-template-columns: 1fr;
			gap: 5px;
		}
		.finding-list em {
			text-align: left;
		}
	}
</style>
