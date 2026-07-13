<script lang="ts">
	import { browser } from '$app/environment';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { onDestroy } from 'svelte';
	import ResearchUnderstandingWorkbench from '../../_components/ResearchUnderstandingWorkbench.svelte';
	import { errorMessage } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import {
		fetchGoalAnalysis,
		runGoalAnalysis,
		type GoalAnalysis,
		type GoalAnalysisProgress
	} from '../../../../_shared/researchView';

	const POLL_DELAY_MS = 2500;

	let analysis: GoalAnalysis | null = null;
	let loading = false;
	let running = false;
	let error = '';
	let loadedKey = '';
	let pollTimer: ReturnType<typeof setTimeout> | null = null;

	$: collectionId = $page.params.id ?? '';
	$: goalId = $page.params.goal_id ?? '';
	$: loadKey = `${collectionId}:${goalId}`;
	$: goal = analysis?.goal ?? null;
	$: understanding = analysis?.understanding ?? null;
	$: progress = goal?.analysis_progress ?? null;
	$: isAnalysisRunning = goal?.status === 'running';
	$: analysisErrors = analysis?.errors ?? [];
	$: analysisWarnings = analysis?.warnings ?? [];
	$: hasAnalysisErrors = analysisErrors.length > 0;
	$: hasAnalysisWarnings = analysisWarnings.length > 0;
	$: hasReviewableUnderstanding =
		((understanding?.presentation?.primary_findings?.length ?? 0) > 0 ||
			(understanding?.presentation?.review_queue_findings?.length ?? 0) > 0);
	$: progressPercent = progressPercentLabel(progress);
	$: currentDocumentLabel = progressDocumentLabel(progress);
	$: if (browser && collectionId && goalId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		clearPoll();
		void loadAnalysis();
	}

	onDestroy(() => {
		clearPoll();
	});

	async function loadAnalysis() {
		loading = true;
		error = '';
		try {
			analysis = await fetchGoalAnalysis(collectionId, goalId);
			schedulePollIfRunning();
		} catch (err) {
			analysis = null;
			error = errorMessage(err);
			clearPoll();
		} finally {
			loading = false;
		}
	}

	async function rerunAnalysis() {
		running = true;
		error = '';
		try {
			analysis = await runGoalAnalysis(collectionId, goalId);
			schedulePollIfRunning();
		} catch (err) {
			error = errorMessage(err);
			clearPoll();
		} finally {
			running = false;
		}
	}

	function clearPoll() {
		if (pollTimer) {
			clearTimeout(pollTimer);
			pollTimer = null;
		}
	}

	function schedulePollIfRunning() {
		clearPoll();
		if (!browser || analysis?.goal.status !== 'running') return;
		pollTimer = setTimeout(() => {
			void refreshAnalysis();
		}, POLL_DELAY_MS);
	}

	async function refreshAnalysis() {
		try {
			analysis = await fetchGoalAnalysis(collectionId, goalId);
			error = '';
			schedulePollIfRunning();
		} catch (err) {
			error = errorMessage(err);
			clearPoll();
		}
	}

	function statusLabel(status: string | null | undefined) {
		if (!status) return $t('research.emptyValue');
		return status.replace(/_/g, ' ');
	}

	function progressDocumentLabel(value: GoalAnalysisProgress | null) {
		return (
			value?.active_document_title ||
			value?.active_source_filename ||
			$t('research.goalWorkspace.waitingDocument')
		);
	}

	function progressPercentLabel(value: GoalAnalysisProgress | null) {
		if (!value?.current || !value.total || value.total <= 0) return '';
		return `${value.current}/${value.total} ${value.unit ?? ''}`.trim();
	}
</script>

<svelte:head>
	<title>{goal?.question ?? goalId}</title>
</svelte:head>

<section class="goal-page fade-up">
	<nav class="breadcrumb" aria-label="Breadcrumb">
		<a href={resolve('/collections/[id]/objectives', { id: collectionId })}>
			{$t('research.objectiveWorkspace.back')}
		</a>
		<span>{goal?.question ?? goalId}</span>
	</nav>

	<header class="goal-header">
		<div>
			<p class="eyebrow">{$t('research.goalWorkspace.eyebrow')}</p>
			<h2>{goal?.question ?? goalId}</h2>
			{#if goal}
				<div class="goal-meta">
					<span>{statusLabel(goal.status)}</span>
				</div>
			{/if}
		</div>
		<div class="goal-actions">
			<a
				class="btn btn--ghost btn--small"
				href={`${resolve('/collections/[id]/assistant', {
					id: collectionId
				})}?goal_id=${encodeURIComponent(goalId)}`}
			>
				{$t('research.goalWorkspace.askCopilot')}
			</a>
			<button class="btn btn--ghost btn--small" type="button" on:click={loadAnalysis}>
				{$t('research.objectives.refresh')}
			</button>
			<button
				class="btn btn--primary btn--small"
				type="button"
				disabled={running || isAnalysisRunning}
				on:click={rerunAnalysis}
			>
				{running || isAnalysisRunning
					? $t('research.objectives.analyzing')
					: $t('research.objectives.confirmAndAnalyze')}
			</button>
		</div>
	</header>

	{#if loading}
		<section class="goal-state" aria-busy="true" aria-live="polite">
			<div class="status" role="status">{$t('research.objectiveWorkspace.loading')}</div>
		</section>
	{:else if error}
		<section class="goal-state goal-state--error" role="alert">
			<h3>{$t('research.objectives.analysisErrorTitle')}</h3>
			<p>{error}</p>
		</section>
	{:else if !analysis}
		<section class="goal-state">
			<h3>{$t('research.objectiveWorkspace.emptyTitle')}</h3>
			<p>{$t('research.objectiveWorkspace.emptyBody')}</p>
		</section>
	{:else}
		{#if hasAnalysisErrors}
			<section class="goal-state goal-state--error" role="alert">
				<h3>{$t('research.objectives.analysisErrorTitle')}</h3>
				{#each analysisErrors as item}
					<p>{item}</p>
				{/each}
			</section>
		{/if}
		{#if !hasAnalysisErrors && hasAnalysisWarnings}
			<section class="goal-state goal-state--warning" role="status">
				<h3>{$t('research.objectives.analysisWarningTitle')}</h3>
				{#each analysisWarnings as item}
					<p>{item}</p>
				{/each}
			</section>
		{/if}
		{#if isAnalysisRunning}
			<section class="goal-progress" aria-live="polite" aria-busy="true">
				<div>
					<p class="goal-progress__eyebrow">{$t('research.goalWorkspace.progressEyebrow')}</p>
					<h3>{$t('research.goalWorkspace.progressTitle')}</h3>
					<p>{progress?.message ?? $t('research.goalWorkspace.progressBody')}</p>
				</div>
				<div class="goal-progress__grid">
					<div>
						<span>{$t('research.goalWorkspace.phase')}</span>
						<strong>{statusLabel(progress?.phase ?? 'running')}</strong>
					</div>
					<div>
						<span>{$t('research.goalWorkspace.currentDocument')}</span>
						<strong>{currentDocumentLabel}</strong>
					</div>
					{#if progressPercent}
						<div>
							<span>{$t('research.goalWorkspace.stepProgress')}</span>
							<strong>{progressPercent}</strong>
						</div>
					{/if}
				</div>
			</section>
		{/if}
		{#if !hasAnalysisErrors || hasReviewableUnderstanding}
			<ResearchUnderstandingWorkbench
				{understanding}
				{collectionId}
				returnTo={resolve('/collections/[id]/goals/[goal_id]', {
					id: collectionId,
					goal_id: goalId
				})}
				bodyKey="research.understanding.objectiveBody"
				titleId="goal-understanding-title"
			/>
		{/if}
	{/if}
</section>

<style>
	.goal-page {
		width: 100%;
		max-width: 1280px;
		margin: 0 auto;
		display: grid;
		gap: 18px;
	}

	.breadcrumb {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.breadcrumb a {
		color: var(--accent);
		text-decoration: none;
	}

	.goal-header,
	.goal-state,
	.goal-progress {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.goal-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 18px;
		padding: 24px;
	}

	.eyebrow {
		margin: 0 0 6px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.goal-header h2,
	.goal-state h3 {
		margin: 0;
		color: var(--text-primary);
	}

	.goal-header h2 {
		max-width: 860px;
		font-size: 28px;
		line-height: 36px;
	}

	.goal-meta,
	.goal-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
	}

	.goal-meta {
		margin-top: 12px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
		text-transform: capitalize;
	}

	.goal-state {
		padding: 24px;
	}

	.goal-state p {
		margin: 8px 0 0;
		color: var(--text-secondary);
	}

	.goal-progress {
		display: grid;
		gap: 18px;
		padding: 22px 24px;
	}

	.goal-progress__eyebrow {
		margin: 0 0 6px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.goal-progress h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 18px;
		line-height: 26px;
	}

	.goal-progress p {
		margin: 8px 0 0;
		color: var(--text-secondary);
	}

	.goal-progress__grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 12px;
	}

	.goal-progress__grid div {
		min-width: 0;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		background: var(--bg-subtle);
	}

	.goal-progress__grid span,
	.goal-progress__grid strong {
		display: block;
	}

	.goal-progress__grid span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.goal-progress__grid strong {
		margin-top: 4px;
		overflow-wrap: anywhere;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 20px;
	}

	.goal-state--error {
		border-color: rgba(185, 28, 28, 0.28);
		background: rgba(254, 242, 242, 0.72);
	}

	.goal-state--warning {
		border-color: rgba(217, 119, 6, 0.32);
		background: rgba(255, 251, 235, 0.86);
	}

	@media (max-width: 760px) {
		.goal-header {
			display: grid;
		}

		.goal-progress__grid {
			grid-template-columns: 1fr;
		}
	}
</style>
