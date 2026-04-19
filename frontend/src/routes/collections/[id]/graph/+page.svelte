<script lang="ts">
	import { onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import Graph from 'graphology';
	import forceAtlas2 from 'graphology-layout-forceatlas2';
	import Sigma from 'sigma';
	import {
		errorMessage,
		getApiErrorCode,
		isHttpStatusError,
		throwApiError
	} from '../../../_shared/api';
	import {
		buildCollectionGraphmlUrl,
		fetchCollectionGraph,
		fetchCollectionGraphNeighbors,
		parseGraphNodeId,
		type GraphEdge,
		type GraphNode,
		type GraphResponse
	} from '../../../_shared/graph';
	import { t } from '../../../_shared/i18n';
	import { fetchComparisonRow, type ComparisonRow } from '../../../_shared/comparisons';
	import { fetchDocumentProfile, type DocumentProfile } from '../../../_shared/documents';
	import { fetchEvidenceCard, type EvidenceCard } from '../../../_shared/evidence';
	import { buildDocumentViewerHref } from '../../../_shared/traceback';
	import {
		fetchWorkspaceOverview,
		getWorkspaceSurfaceState,
		type WorkspaceOverview
	} from '../../../_shared/workspace';

	const palette = ['#2b6ff7', '#3cc9f5', '#31d0aa', '#f2b646', '#f55f8d', '#8c7bff'];

	type NodeKind = 'document' | 'evidence' | 'comparison';
	type SelectedNode = GraphNode & { kind: NodeKind | null; resourceId: string | null };
	type NodeDetail =
		| { kind: 'document'; data: DocumentProfile }
		| { kind: 'evidence'; data: EvidenceCard }
		| { kind: 'comparison'; data: ComparisonRow };
	type EdgeDetail = GraphEdge & { sourceLabel: string; targetLabel: string };

	let collectionId = '';

	$: collectionId = $page.params.id ?? '';

	let maxNodes = 200;
	let minWeight = 0;
	let previewQuery = '';
	let loading = false;
	let error = '';
	let status = '';
	let detailLoading = false;
	let detailError = '';
	let expandingNeighborhood = false;
	let workspace: WorkspaceOverview | null = null;
	let notFound = false;
	let visibleNodes = 0;
	let visibleEdges = 0;
	let graphContainer: HTMLDivElement | null = null;
	let renderer: Sigma | null = null;
	let graph: Graph | null = null;
	let graphData: GraphResponse | null = null;
	let selectedNode: SelectedNode | null = null;
	let selectedNodeDetail: NodeDetail | null = null;
	let selectedEdge: EdgeDetail | null = null;
	let loadedCollectionId = '';
	let detailRequestId = 0;
	$: surfaceState = getWorkspaceSurfaceState(workspace, 'graph');
	$: showFallbackState =
		Boolean(workspace) && !loading && !visibleNodes && (surfaceState !== 'ready' || notFound);

	function disposeRenderer() {
		if (renderer) {
			renderer.kill();
			renderer = null;
		}
	}

	function nodeColor(type?: string | null) {
		if (!type) return palette[0];
		const sum = type.split('').reduce((acc, item) => acc + item.charCodeAt(0), 0);
		return palette[sum % palette.length];
	}

	function getNodeLabel(nodeId: string) {
		if (!graph) return nodeId;
		const attrs = graph.getNodeAttributes(nodeId) as Record<string, unknown>;
		return String(attrs.label ?? nodeId);
	}

	function stableHash(value: string) {
		let hash = 0;
		for (const item of value) {
			hash = (hash * 31 + item.charCodeAt(0)) | 0;
		}
		return Math.abs(hash);
	}

	function fallbackPosition(nodeId: string, index: number, total: number) {
		const hash = stableHash(nodeId);
		const angle = (2 * Math.PI * index) / Math.max(total, 1);
		const radius = 1 + (hash % 11) / 20;
		const xJitter = ((hash >> 3) % 100) / 800;
		const yJitter = ((hash >> 9) % 100) / 800;
		return {
			x: Math.cos(angle) * radius + xJitter,
			y: Math.sin(angle) * radius + yJitter
		};
	}

	function currentPositions() {
		const positions = new Map<string, { x: number; y: number }>();
		if (!graph) return positions;

		graph.forEachNode((node, attrs) => {
			if (typeof attrs.x === 'number' && typeof attrs.y === 'number') {
				positions.set(node, { x: attrs.x, y: attrs.y });
			}
		});
		return positions;
	}

	function clearSelection() {
		detailRequestId += 1;
		selectedNode = null;
		selectedNodeDetail = null;
		selectedEdge = null;
		detailLoading = false;
		detailError = '';
	}

	function updateVisibility() {
		if (!graph) return;

		const query = previewQuery.trim().toLowerCase();

		graph.forEachNode((node, attrs) => {
			const label = String(attrs.label ?? '').toLowerCase();
			const matches = !query || label.includes(query) || String(node).toLowerCase().includes(query);
			graph?.setNodeAttribute(node, 'hidden', !matches);
		});

		graph.forEachEdge((edge, _attrs, source, target) => {
			const hidden =
				graph?.getNodeAttribute(source, 'hidden') || graph?.getNodeAttribute(target, 'hidden');
			graph?.setEdgeAttribute(edge, 'hidden', Boolean(hidden));
		});

		visibleNodes = graph.filterNodes((node) => !graph?.getNodeAttribute(node, 'hidden')).length;
		visibleEdges = graph.filterEdges((edge) => !graph?.getEdgeAttribute(edge, 'hidden')).length;
		renderer?.refresh();
	}

	async function loadNodeDetail(node: SelectedNode) {
		const requestId = ++detailRequestId;
		detailLoading = true;
		detailError = '';
		selectedNodeDetail = null;

		try {
			if (!node.resourceId || !node.kind) {
				throw new Error('Unsupported graph node type.');
			}

			if (node.kind === 'document') {
				selectedNodeDetail = {
					kind: 'document',
					data: await fetchDocumentProfile(collectionId, node.resourceId)
				};
			} else if (node.kind === 'evidence') {
				selectedNodeDetail = {
					kind: 'evidence',
					data: await fetchEvidenceCard(collectionId, node.resourceId)
				};
			} else {
				selectedNodeDetail = {
					kind: 'comparison',
					data: await fetchComparisonRow(collectionId, node.resourceId)
				};
			}
		} catch (err) {
			if (requestId !== detailRequestId) return;
			detailError = errorMessage(err);
			selectedNodeDetail = null;
		} finally {
			if (requestId === detailRequestId) {
				detailLoading = false;
			}
		}
	}

	async function selectNode(nodeId: string) {
		if (!graph) return;
		const attrs = graph.getNodeAttributes(nodeId) as Record<string, unknown>;
		const parsed = parseGraphNodeId(nodeId);
		selectedEdge = null;
		selectedNode = {
			id: nodeId,
			label: String(attrs.label ?? nodeId),
			type: typeof attrs.entityType === 'string' ? attrs.entityType : null,
			degree: typeof attrs.degree === 'number' ? attrs.degree : null,
			kind: parsed.kind === 'unknown' ? null : parsed.kind,
			resourceId: parsed.resourceId || null
		};
		await loadNodeDetail(selectedNode);
	}

	function selectEdge(edgeId: string) {
		if (!graph) return;
		const attrs = graph.getEdgeAttributes(edgeId) as Record<string, unknown>;
		const source = graph.source(edgeId) as string;
		const target = graph.target(edgeId) as string;
		detailRequestId += 1;
		selectedNode = null;
		selectedNodeDetail = null;
		detailLoading = false;
		detailError = '';
		selectedEdge = {
			id: edgeId,
			source,
			target,
			sourceLabel: getNodeLabel(source),
			targetLabel: getNodeLabel(target),
			weight: typeof attrs.weight === 'number' ? attrs.weight : null,
			edge_description: typeof attrs.edgeDescription === 'string' ? attrs.edgeDescription : null
		};
	}

	function attachRendererEvents() {
		if (!renderer) return;
		renderer.on('clickNode', (payload) => {
			void selectNode(payload.node);
		});
		renderer.on('clickEdge', (payload) => selectEdge(payload.edge));
		renderer.on('clickStage', () => clearSelection());
	}

	function renderGraph(
		nodes: GraphNode[],
		edges: GraphEdge[],
		focusNodeId: string | null = null
	) {
		const previousPositions = currentPositions();
		const needsLayout = nodes.some((node) => !previousPositions.has(node.id));
		disposeRenderer();
		clearSelection();
		graph = new Graph();

		for (const [index, node] of nodes.entries()) {
			const position = previousPositions.get(node.id) ?? fallbackPosition(node.id, index, nodes.length);
			graph.addNode(node.id, {
				label: node.label,
				type: 'circle',
				entityType: node.type,
				degree: node.degree ?? 0,
				x: position.x,
				y: position.y,
				size: Math.max(4, Math.min(18, (node.degree ?? 1) + 4)),
				color: nodeColor(node.type)
			});
		}

		for (const edge of edges) {
			if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
			const edgeId = edge.id || `${edge.source}-${edge.target}`;
			if (graph.hasEdge(edgeId)) continue;
			graph.addEdgeWithKey(edgeId, edge.source, edge.target, {
				weight: edge.weight ?? 1,
				edgeDescription: edge.edge_description,
				size: Math.max(1, Math.min(8, edge.weight ?? 1)),
				color: 'rgba(15, 27, 45, 0.25)'
			});
		}

		if (graph.order > 1 && needsLayout) {
			forceAtlas2.assign(graph, 80);
		}

		if (graphContainer) {
			renderer = new Sigma(graph, graphContainer, {
				renderLabels: true,
				labelSize: 12,
				defaultEdgeType: 'line'
			});
			attachRendererEvents();
		}

		updateVisibility();
		if (focusNodeId && graph.hasNode(focusNodeId)) {
			void selectNode(focusNodeId);
		}
	}

	async function loadGraph() {
		loading = true;
		error = '';
		status = '';
		notFound = false;

		const [graphResult, workspaceResult] = await Promise.allSettled([
			fetchCollectionGraph(collectionId, {
				maxNodes,
				minWeight
			}),
			fetchWorkspaceOverview(collectionId)
		]);

		workspace = workspaceResult.status === 'fulfilled' ? workspaceResult.value : null;

		try {
			if (graphResult.status !== 'fulfilled') {
				throw graphResult.reason;
			}

			const response = graphResult.value;
			graphData = response;
			renderGraph(response.nodes, response.edges);
			status = response.truncated ? $t('graph.previewLoadedTruncated') : $t('graph.previewLoaded');
		} catch (err) {
			const errorCode = getApiErrorCode(err);
			error = errorMessage(err);
			notFound = errorCode ? errorCode === 'collection_not_found' : isHttpStatusError(err, 404);
			graphData = null;
			disposeRenderer();
			graph = null;
			clearSelection();
			visibleNodes = 0;
			visibleEdges = 0;
		} finally {
			loading = false;
		}
	}

	async function downloadGraphml() {
		try {
			status = $t('graph.downloading');
			const response = await fetch(
				buildCollectionGraphmlUrl(collectionId, {
					maxNodes,
					minWeight
				})
			);
			if (!response.ok) {
				await throwApiError(response);
			}
			const blob = await response.blob();
			const disposition = response.headers.get('content-disposition') ?? '';
			const matched = disposition.match(/filename="(.+?)"/i);
			const fileName = matched?.[1] ?? `graph-${collectionId}.graphml`;
			const url = URL.createObjectURL(blob);
			const anchor = document.createElement('a');
			anchor.href = url;
			anchor.download = fileName;
			anchor.click();
			URL.revokeObjectURL(url);
			status = $t('graph.downloaded', { filename: fileName });
		} catch (err) {
			error = errorMessage(err);
		}
	}

	function exportImage() {
		const canvas = graphContainer?.querySelector('canvas');
		if (!(canvas instanceof HTMLCanvasElement)) return;

		const url = canvas.toDataURL('image/png');
		const anchor = document.createElement('a');
		anchor.href = url;
		anchor.download = `graph-${collectionId}.png`;
		anchor.click();
		status = $t('graph.imageExported');
	}

	function resetFilters() {
		previewQuery = '';
		updateVisibility();
	}

	function stateCardTitle() {
		return $t(`overview.surfaceStateCards.${surfaceState}.title`);
	}

	function stateCardBody() {
		return $t(`overview.surfaceStateCards.${surfaceState}.body`);
	}

	function mergeGraphPayload(
		current: GraphResponse | null,
		next: Pick<GraphResponse, 'collection_id' | 'nodes' | 'edges' | 'truncated'>
	): GraphResponse {
		const nodes = new Map<string, GraphNode>();
		const edges = new Map<string, GraphEdge>();

		for (const node of current?.nodes ?? []) {
			nodes.set(node.id, node);
		}
		for (const node of next.nodes) {
			nodes.set(node.id, node);
		}

		for (const edge of current?.edges ?? []) {
			edges.set(edge.id, edge);
		}
		for (const edge of next.edges) {
			edges.set(edge.id, edge);
		}

		return {
			collection_id: next.collection_id,
			nodes: Array.from(nodes.values()),
			edges: Array.from(edges.values()),
			truncated: Boolean(current?.truncated || next.truncated)
		};
	}

	async function expandSelectedNeighborhood() {
		if (!selectedNode) return;

		expandingNeighborhood = true;
		detailError = '';
		try {
			const response = await fetchCollectionGraphNeighbors(collectionId, selectedNode.id);
			graphData = mergeGraphPayload(graphData, response);
			renderGraph(graphData.nodes, graphData.edges, selectedNode.id);
			status = $t('graph.neighborsExpanded');
		} catch (err) {
			detailError = errorMessage(err);
		} finally {
			expandingNeighborhood = false;
		}
	}

	function formatList(items: string[]) {
		return items.length ? items.join(', ') : '--';
	}

	function selectedNodeHref() {
		if (!selectedNode) return null;
		const returnTo = `/collections/${encodeURIComponent(collectionId)}/graph`;

		if (selectedNode.kind === 'document' && selectedNode.resourceId) {
			return buildDocumentViewerHref(collectionId, selectedNode.resourceId, { returnTo });
		}
		if (
			selectedNode.kind === 'evidence' &&
			selectedNodeDetail?.kind === 'evidence' &&
			selectedNodeDetail.data.document_id
		) {
			return buildDocumentViewerHref(collectionId, selectedNodeDetail.data.document_id, {
				evidenceId: selectedNodeDetail.data.evidence_id,
				returnTo
			});
		}
		if (selectedNode.kind === 'comparison') {
			return `/collections/${encodeURIComponent(collectionId)}/comparisons`;
		}
		return null;
	}

	function selectedNodeLinkLabel() {
		if (selectedNode?.kind === 'comparison') return $t('graph.openComparisons');
		if (selectedNode?.kind === 'evidence') return $t('graph.openEvidenceSource');
		return $t('graph.openDocument');
	}

	$: if (graph) {
		previewQuery;
		updateVisibility();
	}

	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadGraph();
	}

	onDestroy(() => {
		disposeRenderer();
		graph = null;
	});
</script>

<svelte:head>
	<title>{$t('graph.title')}</title>
</svelte:head>

<section class="card fade-up">
	<div class="graph-preview-header">
		<div>
			<h2>{$t('graph.title')}</h2>
			<p class="lead">{$t('graph.lead')}</p>
		</div>
		<div class="preview-actions">
			<button class="btn btn--ghost" type="button" on:click={() => void loadGraph()}>
				{$t('graph.previewLoad')}
			</button>
			<button class="btn btn--ghost" type="button" on:click={exportImage} disabled={!visibleNodes}>
				{$t('graph.exportImage')}
			</button>
			<button class="btn btn--primary" type="button" on:click={() => void downloadGraphml()}>
				{$t('graph.download')}
			</button>
		</div>
	</div>
</section>

{#if showFallbackState}
	<section class="card">
		<article class="result-card">
			<h3>{stateCardTitle()}</h3>
			<p class="result-text">{stateCardBody()}</p>
			<div class="table-actions">
				<a class="btn btn--ghost btn--small" href={`/collections/${collectionId}`}>
					{$t('overview.goToWorkspace')}
				</a>
			</div>
		</article>
	</section>
{:else}
	<section class="card">
		<div class="graph-preview-body">
			<div class="graph-controls">
				<div class="field">
					<label for="maxNodes">{$t('graph.maxNodesLabel')}</label>
					<input
						id="maxNodes"
						class="input"
						type="number"
						min="1"
						max="2000"
						bind:value={maxNodes}
					/>
				</div>
				<div class="field">
					<label for="minWeight">{$t('graph.minWeightLabel')}</label>
					<input
						id="minWeight"
						class="input"
						type="number"
						min="0"
						step="0.1"
						bind:value={minWeight}
					/>
				</div>
				<div class="field">
					<label for="previewQuery">{$t('graph.searchLabel')}</label>
					<input
						id="previewQuery"
						class="input"
						bind:value={previewQuery}
						placeholder={$t('graph.searchPlaceholder')}
					/>
				</div>
				<div class="table-actions">
					<button class="btn btn--ghost btn--small" type="button" on:click={resetFilters}>
						{$t('graph.resetFilters')}
					</button>
				</div>
				<div class="graph-stats">
					<span>{$t('graph.visibleNodes')}: {visibleNodes}</span>
					<span>{$t('graph.visibleEdges')}: {visibleEdges}</span>
					{#if graphData?.truncated}
						<span>{$t('graph.truncated')}</span>
					{/if}
				</div>
				{#if status}
					<div class="status" role="status">{status}</div>
				{/if}
				{#if error}
					<div class="status status--error" role="alert">{error}</div>
				{/if}
			</div>

			<div
				class="graph-canvas"
				bind:this={graphContainer}
				aria-label={$t('graph.previewCanvasLabel')}
			>
				{#if loading}
					<div class="graph-empty">{$t('graph.previewLoading')}</div>
				{:else if !visibleNodes}
					<div class="graph-empty">{$t('graph.previewEmpty')}</div>
				{/if}
			</div>
		</div>
	</section>

	<section class="card">
		<h3>{$t('graph.detailsTitle')}</h3>
		<div class="graph-details">
			{#if selectedNode}
				<div class="graph-details__header">
					<span>{$t('graph.detailsNode')}</span>
					<div class="table-actions">
						<button
							class="btn btn--ghost btn--small"
							type="button"
							on:click={() => void expandSelectedNeighborhood()}
							disabled={expandingNeighborhood}
						>
							{expandingNeighborhood ? $t('graph.neighborsExpanding') : $t('graph.neighborsExpand')}
						</button>
						{#if selectedNodeHref()}
							<a class="btn btn--ghost btn--small" href={selectedNodeHref() ?? '#'}>
								{selectedNodeLinkLabel()}
							</a>
						{/if}
						<button class="btn btn--ghost btn--small" type="button" on:click={clearSelection}>
							{$t('graph.detailsClear')}
						</button>
					</div>
				</div>
				<div class="detail-primary">
					<span class="detail-name">{selectedNode.label}</span>
					{#if selectedNode.type}
						<span class="detail-tag">{selectedNode.type}</span>
					{/if}
				</div>
				<dl class="detail-list">
					<div class="detail-row">
						<dt>{$t('graph.detailId')}</dt>
						<dd>{selectedNode.id}</dd>
					</div>
					<div class="detail-row">
						<dt>{$t('graph.detailDegree')}</dt>
						<dd>{selectedNode.degree ?? '--'}</dd>
					</div>
					{#if detailLoading}
						<div class="status" role="status">{$t('graph.detailsLoading')}</div>
					{:else if detailError}
						<div class="status status--error" role="alert">{detailError}</div>
					{:else if selectedNodeDetail?.kind === 'document'}
						<div class="detail-row">
							<dt>{$t('graph.detailSourceFile')}</dt>
							<dd>{selectedNodeDetail.data.source_filename ?? '--'}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('graph.detailDocType')}</dt>
							<dd>{selectedNodeDetail.data.doc_type}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('graph.detailProtocol')}</dt>
							<dd>{selectedNodeDetail.data.protocol_extractable}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('graph.detailConfidence')}</dt>
							<dd>{selectedNodeDetail.data.confidence ?? '--'}</dd>
						</div>
					{:else if selectedNodeDetail?.kind === 'evidence'}
						<div class="detail-row detail-row--wide">
							<dt>{$t('graph.detailClaim')}</dt>
							<dd>{selectedNodeDetail.data.claim_text || '--'}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('graph.detailClaimType')}</dt>
							<dd>{selectedNodeDetail.data.claim_type}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('graph.detailTraceability')}</dt>
							<dd>{selectedNodeDetail.data.traceability_status}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('graph.detailConfidence')}</dt>
							<dd>{selectedNodeDetail.data.confidence ?? '--'}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('graph.detailMaterialSystem')}</dt>
							<dd>{selectedNodeDetail.data.material_system || '--'}</dd>
						</div>
						<div class="detail-row detail-row--wide">
							<dt>{$t('graph.detailProcess')}</dt>
							<dd>{formatList(selectedNodeDetail.data.condition_context.process)}</dd>
						</div>
						<div class="detail-row detail-row--wide">
							<dt>{$t('graph.detailBaseline')}</dt>
							<dd>{formatList(selectedNodeDetail.data.condition_context.baseline)}</dd>
						</div>
						<div class="detail-row detail-row--wide">
							<dt>{$t('graph.detailTest')}</dt>
							<dd>{formatList(selectedNodeDetail.data.condition_context.test)}</dd>
						</div>
					{:else if selectedNodeDetail?.kind === 'comparison'}
						<div class="detail-row">
							<dt>{$t('graph.detailSourceDocument')}</dt>
							<dd>{selectedNodeDetail.data.source_document_id}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('graph.detailProperty')}</dt>
							<dd>{selectedNodeDetail.data.display.property_normalized}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('graph.detailComparability')}</dt>
							<dd>{selectedNodeDetail.data.assessment.comparability_status}</dd>
						</div>
						<div class="detail-row detail-row--wide">
							<dt>{$t('graph.detailResult')}</dt>
							<dd>{selectedNodeDetail.data.display.result_summary}</dd>
						</div>
						<div class="detail-row detail-row--wide">
							<dt>{$t('graph.detailEvidenceIds')}</dt>
							<dd>{formatList(selectedNodeDetail.data.evidence_bundle.supporting_evidence_ids)}</dd>
						</div>
					{/if}
				</dl>
			{:else if selectedEdge}
				<div class="graph-details__header">
					<span>{$t('graph.detailsEdge')}</span>
					<button class="btn btn--ghost btn--small" type="button" on:click={clearSelection}>
						{$t('graph.detailsClear')}
					</button>
				</div>
				<div class="detail-primary">
					<span class="detail-name">{selectedEdge.sourceLabel} -> {selectedEdge.targetLabel}</span>
				</div>
				<dl class="detail-list">
					<div class="detail-row">
						<dt>{$t('graph.detailId')}</dt>
						<dd>{selectedEdge.id}</dd>
					</div>
					<div class="detail-row">
						<dt>{$t('graph.detailSource')}</dt>
						<dd>{selectedEdge.source}</dd>
					</div>
					<div class="detail-row">
						<dt>{$t('graph.detailTarget')}</dt>
						<dd>{selectedEdge.target}</dd>
					</div>
					<div class="detail-row">
						<dt>{$t('graph.detailWeight')}</dt>
						<dd>{selectedEdge.weight ?? '--'}</dd>
					</div>
					<div class="detail-row detail-row--wide">
						<dt>{$t('graph.detailDescription')}</dt>
						<dd>{selectedEdge.edge_description || '--'}</dd>
					</div>
				</dl>
			{:else}
				<div class="graph-empty">{$t('graph.detailsEmpty')}</div>
			{/if}
		</div>
	</section>
{/if}
