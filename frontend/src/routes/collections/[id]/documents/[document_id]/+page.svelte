<script lang="ts">
	import { browser } from '$app/environment';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../../_shared/api';
	import {
		buildDocumentWorkbenchModel,
		fetchDocumentComparisonSemantics,
		fetchDocumentContent,
		type DocumentComparisonSemanticsResponse,
		type DocumentContentResponse,
		type DocumentWorkbenchModel,
		type SourceAnchor,
		type WorkbenchLocalGraph,
		type WorkbenchSelectableItem,
		type WorkbenchTab
	} from '../../../../_shared/documents';
	import { t } from '../../../../_shared/i18n';
	import { fetchCollectionResults, type ResultListItem } from '../../../../_shared/results';
	import {
		fetchEvidenceTraceback,
		type EvidenceTracebackResponse
	} from '../../../../_shared/traceback';
	import {
		fetchDocumentResearchView,
		formatEvidenceBackedValue,
		type ConditionSeries,
		type EvidenceBackedValue,
		type PaperAggregation,
		type SampleMatrixColumn,
		type SampleMatrixRow
	} from '../../../../_shared/researchView';
	import LocalGraphPanel from './_components/LocalGraphPanel.svelte';
	import PaperReader from './_components/PaperReader.svelte';
	import StructuredExtractionPanel from './_components/StructuredExtractionPanel.svelte';

	let model: DocumentWorkbenchModel | null = null;
	let paperAggregation: PaperAggregation | null = null;
	let paperResearchError = '';
	let selectedPaperMaterialId = '';
	let selectedMatrixValue: EvidenceBackedValue | null = null;
	let loading = false;
	let loadedKey = '';
	let appliedRequestKey = '';
	let loadGeneration = 0;
	let activeTab: WorkbenchTab = 'overview';
	let selectedItemId = '';
	let selectedSourceSpanId = '';
	let selectedGraphNodeId = '';
	let graphCollapsed = false;
	let extractionDetailsOpen = false;
	let sourceJumpToken = 0;
	let contentForModel: DocumentContentResponse | null = null;
	let comparisonSemanticsForModel: DocumentComparisonSemanticsResponse | null = null;
	let relatedResultsForModel: ResultListItem[] = [];
	let evidenceTracebacksById = new Map<string, EvidenceTracebackResponse>();
	let loadingTracebackIds = new Set<string>();

	type SelectItemOptions = {
		preserveGraphNodeId?: string;
		skipTracebackFetch?: boolean;
	};

	$: collectionId = $page.params.id ?? '';
	$: routeDocumentId = $page.params.document_id ?? '';
	$: requestedResultId = $page.url.searchParams.get('result_id')?.trim() ?? '';
	$: requestedEvidenceId = $page.url.searchParams.get('evidence_id')?.trim() ?? '';
	$: requestedAnchorId = $page.url.searchParams.get('anchor_id')?.trim() ?? '';
	$: requestedPageNumber = positivePageParam($page.url.searchParams.get('page'));
	$: requestedReturnTo = safeReturnTo($page.url.searchParams.get('return_to'));
	$: documentLoadKey = `${collectionId}:${routeDocumentId}`;
	$: requestKey = `${documentLoadKey}:${requestedResultId}:${requestedEvidenceId}:${requestedAnchorId}:${requestedPageNumber ?? ''}`;
	$: hasDocumentSource = Boolean(contentForModel);
	$: hasExtractionDetails = Boolean(
		paperAggregation ||
		comparisonSemanticsForModel?.count ||
		comparisonSemanticsForModel?.variant_dossiers.length ||
		relatedResultsForModel.length
	);
	$: selectedGraph = graphForSelection(model, selectedItemId);
	$: selectedSourceAnchor = sourceAnchorForSelection(model, selectedSourceSpanId);
	$: paperMaterialRows = paperAggregation?.materials ?? [];
	$: activePaperMaterial =
		paperMaterialRows.find((material) => material.material_id === selectedPaperMaterialId) ??
		paperMaterialRows[0] ??
		null;
	$: paperSampleRows = paperAggregation?.sample_matrix.rows ?? [];
	$: sampleColumns = sampleMatrixColumns(paperAggregation, paperSampleRows);
	$: if (
		paperMaterialRows.length &&
		!paperMaterialRows.some((material) => material.material_id === selectedPaperMaterialId)
	) {
		selectedPaperMaterialId = paperMaterialRows[0].material_id;
	}
	$: if (!paperMaterialRows.length && selectedPaperMaterialId) {
		selectedPaperMaterialId = '';
	}
	$: if (selectedGraph && !selectedGraph.nodes.some((node) => node.id === selectedGraphNodeId)) {
		selectedGraphNodeId = selectedGraph.nodes.find((node) => node.position === 'center')?.id ?? '';
	}
	$: if (browser && collectionId && routeDocumentId && documentLoadKey !== loadedKey) {
		loadedKey = documentLoadKey;
		appliedRequestKey = '';
		void loadWorkbench();
	}
	$: if (model && documentLoadKey === loadedKey && requestKey !== appliedRequestKey) {
		appliedRequestKey = requestKey;
		applyRequestedSelection();
	}

	function backHref() {
		return requestedReturnTo || `/collections/${collectionId}/documents`;
	}

	async function loadWorkbench() {
		const generation = ++loadGeneration;
		const currentCollectionId = collectionId;
		const currentDocumentId = routeDocumentId;
		const currentRequestedEvidenceId = requestedEvidenceId;

		loading = true;
		model = null;
		contentForModel = null;
		comparisonSemanticsForModel = null;
		relatedResultsForModel = [];
		evidenceTracebacksById = new Map();
		loadingTracebackIds = new Set();
		paperAggregation = null;
		paperResearchError = '';
		selectedPaperMaterialId = '';
		selectedMatrixValue = null;
		extractionDetailsOpen = false;

		const researchPromise = loadPaperResearchView(currentCollectionId, currentDocumentId);
		const [contentResult, resultsResult, semanticsResult] = await Promise.allSettled([
			fetchDocumentContent(currentCollectionId, currentDocumentId),
			fetchCollectionResults(currentCollectionId, {
				source_document_id: currentDocumentId,
				limit: 20
			}),
			fetchDocumentComparisonSemantics(currentCollectionId, currentDocumentId, {
				includeGroupedProjections: true
			})
		]);
		await researchPromise;
		if (generation !== loadGeneration) return;

		contentForModel = contentResult.status === 'fulfilled' ? contentResult.value : null;
		relatedResultsForModel = resultsResult.status === 'fulfilled' ? resultsResult.value.items : [];
		comparisonSemanticsForModel =
			semanticsResult.status === 'fulfilled' ? semanticsResult.value : null;

		let requestedTraceback: EvidenceTracebackResponse | null = null;
		if (currentRequestedEvidenceId) {
			try {
				requestedTraceback = await fetchEvidenceTraceback(
					currentCollectionId,
					currentRequestedEvidenceId
				);
			} catch {
				requestedTraceback = null;
			}
		}
		if (generation !== loadGeneration) return;
		if (requestedTraceback) {
			evidenceTracebacksById = new Map([[currentRequestedEvidenceId, requestedTraceback]]);
		}

		rebuildWorkbenchModel();
		applyRequestedSelection();
		appliedRequestKey = requestKey;
		loading = false;
	}

	function rebuildWorkbenchModel() {
		model = buildDocumentWorkbenchModel({
			collectionId,
			documentId: routeDocumentId,
			content: contentForModel,
			comparisonSemantics: comparisonSemanticsForModel,
			relatedResults: relatedResultsForModel,
			evidenceTracebacks: Array.from(evidenceTracebacksById.values())
		});
	}

	function selectRequestedAnchor(nextModel: DocumentWorkbenchModel) {
		if (!requestedAnchorId) return false;
		const sourceSpanId = `source-anchor-${requestedAnchorId}`;
		if (!nextModel.source_anchors_by_span_id[sourceSpanId]) return false;
		selectedSourceSpanId = sourceSpanId;
		sourceJumpToken += 1;
		return true;
	}

	function selectRequestedPage(nextModel: DocumentWorkbenchModel) {
		if (!requestedPageNumber) return false;
		const sourceSpan = nextModel.source_spans.find((span) => span.page === requestedPageNumber);
		if (!sourceSpan) return false;
		selectedSourceSpanId = sourceSpan.id;
		sourceJumpToken += 1;
		return true;
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

	function sourceAnchorForSelection(
		currentModel: DocumentWorkbenchModel | null,
		sourceSpanId: string
	): SourceAnchor | null {
		if (!currentModel || !sourceSpanId) return null;
		return currentModel.source_anchors_by_span_id[sourceSpanId] ?? null;
	}

	function applyRequestedSelection() {
		if (!model) return;
		const requestedItemId =
			model.selectable_items.find((item) => item.id === requestedResultId)?.id ||
			model.selectable_items.find((item) => item.id === requestedEvidenceId)?.id ||
			model.default_item_id;
		selectItem(requestedItemId);
		if (!selectRequestedAnchor(model)) selectRequestedPage(model);
	}

	function selectItem(itemId: string, tab?: WorkbenchTab, options: SelectItemOptions = {}) {
		if (!model || !itemId) return;
		const item = model.selectable_items.find((candidate) => candidate.id === itemId);
		if (!item) return;
		selectedItemId = item.id;
		activeTab = tab ?? item.tab;
		selectedSourceSpanId = item.source_span_id;
		sourceJumpToken += 1;
		const graph = graphForSelection(model, item.id);
		const preservedNodeId = options.preserveGraphNodeId;
		selectedGraphNodeId =
			preservedNodeId && graph?.nodes.some((node) => node.id === preservedNodeId)
				? preservedNodeId
				: (graph?.nodes.find((node) => node.position === 'center')?.id ?? '');
		if (!options.skipTracebackFetch) void ensureTracebackForItem(item, item.tab);
	}

	function evidenceIdForItem(item: WorkbenchSelectableItem) {
		if (!model) return '';
		if (item.kind === 'result') {
			return model.result_rows.find((row) => row.id === item.id)?.evidence_id ?? '';
		}
		if (item.kind === 'evidence') {
			const card = model.evidence_cards.find((candidate) => candidate.id === item.id);
			return model.result_rows.find((row) => row.id === card?.result_id)?.evidence_id ?? '';
		}
		return '';
	}

	async function ensureTracebackForItem(item: WorkbenchSelectableItem, tab: WorkbenchTab) {
		const evidenceId = evidenceIdForItem(item);
		if (
			!evidenceId ||
			evidenceTracebacksById.has(evidenceId) ||
			loadingTracebackIds.has(evidenceId)
		) {
			return;
		}

		const generation = loadGeneration;
		const graphNodeId = selectedGraphNodeId;
		loadingTracebackIds = new Set(loadingTracebackIds).add(evidenceId);
		let traceback: EvidenceTracebackResponse | null = null;
		try {
			traceback = await fetchEvidenceTraceback(collectionId, evidenceId);
		} catch {
			traceback = null;
		}
		loadingTracebackIds = new Set(
			Array.from(loadingTracebackIds).filter((candidate) => candidate !== evidenceId)
		);
		if (!traceback || generation !== loadGeneration) return;

		evidenceTracebacksById = new Map(evidenceTracebacksById).set(evidenceId, traceback);
		rebuildWorkbenchModel();
		selectItem(item.id, tab, {
			preserveGraphNodeId: graphNodeId,
			skipTracebackFetch: true
		});
		if (model && requestedEvidenceId === evidenceId && !selectRequestedAnchor(model)) {
			selectRequestedPage(model);
		}
	}

	function jumpToSource(sourceSpanId: string) {
		const preservedNodeId = selectedGraphNodeId;
		const linkedItem =
			model?.selectable_items.find(
				(item) => item.source_span_id === sourceSpanId && item.tab === activeTab
			) ?? model?.selectable_items.find((item) => item.source_span_id === sourceSpanId);
		if (linkedItem) {
			selectItem(linkedItem.id, linkedItem.tab, { preserveGraphNodeId: preservedNodeId });
			return;
		}
		selectedSourceSpanId = sourceSpanId;
		sourceJumpToken += 1;
	}

	function selectSourceSpan(sourceSpanId: string) {
		selectedSourceSpanId = sourceSpanId;
		const linkedItem = model?.selectable_items.find((item) => item.source_span_id === sourceSpanId);
		if (linkedItem) {
			selectItem(linkedItem.id);
		}
	}

	function handleGraphItemSelect(itemId: string) {
		selectItem(itemId, undefined, { preserveGraphNodeId: selectedGraphNodeId });
	}

	function openTab(tab: WorkbenchTab) {
		if (!hasExtractionDetails) return;
		extractionDetailsOpen = true;
		activeTab = tab;
		const item = model?.selectable_items.find((candidate) => candidate.tab === tab);
		if (item) selectItem(item.id, tab);
	}

	function toggleGraphPanel() {
		if (!hasExtractionDetails) return;
		extractionDetailsOpen = true;
		graphCollapsed = !graphCollapsed;
	}

	function setActiveTab(tab: WorkbenchTab) {
		activeTab = tab;
	}

	function toggleExtractionDetails() {
		if (!hasExtractionDetails) return;
		extractionDetailsOpen = !extractionDetailsOpen;
	}

	async function loadPaperResearchView(
		currentCollectionId = collectionId,
		currentDocumentId = routeDocumentId
	) {
		try {
			paperAggregation = await fetchDocumentResearchView(currentCollectionId, currentDocumentId);
		} catch (err) {
			paperAggregation = null;
			paperResearchError = errorMessage(err);
		}
	}

	function sampleMatrixRows(): SampleMatrixRow[] {
		return paperSampleRows;
	}

	function selectPaperMaterial(materialId: string) {
		selectedPaperMaterialId = materialId;
	}

	function sampleMatrixColumns(
		aggregation: PaperAggregation | null = paperAggregation,
		rows: SampleMatrixRow[] = paperSampleRows
	): SampleMatrixColumn[] {
		if (aggregation?.sample_matrix.columns.length) {
			return aggregation.sample_matrix.columns;
		}

		const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row.values))));
		return keys.map((key) => ({
			column_id: key,
			key,
			label: key,
			kind: 'value',
			unit: null
		}));
	}

	function conditionSeries(): ConditionSeries[] {
		return paperAggregation?.condition_series ?? [];
	}

	function openMatrixEvidence(value: EvidenceBackedValue) {
		selectedMatrixValue = value;
	}

	function closeMatrixEvidence() {
		selectedMatrixValue = null;
	}

	function matrixCellStatus(value: EvidenceBackedValue) {
		if (value.status === 'observed' || value.status === 'normalized') return 'observed';
		if (value.status === 'conflicted') return 'conflicted';
		if (value.status === 'inferred') return 'inferred';
		return 'missing';
	}

	function positivePageParam(rawValue: string | null) {
		const value = Number(rawValue ?? NaN);
		if (!Number.isInteger(value) || value < 1) return null;
		return value;
	}

	function safeReturnTo(rawValue: string | null) {
		const value = rawValue?.trim() ?? '';
		if (!value || !value.startsWith('/') || value.startsWith('//')) return '';
		return value;
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
			<button type="button" disabled={!hasExtractionDetails} on:click={() => openTab('overview')}>
				{$t('workbench.actionOverview')}
			</button>
			<button type="button" disabled={!hasExtractionDetails} on:click={() => openTab('evidence')}>
				{$t('workbench.actionEvidence')}
			</button>
			<button
				type="button"
				disabled={!hasExtractionDetails}
				title={hasExtractionDetails
					? $t('workbench.extractionDetailsReady')
					: $t('workbench.extractionDetailsUnavailable')}
				aria-pressed={extractionDetailsOpen}
				on:click={toggleExtractionDetails}
			>
				{extractionDetailsOpen
					? $t('workbench.hideExtractionDetails')
					: $t('workbench.showExtractionDetails')}
			</button>
			<button type="button" disabled={!hasExtractionDetails} on:click={toggleGraphPanel}>
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
	{:else if model && hasDocumentSource}
		<main
			class:workbench-main--details-open={extractionDetailsOpen && hasExtractionDetails}
			class:workbench-main--reader-only={!extractionDetailsOpen || !hasExtractionDetails}
			class="workbench-main"
		>
			<section class="reader-column">
				<PaperReader
					title={model.title}
					metadata={model.metadata}
					pages={model.pages}
					sourceFileUrl={model.sourceFileUrl}
					sourceFilename={model.source_filename}
					activeSourceSpanId={selectedSourceSpanId}
					activeSourceAnchor={selectedSourceAnchor}
					{sourceJumpToken}
					onSelectSourceSpan={selectSourceSpan}
				/>
			</section>

			{#if extractionDetailsOpen && hasExtractionDetails}
				<section class="extraction-column">
					<StructuredExtractionPanel
						{model}
						{activeTab}
						{selectedItemId}
						onSelectItem={selectItem}
						onJumpToSource={jumpToSource}
						onOpenTab={setActiveTab}
					/>

					{#if paperAggregation}
						<section class="paper-research-panel" aria-label={$t('research.paper.title')}>
							<div class="paper-research-panel__header">
								<div>
									<h2>{$t('research.paper.title')}</h2>
									<p>{paperAggregation.paper_title}</p>
								</div>
								<span class={`research-state research-state--${paperAggregation.state}`}>
									{$t(`research.state.${paperAggregation.state}`)}
								</span>
							</div>

							<div class="paper-research-summary">
								<div>
									<span>{$t('research.overview.materials')}</span>
									<strong
										>{paperAggregation.overview.material_systems.join(', ') ||
											$t('research.emptyValue')}</strong
									>
								</div>
								<div>
									<span>{$t('research.overview.samples')}</span>
									<strong>{paperAggregation.overview.sample_variant_count}</strong>
								</div>
								<div>
									<span>{$t('research.overview.variables')}</span>
									<strong
										>{paperAggregation.overview.main_process_variables.join(', ') ||
											$t('research.emptyValue')}</strong
									>
								</div>
								<div>
									<span>{$t('research.overview.properties')}</span>
									<strong
										>{paperAggregation.overview.measured_properties.join(', ') ||
											$t('research.emptyValue')}</strong
									>
								</div>
							</div>

							{#if paperMaterialRows.length}
								<section class="paper-research-section">
									<h3>{$t('research.paperMaterials.title')}</h3>
									<div class="paper-material-tabs" aria-label={$t('research.paperMaterials.title')}>
										{#each paperMaterialRows as material (material.material_id)}
											<button
												type="button"
												class:active={activePaperMaterial?.material_id === material.material_id}
												on:click={() => selectPaperMaterial(material.material_id)}
											>
												{material.canonical_name}
											</button>
										{/each}
									</div>
									{#if activePaperMaterial}
										<div class="paper-material-card">
											<div>
												<span>{$t('research.materials.aliases')}</span>
												<strong
													>{activePaperMaterial.aliases.join(', ') ||
														$t('research.emptyValue')}</strong
												>
											</div>
											<div>
												<span>{$t('research.overview.samples')}</span>
												<strong>{activePaperMaterial.sample_count}</strong>
											</div>
											<div>
												<span>{$t('research.overview.processes')}</span>
												<strong
													>{activePaperMaterial.process_families.join(', ') ||
														$t('research.emptyValue')}</strong
												>
											</div>
											<div>
												<span>{$t('research.overview.properties')}</span>
												<strong
													>{activePaperMaterial.measured_properties.join(', ') ||
														$t('research.emptyValue')}</strong
												>
											</div>
											<div>
												<span>{$t('research.materials.comparisons')}</span>
												<strong>{activePaperMaterial.comparison_count}</strong>
											</div>
										</div>
										{#if activePaperMaterial.warnings.length}
											<div class="paper-material-warning" role="status">
												<strong>{$t('research.warnings')}</strong>
												<span
													>{activePaperMaterial.warnings
														.map((warning) => warning.message)
														.join(' | ')}</span
												>
											</div>
										{/if}
									{/if}
								</section>
							{/if}

							{#if sampleMatrixRows().length}
								<section class="paper-research-section">
									<h3>{$t('research.sampleMatrix.title')}</h3>
									<div class="paper-matrix-wrapper">
										<table class="paper-matrix-table">
											<thead>
												<tr>
													<th>{$t('research.sampleMatrix.sample')}</th>
													<th>{$t('research.comparison.material')}</th>
													<th>{$t('research.comparison.process')}</th>
													{#each sampleColumns as column (column.column_id)}
														<th>{column.label}</th>
													{/each}
												</tr>
											</thead>
											<tbody>
												{#each sampleMatrixRows() as row (row.row_id)}
													<tr>
														<td>{row.sample_label}</td>
														<td>{row.material}</td>
														<td>
															{Object.entries(row.process_context)
																.map(([key, value]) => `${key}: ${value}`)
																.join(' | ') || '--'}
														</td>
														{#each sampleColumns as column (column.column_id)}
															{@const value = row.values[column.key]}
															<td>
																{#if value}
																	<button
																		type="button"
																		class={`paper-matrix-value paper-matrix-value--${matrixCellStatus(value)}`}
																		on:click={() => openMatrixEvidence(value)}
																	>
																		{formatEvidenceBackedValue(value)}
																	</button>
																{:else}
																	<span class="paper-matrix-missing">--</span>
																{/if}
															</td>
														{/each}
													</tr>
												{/each}
											</tbody>
										</table>
									</div>
								</section>
							{/if}

							{#if conditionSeries().length}
								<section class="paper-research-section">
									<h3>{$t('research.conditionSeries.title')}</h3>
									<div class="condition-series-list">
										{#each conditionSeries() as series (series.series_id)}
											<article class="condition-series-card">
												<strong>{series.property} / {series.condition_axis}</strong>
												<div>
													{#each series.points as point (point.point_id)}
														<button type="button" on:click={() => openMatrixEvidence(point.result)}>
															{point.condition_value ?? '--'}{point.condition_unit
																? ` ${point.condition_unit}`
																: ''}
															-&gt; {formatEvidenceBackedValue(point.result)}
														</button>
													{/each}
												</div>
											</article>
										{/each}
									</div>
								</section>
							{/if}

							{#if selectedMatrixValue}
								<section class="paper-evidence-panel" aria-label={$t('research.evidence.title')}>
									<div class="paper-evidence-panel__header">
										<h3>{$t('research.evidence.title')}</h3>
										<button type="button" on:click={closeMatrixEvidence}>
											{$t('research.evidence.close')}
										</button>
									</div>
									<p>
										<strong>{formatEvidenceBackedValue(selectedMatrixValue)}</strong>
										<span>{$t(`research.valueStatus.${selectedMatrixValue.status}`)}</span>
									</p>
									{#if selectedMatrixValue.evidence_refs.length}
										<ul>
											{#each selectedMatrixValue.evidence_refs as ref (ref.evidence_ref_id)}
												<li>{ref.evidence_ref_id} / {ref.locator ?? ref.document_id ?? '--'}</li>
											{/each}
										</ul>
									{:else}
										<p>{$t('research.evidence.missing')}</p>
									{/if}
								</section>
							{/if}
						</section>
					{/if}
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
			{:else}
				<section class="details-status-panel" role="status">
					<strong>{$t('workbench.sourceReadyTitle')}</strong>
					<span
						>{hasExtractionDetails
							? $t('workbench.extractionDetailsClosed')
							: $t('workbench.extractionDetailsUnavailable')}</span
					>
				</section>
			{/if}
		</main>
	{:else if model}
		<main class="workbench-main">
			<section class="loading-panel research-unavailable-panel" role="alert">
				<h2>{$t('workbench.sourceContentUnavailableTitle')}</h2>
				<p>{paperResearchError || $t('workbench.sourceContentUnavailableBody')}</p>
				<a href={backHref()}>{$t('workbench.documents')}</a>
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

	.top-actions button:disabled {
		color: #94a3b8;
		cursor: not-allowed;
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
		column-gap: 16px;
		padding: 16px 20px 20px;
		box-sizing: border-box;
		overflow: hidden;
	}

	.workbench-main--reader-only {
		grid-template-columns: minmax(0, 1fr) minmax(280px, 340px);
	}

	.workbench-main--details-open {
		grid-template-columns: 700px 480px 420px;
	}

	.reader-column,
	.extraction-column,
	.graph-column,
	.details-status-panel {
		min-width: 0;
		height: 100%;
		overflow: hidden;
	}

	.extraction-column {
		display: grid;
		grid-template-rows: minmax(0, 1fr) auto;
		gap: 12px;
	}

	.details-status-panel {
		display: grid;
		align-content: start;
		gap: 8px;
		padding: 14px;
		border: 1px solid #dbeafe;
		border-radius: 16px;
		background: #ffffff;
		color: #334155;
		font-size: 13px;
		line-height: 19px;
	}

	.details-status-panel strong {
		color: #0f172a;
		font-size: 14px;
		line-height: 20px;
	}

	.details-status-panel span {
		color: #64748b;
	}

	.paper-research-panel {
		display: grid;
		max-height: 42vh;
		gap: 12px;
		overflow: auto;
		padding: 14px;
		border: 1px solid #dbeafe;
		border-radius: 16px;
		background: #ffffff;
		box-shadow: 0 8px 20px rgba(15, 23, 42, 0.05);
	}

	.paper-research-panel__header,
	.paper-evidence-panel__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}

	.paper-research-panel h2,
	.paper-research-panel h3 {
		margin: 0;
		color: #0f172a;
	}

	.paper-research-panel h2 {
		font-size: 16px;
		line-height: 22px;
	}

	.paper-research-panel p {
		margin: 3px 0 0;
		color: #64748b;
		font-size: 12px;
		line-height: 18px;
	}

	.paper-research-panel h3 {
		font-size: 14px;
		line-height: 20px;
	}

	.research-state {
		display: inline-flex;
		min-height: 24px;
		align-items: center;
		padding: 3px 8px;
		border-radius: 999px;
		background: #f1f5f9;
		color: #64748b;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.research-state--ready {
		background: #dcfce7;
		color: #15803d;
	}

	.research-state--partial,
	.research-state--processing {
		background: #fef3c7;
		color: #b45309;
	}

	.research-state--failed {
		background: #fee2e2;
		color: #b91c1c;
	}

	.paper-research-summary {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px;
	}

	.paper-research-summary > div {
		display: grid;
		gap: 4px;
		min-width: 0;
		padding: 10px;
		border-radius: 10px;
		background: #f8fafc;
	}

	.paper-research-summary span {
		color: #64748b;
		font-size: 11px;
		font-weight: 700;
		line-height: 16px;
	}

	.paper-research-summary strong {
		overflow-wrap: anywhere;
		color: #0f172a;
		font-size: 12px;
		line-height: 18px;
	}

	.paper-research-section {
		display: grid;
		gap: 8px;
	}

	.paper-material-tabs {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.paper-material-tabs button {
		min-height: 28px;
		padding: 4px 8px;
		border: 1px solid #dbeafe;
		border-radius: 8px;
		background: #ffffff;
		color: #1d4ed8;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
		cursor: pointer;
	}

	.paper-material-tabs button.active {
		background: #eff6ff;
	}

	.paper-material-card {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px;
		padding: 10px;
		border: 1px solid #e2e8f0;
		border-radius: 12px;
		background: #f8fafc;
	}

	.paper-material-card div {
		display: grid;
		gap: 4px;
		min-width: 0;
	}

	.paper-material-card span {
		color: #64748b;
		font-size: 11px;
		font-weight: 700;
		line-height: 16px;
	}

	.paper-material-card strong {
		overflow-wrap: anywhere;
		color: #0f172a;
		font-size: 12px;
		line-height: 18px;
	}

	.paper-material-warning {
		display: grid;
		gap: 4px;
		padding: 8px;
		border: 1px solid #fde68a;
		border-radius: 10px;
		background: #fef3c7;
		color: #b45309;
		font-size: 12px;
		line-height: 18px;
	}

	.paper-matrix-wrapper {
		overflow-x: auto;
		border: 1px solid #e2e8f0;
		border-radius: 12px;
	}

	.paper-matrix-table {
		width: 100%;
		min-width: 640px;
		border-collapse: collapse;
		font-size: 12px;
	}

	.paper-matrix-table th,
	.paper-matrix-table td {
		padding: 8px 10px;
		border-bottom: 1px solid #e2e8f0;
		text-align: left;
		vertical-align: top;
	}

	.paper-matrix-table th {
		color: #64748b;
		font-weight: 700;
		background: #f8fafc;
	}

	.paper-matrix-value {
		display: inline-flex;
		min-height: 28px;
		align-items: center;
		padding: 3px 8px;
		border: 1px solid #dbeafe;
		border-radius: 8px;
		background: #eff6ff;
		color: #1d4ed8;
		font-size: 12px;
		font-weight: 700;
		cursor: pointer;
	}

	.paper-matrix-value--missing,
	.paper-matrix-missing {
		color: #94a3b8;
		background: #f8fafc;
	}

	.paper-matrix-value--conflicted {
		border-color: #fecaca;
		background: #fee2e2;
		color: #b91c1c;
	}

	.paper-matrix-value--inferred {
		border-color: #fde68a;
		background: #fef3c7;
		color: #b45309;
	}

	.condition-series-list {
		display: grid;
		gap: 8px;
	}

	.condition-series-card {
		display: grid;
		gap: 8px;
		padding: 10px;
		border: 1px solid #e2e8f0;
		border-radius: 12px;
		background: #ffffff;
	}

	.condition-series-card strong {
		color: #0f172a;
		font-size: 12px;
		line-height: 18px;
	}

	.condition-series-card div {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.condition-series-card button,
	.paper-evidence-panel__header button {
		border: 0;
		border-radius: 8px;
		background: #eff6ff;
		color: #1d4ed8;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
		cursor: pointer;
	}

	.condition-series-card button {
		padding: 5px 8px;
	}

	.paper-evidence-panel {
		display: grid;
		gap: 8px;
		padding: 10px;
		border-radius: 12px;
		background: #f8fafc;
	}

	.paper-evidence-panel p {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin: 0;
		color: #334155;
	}

	.paper-evidence-panel ul {
		display: grid;
		gap: 4px;
		margin: 0;
		padding-left: 18px;
		color: #334155;
		font-size: 12px;
		line-height: 18px;
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
		.workbench-main--details-open {
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

		.workbench-main--details-open {
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

		.workbench-main--details-open {
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
			order: 1;
			height: 760px;
		}

		.extraction-column {
			order: 2;
			height: 720px;
		}

		.details-status-panel {
			order: 2;
			min-height: 120px;
		}

		.graph-column {
			display: none;
		}
	}
</style>
