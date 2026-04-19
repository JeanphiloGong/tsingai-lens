<script lang="ts">
	import { onDestroy, tick } from 'svelte';
	import { page } from '$app/stores';
	import cytoscape, {
		type CollectionReturnValue,
		type Core,
		type EdgeSingular,
		type ElementDefinition,
		type LayoutOptions,
		type NodeSingular,
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
	type HoverPreview = {
		nodeId: string;
		label: string;
		typeLabel: string;
		degree: number | null;
		left: number;
		top: number;
	};

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
	const detailNodeKinds = new Set<NodeKind>(['document', 'evidence', 'comparison']);
	const graphViewportPadding = 72;
	const graphAnimationDuration = 220;
	const graphStylesheet = [
		{
			selector: 'node',
			style: {
				shape: 'data(shape)',
				width: 'data(width)',
				height: 'data(height)',
				'background-color': 'data(color)',
				'background-opacity': 0.93,
				'border-width': 1.5,
				'border-color': 'rgba(255, 255, 255, 0.94)',
				label: 'data(label)',
				color: '#0f1b2d',
				'font-size': 'data(fontSize)',
				'font-weight': 600,
				'text-wrap': 'wrap',
				'text-max-width': 'data(textMaxWidth)',
				'text-valign': 'center',
				'text-halign': 'center',
				'text-justification': 'center',
				'text-margin-y': 0,
				'overlay-opacity': 0
			}
		},
		{
			selector: 'node.is-card-node',
			style: {
				shape: 'round-rectangle',
				'border-width': 2,
				'font-weight': 700
			}
		},
		{
			selector: 'node.is-detail-node',
			style: {
				'background-opacity': 0.97
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
				'border-color': '#0f1b2d',
				'shadow-blur': 20,
				'shadow-color': 'rgba(15, 27, 45, 0.18)',
				'shadow-opacity': 1,
				'shadow-offset-x': 0,
				'shadow-offset-y': 8
			}
		},
		{
			selector: 'node.is-connected',
			style: {
				'border-width': 2,
				'border-color': '#2b6ff7',
				'background-blacken': -0.05
			}
		},
		{
			selector: 'node.is-hovered',
			style: {
				'border-width': 2.5,
				'border-color': '#f28f3b',
				'shadow-blur': 14,
				'shadow-color': 'rgba(242, 143, 59, 0.22)',
				'shadow-opacity': 1,
				'shadow-offset-x': 0,
				'shadow-offset-y': 4
			}
		},
		{
			selector: 'node.is-hovered-neighbor',
			style: {
				'border-width': 2,
				'border-color': 'rgba(242, 143, 59, 0.48)'
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
				'target-arrow-color': 'rgba(43, 111, 247, 0.38)',
				width: 3
			}
		},
		{
			selector: 'edge.is-hovered',
			style: {
				'line-color': 'rgba(242, 143, 59, 0.54)',
				'target-arrow-color': 'rgba(242, 143, 59, 0.54)',
				width: 3
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
	let hoveredNodeId: string | null = null;
	let hoverPreview: HoverPreview | null = null;
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

	function isAggregateNodeKind(kind: NodeKind | null) {
		return Boolean(kind && !detailNodeKinds.has(kind));
	}

	function clamp(value: number, min: number, max: number) {
		return Math.max(min, Math.min(max, value));
	}

	function truncateText(value: string, limit: number) {
		const normalized = value.replace(/\s+/g, ' ').trim();
		if (normalized.length <= limit) return normalized;
		return `${normalized.slice(0, Math.max(limit - 1, 1)).trimEnd()}…`;
	}

	function nodeColor(type?: string | null) {
		const kind = asNodeKind(type);
		return kind ? nodeTypeMeta[kind].color : '#2b6ff7';
	}

	function nodeShape(type?: string | null) {
		const kind = asNodeKind(type);
		if (!kind) return 'round-rectangle';
		return isAggregateNodeKind(kind) ? 'round-rectangle' : nodeTypeMeta[kind].shape;
	}

	function nodeDisplayLabel(label: string, type?: string | null) {
		const kind = asNodeKind(type);
		return truncateText(label || '', isAggregateNodeKind(kind) ? 54 : 22) || '--';
	}

	function estimatedLineCount(label: string, type?: string | null) {
		const kind = asNodeKind(type);
		const charsPerLine = isAggregateNodeKind(kind) ? 16 : 12;
		const maxLines = isAggregateNodeKind(kind) ? 3 : 2;
		const normalized = label.replace(/\s+/g, ' ').trim();
		return clamp(Math.ceil(Math.max(normalized.length, 1) / charsPerLine), 1, maxLines);
	}

	function nodeLayoutMetrics(node: GraphNode) {
		const kind = asNodeKind(node.type);
		const displayLabel = nodeDisplayLabel(node.label || node.id, node.type);
		const lineCount = estimatedLineCount(displayLabel, node.type);
		const aggregate = isAggregateNodeKind(kind);
		const degreeBoost = Math.min(node.degree ?? 0, aggregate ? 5 : 4);
		const width = aggregate
			? clamp(98 + Math.min(displayLabel.length, 44) * 2.1 + degreeBoost * 5, 98, 210)
			: clamp(58 + Math.min(displayLabel.length, 22) * 1.55 + degreeBoost * 4, 58, 128);
		const height = aggregate
			? clamp(52 + ((lineCount - 1) * 22) + degreeBoost * 4, 52, 118)
			: clamp(44 + ((lineCount - 1) * 18) + degreeBoost * 3, 44, 82);
		return {
			aggregate,
			displayLabel,
			width: Math.round(width),
			height: Math.round(height),
			textMaxWidth: Math.max(Math.round(width - 18), aggregate ? 76 : 44),
			fontSize: aggregate ? 12 : 10,
			focusZoom: aggregate ? 0.88 : 1.02,
			layoutRepulsion: aggregate ? 26000 + degreeBoost * 900 : 12000 + degreeBoost * 700
		};
	}

	function edgeWidth(weight?: number | null) {
		return Math.max(1.4, Math.min(5, (weight ?? 1) + 0.25));
	}

	function getNodeLabel(nodeId: string) {
		if (!cy) return nodeId;
		const node = cy.$id(nodeId);
		return node.empty() ? nodeId : String(node.data('fullLabel') ?? nodeId);
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

	function visibleGraphElements(): CollectionReturnValue | null {
		if (!cy) return null;
		return cy.elements().filter((element) => !element.hasClass('is-hidden'));
	}

	function fitVisibleGraph(animate = true) {
		if (!cy) return;
		const visible = visibleGraphElements();
		if (!visible || visible.empty()) return;

		if (animate) {
			cy.animate({
				fit: { eles: visible, padding: graphViewportPadding },
				duration: graphAnimationDuration,
				easing: 'ease-out-cubic'
			});
			return;
		}

		cy.fit(visible, graphViewportPadding);
	}

	function focusNodeInViewport(nodeId: string) {
		if (!cy) return;
		const node = cy.$id(nodeId);
		if (node.empty()) return;
		const targetZoom = clamp(
			Math.max(
				cy.zoom(),
				typeof node.data('focusZoom') === 'number' ? Number(node.data('focusZoom')) : 0.92
			),
			0.45,
			1.25
		);
		cy.animate({
			center: { eles: node },
			zoom: targetZoom,
			duration: graphAnimationDuration,
			easing: 'ease-out-cubic'
		});
	}

	function focusEdgeInViewport(edgeId: string) {
		if (!cy) return;
		const edge = cy.$id(edgeId);
		if (edge.empty()) return;
		cy.animate({
			fit: { eles: edge.union(edge.connectedNodes()), padding: 92 },
			duration: graphAnimationDuration,
			easing: 'ease-out-cubic'
		});
	}

	function clearHoverPreview(shouldSync = true) {
		hoveredNodeId = null;
		hoverPreview = null;
		if (shouldSync) {
			syncSelectionStyles();
		}
	}

	function updateHoverPreview(node: NodeSingular) {
		if (!graphContainer) return;
		const position = node.renderedPosition();
		hoverPreview = {
			nodeId: node.id(),
			label: String(node.data('fullLabel') ?? node.id()),
			typeLabel: selectedNodeTypeLabel(
				typeof node.data('entityType') === 'string' ? node.data('entityType') : null
			),
			degree: typeof node.data('degree') === 'number' ? node.data('degree') : null,
			left: clamp(position.x + 18, 14, Math.max(14, graphContainer.clientWidth - 228)),
			top: clamp(position.y + 16, 14, Math.max(14, graphContainer.clientHeight - 104))
		};
	}

	function setHoveredNode(node: NodeSingular | null) {
		if (!node) {
			clearHoverPreview();
			return;
		}
		if (selectedNode?.id === node.id()) {
			clearHoverPreview();
			return;
		}
		hoveredNodeId = node.id();
		updateHoverPreview(node);
		syncSelectionStyles();
	}

	function syncSelectionStyles() {
		if (!cy) return;
		cy.batch(() => {
			cy?.elements().removeClass('is-selected');
			cy?.elements().removeClass('is-connected');
			cy?.elements().removeClass('is-hovered');
			cy?.elements().removeClass('is-hovered-neighbor');

			if (selectedNode) {
				const node = cy?.$id(selectedNode.id);
				if (node && !node.empty()) {
					node.addClass('is-selected');
					node.connectedNodes().difference(node).addClass('is-connected');
					node.connectedEdges().addClass('is-connected');
				}
			} else if (selectedEdge) {
				const edge = cy?.$id(selectedEdge.id);
				if (edge && !edge.empty()) {
					edge.addClass('is-selected');
					edge.connectedNodes().addClass('is-connected');
				}
			}

			if (hoveredNodeId) {
				const node = cy?.$id(hoveredNodeId);
				if (node && !node.empty()) {
					node.addClass('is-hovered');
					node.connectedNodes().difference(node).addClass('is-hovered-neighbor');
					node.connectedEdges().addClass('is-hovered');
				}
			}
		});
	}

	function clearSelection() {
		detailRequestId += 1;
		hoveredNodeId = null;
		hoverPreview = null;
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
				const label = String(node.data('fullLabel') ?? '').toLowerCase();
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
		if (hoveredNodeId) {
			const hoveredNode = cy.$id(hoveredNodeId);
			if (hoveredNode.empty() || hoveredNode.hasClass('is-hidden')) {
				hoveredNodeId = null;
				hoverPreview = null;
			}
		}
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

	async function selectNode(
		nodeId: string,
		options: { focus?: boolean; reloadDetail?: boolean } = {}
	) {
		if (!cy) return;
		const node = cy.$id(nodeId);
		if (node.empty()) return;
		const parsed = parseGraphNodeId(nodeId);
		const nextSelectedNode: SelectedNode = {
			id: nodeId,
			label: String(node.data('fullLabel') ?? nodeId),
			type: typeof node.data('entityType') === 'string' ? node.data('entityType') : null,
			degree: typeof node.data('degree') === 'number' ? node.data('degree') : null,
			kind: parsed.kind,
			resourceId: parsed.resourceId || null
		};
		const shouldReloadDetail =
			options.reloadDetail ??
			(nextSelectedNode.id !== selectedNode?.id ||
				nextSelectedNode.kind !== selectedNode?.kind ||
				nextSelectedNode.resourceId !== selectedNode?.resourceId ||
				Boolean(detailError));

		clearHoverPreview(false);
		selectedEdge = null;
		selectedNode = nextSelectedNode;
		syncSelectionStyles();
		if (options.focus !== false) {
			focusNodeInViewport(nodeId);
		}
		if (shouldReloadDetail) {
			await loadNodeDetail(nextSelectedNode);
		}
	}

	function selectEdge(edgeId: string, focus = true) {
		if (!cy) return;
		const edge = cy.$id(edgeId);
		if (edge.empty()) return;
		detailRequestId += 1;
		clearHoverPreview(false);
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
		if (focus) {
			focusEdgeInViewport(edgeId);
		}
	}

	function attachRendererEvents() {
		if (!cy) return;
		cy.on('tap', 'node', (event) => {
			void selectNode(event.target.id());
		});
		cy.on('dbltap', 'node', (event) => {
			void expandNeighborhood(event.target.id());
		});
		cy.on('mouseover', 'node', (event) => {
			setHoveredNode(event.target);
		});
		cy.on('mouseout', 'node', (event) => {
			if (hoveredNodeId === event.target.id()) {
				clearHoverPreview();
			}
		});
		cy.on('tap', 'edge', (event) => {
			selectEdge(event.target.id());
		});
		cy.on('tap', (event) => {
			if (event.target === cy) {
				clearSelection();
			}
		});
		cy.on('dbltap', (event) => {
			if (event.target === cy) {
				fitVisibleGraph(true);
			}
		});
		cy.on('pan', () => {
			if (hoveredNodeId || hoverPreview) {
				clearHoverPreview();
			}
		});
		cy.on('zoom', () => {
			if (hoveredNodeId || hoverPreview) {
				clearHoverPreview();
			}
		});
		cy.on('tapdrag', () => {
			if (hoveredNodeId || hoverPreview) {
				clearHoverPreview();
			}
		});
	}

	function buildGraphElements(
		nodes: GraphNode[],
		edges: GraphEdge[],
		previousPositions: Map<string, Position>
	): ElementDefinition[] {
		const nodeIds = new Set(nodes.map((node) => node.id));
		const nodeMap = new Map(nodes.map((node) => [node.id, node]));
		const elements: ElementDefinition[] = [];

		for (const [index, node] of nodes.entries()) {
			const position = previousPositions.get(node.id) ?? fallbackPosition(node.id, index, nodes.length);
			const metrics = nodeLayoutMetrics(node);
			elements.push({
				group: 'nodes',
				classes: metrics.aggregate ? 'is-card-node' : 'is-detail-node',
				data: {
					id: node.id,
					label: metrics.displayLabel,
					fullLabel: node.label,
					entityType: node.type ?? null,
					degree: node.degree ?? 0,
					color: nodeColor(node.type),
					width: metrics.width,
					height: metrics.height,
					textMaxWidth: metrics.textMaxWidth,
					fontSize: metrics.fontSize,
					focusZoom: metrics.focusZoom,
					layoutRepulsion: metrics.layoutRepulsion,
					shape: nodeShape(node.type)
				},
				position
			});
		}

		for (const edge of edges) {
			if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
			const edgeId = edge.id || `${edge.source}-${edge.target}`;
			const sourceKind = asNodeKind(nodeMap.get(edge.source)?.type);
			const targetKind = asNodeKind(nodeMap.get(edge.target)?.type);
			const idealLength =
				isAggregateNodeKind(sourceKind) || isAggregateNodeKind(targetKind) ? 170 : 128;
			elements.push({
				group: 'edges',
				data: {
					id: edgeId,
					source: edge.source,
					target: edge.target,
					label: edgeRelationLabel(edge.edge_description),
					weight: edge.weight ?? 1,
					width: edgeWidth(edge.weight),
					idealLength,
					edgeDescription: edge.edge_description ?? null
				}
			});
		}

		return elements;
	}

	async function runGraphLayout(previousPositions: Map<string, Position>) {
		if (!cy || cy.nodes().length < 2) {
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
				quality: 'proof',
				randomize: false,
				animate: false,
				fit: false,
				padding: graphViewportPadding,
				nodeDimensionsIncludeLabels: true,
				uniformNodeDimensions: false,
				nodeSeparation: 88,
				nodeRepulsion: (node: NodeSingular) => Number(node.data('layoutRepulsion') ?? 12000),
				idealEdgeLength: (edge: EdgeSingular) => Number(edge.data('idealLength') ?? 132),
				edgeElasticity: 0.2,
				gravity: 0.18,
				gravityRange: 3.2,
				numIter: 3000,
				tile: true,
				tilingPaddingVertical: 20,
				tilingPaddingHorizontal: 20,
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
			await runGraphLayout(previousPositions);
			if (previousViewport) {
				restoreViewport(previousViewport);
			}
		}

		updateVisibility();
		if (shouldFit) {
			fitVisibleGraph(false);
		}
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

	async function expandNeighborhood(nodeId: string) {
		if (!nodeId || expandingNeighborhood) return;
		expandingNeighborhood = true;
		detailError = '';
		try {
			const response = await fetchCollectionGraphNeighbors(collectionId, nodeId);
			graphData = mergeGraphPayload(graphData, response);
			await renderGraph(graphData.nodes, graphData.edges, nodeId);
			status = $t('graph.neighborsExpanded');
		} catch (err) {
			detailError = errorMessage(err);
		} finally {
			expandingNeighborhood = false;
		}
	}

	async function expandSelectedNeighborhood() {
		if (!selectedNode) return;
		await expandNeighborhood(selectedNode.id);
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
			<button
				class="btn btn--ghost"
				type="button"
				on:click={() => fitVisibleGraph(true)}
				disabled={!visibleNodes}
			>
				{$t('graph.resetView')}
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
				<p class="graph-hint">{$t('graph.interactionHint')}</p>
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
				{#if hoverPreview}
					<div
						class="graph-hover-preview"
						style={`left:${hoverPreview.left}px;top:${hoverPreview.top}px;`}
						aria-hidden="true"
					>
						<div class="graph-hover-preview__title">{hoverPreview.label}</div>
						<div class="graph-hover-preview__meta">
							<span>{hoverPreview.typeLabel || '--'}</span>
							<span>{$t('graph.detailDegree')}: {hoverPreview.degree ?? '--'}</span>
						</div>
					</div>
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
						<span class="detail-tag">{selectedNodeTypeLabel(selectedNode.type)}</span>
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

	.graph-hint {
		margin: 0;
		font-size: 0.84rem;
		line-height: 1.5;
		color: var(--color-subtle);
	}

	.graph-hover-preview {
		position: absolute;
		z-index: 2;
		max-width: 210px;
		padding: 0.7rem 0.8rem;
		border: 1px solid rgba(15, 27, 45, 0.12);
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.96);
		box-shadow: 0 16px 32px rgba(15, 27, 45, 0.16);
		backdrop-filter: blur(10px);
		pointer-events: none;
	}

	.graph-hover-preview__title {
		font-weight: 700;
		font-size: 0.92rem;
		line-height: 1.35;
	}

	.graph-hover-preview__meta {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		margin-top: 0.35rem;
		font-size: 0.76rem;
		color: var(--color-subtle);
	}
</style>
