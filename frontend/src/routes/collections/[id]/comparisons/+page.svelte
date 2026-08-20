<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		fetchCollectionObjectives,
		fetchObjectiveFindings,
		type ObjectiveFinding,
		type ObjectiveSummary
	} from '../../../_shared/researchView';

	type PublishedFindingGroup = {
		objective: ObjectiveSummary;
		findings: ObjectiveFinding[];
	};

	let groups: PublishedFindingGroup[] = [];
	let publishedObjectiveCount = 0;
	let failedObjectiveCount = 0;
	let loading = false;
	let error = '';
	let loadedCollectionId = '';

	$: collectionId = $page.params.id ?? '';
	$: findingCount = groups.reduce((count, group) => count + group.findings.length, 0);
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadPublishedFindings();
	}

	async function loadPublishedFindings() {
		loading = true;
		error = '';
		groups = [];
		failedObjectiveCount = 0;
		try {
			const objectiveList = await fetchCollectionObjectives(collectionId);
			const publishedObjectives = objectiveList.objectives.filter(
				(objective) => objective.published_analysis_version !== null
			);
			publishedObjectiveCount = publishedObjectives.length;
			const results = await Promise.allSettled(
				publishedObjectives.map(async (objective) => ({
					objective,
					findings: (
						await fetchObjectiveFindings(
							collectionId,
							objective.objective_id,
							objective.published_analysis_version as number,
							0,
							200
						)
					).items
				}))
			);
			groups = results.flatMap((result) => (result.status === 'fulfilled' ? [result.value] : []));
			failedObjectiveCount = results.length - groups.length;
			if (publishedObjectives.length && failedObjectiveCount === publishedObjectives.length) {
				const firstFailure = results.find((result) => result.status === 'rejected');
				throw firstFailure?.status === 'rejected'
					? firstFailure.reason
					: new Error($t('research.comparison.errorTitle'));
			}
		} catch (err) {
			groups = [];
			publishedObjectiveCount = 0;
			failedObjectiveCount = 0;
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	function joined(items: string[]) {
		return items.length ? items.join(', ') : $t('research.emptyValue');
	}

	function directPaperCount(finding: ObjectiveFinding) {
		return finding.paper_contributions.filter(
			(contribution) =>
				contribution.supporting_evidence_ids.length ||
				contribution.contradicting_evidence_ids.length
		).length;
	}

	function findingHref(objectiveId: string, findingId: string) {
		return `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}?finding_id=${encodeURIComponent(findingId)}`;
	}
</script>

<svelte:head>
	<title>{$t('research.comparison.title')}</title>
</svelte:head>

<section class="comparison-page fade-up">
	<header class="comparison-header">
		<div>
			<p class="comparison-eyebrow">{$t('research.comparison.eyebrow')}</p>
			<h2>{$t('research.comparison.title')}</h2>
			<p>{$t('research.comparison.directBody')}</p>
		</div>
		{#if !loading && !error && publishedObjectiveCount}
			<div class="comparison-summary" aria-label={$t('research.comparison.summaryLabel')}>
				<strong>{findingCount}</strong>
				<span>{$t('research.comparison.findingsCount')}</span>
				<small
					>{$t('research.comparison.publishedObjectiveCount', {
						count: publishedObjectiveCount
					})}</small
				>
			</div>
		{/if}
	</header>

	{#if loading}
		<section class="page-state" aria-busy="true" aria-live="polite">
			<p>{$t('research.comparison.loading')}</p>
		</section>
	{:else if error}
		<section class="page-state page-state--error" role="alert">
			<h3>{$t('research.comparison.errorTitle')}</h3>
			<p>{error}</p>
			<button class="btn btn--ghost btn--small" type="button" on:click={loadPublishedFindings}>
				{$t('research.comparison.retry')}
			</button>
		</section>
	{:else if !findingCount}
		<section class="page-state page-state--empty">
			<h3>{$t('research.comparison.emptyTitle')}</h3>
			<p>{$t('research.comparison.emptyBody')}</p>
			<a
				class="btn btn--primary btn--small"
				href={resolve('/collections/[id]/objectives', { id: collectionId })}
			>
				{$t('research.comparison.openObjectives')}
			</a>
		</section>
	{:else}
		{#if failedObjectiveCount}
			<p class="partial-warning" role="status">
				{$t('research.comparison.partialError', { count: failedObjectiveCount })}
			</p>
		{/if}

		<div class="finding-groups">
			{#each groups as group (group.objective.objective_id)}
				{#if group.findings.length}
					<section class="finding-group" aria-labelledby={`objective-${group.objective.objective_id}`}>
						<header class="objective-context">
							<div>
								<span>{$t('research.comparison.objectiveLabel')}</span>
								<h3 id={`objective-${group.objective.objective_id}`}>{group.objective.question}</h3>
							</div>
							<p>
								{$t('research.comparison.materialScope')}:
								<strong>{joined(group.objective.material_scope)}</strong>
							</p>
						</header>

						<div class="finding-list">
							{#each group.findings as finding (finding.finding_id)}
								<article class="finding-item">
									<div class="finding-item__main">
										<div class="finding-status">
											<span class={`status-badge status-badge--${finding.synthesis_status}`}>
												{$t(`research.comparison.synthesis.${finding.synthesis_status}`)}
											</span>
											<span>{$t('research.comparison.certainty', { value: Math.round(finding.certainty * 100) })}</span>
										</div>
										<h4>{finding.statement}</h4>
										<dl>
											<div>
												<dt>{$t('research.comparison.factors')}</dt>
												<dd>{joined(finding.factors)}</dd>
											</div>
											<div>
												<dt>{$t('research.comparison.outcome')}</dt>
												<dd>{finding.outcome}</dd>
											</div>
										</dl>
										{#if finding.limitations.length}
											<p class="limitations">
												<strong>{$t('research.comparison.limitations')}:</strong>
												{finding.limitations.join(' ')}
											</p>
										{/if}
									</div>
									<div class="finding-item__action">
										<strong
											>{$t('research.comparison.supportingPapers', {
												count: directPaperCount(finding)
											})}</strong
										>
										<a
											class="btn btn--primary btn--small"
											href={findingHref(group.objective.objective_id, finding.finding_id)}
										>
											{$t('research.comparison.reviewEvidence')}
										</a>
									</div>
								</article>
							{/each}
						</div>
					</section>
				{/if}
			{/each}
		</div>
	{/if}
</section>

<style>
	.comparison-page {
		width: min(1180px, 100%);
		margin: 0 auto;
		display: grid;
		gap: 26px;
	}

	.comparison-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 32px;
		padding-bottom: 22px;
		border-bottom: 1px solid var(--border-default);
	}

	.comparison-eyebrow,
	.comparison-header h2,
	.comparison-header p,
	.objective-context h3,
	.objective-context p,
	.finding-item h4,
	.finding-item p,
	.page-state h3,
	.page-state p {
		margin: 0;
	}

	.comparison-eyebrow,
	.objective-context span {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
		text-transform: uppercase;
	}

	.comparison-header h2 {
		margin-top: 4px;
		font-size: 30px;
		line-height: 38px;
	}

	.comparison-header p {
		max-width: 720px;
		margin-top: 8px;
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 23px;
	}

	.comparison-summary {
		min-width: 150px;
		display: grid;
		justify-items: end;
		color: var(--text-secondary);
	}

	.comparison-summary strong {
		color: var(--text-primary);
		font-size: 32px;
		line-height: 36px;
	}

	.comparison-summary span {
		font-weight: 700;
	}

	.comparison-summary small {
		margin-top: 2px;
	}

	.page-state {
		display: grid;
		justify-items: start;
		gap: 10px;
		padding: 28px 0;
	}

	.page-state h3 {
		font-size: 20px;
		line-height: 28px;
	}

	.page-state p {
		max-width: 700px;
		color: var(--text-secondary);
		line-height: 22px;
	}

	.page-state--error,
	.partial-warning {
		color: var(--danger-text);
	}

	.partial-warning {
		margin: 0;
		padding: 10px 12px;
		border-left: 3px solid var(--danger-border);
		background: var(--danger-bg);
	}

	.finding-groups,
	.finding-group,
	.finding-list {
		display: grid;
	}

	.finding-groups {
		gap: 34px;
	}

	.finding-group {
		gap: 14px;
	}

	.objective-context {
		display: flex;
		align-items: end;
		justify-content: space-between;
		gap: 22px;
	}

	.objective-context h3 {
		max-width: 760px;
		margin-top: 3px;
		font-size: 18px;
		line-height: 26px;
	}

	.objective-context p {
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
		text-align: right;
	}

	.finding-list {
		gap: 10px;
	}

	.finding-item {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 190px;
		gap: 24px;
		padding: 18px;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--surface-card);
	}

	.finding-item__main {
		min-width: 0;
		display: grid;
		gap: 12px;
	}

	.finding-status {
		display: flex;
		align-items: center;
		gap: 10px;
		color: var(--text-secondary);
		font-size: 12px;
	}

	.status-badge {
		padding: 3px 8px;
		border-radius: 999px;
		background: var(--bg-subtle);
		font-weight: 700;
	}

	.status-badge--agreement {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.status-badge--conflict {
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.status-badge--condition_dependent,
	.status-badge--insufficient_confirmation {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.finding-item h4 {
		font-size: 17px;
		line-height: 25px;
	}

	.finding-item dl {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
		margin: 0;
	}

	.finding-item dl div {
		display: grid;
		gap: 2px;
	}

	.finding-item dt {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
	}

	.finding-item dd {
		margin: 0;
		font-size: 13px;
		line-height: 20px;
	}

	.limitations {
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.finding-item__action {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		justify-content: space-between;
		gap: 18px;
		padding-left: 18px;
		border-left: 1px solid var(--border-default);
		color: var(--text-secondary);
		font-size: 13px;
		text-align: right;
	}

	@media (max-width: 760px) {
		.comparison-header,
		.objective-context {
			align-items: flex-start;
			flex-direction: column;
		}

		.comparison-summary {
			justify-items: start;
		}

		.objective-context p {
			text-align: left;
		}

		.finding-item {
			grid-template-columns: 1fr;
		}

		.finding-item__action {
			align-items: flex-start;
			padding-top: 14px;
			padding-left: 0;
			border-top: 1px solid var(--border-default);
			border-left: 0;
			text-align: left;
		}
	}
</style>
