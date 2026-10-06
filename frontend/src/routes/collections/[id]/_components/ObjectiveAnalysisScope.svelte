<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { resolve } from '$app/paths';
	import { ExternalLink, Play, RefreshCw, ChevronLeft, ChevronRight } from '@lucide/svelte';
	import { listCollectionDocuments, type CollectionDocument } from '../../../_shared/collectionDocuments';
	import { fetchObjectiveScope, runObjectiveAnalysis, type ObjectiveAnalysis, type ObjectiveScope } from '../../../_shared/researchView';
	import { errorMessage } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	export let collectionId: string;
	export let analysis: ObjectiveAnalysis;
	export let documentTitles: Record<string, string> = {};
	export let onStarted: (result: ObjectiveAnalysis) => void;
	let scope: ObjectiveScope | null = null;
	let papers: CollectionDocument[] = [];
	let selected: string[] = [];
	let query = '';
	let pageIndex = 0;
	let loading = true;
	let saving = false;
	let error = '';
	let disposed = false;
	let requestSequence = 0;
	let previousQuery = '';
	$: processing = ['queued', 'running'].includes(analysis.active_analysis?.status ?? '');
	$: matches = papers.filter(paper => [paper.original_filename, documentTitles[paper.document_id]].join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
	$: if (query !== previousQuery) { previousQuery = query; pageIndex = 0; }
	$: pages = Math.max(1, Math.ceil(matches.length / 8));
	$: if (pageIndex >= pages) pageIndex = pages - 1;
	$: visible = matches.slice(pageIndex * 8, (pageIndex + 1) * 8);
	onMount(() => { void load(); });
	onDestroy(() => { disposed = true; requestSequence++; });
	async function load() {
		const sequence = ++requestSequence;
		loading = true; error = '';
		try {
			const [preview, documents] = await Promise.all([fetchObjectiveScope(collectionId, analysis.objective.objective_id), listCollectionDocuments(collectionId)]);
			if (disposed || sequence !== requestSequence) return;
			scope = preview; papers = documents.items.filter(paper => paper.status === 'ready');
			const frozen = analysis.active_analysis?.document_inputs ?? analysis.published_analysis?.document_inputs;
			selected = (frozen ? frozen.map(item => item.document_id) : preview.recommended_document_ids).filter(id => papers.some(paper => paper.document_id === id));
		} catch (err) { if (!disposed && sequence === requestSequence) error = errorMessage(err); }
		finally { if (!disposed && sequence === requestSequence) loading = false; }
	}
	function toggle(id: string) { selected = selected.includes(id) ? selected.filter(value => value !== id) : [...selected, id]; }
	async function start() {
		if (!selected.length || loading || saving || processing) return;
		saving = true; error = '';
		try {
			const result = await runObjectiveAnalysis(collectionId, analysis.objective.objective_id, selected);
			if (!disposed) onStarted(result);
		} catch (err) { if (!disposed) error = errorMessage(err); }
		finally { if (!disposed) saving = false; }
	}
</script>

<section class="scope" aria-label={$t('objectiveWorkspace.scope')}>
	<div class="paper-picker">
		<header><h2>{$t('objectiveWorkspace.scope')}</h2><span>{$t('objectiveWorkspace.selected', { count: selected.length })}</span></header>
		<input type="search" bind:value={query} aria-label={$t('objectiveWorkspace.scopeSearch')} placeholder={$t('objectiveWorkspace.scopeSearch')} />
		{#if loading}<p aria-busy="true">{$t('objectiveWorkspace.scopeLoading')}</p>
		{:else if error && !scope}<p role="alert">{error}</p><button type="button" class="btn btn--ghost" on:click={load}><RefreshCw size={16} />{$t('objectiveWorkspace.retry')}</button>
		{:else}
			<div class="paper-list">{#each visible as paper (paper.document_id)}
				{@const decision = scope?.decisions.find(item => item.document_id === paper.document_id)}
					<div class="paper-row"><label><input type="checkbox" checked={selected.includes(paper.document_id)} disabled={saving || processing} on:change={() => toggle(paper.document_id)} /><span><strong>{documentTitles[paper.document_id] || paper.original_filename}</strong><small title={decision?.reason}>{$t(`objectiveWorkspace.${decision?.classification === 'likely_relevant' ? 'recommended' : decision?.classification === 'confidently_out_of_scope' ? 'outside' : 'inspect'}`)}</small></span></label><a href={resolve('/collections/[id]/documents/[document_id]', { id: collectionId, document_id: paper.document_id })} aria-label={`${$t('objectiveWorkspace.openPaper')}: ${paper.original_filename}`} title={$t('objectiveWorkspace.openPaper')}><ExternalLink size={17} /></a></div>
			{:else}<p>{papers.length ? $t('objectiveWorkspace.noMatches') : $t('objectiveWorkspace.noReady')}</p>{/each}</div>
			{#if pages > 1}<nav aria-label={$t('objectiveWorkspace.scope')}><button type="button" disabled={!pageIndex} on:click={() => pageIndex--} aria-label={$t('objectiveWorkspace.previous')}><ChevronLeft size={18} /></button><span>{$t('objectiveWorkspace.page', { current: pageIndex + 1, total: pages })}</span><button type="button" disabled={pageIndex + 1 >= pages} on:click={() => pageIndex++} aria-label={$t('objectiveWorkspace.next')}><ChevronRight size={18} /></button></nav>{/if}
		{/if}
	</div>
	<aside><dl>{#each [['material', analysis.objective.material_scope], ['variables', analysis.objective.variables], ['outcome', analysis.objective.outcomes], ['limits', analysis.objective.constraints]] as [key, values]}<div><dt>{$t(`objectiveWorkspace.${key}`)}</dt><dd>{(values as string[]).join(' · ') || $t('objectiveWorkspace.notReported')}</dd></div>{/each}</dl>
		{#if analysis.published_analysis}<p>{$t('objectiveWorkspace.currentScope')}: {$t('objectiveWorkspace.papers', { count: analysis.published_analysis.document_inputs.length })}</p>{/if}
		<button class="btn btn--primary" type="button" disabled={loading || saving || processing || !selected.length || !scope} on:click={start}><Play size={16} />{$t(saving ? 'objectiveWorkspace.starting' : 'objectiveWorkspace.start')}</button>
		{#if !loading && !selected.length}<p>{$t('objectiveWorkspace.scopeRequired')}</p>{/if}
		{#if analysis.published_analysis}<p>{$t('objectiveWorkspace.retained')}</p>{/if}
		{#if error && scope}<p role="alert">{error}</p>{/if}
	</aside>
</section>

<style>
	.scope { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 32px; align-items: start; }
	header, nav { display: flex; gap: 12px; align-items: center; } header { justify-content: space-between; margin-bottom: 16px; } h2 { font-size: 18px; margin: 0; } header span, small, dt, aside p { color: var(--text-secondary); font-size: 13px; }
	input[type='search'] { width: 100%; padding: 10px 12px; background: var(--surface-card); border: 1px solid var(--border-default); border-radius: 4px; } .paper-list { margin-top: 20px; border-top: 1px solid var(--border-default); }
	.paper-row { display: flex; gap: 16px; align-items: center; padding: 16px 0; border-bottom: 1px solid var(--border-default); } label { display: flex; align-items: flex-start; gap: 12px; flex: 1; min-width: 0; } label span { display: grid; gap: 6px; min-width: 0; overflow-wrap: anywhere; } strong { font-size: 14px; font-weight: 500; } input[type='checkbox'] { margin-top: 3px; width: 17px; height: 17px; accent-color: var(--brand-primary); }
	a { color: var(--brand-primary); padding: 6px; } aside { border-left: 1px solid var(--border-default); padding-left: 24px; } dl { display: grid; gap: 20px; margin: 0 0 24px; } dd { margin: 5px 0 0; font-size: 14px; overflow-wrap: anywhere; } aside button { width: 100%; border-radius: 5px; } aside p { margin-top: 12px; line-height: 1.5; } [role='alert'] { color: var(--danger-text); }
	nav { justify-content: flex-end; margin-top: 16px; } nav button { background: var(--surface-card); border: 1px solid var(--border-default); border-radius: 4px; padding: 6px; } nav button:disabled { opacity: .5; }
	@media (max-width: 760px) { .scope { grid-template-columns: minmax(0, 1fr); } aside { border-left: 0; border-top: 1px solid var(--border-default); padding: 20px 0; } }
</style>
