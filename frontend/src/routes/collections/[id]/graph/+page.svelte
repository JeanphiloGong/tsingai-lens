<script lang="ts">
	import { tick, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import cytoscape, { type Core, type EdgeSingular, type NodeSingular } from 'cytoscape';
	import fcose from 'cytoscape-fcose';
	import { errorMessage, getApiErrorCode, isHttpStatusError } from '../../../_shared/api';
	import {
		buildCytoscapeElements,
		buildCytoscapeStyles,
		buildGraphMeta,
		buildNodeTypeCounts,
		downloadGraphml as downloadGraphmlFile,
		exportGraphPng,
		fetchCollectionGraph,
		fetchCollectionGraphNeighbors,
		filterGraphElements,
		formatGraphLabel,
		getEdgeTypeStyle,
		getLinkedComparisons,
		getLinkedDocuments,
		getLinkedEvidence,
		getNodeDescription,
		getNodeTypeStyle,
		getSelectedObjectDetail,
		graphNodeTypeOrder,
		parseGraphNodeId,
		runGraphLayout,
		type GraphEdge,
		type GraphMeta,
		type GraphNode,
		type GraphNodeType,
		type GraphPosition,
		type GraphResponse,
		type GraphSelectedObject
	} from '../../../_shared/graph';
	import {
		fetchComparisonRow,
		fetchComparisons,
		type ComparisonRow
	} from '../../../_shared/comparisons';
	import {
		fetchDocumentProfile,
		fetchDocumentProfiles,
		type DocumentProfile
	} from '../../../_shared/documents';
	import {
		fetchEvidenceCard,
		fetchEvidenceCards,
		type EvidenceCard
	} from '../../../_shared/evidence';
	import { t } from '../../../_shared/i18n';
	import { createBuildTask } from '../../../_shared/tasks';
	import { buildDocumentViewerHref } from '../../../_shared/traceback';
	import {
		fetchWorkspaceOverview,
		getWorkspaceSurfaceState,
		type WorkspaceOverview
	} from '../../../_shared/workspace';

	cytoscape.use(fcose);

	type LayoutName = 'fcose' | 'cose' | 'grid' | 'circle';
	type LinkedTab = 'evidence' | 'comparison' | 'documents';
	type SelectedNode = GraphNode & {
		kind: GraphNodeType | 'unknown';
		resourceId: string | null;
		displayLabel: string;
	};
	type SelectedEdge = GraphEdge & {
		sourceLabel: string;
		targetLabel: string;
		relationLabel: string;
	};
	type NodeDetail =
		| { kind: 'document'; data: DocumentProfile }
		| { kind: 'evidence'; data: EvidenceCard }
		| { kind: 'comparison'; data: ComparisonRow };
	type HoverPreview = {
		label: string;
		typeLabel: string;
		left: number;
		top: number;
	};
	type RelationPreview = {
		label: string;
		target: string;
	};

	const defaultMaxNodes = 200;
	const defaultMinWeight = 0;
	const graphPadding = 72;
	const graphAnimationDuration = 220;

	let collectionId = '';
	let graphContainer: HTMLDivElement | null = null;
	let cy: Core | null = null;
	let graphData: GraphResponse | null = null;
	let workspace: WorkspaceOverview | null = null;
	let loadedCollectionId = '';

	let loading = false;
	let supportLoading = false;
	let detailLoading = false;
	let expandingNeighborhood = false;
	let exportMenuOpen = false;
	let notFound = false;
	let error = '';
	let status = '';
	let supportStatus = '';
	let detailError = '';

	let maxNodes = defaultMaxNodes;
	let minWeight = defaultMinWeight;
	let layoutName: LayoutName = 'fcose';
	let searchQuery = '';
	let visibleNodeTypes: Partial<Record<GraphNodeType, boolean>> = buildDefaultVisibleTypes();
	let visibleNodes = 0;
	let visibleEdges = 0;

	let selectedNode: SelectedNode | null = null;
	let selectedEdge: SelectedEdge | null = null;
	let selectedNodeDetail: NodeDetail | null = null;
	let hoverPreview: HoverPreview | null = null;
	let linkedTab: LinkedTab = 'evidence';
	let detailRequestId = 0;

	let evidenceItems: EvidenceCard[] = [];
	let comparisonItems: ComparisonRow[] = [];
	let documentItems: DocumentProfile[] = [];

	$: collectionId = $page.params.id ?? '';
	$: graphMeta = buildGraphMeta(graphData);
	$: nodeTypeCounts = buildNodeTypeCounts(graphData);
	$: availableNodeTypes = graphNodeTypeOrder.filter((type) => nodeTypeCounts[type] > 0);
	$: surfaceState = getWorkspaceSurfaceState(workspace, 'graph');
	$: selectedObject = selectedNode
		? ({ kind: 'node', node: selectedNode } as GraphSelectedObject)
		: selectedEdge
			? ({ kind: 'edge', edge: selectedEdge } as GraphSelectedObject)
			: null;
	$: selectedDetail = getSelectedObjectDetail(selectedObject);
	$: linkedEvidence = getLinkedEvidence(selectedObject, evidenceItems);
	$: linkedComparisons = getLinkedComparisons(selectedObject, comparisonItems);
	$: linkedDocuments = buildLinkedDocuments(
		getLinkedDocuments(selectedObject, documentItems),
		linkedEvidence,
		linkedComparisons
	);
	$: selectedStats = {
		evidence: linkedEvidence.length,
		comparison: linkedComparisons.length,
		documents: linkedDocuments.length
	};
	$: commonRelations = buildCommonRelations();
	$: showEmptyGraph = !loading && (!graphData || !graphData.nodes.length || (notFound && !visibleNodes));
	$: if (cy) {
		searchQuery;
		visibleNodeTypes;
		applyVisibilityAndSearch();
	}
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		resetControlState();
		void loadGraph();
	}

	onDestroy(() => {
		disposeRenderer();
	});

	function buildDefaultVisibleTypes() {
		return Object.fromEntries(graphNodeTypeOrder.map((type) => [type, true])) as Partial<
			Record<GraphNodeType, boolean>
		>;
	}

	function resetControlState() {
		maxNodes = defaultMaxNodes;
		minWeight = defaultMinWeight;
		layoutName = 'fcose';
		searchQuery = '';
		visibleNodeTypes = buildDefaultVisibleTypes();
		linkedTab = 'evidence';
	}

	function disposeRenderer() {
		if (!cy) return;
		cy.destroy();
		cy = null;
	}

	function currentPositions() {
		const positions = new Map<string, GraphPosition>();
		cy?.nodes().forEach((node) => {
			const position = node.position();
			positions.set(node.id(), { x: position.x, y: position.y });
		});
		return positions;
	}

	function visibleGraphElements() {
		return cy?.elements().filter((element) => !element.hasClass('is-hidden')) ?? null;
	}

	function fitGraph(animate = true) {
		if (!cy) return;
		const visible = visibleGraphElements();
		if (!visible || visible.empty()) return;
		if (animate) {
			cy.animate({
				fit: { eles: visible, padding: graphPadding },
				duration: graphAnimationDuration,
				easing: 'ease-out-cubic'
			});
			return;
		}
		cy.fit(visible, graphPadding);
	}

	function centerGraph() {
		const visible = visibleGraphElements();
		if (!cy || !visible || visible.empty()) return;
		cy.animate({
			center: { eles: visible },
			duration: graphAnimationDuration,
			easing: 'ease-out-cubic'
		});
	}

	function zoomGraph(factor: number) {
		if (!cy) return;
		cy.animate({
			zoom: Math.max(0.22, Math.min(2.4, cy.zoom() * factor)),
			duration: graphAnimationDuration,
			easing: 'ease-out-cubic'
		});
	}

	function currentTheme() {
		if (typeof document === 'undefined') return 'light';
		return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
	}

	function buildVisibleGraphPayload() {
		if (!graphData) return { nodes: [], edges: [] };
		return filterGraphElements(graphData, {
			maxNodes,
			minWeight,
			visibleNodeTypes
		});
	}

	async function renderGraph(focusNodeId: string | null = null) {
		if (!graphData) return;
		if (!graphContainer) {
			await tick();
		}
		if (!graphContainer) return;

		const previousPositions = currentPositions();
		const payload = buildVisibleGraphPayload();
		disposeRenderer();
		clearSelection(false);

		cy = cytoscape({
			container: graphContainer,
			elements: buildCytoscapeElements(payload, { previousPositions }),
			style: buildCytoscapeStyles(currentTheme()),
			layout: { name: 'preset' },
			minZoom: 0.2,
			maxZoom: 2.6,
			wheelSensitivity: 0.2,
			boxSelectionEnabled: false
		});

		attachRendererEvents();
		await runGraphLayout(cy, layoutName);
		applyVisibilityAndSearch();
		fitGraph(false);

		if (focusNodeId) {
			const focusNode = cy.$id(focusNodeId);
			if (!focusNode.empty()) {
				await selectNode(focusNodeId, { focus: true });
			}
		}
	}

	function attachRendererEvents() {
		if (!cy) return;
		cy.on('tap', 'node', (event) => {
			void selectNode(event.target.id(), { focus: true });
		});
		cy.on('dbltap', 'node', (event) => {
			void expandNeighborhood(event.target.id());
		});
		cy.on('mouseover', 'node', (event) => {
			updateHoverPreview(event.target as NodeSingular);
		});
		cy.on('mouseout', () => {
			hoverPreview = null;
			syncSelectionStyles();
		});
		cy.on('tap', 'edge', (event) => {
			selectEdge(event.target.id(), true);
		});
		cy.on('tap', (event) => {
			if (event.target === cy) {
				clearSelection();
			}
		});
		cy.on('pan zoom tapdrag', () => {
			hoverPreview = null;
		});
	}

	function applyVisibilityAndSearch() {
		if (!cy) return;
		const query = searchQuery.trim().toLowerCase();

		cy.batch(() => {
			cy?.nodes().forEach((node) => {
				const type = String(node.data('entityType') ?? 'unknown') as GraphNodeType;
				const typeVisible = visibleNodeTypes[type] ?? true;
				const label = String(node.data('fullLabel') ?? '').toLowerCase();
				const displayLabel = String(node.data('displayLabel') ?? '').toLowerCase();
				const id = node.id().toLowerCase();
				const matches = Boolean(query && `${label} ${displayLabel} ${id}`.includes(query));
				node.toggleClass('is-hidden', !typeVisible);
				node.toggleClass('search-match', matches);
			});
			cy?.edges().forEach((edge) => {
				edge.toggleClass(
					'is-hidden',
					edge.source().hasClass('is-hidden') || edge.target().hasClass('is-hidden')
				);
			});
		});

		visibleNodes = cy.nodes().filter((node) => !node.hasClass('is-hidden')).length;
		visibleEdges = cy.edges().filter((edge) => !edge.hasClass('is-hidden')).length;
		syncSelectionStyles();
	}

	function syncSelectionStyles() {
		if (!cy) return;
		cy.batch(() => {
			cy?.elements().removeClass('is-selected is-neighbor is-dimmed');
			const selectedId = selectedNode?.id ?? selectedEdge?.id ?? '';
			if (!selectedId) return;

			cy?.elements().addClass('is-dimmed');
			if (selectedNode) {
				const node = cy?.$id(selectedNode.id);
				if (node && !node.empty()) {
					const connected = node.closedNeighborhood();
					connected.removeClass('is-dimmed');
					node.addClass('is-selected');
					node.connectedNodes().addClass('is-neighbor');
					node.connectedEdges().addClass('is-neighbor');
				}
			}
			if (selectedEdge) {
				const edge = cy?.$id(selectedEdge.id);
				if (edge && !edge.empty()) {
					edge.removeClass('is-dimmed').addClass('is-selected');
					edge.connectedNodes().removeClass('is-dimmed').addClass('is-neighbor');
				}
			}
		});
	}

	function updateHoverPreview(node: NodeSingular) {
		if (!graphContainer || selectedNode?.id === node.id()) return;
		const position = node.renderedPosition();
		hoverPreview = {
			label: String(node.data('fullLabel') ?? node.id()),
			typeLabel: nodeTypeLabel(String(node.data('entityType') ?? 'unknown')),
			left: clamp(position.x + 18, 12, Math.max(12, graphContainer.clientWidth - 230)),
			top: clamp(position.y + 14, 12, Math.max(12, graphContainer.clientHeight - 112))
		};
		syncSelectionStyles();
	}

	function clearSelection(sync = true) {
		detailRequestId += 1;
		selectedNode = null;
		selectedEdge = null;
		selectedNodeDetail = null;
		detailError = '';
		detailLoading = false;
		hoverPreview = null;
		if (sync) syncSelectionStyles();
	}

	async function selectNode(nodeId: string, options: { focus?: boolean } = {}) {
		if (!cy) return;
		const node = cy.$id(nodeId);
		if (node.empty()) return;
		const parsed = parseGraphNodeId(nodeId);
		const entityType = String(node.data('entityType') ?? parsed.kind ?? 'unknown') as GraphNodeType;
		selectedNode = {
			id: node.id(),
			label: String(node.data('fullLabel') ?? node.id()),
			type: entityType,
			degree: Number(node.data('degree') ?? 0),
			kind: parsed.kind === 'unknown' ? entityType : parsed.kind,
			resourceId: parsed.resourceId || null,
			displayLabel: String(node.data('displayLabel') ?? node.data('fullLabel') ?? node.id())
		};
		selectedEdge = null;
		linkedTab = 'evidence';
		syncSelectionStyles();
		if (options.focus) focusNode(nodeId);
		void loadNodeDetail(selectedNode);
	}

	function selectEdge(edgeId: string, focus = false) {
		if (!cy) return;
		const edge = cy.$id(edgeId);
		if (edge.empty()) return;
		detailRequestId += 1;
		selectedNode = null;
		selectedNodeDetail = null;
		detailError = '';
		detailLoading = false;
		selectedEdge = {
			id: edge.id(),
			source: String(edge.data('source') ?? ''),
			target: String(edge.data('target') ?? ''),
			edge_description: String(edge.data('edgeDescription') ?? 'related_to'),
			weight: typeof edge.data('weight') === 'number' ? Number(edge.data('weight')) : null,
			sourceLabel: nodeLabelForId(String(edge.data('source') ?? '')),
			targetLabel: nodeLabelForId(String(edge.data('target') ?? '')),
			relationLabel: String(edge.data('label') ?? '')
		};
		linkedTab = 'evidence';
		syncSelectionStyles();
		if (focus) {
			cy.animate({
				fit: { eles: edge.connectedNodes().union(edge), padding: 100 },
				duration: graphAnimationDuration,
				easing: 'ease-out-cubic'
			});
		}
	}

	function focusNode(nodeId: string) {
		if (!cy) return;
		const node = cy.$id(nodeId);
		if (node.empty()) return;
		cy.animate({
			center: { eles: node },
			zoom: Math.max(cy.zoom(), 0.88),
			duration: graphAnimationDuration,
			easing: 'ease-out-cubic'
		});
	}

	function focusFirstSearchMatch() {
		if (!cy) return;
		const match = cy.nodes('.search-match').filter((node) => !node.hasClass('is-hidden'))[0];
		if (match) {
			void selectNode(match.id(), { focus: true });
		}
	}

	async function loadNodeDetail(node: SelectedNode) {
		const requestId = ++detailRequestId;
		selectedNodeDetail = null;
		detailError = '';
		detailLoading =
			node.kind === 'document' || node.kind === 'evidence' || node.kind === 'comparison';

		if (!detailLoading || !node.resourceId) return;

		try {
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

	async function loadGraph() {
		loading = true;
		error = '';
		status = '';
		supportStatus = '';
		notFound = false;
		clearSelection(false);

		const [graphResult, workspaceResult] = await Promise.allSettled([
			fetchCollectionGraph(collectionId, { maxNodes, minWeight }),
			fetchWorkspaceOverview(collectionId)
		]);

		workspace = workspaceResult.status === 'fulfilled' ? workspaceResult.value : null;

		try {
			if (graphResult.status !== 'fulfilled') throw graphResult.reason;
			graphData = graphResult.value;
			visibleNodeTypes = ensureVisibleTypes(graphData);
			await renderGraph();
			status = graphData.truncated
				? $t('graph.status.loadedTruncated')
				: $t('graph.status.loaded');
		} catch (err) {
			const errorCode = getApiErrorCode(err);
			error = errorMessage(err);
			notFound = errorCode ? errorCode === 'collection_not_found' : isHttpStatusError(err, 404);
			graphData = null;
			visibleNodes = 0;
			visibleEdges = 0;
			disposeRenderer();
		} finally {
			loading = false;
			void loadSupportData();
		}
	}

	async function loadSupportData() {
		if (!collectionId) return;
		supportLoading = true;
		supportStatus = '';
		const [evidenceResult, comparisonResult, documentResult] = await Promise.allSettled([
			fetchEvidenceCards(collectionId),
			fetchComparisons(collectionId, { limit: 120 }),
			fetchDocumentProfiles(collectionId)
		]);

		evidenceItems = evidenceResult.status === 'fulfilled' ? evidenceResult.value.items : [];
		comparisonItems = comparisonResult.status === 'fulfilled' ? comparisonResult.value.items : [];
		documentItems = documentResult.status === 'fulfilled' ? documentResult.value.items : [];
		if (
			evidenceResult.status === 'rejected' ||
			comparisonResult.status === 'rejected' ||
			documentResult.status === 'rejected'
		) {
			supportStatus = $t('graph.status.supportPartial');
		}
		supportLoading = false;
	}

	async function handleGenerateGraph() {
		try {
			status = $t('graph.status.generating');
			await createBuildTask(collectionId);
			status = $t('graph.status.generateStarted');
		} catch (err) {
			error = errorMessage(err);
		}
	}

	async function handleRefreshGraph() {
		await loadGraph();
	}

	async function handleResetView() {
		resetControlState();
		if (graphData) {
			await renderGraph();
		}
		fitGraph(true);
	}

	async function handleRestoreDefaults() {
		resetControlState();
		if (graphData) {
			await renderGraph();
		}
	}

	async function handleControlRender() {
		if (!graphData) return;
		await renderGraph(selectedNode?.id ?? null);
	}

	async function handleLayout() {
		if (!cy) return;
		await runGraphLayout(cy, layoutName);
		fitGraph(true);
	}

	async function expandNeighborhood(nodeId: string) {
		if (!nodeId || expandingNeighborhood) return;
		expandingNeighborhood = true;
		detailError = '';
		try {
			const response = await fetchCollectionGraphNeighbors(collectionId, nodeId);
			graphData = mergeGraphPayload(graphData, response);
			await renderGraph(nodeId);
			status = $t('graph.status.neighborsExpanded');
		} catch (err) {
			detailError = errorMessage(err);
		} finally {
			expandingNeighborhood = false;
		}
	}

	function mergeGraphPayload(
		current: GraphResponse | null,
		next: Pick<GraphResponse, 'collection_id' | 'nodes' | 'edges' | 'truncated'>
	): GraphResponse {
		const nodes = new Map<string, GraphNode>();
		const edges = new Map<string, GraphEdge>();
		for (const node of current?.nodes ?? []) nodes.set(node.id, node);
		for (const node of next.nodes) nodes.set(node.id, node);
		for (const edge of current?.edges ?? []) edges.set(edge.id, edge);
		for (const edge of next.edges) edges.set(edge.id, edge);
		return {
			collection_id: next.collection_id,
			nodes: Array.from(nodes.values()),
			edges: Array.from(edges.values()),
			truncated: Boolean(current?.truncated || next.truncated)
		};
	}

	function ensureVisibleTypes(graph: GraphResponse | null) {
		const next = { ...visibleNodeTypes };
		for (const node of graph?.nodes ?? []) {
			const type = String(node.type ?? 'unknown') as GraphNodeType;
			if (next[type] === undefined) next[type] = true;
		}
		return next;
	}

	function toggleNodeType(type: GraphNodeType, checked: boolean) {
		visibleNodeTypes = { ...visibleNodeTypes, [type]: checked };
	}

	function nodeTypeLabel(type: string) {
		const key = type === 'test_condition' ? 'testCondition' : type;
		const translated = $t(`graph.legend.${key}`);
		return translated === `graph.legend.${key}` ? formatMachineText(type) : translated;
	}

	function nodeLabelForId(nodeId: string) {
		if (!cy) return nodeId;
		const node = cy.$id(nodeId);
		if (node.empty()) return nodeId;
		return String(node.data('displayLabel') ?? node.data('fullLabel') ?? nodeId);
	}

	function selectedNodeDescription() {
		if (!selectedNode) return '';
		if (selectedNodeDetail?.kind === 'document') {
			return (
				selectedNodeDetail.data.title ||
				selectedNodeDetail.data.source_filename ||
				getNodeDescription(selectedNode)
			);
		}
		if (selectedNodeDetail?.kind === 'evidence') {
			return selectedNodeDetail.data.claim_text || getNodeDescription(selectedNode);
		}
		if (selectedNodeDetail?.kind === 'comparison') {
			return selectedNodeDetail.data.display.result_summary || getNodeDescription(selectedNode);
		}
		return getNodeDescription(selectedNode);
	}

	function selectedActionHref(action: 'evidence' | 'comparison' | 'source') {
		const returnTo = `/collections/${encodeURIComponent(collectionId)}/graph`;
		if (action === 'evidence') return `/collections/${encodeURIComponent(collectionId)}/evidence`;
		if (action === 'comparison') {
			const filter = selectedNodeComparisonFilter();
			if (filter) {
				const params = new URLSearchParams({ [filter.key]: filter.value });
				return `/collections/${encodeURIComponent(collectionId)}/comparisons?${params.toString()}`;
			}
			if (selectedNode?.kind === 'comparison' && selectedNode.resourceId) {
				if (selectedNodeDetail?.kind === 'comparison') {
					return `/collections/${encodeURIComponent(collectionId)}/results/${encodeURIComponent(
						selectedNodeDetail.data.result_id
					)}`;
				}
				return `/collections/${encodeURIComponent(collectionId)}/comparisons`;
			}
			return `/collections/${encodeURIComponent(collectionId)}/comparisons`;
		}

		if (selectedNode?.kind === 'document' && selectedNode.resourceId) {
			return buildDocumentViewerHref(collectionId, selectedNode.resourceId, { returnTo });
		}
		if (
			selectedNode?.kind === 'evidence' &&
			selectedNodeDetail?.kind === 'evidence' &&
			selectedNodeDetail.data.document_id
		) {
			return buildDocumentViewerHref(collectionId, selectedNodeDetail.data.document_id, {
				evidenceId: selectedNodeDetail.data.evidence_id,
				anchorId: selectedNodeDetail.data.evidence_anchors[0]?.anchor_id,
				returnTo
			});
		}
		if (linkedEvidence[0]?.document_id) {
			return buildDocumentViewerHref(collectionId, linkedEvidence[0].document_id, {
				evidenceId: linkedEvidence[0].evidence_id,
				anchorId: linkedEvidence[0].evidence_anchors[0]?.anchor_id,
				returnTo
			});
		}
		if (linkedComparisons[0]?.source_document_id) {
			const evidenceId = linkedComparisons[0].evidence_bundle.supporting_evidence_ids[0] ?? null;
			return buildDocumentViewerHref(collectionId, linkedComparisons[0].source_document_id, {
				evidenceId,
				returnTo
			});
		}
		return null;
	}

	function selectedNodeComparisonFilter() {
		if (!selectedNode) return null;
		const value = selectedNode.label.trim();
		if (!value) return null;
		if (selectedNode.kind === 'material') return { key: 'material_system_normalized', value };
		if (selectedNode.kind === 'property') return { key: 'property_normalized', value };
		if (selectedNode.kind === 'test_condition') return { key: 'test_condition_normalized', value };
		if (selectedNode.kind === 'baseline') return { key: 'baseline_normalized', value };
		return null;
	}

	function buildLinkedDocuments(
		directDocuments: DocumentProfile[],
		evidence: EvidenceCard[],
		comparisons: ComparisonRow[]
	) {
		const docs = new Map(documentItems.map((item) => [item.document_id, item]));
		const linked = new Map<string, DocumentProfile>();
		for (const document of directDocuments) linked.set(document.document_id, document);
		for (const item of evidence) {
			const document = docs.get(item.document_id);
			if (document) linked.set(document.document_id, document);
		}
		for (const item of comparisons) {
			const document = docs.get(item.source_document_id);
			if (document) linked.set(document.document_id, document);
		}
		return Array.from(linked.values());
	}

	function buildCommonRelations(): RelationPreview[] {
		if (!cy || !selectedNode) return [];
		const node = cy.$id(selectedNode.id);
		if (node.empty()) return [];
		const relations: RelationPreview[] = [];
		node.connectedEdges().forEach((item) => {
			const edge = item as EdgeSingular;
			if (edge.hasClass('is-hidden') || relations.length >= 5) return;
			const other = edge.source().id() === selectedNode?.id ? edge.target() : edge.source();
			relations.push({
				label: String(edge.data('label') ?? 'related'),
				target: String(other.data('displayLabel') ?? other.data('fullLabel') ?? other.id())
			});
		});
		return relations;
	}

	function formatMachineText(value?: string | null) {
		return String(value ?? '')
			.replace(/[_-]+/g, ' ')
			.replace(/\s+/g, ' ')
			.trim()
			.replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
	}

	function formatConfidence(value?: number | null) {
		if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
		const percent = value <= 1 ? value * 100 : value;
		return `${Math.max(0, Math.min(100, Math.round(percent)))}%`;
	}

	function formatCount(value: number) {
		return Number.isFinite(value) ? value : 0;
	}

	function statusBadgeLabel(meta: GraphMeta) {
		if (loading) return $t('graph.status.loading');
		if (meta.nodeCount > 0) return $t('graph.status.built');
		return $t('graph.status.pending');
	}

	function statusBadgeTone() {
		if (loading) return 'warning';
		if (graphMeta.nodeCount > 0) return 'success';
		return 'neutral';
	}

	function evidenceSourceHref(item: EvidenceCard) {
		if (!item.document_id) return null;
		return buildDocumentViewerHref(collectionId, item.document_id, {
			evidenceId: item.evidence_id,
			anchorId: item.evidence_anchors[0]?.anchor_id,
			returnTo: `/collections/${encodeURIComponent(collectionId)}/graph`
		});
	}

	function comparisonHref(item: ComparisonRow) {
		return `/collections/${encodeURIComponent(collectionId)}/results/${encodeURIComponent(
			item.result_id
		)}`;
	}

	function comparisonSourceHref(item: ComparisonRow) {
		if (!item.source_document_id) return null;
		return buildDocumentViewerHref(collectionId, item.source_document_id, {
			evidenceId: item.evidence_bundle.supporting_evidence_ids[0] ?? null,
			returnTo: `/collections/${encodeURIComponent(collectionId)}/graph`
		});
	}

	function documentHref(item: DocumentProfile) {
		return buildDocumentViewerHref(collectionId, item.document_id, {
			returnTo: `/collections/${encodeURIComponent(collectionId)}/graph`
		});
	}

	function handleExportImage() {
		if (!cy) return;
		exportGraphPng(cy, `graph-${collectionId}.png`);
		status = $t('graph.status.imageExported');
		exportMenuOpen = false;
	}

	async function handleDownloadGraphml() {
		try {
			status = $t('graph.status.downloading');
			const fileName = await downloadGraphmlFile(collectionId, { maxNodes, minWeight });
			status = $t('graph.status.downloaded', { filename: fileName });
		} catch (err) {
			error = errorMessage(err);
		} finally {
			exportMenuOpen = false;
		}
	}

	async function copyCurrentView() {
		if (!cy) return;
		const view = {
			collectionId,
			selected: selectedNode?.id ?? selectedEdge?.id ?? null,
			zoom: cy.zoom(),
			pan: cy.pan(),
			filters: {
				maxNodes,
				minWeight,
				layoutName,
				searchQuery,
				visibleNodeTypes
			}
		};
		try {
			await navigator.clipboard.writeText(JSON.stringify(view, null, 2));
			status = $t('graph.status.viewCopied');
		} catch {
			status = $t('graph.status.copyUnavailable');
		} finally {
			exportMenuOpen = false;
		}
	}

	function clamp(value: number, min: number, max: number) {
		return Math.max(min, Math.min(max, value));
	}
</script>

<svelte:head>
	<title>{$t('graph.title')}</title>
</svelte:head>

<section class="graph-page-shell" aria-labelledby="graph-page-title">
	<header class="graph-page-card graph-header-card">
		<div class="graph-header-identity">
			<div class="graph-header-icon" aria-hidden="true">
				<span class="graph-icon graph-icon--network"></span>
			</div>
			<div class="graph-header-copy">
				<h1 id="graph-page-title">{$t('graph.title')}</h1>
				<p>{$t('graph.description')}</p>
				<div class="graph-meta-row" aria-label={$t('graph.meta.label')}>
					<span class="graph-meta-item">
						<span class="meta-icon meta-icon--node" aria-hidden="true"></span>
						{$t('graph.meta.nodes', { count: graphMeta.nodeCount })}
					</span>
					<span class="graph-meta-item">
						<span class="meta-icon meta-icon--edge" aria-hidden="true"></span>
						{$t('graph.meta.edges', { count: graphMeta.edgeCount })}
					</span>
					<span class="graph-meta-item">
						<span class="meta-icon meta-icon--type" aria-hidden="true"></span>
						{$t('graph.meta.types', { count: graphMeta.nodeTypeCount })}
					</span>
					<span class={`graph-status-badge graph-status-badge--${statusBadgeTone()}`}>
						<span class="meta-icon meta-icon--status" aria-hidden="true"></span>
						{statusBadgeLabel(graphMeta)}
					</span>
				</div>
			</div>
		</div>
		<div class="graph-header-actions">
			<button class="graph-button graph-button--ghost" type="button" on:click={handleRefreshGraph}>
				<span class="action-icon action-icon--refresh" aria-hidden="true"></span>
				{$t('graph.actions.refresh')}
			</button>
			<button class="graph-button graph-button--ghost" type="button" on:click={handleResetView}>
				<span class="action-icon action-icon--target" aria-hidden="true"></span>
				{$t('graph.actions.resetView')}
			</button>
			<div class="graph-export-menu">
				<button
					class="graph-button graph-button--primary"
					type="button"
					aria-haspopup="menu"
					aria-expanded={exportMenuOpen}
					on:click={() => (exportMenuOpen = !exportMenuOpen)}
				>
					<span class="action-icon action-icon--export" aria-hidden="true"></span>
					{$t('graph.actions.export')}
				</button>
				{#if exportMenuOpen}
					<div class="graph-export-dropdown" role="menu">
						<button type="button" role="menuitem" disabled={!cy} on:click={handleExportImage}>
							{$t('graph.actions.exportPng')}
						</button>
						<button type="button" role="menuitem" on:click={handleDownloadGraphml}>
							{$t('graph.actions.downloadGraphml')}
						</button>
						<button type="button" role="menuitem" disabled={!cy} on:click={copyCurrentView}>
							{$t('graph.actions.copyView')}
						</button>
					</div>
				{/if}
			</div>
		</div>
	</header>

	{#if status || supportStatus}
		<div class="graph-inline-status" role="status">{status || supportStatus}</div>
	{/if}
	{#if error}
		<div class="graph-inline-status graph-inline-status--error" role="alert">
			<span>{error}</span>
			<button class="graph-link-button" type="button" on:click={handleRefreshGraph}>
				{$t('graph.actions.retry')}
			</button>
		</div>
	{/if}

	{#if showEmptyGraph}
		<section class="graph-page-card graph-empty-state">
			<div class="graph-empty-state__icon" aria-hidden="true">
				<span class="graph-icon graph-icon--network"></span>
			</div>
			<h2>{$t('graph.empty.title')}</h2>
			<p>{$t('graph.empty.description')}</p>
			<div class="graph-empty-state__actions">
				<button class="graph-button graph-button--primary" type="button" on:click={handleGenerateGraph}>
					{$t('graph.empty.action')}
				</button>
				<button class="graph-button graph-button--ghost" type="button" on:click={handleRefreshGraph}>
					{$t('graph.actions.refreshStatus')}
				</button>
			</div>
			{#if workspace && surfaceState !== 'ready'}
				<p class="graph-empty-state__note">{$t(`overview.surfaceStateCards.${surfaceState}.body`)}</p>
			{/if}
		</section>
	{:else}
		<div class="graph-workspace" aria-label={$t('graph.workspace.label')}>
			<aside class="graph-page-card graph-controls-panel" aria-labelledby="graph-controls-title">
				<div class="graph-panel-header">
					<h2 id="graph-controls-title">{$t('graph.controls.title')}</h2>
				</div>

				<div class="graph-control-group">
					<label class="graph-control-label" for="graph-node-search">
						{$t('graph.controls.search')}
					</label>
					<div class="graph-search-control">
						<input
							id="graph-node-search"
							class="graph-input"
							bind:value={searchQuery}
							placeholder={$t('graph.controls.searchPlaceholder')}
							disabled={loading}
							on:keydown={(event) => {
								if (event.key === 'Enter') focusFirstSearchMatch();
							}}
						/>
						<button
							class="graph-search-button"
							type="button"
							aria-label={$t('graph.controls.focusSearch')}
							disabled={!searchQuery.trim()}
							on:click={focusFirstSearchMatch}
						>
							<span class="action-icon action-icon--search" aria-hidden="true"></span>
						</button>
					</div>
				</div>

				<fieldset class="graph-control-group graph-node-type-fieldset">
					<legend>{$t('graph.controls.nodeTypes')}</legend>
					<div class="graph-node-type-list">
						{#each availableNodeTypes as type}
							<label
								class="graph-node-type-row"
								style={`--node-color:${getNodeTypeStyle(type).color};--node-bg:${getNodeTypeStyle(type).background};`}
							>
								<span class="graph-node-type-icon" aria-hidden="true"></span>
								<span class="graph-node-type-label">{nodeTypeLabel(type)}</span>
								<span class="graph-node-type-count">{formatCount(nodeTypeCounts[type])}</span>
								<input
									type="checkbox"
									checked={visibleNodeTypes[type] ?? true}
									disabled={loading}
									on:change={(event) =>
										toggleNodeType(type, (event.currentTarget as HTMLInputElement).checked)}
								/>
							</label>
						{/each}
					</div>
				</fieldset>

				<details class="graph-advanced-settings" open>
					<summary>{$t('graph.controls.advanced')}</summary>
					<div class="graph-advanced-grid">
						<label class="graph-control-field" for="graph-max-nodes">
							<span>{$t('graph.controls.maxNodes')}</span>
							<input
								id="graph-max-nodes"
								class="graph-input"
								type="number"
								min="1"
								max="2000"
								bind:value={maxNodes}
								disabled={loading}
								on:change={handleControlRender}
							/>
						</label>
						<label class="graph-control-field" for="graph-min-weight">
							<span>{$t('graph.controls.minWeight')}</span>
							<input
								id="graph-min-weight"
								class="graph-input"
								type="number"
								min="0"
								step="0.01"
								bind:value={minWeight}
								disabled={loading}
								on:change={handleControlRender}
							/>
						</label>
						<label class="graph-control-field" for="graph-layout">
							<span>{$t('graph.controls.layout')}</span>
							<select
								id="graph-layout"
								class="graph-input"
								bind:value={layoutName}
								disabled={loading}
								on:change={handleLayout}
							>
								<option value="fcose">{$t('graph.layout.fcose')}</option>
								<option value="cose">{$t('graph.layout.cose')}</option>
								<option value="grid">{$t('graph.layout.grid')}</option>
								<option value="circle">{$t('graph.layout.circle')}</option>
							</select>
						</label>
						<button class="graph-link-button graph-link-button--icon" type="button" on:click={handleRestoreDefaults}>
							<span class="action-icon action-icon--refresh" aria-hidden="true"></span>
							{$t('graph.controls.restoreDefaults')}
						</button>
					</div>
				</details>

				<div class="graph-control-status">
					<div>
						<span>{$t('graph.controls.visibleNodes')}</span>
						<strong>{visibleNodes}</strong>
					</div>
					<div>
						<span>{$t('graph.controls.visibleEdges')}</span>
						<strong>{visibleEdges}</strong>
					</div>
					<div>
						<span>{$t('graph.controls.loadState')}</span>
						<strong>{supportLoading ? $t('graph.status.loading') : $t('graph.status.loaded')}</strong>
					</div>
				</div>
			</aside>

			<section class="graph-page-card graph-canvas-panel" aria-labelledby="graph-canvas-title">
				<div class="graph-canvas-toolbar">
					<div>
						<h2 id="graph-canvas-title">{$t('graph.canvas.title')}</h2>
						<p>{$t('graph.canvas.meta', { nodes: visibleNodes, edges: visibleEdges })}</p>
					</div>
					<div class="graph-canvas-actions">
						<button class="graph-tool-button" type="button" title={$t('graph.canvas.fit')} on:click={() => fitGraph(true)}>
							<span class="action-icon action-icon--fit" aria-hidden="true"></span>
						</button>
						<button class="graph-tool-button" type="button" title={$t('graph.canvas.zoomIn')} on:click={() => zoomGraph(1.18)}>
							<span class="action-icon action-icon--plus" aria-hidden="true"></span>
						</button>
						<button class="graph-tool-button" type="button" title={$t('graph.canvas.zoomOut')} on:click={() => zoomGraph(0.84)}>
							<span class="action-icon action-icon--minus" aria-hidden="true"></span>
						</button>
						<button class="graph-tool-button" type="button" title={$t('graph.canvas.center')} on:click={centerGraph}>
							<span class="action-icon action-icon--target" aria-hidden="true"></span>
						</button>
						<button class="graph-tool-button graph-tool-button--text" type="button" on:click={handleLayout}>
							{$t('graph.canvas.layout')}
						</button>
					</div>
				</div>

				<div class="graph-legend" aria-label={$t('graph.legend.label')}>
					{#each availableNodeTypes as type}
						<span
							class="graph-legend-item"
							style={`--node-color:${getNodeTypeStyle(type).color};`}
						>
							<i aria-hidden="true"></i>
							{nodeTypeLabel(type)}
						</span>
					{/each}
				</div>

				<div class="graph-canvas-stage">
					<div class="graph-cytoscape" bind:this={graphContainer} aria-label={$t('graph.canvas.ariaLabel')}></div>
					{#if loading}
						<div class="graph-canvas-state graph-canvas-state--loading">
							<div class="graph-spinner" aria-hidden="true"></div>
							<span>{$t('graph.status.loading')}</span>
						</div>
					{:else if !visibleNodes}
						<div class="graph-canvas-state">
							<span>{$t('graph.canvas.empty')}</span>
						</div>
					{/if}
					{#if hoverPreview}
						<div
							class="graph-hover-card"
							style={`left:${hoverPreview.left}px;top:${hoverPreview.top}px;`}
							aria-hidden="true"
						>
							<strong>{hoverPreview.label}</strong>
							<span>{hoverPreview.typeLabel}</span>
						</div>
					{/if}
				</div>
			</section>

			<aside class="graph-page-card graph-detail-panel" aria-labelledby="graph-detail-title">
				<div class="graph-panel-header">
					<h2 id="graph-detail-title">{$t('graph.detail.title')}</h2>
					{#if selectedObject}
						<button class="graph-link-button" type="button" on:click={() => clearSelection()}>
							{$t('graph.detail.clear')}
						</button>
					{/if}
				</div>

				{#if selectedNode}
					<div class="graph-selected-summary">
						<span
							class="graph-selected-icon"
							style={`--node-color:${getNodeTypeStyle(selectedNode.type).color};--node-bg:${getNodeTypeStyle(selectedNode.type).background};`}
							aria-hidden="true"
						></span>
						<div>
							<h3>{selectedNode.displayLabel}</h3>
							<span class="graph-chip">{nodeTypeLabel(selectedNode.type ?? 'unknown')}</span>
						</div>
					</div>

					<div class="graph-detail-stat-grid">
						<div>
							<span>{$t('graph.detail.relatedEvidence')}</span>
							<strong>{selectedStats.evidence}</strong>
						</div>
						<div>
							<span>{$t('graph.detail.relatedComparisons')}</span>
							<strong>{selectedStats.comparison}</strong>
						</div>
						<div>
							<span>{$t('graph.detail.relatedDocuments')}</span>
							<strong>{selectedStats.documents}</strong>
						</div>
					</div>

					<div class="graph-detail-section">
						<h4>{$t('graph.detail.description')}</h4>
						{#if detailLoading}
							<p class="graph-muted">{$t('graph.detail.loading')}</p>
						{:else if detailError}
							<p class="graph-error-text">{detailError}</p>
						{:else}
							<p>{selectedNodeDescription()}</p>
						{/if}
					</div>

					<div class="graph-detail-section">
						<h4>{$t('graph.detail.relatedContent')}</h4>
						<ul class="graph-compact-list">
							<li>
								<span>{$t('graph.linked.evidence')}</span>
								<strong>{selectedStats.evidence}</strong>
							</li>
							<li>
								<span>{$t('graph.linked.comparison')}</span>
								<strong>{selectedStats.comparison}</strong>
							</li>
							<li>
								<span>{$t('graph.linked.documents')}</span>
								<strong>{selectedStats.documents}</strong>
							</li>
						</ul>
					</div>

					<div class="graph-detail-section">
						<h4>{$t('graph.detail.commonRelations')}</h4>
						{#if commonRelations.length}
							<ul class="graph-relation-list">
								{#each commonRelations as relation}
									<li>
										<span>{relation.label}</span>
										<strong>{relation.target}</strong>
									</li>
								{/each}
							</ul>
						{:else}
							<p class="graph-muted">{$t('graph.detail.noRelations')}</p>
						{/if}
					</div>

					<div class="graph-detail-actions">
						<a class="graph-button graph-button--primary" href={selectedActionHref('evidence') ?? '#'}>
							{$t('graph.detail.viewEvidence')}
						</a>
						<a class="graph-button graph-button--ghost" href={selectedActionHref('comparison') ?? '#'}>
							{$t('graph.detail.openComparison')}
						</a>
						{#if selectedActionHref('source')}
							<a class="graph-button graph-button--ghost" href={selectedActionHref('source') ?? '#'}>
								{$t('graph.detail.locateSource')}
							</a>
						{/if}
						<button
							class="graph-button graph-button--ghost"
							type="button"
							disabled={expandingNeighborhood}
							on:click={() => void expandNeighborhood(selectedNode?.id ?? '')}
						>
							{expandingNeighborhood ? $t('graph.detail.expanding') : $t('graph.detail.expand')}
						</button>
					</div>
				{:else if selectedEdge}
					<div class="graph-edge-detail">
						<h3>{selectedEdge.sourceLabel} -&gt; {selectedEdge.targetLabel}</h3>
						<div class="graph-detail-kv">
							<span>{$t('graph.detail.relationshipType')}</span>
							<strong>{selectedEdge.relationLabel || formatMachineText(selectedEdge.edge_description)}</strong>
						</div>
						<div class="graph-detail-kv">
							<span>{$t('graph.detail.confidence')}</span>
							<strong>{formatConfidence(selectedEdge.weight)}</strong>
						</div>
						<div class="graph-detail-kv">
							<span>{$t('graph.detail.sourceEvidence')}</span>
							<strong>{selectedStats.evidence}</strong>
						</div>
						<div class="graph-detail-section">
							<h4>{$t('graph.detail.originalEvidence')}</h4>
							<p>
								{linkedEvidence[0]?.claim_text ||
									getEdgeTypeStyle(selectedEdge.edge_description).label ||
									$t('graph.detail.noEvidenceQuote')}
							</p>
						</div>
						<div class="graph-detail-actions">
							{#if selectedActionHref('source')}
								<a class="graph-button graph-button--primary" href={selectedActionHref('source') ?? '#'}>
									{$t('graph.detail.viewSource')}
								</a>
							{/if}
							<a class="graph-button graph-button--ghost" href={selectedActionHref('evidence') ?? '#'}>
								{$t('graph.detail.viewEvidence')}
							</a>
							<a class="graph-button graph-button--ghost" href={selectedActionHref('comparison') ?? '#'}>
								{$t('graph.detail.openComparison')}
							</a>
						</div>
					</div>
				{:else}
					<div class="graph-detail-empty">
						<span class="graph-icon graph-icon--network" aria-hidden="true"></span>
						<p>{$t('graph.detail.empty')}</p>
					</div>
				{/if}
			</aside>
		</div>

		<section class="graph-page-card graph-linked-panel" aria-labelledby="graph-linked-title">
			<div class="graph-linked-header">
				<div>
					<h2 id="graph-linked-title">
						{#if selectedDetail}
							{$t('graph.linked.relatedTitle', { name: selectedDetail.title })}
						{:else}
							{$t('graph.linked.title')}
						{/if}
					</h2>
					<p>
						{#if selectedObject}
							{$t('graph.linked.stats', {
								evidence: selectedStats.evidence,
								comparison: selectedStats.comparison,
								documents: selectedStats.documents
							})}
						{:else}
							{$t('graph.linked.empty')}
						{/if}
					</p>
				</div>
				{#if selectedObject}
					<a class="graph-link-button" href={selectedActionHref('comparison') ?? `/collections/${collectionId}/comparisons`}>
						{$t('graph.linked.viewAll')}
					</a>
				{/if}
			</div>

			<div class="graph-linked-tabs" role="tablist" aria-label={$t('graph.linked.title')}>
				<button
					type="button"
					role="tab"
					class:active={linkedTab === 'evidence'}
					on:click={() => (linkedTab = 'evidence')}
				>
					{$t('graph.linked.evidence')} ({selectedStats.evidence})
				</button>
				<button
					type="button"
					role="tab"
					class:active={linkedTab === 'comparison'}
					on:click={() => (linkedTab = 'comparison')}
				>
					{$t('graph.linked.comparison')} ({selectedStats.comparison})
				</button>
				<button
					type="button"
					role="tab"
					class:active={linkedTab === 'documents'}
					on:click={() => (linkedTab = 'documents')}
				>
					{$t('graph.linked.documents')} ({selectedStats.documents})
				</button>
			</div>

			{#if !selectedObject}
				<div class="graph-linked-empty">{$t('graph.linked.empty')}</div>
			{:else if linkedTab === 'evidence'}
				{#if linkedEvidence.length}
					<div class="graph-linked-grid graph-linked-grid--evidence">
						{#each linkedEvidence.slice(0, 6) as item}
							<article class="graph-linked-card">
								<div class="graph-linked-card__header">
									<h3>{item.claim_type || $t('graph.linked.evidence')}</h3>
									<span class="graph-chip graph-chip--success">{item.traceability_status}</span>
								</div>
								<p>{item.claim_text || $t('graph.linked.noSummary')}</p>
								<div class="graph-linked-card__meta">
									<span>{item.source_document_title || item.document_id || '--'}</span>
								</div>
								<div class="graph-linked-card__actions">
									<a class="graph-link-button" href={`/collections/${collectionId}/evidence`}>
										{$t('graph.linked.viewEvidence')}
									</a>
									{#if evidenceSourceHref(item)}
										<a class="graph-link-button" href={evidenceSourceHref(item) ?? '#'}>
											{$t('graph.linked.viewSource')}
										</a>
									{/if}
								</div>
							</article>
						{/each}
					</div>
				{:else}
					<div class="graph-linked-empty">{$t('graph.linked.noEvidence')}</div>
				{/if}
			{:else if linkedTab === 'comparison'}
				{#if linkedComparisons.length}
					<div class="graph-linked-grid graph-linked-grid--comparison">
						{#each linkedComparisons.slice(0, 6) as item}
							<article class="graph-linked-card">
								<div class="graph-linked-card__header">
									<h3>{item.display.result_summary || item.row_id}</h3>
									<span class="graph-chip">{formatMachineText(item.assessment.comparability_status)}</span>
								</div>
								<p>
									{formatGraphLabel(item.display.material_system_normalized)} /
									{formatGraphLabel(item.display.property_normalized)}
								</p>
								{#if item.uncertainty.missing_critical_context.length}
									<div class="graph-missing-chip-row">
										{#each item.uncertainty.missing_critical_context.slice(0, 3) as missing}
											<span>{formatMachineText(missing)}</span>
										{/each}
									</div>
								{/if}
								<div class="graph-linked-card__actions">
									<a class="graph-link-button" href={comparisonHref(item)}>
										{$t('graph.linked.openComparison')}
									</a>
									{#if comparisonSourceHref(item)}
										<a class="graph-link-button" href={comparisonSourceHref(item) ?? '#'}>
											{$t('graph.linked.viewSource')}
										</a>
									{/if}
								</div>
							</article>
						{/each}
					</div>
				{:else}
					<div class="graph-linked-empty">{$t('graph.linked.noComparisons')}</div>
				{/if}
			{:else if linkedDocuments.length}
				<div class="graph-linked-grid graph-linked-grid--documents">
					{#each linkedDocuments.slice(0, 6) as item}
						<article class="graph-linked-card">
							<div class="graph-linked-card__header">
								<h3>{item.title || item.source_filename || item.document_id}</h3>
								<span class="graph-chip">{formatMachineText(item.doc_type)}</span>
							</div>
							<p>{item.source_filename || item.document_id}</p>
							<div class="graph-linked-card__meta">
								<span>{formatMachineText(item.processing_status ?? 'unknown')}</span>
								{#if item.page_count}
									<span>{$t('graph.linked.pages', { count: item.page_count })}</span>
								{/if}
							</div>
							<div class="graph-linked-card__actions">
								<a class="graph-link-button" href={documentHref(item)}>
									{$t('graph.linked.viewDocument')}
								</a>
							</div>
						</article>
					{/each}
				</div>
			{:else}
				<div class="graph-linked-empty">{$t('graph.linked.noDocuments')}</div>
			{/if}
		</section>
	{/if}
</section>

<style>
	.graph-page-shell {
		width: 100%;
		max-width: 1440px;
		margin: 0 auto;
		display: grid;
		gap: 16px;
	}

	.graph-page-card {
		min-width: 0;
		border: 1px solid #e6ebf2;
		border-radius: 16px;
		background: #ffffff;
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.graph-header-card {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 20px;
		padding: 22px 24px;
	}

	.graph-header-identity {
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 18px;
	}

	.graph-header-icon,
	.graph-empty-state__icon {
		width: 72px;
		height: 72px;
		flex: 0 0 auto;
		display: grid;
		place-items: center;
		border-radius: 999px;
		background: #eff6ff;
		color: #2563eb;
	}

	.graph-header-copy {
		min-width: 0;
		display: grid;
		gap: 8px;
	}

	.graph-header-copy h1 {
		margin: 0;
		color: #0f172a;
		font-size: 30px;
		font-weight: 700;
		line-height: 38px;
		letter-spacing: 0;
	}

	.graph-header-copy p {
		margin: 0;
		color: #64748b;
		font-size: 15px;
		line-height: 22px;
	}

	.graph-meta-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 10px;
		color: #64748b;
		font-size: 13px;
		line-height: 20px;
	}

	.graph-meta-item,
	.graph-status-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.graph-status-badge {
		min-height: 24px;
		padding: 2px 9px;
		border-radius: 999px;
		font-size: 12px;
		font-weight: 700;
	}

	.graph-status-badge--success {
		color: #15803d;
		background: #dcfce7;
	}

	.graph-status-badge--warning {
		color: #b45309;
		background: #fef3c7;
	}

	.graph-status-badge--neutral {
		color: #64748b;
		background: #f1f5f9;
	}

	.graph-header-actions,
	.graph-canvas-actions,
	.graph-empty-state__actions,
	.graph-detail-actions,
	.graph-linked-card__actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 10px;
	}

	.graph-button,
	.graph-tool-button,
	.graph-link-button,
	.graph-search-button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		min-height: 40px;
		border: 1px solid transparent;
		border-radius: 10px;
		font-size: 14px;
		font-weight: 700;
		line-height: 20px;
		cursor: pointer;
		transition:
			background 0.18s ease,
			border-color 0.18s ease,
			box-shadow 0.18s ease,
			color 0.18s ease;
	}

	.graph-button {
		padding: 0 16px;
	}

	.graph-button--primary {
		color: #ffffff;
		background: #2563eb;
		box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
	}

	.graph-button--primary:hover {
		background: #1d4ed8;
	}

	.graph-button--ghost,
	.graph-tool-button,
	.graph-search-button {
		color: #0f172a;
		border-color: #d7e0ec;
		background: #ffffff;
	}

	.graph-button--ghost:hover,
	.graph-tool-button:hover,
	.graph-search-button:hover {
		background: #f8fafc;
		border-color: #cbd5e1;
	}

	.graph-button:disabled,
	.graph-tool-button:disabled,
	.graph-search-button:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}

	.graph-tool-button {
		width: 40px;
		padding: 0;
	}

	.graph-tool-button--text {
		width: auto;
		padding: 0 12px;
	}

	.graph-link-button {
		min-height: 0;
		padding: 0;
		border: 0;
		background: transparent;
		color: #2563eb;
		font-size: 13px;
	}

	.graph-link-button:hover {
		color: #1d4ed8;
	}

	.graph-link-button--icon {
		gap: 6px;
	}

	.graph-export-menu {
		position: relative;
	}

	.graph-export-dropdown {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		z-index: 8;
		min-width: 180px;
		display: grid;
		gap: 4px;
		padding: 6px;
		border: 1px solid #e6ebf2;
		border-radius: 12px;
		background: #ffffff;
		box-shadow: 0 12px 28px rgba(15, 23, 42, 0.12);
	}

	.graph-export-dropdown button {
		width: 100%;
		padding: 9px 10px;
		border: 0;
		border-radius: 9px;
		background: transparent;
		color: #0f172a;
		text-align: left;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}

	.graph-export-dropdown button:hover {
		background: #eff6ff;
	}

	.graph-export-dropdown button:disabled {
		color: #94a3b8;
		cursor: not-allowed;
	}

	.graph-inline-status {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 10px 12px;
		border: 1px solid #bfdbfe;
		border-radius: 12px;
		background: #eff6ff;
		color: #1d4ed8;
		font-size: 13px;
		font-weight: 600;
	}

	.graph-inline-status--error {
		border-color: #fecaca;
		background: #fee2e2;
		color: #b91c1c;
	}

	.graph-empty-state {
		min-height: 420px;
		display: grid;
		place-items: center;
		justify-items: center;
		gap: 14px;
		padding: 48px 24px;
		text-align: center;
	}

	.graph-empty-state h2 {
		margin: 0;
		color: #0f172a;
		font-size: 22px;
		line-height: 30px;
	}

	.graph-empty-state p {
		max-width: 560px;
		margin: 0;
		color: #64748b;
		font-size: 14px;
		line-height: 22px;
	}

	.graph-empty-state__note {
		color: #94a3b8;
	}

	.graph-workspace {
		display: grid;
		grid-template-columns: 260px minmax(0, 1fr) 320px;
		gap: 16px;
		align-items: stretch;
	}

	.graph-controls-panel,
	.graph-detail-panel {
		align-self: start;
		display: grid;
		gap: 16px;
		padding: 16px;
	}

	.graph-detail-panel {
		position: sticky;
		top: 96px;
		max-height: calc(100vh - 128px);
		overflow: auto;
	}

	.graph-panel-header,
	.graph-canvas-toolbar,
	.graph-linked-header,
	.graph-linked-card__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}

	.graph-panel-header h2,
	.graph-canvas-toolbar h2,
	.graph-linked-header h2 {
		margin: 0;
		color: #0f172a;
		font-size: 16px;
		font-weight: 700;
		line-height: 24px;
	}

	.graph-canvas-toolbar p,
	.graph-linked-header p {
		margin: 2px 0 0;
		color: #64748b;
		font-size: 13px;
		line-height: 20px;
	}

	.graph-control-group {
		display: grid;
		gap: 8px;
	}

	.graph-control-label,
	.graph-node-type-fieldset legend,
	.graph-control-field span {
		color: #64748b;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.graph-node-type-fieldset {
		min-width: 0;
		margin: 0;
		padding: 0;
		border: 0;
	}

	.graph-search-control {
		height: 40px;
		display: grid;
		grid-template-columns: minmax(0, 1fr) 40px;
		border: 1px solid #d7e0ec;
		border-radius: 10px;
		background: #ffffff;
		overflow: hidden;
	}

	.graph-search-control:focus-within {
		border-color: #2563eb;
		box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
	}

	.graph-search-control .graph-input {
		border: 0;
		border-radius: 0;
	}

	.graph-search-button {
		width: 40px;
		height: 40px;
		border-width: 0 0 0 1px;
		border-color: #e6ebf2;
		border-radius: 0;
	}

	.graph-input {
		width: 100%;
		height: 40px;
		padding: 0 11px;
		border: 1px solid #d7e0ec;
		border-radius: 10px;
		background: #ffffff;
		color: #0f172a;
		font-size: 14px;
		line-height: 22px;
	}

	.graph-input::placeholder {
		color: #94a3b8;
	}

	.graph-input:focus {
		border-color: #2563eb;
		box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
		outline: 0;
	}

	.graph-node-type-list {
		display: grid;
		gap: 8px;
	}

	.graph-node-type-row {
		display: grid;
		grid-template-columns: 24px minmax(0, 1fr) auto auto;
		align-items: center;
		gap: 8px;
		min-height: 36px;
		padding: 6px 8px;
		border: 1px solid #e6ebf2;
		border-radius: 10px;
		background: #ffffff;
		color: #0f172a;
		font-size: 13px;
		cursor: pointer;
	}

	.graph-node-type-icon,
	.graph-selected-icon {
		display: inline-grid;
		place-items: center;
		border-radius: 8px;
		background: var(--node-bg);
		border: 1px solid color-mix(in srgb, var(--node-color) 45%, transparent);
	}

	.graph-node-type-icon {
		width: 24px;
		height: 24px;
	}

	.graph-node-type-icon::after,
	.graph-selected-icon::after {
		content: '';
		width: 8px;
		height: 8px;
		border-radius: 999px;
		background: var(--node-color);
	}

	.graph-node-type-label {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.graph-node-type-count {
		min-width: 26px;
		padding: 1px 7px;
		border-radius: 999px;
		background: #f1f5f9;
		color: #64748b;
		text-align: center;
		font-size: 12px;
		font-weight: 700;
	}

	.graph-node-type-row input {
		width: 16px;
		height: 16px;
		accent-color: #2563eb;
	}

	.graph-advanced-settings {
		border-top: 1px solid #e6ebf2;
		padding-top: 12px;
	}

	.graph-advanced-settings summary {
		color: #0f172a;
		font-size: 14px;
		font-weight: 700;
		cursor: pointer;
	}

	.graph-advanced-grid {
		display: grid;
		gap: 10px;
		margin-top: 12px;
	}

	.graph-control-field {
		display: grid;
		gap: 6px;
	}

	.graph-control-status {
		display: grid;
		gap: 8px;
		padding: 12px;
		border-radius: 12px;
		background: #fbfdff;
		border: 1px solid #e6ebf2;
	}

	.graph-control-status div {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		color: #64748b;
		font-size: 13px;
	}

	.graph-control-status strong {
		color: #0f172a;
	}

	.graph-canvas-panel {
		min-height: 680px;
		display: grid;
		grid-template-rows: auto auto minmax(0, 1fr);
		gap: 12px;
		padding: 16px;
		box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
	}

	.graph-legend {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 10px;
		padding: 0 2px;
	}

	.graph-legend-item {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		color: #64748b;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.graph-legend-item i {
		width: 9px;
		height: 9px;
		border-radius: 999px;
		background: var(--node-color);
	}

	.graph-canvas-stage {
		position: relative;
		min-height: 600px;
		border: 1px solid #e6ebf2;
		border-radius: 16px;
		background:
			linear-gradient(rgba(37, 99, 235, 0.035) 1px, transparent 1px),
			linear-gradient(90deg, rgba(37, 99, 235, 0.035) 1px, transparent 1px), #fbfdff;
		background-size: 22px 22px;
		overflow: hidden;
	}

	.graph-cytoscape {
		position: absolute;
		inset: 0;
	}

	.graph-canvas-state {
		position: absolute;
		inset: 0;
		z-index: 2;
		display: grid;
		place-items: center;
		gap: 10px;
		padding: 24px;
		background: rgba(251, 253, 255, 0.72);
		color: #64748b;
		font-size: 14px;
		text-align: center;
		pointer-events: none;
	}

	.graph-canvas-state--loading {
		background: rgba(251, 253, 255, 0.84);
	}

	.graph-spinner {
		width: 28px;
		height: 28px;
		border: 3px solid #dbeafe;
		border-top-color: #2563eb;
		border-radius: 999px;
		animation: graph-spin 0.9s linear infinite;
	}

	.graph-hover-card {
		position: absolute;
		z-index: 4;
		max-width: 220px;
		display: grid;
		gap: 4px;
		padding: 10px 12px;
		border: 1px solid #d7e0ec;
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.96);
		box-shadow: 0 12px 28px rgba(15, 23, 42, 0.14);
		pointer-events: none;
	}

	.graph-hover-card strong {
		color: #0f172a;
		font-size: 13px;
		line-height: 18px;
	}

	.graph-hover-card span {
		color: #64748b;
		font-size: 12px;
		line-height: 18px;
	}

	.graph-selected-summary {
		display: grid;
		grid-template-columns: 46px minmax(0, 1fr);
		gap: 12px;
		align-items: center;
	}

	.graph-selected-icon {
		width: 46px;
		height: 46px;
		border-radius: 12px;
	}

	.graph-selected-summary h3,
	.graph-edge-detail h3,
	.graph-linked-card h3 {
		margin: 0;
		color: #0f172a;
		font-size: 17px;
		font-weight: 700;
		line-height: 24px;
		letter-spacing: 0;
	}

	.graph-chip {
		display: inline-flex;
		width: max-content;
		align-items: center;
		min-height: 22px;
		padding: 2px 8px;
		border-radius: 999px;
		background: #eff6ff;
		color: #2563eb;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.graph-chip--success {
		color: #15803d;
		background: #dcfce7;
	}

	.graph-detail-stat-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 8px;
	}

	.graph-detail-stat-grid div {
		display: grid;
		gap: 4px;
		padding: 10px;
		border: 1px solid #e6ebf2;
		border-radius: 10px;
		background: #fbfdff;
		text-align: center;
	}

	.graph-detail-stat-grid span,
	.graph-detail-kv span {
		color: #64748b;
		font-size: 12px;
		line-height: 18px;
	}

	.graph-detail-stat-grid strong,
	.graph-detail-kv strong {
		color: #0f172a;
		font-size: 18px;
		line-height: 24px;
	}

	.graph-detail-section {
		display: grid;
		gap: 8px;
	}

	.graph-detail-section h4 {
		margin: 0;
		color: #0f172a;
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
	}

	.graph-detail-section p,
	.graph-edge-detail p,
	.graph-linked-card p {
		margin: 0;
		color: #64748b;
		font-size: 14px;
		line-height: 22px;
	}

	.graph-compact-list,
	.graph-relation-list {
		display: grid;
		gap: 6px;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.graph-compact-list li,
	.graph-relation-list li,
	.graph-detail-kv {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 10px;
		padding: 8px 10px;
		border-radius: 10px;
		background: #f8fafc;
	}

	.graph-compact-list span,
	.graph-relation-list span {
		color: #64748b;
		font-size: 13px;
	}

	.graph-compact-list strong,
	.graph-relation-list strong {
		min-width: 0;
		color: #0f172a;
		font-size: 13px;
		text-align: right;
		overflow-wrap: anywhere;
	}

	.graph-edge-detail {
		display: grid;
		gap: 14px;
	}

	.graph-detail-empty,
	.graph-linked-empty {
		display: grid;
		place-items: center;
		gap: 12px;
		min-height: 220px;
		padding: 24px;
		border: 1px dashed #d7e0ec;
		border-radius: 14px;
		background: #fbfdff;
		color: #64748b;
		text-align: center;
	}

	.graph-detail-empty p,
	.graph-linked-empty {
		margin: 0;
		font-size: 14px;
		line-height: 22px;
	}

	.graph-linked-panel {
		display: grid;
		gap: 14px;
		padding: 20px;
	}

	.graph-linked-tabs {
		display: flex;
		align-items: center;
		gap: 20px;
		border-bottom: 1px solid #e6ebf2;
	}

	.graph-linked-tabs button {
		position: relative;
		min-height: 42px;
		padding: 0 2px;
		border: 0;
		background: transparent;
		color: #64748b;
		font-size: 14px;
		font-weight: 700;
		cursor: pointer;
	}

	.graph-linked-tabs button.active {
		color: #2563eb;
	}

	.graph-linked-tabs button.active::after {
		content: '';
		position: absolute;
		left: 0;
		right: 0;
		bottom: -1px;
		height: 2px;
		border-radius: 999px;
		background: #2563eb;
	}

	.graph-linked-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
		gap: 12px;
	}

	.graph-linked-card {
		min-width: 0;
		display: grid;
		align-content: start;
		gap: 10px;
		padding: 14px;
		border: 1px solid #e6ebf2;
		border-radius: 12px;
		background: #ffffff;
	}

	.graph-linked-card h3 {
		font-size: 14px;
		line-height: 20px;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.graph-linked-card__meta,
	.graph-missing-chip-row {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.graph-linked-card__meta span,
	.graph-missing-chip-row span {
		display: inline-flex;
		min-height: 22px;
		align-items: center;
		padding: 2px 8px;
		border-radius: 999px;
		background: #f1f5f9;
		color: #64748b;
		font-size: 12px;
		font-weight: 700;
	}

	.graph-muted {
		color: #94a3b8;
	}

	.graph-error-text {
		color: #b91c1c;
	}

	.graph-icon--network,
	.meta-icon,
	.action-icon {
		position: relative;
		display: inline-block;
		flex: 0 0 auto;
	}

	.graph-icon--network {
		width: 34px;
		height: 34px;
	}

	.graph-icon--network::before,
	.graph-icon--network::after {
		content: '';
		position: absolute;
		inset: 6px;
		border: 3px solid currentColor;
		border-radius: 999px;
		clip-path: polygon(0 38%, 42% 38%, 42% 0, 58% 0, 58% 38%, 100% 38%, 100% 58%, 58% 58%, 58% 100%, 42% 100%, 42% 58%, 0 58%);
	}

	.graph-icon--network::after {
		inset: 0;
		border-width: 2px;
		opacity: 0.42;
		transform: rotate(45deg);
	}

	.meta-icon {
		width: 13px;
		height: 13px;
	}

	.meta-icon--node {
		border: 2px solid #64748b;
		border-radius: 999px;
	}

	.meta-icon--edge::before {
		content: '';
		position: absolute;
		left: 1px;
		right: 1px;
		top: 6px;
		height: 2px;
		background: #64748b;
		transform: rotate(-20deg);
	}

	.meta-icon--type {
		border: 2px solid #64748b;
		border-radius: 4px;
	}

	.meta-icon--status {
		border: 2px solid currentColor;
		border-radius: 999px;
	}

	.meta-icon--status::after {
		content: '';
		position: absolute;
		left: 3px;
		top: 3px;
		width: 5px;
		height: 3px;
		border: solid currentColor;
		border-width: 0 0 2px 2px;
		transform: rotate(-45deg);
	}

	.action-icon {
		width: 15px;
		height: 15px;
		color: currentColor;
	}

	.action-icon--refresh {
		border: 2px solid currentColor;
		border-right-color: transparent;
		border-radius: 999px;
	}

	.action-icon--target {
		border: 2px solid currentColor;
		border-radius: 999px;
	}

	.action-icon--target::after {
		content: '';
		position: absolute;
		inset: 4px;
		border-radius: 999px;
		background: currentColor;
	}

	.action-icon--export {
		border: 2px solid currentColor;
		border-radius: 3px;
	}

	.action-icon--search {
		border: 2px solid currentColor;
		border-radius: 999px;
	}

	.action-icon--search::after {
		content: '';
		position: absolute;
		right: -4px;
		bottom: -2px;
		width: 6px;
		height: 2px;
		border-radius: 999px;
		background: currentColor;
		transform: rotate(45deg);
	}

	.action-icon--fit {
		border: 2px solid currentColor;
		border-radius: 4px;
	}

	.action-icon--plus::before,
	.action-icon--plus::after,
	.action-icon--minus::before {
		content: '';
		position: absolute;
		left: 2px;
		right: 2px;
		top: 6px;
		height: 2px;
		background: currentColor;
	}

	.action-icon--plus::after {
		top: 2px;
		bottom: 2px;
		left: 6px;
		right: auto;
		width: 2px;
		height: auto;
	}

	@keyframes graph-spin {
		to {
			transform: rotate(360deg);
		}
	}

	@media (max-width: 1240px) {
		.graph-workspace {
			grid-template-columns: 260px minmax(0, 1fr);
		}

		.graph-detail-panel {
			grid-column: 1 / -1;
			position: static;
			max-height: none;
		}
	}

	@media (max-width: 920px) {
		.graph-header-card {
			align-items: flex-start;
			flex-direction: column;
		}

		.graph-header-actions {
			width: 100%;
		}

		.graph-header-actions .graph-button,
		.graph-export-menu {
			flex: 1 1 auto;
		}

		.graph-export-menu > .graph-button {
			width: 100%;
		}

		.graph-workspace {
			grid-template-columns: 1fr;
		}

		.graph-controls-panel {
			grid-template-columns: repeat(2, minmax(0, 1fr));
			align-items: start;
		}

		.graph-panel-header,
		.graph-control-status {
			grid-column: 1 / -1;
		}

		.graph-canvas-panel {
			min-height: auto;
		}

		.graph-canvas-stage {
			min-height: 500px;
		}
	}

	@media (max-width: 640px) {
		.graph-page-shell {
			gap: 12px;
		}

		.graph-header-card,
		.graph-linked-panel {
			padding: 16px;
		}

		.graph-header-identity {
			align-items: flex-start;
		}

		.graph-header-icon {
			width: 56px;
			height: 56px;
		}

		.graph-header-copy h1 {
			font-size: 26px;
			line-height: 34px;
		}

		.graph-controls-panel {
			grid-template-columns: 1fr;
		}

		.graph-panel-header,
		.graph-control-status {
			grid-column: auto;
		}

		.graph-canvas-toolbar,
		.graph-linked-header {
			display: grid;
		}

		.graph-canvas-actions {
			justify-content: flex-start;
		}

		.graph-canvas-stage {
			min-height: 420px;
		}

		.graph-detail-stat-grid {
			grid-template-columns: 1fr;
		}

		.graph-linked-tabs {
			overflow-x: auto;
		}
	}

	:global(:root[data-theme='dark']) .graph-page-card,
	:global(:root[data-theme='dark']) .graph-export-dropdown,
	:global(:root[data-theme='dark']) .graph-linked-card {
		border-color: rgba(122, 145, 185, 0.2);
		background: rgba(16, 26, 44, 0.94);
	}

	:global(:root[data-theme='dark']) .graph-header-copy h1,
	:global(:root[data-theme='dark']) .graph-panel-header h2,
	:global(:root[data-theme='dark']) .graph-canvas-toolbar h2,
	:global(:root[data-theme='dark']) .graph-linked-header h2,
	:global(:root[data-theme='dark']) .graph-selected-summary h3,
	:global(:root[data-theme='dark']) .graph-edge-detail h3,
	:global(:root[data-theme='dark']) .graph-linked-card h3,
	:global(:root[data-theme='dark']) .graph-detail-section h4,
	:global(:root[data-theme='dark']) .graph-control-status strong,
	:global(:root[data-theme='dark']) .graph-detail-stat-grid strong,
	:global(:root[data-theme='dark']) .graph-detail-kv strong,
	:global(:root[data-theme='dark']) .graph-compact-list strong,
	:global(:root[data-theme='dark']) .graph-relation-list strong {
		color: #e6efff;
	}

	:global(:root[data-theme='dark']) .graph-header-copy p,
	:global(:root[data-theme='dark']) .graph-meta-row,
	:global(:root[data-theme='dark']) .graph-canvas-toolbar p,
	:global(:root[data-theme='dark']) .graph-linked-header p,
	:global(:root[data-theme='dark']) .graph-detail-section p,
	:global(:root[data-theme='dark']) .graph-edge-detail p,
	:global(:root[data-theme='dark']) .graph-linked-card p,
	:global(:root[data-theme='dark']) .graph-control-label,
	:global(:root[data-theme='dark']) .graph-node-type-fieldset legend,
	:global(:root[data-theme='dark']) .graph-control-field span {
		color: #a7b6cf;
	}

	:global(:root[data-theme='dark']) .graph-button--ghost,
	:global(:root[data-theme='dark']) .graph-tool-button,
	:global(:root[data-theme='dark']) .graph-search-button,
	:global(:root[data-theme='dark']) .graph-input,
	:global(:root[data-theme='dark']) .graph-search-control,
	:global(:root[data-theme='dark']) .graph-node-type-row,
	:global(:root[data-theme='dark']) .graph-control-status,
	:global(:root[data-theme='dark']) .graph-detail-stat-grid div,
	:global(:root[data-theme='dark']) .graph-compact-list li,
	:global(:root[data-theme='dark']) .graph-relation-list li,
	:global(:root[data-theme='dark']) .graph-detail-kv,
	:global(:root[data-theme='dark']) .graph-detail-empty,
	:global(:root[data-theme='dark']) .graph-linked-empty {
		border-color: rgba(122, 145, 185, 0.24);
		background: rgba(12, 20, 34, 0.8);
		color: #e6efff;
	}

	:global(:root[data-theme='dark']) .graph-canvas-stage {
		border-color: rgba(122, 145, 185, 0.2);
		background:
			linear-gradient(rgba(75, 139, 255, 0.06) 1px, transparent 1px),
			linear-gradient(90deg, rgba(75, 139, 255, 0.06) 1px, transparent 1px), #101a2c;
		background-size: 22px 22px;
	}

	:global(:root[data-theme='dark']) .graph-canvas-state {
		background: rgba(16, 26, 44, 0.78);
		color: #a7b6cf;
	}

	:global(:root[data-theme='dark']) .graph-hover-card {
		border-color: rgba(122, 145, 185, 0.3);
		background: rgba(16, 26, 44, 0.96);
	}

	:global(:root[data-theme='dark']) .graph-hover-card strong {
		color: #e6efff;
	}
</style>
