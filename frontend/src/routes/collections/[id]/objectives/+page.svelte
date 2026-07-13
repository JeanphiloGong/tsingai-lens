<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { errorMessage, getApiErrorCode } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		createConfirmedGoalFromObjective,
		fetchConfirmedGoals,
		fetchCollectionObjectives,
		fetchResearchUnderstandingDataset,
		getResearchViewStateTone,
		runGoalAnalysis,
		type ConfirmedGoal,
		type ObjectiveList,
		type ObjectiveListItem,
		type ResearchUnderstandingDataset
	} from '../../../_shared/researchView';

	let objectiveList: ObjectiveList | null = null;
	let confirmedGoals: ConfirmedGoal[] = [];
	let goalDatasetById = new Map<string, ResearchUnderstandingDataset>();
	let objectivesError = '';
	let goalReviewError = '';
	let objectivesNotReady = false;
	let loading = false;
	let goalReviewLoading = false;
	let loadedCollectionId = '';
	let analyzingObjectiveId = '';
	let analysisError = '';
	let objectivesRequestSequence = 0;
	let goalReviewRequestSequence = 0;

	$: collectionId = $page.params.id ?? '';
	$: objectives = objectiveList?.objectives ?? [];
	$: readyCount = objectives.filter((objective) => objective.state === 'ready').length;
	$: partialCount = objectives.filter((objective) => objective.state === 'partial').length;
	$: paperFrameCount = objectives.reduce(
		(total, objective) => total + objective.paper_frame_count,
		0
	);
	$: evidenceRouteCount = objectives.reduce(
		(total, objective) => total + objective.evidence_route_count,
		0
	);
	$: goalReviewSummary = buildGoalReviewSummary(confirmedGoals, goalDatasetById);
	$: goalReviewRows = buildGoalReviewRows(confirmedGoals, goalDatasetById);
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadObjectives();
	}

	async function loadObjectives() {
		const activeCollectionId = collectionId;
		const requestSequence = ++objectivesRequestSequence;
		loading = true;
		objectivesError = '';
		objectivesNotReady = false;
		analysisError = '';
		try {
			const nextObjectiveList = await fetchCollectionObjectives(activeCollectionId);
			if (requestSequence !== objectivesRequestSequence || activeCollectionId !== collectionId) return;
			objectiveList = nextObjectiveList;
			void loadGoalReviewStatus(activeCollectionId);
		} catch (err) {
			if (requestSequence !== objectivesRequestSequence || activeCollectionId !== collectionId) return;
			objectiveList = null;
			confirmedGoals = [];
			goalDatasetById = new Map();
			if (getApiErrorCode(err) === 'research_objectives_not_ready') {
				objectivesNotReady = true;
			} else {
				objectivesError = errorMessage(err);
			}
		} finally {
			if (requestSequence === objectivesRequestSequence && activeCollectionId === collectionId) {
				loading = false;
			}
		}
	}

	async function loadGoalReviewStatus(activeCollectionId = collectionId) {
		const requestSequence = ++goalReviewRequestSequence;
		goalReviewLoading = true;
		goalReviewError = '';
		try {
			const goalList = await fetchConfirmedGoals(activeCollectionId);
			if (requestSequence !== goalReviewRequestSequence || activeCollectionId !== collectionId) return;
			confirmedGoals = goalList.goals;
			const datasetEntries = await Promise.all(
				goalList.goals.map(async (goal) => {
					try {
						const dataset = await fetchResearchUnderstandingDataset(activeCollectionId, {
							scope_type: 'goal',
							scope_id: goal.goal_id
						});
						return [goal.goal_id, dataset] as const;
					} catch {
						return [goal.goal_id, null] as const;
					}
				})
			);
			if (requestSequence !== goalReviewRequestSequence || activeCollectionId !== collectionId) return;
			goalDatasetById = new Map(
				datasetEntries
					.filter((entry): entry is readonly [string, ResearchUnderstandingDataset] =>
						Boolean(entry[1])
					)
					.map(([goalId, dataset]) => [goalId, dataset])
			);
		} catch (err) {
			if (requestSequence !== goalReviewRequestSequence || activeCollectionId !== collectionId) return;
			confirmedGoals = [];
			goalDatasetById = new Map();
			goalReviewError = errorMessage(err);
		} finally {
			if (requestSequence === goalReviewRequestSequence && activeCollectionId === collectionId) {
				goalReviewLoading = false;
			}
		}
	}

	function objectiveStateTone(objective: ObjectiveListItem) {
		return getResearchViewStateTone(objective.state);
	}

	function listLabel(items: string[]) {
		return items.length ? items.slice(0, 5).join(', ') : $t('research.emptyValue');
	}

	function confidenceLabel(value: number) {
		return value > 0 ? `${Math.round(value * 100)}%` : $t('research.emptyValue');
	}

	function canAnalyzeObjective(objective: ObjectiveListItem) {
		return Boolean(objective.objective_id && objective.question);
	}

	function needsAnalysisCoverage(objective: ObjectiveListItem) {
		return (
			objective.paper_frame_count === 0 ||
			objective.evidence_route_count === 0 ||
			objective.evidence_unit_count === 0
		);
	}

	function buildGoalReviewSummary(
		goals: ConfirmedGoal[],
		datasets: Map<string, ResearchUnderstandingDataset>
	) {
		let trainingReady = 0;
		let trainingMessages = 0;
		let reviewCandidates = 0;
		for (const goal of goals) {
			const dataset = datasets.get(goal.goal_id);
			trainingReady += dataset?.quality_summary.training_ready_sample_count ?? 0;
			trainingMessages += dataset?.quality_summary.training_message_sample_count ?? 0;
			reviewCandidates += dataset?.quality_summary.review_candidate_sample_count ?? 0;
		}
		return {
			goalCount: goals.length,
			trainingReady,
			trainingMessages,
			reviewCandidates
		};
	}

	function buildGoalReviewRows(
		goals: ConfirmedGoal[],
		datasets: Map<string, ResearchUnderstandingDataset>
	) {
		return goals
			.map((goal, index) => {
				const dataset = datasets.get(goal.goal_id) ?? null;
				const status = goalReviewStatus(goal, dataset);
				return {
					goal,
					dataset,
					status,
					index,
					priority: goalReviewPriority(status)
				};
			})
			.sort(
				(left, right) =>
					left.priority - right.priority ||
					goalReviewCandidateCount(right.dataset) - goalReviewCandidateCount(left.dataset) ||
					left.index - right.index
			);
	}

	function goalReviewStatus(
		goal: ConfirmedGoal,
		dataset: ResearchUnderstandingDataset | null
	) {
		if (goal.status !== 'ready') return goal.status;
		if (!dataset) return 'dataset_pending';
		if (dataset.quality_summary.review_candidate_sample_count > 0) return 'needs_review';
		if (
			dataset.quality_summary.training_ready_sample_count > 0 &&
			dataset.quality_summary.training_message_sample_count > 0
		) {
			return 'training_ready';
		}
		return 'needs_review';
	}

	function goalReviewPriority(status: string) {
		if (status === 'needs_review') return 0;
		if (status === 'dataset_pending') return 1;
		if (status === 'failed') return 2;
		if (status === 'running' || status === 'pending') return 3;
		if (status === 'training_ready') return 4;
		return 5;
	}

	function goalReviewCandidateCount(dataset: ResearchUnderstandingDataset | null) {
		return dataset?.quality_summary.review_candidate_sample_count ?? 0;
	}

	function goalReviewStatusLabel(status: string) {
		return $t(`research.objectives.goalReviewStatuses.${status}`);
	}

	function goalReviewBody(dataset: ResearchUnderstandingDataset | null) {
		if (!dataset) return $t('research.objectives.goalReviewDatasetPending');
		return $t('research.objectives.goalReviewDatasetBody', {
			training: dataset.quality_summary.training_ready_sample_count,
			messages: dataset.quality_summary.training_message_sample_count,
			review: dataset.quality_summary.review_candidate_sample_count
		});
	}

	function goalReviewActionLabel(status: string) {
		if (status === 'needs_review') return $t('research.objectives.goalReviewActionReview');
		if (status === 'training_ready') return $t('research.objectives.goalReviewActionProtocol');
		if (status === 'failed') return $t('research.objectives.goalReviewActionRepair');
		if (status === 'running' || status === 'pending') {
			return $t('research.objectives.goalReviewActionWait');
		}
		return $t('research.objectives.goalReviewActionOpen');
	}

	function goalReviewHref(goal: ConfirmedGoal) {
		return resolve('/collections/[id]/goals/[goal_id]', {
			id: collectionId,
			goal_id: goal.goal_id
		});
	}

	async function confirmAndAnalyze(objective: ObjectiveListItem) {
		if (!canAnalyzeObjective(objective)) return;
		analyzingObjectiveId = objective.objective_id;
		analysisError = '';
		try {
			const goal = await createConfirmedGoalFromObjective(collectionId, objective);
			await runGoalAnalysis(collectionId, goal.goal_id);
			analyzingObjectiveId = '';
			await goto(
				resolve('/collections/[id]/goals/[goal_id]', {
					id: collectionId,
					goal_id: goal.goal_id
				})
			);
		} catch (err) {
			analysisError = errorMessage(err);
		} finally {
			analyzingObjectiveId = '';
		}
	}
</script>

<svelte:head>
	<title>{$t('research.objectives.title')}</title>
</svelte:head>

<section class="objectives-page fade-up">
	<header class="objectives-header">
		<div>
			<h2>{$t('research.objectives.title')}</h2>
			<p>{$t('research.objectives.body')}</p>
			{#if objectives.length}
				<div class="objectives-meta-row">
					<span>{$t('research.objectives.objectiveCount', { count: objectives.length })}</span>
					<span>{$t('research.objectives.paperFrameCount', { count: paperFrameCount })}</span>
					<span>{$t('research.objectives.routeCount', { count: evidenceRouteCount })}</span>
				</div>
			{/if}
		</div>
		<button class="btn btn--ghost" type="button" on:click={loadObjectives}>
			<span class="refresh-icon" aria-hidden="true"></span>
			{$t('research.objectives.refresh')}
		</button>
	</header>

	{#if loading}
		<section class="objectives-state-card" aria-busy="true" aria-live="polite">
			<div class="status" role="status">{$t('research.objectives.loading')}</div>
		</section>
	{:else if objectivesNotReady}
		<section class="objectives-state-card objectives-state-card--pending" role="status">
			<h3>{$t('research.objectives.pendingTitle')}</h3>
			<p>{$t('research.objectives.pendingBody')}</p>
			<div class="objectives-state-card__actions">
				<a class="btn btn--primary btn--small" href={resolve('/collections/[id]', { id: collectionId })}>
					{$t('research.objectives.openOverview')}
				</a>
				<button class="btn btn--ghost btn--small" type="button" on:click={loadObjectives}>
					{$t('research.objectives.refresh')}
				</button>
			</div>
		</section>
	{:else if objectivesError}
		<section class="objectives-state-card objectives-state-card--error" role="alert">
			<h3>{$t('research.objectives.errorTitle')}</h3>
			<p>{objectivesError}</p>
		</section>
	{:else if analysisError}
		<section class="objectives-state-card objectives-state-card--error" role="alert">
			<h3>{$t('research.objectives.analysisErrorTitle')}</h3>
			<p>{analysisError}</p>
		</section>
	{:else if !objectives.length}
		<section class="objectives-state-card">
			<h3>{$t('research.objectives.emptyTitle')}</h3>
			<p>{$t('research.objectives.emptyBody')}</p>
		</section>
	{:else}
		<section class="objectives-summary-grid" aria-label={$t('research.objectives.summaryTitle')}>
			<article>
				<span>{$t('research.state.ready')}</span>
				<strong>{readyCount}</strong>
			</article>
			<article>
				<span>{$t('research.state.partial')}</span>
				<strong>{partialCount}</strong>
			</article>
			<article>
				<span>{$t('research.objectives.paperFrames')}</span>
				<strong>{paperFrameCount}</strong>
			</article>
			<article>
				<span>{$t('research.objectives.routes')}</span>
				<strong>{evidenceRouteCount}</strong>
			</article>
		</section>

		<section class="goal-review-panel" aria-label={$t('research.objectives.goalReviewTitle')}>
			<div class="goal-review-panel__heading">
				<div>
					<h3>{$t('research.objectives.goalReviewTitle')}</h3>
					<p>
						{goalReviewLoading
							? $t('research.objectives.goalReviewLoading')
							: $t('research.objectives.goalReviewBody', {
									goals: goalReviewSummary.goalCount,
									training: goalReviewSummary.trainingReady,
									messages: goalReviewSummary.trainingMessages,
									review: goalReviewSummary.reviewCandidates
								})}
					</p>
				</div>
				<button
					class="btn btn--ghost btn--small"
					type="button"
					on:click={() => loadGoalReviewStatus()}
				>
					{$t('research.objectives.refreshGoalReview')}
				</button>
			</div>
			{#if goalReviewError}
				<p class="goal-review-panel__error" role="alert">
					{$t('research.objectives.goalReviewError', { message: goalReviewError })}
				</p>
			{:else if confirmedGoals.length}
				<div class="goal-review-panel__metrics">
					<span>
						{$t('research.objectives.goalReviewGoals')}
						<strong>{goalReviewSummary.goalCount}</strong>
					</span>
					<span>
						{$t('research.understanding.datasetTrainingReady')}
						<strong>{goalReviewSummary.trainingReady}</strong>
					</span>
					<span>
						{$t('research.understanding.datasetTrainingMessages')}
						<strong>{goalReviewSummary.trainingMessages}</strong>
					</span>
					<span>
						{$t('research.understanding.datasetReviewCandidate')}
						<strong>{goalReviewSummary.reviewCandidates}</strong>
					</span>
				</div>
				<div class="goal-review-list">
					{#each goalReviewRows as row (row.goal.goal_id)}
						<a href={goalReviewHref(row.goal)} class="goal-review-item">
							<div>
								<strong>{row.goal.question}</strong>
								<span>{goalReviewBody(row.dataset)}</span>
							</div>
							<small class={`goal-review-item__status goal-review-item__status--${row.status}`}>
								{goalReviewStatusLabel(row.status)}
							</small>
							<small class="goal-review-item__action">{goalReviewActionLabel(row.status)}</small>
						</a>
					{/each}
				</div>
			{:else}
				<p class="goal-review-panel__empty">{$t('research.objectives.goalReviewEmpty')}</p>
			{/if}
		</section>

		<section class="objectives-grid" aria-label={$t('research.objectives.title')}>
			{#each objectives as objective (objective.objective_id)}
				<article class="objective-card">
					<div class="objective-card__header">
						<div>
							<h3>{objective.question}</h3>
							<p>{objective.comparison_intent || $t('research.objectives.noIntent')}</p>
						</div>
						<span class={`status-badge status-badge--${objectiveStateTone(objective)}`}>
							{$t(`research.state.${objective.state}`)}
						</span>
					</div>

					<div class="objective-stat-row">
						<div>
							<span>{$t('research.objectives.confidence')}</span>
							<strong>{confidenceLabel(objective.confidence)}</strong>
						</div>
						<div>
							<span>{$t('research.objectives.paperFrames')}</span>
							<strong>{objective.paper_frame_count}</strong>
						</div>
						<div>
							<span>{$t('research.objectives.routes')}</span>
							<strong>{objective.evidence_route_count}</strong>
						</div>
						<div>
							<span>{$t('research.objectives.evidenceUnits')}</span>
							<strong>{objective.evidence_unit_count}</strong>
						</div>
					</div>

					<dl class="objective-fact-list">
						<div>
							<dt>{$t('research.objectives.materialScope')}</dt>
							<dd>{listLabel(objective.material_scope)}</dd>
						</div>
						<div>
							<dt>{$t('research.objectives.processAxes')}</dt>
							<dd>{listLabel(objective.process_axes)}</dd>
						</div>
						<div>
							<dt>{$t('research.objectives.propertyAxes')}</dt>
							<dd>{listLabel(objective.property_axes)}</dd>
						</div>
					</dl>

					<div class="objective-card__actions">
						<button
							class="btn btn--primary btn--small"
							type="button"
							disabled={Boolean(analyzingObjectiveId) || !canAnalyzeObjective(objective)}
							on:click={() => confirmAndAnalyze(objective)}
						>
							{analyzingObjectiveId === objective.objective_id
								? $t('research.objectives.analyzing')
								: $t('research.objectives.confirmAndAnalyze')}
						</button>
						<a
							class="btn btn--ghost btn--small"
							href={resolve('/collections/[id]/objectives/[objective_id]', {
								id: collectionId,
								objective_id: objective.objective_id
							})}
						>
							{$t('research.objectives.openWorkspace')}
						</a>
					</div>
					{#if needsAnalysisCoverage(objective)}
						<p class="objective-card__analysis-note">
							{$t('research.objectives.noAnalysisCoverage')}
						</p>
					{/if}
				</article>
			{/each}
		</section>
	{/if}
</section>

<style>
	.objectives-page {
		width: 100%;
		max-width: 1280px;
		margin: 0 auto;
		display: grid;
		gap: 22px;
	}

	.objectives-header,
	.objectives-state-card,
	.objective-card,
	.goal-review-panel,
	.objectives-summary-grid article {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.objectives-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 18px;
		padding: 24px;
	}

	.objectives-header h2,
	.objectives-state-card h3,
	.objective-card h3 {
		margin: 0;
		color: var(--text-primary);
	}

	.objectives-header h2 {
		font-size: 30px;
		line-height: 38px;
	}

	.objectives-header p,
	.objectives-state-card p,
	.objective-card p {
		max-width: 820px;
		margin: 8px 0 0;
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 23px;
	}

	.objectives-meta-row {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		margin-top: 12px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.objectives-state-card {
		display: grid;
		gap: 8px;
		padding: 24px;
	}

	.objectives-state-card--error {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.objectives-state-card--pending {
		border-color: var(--warning-border);
		background: var(--warning-bg);
	}

	.objectives-state-card__actions {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		margin-top: 8px;
	}

	.objectives-summary-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 12px;
	}

	.goal-review-panel {
		display: grid;
		gap: 14px;
		padding: 18px;
	}

	.goal-review-panel__heading {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 14px;
		min-width: 0;
	}

	.goal-review-panel__heading h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 18px;
		line-height: 26px;
	}

	.goal-review-panel__heading p,
	.goal-review-panel__empty,
	.goal-review-panel__error {
		margin: 6px 0 0;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
	}

	.goal-review-panel__error {
		color: var(--color-danger);
	}

	.goal-review-panel__metrics {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.goal-review-panel__metrics span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-height: 28px;
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 4px 9px;
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		white-space: nowrap;
	}

	.goal-review-panel__metrics strong {
		color: var(--text-primary);
		font-size: 12px;
		line-height: 18px;
	}

	.goal-review-list {
		display: grid;
		gap: 8px;
	}

	.goal-review-item {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto auto;
		gap: 12px;
		align-items: center;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 11px 12px;
		background: var(--bg-subtle);
		color: inherit;
		text-decoration: none;
	}

	.goal-review-item:hover,
	.goal-review-item:focus-visible {
		border-color: var(--color-accent);
	}

	.goal-review-item div {
		display: grid;
		gap: 3px;
		min-width: 0;
	}

	.goal-review-item strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 21px;
		overflow-wrap: anywhere;
	}

	.goal-review-item span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.goal-review-item__status {
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 3px 8px;
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 750;
		line-height: 18px;
		white-space: nowrap;
	}

	.goal-review-item__status--needs_review,
	.goal-review-item__status--dataset_pending,
	.goal-review-item__status--pending,
	.goal-review-item__status--running {
		border-color: rgba(217, 119, 6, 0.36);
		background: rgba(217, 119, 6, 0.08);
		color: #92400e;
	}

	.goal-review-item__status--training_ready {
		border-color: rgba(22, 163, 74, 0.34);
		background: rgba(22, 163, 74, 0.08);
		color: #166534;
	}

	.goal-review-item__status--failed {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.goal-review-item__action {
		color: var(--color-accent);
		font-size: 12px;
		font-weight: 750;
		line-height: 18px;
		white-space: nowrap;
	}

	.objectives-summary-grid article {
		display: grid;
		gap: 4px;
		padding: 18px;
	}

	.objectives-summary-grid span,
	.objective-stat-row span,
	.objective-fact-list dt {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.objectives-summary-grid strong,
	.objective-stat-row strong {
		color: var(--text-primary);
		font-size: 24px;
		line-height: 30px;
	}

	.objectives-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
		gap: 14px;
	}

	.objective-card {
		display: grid;
		gap: 18px;
		padding: 20px;
	}

	.objective-card__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}

	.objective-card h3 {
		font-size: 18px;
		line-height: 26px;
	}

	.objective-stat-row {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 10px;
	}

	.objective-stat-row div {
		display: grid;
		gap: 3px;
		min-width: 0;
	}

	.objective-fact-list {
		display: grid;
		gap: 10px;
		margin: 0;
	}

	.objective-fact-list div {
		display: grid;
		gap: 4px;
	}

	.objective-fact-list dd {
		margin: 0;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
	}

	.objective-card__actions {
		display: flex;
		justify-content: flex-end;
		gap: 10px;
		flex-wrap: wrap;
	}

	.objective-card__analysis-note {
		margin: -8px 0 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.refresh-icon {
		width: 13px;
		height: 13px;
		border: 2px solid currentColor;
		border-left-color: transparent;
		border-radius: 50%;
		display: inline-block;
	}

	@media (max-width: 760px) {
		.objectives-header,
		.objective-card__header {
			flex-direction: column;
		}

		.objectives-summary-grid,
		.objective-stat-row {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.goal-review-panel__heading,
		.goal-review-item {
			grid-template-columns: 1fr;
		}
	}
</style>
