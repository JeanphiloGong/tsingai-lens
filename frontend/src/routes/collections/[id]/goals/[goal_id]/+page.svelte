<script lang="ts">
	import { browser } from '$app/environment';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import ResearchUnderstandingWorkbench from '../../_components/ResearchUnderstandingWorkbench.svelte';
	import { errorMessage } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import {
		fetchGoalAnalysis,
		runGoalAnalysis,
		type GoalAnalysis
	} from '../../../../_shared/researchView';

	let analysis: GoalAnalysis | null = null;
	let loading = false;
	let running = false;
	let error = '';
	let loadedKey = '';

	$: collectionId = $page.params.id ?? '';
	$: goalId = $page.params.goal_id ?? '';
	$: loadKey = `${collectionId}:${goalId}`;
	$: goal = analysis?.goal ?? null;
	$: understanding = analysis?.understanding ?? null;
	$: if (browser && collectionId && goalId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		void loadAnalysis();
	}

	async function loadAnalysis() {
		loading = true;
		error = '';
		try {
			analysis = await fetchGoalAnalysis(collectionId, goalId);
		} catch (err) {
			analysis = null;
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	async function rerunAnalysis() {
		running = true;
		error = '';
		try {
			analysis = await runGoalAnalysis(collectionId, goalId);
		} catch (err) {
			error = errorMessage(err);
		} finally {
			running = false;
		}
	}

	function statusLabel(status: string | null | undefined) {
		if (!status) return $t('research.emptyValue');
		return status.replace(/_/g, ' ');
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
					{#if goal.source_objective_id}
						<span>{goal.source_objective_id}</span>
					{/if}
				</div>
			{/if}
		</div>
		<div class="goal-actions">
			<button class="btn btn--ghost btn--small" type="button" on:click={loadAnalysis}>
				{$t('research.objectives.refresh')}
			</button>
			<button
				class="btn btn--primary btn--small"
				type="button"
				disabled={running}
				on:click={rerunAnalysis}
			>
				{running ? $t('research.objectives.analyzing') : $t('research.objectives.confirmAndAnalyze')}
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
	.goal-state {
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

	.goal-state--error {
		border-color: rgba(185, 28, 28, 0.28);
		background: rgba(254, 242, 242, 0.72);
	}

	@media (max-width: 760px) {
		.goal-header {
			display: grid;
		}
	}
</style>
