<script lang="ts">
	import { onDestroy, tick } from 'svelte';
	import { page } from '$app/stores';
	import cytoscape, {
		type Core,
		type ElementDefinition,
		type LayoutOptions,
		type StylesheetJson
	} from 'cytoscape';
	import fcose from 'cytoscape-fcose';
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

	cytoscape.use(fcose);

	type NodeKind =
		| 'document'
		| 'evidence'
		| 'comparison'
		| 'material'
		| 'property'
		| 'test_condition'
		| 'baseline'
		| 'variant'
		| 'process';
	type Position = { x: number; y: number };
	type ViewportState = { zoom: number; pan: Position };
	type SelectedNode = GraphNode & { kind: NodeKind | 'unknown'; resourceId: string | null };
	type NodeDetail =
		| { kind: 'document'; data: DocumentProfile }
		| { kind: 'evidence'; data: EvidenceCard }
		| { kind: 'comparison'; data: ComparisonRow };
	type EdgeDetail = GraphEdge & { sourceLabel: string; targetLabel: string };

	const nodeTypeOrder: NodeKind[] = [
		'document',
		'evidence',
		'comparison',
		'material',
		'property',
		'test_condition',
		'baseline',
		'variant',
		'process'
	];
	const nodeTypeMeta: Record<NodeKind, { color: string; shape: string }> = {
		document: { color: '#2b6ff7', shape: 'round-rectangle' },
		evidence: { color: '#12a579', shape: 'ellipse' },
		comparison: { color: '#f28f3b', shape: 'diamond' },
		material: { color: '#d94f70', shape: 'hexagon' },
		property: { color: '#7a63ff', shape: 'round-hexagon' },
		test_condition: { color: '#1791c8', shape: 'vee' },
		baseline: { color: '#5b8c3b', shape: 'tag' },
		variant: { color: '#b14d83', shape: 'star' },
		process: { color: '#65748b', shape: 'concave-hexagon' }
	};
	const defaultVisibleNodeTypes: Record<NodeKind, boolean> = {
		document: true,
		evidence: true,
		comparison: true,
		material: true,
		property: true,
		test_condition: false,
		baseline: false,
		variant: false,
		process: false
	};
	const graphStylesheet = [
		{
			selector: 'node',
			style: {
				shape: 'data(shape)',
				width: 'data(size)',
				height: 'data(size)',
				'background-color': 'data(color)',
				'border-width': 1.5,
				'border-color': '#ffffff',
				label: 'data(label)',
				color: '#0f1b2d',
				'font-size': 11,
				'font-weight': 600,
				'text-wrap': 'wrap',
				'text-max-width': 120,
				'text-valign': 'bottom',
				'text-halign': 'center',
				'text-margin-y': 10,
				'text-background-color': '#ffffff',
				'text-background-opacity': 0.88,
				'text-background-shape': 'roundrectangle',
				'text-background-padding': 2,
				'overlay-opacity': 0
			}
		},
		{
			selector: 'edge',
			style: {
				width: 'data(width)',
				'curve-style': 'bezier',
				'line-color': 'rgba(15, 27, 45, 0.25)',
				'target-arrow-color': 'rgba(15, 27, 45, 0.25)',
				'target-arrow-shape': 'triangle',
				'arrow-scale': 0.9,
				label: 'data(label)',
				color: 'rgba(15, 27, 45, 0.8)',
				'font-size': 9,
				'text-rotation': 'autorotate',
				'text-background-color': '#ffffff',
				'text-background-opacity': 0.92,
				'text-background-shape': 'roundrectangle',
				'text-background-padding': 2,
				'text-margin-y': -4,
				'min-zoomed-font-size': 4,
				'overlay-opacity': 0
			}
		},
		{
			selector: '.is-hidden',
			style: {
				display: 'none'
			}
		},
		{
			selector: 'node.is-selected',
			style: {
				'border-width': 3,
				'border-color': '#0f1b2d'
			}
		},
		{
			selector: 'node.is-connected',
			style: {
				'border-width': 2,
				'border-color': '#2b6ff7'
			}
		},
		{
			selector: 'edge.is-selected',
			style: {
				'line-color': '#0f1b2d',
				'target-arrow-color': '#0f1b2d',
				width: 4
			}
		},
		{
			selector: 'edge.is-connected',
			style: {
				'line-color': 'rgba(43, 111, 247, 0.38)',
				'target-arrow-color': 'rgba(43, 111, 247, 0.38)'
			}
		}
	] as unknown as StylesheetJson;

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
	let cy: Core | null = null;
	let graphData: GraphResponse | null = null;
	let selectedNode: SelectedNode | null = null;
	let selectedNodeDetail: NodeDetail | null = null;
	let selectedEdge: EdgeDetail | null = null;
	let loadedCollectionId = '';
	let detailRequestId = 0;
	let visibleNodeTypes: Record<NodeKind, boolean> = { ...defaultVisibleNodeTypes };
	$: surfaceState = getWorkspaceSurfaceState(workspace, 'graph');
	$: showFallbackState =
		Boolean(workspace) && !loading && !visibleNodes && (surfaceState !== 'ready' || notFound);
	$: availableNodeTypes = nodeTypeOrder.filter((type) =>
		(graphData?.nodes ?? []).some((node) => node.type === type)
	);

	function disposeRenderer() {
		if (cy) {
			cy.destroy();
			cy = null;
		}
	}

	function asNodeKind(type?: string | null): NodeKind | null {
		return type && type in nodeTypeMeta ? (type as NodeKind) : null;
	}

	function nodeColor(type?: string | null) {
		const kind = asNodeKind(type);
		return kind ? nodeTypeMeta[kind].color : '#2b6ff7';
	}

	function nodeShape(type?: string | null) {
		const kind = asNodeKind(type);
		return kind ? nodeTypeMeta[kind].shape : 'ellipse';
	}

	function nodeSize(degree?: number | null) {
		return Math.max(24, Math.min(54, ((degree ?? 1) * 4) + 18));
	}

	function edgeWidth(weight?: number | null) {
		return Math.max(1.5, Math.min(6, (weight ?? 1) + 0.5));
	}

	function getNodeLabel(nodeId: string) {
		if (!cy) return nodeId;
		const node = cy.$id(nodeId);
		return node.empty() ? nodeId : String(node.data('label') ?? nodeId);
	}

	function edgeRelationLabel(description?: string | null) {
		if (description === 'document_to_evidence') {
			return $t('graph.edgeLabelDocumentEvidence');
		}
		if (description === 'evidence_to_comparison') {
			return $t('graph.edgeLabelEvidenceComparison');
		}
		if (description === 'comparison_to_material') {
			return $t('graph.edgeLabelComparisonMaterial');
		}
		if (description === 'comparison_to_property') {
			return $t('graph.edgeLabelComparisonProperty');
		}
		if (description === 'comparison_to_test_condition') {
			return $t('graph.edgeLabelComparisonTestCondition');
		}
		if (description === 'comparison_to_baseline') {
			return $t('graph.edgeLabelComparisonBaseline');
		}
		return description?.trim() || $t('graph.edgeLabelFallback');
	}

	function nodeTypeLabel(type: NodeKind) {
		if (type === 'document') return $t('graph.nodeTypeDocument');
		if (type === 'evidence') return $t('graph.nodeTypeEvidence');
		if (type === 'comparison') return $t('graph.nodeTypeComparison');
		if (type === 'material') return $t('graph.nodeTypeMaterial');
		if (type === 'property') return $t('graph.nodeTypeProperty');
		if (type === 'test_condition') return $t('graph.nodeTypeTestCondition');
		if (type === 'baseline') return $t('graph.nodeTypeBaseline');
		if (type === 'variant') return $t('graph.nodeTypeVariant');
		return $t('graph.nodeTypeProcess');
	}

	function selectedNodeTypeLabel(type?: string | null) {
		const kind = asNodeKind(type);
		return kind ? nodeTypeLabel(kind) : type?.trim() || '';
	}

	function isNodeTypeVisible(type: NodeKind) {
		return visibleNodeTypes[type];
	}

	function setNodeTypeVisibility(type: NodeKind, checked: boolean) {
		visibleNodeTypes = {
			...visibleNodeTypes,
			[type]: checked
		};
	}

	function stableHash(value: string) {
		let hash = 0;
		for (const item of value) {
			hash = (hash * 31 + item.charCodeAt(0)) | 0;
		}
		return Math.abs(hash);
	}

	function fallbackPosition(nodeId: string, index: number, total: number): Position {
		const hash = stableHash(nodeId);
		const angle = (2 * Math.PI * index) / Math.max(total, 1);
		const radius = 120 + (hash % 11) * 12;
		const xJitter = ((hash >> 3) % 100) - 50;
		const yJitter = ((hash >> 9) % 100) - 50;
		return {
			x: Math.cos(angle) * radius + xJitter,
			y: Math.sin(angle) * radius + yJitter
		};
	}

	function currentPositions() {
		const positions = new Map<string, Position>();
		if (!cy) return positions;

		cy.nodes().forEach((node) => {
			const position = node.position();
			positions.set(node.id(), { x: position.x, y: position.y });
		});
		return positions;
	}

	function currentViewport(): ViewportState | null {
		if (!cy) return null;
		const pan = cy.pan();
		return {
			zoom: cy.zoom(),
			pan: { x: pan.x, y: pan.y }
		};
	}

	function restoreViewport(viewport: ViewportState | null) {
		if (!cy || !viewport) return;
		cy.zoom(viewport.zoom);
		cy.pan(viewport.pan);
	}

	function syncSelectionStyles() {
		if (!cy) return;
		cy.batch(() => {
			cy?.elements().removeClass('is-selected');
			cy?.elements().removeClass('is-connected');

			if (selectedNode) {
				const node = cy?.$id(selectedNode.id);
				if (node && !node.empty()) {
					node.addClass('is-selected');
					node.connectedEdges().addClass('is-connected');
				}
				return;
			}

			if (selectedEdge) {
				const edge = cy?.$id(selectedEdge.id);
				if (edge && !edge.empty()) {
					edge.addClass('is-selected');
					edge.connectedNodes().addClass('is-connected');
				}
			}
		});
	}

	function clearSelection() {
		detailRequestId += 1;
		selectedNode = null;
		selectedNodeDetail = null;
		selectedEdge = null;
		detailLoading = false;
		detailError = '';
		syncSelectionStyles();
	}

	function updateVisibility() {
		if (!cy) return;

		const query = previewQuery.trim().toLowerCase();

		cy.batch(() => {
			cy?.nodes().forEach((node) => {
				const label = String(node.data('label') ?? '').toLowerCase();
				const type = asNodeKind(
					typeof node.data('entityType') === 'string' ? node.data('entityType') : null
				);
				const typeVisible = type ? visibleNodeTypes[type] : true;
				const matches = !query || label.includes(query) || node.id().toLowerCase().includes(query);
				node.toggleClass('is-hidden', !(typeVisible && matches));
			});

			cy?.edges().forEach((edge) => {
				const hidden = edge.source().hasClass('is-hidden') || edge.target().hasClass('is-hidden');
				edge.toggleClass('is-hidden', hidden);
			});
		});

		visibleNodes = cy.nodes().filter((node) => !node.hasClass('is-hidden')).length;
		visibleEdges = cy.edges().filter((edge) => !edge.hasClass('is-hidden')).length;
		syncSelectionStyles();
	}

	async function loadNodeDetail(node: SelectedNode) {
		const requestId = ++detailRequestId;
		detailLoading = node.kind === 'document' || node.kind === 'evidence' || node.kind === 'comparison';
		detailError = '';
		selectedNodeDetail = null;

		try {
			if (!node.resourceId || node.kind === 'unknown') {
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
			} else if (node.kind === 'comparison') {
				selectedNodeDetail = {
					kind: 'comparison',
					data: await fetchComparisonRow(collectionId, node.resourceId)
				};
			} else {
				selectedNodeDetail = null;
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
		if (!cy) return;
		const node = cy.$id(nodeId);
		if (node.empty()) return;
		const parsed = parseGraphNodeId(nodeId);
		selectedEdge = null;
		selectedNode = {
			id: nodeId,
			label: String(node.data('label') ?? nodeId),
			type: typeof node.data('entityType') === 'string' ? node.data('entityType') : null,
			degree: typeof node.data('degree') === 'number' ? node.data('degree') : null,
			kind: parsed.kind,
			resourceId: parsed.resourceId || null
		};
		syncSelectionStyles();
		await loadNodeDetail(selectedNode);
	}

	function selectEdge(edgeId: string) {
		if (!cy) return;
		const edge = cy.$id(edgeId);
		if (edge.empty()) return;
		detailRequestId += 1;
		selectedNode = null;
		selectedNodeDetail = null;
		detailLoading = false;
		detailError = '';
		selectedEdge = {
			id: edgeId,
			source: String(edge.data('source') ?? ''),
			target: String(edge.data('target') ?? ''),
			sourceLabel: getNodeLabel(String(edge.data('source') ?? '')),
			targetLabel: getNodeLabel(String(edge.data('target') ?? '')),
			weight: typeof edge.data('weight') === 'number' ? edge.data('weight') : null,
			edge_description:
				typeof edge.data('edgeDescription') === 'string' ? edge.data('edgeDescription') : null
		};
		syncSelectionStyles();
	}

	function attachRendererEvents() {
		if (!cy) return;
		cy.on('tap', 'node', (event) => {
			void selectNode(event.target.id());
		});
		cy.on('tap', 'edge', (event) => {
			selectEdge(event.target.id());
		});
		cy.on('tap', (event) => {
			if (event.target === cy) {
				clearSelection();
			}
		});
	}

	function buildGraphElements(
		nodes: GraphNode[],
		edges: GraphEdge[],
		previousPositions: Map<string, Position>
	): ElementDefinition[] {
		const nodeIds = new Set(nodes.map((node) => node.id));
		const elements: ElementDefinition[] = [];

		for (const [index, node] of nodes.entries()) {
			const position = previousPositions.get(node.id) ?? fallbackPosition(node.id, index, nodes.length);
			elements.push({
				group: 'nodes',
				data: {
					id: node.id,
					label: node.label,
					entityType: node.type ?? null,
					degree: node.degree ?? 0,
					color: nodeColor(node.type),
					size: nodeSize(node.degree),
					shape: nodeShape(node.type)
				},
				position
			});
		}

		for (const edge of edges) {
			if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
			const edgeId = edge.id || `${edge.source}-${edge.target}`;
			elements.push({
				group: 'edges',
				data: {
					id: edgeId,
					source: edge.source,
					target: edge.target,
					label: edgeRelationLabel(edge.edge_description),
					weight: edge.weight ?? 1,
					width: edgeWidth(edge.weight),
					edgeDescription: edge.edge_description ?? null
				}
			});
		}

		return elements;
	}

	async function runGraphLayout(previousPositions: Map<string, Position>, fit: boolean) {
		if (!cy || cy.nodes().length < 2) {
			if (fit && cy) {
				cy.fit(cy.elements(), 40);
			}
			return;
		}

		const fixedNodeConstraint = Array.from(previousPositions.entries())
			.filter(([nodeId]) => !cy?.$id(nodeId).empty())
			.map(([nodeId, position]) => ({ nodeId, position }));

		await new Promise<void>((resolve) => {
			if (!cy) {
				resolve();
				return;
			}

			const layout = cy.layout({
				name: 'fcose',
				quality: 'default',
				randomize: false,
				animate: false,
				fit,
				padding: 48,
				nodeRepulsion: 4500,
				idealEdgeLength: 120,
				edgeElasticity: 0.25,
				gravity: 0.2,
				numIter: 2500,
				fixedNodeConstraint
			} as unknown as LayoutOptions);

			layout.on('layoutstop', () => resolve());
			layout.run();
		});
	}

	async function renderGraph(
		nodes: GraphNode[],
		edges: GraphEdge[],
		focusNodeId: string | null = null
	) {
		const previousPositions = currentPositions();
		const previousViewport = currentViewport();
		const hasNewNodes = nodes.some((node) => !previousPositions.has(node.id));
		const shouldFit = !previousViewport;

		if (!graphContainer) {
			await tick();
		}
		if (!graphContainer) return;

		disposeRenderer();
		clearSelection();

		cy = cytoscape({
			container: graphContainer,
			elements: buildGraphElements(nodes, edges, previousPositions),
			style: graphStylesheet,
			layout: { name: 'preset' },
			minZoom: 0.2,
			maxZoom: 2.5,
			wheelSensitivity: 0.2,
			boxSelectionEnabled: false
		});
		attachRendererEvents();
		restoreViewport(previousViewport);

		if (hasNewNodes) {
			await runGraphLayout(previousPositions, shouldFit);
			restoreViewport(previousViewport);
		} else if (shouldFit) {
			cy.fit(cy.elements(), 40);
		}

		updateVisibility();
		if (focusNodeId && !cy.$id(focusNodeId).empty()) {
			await selectNode(focusNodeId);
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
			await renderGraph(response.nodes, response.edges);
			status = response.truncated ? $t('graph.previewLoadedTruncated') : $t('graph.previewLoaded');
		} catch (err) {
			const errorCode = getApiErrorCode(err);
			error = errorMessage(err);
			notFound = errorCode ? errorCode === 'collection_not_found' : isHttpStatusError(err, 404);
			graphData = null;
			disposeRenderer();
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
		if (!cy) return;

		const url = cy.png({ full: true, scale: 2, bg: '#ffffff' });
		const anchor = document.createElement('a');
		anchor.href = String(url);
		anchor.download = `graph-${collectionId}.png`;
		anchor.click();
		status = $t('graph.imageExported');
	}

	function resetFilters() {
		previewQuery = '';
		visibleNodeTypes = { ...defaultVisibleNodeTypes };
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
			await renderGraph(graphData.nodes, graphData.edges, selectedNode.id);
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

	function selectedNodeComparisonFilter() {
		if (!selectedNode) return null;
		const value = selectedNode.label.trim();
		if (!value) return null;

		if (selectedNode.kind === 'material') {
			return {
				key: 'material_system_normalized',
				value
			};
		}
		if (selectedNode.kind === 'property') {
			return {
				key: 'property_normalized',
				value
			};
		}
		if (selectedNode.kind === 'test_condition') {
			return {
				key: 'test_condition_normalized',
				value
			};
		}
		if (selectedNode.kind === 'baseline') {
			return {
				key: 'baseline_normalized',
				value
			};
		}
		return null;
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
		const comparisonFilter = selectedNodeComparisonFilter();
		if (comparisonFilter) {
			const params = new URLSearchParams({
				[comparisonFilter.key]: comparisonFilter.value
			});
			return `/collections/${encodeURIComponent(collectionId)}/comparisons?${params.toString()}`;
		}
		return null;
	}

	function selectedNodeLinkLabel() {
		if (
			selectedNode?.kind === 'material' ||
			selectedNode?.kind === 'property' ||
			selectedNode?.kind === 'test_condition' ||
			selectedNode?.kind === 'baseline'
		) {
			return $t('graph.openFilteredComparisons');
		}
		if (selectedNode?.kind === 'comparison') return $t('graph.openComparisons');
		if (selectedNode?.kind === 'evidence') return $t('graph.openEvidenceSource');
		return $t('graph.openDocument');
	}

	$: if (cy) {
		previewQuery;
		visibleNodeTypes;
		updateVisibility();
	}

	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		visibleNodeTypes = { ...defaultVisibleNodeTypes };
		void loadGraph();
	}

	onDestroy(() => {
		disposeRenderer();
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
				{#if availableNodeTypes.length}
					<div class="field field--wide">
						<span>{$t('graph.nodeTypesLabel')}</span>
						<div class="graph-node-types">
							{#each availableNodeTypes as type}
								<label class="graph-node-type">
									<input
										type="checkbox"
										checked={isNodeTypeVisible(type)}
										on:change={(event) =>
											setNodeTypeVisibility(
												type,
												(event.currentTarget as HTMLInputElement).checked
											)}
									/>
									<span
										class="graph-node-type__swatch"
										style={`background:${nodeColor(type)};`}
										aria-hidden="true"
									></span>
									<span>{nodeTypeLabel(type)}</span>
								</label>
							{/each}
						</div>
					</div>
				{/if}
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
					{:else if selectedNodeComparisonFilter()}
						<div class="detail-row detail-row--wide">
							<dt>{$t('graph.detailAggregate')}</dt>
							<dd>{$t('graph.detailAggregateBody')}</dd>
						</div>
						<div class="detail-row detail-row--wide">
							<dt>{$t('graph.detailAggregateValue')}</dt>
							<dd>{selectedNode.label}</dd>
						</div>
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

<style>
	.field--wide {
		grid-column: 1 / -1;
	}

	.graph-node-types {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		margin-top: 0.5rem;
	}

	.graph-node-type {
		display: inline-flex;
		align-items: center;
		gap: 0.45rem;
		padding: 0.45rem 0.7rem;
		border: 1px solid rgba(15, 27, 45, 0.12);
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.9);
		font-size: 0.92rem;
	}

	.graph-node-type__swatch {
		width: 0.7rem;
		height: 0.7rem;
		border-radius: 999px;
		flex: 0 0 auto;
	}
</style>
