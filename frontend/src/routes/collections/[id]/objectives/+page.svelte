<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage, getApiErrorCode } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		confirmObjective,
		fetchCollectionObjectives,
		runObjectiveAnalysis,
		type ObjectiveList,
		type ObjectiveListItem
	} from '../../../_shared/researchView';

	let objectiveList: ObjectiveList | null = null;
	let loading = false;
	let objectivesNotReady = false;
	let error = '';
	let activeObjectiveId = '';
	let loadedCollectionId = '';
	let requestSequence = 0;

	$: collectionId = $page.params.id ?? '';
	$: objectives = objectiveList?.objectives ?? [];
	$: readyCount = objectives.filter((objective) => objective.status === 'ready').length;
	$: processingCount = objectives.filter(
		(objective) => objective.status === 'queued' || objective.status === 'running'
	).length;
	$: reviewCandidateCount = objectives.reduce(
		(total, objective) => total + objective.review_summary.review_candidate_count,
		0
	);
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadObjectives();
	}

	async function loadObjectives() {
		const activeCollectionId = collectionId;
		const sequence = ++requestSequence;
		loading = true;
		objectivesNotReady = false;
		error = '';
		try {
			const result = await fetchCollectionObjectives(activeCollectionId);
			if (sequence !== requestSequence || activeCollectionId !== collectionId) return;
			objectiveList = result;
		} catch (err) {
			if (sequence !== requestSequence || activeCollectionId !== collectionId) return;
			objectiveList = null;
			if (getApiErrorCode(err) === 'research_objectives_not_ready') {
				objectivesNotReady = true;
			} else {
				error = errorMessage(err);
			}
		} finally {
			if (sequence === requestSequence && activeCollectionId === collectionId) loading = false;
		}
	}

	function objectiveHref(objectiveId: string) {
		return resolve('/collections/[id]/objectives/[objective_id]', {
			id: collectionId,
			objective_id: objectiveId
		});
	}

	function canStartAnalysis(objective: ObjectiveListItem) {
		return ['candidate', 'confirmed', 'failed'].includes(objective.status);
	}

	function analysisActionLabel(objective: ObjectiveListItem) {
		if (activeObjectiveId === objective.objective_id) return $t('research.objectives.analyzing');
		if (objective.status === 'failed') return $t('research.objectives.retryAnalysis');
		return $t('research.objectives.confirmAndAnalyze');
	}

	async function startAnalysis(objective: ObjectiveListItem) {
		if (!canStartAnalysis(objective) || activeObjectiveId) return;
		activeObjectiveId = objective.objective_id;
		error = '';
		try {
			if (objective.status === 'candidate') {
				await confirmObjective(collectionId, objective.objective_id);
			}
			await runObjectiveAnalysis(collectionId, objective.objective_id);
			await goto(objectiveHref(objective.objective_id));
		} catch (err) {
			error = errorMessage(err);
		} finally {
			activeObjectiveId = '';
		}
	}

	function listLabel(items: string[]) {
		return items.length ? items.join(', ') : $t('research.emptyValue');
	}

	function confidenceLabel(value: number) {
		return value > 0 ? `${Math.round(value * 100)}%` : $t('research.emptyValue');
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
		</div>
		<button class="btn btn--ghost" type="button" on:click={loadObjectives}>
			{$t('research.objectives.refresh')}
		</button>
	</header>

	{#if loading}
		<div class="page-state" aria-busy="true" role="status">
			{$t('research.objectives.loading')}
		</div>
	{:else if objectivesNotReady}
		<section class="page-state page-state--pending" role="status">
			<h3>{$t('research.objectives.pendingTitle')}</h3>
			<p>{$t('research.objectives.pendingBody')}</p>
			<a class="btn btn--primary btn--small" href={resolve('/collections/[id]', { id: collectionId })}>
				{$t('research.objectives.openOverview')}
			</a>
		</section>
	{:else if error}
		<section class="page-state page-state--error" role="alert">
			<h3>{$t('research.objectives.analysisErrorTitle')}</h3>
			<p>{error}</p>
		</section>
	{:else if !objectives.length}
		<section class="page-state">
			<h3>{$t('research.objectives.emptyTitle')}</h3>
			<p>{$t('research.objectives.emptyBody')}</p>
		</section>
	{:else}
		<section class="objective-summary" aria-label={$t('research.objectives.summaryTitle')}>
			<div><strong>{objectives.length}</strong><span>{$t('research.objectives.title')}</span></div>
			<div><strong>{readyCount}</strong><span>{$t('research.objectives.lifecycle.ready')}</span></div>
			<div><strong>{processingCount}</strong><span>{$t('research.objectives.processing')}</span></div>
			<div><strong>{reviewCandidateCount}</strong><span>{$t('research.objectives.needReview')}</span></div>
		</section>

		<section class="objectives-grid" aria-label={$t('research.objectives.title')}>
			{#each objectives as objective (objective.objective_id)}
				<article class="objective-card">
					<div class="objective-card__heading">
						<div>
							<h3>{objective.question}</h3>
							<p>{objective.comparison_intent || $t('research.objectives.noIntent')}</p>
						</div>
						<span class={`lifecycle lifecycle--${objective.status}`}>
							{$t(`research.objectives.lifecycle.${objective.status}`)}
						</span>
					</div>

					<dl class="objective-facts">
						<div><dt>{$t('research.objectives.materialScope')}</dt><dd>{listLabel(objective.material_scope)}</dd></div>
						<div><dt>{$t('research.objectives.processAxes')}</dt><dd>{listLabel(objective.process_axes)}</dd></div>
						<div><dt>{$t('research.objectives.propertyAxes')}</dt><dd>{listLabel(objective.property_axes)}</dd></div>
						<div><dt>{$t('research.objectives.confidence')}</dt><dd>{confidenceLabel(objective.confidence)}</dd></div>
					</dl>

					<div class="objective-card__review">
						<span>{$t('research.objectives.findingCount', { count: objective.review_summary.primary_finding_count })}</span>
						<span>{$t('research.objectives.reviewCount', { count: objective.review_summary.review_candidate_count })}</span>
					</div>

					{#if objective.analysis_error}
						<p class="objective-card__error" role="alert">{objective.analysis_error}</p>
					{:else if objective.analysis_progress?.message}
						<p class="objective-card__progress" role="status">{objective.analysis_progress.message}</p>
					{/if}

					<div class="objective-card__actions">
						{#if canStartAnalysis(objective)}
							<button
								class="btn btn--primary btn--small"
								type="button"
								disabled={Boolean(activeObjectiveId)}
								on:click={() => startAnalysis(objective)}
							>
								{analysisActionLabel(objective)}
							</button>
						{/if}
						<a class="btn btn--ghost btn--small" href={objectiveHref(objective.objective_id)}>
							{$t('research.objectives.openWorkspace')}
						</a>
					</div>
				</article>
			{/each}
		</section>
	{/if}
</section>

<style>
	.objectives-page { width: 100%; max-width: 1180px; margin: 0 auto; display: grid; gap: 20px; }
	.objectives-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; padding-bottom: 18px; border-bottom: 1px solid var(--border-default); }
	.objectives-header h2, .page-state h3, .objective-card h3 { margin: 0; color: var(--text-primary); }
	.objectives-header h2 { font-size: 30px; line-height: 38px; }
	.objectives-header p, .page-state p, .objective-card p { margin: 7px 0 0; color: var(--text-secondary); line-height: 1.55; }
	.page-state { padding: 22px 0; }
	.page-state--pending { color: var(--warning-text); }
	.page-state--error, .objective-card__error { color: var(--danger-text); }
	.page-state .btn { margin-top: 12px; }
	.objective-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-block: 1px solid var(--border-default); }
	.objective-summary div { display: grid; gap: 4px; padding: 16px 18px; border-right: 1px solid var(--border-default); }
	.objective-summary div:last-child { border-right: 0; }
	.objective-summary strong { color: var(--text-primary); font-size: 24px; }
	.objective-summary span { color: var(--text-secondary); font-size: 13px; }
	.objectives-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
	.objective-card { display: grid; gap: 16px; min-width: 0; padding: 18px; border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-card); }
	.objective-card__heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; }
	.objective-card__heading > div { min-width: 0; }
	.objective-card h3 { font-size: 18px; line-height: 1.4; }
	.lifecycle { flex: 0 0 auto; padding: 4px 8px; border-radius: 4px; background: var(--surface-muted); color: var(--text-secondary); font-size: 12px; font-weight: 700; }
	.lifecycle--ready, .lifecycle--confirmed { background: var(--success-bg); color: var(--success-text); }
	.lifecycle--queued, .lifecycle--running { background: var(--warning-bg); color: var(--warning-text); }
	.lifecycle--failed { background: var(--danger-bg); color: var(--danger-text); }
	.objective-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 18px; margin: 0; }
	.objective-facts div { min-width: 0; }
	.objective-facts dt { color: var(--text-tertiary); font-size: 12px; }
	.objective-facts dd { margin: 3px 0 0; color: var(--text-primary); overflow-wrap: anywhere; }
	.objective-card__review { display: flex; flex-wrap: wrap; gap: 8px; color: var(--text-secondary); font-size: 13px; }
	.objective-card__review span { padding: 4px 7px; border: 1px solid var(--border-default); border-radius: 4px; }
	.objective-card__progress, .objective-card__error { margin: 0; font-size: 13px; }
	.objective-card__actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: auto; }
	@media (max-width: 760px) {
		.objectives-header { align-items: stretch; flex-direction: column; }
		.objective-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
		.objective-summary div:nth-child(2) { border-right: 0; }
		.objective-summary div:nth-child(-n + 2) { border-bottom: 1px solid var(--border-default); }
		.objectives-grid { grid-template-columns: 1fr; }
		.objective-card__heading { flex-direction: column; }
	}
</style>
