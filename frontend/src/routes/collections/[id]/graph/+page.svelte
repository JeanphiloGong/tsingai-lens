<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		fetchCollectionObjectives,
		fetchObjectiveEvidenceMap,
		type ObjectiveEvidenceMap,
		type ObjectiveSummary
	} from '../../../_shared/researchView';
	import EvidenceMapFlow from '../_components/EvidenceMapFlow.svelte';

	let publishedObjectives: ObjectiveSummary[] = [];
	let selectedObjectiveId = '';
	let evidenceMap: ObjectiveEvidenceMap | null = null;
	let loading = false;
	let error = '';
	let loadedCollectionId = '';
	let requestSequence = 0;

	$: collectionId = $page.params.id ?? '';
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadObjectives();
	}

	async function loadObjectives() {
		const sequence = ++requestSequence;
		loading = true;
		error = '';
		evidenceMap = null;
		try {
			const result = await fetchCollectionObjectives(collectionId);
			if (sequence !== requestSequence) return;
			publishedObjectives = result.objectives.filter(
				(objective) => objective.published_analysis_version !== null
			);
			const requestedObjectiveId = $page.url.searchParams.get('objective_id') ?? '';
			selectedObjectiveId = publishedObjectives.some(
				(objective) => objective.objective_id === requestedObjectiveId
			)
				? requestedObjectiveId
				: (publishedObjectives[0]?.objective_id ?? '');
			if (selectedObjectiveId) {
				evidenceMap = await fetchObjectiveEvidenceMap(collectionId, selectedObjectiveId);
			}
		} catch (err) {
			if (sequence === requestSequence) error = errorMessage(err);
		} finally {
			if (sequence === requestSequence) loading = false;
		}
	}

	async function selectObjective() {
		const sequence = ++requestSequence;
		loading = true;
		error = '';
		evidenceMap = null;
		try {
			evidenceMap = await fetchObjectiveEvidenceMap(collectionId, selectedObjectiveId);
		} catch (err) {
			if (sequence === requestSequence) error = errorMessage(err);
		} finally {
			if (sequence === requestSequence) loading = false;
		}
	}
</script>

<svelte:head><title>{$t('research.evidenceMap.pageTitle')}</title></svelte:head>

<section class="evidence-map-page">
	<header class="page-heading">
		<div>
			<h2>{$t('research.evidenceMap.pageTitle')}</h2>
			<p>{$t('research.evidenceMap.subtitle')}</p>
		</div>
		{#if publishedObjectives.length}
			<label>
				<span>{$t('research.evidenceMap.objectiveLabel')}</span>
				<select bind:value={selectedObjectiveId} on:change={selectObjective} disabled={loading}>
					{#each publishedObjectives as objective (objective.objective_id)}
						<option value={objective.objective_id}>{objective.question}</option>
					{/each}
				</select>
			</label>
		{/if}
	</header>

	{#if loading}
		<div class="state" aria-busy="true">
			<span class="loading-line"></span>
			<span class="loading-line loading-line--short"></span>
			<p>{$t('research.evidenceMap.loading')}</p>
		</div>
	{:else if error}
		<section class="state state--error" role="alert">
			<h3>{$t('research.evidenceMap.errorTitle')}</h3>
			<p>{error}</p>
			<button class="btn btn--ghost btn--small" type="button" on:click={loadObjectives}>
				{$t('research.evidenceMap.retry')}
			</button>
		</section>
	{:else if !publishedObjectives.length}
		<section class="state state--empty">
			<h3>{$t('research.evidenceMap.emptyTitle')}</h3>
			<p>{$t('research.evidenceMap.emptyBody')}</p>
			<a
				class="btn btn--primary btn--small"
				href={resolve('/collections/[id]/objectives', { id: collectionId })}
			>
				{$t('research.evidenceMap.openObjectives')}
			</a>
		</section>
	{:else if evidenceMap}
		<EvidenceMapFlow map={evidenceMap} {collectionId} />
	{/if}
</section>

<style>
	.evidence-map-page {
		width: min(1440px, 100%);
		margin: 0 auto;
		display: grid;
		gap: 20px;
	}

	.page-heading {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 24px;
		padding-bottom: 16px;
		border-bottom: 1px solid var(--border-default);
	}

	h2,
	h3,
	p {
		margin: 0;
	}

	.page-heading h2 {
		font-size: 24px;
		line-height: 1.25;
	}

	.page-heading p,
	.state p,
	label span {
		color: var(--text-secondary);
	}

	label {
		width: min(440px, 100%);
		display: grid;
		gap: 6px;
		font-size: 13px;
		font-weight: 600;
	}

	select {
		width: 100%;
		min-height: 40px;
		padding: 8px 34px 8px 12px;
		border: 1px solid var(--border-strong);
		border-radius: 6px;
		background: var(--surface-card);
	}

	.state {
		min-height: 240px;
		display: grid;
		align-content: center;
		justify-items: start;
		gap: 12px;
		padding: 32px;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--surface-card);
	}

	.state--error {
		border-color: var(--danger-border);
	}

	.loading-line {
		width: min(520px, 82%);
		height: 12px;
		border-radius: 4px;
		background: var(--border-default);
		animation: pulse 1.4s ease-in-out infinite;
	}

	.loading-line--short {
		width: min(320px, 56%);
	}

	@keyframes pulse {
		50% {
			opacity: 0.45;
		}
	}

	@media (max-width: 760px) {
		.page-heading {
			align-items: stretch;
			flex-direction: column;
		}

		label {
			width: 100%;
		}

		.state {
			padding: 20px;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.loading-line {
			animation: none;
		}
	}
</style>
