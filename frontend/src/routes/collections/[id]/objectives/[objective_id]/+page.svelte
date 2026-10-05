<script lang="ts">
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { onDestroy } from 'svelte';
	import { ArrowLeft, Download, RefreshCw, X } from '@lucide/svelte';
	import FindingAuthoringEditor from '../../_components/FindingAuthoringEditor.svelte';
	import FindingWorkbench from '../../_components/FindingWorkbench.svelte';
	import ExperimentResults from '../../_components/ExperimentResults.svelte';
	import ObjectiveResultsOverview from '../../_components/ObjectiveResultsOverview.svelte';
	import { downloadBlob, errorMessage } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import { fetchDocumentProfiles } from '../../../../_shared/documents';
	import {
		fetchObjectiveAnalysis, fetchObjectiveAnalysisStatus, fetchObjectiveEvidence,
		fetchExperimentAnalysis, experimentAnalysisExportUrl, fetchObjectiveFindings,
		objectiveFindingDatasetUrl,
		type FindingDatasetLabelStatus, type FindingDatasetUseStatus, type ObjectiveAnalysis,
		type ObjectiveEvidence, type ObjectiveFinding, type FindingAuthoringResult,
		type FindingEvidenceReview, type ExperimentAnalysisProjection
	} from '../../../../_shared/researchView';

	let analysis: ObjectiveAnalysis | null = null;
	let findings: ObjectiveFinding[] = [];
	let evidenceReviews: Record<string, FindingEvidenceReview> = {};
	let evidence: ObjectiveEvidence[] = [];
	let documentTitles: Record<string, string> = {};
	let selectedFinding: ObjectiveFinding | null = null;
	let selectedFindingId = '';
	let loading = true;
	let findingLoading = false;
	let error = '';
	let actionError = '';
	let findingError = '';
	let loadedKey = '';
	let loadSequence = 0;
	let evidenceSequence = 0;
	let projectionSequence = 0;
	let disposed = false;
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let authoringOpen = false;
	let authoringParent: ObjectiveFinding | null = null;
	let projection: ExperimentAnalysisProjection | null = null;
	let experimentLoading = false;
	let experimentError = '';
	let view: 'results' | 'scope' = 'results';
	let exportOpen = false;
	let exportFormat: 'json' | 'csv' = 'csv';
	let exportLoading = false;
	let exportError = '';
	let datasetLabelStatus: FindingDatasetLabelStatus | '' = '';
	let datasetUseStatus: FindingDatasetUseStatus | '' = '';

	$: collectionId = $page.params.id ?? '';
	$: objectiveId = $page.params.objective_id ?? '';
	$: requestedFindingId = $page.url.searchParams.get('finding_id') ?? '';
	$: published = analysis?.published_analysis ?? null;
	$: active = analysis?.active_analysis ?? null;
	$: isProcessing = active?.status === 'queued' || active?.status === 'running';
	$: if (browser && collectionId && objectiveId && loadedKey !== collectionId + ':' + objectiveId) {
		loadedKey = collectionId + ':' + objectiveId;
		closeAuthoring();
		exportOpen = false;
		void loadObjective();
	}
	$: if (browser && !loading && analysis) syncFinding(requestedFindingId);

	onDestroy(() => {
		disposed = true;
		loadSequence++;
		evidenceSequence++;
		projectionSequence++;
		clearPoll();
	});

	async function loadObjective(preferredFindingId?: string) {
		const sequence = ++loadSequence;
		const key = loadedKey;
		const ids = [collectionId, objectiveId] as const;
		evidenceSequence++;
		projectionSequence++;
		loading = true;
		error = '';
		clearPoll();
		try {
			const [result, profiles] = await Promise.allSettled([
				fetchObjectiveAnalysis(...ids), fetchDocumentProfiles(ids[0])
			]);
			if (disposed || sequence !== loadSequence || key !== loadedKey) return;
			if (result.status === 'rejected') throw result.reason;
			analysis = result.value;
			documentTitles = profiles.status === 'fulfilled'
				? Object.fromEntries(profiles.value.items.map(item => [item.document_id, item.title || ''])) : {};
			view = analysis.published_analysis ? 'results' : 'scope';
			await Promise.all([loadFindings(), loadProjection()]);
			if (disposed || sequence !== loadSequence || key !== loadedKey) return;
			if (preferredFindingId !== undefined) await navigateFinding(preferredFindingId, true);
			await selectFinding(preferredFindingId ?? requestedFindingId);
			schedulePoll();
		} catch (err) {
			if (disposed || sequence !== loadSequence) return;
			error = errorMessage(err);
			analysis = null;
			findings = [];
			selectedFinding = null;
			evidence = [];
		} finally {
			if (!disposed && sequence === loadSequence) loading = false;
		}
	}

	async function loadProjection() {
		const sequence = ++projectionSequence;
		const key = loadedKey;
		const version = analysis?.objective.published_analysis_version;
		projection = null;
		experimentError = '';
		experimentLoading = Boolean(version);
		if (!version) return;
		try {
			const result = await fetchExperimentAnalysis(collectionId, objectiveId, version);
			if (!disposed && sequence === projectionSequence && key === loadedKey) projection = result;
		} catch (err) {
			if (!disposed && sequence === projectionSequence && key === loadedKey) experimentError = errorMessage(err);
		} finally {
			if (!disposed && sequence === projectionSequence) experimentLoading = false;
		}
	}

	async function loadFindings() {
		const version = analysis?.objective.published_analysis_version;
		const key = loadedKey;
		const items: ObjectiveFinding[] = [];
		const reviews: Record<string, FindingEvidenceReview> = {};
		if (version) {
			while (true) {
				const result = await fetchObjectiveFindings(collectionId, objectiveId, version, items.length, 200);
				if (disposed || key !== loadedKey || version !== analysis?.objective.published_analysis_version) return;
				items.push(...result.items);
				Object.assign(reviews, result.evidence_reviews);
				if (items.length >= result.total) break;
				if (!result.items.length) throw new Error($t('objectiveWorkspace.incomplete'));
			}
		}
		findings = items;
		evidenceReviews = reviews;
	}

	function syncFinding(id: string) {
		if (id === selectedFindingId) return;
		closeAuthoring();
		view = 'results';
		void selectFinding(id);
	}

	async function navigateFinding(id: string, replaceState = false) {
		closeAuthoring();
		view = 'results';
		const url = new URL($page.url);
		if (id) url.searchParams.set('finding_id', id);
		else url.searchParams.delete('finding_id');
		await goto(resolve('/collections/[id]/objectives/[objective_id]', { id: collectionId, objective_id: objectiveId }) + url.search, { replaceState, noScroll: true });
	}

	async function selectFinding(id: string) {
		const sequence = ++evidenceSequence;
		const key = loadedKey;
		const version = analysis?.objective.published_analysis_version;
		selectedFindingId = id;
		selectedFinding = findings.find(item => item.finding_id === id) ?? null;
		evidence = [];
		findingError = id && !selectedFinding ? $t('objectiveWorkspace.missingFinding') : '';
		findingLoading = false;
		if (!selectedFinding || !version) return;
		findingLoading = true;
		try {
			const items: ObjectiveEvidence[] = [];
			while (true) {
				const result = await fetchObjectiveEvidence(collectionId, objectiveId, version, id, items.length, 500);
				if (disposed || sequence !== evidenceSequence || key !== loadedKey) return;
				items.push(...result.items);
				if (items.length >= result.total) break;
				if (!result.items.length) throw new Error($t('objectiveWorkspace.incomplete'));
			}
			evidence = items;
		} catch (err) {
			if (!disposed && sequence === evidenceSequence) findingError = errorMessage(err);
		} finally {
			if (!disposed && sequence === evidenceSequence) findingLoading = false;
		}
	}

	function openAuthoring(parent: ObjectiveFinding | null = null) {
		authoringParent = parent;
		authoringOpen = true;
	}
	function closeAuthoring() { authoringOpen = false; authoringParent = null; }
	async function handleFindingSaved(result: FindingAuthoringResult) {
		closeAuthoring();
		await loadObjective(result.finding?.finding_id ?? '');
	}
	async function handleScopeStarted(result: ObjectiveAnalysis) {
		analysis = result;
		view = result.published_analysis ? 'results' : 'scope';
		actionError = '';
		if (result.objective.published_analysis_version) {
			await Promise.all([loadFindings(), loadProjection()]);
			view = 'results';
		}
		schedulePoll();
	}
	function clearPoll() {
		if (pollTimer) clearTimeout(pollTimer);
		pollTimer = null;
	}
	function schedulePoll() {
		clearPoll();
		if (!disposed && ['queued', 'running'].includes(analysis?.active_analysis?.status ?? '')) {
			pollTimer = setTimeout(() => void refreshAnalysis(), 2500);
		}
	}
	async function refreshAnalysis() {
		const key = loadedKey;
		actionError = '';
		try {
			const status = await fetchObjectiveAnalysisStatus(collectionId, objectiveId);
			if (disposed || key !== loadedKey) return;
			if (status.status === 'queued' || status.status === 'running') {
				if (analysis?.active_analysis) analysis = { ...analysis, active_analysis: { ...analysis.active_analysis, ...status } };
			} else {
				const previous = analysis?.objective.published_analysis_version;
				const result = await fetchObjectiveAnalysis(collectionId, objectiveId);
				if (disposed || key !== loadedKey) return;
				analysis = result;
				if (previous !== result.objective.published_analysis_version) {
					evidenceSequence++;
					closeAuthoring();
					await Promise.all([loadFindings(), loadProjection()]);
					if (disposed || key !== loadedKey) return;
					const id = findings.some(item => item.finding_id === requestedFindingId) ? requestedFindingId : '';
					if (id !== requestedFindingId) await navigateFinding(id, true);
					await selectFinding(id);
				}
			}
			schedulePoll();
		} catch (err) {
			if (!disposed && key === loadedKey) actionError = errorMessage(err);
			clearPoll();
		}
	}
	function showExport(node: HTMLDialogElement) { node.showModal(); }
	async function downloadData(format: 'csv' | 'json' | 'training_jsonl' | 'llamafactory_alpaca', dataset = false) {
		if (!published || exportLoading) return;
		exportLoading = true;
		exportError = '';
		try {
			const version = published.analysis_version;
			const path = dataset
				? objectiveFindingDatasetUrl(collectionId, objectiveId, format as 'json' | 'training_jsonl' | 'llamafactory_alpaca', {
					...(datasetLabelStatus ? { label_status: datasetLabelStatus } : {}),
					...(datasetUseStatus ? { dataset_use_status: datasetUseStatus } : {})
				})
				: experimentAnalysisExportUrl(collectionId, objectiveId, version, format as 'csv' | 'json');
			await downloadBlob(path, 'objective-' + objectiveId + '-v' + version + (dataset ? '-findings' : '-experiments') + '.' + (format === 'csv' || format === 'json' ? format : 'jsonl'));
		} catch (err) { exportError = errorMessage(err); }
		finally { exportLoading = false; }
	}
</script>

<svelte:head><title>{analysis?.objective.question ?? $t('objectiveWorkspace.list')}</title></svelte:head>

{#if loading}
	<p class="page-state" aria-busy="true">{$t('objectiveWorkspace.loading')}</p>
{:else if error || !analysis}
	<div class="page-state" role="alert"><p>{error || $t('objectiveWorkspace.missingObjective')}</p><button class="btn btn--ghost" on:click={() => loadObjective()}><RefreshCw size={16} />{$t('objectiveWorkspace.retry')}</button></div>
{:else}
	<section class="objective-page">
		<header class="objective-header">
			<div>
				<a class="back" href={resolve('/collections/[id]/objectives', { id: collectionId })}><ArrowLeft size={16} />{$t('objectiveWorkspace.list')}</a>
				<h1>{analysis.objective.question}</h1>
				<p class="meta">{analysis.objective.material_scope.join(' · ')}{#if published} · {$t('objectiveWorkspace.publishedVersion', { version: published.analysis_version })}{/if}</p>
			</div>
			{#if published}<button class="btn btn--ghost btn--small" on:click={() => { exportError = ''; exportOpen = true; }}><Download size={16} />{$t('objectiveWorkspace.export')}</button>{/if}
		</header>
		{#if active && active.status !== 'succeeded'}
			<div class="analysis-state" class:failed={active.status === 'failed'} role="status">
				<strong>{$t(isProcessing ? 'objectiveWorkspace.active' : 'objectiveWorkspace.failed')}</strong>
				<span>{active.status === 'failed' ? $t('researchAgent.capability.analysisFailed') : active.progress_message || $t('objectiveWorkspace.runProgress', { processed: active.processed_document_count, total: active.total_document_count })}</span>
				{#if published}<span>{$t('objectiveWorkspace.retained')}</span>{/if}
				{#if active.status === 'failed'}<button class="btn btn--ghost btn--small" on:click={() => view = 'scope'}>{$t('objectiveWorkspace.scope')}</button>{/if}
			</div>
		{/if}
		{#if actionError}<div role="alert"><p>{actionError}</p><button class="btn btn--ghost" on:click={refreshAnalysis}><RefreshCw size={16} />{$t('objectiveWorkspace.retry')}</button></div>{/if}
		{#if published?.abstention_reason}<p class="analysis-state">{published.abstention_note || $t('objectiveWorkspace.emptyFindings')}</p>{/if}
		<ObjectiveResultsOverview {analysis} {projection} {experimentLoading} {experimentError} {findings} {evidenceReviews} {collectionId} {documentTitles} bind:view {selectedFindingId} {authoringOpen} onSelectFinding={navigateFinding} onScopeStarted={handleScopeStarted} onRetryProjection={loadProjection} onNewFinding={() => openAuthoring()}>
			<section slot="selected" class="finding-workspace" aria-label={$t('objectiveWorkspace.findingDetail')} aria-busy={findingLoading}>
				{#if authoringOpen && published}
					{#key published.analysis_version + ':' + (authoringParent?.finding_id ?? '')}
						<FindingAuthoringEditor {collectionId} {objectiveId} analysisVersion={published.analysis_version} parentFinding={authoringParent} onSaved={handleFindingSaved} onCancel={closeAuthoring} />
					{/key}
				{:else if findingLoading}<p class="page-state">{$t('objectiveWorkspace.loading')}</p>
				{:else if findingError}<div role="alert"><p>{findingError}</p>{#if selectedFinding}<button class="btn btn--ghost" on:click={() => selectFinding(selectedFindingId)}><RefreshCw size={16} />{$t('objectiveWorkspace.retry')}</button>{/if}</div>
				{:else if selectedFinding}
					<FindingWorkbench finding={selectedFinding} evidenceReview={evidenceReviews[selectedFinding.finding_id] ?? null} derivedFindings={findings.filter(item => item.parent_finding_id === selectedFinding?.finding_id)} parentFinding={findings.find(item => item.finding_id === selectedFinding?.parent_finding_id) ?? null} onSelectFinding={finding => navigateFinding(finding.finding_id)} {evidence} {collectionId} {documentTitles} onDerive={openAuthoring}>
						<div slot="comparison">
							{#if projection}<ExperimentResults {projection} {collectionId} {objectiveId} {documentTitles} findingId={selectedFinding.finding_id} selectionIds={selectedFinding.selection_ids ?? []} />
							{:else}<p role="alert">{experimentError || $t('objectiveWorkspace.unavailable')}</p><button class="btn btn--ghost" on:click={loadProjection}><RefreshCw size={16} />{$t('objectiveWorkspace.retry')}</button>{/if}
						</div>
					</FindingWorkbench>
				{/if}
			</section>
		</ObjectiveResultsOverview>
	</section>
	{#if exportOpen && published}
		<dialog use:showExport on:close={() => exportOpen = false} on:cancel={() => exportOpen = false} aria-labelledby="objective-export-title">
			<header><h2 id="objective-export-title">{$t('objectiveWorkspace.exportTitle')}</h2><button class="icon-button" title={$t('objectiveWorkspace.cancel')} aria-label={$t('objectiveWorkspace.cancel')} on:click={() => exportOpen = false}><X size={18} /></button></header>
			<p>{$t('objectiveWorkspace.exportScope', { version: published.analysis_version })}</p>
			<fieldset disabled={exportLoading}><legend>{$t('objectiveWorkspace.format')}</legend>
				<label><input type="radio" bind:group={exportFormat} value="csv" />{$t('objectiveWorkspace.csv')}</label>
				<label><input type="radio" bind:group={exportFormat} value="json" />{$t('objectiveWorkspace.json')}</label>
			</fieldset>
			<details><summary>{$t('objectiveWorkspace.dataset')}</summary>
				<div class="dataset-filters">
					<label>{$t('objectiveWorkspace.labelStatus')}<select bind:value={datasetLabelStatus}><option value="">{$t('objectiveWorkspace.all')}</option>{#each ['candidate', 'silver', 'gold', 'rejected'] as status}<option value={status}>{$t('objectiveWorkspace.' + status)}</option>{/each}</select></label>
					<label>{$t('objectiveWorkspace.useStatus')}<select bind:value={datasetUseStatus}><option value="">{$t('objectiveWorkspace.all')}</option>{#each ['training_ready', 'review_candidate', 'rejected'] as status}<option value={status}>{$t('objectiveWorkspace.' + status)}</option>{/each}</select></label>
				</div>
				<div class="dataset-actions">{#each ['json', 'training_jsonl', 'llamafactory_alpaca'] as format}<button class="btn btn--ghost btn--small" disabled={exportLoading} on:click={() => downloadData(format as 'json' | 'training_jsonl' | 'llamafactory_alpaca', true)}><Download size={14} />{format === 'json' ? 'JSON' : format === 'training_jsonl' ? 'JSONL' : 'LlamaFactory JSONL'}</button>{/each}</div>
			</details>
			{#if exportError}<p role="alert">{exportError}</p>{/if}
			<footer><button class="btn btn--ghost" on:click={() => exportOpen = false}>{$t('objectiveWorkspace.cancel')}</button><button class="btn btn--primary" disabled={exportLoading} on:click={() => downloadData(exportFormat)}><Download size={16} />{$t(exportLoading ? 'objectiveWorkspace.downloading' : 'objectiveWorkspace.download')}</button></footer>
		</dialog>
	{/if}
{/if}

<style>
	.objective-page { width: min(1360px, 100%); margin: 0 auto; display: grid; gap: 20px; min-width: 0; }
	.objective-header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; }
	.objective-header > div { min-width: 0; } .objective-header > button { flex-shrink: 0; }
	h1 { margin: 12px 0 8px; font-size: 22px; line-height: 1.4; overflow-wrap: anywhere; }
	.back { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 13px; }
	.meta { margin: 0; color: var(--text-secondary); font-size: 13px; }
	.analysis-state { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; padding: 12px 16px; border-left: 3px solid var(--brand-primary); background: var(--brand-soft); font-size: 13px; }
	.analysis-state.failed { border-color: var(--danger-text); background: var(--danger-bg); }
	.finding-workspace { min-width: 0; } .page-state { padding: 28px 0; color: var(--text-secondary); }
	[role='alert'] { color: var(--danger-text); }
	dialog { width: min(480px, calc(100vw - 32px)); max-height: calc(100dvh - 40px); box-sizing: border-box; padding: 24px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); }
	dialog::backdrop { background: rgb(0 0 0 / 40%); }
	dialog header, dialog footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
	dialog h2 { margin: 0; font-size: 18px; } dialog p, dialog summary { font-size: 13px; color: var(--text-secondary); }
	.icon-button { display: grid; place-items: center; width: 32px; height: 32px; border: 0; background: transparent; color: inherit; cursor: pointer; }
	fieldset { border: 0; padding: 12px 0 20px; margin: 0; display: grid; gap: 12px; font-size: 14px; }
	fieldset label { display: flex; gap: 8px; } legend { font-size: 13px; }
	dialog details { border-top: 1px solid var(--border-default); padding: 12px 0; } summary { cursor: pointer; }
	.dataset-filters { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px; }
	.dataset-filters label { display: grid; gap: 8px; font-size: 13px; min-width: 0; }
	select { width: 100%; min-height: 34px; border: 1px solid var(--border-default); border-radius: 4px; background: var(--surface-card); color: inherit; }
	.dataset-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
	dialog footer { justify-content: flex-end; margin-top: 20px; }
	@media (max-width: 700px) { .objective-header { flex-wrap: wrap; } h1 { font-size: 20px; } }
</style>
