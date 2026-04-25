import type {
	Core,
	EdgeSingular,
	ElementDefinition,
	LayoutOptions,
	NodeSingular,
	StylesheetJson
} from 'cytoscape';
import { buildApiUrl, requestJson, throwApiError } from './api';
import type { ComparisonRow } from './comparisons';
import type { DocumentProfile } from './documents';
import type { EvidenceCard } from './evidence';

export type GraphNode = {
	id: string;
	label: string;
	type?: string | null;
	degree?: number | null;
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

export type GraphNeighborsResponse = {
	collection_id: string;
	center_node_id: string;
	nodes: GraphNode[];
	edges: GraphEdge[];
	truncated: boolean;
};

export type GraphNodeRef =
	| { kind: 'document'; resourceId: string }
	| { kind: 'evidence'; resourceId: string }
	| { kind: 'comparison'; resourceId: string }
	| { kind: 'material'; resourceId: string }
	| { kind: 'property'; resourceId: string }
	| { kind: 'test_condition'; resourceId: string }
	| { kind: 'baseline'; resourceId: string }
	| { kind: 'unknown'; resourceId: string };

export type GraphQuery = {
	maxNodes?: number;
	minWeight?: number;
};

export type GraphNodeType =
	| 'document'
	| 'evidence'
	| 'comparison'
	| 'material'
	| 'property'
	| 'test_condition'
	| 'baseline'
	| 'variant'
	| 'process'
	| 'unknown';

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

export type GraphPosition = { x: number; y: number };

export type GraphSelectedNode = GraphNode & {
	kind?: GraphNodeRef['kind'] | GraphNodeType;
	resourceId?: string | null;
	displayLabel?: string;
};

export type GraphSelectedEdge = GraphEdge & {
	sourceLabel?: string;
	targetLabel?: string;
};

export type GraphSelectedObject =
	| { kind: 'node'; node: GraphSelectedNode }
	| { kind: 'edge'; edge: GraphSelectedEdge };

export type GraphSelectedObjectDetail = {
	kind: 'node' | 'edge';
	id: string;
	title: string;
	type: string;
	description: string;
	confidence: number | null;
	sourceLabel?: string;
	targetLabel?: string;
};

export type CytoscapeThemeName = 'light' | 'dark';

export const graphNodeTypeOrder: GraphNodeType[] = [
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

const nodeTypeStyles: Record<GraphNodeType, GraphTypeStyle> = {
	document: {
		color: '#2563EB',
		background: '#EFF6FF',
		shape: 'round-rectangle',
		icon: 'document'
	},
	evidence: {
		color: '#10B981',
		background: '#ECFDF5',
		shape: 'round-rectangle',
		icon: 'evidence'
	},
	comparison: {
		color: '#F97316',
		background: '#FFF7ED',
		shape: 'diamond',
		icon: 'comparison'
	},
	material: {
		color: '#8B5CF6',
		background: '#F5F3FF',
		shape: 'round-rectangle',
		icon: 'material'
	},
	property: {
		color: '#06B6D4',
		background: '#ECFEFF',
		shape: 'ellipse',
		icon: 'property'
	},
	test_condition: {
		color: '#64748B',
		background: '#F1F5F9',
		shape: 'round-rectangle',
		icon: 'test-condition'
	},
	baseline: {
		color: '#84CC16',
		background: '#F7FEE7',
		shape: 'round-rectangle',
		icon: 'baseline'
	},
	variant: {
		color: '#A855F7',
		background: '#FAF5FF',
		shape: 'round-rectangle',
		icon: 'variant'
	},
	process: {
		color: '#0EA5E9',
		background: '#F0F9FF',
		shape: 'round-rectangle',
		icon: 'process'
	},
	unknown: {
		color: '#94A3B8',
		background: '#F8FAFC',
		shape: 'round-rectangle',
		icon: 'unknown'
	}
};

const edgeTypeLabels: Record<string, string> = {
	document_to_evidence: 'source',
	evidence_to_comparison: 'supports',
	comparison_to_material: 'material',
	comparison_to_property: 'property',
	comparison_to_test_condition: 'test condition',
	comparison_to_baseline: 'baseline',
	evidence_supports: 'supports',
	related_to: 'related',
	missing_context: 'missing context',
	comparison_depends_on: 'depends on'
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

	if (!resourceId) {
		return { kind: 'unknown', resourceId: '' };
	}

	if (prefix === 'doc') return { kind: 'document', resourceId };
	if (prefix === 'evi') return { kind: 'evidence', resourceId };
	if (prefix === 'cmp') return { kind: 'comparison', resourceId };
	if (prefix === 'mat') return { kind: 'material', resourceId };
	if (prefix === 'prop') return { kind: 'property', resourceId };
	if (prefix === 'tc') return { kind: 'test_condition', resourceId };
	if (prefix === 'base') return { kind: 'baseline', resourceId };
	return { kind: 'unknown', resourceId };
}

export function formatGraphLabel(value: string) {
	const normalized = value.replace(/_+/g, ' ').replace(/\s+/g, ' ').trim();

	if (!normalized) return '--';

	return normalized.replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

export function buildGraphMeta(graph: GraphResponse | null | undefined): GraphMeta {
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

export function buildNodeTypeCounts(graph: GraphResponse | null | undefined) {
	const counts: Record<string, number> = {};
	for (const type of graphNodeTypeOrder) {
		counts[type] = 0;
	}
	for (const node of graph?.nodes ?? []) {
		const type = normalizeGraphNodeType(node.type);
		counts[type] = (counts[type] ?? 0) + 1;
	}
	return counts;
}

export function filterGraphElements(graph: GraphResponse | null | undefined, filters: GraphFilters) {
	const graphNodes = graph?.nodes ?? [];
	const graphEdges = graph?.edges ?? [];
	const query = normalizeSearch(filters.search);
	const visibleTypes = filters.visibleNodeTypes ?? {};
	const maxNodes = Math.max(1, Math.trunc(filters.maxNodes ?? (graphNodes.length || 1)));
	const minWeight = Math.max(0, Number(filters.minWeight ?? 0));

	const nodes = graphNodes
		.filter((node) => {
			const type = normalizeGraphNodeType(node.type);
			const typeVisible = visibleTypes[type] ?? true;
			if (!typeVisible) return false;
			if (!query) return true;
			return normalizeSearch(`${node.id} ${node.label} ${type}`).includes(query);
		})
		.slice(0, maxNodes);
	const nodeIds = new Set(nodes.map((node) => node.id));
	const edges = graphEdges.filter(
		(edge) =>
			nodeIds.has(edge.source) &&
			nodeIds.has(edge.target) &&
			(typeof edge.weight === 'number' && Number.isFinite(edge.weight)
				? edge.weight >= minWeight
				: minWeight <= 0)
	);

	return { nodes, edges };
}

export function getNodeTypeStyle(type?: string | null): GraphTypeStyle {
	return nodeTypeStyles[normalizeGraphNodeType(type)];
}

export function getEdgeTypeStyle(type?: string | null): GraphEdgeStyle {
	const normalized = String(type ?? '').trim();
	const dashed = normalized === 'missing_context' || normalized === 'comparison_depends_on';
	return {
		color: '#CBD5E1',
		selectedColor: '#2563EB',
		lineStyle: dashed ? 'dashed' : 'solid',
		label: edgeTypeLabels[normalized] ?? normalized.replace(/[_-]+/g, ' ').trim() ?? 'related'
	};
}

export function getNodeLabel(node: GraphNode | GraphSelectedNode, limit = 34) {
	const label = formatGraphLabel(node.label || node.id);
	if (label.length <= limit) return label;
	return `${label.slice(0, Math.max(1, limit - 1)).trimEnd()}...`;
}

export function getNodeDescription(node: GraphNode | GraphSelectedNode) {
	const type = normalizeGraphNodeType(node.type);
	const label = getNodeLabel(node, 72);
	if (type === 'document') return `${label} is a source document in this collection.`;
	if (type === 'evidence') return `${label} is an extracted evidence claim linked to source text.`;
	if (type === 'comparison') return `${label} is a comparison row connecting evidence and review context.`;
	if (type === 'material') return `${label} is a material or material system shared by collection results.`;
	if (type === 'property') return `${label} is a measured or reported property.`;
	if (type === 'test_condition') return `${label} is an experimental or evaluation condition.`;
	if (type === 'baseline') return `${label} is a baseline or control reference.`;
	if (type === 'process') return `${label} is a method or process context extracted from the collection.`;
	if (type === 'variant') return `${label} is a variant or experimental branch.`;
	return `${label} is a graph object in this collection.`;
}

export function getSelectedObjectDetail(
	selected: GraphSelectedObject | null | undefined
): GraphSelectedObjectDetail | null {
	if (!selected) return null;
	if (selected.kind === 'node') {
		const node = selected.node;
		return {
			kind: 'node',
			id: node.id,
			title: node.displayLabel || getNodeLabel(node, 72),
			type: normalizeGraphNodeType(node.type),
			description: getNodeDescription(node),
			confidence: null
		};
	}

	return {
		kind: 'edge',
		id: selected.edge.id,
		title: `${selected.edge.sourceLabel ?? selected.edge.source} -> ${
			selected.edge.targetLabel ?? selected.edge.target
		}`,
		type: selected.edge.edge_description || 'related_to',
		description: selected.edge.edge_description || 'related_to',
		confidence: typeof selected.edge.weight === 'number' ? selected.edge.weight : null,
		sourceLabel: selected.edge.sourceLabel,
		targetLabel: selected.edge.targetLabel
	};
}

export function getLinkedEvidence(
	selected: GraphSelectedObject | null | undefined,
	evidenceItems: EvidenceCard[]
) {
	if (!selected) return [];
	return evidenceItems.filter((item) => selectedMatchesEvidence(selected, item));
}

export function getLinkedComparisons(
	selected: GraphSelectedObject | null | undefined,
	comparisonItems: ComparisonRow[]
) {
	if (!selected) return [];
	return comparisonItems.filter((item) => selectedMatchesComparison(selected, item));
}

export function getLinkedDocuments(
	selected: GraphSelectedObject | null | undefined,
	documents: DocumentProfile[]
) {
	if (!selected) return [];
	return documents.filter((item) => selectedMatchesDocument(selected, item));
}

export function buildCytoscapeElements(
	graph: Pick<GraphResponse, 'nodes' | 'edges'>,
	options: { previousPositions?: Map<string, GraphPosition> } = {}
): ElementDefinition[] {
	const nodeIds = new Set(graph.nodes.map((node) => node.id));
	const nodeMap = new Map(graph.nodes.map((node) => [node.id, node]));
	const elements: ElementDefinition[] = [];

	for (const [index, node] of graph.nodes.entries()) {
		const style = getNodeTypeStyle(node.type);
		const type = normalizeGraphNodeType(node.type);
		const label = getNodeLabel(node, type === 'comparison' ? 26 : 30);
		const degree = node.degree ?? 0;
		const width = type === 'comparison' ? 102 : type === 'property' ? 78 : 112;
		const height = type === 'comparison' ? 72 : type === 'property' ? 78 : 58;
		elements.push({
			group: 'nodes',
			data: {
				id: node.id,
				label,
				fullLabel: formatGraphLabel(node.label || node.id),
				displayLabel: formatGraphLabel(node.label || node.id),
				entityType: type,
				typeColor: style.color,
				typeBackground: style.background,
				typeShape: style.shape,
				typeIcon: style.icon,
				degree,
				width: width + Math.min(Math.max(degree, 0), 6) * 4,
				height: height + Math.min(Math.max(degree, 0), 6) * 2,
				textMaxWidth: width - 18,
				fontSize: type === 'document' || type === 'comparison' ? 10 : 11,
				layoutWeight: type === 'comparison' || type === 'material' ? 18000 : 12000
			},
			position:
				options.previousPositions?.get(node.id) ?? fallbackPosition(node.id, index, graph.nodes.length)
		});
	}

	for (const edge of graph.edges) {
		if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
		const style = getEdgeTypeStyle(edge.edge_description);
		const sourceType = normalizeGraphNodeType(nodeMap.get(edge.source)?.type);
		const targetType = normalizeGraphNodeType(nodeMap.get(edge.target)?.type);
		const hubEdge =
			sourceType === 'comparison' ||
			targetType === 'comparison' ||
			sourceType === 'material' ||
			targetType === 'material';
		elements.push({
			group: 'edges',
			data: {
				id: edge.id || `${edge.source}-${edge.target}`,
				source: edge.source,
				target: edge.target,
				edgeDescription: edge.edge_description ?? 'related_to',
				label: style.label,
				weight: edge.weight ?? null,
				width: edgeWidth(edge.weight),
				lineStyle: style.lineStyle,
				idealLength: hubEdge ? 150 : 120
			}
		});
	}

	return elements;
}

export function buildCytoscapeStyles(theme: CytoscapeThemeName = 'light') {
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
			selector: 'node.search-match',
			style: {
				'border-width': 3,
				'border-color': '#2563EB',
				'shadow-blur': 16,
				'shadow-color': 'rgba(37, 99, 235, 0.22)',
				'shadow-opacity': 1,
				'shadow-offset-x': 0,
				'shadow-offset-y': 4
			}
		},
		{
			selector: 'node.is-selected',
			style: {
				'border-width': 4,
				'border-color': '#2563EB',
				'shadow-blur': 24,
				'shadow-color': 'rgba(37, 99, 235, 0.28)',
				'shadow-opacity': 1,
				'shadow-offset-x': 0,
				'shadow-offset-y': 6
			}
		},
		{
			selector: 'node.is-neighbor',
			style: {
				'border-width': 3,
				'border-color': '#94A3B8'
			}
		},
		{
			selector: 'node.is-dimmed',
			style: {
				opacity: 0.28
			}
		},
		{
			selector: '.is-hidden',
			style: {
				display: 'none'
			}
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
				'text-background-shape': 'roundrectangle',
				'min-zoomed-font-size': 5,
				'overlay-opacity': 0
			}
		},
		{
			selector: 'edge.is-selected',
			style: {
				'line-color': '#2563EB',
				'target-arrow-color': '#2563EB',
				width: 4
			}
		},
		{
			selector: 'edge.is-neighbor',
			style: {
				'line-color': '#94A3B8',
				'target-arrow-color': '#94A3B8',
				width: 3
			}
		},
		{
			selector: 'edge.is-dimmed',
			style: {
				opacity: 0.22
			}
		}
	] as unknown as StylesheetJson;
}

export async function runGraphLayout(cy: Core, layoutName = 'fcose') {
	if (cy.nodes().length < 2) return;
	const name = layoutName === 'grid' || layoutName === 'circle' || layoutName === 'cose' ? layoutName : 'fcose';

	await new Promise<void>((resolve) => {
		const options =
			name === 'fcose'
				? ({
						name: 'fcose',
						quality: 'proof',
						randomize: false,
						animate: false,
						fit: false,
						padding: 72,
						nodeDimensionsIncludeLabels: true,
						uniformNodeDimensions: false,
						nodeSeparation: 100,
						nodeRepulsion: (node: NodeSingular) => Number(node.data('layoutWeight') ?? 12000),
						idealEdgeLength: (edge: EdgeSingular) => Number(edge.data('idealLength') ?? 132),
						edgeElasticity: 0.22,
						gravity: 0.14,
						gravityRange: 3.8,
						numIter: 3200,
						tile: true,
						tilingPaddingVertical: 24,
						tilingPaddingHorizontal: 24
					} as unknown as LayoutOptions)
				: ({
						name,
						animate: false,
						fit: false,
						padding: 72
					} as LayoutOptions);
		const layout = cy.layout(options);
		layout.on('layoutstop', () => resolve());
		layout.run();
	});
}

export function exportGraphPng(cy: Core, filename = 'graph.png') {
	const url = cy.png({ full: true, scale: 2, bg: '#FFFFFF' });
	const anchor = document.createElement('a');
	anchor.href = String(url);
	anchor.download = filename;
	anchor.click();
}

export async function downloadGraphml(collectionId: string, query: GraphQuery = {}) {
	const response = await fetch(buildCollectionGraphmlUrl(collectionId, query));
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
	return fileName;
}

function normalizeGraphNodeType(type?: string | null): GraphNodeType {
	const normalized = String(type ?? '').trim();
	return graphNodeTypeOrder.includes(normalized as GraphNodeType)
		? (normalized as GraphNodeType)
		: 'unknown';
}

function normalizeSearch(value?: string | null) {
	return String(value ?? '')
		.toLowerCase()
		.replace(/\s+/g, ' ')
		.trim();
}

function edgeWidth(weight?: number | null) {
	if (typeof weight !== 'number' || !Number.isFinite(weight)) return 1.8;
	return Math.max(1.4, Math.min(4.5, 1.6 + weight * 1.8));
}

function stableHash(value: string) {
	let hash = 0;
	for (const char of value) {
		hash = (hash * 31 + char.charCodeAt(0)) | 0;
	}
	return Math.abs(hash);
}

function fallbackPosition(nodeId: string, index: number, total: number): GraphPosition {
	const hash = stableHash(nodeId);
	const angle = (2 * Math.PI * index) / Math.max(total, 1);
	const ring = 140 + (hash % 7) * 22;
	return {
		x: Math.cos(angle) * ring + ((hash >> 4) % 90) - 45,
		y: Math.sin(angle) * ring + ((hash >> 10) % 90) - 45
	};
}

function selectedMatchesEvidence(selected: GraphSelectedObject, evidence: EvidenceCard): boolean {
	if (selected.kind === 'edge') {
		return (
			selectedMatchesEvidence(nodeSelection(selected.edge.source), evidence) ||
			selectedMatchesEvidence(nodeSelection(selected.edge.target), evidence)
		);
	}

	const ref = parseSelectedNode(selected.node);
	if (ref.kind === 'evidence') return evidence.evidence_id === ref.resourceId;
	if (ref.kind === 'document') return evidence.document_id === ref.resourceId;
	if (ref.kind === 'comparison') return false;

	const needle = normalizeSearch(selected.node.label || selected.node.displayLabel || ref.resourceId);
	if (!needle) return false;
	return normalizeSearch(
		[
			evidence.claim_text,
			evidence.material_system,
			evidence.claim_type,
			evidence.materials.join(' '),
			evidence.parameters.join(' '),
			evidence.tags.join(' '),
			evidence.condition_context.process.join(' '),
			evidence.condition_context.baseline.join(' '),
			evidence.condition_context.test.join(' ')
		].join(' ')
	).includes(needle);
}

function selectedMatchesComparison(
	selected: GraphSelectedObject,
	comparison: ComparisonRow
): boolean {
	if (selected.kind === 'edge') {
		return (
			selectedMatchesComparison(nodeSelection(selected.edge.source), comparison) ||
			selectedMatchesComparison(nodeSelection(selected.edge.target), comparison)
		);
	}

	const ref = parseSelectedNode(selected.node);
	if (ref.kind === 'comparison') {
		return comparison.row_id === ref.resourceId || comparison.result_id === ref.resourceId;
	}
	if (ref.kind === 'document') return comparison.source_document_id === ref.resourceId;
	if (ref.kind === 'evidence') {
		return comparison.evidence_bundle.supporting_evidence_ids.includes(ref.resourceId);
	}

	const label = selected.node.label || selected.node.displayLabel || ref.resourceId;
	return nodeLabelMatchesComparison(ref.kind, label, comparison);
}

function selectedMatchesDocument(selected: GraphSelectedObject, document: DocumentProfile): boolean {
	if (selected.kind === 'edge') {
		return (
			selectedMatchesDocument(nodeSelection(selected.edge.source), document) ||
			selectedMatchesDocument(nodeSelection(selected.edge.target), document)
		);
	}

	const ref = parseSelectedNode(selected.node);
	if (ref.kind === 'document') return document.document_id === ref.resourceId;
	const needle = normalizeSearch(selected.node.label || selected.node.displayLabel || ref.resourceId);
	if (!needle) return false;
	return normalizeSearch(`${document.title ?? ''} ${document.source_filename ?? ''}`).includes(needle);
}

function parseSelectedNode(node: GraphSelectedNode): GraphNodeRef {
	const parsed = parseGraphNodeId(node.id);
	if (parsed.kind !== 'unknown') return parsed;
	const resourceId = String(node.resourceId ?? node.id).trim();
	const kind = normalizeGraphNodeType(node.kind ?? node.type);
	if (
		kind === 'document' ||
		kind === 'evidence' ||
		kind === 'comparison' ||
		kind === 'material' ||
		kind === 'property' ||
		kind === 'test_condition' ||
		kind === 'baseline'
	) {
		return { kind, resourceId };
	}
	return { kind: 'unknown', resourceId };
}

function nodeSelection(nodeId: string): GraphSelectedObject {
	return {
		kind: 'node',
		node: {
			id: nodeId,
			label: parseGraphNodeId(nodeId).resourceId || nodeId,
			type: parseGraphNodeId(nodeId).kind
		}
	};
}

function nodeLabelMatchesComparison(
	kind: GraphNodeRef['kind'],
	label: string,
	comparison: ComparisonRow
) {
	const value = normalizeSearch(label);
	if (!value) return false;
	if (kind === 'material') {
		return normalizeSearch(comparison.display.material_system_normalized) === value;
	}
	if (kind === 'property') {
		return normalizeSearch(comparison.display.property_normalized) === value;
	}
	if (kind === 'test_condition') {
		return normalizeSearch(comparison.display.test_condition_normalized) === value;
	}
	if (kind === 'baseline') {
		return normalizeSearch(comparison.display.baseline_normalized) === value;
	}
	return normalizeSearch(
		[
			comparison.display.material_system_normalized,
			comparison.display.process_normalized,
			comparison.display.property_normalized,
			comparison.display.result_summary,
			comparison.display.test_condition_normalized,
			comparison.display.baseline_normalized
		].join(' ')
	).includes(value);
}
