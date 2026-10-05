<script lang="ts">
	import { resolve } from '$app/paths';
	import { ArrowLeft, ChevronRight, Plus, RefreshCw } from '@lucide/svelte';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import ExperimentResults from './ExperimentResults.svelte';
	import ObjectiveAnalysisScope from './ObjectiveAnalysisScope.svelte';
	import { t } from '../../../_shared/i18n';
	import type { ObjectiveAnalysis, ObjectiveFinding, FindingEvidenceReview, ExperimentAnalysisProjection } from '../../../_shared/researchView';

	export let analysis: ObjectiveAnalysis;
	export let projection: ExperimentAnalysisProjection | null = null;
	export let experimentLoading = false;
	export let experimentError = '';
	export let findings: ObjectiveFinding[] = [];
	export let evidenceReviews: Record<string, FindingEvidenceReview> = {};
	export let collectionId: string;
	export let documentTitles: Record<string, string> = {};
	export let selectedFindingId = '';
	export let onSelectFinding: (findingId: string) => void = () => {};
	export let onScopeStarted: (result: ObjectiveAnalysis) => void = () => {};
	export let onRetryProjection: () => void = () => {};
	export let onNewFinding: () => void = () => {};
	export let authoringOpen = false;
	export let view: 'results' | 'scope' = 'results';
	$: published = analysis.published_analysis;
	$: publishedVersion = published?.analysis_version ?? null;

	function directPaperCount(finding: ObjectiveFinding) {
		return finding.paper_contributions.filter(item => item.supporting_evidence_ids.length || item.contradicting_evidence_ids.length).length;
	}
	function sourceQuery(gap: ObjectiveAnalysis['evidence_review']['gaps'][number]) {
		const returnTo = resolve('/collections/[id]/objectives/[objective_id]', { id: collectionId, objective_id: analysis.objective.objective_id });
		const query = new SvelteURLSearchParams({ view: 'parsed-paper', evidence_id: gap.evidence_id, source_ref: gap.source_ref, quote: gap.source_excerpt, return_to: returnTo });
		if (gap.page_numbers[0]) query.set('page', String(gap.page_numbers[0]));
		return String(query);
	}
</script>

{#if selectedFindingId || authoringOpen}
	<div class="selected-heading"><button class="back" type="button" on:click={() => onSelectFinding('')}><ArrowLeft size={16} />{$t('objectiveWorkspace.back')}</button><button class="new-finding" type="button" aria-label={$t('objectiveWorkspace.newFinding')} on:click={onNewFinding}><Plus size={16} />{$t('objectiveWorkspace.newFinding')}</button></div>
	<slot name="selected" />
{:else}
	<nav class="workspace-tabs" aria-label={$t('objectiveWorkspace.list')}>
		<button type="button" aria-current={view === 'results' ? 'page' : undefined} on:click={() => view = 'results'}>{$t('objectiveWorkspace.results')}</button>
		<button type="button" aria-current={view === 'scope' ? 'page' : undefined} on:click={() => view = 'scope'}>{$t('objectiveWorkspace.scope')}</button>
	</nav>
	{#if view === 'scope'}
		<ObjectiveAnalysisScope {collectionId} {analysis} {documentTitles} onStarted={onScopeStarted} />
	{:else}
		{#if experimentLoading}
			<p class="empty" aria-busy="true">{$t('objectiveWorkspace.loading')}</p>
		{:else if experimentError}
			<div class="error" role="alert"><p>{experimentError}</p><button class="btn btn--ghost" type="button" on:click={onRetryProjection}><RefreshCw size={16} />{$t('objectiveWorkspace.retry')}</button></div>
		{:else if projection && publishedVersion}
			<ExperimentResults {projection} {collectionId} objectiveId={analysis.objective.objective_id} {documentTitles} />
		{:else if !publishedVersion}
			<p class="empty">{$t('objectiveWorkspace.analysisMissing')}</p>
		{/if}

		{#if published}
			<section class="finding-index" aria-labelledby="finding-index-title">
				<header><div><h2 id="finding-index-title">{$t('objectiveWorkspace.findings')}</h2><span>{$t('objectiveWorkspace.findingCount', { count: findings.length })}</span></div><button class="new-finding" type="button" aria-label={$t('objectiveWorkspace.newFinding')} on:click={onNewFinding}><Plus size={16} />{$t('objectiveWorkspace.newFinding')}</button></header>
				{#if findings.length}
					<ul class="finding-list">
						{#each findings as finding (finding.finding_id)}
							<li><button type="button" on:click={() => onSelectFinding(finding.finding_id)}>
								<span class="card-title">{finding.statement}</span>
								<span class="card-meta">{$t('objectiveWorkspace.' + finding.synthesis_status)} · {$t('objectiveWorkspace.directPapers', { count: directPaperCount(finding) })}
									{#if evidenceReviews[finding.finding_id]?.needs_review}<strong class="needs-review">{$t('research.findingReview.basisUpdated')}</strong>{/if}
								</span>
								<span class="card-link">{$t('objectiveWorkspace.detail')}<ChevronRight size={16} /></span>
							</button></li>
						{/each}
					</ul>
				{:else}<p class="empty">{$t('objectiveWorkspace.emptyFindings')}</p>{/if}
			</section>
			{#if analysis.evidence_review.total_evidence_count > 0}
				<details class="coverage" aria-label={$t('research.findingReview.coverage')}>
					<summary>{$t('research.findingReview.coverage')} · {$t('research.findingReview.coverageCount', { count: analysis.evidence_review.total_evidence_count })}</summary>
					<p>{$t('research.findingReview.coverageTotal', { count: analysis.evidence_review.total_evidence_count, results: analysis.evidence_review.result_count })}</p>
					<div class="counts">{#each Object.entries(analysis.evidence_review.status_counts) as [status, count] (status)}<span>{count} · {$t('objectiveWorkspace.evidenceStatus.' + status)}</span>{/each}</div>
					{#each analysis.evidence_review.gaps as gap (gap.evidence_id)}
						<article><h3>{documentTitles[gap.document_id] || $t('research.findingReview.untitledPaper')}</h3><span>{$t('objectiveWorkspace.evidenceStatus.' + gap.evidence_status)}</span><p>{gap.reason}</p>{#if gap.outcome}<p>{$t('research.findingReview.outcome', { outcome: gap.outcome })}</p>{/if}{#if gap.source_excerpt}<blockquote>{gap.source_excerpt}</blockquote>{/if}
							<!-- eslint-disable svelte/no-navigation-without-resolve -->
							<a href={resolve('/collections/[id]/documents/[document_id]', { id: collectionId, document_id: gap.document_id }) + '?' + sourceQuery(gap)}>{$t('research.findingReview.openSource')}</a></article>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
					{/each}
					{#if analysis.evidence_review.omitted_gap_count}<p>{$t('research.findingReview.omittedGaps', { count: analysis.evidence_review.omitted_gap_count })}</p>{/if}
				</details>
			{/if}
			<details class="versions"><summary>{$t('objectiveWorkspace.versions')}</summary><p>{$t('objectiveWorkspace.publishedVersion', { version: publishedVersion ?? '' })} · {published.model_name || $t('objectiveWorkspace.modelMissing')}</p></details>
		{/if}
	{/if}
{/if}

<style>
	.workspace-tabs { display: flex; gap: 24px; border-bottom: 1px solid var(--border-default); }
	.workspace-tabs button { border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--text-secondary); padding: 10px 2px; cursor: pointer; font: inherit; font-size: 14px; }
	.workspace-tabs button[aria-current='page'] { border-bottom-color: var(--brand-primary); color: var(--brand-primary); font-weight: 600; }
	.selected-heading { font-size: 13px; }
	.back, .new-finding { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; color: var(--brand-primary); cursor: pointer; font: inherit; padding: 4px 0; }
	.finding-index { border-top: 1px solid var(--border-default); }
	.finding-index header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin: 18px 0 12px; }
	.finding-index header > div { display: flex; align-items: baseline; gap: 12px; }
	h2 { margin: 0; font-size: 18px; } header span { color: var(--text-secondary); font-size: 13px; }
	.new-finding { font-size: 13px; }
	.finding-list { list-style: none; padding: 0; margin: 0; border-top: 1px solid var(--border-default); }
	.finding-list button { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px 20px; width: 100%; text-align: left; padding: 18px 12px; border: 0; border-bottom: 1px solid var(--border-default); background: transparent; color: inherit; cursor: pointer; font: inherit; }
	.finding-list button:hover { background: var(--brand-soft); }
	.card-title { min-width: 0; overflow-wrap: anywhere; font-size: 15px; font-weight: 600; }
	.card-meta { grid-column: 1; grid-row: 2; color: var(--text-secondary); font-size: 12px; }
	.card-link { grid-column: 2; grid-row: 1 / 3; display: inline-flex; align-items: center; gap: 4px; color: var(--brand-primary); font-size: 13px; white-space: nowrap; }
	.empty { padding: 16px 0; color: var(--text-secondary); }
	.coverage, .versions { border-top: 1px solid var(--border-default); padding-top: 14px; color: var(--text-secondary); font-size: 13px; }
	summary { cursor: pointer; } .counts { display: flex; flex-wrap: wrap; gap: 8px 20px; }
	article { padding: 16px 0; border-bottom: 1px solid var(--border-default); overflow-wrap: anywhere; }
	h3 { font-size: 14px; color: var(--text-primary); margin: 0 0 8px; }
	blockquote { margin: 12px 0; padding-left: 12px; border-left: 2px solid var(--border-default); } a { color: var(--brand-primary); }
	.error { color: var(--danger-text); } .needs-review { display: block; margin-top: 6px; color: var(--warning-text); font-weight: 500; }
	@media (max-width: 600px) { .card-link { grid-column: 1; grid-row: 3; } }
</style>
