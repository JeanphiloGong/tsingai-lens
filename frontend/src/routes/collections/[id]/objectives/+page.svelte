<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import {
		listCollectionDocuments,
		type CollectionDocument
	} from '../../../_shared/collectionDocuments';
	import {
		fetchCollectionObjectives,
		fetchObjectiveAnalysis,
		fetchObjectiveScope,
		runObjectiveAnalysis,
		type ObjectiveAnalysisState,
		type ObjectiveList,
		type ObjectiveScope,
		type ObjectiveScopeDecision,
		type ObjectiveSummary
	} from '../../../_shared/researchView';
	import { t } from '../../../_shared/i18n';

	const OBJECTIVE_PAGE_SIZE = 5;
	const SCOPE_PAGE_SIZE = 8;
	type ObjectiveFilterStatus = 'all' | 'pending' | 'active' | 'published' | 'failed';

	let objectiveList: ObjectiveList | null = null;
	let readyDocuments: CollectionDocument[] = [];
	let documentsLoaded = false;
	let selectedDocumentIdsByObjective: Record<string, string[]> = {};
	let scopesByObjective: Record<string, ObjectiveScope> = {};
	let analysisStates: Record<string, ObjectiveAnalysisState | null> = {};
	let scopeObjectiveId = '';
	let scopeQuery = '';
	let scopePage = 0;
	let scopeLoading = false;
	let scopeError = '';
	let objectiveQuery = '';
	let objectiveFilterStatus: ObjectiveFilterStatus = 'all';
	let objectivePage = 0;
	let previousObjectiveFilterKey = '';
	let loading = false;
	let actionObjectiveId = '';
	let error = '';
	let loadedCollectionId = '';

	$: collectionId = $page.params.id ?? '';
	$: objectives = objectiveList?.objectives ?? [];
	$: confirmedCount = objectives.filter(
		(objective) => objective.confirmation_status === 'confirmed'
	).length;
	$: publishedCount = objectives.filter(
		(objective) => objective.published_analysis_version !== null
	).length;
	$: orderedObjectives = prioritizeObjectives(objectives);
	$: objectiveFiltersActive = Boolean(objectiveQuery.trim() || objectiveFilterStatus !== 'all');
	$: filteredObjectives = orderedObjectives.filter((objective) =>
		matchesObjectiveFilters(objective, objectiveQuery, objectiveFilterStatus, analysisStates)
	);
	$: objectiveFilterKey = `${objectiveQuery.trim()}\u0000${objectiveFilterStatus}`;
	$: if (objectiveFilterKey !== previousObjectiveFilterKey) {
		previousObjectiveFilterKey = objectiveFilterKey;
		objectivePage = 0;
	}
	$: objectivePageCount = Math.max(1, Math.ceil(filteredObjectives.length / OBJECTIVE_PAGE_SIZE));
	$: if (objectivePage >= objectivePageCount) objectivePage = objectivePageCount - 1;
	$: objectivePageRangeText = filteredObjectives.length
		? $t('research.objectives.pageRange', {
				start: objectivePage * OBJECTIVE_PAGE_SIZE + 1,
				end: Math.min((objectivePage + 1) * OBJECTIVE_PAGE_SIZE, filteredObjectives.length),
				total: filteredObjectives.length
			})
		: '';
	$: visibleObjectives = filteredObjectives.slice(
		objectivePage * OBJECTIVE_PAGE_SIZE,
		(objectivePage + 1) * OBJECTIVE_PAGE_SIZE
	);
	$: scopeObjective =
		objectives.find((objective) => objective.objective_id === scopeObjectiveId) ?? null;
	$: activeScope = scopeObjective ? (scopesByObjective[scopeObjective.objective_id] ?? null) : null;
	$: selectedScopeIds = scopeObjective
		? (selectedDocumentIdsByObjective[scopeObjective.objective_id] ?? [])
		: [];
	$: scopeMatches = readyDocuments.filter((document) =>
		document.original_filename.toLocaleLowerCase().includes(scopeQuery.trim().toLocaleLowerCase())
	);
	$: scopePageCount = Math.max(1, Math.ceil(scopeMatches.length / SCOPE_PAGE_SIZE));
	$: if (scopePage >= scopePageCount) scopePage = scopePageCount - 1;
	$: visibleScopeDocuments = scopeMatches.slice(
		scopePage * SCOPE_PAGE_SIZE,
		(scopePage + 1) * SCOPE_PAGE_SIZE
	);
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadObjectives();
	}

	function prioritizeObjectives(items: ObjectiveSummary[]) {
		const resumed = items.filter(
			(objective) =>
				objective.published_analysis_version !== null ||
				objective.active_analysis_version !== null ||
				objective.confirmation_status === 'confirmed'
		);
		const resumedIds = new Set(resumed.map((objective) => objective.objective_id));
		return [...resumed, ...items.filter((objective) => !resumedIds.has(objective.objective_id))];
	}

	async function loadObjectives() {
		loading = true;
		error = '';
		try {
			objectiveList = await fetchCollectionObjectives(collectionId);
			await refreshActiveAnalysisStates();
			scopesByObjective = {};
			selectedDocumentIdsByObjective = {};
			objectivePage = 0;
		} catch (err) {
			objectiveList = null;
			analysisStates = {};
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	async function refreshActiveAnalysisStates() {
		const currentList = objectiveList;
		if (!currentList) return;
		const activeObjectives = currentList.objectives.filter(
			(objective) =>
				objective.active_analysis_version !== null &&
				objective.active_analysis_version !== objective.published_analysis_version
		);
		if (!activeObjectives.length) {
			analysisStates = {};
			return;
		}

		const states = await Promise.all(
			activeObjectives.map(async (objective) => {
				try {
					const snapshot = await fetchObjectiveAnalysis(collectionId, objective.objective_id);
					return [objective.objective_id, snapshot.active_analysis] as const;
				} catch {
					return [objective.objective_id, null] as const;
				}
			})
		);
		analysisStates = Object.fromEntries(states);
	}

	function analysisStatus(objective: ObjectiveSummary) {
		return analysisStates[objective.objective_id]?.status ?? null;
	}

	function statusLabel(objective: ObjectiveSummary) {
		const active = analysisStates[objective.objective_id];
		if (active?.status === 'queued') return '等待分析';
		if (active?.status === 'running') {
			return active.total_document_count > 0
				? `分析中 · ${active.processed_document_count}/${active.total_document_count}`
				: '分析中';
		}
		if (active?.status === 'failed') return '分析失败';
		if (objective.published_analysis_version !== null) {
			return `结果 v${objective.published_analysis_version}`;
		}
		if (objective.active_analysis_version !== null) return '分析已启动';
		return objective.confirmation_status === 'confirmed' ? '已确认' : '待确认';
	}

	function canStartAnalysis(objective: ObjectiveSummary) {
		return objective.active_analysis_version === null || analysisStatus(objective) === 'failed';
	}

	function actionLabel(objective: ObjectiveSummary) {
		if (analysisStatus(objective) === 'failed') return '重试分析';
		return objective.confirmation_status === 'candidate' ? '确认并分析' : '开始分析';
	}

	function objectiveWorkflowStatus(
		objective: ObjectiveSummary,
		states: Record<string, ObjectiveAnalysisState | null>
	): ObjectiveFilterStatus {
		const activeStatus = states[objective.objective_id]?.status ?? null;
		if (activeStatus === 'failed') return 'failed';
		if (objective.published_analysis_version !== null) return 'published';
		if (
			activeStatus === 'queued' ||
			activeStatus === 'running' ||
			objective.active_analysis_version !== null
		) {
			return 'active';
		}
		return 'pending';
	}

	function matchesObjectiveFilters(
		objective: ObjectiveSummary,
		queryValue: string,
		statusFilter: ObjectiveFilterStatus,
		states: Record<string, ObjectiveAnalysisState | null>
	) {
		const query = queryValue.trim().toLocaleLowerCase();
		const matchesQuery =
			!query ||
			[
				objective.question,
				...objective.material_scope,
				...objective.variables,
				...objective.outcomes
			]
				.join(' ')
				.toLocaleLowerCase()
				.includes(query);
		return (
			matchesQuery &&
			(statusFilter === 'all' || objectiveWorkflowStatus(objective, states) === statusFilter)
		);
	}

	function clearObjectiveFilters() {
		objectiveQuery = '';
		objectiveFilterStatus = 'all';
	}

	function previousObjectivePage() {
		objectivePage = Math.max(0, objectivePage - 1);
	}

	function nextObjectivePage() {
		if (objectivePage + 1 >= objectivePageCount) return;
		objectivePage += 1;
	}

	function failedFrozenScope(objective: ObjectiveSummary) {
		const failed = analysisStates[objective.objective_id];
		return failed?.status === 'failed'
			? failed.document_inputs.map((input) => input.document_id)
			: null;
	}

	async function loadObjectiveScope(objective: ObjectiveSummary) {
		const cached = scopesByObjective[objective.objective_id];
		if (cached) return cached;
		const preview = await fetchObjectiveScope(collectionId, objective.objective_id);
		scopesByObjective = {
			...scopesByObjective,
			[objective.objective_id]: preview
		};
		return preview;
	}

	async function loadReadyDocuments() {
		if (documentsLoaded) return readyDocuments;
		const response = await listCollectionDocuments(collectionId);
		readyDocuments = response.items.filter((document) => document.status === 'ready');
		documentsLoaded = true;
		return readyDocuments;
	}

	async function openScopeReview(objective: ObjectiveSummary) {
		scopeObjectiveId = objective.objective_id;
		scopeQuery = '';
		scopePage = 0;
		scopeError = '';
		scopeLoading = true;
		try {
			const [preview] = await Promise.all([loadObjectiveScope(objective), loadReadyDocuments()]);
			const existing = selectedDocumentIdsByObjective[objective.objective_id];
			const frozen = failedFrozenScope(objective);
			selectedDocumentIdsByObjective = {
				...selectedDocumentIdsByObjective,
				[objective.objective_id]: [...(existing ?? frozen ?? preview.recommended_document_ids)]
			};
			filterScopeToReadyDocuments(objective.objective_id);
		} catch (err) {
			scopeError = errorMessage(err);
		} finally {
			scopeLoading = false;
		}
	}

	function filterScopeToReadyDocuments(objectiveId: string) {
		const readyIds = new Set(readyDocuments.map((document) => document.document_id));
		selectedDocumentIdsByObjective = {
			...selectedDocumentIdsByObjective,
			[objectiveId]: selectedDocumentIds(objectiveId).filter((documentId) =>
				readyIds.has(documentId)
			)
		};
	}

	function closeScopeReview() {
		if (actionObjectiveId) return;
		if (scopeObjectiveId) {
			const nextSelections = { ...selectedDocumentIdsByObjective };
			delete nextSelections[scopeObjectiveId];
			selectedDocumentIdsByObjective = nextSelections;
		}
		scopeObjectiveId = '';
		scopeError = '';
	}

	async function startRecommendedAnalysis(objective: ObjectiveSummary) {
		if (actionObjectiveId) return;
		actionObjectiveId = objective.objective_id;
		scopeError = '';
		try {
			const frozen = failedFrozenScope(objective);
			const recommendedIds =
				frozen ?? (await loadObjectiveScope(objective)).recommended_document_ids;
			if (!recommendedIds.length) {
				actionObjectiveId = '';
				await openScopeReview(objective);
				return;
			}
			const documents = await loadReadyDocuments();
			const readyIds = new Set(documents.map((document) => document.document_id));
			const documentIds = recommendedIds.filter((documentId) => readyIds.has(documentId));
			if (!documentIds.length) {
				scopeObjectiveId = objective.objective_id;
				scopeQuery = '';
				scopePage = 0;
				scopeError = '系统推荐范围中没有可分析的已准备论文，请调整范围。';
				return;
			}

			selectedDocumentIdsByObjective = {
				...selectedDocumentIdsByObjective,
				[objective.objective_id]: documentIds
			};
			await runObjectiveAnalysis(collectionId, objective.objective_id, documentIds);
			await goto(
				resolve('/collections/[id]/objectives/[objective_id]', {
					id: collectionId,
					objective_id: objective.objective_id
				})
			);
		} catch (err) {
			scopeObjectiveId = objective.objective_id;
			scopeQuery = '';
			scopePage = 0;
			scopeError = errorMessage(err);
		} finally {
			actionObjectiveId = '';
		}
	}

	async function startAnalysis(objective: ObjectiveSummary) {
		const documentIds = selectedDocumentIds(objective.objective_id);
		if (actionObjectiveId || !documentIds.length) return;
		actionObjectiveId = objective.objective_id;
		scopeError = '';
		try {
			await runObjectiveAnalysis(collectionId, objective.objective_id, documentIds);
			await goto(
				resolve('/collections/[id]/objectives/[objective_id]', {
					id: collectionId,
					objective_id: objective.objective_id
				})
			);
		} catch (err) {
			scopeError = errorMessage(err);
		} finally {
			actionObjectiveId = '';
		}
	}

	function joined(items: string[]) {
		return items.length ? items.join(', ') : '-';
	}

	function selectedDocumentIds(objectiveId: string) {
		return selectedDocumentIdsByObjective[objectiveId] ?? [];
	}

	function updateScopeQuery(value: string) {
		scopeQuery = value;
		scopePage = 0;
	}

	function toggleDocument(objectiveId: string, documentId: string) {
		const selected = selectedDocumentIds(objectiveId);
		selectedDocumentIdsByObjective = {
			...selectedDocumentIdsByObjective,
			[objectiveId]: selected.includes(documentId)
				? selected.filter((item) => item !== documentId)
				: [...selected, documentId]
		};
	}

	function scopeDecision(documentId: string): ObjectiveScopeDecision | null {
		return activeScope?.decisions.find((item) => item.document_id === documentId) ?? null;
	}

	function scopeDecisionLabel(documentId: string) {
		const decision = scopeDecision(documentId);
		if (!decision) return '尚未完成范围判断';
		if (decision.classification === 'likely_relevant') return '系统推荐';
		if (decision.classification === 'needs_inspection') return '待人工确认';
		return '当前不建议';
	}

	function confirmActionLabel(objective: ObjectiveSummary, count: number) {
		if (!count) return '选择论文后开始分析';
		return analysisStatus(objective) === 'failed'
			? `使用 ${count} 篇论文重新分析`
			: `使用 ${count} 篇论文开始分析`;
	}
</script>

<svelte:head><title>研究目标</title></svelte:head>

<section class="objectives-page">
	<header class="page-heading">
		<div>
			<h2>研究目标</h2>
			<p>选择一个具体问题，审阅分析范围，再让系统逐篇提取并比较证据。</p>
		</div>
		<button class="btn btn--ghost" type="button" on:click={loadObjectives}>刷新</button>
	</header>

	{#if loading}
		<p class="state" aria-busy="true">正在加载...</p>
	{:else if error}
		<p class="state state--error" role="alert">{error}</p>
	{:else if !objectives.length}
		<section class="empty-state">
			<h3>没有可供确认的研究目标</h3>
			<p>
				当前没有候选同时满足材料范围、研究变量、结果指标和来源支持规则。这不表示目标级证据分析已经完成。
			</p>
			<div class="actions">
				<a
					class="btn btn--ghost btn--small"
					href={resolve('/collections/[id]', { id: collectionId })}
				>
					返回集合概览
				</a>
				<a
					class="btn btn--primary btn--small"
					href={resolve('/collections/[id]/documents', { id: collectionId })}
				>
					检查文献
				</a>
			</div>
		</section>
	{:else}
		<div class="summary" aria-label="研究目标概览">
			<div><strong>{objectives.length}</strong><span>研究目标</span></div>
			<div><strong>{confirmedCount}</strong><span>已确认</span></div>
			<div><strong>{publishedCount}</strong><span>已有结果</span></div>
		</div>

		<div class="objective-filters" role="search" aria-label="筛选研究目标">
			<label>
				<span>搜索研究目标</span>
				<input type="search" bind:value={objectiveQuery} placeholder="问题、材料、变量或结果" />
			</label>
			<label>
				<span>分析状态</span>
				<select bind:value={objectiveFilterStatus}>
					<option value="all">全部状态</option>
					<option value="pending">待分析</option>
					<option value="active">分析中</option>
					<option value="published">已有结果</option>
					<option value="failed">分析失败</option>
				</select>
			</label>
			{#if objectiveFiltersActive}
				<button class="btn btn--ghost btn--small" type="button" on:click={clearObjectiveFilters}>
					清除筛选
				</button>
			{/if}
		</div>

		{#if objectiveFiltersActive}
			<p class="filter-count" aria-live="polite">找到 {filteredObjectives.length} 个研究目标</p>
		{/if}

		{#if !filteredObjectives.length}
			<section class="filter-empty">
				<h3>没有匹配的研究目标</h3>
				<p>请调整关键词或分析状态后重试。</p>
				<button class="btn btn--ghost btn--small" type="button" on:click={clearObjectiveFilters}>
					清除筛选
				</button>
			</section>
		{:else}
			<div class="objective-list">
				{#each visibleObjectives as objective (objective.objective_id)}
					<article>
						<div class="heading">
							<div>
								<h3>{objective.question}</h3>
								<p>{objective.requested_comparator || '尚未设置比较意图'}</p>
							</div>
							<span
								class:published={objective.published_analysis_version !== null}
								class:failed={analysisStatus(objective) === 'failed'}
							>
								{statusLabel(objective)}
							</span>
						</div>
						<dl>
							<div>
								<dt>材料</dt>
								<dd>{joined(objective.material_scope)}</dd>
							</div>
							<div>
								<dt>变量</dt>
								<dd>{joined(objective.variables)}</dd>
							</div>
							<div>
								<dt>结果</dt>
								<dd>{joined(objective.outcomes)}</dd>
							</div>
							<div>
								<dt>问题来源</dt>
								<dd>{objective.seed_document_ids.length} 篇</dd>
							</div>
						</dl>
						<div class="actions">
							{#if canStartAnalysis(objective)}
								<button
									class="btn btn--primary btn--small"
									type="button"
									disabled={Boolean(actionObjectiveId)}
									on:click={() => void startRecommendedAnalysis(objective)}
								>
									{actionObjectiveId === objective.objective_id
										? '正在准备...'
										: actionLabel(objective)}
								</button>
								<button
									class="btn btn--ghost btn--small"
									type="button"
									disabled={Boolean(actionObjectiveId)}
									title="默认使用系统推荐的文献范围"
									on:click={() => void openScopeReview(objective)}
								>
									调整范围
								</button>
							{/if}
							<a
								class="btn btn--ghost btn--small"
								href={resolve('/collections/[id]/objectives/[objective_id]', {
									id: collectionId,
									objective_id: objective.objective_id
								})}
							>
								{objective.published_analysis_version === null ? '查看状态' : '查看 Findings'}
							</a>
						</div>
					</article>
				{/each}
			</div>
			{#if objectivePageCount > 1}
				<nav class="objective-pagination" aria-label={$t('research.objectives.paginationLabel')}>
					<button
						class="btn btn--ghost btn--small"
						type="button"
						disabled={objectivePage === 0}
						on:click={previousObjectivePage}
					>
						{$t('research.objectives.previousPage')}
					</button>
					<span>{objectivePageRangeText}</span>
					<button
						class="btn btn--ghost btn--small"
						type="button"
						disabled={objectivePage + 1 >= objectivePageCount}
						on:click={nextObjectivePage}
					>
						{$t('research.objectives.nextPage')}
					</button>
				</nav>
			{/if}
		{/if}
	{/if}
</section>

{#if scopeObjective}
	<div class="dialog-backdrop">
		<div class="scope-dialog" role="dialog" aria-modal="true" aria-labelledby="scope-dialog-title">
			<header>
				<div>
					<span>分析前确认</span>
					<h2 id="scope-dialog-title">确认分析论文范围</h2>
				</div>
				<button
					class="close-button"
					type="button"
					aria-label="关闭论文范围"
					on:click={closeScopeReview}>×</button
				>
			</header>

			<div class="scope-question">
				<strong>{scopeObjective.question}</strong>
				<p>系统只会分析你在这里确认的论文；启动后，本次范围会被冻结以便结果追溯。</p>
			</div>
			{#if activeScope}
				<div class="scope-summary" aria-label="论文范围判断概览">
					<span><strong>{activeScope.counts.likely_relevant}</strong> 篇系统推荐</span>
					<span><strong>{activeScope.counts.needs_inspection}</strong> 篇待人工确认</span>
					<span><strong>{scopeObjective.seed_document_ids.length}</strong> 篇问题来源</span>
				</div>
			{/if}

			<div class="scope-toolbar">
				<label class="scope-search">
					<span>搜索可用论文</span>
					<input
						type="search"
						value={scopeQuery}
						on:input={(event) => updateScopeQuery((event.currentTarget as HTMLInputElement).value)}
					/>
				</label>
				<strong>已选择 {selectedScopeIds.length} 篇论文</strong>
			</div>

			{#if scopeLoading}
				<p class="scope-state" aria-busy="true">正在加载可用论文...</p>
			{:else if scopeError}
				<p class="scope-state scope-state--error" role="alert">{scopeError}</p>
			{:else if visibleScopeDocuments.length}
				<div class="scope-options">
					{#each visibleScopeDocuments as document (document.document_id)}
						<label>
							<input
								type="checkbox"
								checked={selectedScopeIds.includes(document.document_id)}
								on:change={() => toggleDocument(scopeObjective.objective_id, document.document_id)}
							/>
							<span class="scope-option-copy">
								<span>{document.original_filename}</span>
								<small>
									{scopeDecisionLabel(document.document_id)}{scopeDecision(document.document_id)
										?.is_seed
										? ' · 问题来源'
										: ''}
								</small>
							</span>
						</label>
					{/each}
				</div>
				<nav class="scope-pagination" aria-label="论文范围分页">
					<button type="button" disabled={scopePage === 0} on:click={() => (scopePage -= 1)}
						>上一页</button
					>
					<span>第 {scopePage + 1}/{scopePageCount} 页</span>
					<button
						type="button"
						disabled={scopePage + 1 >= scopePageCount}
						on:click={() => (scopePage += 1)}
					>
						下一页
					</button>
				</nav>
			{:else if readyDocuments.length}
				<p class="scope-state">没有匹配的已准备论文。</p>
			{:else}
				<p class="scope-state">还没有可用于分析的已准备论文。</p>
			{/if}

			<footer>
				{#if !selectedScopeIds.length && !scopeLoading}
					<p>请选择至少一篇论文。</p>
				{/if}
				<div>
					<button class="btn btn--ghost" type="button" on:click={closeScopeReview}>取消</button>
					<button
						class="btn btn--primary"
						type="button"
						disabled={!selectedScopeIds.length || scopeLoading || Boolean(actionObjectiveId)}
						on:click={() => void startAnalysis(scopeObjective)}
					>
						{actionObjectiveId
							? '正在启动...'
							: confirmActionLabel(scopeObjective, selectedScopeIds.length)}
					</button>
				</div>
			</footer>
		</div>
	</div>
{/if}

<style>
	.objectives-page {
		width: min(1120px, 100%);
		margin: 0 auto;
		display: grid;
		gap: 20px;
	}

	.page-heading,
	.heading,
	.actions,
	.objective-filters,
	.objective-pagination,
	.scope-dialog header,
	.scope-toolbar,
	.scope-summary,
	.scope-dialog footer,
	.scope-dialog footer > div,
	.scope-pagination {
		display: flex;
		align-items: center;
	}

	.page-heading,
	.heading,
	.objective-pagination,
	.scope-dialog header,
	.scope-toolbar,
	.scope-summary,
	.scope-dialog footer,
	.scope-pagination {
		justify-content: space-between;
	}

	.page-heading {
		align-items: flex-start;
		gap: 20px;
		padding-bottom: 16px;
		border-bottom: 1px solid var(--border-default);
	}

	h2,
	h3,
	p {
		margin: 0;
	}

	.page-heading p,
	article p,
	dt,
	.summary span,
	.scope-question p {
		color: var(--text-secondary);
	}

	.page-heading p {
		max-width: 720px;
		margin-top: 6px;
	}

	.state,
	.empty-state {
		padding: 28px 0;
	}

	.objective-filters {
		align-items: end;
		gap: 12px;
	}

	.objective-filters label {
		min-width: min(320px, 100%);
		display: grid;
		gap: 6px;
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
	}

	.objective-filters label:nth-child(2) {
		min-width: 180px;
	}

	.objective-filters input,
	.objective-filters select {
		width: 100%;
		min-height: 38px;
		padding: 7px 10px;
		border: 1px solid var(--border-default);
		background: var(--surface-card);
		color: var(--text-primary);
	}

	.filter-count {
		color: var(--text-secondary);
		font-size: 13px;
	}

	.filter-empty {
		display: grid;
		justify-items: start;
		gap: 8px;
		padding: 28px 0;
		border-bottom: 1px solid var(--border-default);
	}

	.filter-empty p {
		color: var(--text-secondary);
	}

	.state {
		color: var(--text-secondary);
	}

	.state--error,
	.scope-state--error,
	.scope-dialog footer > p {
		color: var(--danger-text, #b42318);
	}

	.empty-state {
		display: grid;
		gap: 10px;
		border-bottom: 1px solid var(--border-default);
	}

	.empty-state p {
		max-width: 720px;
		color: var(--text-secondary);
		line-height: 1.6;
	}

	.summary {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		border-block: 1px solid var(--border-default);
	}

	.summary div {
		display: grid;
		gap: 2px;
		padding: 14px 18px;
		border-right: 1px solid var(--border-default);
	}

	.summary div:last-child {
		border-right: 0;
	}

	.summary strong {
		font-size: 20px;
	}

	.objective-list {
		display: grid;
	}

	article {
		display: grid;
		gap: 14px;
		padding: 20px 0;
		border-bottom: 1px solid var(--border-default);
	}

	.heading {
		align-items: flex-start;
		gap: 20px;
	}

	.heading h3 {
		font-size: 17px;
		line-height: 1.45;
	}

	.heading p {
		margin-top: 5px;
	}

	.heading > span {
		white-space: nowrap;
		padding: 4px 8px;
		border: 1px solid var(--border-default);
		font-size: 12px;
	}

	.heading > span.published {
		border-color: #3a7d5d;
		color: #256346;
	}

	.heading > span.failed {
		border-color: var(--danger-text, #b42318);
		color: var(--danger-text, #b42318);
	}

	dl {
		margin: 0;
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 14px;
	}

	dt {
		margin-bottom: 4px;
		font-size: 12px;
	}

	dd {
		margin: 0;
		line-height: 1.45;
		overflow-wrap: anywhere;
	}

	.actions,
	.scope-dialog footer > div {
		flex-wrap: wrap;
		gap: 8px;
	}

	.objective-pagination {
		justify-content: space-between;
		gap: 16px;
		padding-top: 8px;
		color: var(--text-secondary);
		font-size: 13px;
	}

	.dialog-backdrop {
		position: fixed;
		z-index: 100;
		inset: 0;
		display: grid;
		place-items: center;
		padding: 24px;
		background: rgb(15 23 42 / 48%);
	}

	.scope-dialog {
		width: min(760px, 100%);
		max-height: min(760px, calc(100vh - 48px));
		overflow: auto;
		padding: 22px;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--surface-card);
		box-shadow: 0 18px 50px rgb(15 23 42 / 22%);
	}

	.scope-dialog > * + * {
		margin-top: 18px;
	}

	.scope-dialog header {
		align-items: flex-start;
		gap: 20px;
	}

	.scope-dialog header span {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
	}

	.scope-dialog header h2 {
		margin-top: 3px;
		font-size: 20px;
	}

	.close-button {
		width: 32px;
		height: 32px;
		border: 1px solid var(--border-default);
		border-radius: 50%;
		background: transparent;
		color: var(--text-primary);
		cursor: pointer;
		font-size: 20px;
		line-height: 1;
	}

	.scope-question {
		padding: 14px 0;
		border-block: 1px solid var(--border-default);
	}

	.scope-question p {
		margin-top: 6px;
		line-height: 1.5;
	}

	.scope-toolbar {
		align-items: flex-end;
		gap: 20px;
	}

	.scope-search {
		min-width: 0;
		flex: 1;
		display: grid;
		gap: 5px;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.scope-search input {
		width: 100%;
		min-height: 38px;
		padding: 7px 10px;
		border: 1px solid var(--border-default);
		background: var(--surface-card);
		color: var(--text-primary);
	}

	.scope-toolbar > strong {
		white-space: nowrap;
		font-size: 13px;
	}

	.scope-summary {
		justify-content: flex-start;
		flex-wrap: wrap;
		gap: 8px 18px;
		color: var(--text-secondary);
		font-size: 13px;
	}

	.scope-summary strong {
		color: var(--text-primary);
	}

	.scope-options {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px 16px;
	}

	.scope-options label {
		min-width: 0;
		display: flex;
		align-items: flex-start;
		gap: 8px;
		padding: 7px 0;
	}

	.scope-options span {
		overflow-wrap: anywhere;
	}

	.scope-option-copy {
		min-width: 0;
		display: grid;
		gap: 2px;
	}

	.scope-option-copy small {
		color: var(--text-secondary);
		font-size: 11px;
	}

	.scope-pagination {
		gap: 12px;
		margin-top: 12px;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.scope-pagination button {
		min-height: 32px;
		padding: 4px 10px;
		border: 1px solid var(--border-default);
		background: var(--surface-card);
		color: inherit;
	}

	.scope-state {
		padding: 24px 0;
		color: var(--text-secondary);
	}

	.scope-dialog footer {
		min-height: 40px;
		gap: 16px;
		padding-top: 16px;
		border-top: 1px solid var(--border-default);
	}

	.scope-dialog footer > p {
		font-size: 13px;
	}

	@media (max-width: 760px) {
		.objectives-page {
			gap: 12px;
		}

		.page-heading,
		.heading,
		.objective-filters,
		.objective-pagination,
		.scope-toolbar,
		.scope-dialog footer {
			align-items: stretch;
			flex-direction: column;
		}

		.summary div {
			padding: 8px;
			text-align: center;
		}

		dl,
		.scope-options {
			grid-template-columns: 1fr 1fr;
		}

		.dialog-backdrop {
			align-items: end;
			padding: 0;
		}

		.scope-dialog {
			max-height: 92vh;
			padding: 18px;
			border-radius: 8px 8px 0 0;
		}

		.scope-toolbar > strong {
			white-space: normal;
		}

		.scope-dialog footer > div,
		.scope-dialog footer .btn {
			width: 100%;
		}

		.scope-dialog footer .btn {
			flex: 1;
		}
	}

	@media (max-width: 480px) {
		dl,
		.scope-options {
			grid-template-columns: 1fr;
		}
	}
</style>
