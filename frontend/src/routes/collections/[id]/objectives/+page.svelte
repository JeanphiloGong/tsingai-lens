<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { onDestroy } from 'svelte';
	import { errorMessage } from '../../../_shared/api';
	import {
		listCollectionDocuments,
		type CollectionDocument
	} from '../../../_shared/collectionDocuments';
	import {
		fetchCollectionObjectives,
		fetchObjectiveAnalysis,
		fetchObjectiveAnalysisStatus,
		fetchObjectiveScope,
		runObjectiveAnalysis,
		type ObjectiveAnalysisState,
		type ObjectiveAnalysisProgress,
		type ObjectiveList,
		type ObjectiveScope,
		type ObjectiveScopeDecision,
		type ObjectiveSummary
	} from '../../../_shared/researchView';
	import { t } from '../../../_shared/i18n';

	const OBJECTIVE_PAGE_SIZE = 5;
	const SCOPE_PAGE_SIZE = 8;
	const ANALYSIS_POLL_DELAY_MS = 2500;
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
	let analysisPollTimer: ReturnType<typeof setTimeout> | null = null;
	let disposed = false;

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

	onDestroy(() => {
		disposed = true;
		clearAnalysisPoll();
	});

	function clearAnalysisPoll() {
		if (analysisPollTimer) clearTimeout(analysisPollTimer);
		analysisPollTimer = null;
	}

	function scheduleAnalysisPoll() {
		clearAnalysisPoll();
		if (disposed) return;
		if (!Object.values(analysisStates).some(isAnalysisProcessing)) return;
		analysisPollTimer = setTimeout(() => void pollActiveAnalyses(), ANALYSIS_POLL_DELAY_MS);
	}

	async function pollActiveAnalyses() {
		if (disposed) return;
		const objectiveIds = Object.entries(analysisStates)
			.filter(([, analysis]) => isAnalysisProcessing(analysis))
			.map(([objectiveId]) => objectiveId);
		if (!objectiveIds.length) return;
		try {
			const snapshots = await Promise.all(
				objectiveIds.map((objectiveId) => fetchObjectiveAnalysisStatus(collectionId, objectiveId))
			);
			if (disposed) return;
			for (const snapshot of snapshots) {
				if (snapshot.status === 'succeeded' || snapshot.status === 'failed') {
					const analysis = await fetchObjectiveAnalysis(collectionId, snapshot.objective_id);
					if (disposed) return;
					applyAnalysisSnapshot(analysis);
				} else {
					applyAnalysisStatus(snapshot);
				}
			}
		} catch (err) {
			error = errorMessage(err);
		}
		scheduleAnalysisPoll();
	}

	function applyAnalysisSnapshot(snapshot: Awaited<ReturnType<typeof fetchObjectiveAnalysis>>) {
		if (objectiveList) {
			objectiveList = {
				...objectiveList,
				objectives: objectiveList.objectives.map((objective) =>
					objective.objective_id === snapshot.objective.objective_id
						? snapshot.objective
						: objective
				)
			};
		}
		analysisStates = {
			...analysisStates,
			[snapshot.objective.objective_id]: snapshot.active_analysis
		};
	}

	function applyAnalysisStatus(status: ObjectiveAnalysisProgress) {
		const previous = analysisStates[status.objective_id];
		if (!previous) return;
		analysisStates = {
			...analysisStates,
			[status.objective_id]: { ...previous, ...status }
		};
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
			const listing = await fetchCollectionObjectives(collectionId);
			if (disposed) return;
			objectiveList = listing;
			await refreshActiveAnalysisStates();
			if (disposed) return;
			scopesByObjective = {};
			selectedDocumentIdsByObjective = {};
			objectivePage = 0;
		} catch (err) {
			objectiveList = null;
			analysisStates = {};
			error = errorMessage(err);
		} finally {
			loading = false;
			scheduleAnalysisPoll();
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
		if (!disposed) analysisStates = Object.fromEntries(states);
	}

	function analysisStatus(objective: ObjectiveSummary) {
		return analysisStates[objective.objective_id]?.status ?? null;
	}

	function statusLabel(objective: ObjectiveSummary, translate = $t) {
		const active = analysisStates[objective.objective_id];
		if (active?.status === 'queued') return translate('objectiveWorkspace.pending');
		if (active?.status === 'running') return translate('objectiveWorkspace.active');
		if (active?.status === 'failed') return translate('objectiveWorkspace.failed');
		if (objective.published_analysis_version !== null) {
			return translate('research.objectives.labels.resultVVersion', { version: objective.published_analysis_version });
		}
		if (objective.active_analysis_version !== null) return translate('objectiveWorkspace.active');
		return objective.confirmation_status === 'confirmed' ? translate('research.objectives.confirmed') : translate('research.objectives.candidate');
	}

	function canStartAnalysis(objective: ObjectiveSummary) {
		return objective.active_analysis_version === null || analysisStatus(objective) === 'failed';
	}

	function actionLabel(objective: ObjectiveSummary, translate = $t) {
		if (analysisStatus(objective) === 'failed') return translate('objectiveWorkspace.retryAnalysis');
		return objective.confirmation_status === 'candidate' ? translate('research.objectives.confirmAndAnalyze') : translate('research.objectives.startAnalysis');
	}

	function isAnalysisProcessing(analysis: ObjectiveAnalysisState | null) {
		return analysis?.status === 'queued' || analysis?.status === 'running';
	}

	function analysisProgressPercent(analysis: ObjectiveAnalysisState) {
		if (analysis.total_document_count <= 0) return 0;
		const processed = Math.max(
			0,
			Math.min(analysis.processed_document_count, analysis.total_document_count)
		);
		return Math.round((processed / analysis.total_document_count) * 100);
	}

	function analysisPhaseLabel(analysis: ObjectiveAnalysisState, translate = $t) {
		if (analysis.status === 'queued') return translate('research.objectives.labels.waitingForAnalysisToStart');
		const phase = analysis.phase.toLocaleLowerCase();
		if (phase.includes('framing') || phase.includes('routing')) {
			return translate('research.objectives.labels.locatingPaperContentRelevantToTheResearch');
		}
		if (phase.includes('evidence') || phase.includes('extraction')) {
			return translate('research.objectives.labels.extractingEvidenceFromEachPaper');
		}
		if (phase.includes('finding') || phase.includes('synthesis')) {
			return translate('research.objectives.labels.comparingEvidenceAcrossPapersAndFormingFindings');
		}
		return translate('research.objectives.labels.analyzingTheConfirmedPaperScope');
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
				scopeError = $t('research.objectives.labels.noReadyPapersAreAvailableInThe');
				return;
			}

			selectedDocumentIdsByObjective = {
				...selectedDocumentIdsByObjective,
				[objective.objective_id]: documentIds
			};
			const snapshot = await runObjectiveAnalysis(
				collectionId,
				objective.objective_id,
				documentIds
			);
			applyAnalysisSnapshot(snapshot);
			scheduleAnalysisPoll();
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
			const snapshot = await runObjectiveAnalysis(
				collectionId,
				objective.objective_id,
				documentIds
			);
			applyAnalysisSnapshot(snapshot);
			scopeObjectiveId = '';
			scopeError = '';
			scheduleAnalysisPoll();
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

	function scopeDecisionLabel(documentId: string, translate = $t) {
		const decision = scopeDecision(documentId);
		if (!decision) return translate('research.objectives.labels.scopeAssessmentPending');
		if (decision.classification === 'likely_relevant') return translate('research.objectives.labels.recommended');
		if (decision.classification === 'needs_inspection') return translate('research.objectives.labels.needsInspection');
		return translate('research.objectives.labels.notCurrentlyRecommended');
	}

	function confirmActionLabel(objective: ObjectiveSummary, count: number, translate = $t) {
		if (!count) return translate('research.objectives.labels.selectPapersToStartAnalysis');
		return analysisStatus(objective) === 'failed'
			? translate('research.objectives.labels.reanalyzeCountPapers', { count })
			: translate('research.objectives.labels.analyzeCountPapers', { count });
	}
</script>

<svelte:head><title>{$t('objectiveWorkspace.list')}</title></svelte:head>

<section class="objectives-page">
	<header class="page-heading">
		<div>
			<h2>{$t('objectiveWorkspace.list')}</h2>
			<p>{$t('research.objectives.description')}</p>
		</div>
		<button class="btn btn--ghost" type="button" on:click={loadObjectives}>{$t('research.objectives.refresh')}</button>
	</header>

	{#if loading}
		<p class="state" aria-busy="true">{$t('research.objectives.loading')}</p>
	{:else if error}
		<p class="state state--error" role="alert">{error}</p>
	{:else if !objectives.length}
		<section class="empty-state">
			<h3>{$t('research.objectives.labels.noResearchObjectivesToConfirm')}</h3>
			<p>
				{$t('research.objectives.labels.noCandidatesCurrentlySatisfyTheMaterialScope')}
			</p>
			<div class="actions">
				<a
					class="btn btn--ghost btn--small"
					href={resolve('/collections/[id]', { id: collectionId })}
				>
					{$t('research.objectives.labels.backToCollectionOverview')}
				</a>
				<a
					class="btn btn--primary btn--small"
					href={resolve('/collections/[id]/documents', { id: collectionId })}
				>
					{$t('research.objectives.labels.inspectPapers')}
				</a>
			</div>
		</section>
	{:else}
		<div class="summary" aria-label={$t('research.objectives.labels.researchObjectiveOverview')}>
			<div><strong>{objectives.length}</strong><span>{$t('research.objectives.labels.researchObjectives')}</span></div>
			<div><strong>{confirmedCount}</strong><span>{$t('research.objectives.labels.confirmed')}</span></div>
			<div><strong>{publishedCount}</strong><span>{$t('research.objectives.labels.resultsAvailable')}</span></div>
		</div>

		<div class="objective-filters" role="search" aria-label={$t('research.objectives.labels.filterResearchObjectives')}>
			<label>
				<span>{$t('research.objectives.search')}</span>
				<input type="search" bind:value={objectiveQuery} placeholder={$t('research.objectives.labels.questionMaterialVariableOrOutcome')} />
			</label>
			<label>
				<span>{$t('research.objectives.status')}</span>
				<select bind:value={objectiveFilterStatus}>
					<option value="all">{$t('research.objectives.allStatus')}</option>
					<option value="pending">{$t('research.objectives.pendingStatus')}</option>
					<option value="active">{$t('research.objectives.activeStatus')}</option>
					<option value="published">{$t('research.objectives.publishedStatus')}</option>
					<option value="failed">{$t('research.objectives.failedStatus')}</option>
				</select>
			</label>
			{#if objectiveFiltersActive}
				<button class="btn btn--ghost btn--small" type="button" on:click={clearObjectiveFilters}>
					{$t('research.objectives.clear')}
				</button>
			{/if}
		</div>

		{#if objectiveFiltersActive}
			<p class="filter-count" aria-live="polite">{$t('research.objectives.labels.foundCountResearchObjectives', { count: filteredObjectives.length })}</p>
		{/if}

		{#if !filteredObjectives.length}
			<section class="filter-empty">
				<h3>{$t('research.objectives.noMatch')}</h3>
				<p>{$t('research.objectives.adjust')}</p>
				<button class="btn btn--ghost btn--small" type="button" on:click={clearObjectiveFilters}>
					{$t('research.objectives.labels.clearFilters')}
				</button>
			</section>
		{:else}
			<div class="objective-list">
				{#each visibleObjectives as objective (objective.objective_id)}
					{@const activeAnalysis = analysisStates[objective.objective_id] ?? null}
					{@const objectiveHref = resolve('/collections/[id]/objectives/[objective_id]', {
						id: collectionId,
						objective_id: objective.objective_id
					})}
					<article>
						<div class="heading">
							<div>
								<h3><a href={objectiveHref}>{objective.question}</a></h3>
								<p>{objective.requested_comparator || $t('research.objectives.labels.noComparisonIntentSpecified')}</p>
							</div>
							<span
								class:published={objective.published_analysis_version !== null}
								class:failed={analysisStatus(objective) === 'failed'}
							>
								{statusLabel(objective, $t)}
							</span>
						</div>
						<dl>
							<div>
								<dt>{$t('research.objectives.labels.material')}</dt>
								<dd>{joined(objective.material_scope)}</dd>
							</div>
							<div>
								<dt>{$t('research.objectives.labels.variables')}</dt>
								<dd>{joined(objective.variables)}</dd>
							</div>
							<div>
								<dt>{$t('research.objectives.labels.outcomes')}</dt>
								<dd>{joined(objective.outcomes)}</dd>
							</div>
							<div>
								<dt>{$t('research.objectives.labels.questionSources')}</dt>
								<dd>{$t('research.objectives.labels.countPapers', { count: objective.seed_document_ids.length })}</dd>
							</div>
						</dl>
						{#if activeAnalysis && isAnalysisProcessing(activeAnalysis)}
							{@const progressPercent = analysisProgressPercent(activeAnalysis)}
							<div class="analysis-progress" role="status" aria-live="polite">
								<div class="analysis-progress__header">
									<strong>{analysisPhaseLabel(activeAnalysis, $t)}</strong>
									{#if activeAnalysis.total_document_count > 0}
										<span
											>{$t('research.objectives.labels.paperProgressDoneTotal', { done: activeAnalysis.processed_document_count, total: activeAnalysis.total_document_count })}</span
										>
									{/if}
								</div>
								{#if activeAnalysis.total_document_count > 0}
									<div
										class="analysis-progress__track"
										role="progressbar"
										aria-label={$t('research.objectives.labels.researchObjectiveAnalysisProgress')}
										aria-valuemin="0"
										aria-valuemax="100"
										aria-valuenow={progressPercent}
										aria-valuetext={$t('research.objectives.labels.paperProgressDoneTotal', { done: activeAnalysis.processed_document_count, total: activeAnalysis.total_document_count })}
									>
										<span style={`width: ${progressPercent}%`}></span>
									</div>
								{/if}
							</div>
						{/if}
						{#if activeAnalysis?.status === 'failed'}
							<p class="analysis-error" role="alert">
								{$t('researchAgent.capability.analysisFailed')}
							</p>
						{/if}
						<div class="actions">
							{#if canStartAnalysis(objective)}
								<button
									class="btn btn--primary btn--small"
									type="button"
									disabled={Boolean(actionObjectiveId)}
									on:click={() => void startRecommendedAnalysis(objective)}
								>
									{actionObjectiveId === objective.objective_id
										? $t('research.objectives.labels.preparing')
										: actionLabel(objective, $t)}
								</button>
								<button
									class="btn btn--ghost btn--small"
									type="button"
									disabled={Boolean(actionObjectiveId)}
									title={$t('research.objectives.labels.useTheRecommendedPaperScopeByDefault')}
									on:click={() => void openScopeReview(objective)}
								>
									{$t('research.objectives.labels.adjustScope')}
								</button>
							{/if}
							{#if objective.published_analysis_version !== null}
								<a class="btn btn--ghost btn--small" href={objectiveHref}>{$t('research.objectives.labels.viewFindings')}</a>
							{:else if activeAnalysis?.status === 'failed'}
								<a class="btn btn--ghost btn--small" href={objectiveHref}>{$t('research.objectives.labels.viewFailureDetails')}</a>
							{/if}
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
					<span>{$t('research.objectives.labels.confirmBeforeAnalysis')}</span>
					<h2 id="scope-dialog-title">{$t('research.objectives.labels.confirmPapersForAnalysis')}</h2>
				</div>
				<button
					class="close-button"
					type="button"
					aria-label={$t('research.objectives.labels.closePaperScope')}
					on:click={closeScopeReview}>×</button
				>
			</header>

			<div class="scope-question">
				<strong>{scopeObjective.question}</strong>
				<p>{$t('research.objectives.labels.onlyThePapersConfirmedHereWillBe')}</p>
			</div>
			{#if activeScope}
				<div class="scope-summary" aria-label={$t('research.objectives.labels.paperScopeAssessmentOverview')}>
					<span>{$t('research.objectives.labels.countRecommendedPapers', { count: activeScope.counts.likely_relevant })}</span>
					<span>{$t('research.objectives.labels.countPapersNeedingInspection', { count: activeScope.counts.needs_inspection })}</span>
					<span>{$t('research.objectives.labels.countQuestionSourcePapers', { count: scopeObjective.seed_document_ids.length })}</span>
				</div>
			{/if}

			<div class="scope-toolbar">
				<label class="scope-search">
					<span>{$t('research.objectives.labels.searchAvailablePapers')}</span>
					<input
						type="search"
						value={scopeQuery}
						on:input={(event) => updateScopeQuery((event.currentTarget as HTMLInputElement).value)}
					/>
				</label>
				<strong>{$t('research.objectives.labels.selectedCountPapers', { count: selectedScopeIds.length })}</strong>
			</div>

			{#if scopeLoading}
				<p class="scope-state" aria-busy="true">{$t('research.objectives.labels.loadingAvailablePapers')}</p>
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
									{scopeDecisionLabel(document.document_id, $t)}{scopeDecision(document.document_id)
										?.is_seed
										? $t('research.objectives.labels.questionSource')
										: ''}
								</small>
							</span>
						</label>
					{/each}
				</div>
				<nav class="scope-pagination" aria-label={$t('research.objectives.labels.paperScopePages')}>
					<button type="button" disabled={scopePage === 0} on:click={() => (scopePage -= 1)}
						>{$t('research.objectives.labels.previous')}</button
					>
					<span>{$t('research.objectives.labels.pagePageTotal', { page: scopePage + 1, total: scopePageCount })}</span>
					<button
						type="button"
						disabled={scopePage + 1 >= scopePageCount}
						on:click={() => (scopePage += 1)}
					>
						{$t('research.objectives.labels.next')}
					</button>
				</nav>
			{:else if readyDocuments.length}
				<p class="scope-state">{$t('research.objectives.labels.noMatchingReadyPapers')}</p>
			{:else}
				<p class="scope-state">{$t('research.objectives.labels.noReadyPapersAvailableForAnalysis')}</p>
			{/if}

			<footer>
				{#if !selectedScopeIds.length && !scopeLoading}
					<p>{$t('research.objectives.labels.selectAtLeastOnePaper')}</p>
				{/if}
				<div>
					<button class="btn btn--ghost" type="button" on:click={closeScopeReview}>{$t('research.objectives.labels.cancel')}</button>
					<button
						class="btn btn--primary"
						type="button"
						disabled={!selectedScopeIds.length || scopeLoading || Boolean(actionObjectiveId)}
						on:click={() => void startAnalysis(scopeObjective)}
					>
						{actionObjectiveId
							? $t('research.objectives.labels.starting')
							: confirmActionLabel(scopeObjective, selectedScopeIds.length, $t)}
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
	.analysis-error,
	.scope-state--error,
	.scope-dialog footer > p {
		color: var(--danger-text, #b42318);
	}

	.analysis-error {
		font-size: 13px;
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

	.heading h3 a {
		color: inherit;
		text-decoration: none;
	}

	.heading h3 a:hover {
		text-decoration: underline;
		text-underline-offset: 3px;
	}

	.heading h3 a:focus-visible {
		outline: 2px solid var(--accent-primary, #2563eb);
		outline-offset: 3px;
	}

	.heading p {
		margin-top: 5px;
	}

	.heading > span {
		align-self: flex-start;
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

	.analysis-progress {
		max-width: 680px;
		display: grid;
		gap: 8px;
		padding: 12px 14px;
		border-left: 3px solid #3676a8;
		background: var(--surface-subtle);
	}

	.analysis-progress__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		font-size: 13px;
	}

	.analysis-progress__header span {
		color: var(--text-secondary);
		white-space: nowrap;
	}

	.analysis-progress__track {
		height: 7px;
		overflow: hidden;
		border-radius: 4px;
		background: var(--border-default);
	}

	.analysis-progress__track span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: var(--accent-primary, #2563eb);
		transition: width 180ms ease;
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
		.analysis-progress__header,
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
