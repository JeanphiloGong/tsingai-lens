<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		fetchCollectionResearchView,
		getResearchViewStateTone,
		type CollectionAggregation,
		type PaperCoverageRow,
		type ResearchViewWarning
	} from '../../../_shared/researchView';

	type WarningSummary = {
		key: string;
		message: string;
		scope: string;
		count: number;
	};

	let researchView: CollectionAggregation | null = null;
	let loading = false;
	let error = '';
	let loadedCollectionId = '';

	$: collectionId = $page.params.id ?? '';
	$: paperCoverageRows = researchView?.paper_coverage ?? [];
	$: readyCount = paperCoverageRows.filter((row) => row.state === 'ready').length;
	$: partialCount = paperCoverageRows.filter((row) => row.state === 'partial').length;
	$: failedCount = paperCoverageRows.filter((row) => row.state === 'failed').length;
	$: totalSamples = paperCoverageRows.reduce((total, row) => total + row.sample_count, 0);
	$: totalMeasurements = paperCoverageRows.reduce((total, row) => total + row.measurement_count, 0);
	$: totalConditions = paperCoverageRows.reduce((total, row) => total + row.condition_count, 0);
	$: totalEvidence = paperCoverageRows.reduce((total, row) => total + row.evidence_count, 0);
	$: collectionWarningSummaries = summarizeWarnings(researchView?.warnings ?? []);

	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadPaperCoverage();
	}

	async function loadPaperCoverage() {
		loading = true;
		error = '';
		try {
			researchView = await fetchCollectionResearchView(collectionId);
		} catch (err) {
			researchView = null;
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	function paperDetailHref(row: PaperCoverageRow) {
		return resolve('/collections/[id]/documents/[document_id]', {
			id: collectionId,
			document_id: row.document_id
		});
	}

	function coverageStateTone(row: PaperCoverageRow) {
		const tone = getResearchViewStateTone(row.state);
		if (tone === 'ready') return 'ready';
		if (tone === 'failed') return 'failed';
		if (tone === 'processing') return 'processing';
		return 'pending';
	}

	function issueLabel(row: PaperCoverageRow) {
		return row.issue_count > 0
			? $t('research.documents.issueCount', { count: row.issue_count })
			: $t('research.documents.noIssues');
	}

	function paperDisplayTitle(row: PaperCoverageRow, index: number) {
		const title = row.title?.trim();
		if (title && title !== row.document_id) return title;
		return $t('research.documents.untitledPaper', { number: index + 1 });
	}

	function paperShortId(row: PaperCoverageRow) {
		return row.document_id.length > 12 ? row.document_id.slice(0, 12) : row.document_id;
	}

	function paperCoverageQuality(row: PaperCoverageRow) {
		if (row.state === 'failed') return $t('research.documents.coverageFailed');
		if (!row.evidence_count) return $t('research.documents.coverageNoEvidence');
		if (!row.condition_count) return $t('research.documents.coverageNeedsConditions');
		return $t('research.documents.coverageReady');
	}

	function summarizeWarnings(warnings: ResearchViewWarning[]): WarningSummary[] {
		const summaries = new Map<string, WarningSummary>();
		for (const warning of warnings) {
			const message = warning.message.trim();
			if (!message) continue;
			const key = `${warning.scope}:${message}`;
			const existing = summaries.get(key);
			if (existing) {
				existing.count += 1;
			} else {
				summaries.set(key, {
					key,
					message,
					scope: warning.scope,
					count: 1
				});
			}
		}
		return [...summaries.values()];
	}

	function warningSummaryLabel(summary: WarningSummary) {
		if (summary.count <= 1) return summary.message;
		if (summary.scope === 'paper') {
			return $t('research.warningPaperCount', {
				message: summary.message,
				count: summary.count
			});
		}
		return $t('research.warningOccurrenceCount', {
			message: summary.message,
			count: summary.count
		});
	}
</script>

<svelte:head>
	<title>{$t('research.documents.title')}</title>
</svelte:head>

<section class="paper-coverage-page fade-up">
	<header class="paper-coverage-header">
		<div>
			<h2>{$t('research.documents.tableTitle')}</h2>
			<p>{$t('research.documents.directBody')}</p>
			{#if researchView}
				<div class="paper-coverage-meta">
					<span
						class={`status-badge status-badge--${getResearchViewStateTone(researchView.state)}`}
					>
						{$t(`research.state.${researchView.state}`)}
					</span>
					<span>{$t('research.documents.documentCount', { count: paperCoverageRows.length })}</span>
				</div>
			{/if}
		</div>
		<button class="btn btn--ghost" type="button" on:click={loadPaperCoverage}>
			<span class="refresh-icon" aria-hidden="true"></span>
			{$t('research.documents.refresh')}
		</button>
	</header>

	{#if loading}
		<section class="coverage-state-card" aria-busy="true" aria-live="polite">
			<div class="status" role="status">{$t('research.documents.loading')}</div>
		</section>
	{:else if error}
		<section class="coverage-state-card coverage-state-card--error" role="alert">
			<h3>{$t('research.documents.errorTitle')}</h3>
			<p>{error}</p>
		</section>
	{:else if !researchView || !paperCoverageRows.length}
		<section class="coverage-state-card">
			<h3>{$t('research.documents.emptyTitle')}</h3>
			<p>{$t('research.documents.emptyBody')}</p>
		</section>
	{:else}
		<section class="coverage-summary-grid" aria-label={$t('research.documents.coverageTitle')}>
			<article>
				<span>{$t('research.state.ready')}</span>
				<strong>{readyCount}</strong>
			</article>
			<article>
				<span>{$t('research.state.partial')}</span>
				<strong>{partialCount}</strong>
			</article>
			<article>
				<span>{$t('research.state.failed')}</span>
				<strong>{failedCount}</strong>
			</article>
			<article>
				<span>{$t('research.overview.evidence')}</span>
				<strong>{totalEvidence}</strong>
			</article>
		</section>

		<section class="coverage-fact-grid" aria-label={$t('research.documents.factCoverageTitle')}>
			<div>
				<span>{$t('research.overview.samples')}</span>
				<strong>{totalSamples}</strong>
			</div>
			<div>
				<span>{$t('research.overview.measurements')}</span>
				<strong>{totalMeasurements}</strong>
			</div>
			<div>
				<span>{$t('research.documents.conditions')}</span>
				<strong>{totalConditions}</strong>
			</div>
		</section>

		{#if collectionWarningSummaries.length}
			<section class="coverage-warning-card">
				<strong>{$t('research.warnings')}</strong>
				<ul>
					{#each collectionWarningSummaries as warning (warning.key)}
						<li>{warningSummaryLabel(warning)}</li>
					{/each}
				</ul>
			</section>
		{/if}

		<section class="coverage-table-card">
			<div class="coverage-table-header">
				<h3>{$t('research.documents.tableTitle')}</h3>
				<span>{$t('research.documents.documentCount', { count: paperCoverageRows.length })}</span>
			</div>
			<div class="paper-review-list">
				{#each paperCoverageRows as row, index (row.document_id)}
					<article class="paper-review-card">
						<div class="paper-review-card__main">
							<span class="pdf-icon" aria-hidden="true">PDF</span>
							<div>
								<div class="paper-review-card__title-row">
									<h4>{paperDisplayTitle(row, index)}</h4>
									<span class={`status-badge status-badge--${coverageStateTone(row)}`}>
										{$t(`research.state.${row.state}`)}
									</span>
								</div>
								<p>{paperCoverageQuality(row)}</p>
								<div class="paper-review-card__meta">
									<span>{$t('research.documents.shortId')}: {paperShortId(row)}</span>
									<span>{issueLabel(row)}</span>
								</div>
							</div>
						</div>
						<div class="paper-review-card__metrics" aria-label={$t('research.documents.factCoverageTitle')}>
							<div>
								<span>{$t('research.overview.samples')}</span>
								<strong>{row.sample_count}</strong>
							</div>
							<div>
								<span>{$t('research.documents.processParams')}</span>
								<strong>{row.process_param_count}</strong>
							</div>
							<div>
								<span>{$t('research.overview.measurements')}</span>
								<strong>{row.measurement_count}</strong>
							</div>
							<div>
								<span>{$t('research.documents.conditions')}</span>
								<strong>{row.condition_count}</strong>
							</div>
							<div>
								<span>{$t('research.documents.evidence')}</span>
								<strong>{row.evidence_count}</strong>
							</div>
						</div>
						<div class="paper-review-card__footer">
							{#if row.primary_warnings.length}
								<p>
									<strong>{$t('research.warnings')}:</strong>
									{row.primary_warnings.map((warning) => warning.message).join(' | ')}
								</p>
							{/if}
							<a class="btn btn--ghost btn--small" href={paperDetailHref(row)}>
								{$t('research.documents.openPaper')}
							</a>
						</div>
					</article>
				{/each}
			</div>
		</section>
	{/if}
</section>

<style>
	.paper-coverage-page {
		display: grid;
		gap: 22px;
	}

	.paper-coverage-header,
	.coverage-state-card,
	.coverage-table-card,
	.coverage-summary-grid article,
	.coverage-fact-grid,
	.coverage-warning-card {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.paper-coverage-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 18px;
		padding: 24px;
	}

	.paper-coverage-header h2,
	.coverage-table-header h3,
	.paper-review-card h4,
	.coverage-state-card h3 {
		margin: 0;
		color: var(--text-primary);
	}

	.paper-coverage-header h2 {
		font-size: 30px;
		line-height: 38px;
	}

	.paper-coverage-header p,
	.paper-review-card p,
	.coverage-state-card p {
		max-width: 760px;
		margin: 8px 0 0;
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 23px;
	}

	.paper-coverage-meta {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 10px;
		margin-top: 12px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.coverage-state-card {
		display: grid;
		gap: 8px;
		padding: 24px;
	}

	.coverage-state-card--error {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.coverage-summary-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 12px;
	}

	.coverage-summary-grid article,
	.coverage-fact-grid > div {
		display: grid;
		gap: 6px;
		min-width: 0;
		padding: 16px;
	}

	.coverage-summary-grid span,
	.coverage-fact-grid span {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.coverage-summary-grid strong,
	.coverage-fact-grid strong {
		color: var(--text-primary);
		font-size: 26px;
		line-height: 32px;
	}

	.coverage-fact-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		overflow: hidden;
	}

	.coverage-warning-card {
		display: grid;
		gap: 8px;
		padding: 16px;
		border-color: var(--warning-border);
		background: var(--warning-bg);
	}

	.coverage-warning-card ul {
		margin: 0;
		padding-left: 18px;
		color: var(--warning-text);
		font-size: 13px;
		line-height: 20px;
	}

	.coverage-table-card {
		padding: 18px;
	}

	.coverage-table-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 14px;
	}

	.coverage-table-header span {
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.paper-review-list {
		display: grid;
		gap: 12px;
	}

	.paper-review-card {
		display: grid;
		gap: 14px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 16px;
		background: var(--bg-subtle);
	}

	.paper-review-card__main {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: 12px;
	}

	.paper-review-card__title-row,
	.paper-review-card__footer {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}

	.paper-review-card h4 {
		font-size: 16px;
		line-height: 23px;
	}

	.paper-review-card__meta {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 9px;
	}

	.paper-review-card__meta span {
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 4px 9px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 16px;
		background: var(--surface-card);
	}

	.paper-review-card__metrics {
		display: grid;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		gap: 8px;
	}

	.paper-review-card__metrics div {
		display: grid;
		gap: 4px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 10px;
		background: var(--surface-card);
	}

	.paper-review-card__metrics span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.paper-review-card__metrics strong {
		color: var(--text-primary);
		font-size: 20px;
		line-height: 25px;
	}

	.paper-review-card__footer p {
		margin: 0;
		color: var(--warning-text);
		font-size: 13px;
		line-height: 20px;
	}

	.pdf-icon {
		width: 34px;
		height: 40px;
		display: inline-grid;
		place-items: end center;
		flex: 0 0 auto;
		padding-bottom: 5px;
		border-radius: 7px;
		background: #fee2e2;
		color: #dc2626;
		font-size: 10px;
		font-weight: 800;
		line-height: 12px;
	}

	@media (max-width: 860px) {
		.paper-coverage-header {
			display: grid;
		}

		.coverage-summary-grid,
		.coverage-fact-grid,
		.paper-review-card__metrics {
			grid-template-columns: 1fr;
		}

		.paper-review-card__title-row,
		.paper-review-card__footer {
			display: grid;
		}

		.paper-review-card__main {
			grid-template-columns: 1fr;
		}
	}
</style>
