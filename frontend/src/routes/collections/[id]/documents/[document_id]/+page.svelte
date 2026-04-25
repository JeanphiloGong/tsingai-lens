<script lang="ts">
	import { page } from '$app/stores';
	import {
		buildDocumentWorkbenchModel,
		fetchDocumentComparisonSemantics,
		fetchDocumentContent,
		type DocumentWorkbenchModel,
		type WorkbenchLocalGraph,
		type WorkbenchTab
	} from '../../../../_shared/documents';
	import { t } from '../../../../_shared/i18n';
	import { fetchCollectionResults } from '../../../../_shared/results';
	import LocalGraphPanel from './_components/LocalGraphPanel.svelte';
	import PaperReader from './_components/PaperReader.svelte';
	import StructuredExtractionPanel from './_components/StructuredExtractionPanel.svelte';

	let model: DocumentWorkbenchModel | null = null;
	let loading = false;
	let loadedKey = '';
	let activeTab: WorkbenchTab = 'summary';
	let selectedItemId = '';
	let selectedSourceSpanId = '';
	let selectedGraphNodeId = '';
	let graphCollapsed = false;

	$: collectionId = $page.params.id ?? '';
	$: routeDocumentId = $page.params.document_id ?? '';
	$: requestedResultId = $page.url.searchParams.get('result_id')?.trim() ?? '';
	$: requestedEvidenceId = $page.url.searchParams.get('evidence_id')?.trim() ?? '';
	$: loadKey = `${collectionId}:${routeDocumentId}:${requestedResultId}:${requestedEvidenceId}`;
	$: selectedGraph = graphForSelection(model, selectedItemId);
	$: if (selectedGraph && !selectedGraph.nodes.some((node) => node.id === selectedGraphNodeId)) {
		selectedGraphNodeId = selectedGraph.nodes.find((node) => node.position === 'center')?.id ?? '';
	}
	$: if (collectionId && routeDocumentId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		void loadWorkbench();
	}

	function backHref() {
		return `/collections/${collectionId}/documents`;
	}

	async function loadWorkbench() {
		loading = true;

		const [contentResult, resultsResult, semanticsResult] = await Promise.allSettled([
			fetchDocumentContent(collectionId, routeDocumentId),
			fetchCollectionResults(collectionId, {
				source_document_id: routeDocumentId,
				limit: 20
			}),
			fetchDocumentComparisonSemantics(collectionId, routeDocumentId, {
				includeGroupedProjections: true
			})
		]);

		const content = contentResult.status === 'fulfilled' ? contentResult.value : null;
		const relatedResults = resultsResult.status === 'fulfilled' ? resultsResult.value.items : [];
		const comparisonSemantics =
			semanticsResult.status === 'fulfilled' ? semanticsResult.value : null;

		const nextModel = buildDocumentWorkbenchModel({
			collectionId,
			documentId: routeDocumentId,
			content,
			comparisonSemantics,
			relatedResults
		});
		model = nextModel;

		const requestedItemId =
			nextModel.selectable_items.find((item) => item.id === requestedResultId)?.id ||
			nextModel.selectable_items.find((item) => item.id === requestedEvidenceId)?.id ||
			nextModel.default_item_id;
		selectItem(requestedItemId);
		loading = false;
	}

	function graphForSelection(
		currentModel: DocumentWorkbenchModel | null,
		itemId: string
	): WorkbenchLocalGraph | null {
		if (!currentModel) return null;
		return (
			currentModel.graphs_by_item_id[itemId] ??
			currentModel.graphs_by_item_id[currentModel.default_item_id] ??
			null
		);
	}

	function selectItem(itemId: string, tab?: WorkbenchTab) {
		if (!model || !itemId) return;
		const item = model.selectable_items.find((candidate) => candidate.id === itemId);
		if (!item) return;
		selectedItemId = item.id;
		activeTab = tab ?? item.tab;
		selectedSourceSpanId = item.source_span_id;
		const graph = graphForSelection(model, item.id);
		selectedGraphNodeId = graph?.nodes.find((node) => node.position === 'center')?.id ?? '';
	}

	function jumpToSource(sourceSpanId: string) {
		selectedSourceSpanId = sourceSpanId;
	}

	function selectSourceSpan(sourceSpanId: string) {
		selectedSourceSpanId = sourceSpanId;
		const linkedItem = model?.selectable_items.find((item) => item.source_span_id === sourceSpanId);
		if (linkedItem) {
			selectItem(linkedItem.id);
		}
	}

	function handleGraphItemSelect(itemId: string) {
		selectItem(itemId);
	}

	function openTab(tab: WorkbenchTab) {
		activeTab = tab;
		const item = model?.selectable_items.find((candidate) => candidate.tab === tab);
		if (item) selectItem(item.id, tab);
	}
</script>

<svelte:head>
	<title>{model?.title ?? $t('workbench.pageTitle')}</title>
</svelte:head>

<div class="document-workbench-root">
	<header class="workbench-appbar">
		<a class="workbench-logo" href={`/collections/${collectionId}`}>
			<span class="logo-mark" aria-hidden="true">L</span>
			<span>Lens</span>
		</a>

		<div class="title-zone">
			<nav class="breadcrumb" aria-label={$t('workbench.breadcrumbLabel')}>
				<a href={`/collections/${collectionId}`}>{$t('workbench.workspace')}</a>
				<span>/</span>
				<a href={backHref()}>{$t('workbench.documents')}</a>
				<span>/</span>
			</nav>
			<div class="current-title">{model?.title ?? routeDocumentId}</div>
		</div>

		<label class="global-search">
			<span class="visually-hidden">{$t('workbench.searchLabel')}</span>
			<input placeholder={$t('workbench.searchPlaceholder')} />
			<kbd>Cmd K</kbd>
		</label>

		<div class="top-actions">
			<button type="button" on:click={() => openTab('summary')}
				>{$t('workbench.actionSummary')}</button
			>
			<button type="button" on:click={() => openTab('evidence')}
				>{$t('workbench.actionEvidence')}</button
			>
			<button type="button" on:click={() => (graphCollapsed = !graphCollapsed)}>
				{$t('workbench.actionGraph')}
			</button>
			<button class="primary" type="button">{$t('workbench.actionExport')}</button>
		</div>
	</header>

	{#if loading && !model}
		<main class="workbench-main">
			<section class="loading-panel" aria-label={$t('workbench.loading')}>
				<div class="skeleton skeleton--wide"></div>
				<div class="skeleton"></div>
				<div class="skeleton skeleton--short"></div>
			</section>
		</main>
	{:else if model}
		<main class="workbench-main">
			<section class="reader-column">
				<PaperReader
					title={model.title}
					metadata={model.metadata}
					pages={model.pages}
					activeSourceSpanId={selectedSourceSpanId}
					onSelectSourceSpan={selectSourceSpan}
				/>
			</section>

			<section class="extraction-column">
				<StructuredExtractionPanel
					{model}
					{activeTab}
					{selectedItemId}
					onSelectItem={selectItem}
					onJumpToSource={jumpToSource}
				/>
			</section>

			<section class:graph-column--collapsed={graphCollapsed} class="graph-column">
				<LocalGraphPanel
					graph={selectedGraph}
					selectedNodeId={selectedGraphNodeId}
					collapsed={graphCollapsed}
					onToggleCollapse={() => (graphCollapsed = !graphCollapsed)}
					onSelectNode={(nodeId) => (selectedGraphNodeId = nodeId)}
					onSelectItem={handleGraphItemSelect}
					onJumpToSource={jumpToSource}
				/>
			</section>
		</main>
	{/if}
</div>

<style>
	.document-workbench-root {
		position: fixed;
		inset: 0;
		z-index: 100;
		overflow: hidden;
		background: #f6f9fd;
		color: #0f172a;
		font-family:
			system-ui,
			-apple-system,
			BlinkMacSystemFont,
			'Segoe UI',
			sans-serif;
	}

	.workbench-appbar {
		display: grid;
		grid-template-columns: 120px minmax(0, 1fr) 320px 420px;
		height: 64px;
		align-items: center;
		gap: 16px;
		padding: 0 24px;
		border-bottom: 1px solid #e2e8f0;
		background: rgba(255, 255, 255, 0.92);
		backdrop-filter: blur(12px);
	}

	.workbench-logo {
		display: flex;
		width: 120px;
		align-items: center;
		gap: 10px;
		color: #0f172a;
		font-size: 18px;
		font-weight: 700;
	}

	.logo-mark {
		display: grid;
		width: 32px;
		height: 32px;
		place-items: center;
		border-radius: 10px;
		background: #2563eb;
		color: #ffffff;
		font-size: 16px;
		font-weight: 800;
	}

	.title-zone {
		min-width: 0;
	}

	.breadcrumb {
		display: flex;
		align-items: center;
		gap: 8px;
		color: #64748b;
		font-size: 13px;
		line-height: 18px;
	}

	.current-title {
		max-width: 420px;
		overflow: hidden;
		color: #0f172a;
		font-size: 14px;
		font-weight: 600;
		line-height: 20px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.global-search {
		display: flex;
		width: 320px;
		height: 38px;
		align-items: center;
		gap: 8px;
		padding: 0 12px;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		background: #ffffff;
	}

	.global-search input {
		min-width: 0;
		flex: 1;
		border: 0;
		outline: 0;
		background: transparent;
		color: #0f172a;
		font-size: 13px;
	}

	.global-search kbd {
		color: #64748b;
		font-size: 12px;
		font-weight: 700;
	}

	.top-actions {
		display: flex;
		width: 420px;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
	}

	.top-actions button {
		display: inline-flex;
		height: 38px;
		align-items: center;
		justify-content: center;
		gap: 8px;
		padding: 0 14px;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		background: #ffffff;
		color: #0f172a;
		font-size: 14px;
		font-weight: 600;
		cursor: pointer;
	}

	.top-actions button:hover {
		background: #f8fafc;
	}

	.top-actions .primary {
		border-color: #2563eb;
		background: #2563eb;
		color: #ffffff;
	}

	.top-actions .primary:hover {
		background: #1d4ed8;
	}

	.workbench-main {
		display: grid;
		height: calc(100vh - 64px);
		grid-template-columns: 700px 480px 420px;
		column-gap: 16px;
		padding: 16px 20px 20px;
		box-sizing: border-box;
		overflow: hidden;
	}

	.reader-column,
	.extraction-column,
	.graph-column {
		min-width: 0;
		height: 100%;
		overflow: hidden;
	}

	.loading-panel {
		grid-column: 1 / -1;
		display: grid;
		width: 100%;
		height: 100%;
		place-content: center;
		gap: 12px;
		border: 1px dashed #cbd5e1;
		border-radius: 14px;
		background: #f8fafc;
	}

	.skeleton {
		width: 280px;
		height: 16px;
		border-radius: 8px;
		background: linear-gradient(90deg, #f1f5f9, #e2e8f0, #f1f5f9);
	}

	.skeleton--wide {
		width: 420px;
	}

	.skeleton--short {
		width: 180px;
	}

	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	@media (min-width: 1729px) {
		.workbench-main {
			grid-template-columns: minmax(700px, 760px) 500px 420px;
		}
	}

	@media (max-width: 1440px) {
		.workbench-appbar {
			grid-template-columns: 120px minmax(0, 1fr) 280px minmax(320px, 420px);
		}

		.global-search {
			width: 280px;
		}

		.top-actions {
			width: auto;
		}

		.workbench-main {
			grid-template-columns: minmax(0, 52%) minmax(420px, 31%) minmax(300px, 17%);
		}
	}

	@media (max-width: 1280px) {
		.workbench-appbar {
			grid-template-columns: 120px minmax(0, 1fr) 260px auto;
		}

		.global-search {
			width: 260px;
		}

		.workbench-main {
			grid-template-columns: minmax(0, 52%) minmax(420px, 1fr);
		}

		.graph-column {
			position: fixed;
			top: 64px;
			right: 0;
			bottom: 0;
			z-index: 120;
			width: 420px;
			padding: 16px 20px 20px 0;
			background: #f6f9fd;
			transform: translateX(0);
			transition: transform 0.18s ease;
		}

		.graph-column--collapsed {
			transform: translateX(100%);
		}
	}

	@media (max-width: 1024px) {
		.document-workbench-root {
			overflow: auto;
		}

		.workbench-appbar {
			grid-template-columns: 120px minmax(0, 1fr);
			height: auto;
			min-height: 64px;
			padding: 12px 16px;
		}

		.global-search,
		.top-actions {
			grid-column: 1 / -1;
			width: 100%;
		}

		.workbench-main {
			height: auto;
			min-height: calc(100vh - 64px);
			grid-template-columns: 1fr;
			row-gap: 16px;
			overflow: visible;
		}

		.reader-column {
			height: 760px;
		}

		.extraction-column {
			height: 720px;
		}

		.graph-column {
			display: none;
		}
	}
</style>
