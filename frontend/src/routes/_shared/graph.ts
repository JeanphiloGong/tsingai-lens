import type {
	Core,
	EdgeSingular,
	ElementDefinition,
	LayoutOptions,
	NodeSingular,
	StylesheetJson
} from 'cytoscape';
import { buildApiUrl, requestJson, throwApiError } from './api';

export type GraphPosition = { x: number; y: number };
export type GraphNodeDetailRow = Record<string, unknown>;

export type GraphNode = {
	id: string;
	label: string;
	type?: string | null;
	role?: string | null;
	summary?: string | null;
	metrics?: Record<string, unknown>;
	detail_rows?: GraphNodeDetailRow[];
	objective_id?: string | null;
	degree?: number | null;
	position?: GraphPosition | null;
};

export type GraphEdge = {
	id: string;
	source: string;
	target: string;
	weight?: number | null;
	edge_description?: string | null;
};

export type GraphResponse = {
	collection_id: string;
	nodes: GraphNode[];
	edges: GraphEdge[];
	truncated: boolean;
};

export type GraphNeighborsResponse = GraphResponse & {
	center_node_id: string;
};

export type GraphNodeType =
	| 'objective'
	| 'document'
	| 'evidence'
	| 'comparison'
	| 'material'
	| 'property'
	| 'test_condition'
	| 'baseline'
	| 'unknown';

export type GraphNodeRef = {
	kind: GraphNodeType;
	resourceId: string;
};

export type GraphQuery = {
	maxNodes?: number;
	minWeight?: number;
};

export type GraphFilters = {
	search?: string;
	visibleNodeTypes?: Partial<Record<GraphNodeType | string, boolean>>;
	maxNodes?: number;
	minWeight?: number;
};

export type GraphMeta = {
	nodeCount: number;
	edgeCount: number;
	nodeTypeCount: number;
	truncated: boolean;
};

export type GraphTypeStyle = {
	color: string;
	background: string;
	shape: string;
	icon: string;
};

export type GraphEdgeStyle = {
	color: string;
	selectedColor: string;
	lineStyle: 'solid' | 'dashed';
	label: string;
};

export const graphNodeTypeOrder: GraphNodeType[] = [
	'objective',
	'document',
	'evidence',
	'comparison',
	'material',
	'property',
	'test_condition',
	'baseline'
];

const nodeTypeStyles: Record<GraphNodeType, GraphTypeStyle> = {
	objective: {
		color: '#1D4ED8',
		background: '#DBEAFE',
		shape: 'round-rectangle',
		icon: 'objective'
	},
	document: {
		color: '#475569',
		background: '#F1F5F9',
		shape: 'round-rectangle',
		icon: 'document'
	},
	evidence: {
		color: '#047857',
		background: '#D1FAE5',
		shape: 'round-rectangle',
		icon: 'evidence'
	},
	comparison: {
		color: '#B45309',
		background: '#FEF3C7',
		shape: 'round-rectangle',
		icon: 'comparison'
	},
	material: {
		color: '#7C3AED',
		background: '#EDE9FE',
		shape: 'ellipse',
		icon: 'material'
	},
	property: {
		color: '#BE123C',
		background: '#FFE4E6',
		shape: 'ellipse',
		icon: 'property'
	},
	test_condition: {
		color: '#0369A1',
		background: '#E0F2FE',
		shape: 'round-rectangle',
		icon: 'test-condition'
	},
	baseline: {
		color: '#4D7C0F',
		background: '#ECFCCB',
		shape: 'round-rectangle',
		icon: 'baseline'
	},
	unknown: {
		color: '#64748B',
		background: '#F8FAFC',
		shape: 'round-rectangle',
		icon: 'unknown'
	}
};

const edgeTypeLabels: Record<string, string> = {
	document_to_evidence: 'source evidence',
	evidence_to_comparison: 'supports comparison',
	comparison_to_material: 'material',
	comparison_to_property: 'property',
	comparison_to_test_condition: 'test condition',
	comparison_to_baseline: 'baseline',
	related_to: 'related'
};

function buildQuery(query: GraphQuery = {}) {
	const params = new URLSearchParams();
	params.set('max_nodes', String(query.maxNodes ?? 200));
	params.set('min_weight', String(query.minWeight ?? 0));
	return params.toString();
}

export async function fetchCollectionGraph(collectionId: string, query: GraphQuery = {}) {
	return (await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/graph?${buildQuery(query)}`,
		{ method: 'GET' }
	)) as GraphResponse;
}

export function buildCollectionGraphmlUrl(collectionId: string, query: GraphQuery = {}) {
	return buildApiUrl(
		`/collections/${encodeURIComponent(collectionId)}/graphml?${buildQuery(query)}`
	);
}

export async function fetchCollectionGraphNeighbors(collectionId: string, nodeId: string) {
	return (await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/graph/nodes/${encodeURIComponent(nodeId)}/neighbors`,
		{ method: 'GET' }
	)) as GraphNeighborsResponse;
}

export function parseGraphNodeId(nodeId: string): GraphNodeRef {
	const [prefix, ...rest] = nodeId.split(':');
	const resourceId = rest.join(':').trim();
	const kindByPrefix: Record<string, GraphNodeType> = {
		obj: 'objective',
		doc: 'document',
		evi: 'evidence',
		cmp: 'comparison',
		mat: 'material',
		prop: 'property',
		tc: 'test_condition',
		base: 'baseline'
	};
	return {
		kind: resourceId ? (kindByPrefix[prefix] ?? 'unknown') : 'unknown',
		resourceId
	};
}

export function formatGraphLabel(value: string) {
	const normalized = value.replace(/_+/g, ' ').replace(/\s+/g, ' ').trim();
	if (!normalized) return '--';
	return normalized.replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

export function buildGraphMeta(
	graph:
		| (Pick<GraphResponse, 'nodes' | 'edges'> & Partial<Pick<GraphResponse, 'truncated'>>)
		| null
		| undefined
): GraphMeta {
	const nodes = graph?.nodes ?? [];
	const nodeTypes = new Set(
		nodes.map((node) => normalizeGraphNodeType(node.type)).filter((type) => type !== 'unknown')
	);
	return {
		nodeCount: nodes.length,
		edgeCount: graph?.edges.length ?? 0,
		nodeTypeCount: nodeTypes.size,
		truncated: Boolean(graph?.truncated)
	};
}

export function buildNodeTypeCounts(graph: Pick<GraphResponse, 'nodes'> | null | undefined) {
	const counts: Record<GraphNodeType, number> = Object.fromEntries(
		[...graphNodeTypeOrder, 'unknown'].map((type) => [type, 0])
	) as Record<GraphNodeType, number>;
	for (const node of graph?.nodes ?? []) {
		const type = normalizeGraphNodeType(node.type);
		counts[type] += 1;
	}
	return counts;
}

export function filterGraphElements(
	graph: Pick<GraphResponse, 'nodes' | 'edges'> | null | undefined,
	filters: GraphFilters
) {
	const query = normalizeSearch(filters.search);
	const visibleTypes = filters.visibleNodeTypes ?? {};
	const maxNodes = Math.max(1, Math.trunc(filters.maxNodes ?? graph?.nodes.length ?? 1));
	const minWeight = Math.max(0, Number(filters.minWeight ?? 0));
	const nodes = (graph?.nodes ?? [])
		.filter((node) => {
			const type = normalizeGraphNodeType(node.type);
			if (visibleTypes[type] === false) return false;
			return !query || normalizeSearch(`${node.id} ${node.label} ${type}`).includes(query);
		})
		.slice(0, maxNodes);
	const nodeIds = new Set(nodes.map((node) => node.id));
	const edges = (graph?.edges ?? []).filter(
		(edge) =>
			nodeIds.has(edge.source) &&
			nodeIds.has(edge.target) &&
			(typeof edge.weight === 'number' ? edge.weight >= minWeight : minWeight === 0)
	);
	return { nodes, edges };
}

export function buildMaterialCentricGraph(
	graph: GraphResponse | null | undefined,
	options: { maxNodes?: number } = {}
): GraphResponse {
	if (!graph) {
		return { collection_id: '', nodes: [], edges: [], truncated: false };
	}
	const maxNodes = Math.max(1, Math.trunc(options.maxNodes ?? 200));
	const materials = graph.nodes
		.filter((node) => normalizeGraphNodeType(node.type) === 'material')
		.sort((left, right) => Number(right.degree ?? 0) - Number(left.degree ?? 0));
	if (!materials.length) {
		const filtered = filterGraphElements(graph, { maxNodes });
		return {
			...graph,
			...filtered,
			truncated: graph.truncated || filtered.nodes.length < graph.nodes.length
		};
	}

	const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
	const adjacency = buildAdjacency(graph.edges);
	const selected = new Set<string>();
	const queue = materials.map((node) => node.id);
	while (queue.length && selected.size < maxNodes) {
		const nodeId = queue.shift();
		if (!nodeId || selected.has(nodeId) || !nodeById.has(nodeId)) continue;
		selected.add(nodeId);
		for (const neighbor of adjacency.get(nodeId) ?? []) {
			if (!selected.has(neighbor)) queue.push(neighbor);
		}
	}
	const nodes = graph.nodes.filter((node) => selected.has(node.id));
	const edges = graph.edges.filter(
		(edge) => selected.has(edge.source) && selected.has(edge.target)
	);
	return {
		collection_id: graph.collection_id,
		nodes,
		edges,
		truncated: graph.truncated || nodes.length < graph.nodes.length
	};
}

export function getNodeTypeStyle(type?: string | null): GraphTypeStyle {
	return nodeTypeStyles[normalizeGraphNodeType(type)];
}

export function getEdgeTypeStyle(type?: string | null): GraphEdgeStyle {
	const description = String(type || 'related_to');
	return {
		color: '#94A3B8',
		selectedColor: '#2563EB',
		lineStyle: description === 'related_to' ? 'dashed' : 'solid',
		label: edgeTypeLabels[description] ?? formatGraphLabel(description)
	};
}

export function getNodeLabel(node: GraphNode, limit = 34) {
	return truncateGraphLabel(formatGraphLabel(node.label || node.id), limit);
}

export function getGraphNodeDisplayLabel(node: GraphNode, limit = 34) {
	return getNodeLabel(node, limit);
}

export function getNodeDescription(node: GraphNode) {
	const label = formatGraphLabel(node.label || node.id);
	const descriptions: Record<GraphNodeType, string> = {
		objective: `${label} is a confirmed or candidate research objective.`,
		document: `${label} is a source paper in this collection.`,
		evidence: `${label} is source evidence used by a comparison.`,
		comparison: `${label} is a structured cross-paper comparison row.`,
		material: `${label} is a normalized material system.`,
		property: `${label} is a normalized measured property.`,
		test_condition: `${label} is a normalized test condition.`,
		baseline: `${label} is a comparison baseline.`,
		unknown: `${label} is a graph object in this collection.`
	};
	return node.summary || descriptions[normalizeGraphNodeType(node.type)];
}

export function buildCytoscapeElements(
	graph: Pick<GraphResponse, 'nodes' | 'edges'>,
	options: { previousPositions?: Map<string, GraphPosition> } = {}
): ElementDefinition[] {
	const nodeIds = new Set(graph.nodes.map((node) => node.id));
	const elements: ElementDefinition[] = graph.nodes.map((node, index) => {
		const type = normalizeGraphNodeType(node.type);
		const style = getNodeTypeStyle(type);
		const fullLabel = formatGraphLabel(node.label || node.id);
		const displayLabel = getGraphNodeDisplayLabel(node, type === 'objective' ? 58 : 34);
		const degree = Number(node.degree ?? 0);
		const dimensions = graphNodeDimensions(type, displayLabel, degree);
		return {
			group: 'nodes',
			data: {
				id: node.id,
				label: displayLabel,
				fullLabel,
				displayLabel,
				entityType: type,
				role: node.role ?? type,
				typeColor: style.color,
				typeBackground: style.background,
				typeShape: style.shape,
				typeIcon: style.icon,
				degree,
				summary: node.summary ?? null,
				metrics: node.metrics ?? {},
				detailRows: node.detail_rows ?? [],
				objectiveId: node.objective_id ?? null,
				width: dimensions.width,
				height: dimensions.height,
				textMaxWidth: dimensions.textMaxWidth,
				fontSize: dimensions.fontSize,
				layoutWeight: dimensions.layoutWeight
			},
			position:
				options.previousPositions?.get(node.id) ??
				node.position ??
				fallbackPosition(node.id, index, graph.nodes.length)
		};
	});

	for (const edge of graph.edges) {
		if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
		const style = getEdgeTypeStyle(edge.edge_description);
		const fullLabel = style.label;
		elements.push({
			group: 'edges',
			data: {
				id: edge.id,
				source: edge.source,
				target: edge.target,
				weight: edge.weight ?? null,
				edgeDescription: edge.edge_description ?? 'related_to',
				label: fullLabel,
				fullLabel,
				lineStyle: style.lineStyle,
				width: edgeWidth(edge.weight),
				idealLength: 132
			}
		});
	}
	return elements;
}

export function buildCytoscapeStyles(theme: 'light' | 'dark' = 'light') {
	const textColor = theme === 'dark' ? '#E6EFFF' : '#0F172A';
	const mutedText = theme === 'dark' ? '#A7B6CF' : '#475569';
	const canvasBg = theme === 'dark' ? '#101A2C' : '#FFFFFF';
	const edgeColor = theme === 'dark' ? 'rgba(148, 163, 184, 0.45)' : '#CBD5E1';
	return [
		{
			selector: 'node',
			style: {
				shape: 'data(typeShape)',
				width: 'data(width)',
				height: 'data(height)',
				'background-color': 'data(typeBackground)',
				'border-width': 2,
				'border-color': 'data(typeColor)',
				label: 'data(label)',
				color: textColor,
				'font-size': 'data(fontSize)',
				'font-weight': 700,
				'text-wrap': 'wrap',
				'text-max-width': 'data(textMaxWidth)',
				'text-valign': 'center',
				'text-halign': 'center',
				'text-justification': 'center',
				'overlay-opacity': 0,
				'underlay-opacity': 0
			}
		},
		{
			selector: 'node.search-match, node.is-selected',
			style: {
				'border-width': 4,
				'border-color': '#2563EB',
				'underlay-color': 'rgba(37, 99, 235, 0.22)',
				'underlay-opacity': 1,
				'underlay-padding': 10
			}
		},
		{
			selector: 'node.is-neighbor',
			style: { 'border-width': 3, 'border-color': '#94A3B8' }
		},
		{
			selector: 'node.is-dimmed, edge.is-dimmed',
			style: { opacity: 0.24 }
		},
		{
			selector: '.is-hidden',
			style: { display: 'none' }
		},
		{
			selector: 'edge',
			style: {
				width: 'data(width)',
				'curve-style': 'bezier',
				'line-color': edgeColor,
				'target-arrow-color': edgeColor,
				'target-arrow-shape': 'triangle',
				'line-style': 'data(lineStyle)',
				'arrow-scale': 0.9,
				label: 'data(label)',
				color: mutedText,
				'font-size': 9,
				'text-rotation': 'autorotate',
				'text-background-color': canvasBg,
				'text-background-opacity': 0.92,
				'text-background-padding': 2,
				'overlay-opacity': 0
			}
		},
		{
			selector: 'edge.is-selected, edge.is-neighbor',
			style: { 'line-color': '#2563EB', 'target-arrow-color': '#2563EB', width: 4 }
		}
	] as unknown as StylesheetJson;
}

export async function runGraphLayout(cy: Core, layoutName = 'layered') {
	const nodeCount = cy.nodes().length;
	if (nodeCount < 2) return;
	const requestedName = ['layered', 'grid', 'circle', 'cose', 'fcose'].includes(layoutName)
		? layoutName
		: 'layered';
	const name =
		requestedName === 'layered'
			? 'breadthfirst'
			: requestedName === 'fcose' && (nodeCount <= 2 || nodeCount > 300)
				? 'grid'
				: requestedName;
	await new Promise<void>((resolve) => {
		let settled = false;
		let timeoutId: ReturnType<typeof setTimeout>;
		const finish = () => {
			if (settled) return;
			settled = true;
			clearTimeout(timeoutId);
			resolve();
		};
		const options =
			name === 'fcose'
				? ({
						name,
						quality: 'proof',
						randomize: false,
						animate: false,
						fit: false,
						nodeDimensionsIncludeLabels: true,
						nodeRepulsion: (node: NodeSingular) => Number(node.data('layoutWeight') ?? 12000),
						idealEdgeLength: (edge: EdgeSingular) => Number(edge.data('idealLength') ?? 132)
					} as unknown as LayoutOptions)
				: ({
						name,
						animate: false,
						fit: false,
						padding: 72,
						directed: name === 'breadthfirst',
						spacingFactor: name === 'breadthfirst' ? 1.25 : undefined
					} as LayoutOptions);
		const layout = cy.layout(options);
		layout.on('layoutstop', finish);
		timeoutId = setTimeout(finish, 1600);
		layout.run();
	});
}

export function exportGraphPng(cy: Core, filename = 'graph.png') {
	const anchor = document.createElement('a');
	anchor.href = String(cy.png({ full: true, scale: 2, bg: '#FFFFFF' }));
	anchor.download = filename;
	anchor.click();
}

export async function downloadGraphml(collectionId: string, query: GraphQuery = {}) {
	const response = await fetch(buildCollectionGraphmlUrl(collectionId, query));
	if (!response.ok) await throwApiError(response);
	const blob = await response.blob();
	const disposition = response.headers.get('content-disposition') ?? '';
	const matched = disposition.match(/filename="(.+?)"/i);
	const url = URL.createObjectURL(blob);
	const anchor = document.createElement('a');
	anchor.href = url;
	const fileName = matched?.[1] ?? `graph-${collectionId}.graphml`;
	anchor.download = fileName;
	anchor.click();
	URL.revokeObjectURL(url);
	return fileName;
}

function normalizeGraphNodeType(type?: string | null): GraphNodeType {
	const normalized = String(type ?? '').trim() as GraphNodeType;
	return graphNodeTypeOrder.includes(normalized) ? normalized : 'unknown';
}

function normalizeSearch(value?: string | null) {
	return String(value ?? '')
		.trim()
		.toLowerCase();
}

function truncateGraphLabel(label: string, limit: number) {
	if (label.length <= limit) return label;
	return `${label.slice(0, Math.max(1, limit - 3)).trimEnd()}...`;
}

function graphNodeDimensions(type: GraphNodeType, label: string, degree: number) {
	const aggregate = type === 'objective' || type === 'document' || type === 'comparison';
	const width = aggregate ? Math.min(260, Math.max(132, label.length * 6.4)) : 112;
	return {
		width,
		height: aggregate ? 72 : 64,
		textMaxWidth: Math.max(84, width - 22),
		fontSize: aggregate ? 11 : 10,
		layoutWeight: 9000 + Math.min(Math.max(degree, 0), 20) * 550
	};
}

function edgeWidth(weight?: number | null) {
	if (typeof weight !== 'number' || !Number.isFinite(weight)) return 1.5;
	return Math.min(5, Math.max(1.5, 1.5 + weight * 2));
}

function buildAdjacency(edges: GraphEdge[]) {
	const adjacency = new Map<string, string[]>();
	for (const edge of edges) {
		adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
		adjacency.set(edge.target, [...(adjacency.get(edge.target) ?? []), edge.source]);
	}
	return adjacency;
}

function stableHash(value: string) {
	let hash = 2166136261;
	for (let index = 0; index < value.length; index += 1) {
		hash ^= value.charCodeAt(index);
		hash = Math.imul(hash, 16777619);
	}
	return hash >>> 0;
}

function fallbackPosition(nodeId: string, index: number, total: number): GraphPosition {
	const angle = ((index + (stableHash(nodeId) % 17) / 17) / Math.max(1, total)) * Math.PI * 2;
	const radius = Math.max(160, Math.sqrt(Math.max(total, 1)) * 72);
	return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
}
