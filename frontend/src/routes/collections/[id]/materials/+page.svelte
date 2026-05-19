<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		fetchCollectionMaterials,
		getResearchViewStateTone,
		type MaterialSummary
	} from '../../../_shared/researchView';

	let materials: MaterialSummary[] = [];
	let materialsError = '';
	let loading = false;
	let loadedCollectionId = '';

	$: collectionId = $page.params.id ?? '';
	$: readyCount = materials.filter((material) => material.state === 'ready').length;
	$: partialCount = materials.filter((material) => material.state === 'partial').length;
	$: sampleCount = materials.reduce((total, material) => total + material.sample_count, 0);
	$: paperCount = materials.reduce((total, material) => total + material.paper_count, 0);
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadMaterials();
	}

	async function loadMaterials() {
		loading = true;
		materialsError = '';
		try {
			materials = await fetchCollectionMaterials(collectionId);
		} catch (err) {
			materials = [];
			materialsError = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	function materialStateTone(material: MaterialSummary) {
		return getResearchViewStateTone(material.state);
	}

	function materialEvidenceLabel(material: MaterialSummary) {
		const coverage = material.evidence_coverage;
		if (coverage === null) return $t('research.emptyValue');
		if (typeof coverage === 'number') {
			const percent = coverage <= 1 ? Math.round(coverage * 100) : Math.round(coverage);
			return `${percent}%`;
		}
		return coverage;
	}

	function listLabel(items: string[]) {
		return items.length ? items.slice(0, 5).join(', ') : $t('research.emptyValue');
	}
</script>

<svelte:head>
	<title>{$t('research.materials.title')}</title>
</svelte:head>

<section class="materials-page fade-up">
	<header class="materials-header">
		<div>
			<h2>{$t('research.materials.title')}</h2>
			<p>{$t('research.materials.body')}</p>
			{#if materials.length}
				<div class="materials-meta-row">
					<span>{$t('research.materials.materialCount', { count: materials.length })}</span>
					<span>{$t('research.materials.paperCount', { count: paperCount })}</span>
					<span>{$t('research.materials.sampleCount', { count: sampleCount })}</span>
				</div>
			{/if}
		</div>
		<button class="btn btn--ghost" type="button" on:click={loadMaterials}>
			<span class="refresh-icon" aria-hidden="true"></span>
			{$t('research.materials.refresh')}
		</button>
	</header>

	{#if loading}
		<section class="materials-state-card" aria-busy="true" aria-live="polite">
			<div class="status" role="status">{$t('research.materials.loading')}</div>
		</section>
	{:else if materialsError}
		<section class="materials-state-card materials-state-card--error" role="alert">
			<h3>{$t('research.materials.errorTitle')}</h3>
			<p>{materialsError}</p>
		</section>
	{:else if !materials.length}
		<section class="materials-state-card">
			<h3>{$t('research.materials.emptyTitle')}</h3>
			<p>{$t('research.materials.emptyBody')}</p>
		</section>
	{:else}
		<section class="materials-summary-grid" aria-label={$t('research.materials.summaryTitle')}>
			<article>
				<span>{$t('research.state.ready')}</span>
				<strong>{readyCount}</strong>
			</article>
			<article>
				<span>{$t('research.state.partial')}</span>
				<strong>{partialCount}</strong>
			</article>
			<article>
				<span>{$t('research.overview.samples')}</span>
				<strong>{sampleCount}</strong>
			</article>
			<article>
				<span>{$t('research.materials.comparisons')}</span>
				<strong
					>{materials.reduce((total, material) => total + material.comparison_count, 0)}</strong
				>
			</article>
		</section>

		<section class="materials-grid" aria-label={$t('research.materials.title')}>
			{#each materials as material (material.material_id)}
				<article class="material-card">
					<div class="material-card__header">
						<div>
							<h3>{material.canonical_name}</h3>
							{#if material.aliases.length}
								<p>{$t('research.materials.aliases')}: {material.aliases.join(', ')}</p>
							{/if}
						</div>
						<span class={`status-badge status-badge--${materialStateTone(material)}`}>
							{$t(`research.state.${material.state}`)}
						</span>
					</div>

					<div class="material-stat-row">
						<div>
							<span>{$t('research.materials.papers')}</span>
							<strong>{material.paper_count}</strong>
						</div>
						<div>
							<span>{$t('research.overview.samples')}</span>
							<strong>{material.sample_count}</strong>
						</div>
						<div>
							<span>{$t('research.materials.comparisons')}</span>
							<strong>{material.comparison_count}</strong>
						</div>
						<div>
							<span>{$t('research.materials.evidenceCoverage')}</span>
							<strong>{materialEvidenceLabel(material)}</strong>
						</div>
					</div>

					<dl class="material-fact-list">
						<div>
							<dt>{$t('research.overview.processes')}</dt>
							<dd>{listLabel(material.process_families)}</dd>
						</div>
						<div>
							<dt>{$t('research.overview.properties')}</dt>
							<dd>{listLabel(material.measured_properties)}</dd>
						</div>
					</dl>

					{#if material.warnings.length}
						<div class="material-warning" role="status">
							<strong>{$t('research.warnings')}</strong>
							<span>{material.warnings.map((warning) => warning.message).join(' | ')}</span>
						</div>
					{/if}

					<div class="material-card__actions">
						<a
							class="btn btn--primary btn--small"
							href={resolve('/collections/[id]/materials/[material_id]', {
								id: collectionId,
								material_id: material.material_id
							})}
						>
							{$t('research.materials.openProfile')}
						</a>
					</div>
				</article>
			{/each}
		</section>
	{/if}
</section>

<style>
	.materials-page {
		width: 100%;
		max-width: 1280px;
		margin: 0 auto;
		display: grid;
		gap: 22px;
	}

	.materials-header,
	.materials-state-card,
	.material-card,
	.materials-summary-grid article {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.materials-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 18px;
		padding: 24px;
	}

	.materials-header h2,
	.materials-state-card h3,
	.material-card h3 {
		margin: 0;
		color: var(--text-primary);
	}

	.materials-header h2 {
		font-size: 30px;
		line-height: 38px;
	}

	.materials-header p,
	.materials-state-card p,
	.material-card p {
		max-width: 760px;
		margin: 8px 0 0;
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 23px;
	}

	.materials-meta-row {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		margin-top: 12px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.materials-state-card {
		display: grid;
		gap: 8px;
		padding: 24px;
	}

	.materials-state-card--error {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.materials-summary-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 12px;
	}

	.materials-summary-grid article {
		display: grid;
		gap: 6px;
		min-width: 0;
		padding: 16px;
	}

	.materials-summary-grid span,
	.material-stat-row span {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.materials-summary-grid strong,
	.material-stat-row strong {
		color: var(--text-primary);
		font-size: 24px;
		line-height: 30px;
	}

	.materials-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
		gap: 16px;
	}

	.material-card {
		display: grid;
		gap: 16px;
		min-width: 0;
		padding: 18px;
	}

	.material-card__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}

	.material-card__header h3 {
		font-size: 20px;
		line-height: 26px;
	}

	.material-stat-row {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 10px;
	}

	.material-stat-row > div,
	.material-fact-list > div {
		min-width: 0;
		padding: 12px;
		border-radius: var(--radius-md);
		background: var(--surface-muted);
	}

	.material-fact-list {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
		margin: 0;
	}

	.material-fact-list dt {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.material-fact-list dd {
		margin: 4px 0 0;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 21px;
	}

	.material-warning {
		display: grid;
		gap: 4px;
		padding: 12px;
		border: 1px solid var(--warning-border);
		border-radius: var(--radius-md);
		background: var(--warning-bg);
		color: var(--warning-text);
		font-size: 13px;
		line-height: 20px;
	}

	.material-card__actions {
		display: flex;
		justify-content: flex-end;
	}

	@media (max-width: 760px) {
		.materials-header,
		.material-card__header {
			display: grid;
		}

		.materials-summary-grid,
		.material-stat-row,
		.material-fact-list {
			grid-template-columns: 1fr;
		}
	}
</style>
