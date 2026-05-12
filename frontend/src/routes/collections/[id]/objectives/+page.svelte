<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		fetchCollectionObjectives,
		getResearchViewStateTone,
		type ObjectiveList,
		type ObjectiveListItem
	} from '../../../_shared/researchView';

	let objectiveList: ObjectiveList | null = null;
	let objectivesError = '';
	let loading = false;
	let loadedCollectionId = '';

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
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadObjectives();
	}

	async function loadObjectives() {
		loading = true;
		objectivesError = '';
		try {
			objectiveList = await fetchCollectionObjectives(collectionId);
		} catch (err) {
			objectiveList = null;
			objectivesError = errorMessage(err);
		} finally {
			loading = false;
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
	{:else if objectivesError}
		<section class="objectives-state-card objectives-state-card--error" role="alert">
			<h3>{$t('research.objectives.errorTitle')}</h3>
			<p>{objectivesError}</p>
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
						<a
							class="btn btn--primary btn--small"
							href={resolve('/collections/[id]/objectives/[objective_id]', {
								id: collectionId,
								objective_id: objective.objective_id
							})}
						>
							{$t('research.objectives.openWorkspace')}
						</a>
					</div>
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

	.objectives-summary-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 12px;
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
	}
</style>
