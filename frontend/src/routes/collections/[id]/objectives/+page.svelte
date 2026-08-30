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
		runObjectiveAnalysis,
		type ObjectiveAnalysisState,
		type ObjectiveList,
		type ObjectiveSummary
	} from '../../../_shared/researchView';

	let objectiveList: ObjectiveList | null = null;
	let readyDocuments: CollectionDocument[] = [];
	let selectedDocumentIdsByObjective: Record<string, string[]> = {};
	let analysisStates: Record<string, ObjectiveAnalysisState | null> = {};
	let scopeEditorObjectiveId = '';
	let scopeQuery = '';
	let scopePage = 0;
	let loading = false;
	let actionObjectiveId = '';
	let error = '';
	let loadedCollectionId = '';
	const SCOPE_PAGE_SIZE = 8;

	$: collectionId = $page.params.id ?? '';
	$: objectives = objectiveList?.objectives ?? [];
	$: confirmedCount = objectives.filter(
		(objective) => objective.confirmation_status === 'confirmed'
	).length;
	$: publishedCount = objectives.filter(
		(objective) => objective.published_analysis_version !== null
	).length;
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

	async function loadObjectives() {
		loading = true;
		error = '';
		try {
			const [objectivesResult, documentsResult] = await Promise.all([
				fetchCollectionObjectives(collectionId),
				listCollectionDocuments(collectionId)
			]);
			objectiveList = objectivesResult;
			readyDocuments = documentsResult.items.filter((document) => document.status === 'ready');
			await refreshActiveAnalysisStates();
			initializeObjectiveScopes();
		} catch (err) {
			objectiveList = null;
			readyDocuments = [];
			selectedDocumentIdsByObjective = {};
			analysisStates = {};
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	function initializeObjectiveScopes() {
		const readyIds = new Set(readyDocuments.map((document) => document.document_id));
		const next: Record<string, string[]> = {};
		for (const objective of objectives) {
			const existing = selectedDocumentIdsByObjective[objective.objective_id];
			const failedInputs =
				analysisStates[objective.objective_id]?.status === 'failed'
					? (analysisStates[objective.objective_id]?.document_inputs.map(
							(input) => input.document_id
						) ?? [])
					: [];
			const initialIds =
				existing ?? (failedInputs.length ? failedInputs : objective.seed_document_ids);
			next[objective.objective_id] = initialIds.filter((documentId) => readyIds.has(documentId));
		}
		selectedDocumentIdsByObjective = next;
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
		if (actionObjectiveId === objective.objective_id) return '正在启动...';
		if (analysisStatus(objective) === 'failed') return '重试分析';
		return objective.confirmation_status === 'candidate' ? '确认并分析' : '开始分析';
	}

	async function startAnalysis(objective: ObjectiveSummary) {
		const selectedDocumentIds = selectedDocumentIdsByObjective[objective.objective_id] ?? [];
		if (actionObjectiveId || !selectedDocumentIds.length) return;
		actionObjectiveId = objective.objective_id;
		error = '';
		try {
			await runObjectiveAnalysis(collectionId, objective.objective_id, selectedDocumentIds);
			await goto(
				resolve('/collections/[id]/objectives/[objective_id]', {
					id: collectionId,
					objective_id: objective.objective_id
				})
			);
		} catch (err) {
			error = errorMessage(err);
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

	function openScopeEditor(objectiveId: string) {
		scopeEditorObjectiveId = scopeEditorObjectiveId === objectiveId ? '' : objectiveId;
		scopeQuery = '';
		scopePage = 0;
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
</script>

<svelte:head><title>研究目标</title></svelte:head>

<section class="objectives-page">
	<header>
		<div>
			<h2>研究目标</h2>
			<p>确认研究问题后，系统将逐篇文献提取证据并生成可审计的 Findings。</p>
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

		<div class="objective-list">
			{#each objectives as objective (objective.objective_id)}
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
							<dt>机制</dt>
							<dd>{joined(objective.mechanisms)}</dd>
						</div>
						<div>
							<dt>约束</dt>
							<dd>{joined(objective.constraints)}</dd>
						</div>
						<div>
							<dt>文献范围</dt>
							<dd>{objective.seed_document_ids.length} 篇</dd>
						</div>
					</dl>
					<div class="actions">
						{#if canStartAnalysis(objective)}
							<div class="scope-summary">
								<strong
									>{(selectedDocumentIdsByObjective[objective.objective_id] ?? []).length} 篇已选</strong
								>
								<button
									class="btn btn--ghost btn--small"
									type="button"
									aria-expanded={scopeEditorObjectiveId === objective.objective_id}
									aria-label={`编辑「${objective.question}」的论文范围`}
									on:click={() => openScopeEditor(objective.objective_id)}
								>
									编辑范围
								</button>
							</div>
							<button
								class="btn btn--primary btn--small"
								type="button"
								disabled={Boolean(actionObjectiveId) ||
									!(selectedDocumentIdsByObjective[objective.objective_id] ?? []).length}
								on:click={() => startAnalysis(objective)}
							>
								{actionLabel(objective)}
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
					{#if canStartAnalysis(objective) && !(selectedDocumentIdsByObjective[objective.objective_id] ?? []).length}
						<p class="scope-warning">请先选择至少一篇已准备论文，再开始分析。</p>
					{/if}
					{#if scopeEditorObjectiveId === objective.objective_id}
						<fieldset class="analysis-scope">
							<legend>分析论文范围</legend>
							<p>只会分析这里选中的已准备论文；启动后会冻结这次范围。</p>
							<label class="scope-search">
								<span>搜索可用论文</span>
								<input
									type="search"
									value={scopeQuery}
									on:input={(event) =>
										updateScopeQuery((event.currentTarget as HTMLInputElement).value)}
								/>
							</label>
							{#if visibleScopeDocuments.length}
								<div class="scope-options">
									{#each visibleScopeDocuments as document (document.document_id)}
										<label>
											<input
												type="checkbox"
												checked={(
													selectedDocumentIdsByObjective[objective.objective_id] ?? []
												).includes(document.document_id)}
												on:change={() =>
													toggleDocument(objective.objective_id, document.document_id)}
											/>
											<span>{document.original_filename}</span>
										</label>
									{/each}
								</div>
								<div class="scope-pagination" aria-label="论文范围分页">
									<button
										type="button"
										disabled={scopePage === 0}
										on:click={() => (scopePage -= 1)}
									>
										上一页
									</button>
									<span>第 {scopePage + 1}/{scopePageCount} 页</span>
									<button
										type="button"
										disabled={scopePage + 1 >= scopePageCount}
										on:click={() => (scopePage += 1)}
									>
										下一页
									</button>
								</div>
							{:else if readyDocuments.length}
								<p class="scope-empty">没有匹配的已准备论文。</p>
							{:else}
								<p class="scope-empty">还没有准备完成的论文。</p>
							{/if}
						</fieldset>
					{/if}
				</article>
			{/each}
		</div>
	{/if}
</section>

<style>
	.objectives-page {
		width: min(1120px, 100%);
		margin: 0 auto;
		display: grid;
		gap: 20px;
	}
	header {
		display: flex;
		justify-content: space-between;
		gap: 20px;
		align-items: flex-start;
		border-bottom: 1px solid var(--border-default);
		padding-bottom: 16px;
	}
	h2,
	h3,
	p {
		margin: 0;
	}
	header p,
	article p,
	dt,
	.summary span {
		color: var(--text-secondary);
	}
	header p {
		margin-top: 6px;
		max-width: 720px;
	}
	.state {
		padding: 28px 0;
		color: var(--text-secondary);
	}
	.state--error {
		color: var(--danger, #b42318);
	}
	.empty-state {
		display: grid;
		gap: 10px;
		padding: 28px 0;
		border-bottom: 1px solid var(--border-default);
	}
	.analysis-scope {
		margin: 0;
		padding: 14px;
		border: 1px solid var(--border-default);
		background: var(--bg-subtle);
	}
	.analysis-scope legend {
		padding: 0;
		font-weight: 700;
	}
	.analysis-scope > p {
		margin-top: 6px;
		color: var(--text-secondary);
	}
	.scope-options {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px 16px;
		margin-top: 14px;
	}
	.scope-search {
		display: grid;
		gap: 5px;
		margin-top: 12px;
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
	.scope-pagination {
		display: flex;
		align-items: center;
		justify-content: space-between;
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
	.scope-empty {
		margin-top: 12px;
		color: var(--text-secondary);
	}
	.scope-warning {
		color: var(--warning-text);
		font-size: 13px;
	}
	.scope-options label {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		min-width: 0;
	}
	.scope-options span {
		overflow-wrap: anywhere;
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
		gap: 10px;
	}
	article {
		border-bottom: 1px solid var(--border-default);
		padding: 18px 0;
		display: grid;
		gap: 16px;
	}
	.heading {
		display: flex;
		justify-content: space-between;
		gap: 20px;
		align-items: flex-start;
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
		border-color: var(--danger, #b42318);
		color: var(--danger, #b42318);
	}
	dl {
		margin: 0;
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 14px;
	}
	dt {
		font-size: 12px;
		margin-bottom: 4px;
	}
	dd {
		margin: 0;
		line-height: 1.45;
		overflow-wrap: anywhere;
	}
	.actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
	}
	.scope-summary {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 13px;
	}
	@media (max-width: 760px) {
		.objectives-page {
			gap: 8px;
		}
		header {
			align-items: center;
			padding-bottom: 4px;
		}
		header p {
			display: none;
		}
		header .btn {
			min-height: 32px;
			padding: 0 12px;
		}
		.heading {
			flex-direction: column;
		}
		dl {
			grid-template-columns: 1fr 1fr;
		}
		.scope-options {
			grid-template-columns: 1fr;
		}
		.summary {
			grid-template-columns: repeat(3, minmax(0, 1fr));
		}
		.summary div {
			justify-items: center;
			padding: 4px;
			border-right: 1px solid var(--border-default);
			border-bottom: 0;
			text-align: center;
		}
		.summary div:last-child {
			border-right: 0;
		}
		.summary span {
			font-size: 11px;
		}
		article {
			padding: 10px 0;
		}
	}
</style>
