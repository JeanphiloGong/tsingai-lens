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
	| { kind: 'objective'; resourceId: string }
	| { kind: 'logic_chain'; resourceId: string }
	| { kind: 'document'; resourceId: string }
	| { kind: 'evidence'; resourceId: string }
	| { kind: 'comparison'; resourceId: string }
	| { kind: 'measurement'; resourceId: string }
	| { kind: 'controlled_comparison'; resourceId: string }
	| { kind: 'material'; resourceId: string }
	| { kind: 'property'; resourceId: string }
	| { kind: 'process'; resourceId: string }
	| { kind: 'sample'; resourceId: string }
	| { kind: 'test_condition'; resourceId: string }
	| { kind: 'baseline'; resourceId: string }
	| { kind: 'mechanism'; resourceId: string }
	| { kind: 'characterization'; resourceId: string }
	| { kind: 'unknown'; resourceId: string };

export type GraphQuery = {
	maxNodes?: number;
	minWeight?: number;
};

export type GraphNodeType =
	| 'objective'
	| 'logic_chain'
	| 'document'
	| 'evidence'
	| 'comparison'
	| 'measurement'
	| 'controlled_comparison'
	| 'material'
	| 'property'
	| 'test_condition'
	| 'baseline'
	| 'variant'
	| 'process'
	| 'sample'
	| 'mechanism'
	| 'characterization'
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
	'objective',
	'logic_chain',
	'document',
	'measurement',
	'controlled_comparison',
	'evidence',
	'comparison',
	'material',
	'property',
	'process',
	'sample',
	'test_condition',
	'baseline',
	'variant',
	'mechanism',
	'characterization'
];

const nodeTypeStyles: Record<GraphNodeType, GraphTypeStyle> = {
	objective: {
		color: '#1D4ED8',
		background: '#DBEAFE',
		shape: 'round-rectangle',
		icon: 'objective'
	},
	logic_chain: {
		color: '#B45309',
		background: '#FEF3C7',
		shape: 'round-rectangle',
		icon: 'logic-chain'
	},
	document: {
		color: '#2563EB',
		background: '#EFF6FF',
		shape: 'round-rectangle',
		icon: 'document'
	},
	measurement: {
		color: '#0891B2',
		background: '#CFFAFE',
		shape: 'round-rectangle',
		icon: 'measurement'
	},
	controlled_comparison: {
		color: '#EA580C',
		background: '#FFEDD5',
		shape: 'diamond',
		icon: 'controlled-comparison'
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
		shape: 'round-rectangle',
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
	sample: {
		color: '#4F46E5',
		background: '#EEF2FF',
		shape: 'round-rectangle',
		icon: 'sample'
	},
	mechanism: {
		color: '#BE123C',
		background: '#FFE4E6',
		shape: 'round-rectangle',
		icon: 'mechanism'
	},
	characterization: {
		color: '#047857',
		background: '#D1FAE5',
		shape: 'round-rectangle',
		icon: 'characterization'
	},
	unknown: {
		color: '#94A3B8',
		background: '#F8FAFC',
		shape: 'round-rectangle',
		icon: 'unknown'
	}
};

const edgeTypeLabels: Record<string, string> = {
	objective_to_evidence: 'scopes',
	document_to_evidence: 'source',
	evidence_to_material: 'material',
	evidence_to_property: 'property',
	evidence_to_process: 'process',
	evidence_to_sample: 'sample',
	evidence_to_test_condition: 'test condition',
	evidence_to_baseline: 'baseline',
	objective_to_logic_chain: 'logic chain',
	document_to_logic_chain: 'paper logic',
	logic_chain_to_evidence: 'uses evidence',
	evidence_to_comparison: 'supports',
	comparison_to_material: 'material',
	comparison_to_property: 'property',
	comparison_to_test_condition: 'test condition',
	comparison_to_baseline: 'baseline',
	overview_objective_material: 'material scope',
	overview_logic_chain_material: 'evidence scope',
	overview_objective_topic: 'focus',
	overview_logic_chain_topic: 'supports',
	overview_document_material: 'studies',
	overview_material_property: 'property',
	overview_material_context: 'context',
	overview_document_topic: 'mentions',
	overview_relation: 'overview',
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

	if (prefix === 'obj') return { kind: 'objective', resourceId };
	if (prefix === 'chain') return { kind: 'logic_chain', resourceId };
	if (prefix === 'doc') return { kind: 'document', resourceId };
	if (prefix === 'evi') return { kind: 'evidence', resourceId };
	if (prefix === 'cmp') return { kind: 'comparison', resourceId };
	if (prefix === 'mat') return { kind: 'material', resourceId };
	if (prefix === 'prop') return { kind: 'property', resourceId };
	if (prefix === 'proc') return { kind: 'process', resourceId };
	if (prefix === 'sample') return { kind: 'sample', resourceId };
	if (prefix === 'tc') return { kind: 'test_condition', resourceId };
	if (prefix === 'base') return { kind: 'baseline', resourceId };
	return { kind: 'unknown', resourceId };
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
	const counts: Record<string, number> = { unknown: 0 };
	for (const type of graphNodeTypeOrder) {
		counts[type] = 0;
	}
	for (const node of graph?.nodes ?? []) {
		const type = normalizeGraphNodeType(node.type);
		counts[type] = (counts[type] ?? 0) + 1;
	}
	return counts;
}

export function filterGraphElements(
	graph: Pick<GraphResponse, 'nodes' | 'edges'> | null | undefined,
	filters: GraphFilters
) {
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

export function buildKeyChainGraph(
	graph: GraphResponse | null | undefined,
	options: { maxNodes?: number } = {}
): GraphResponse {
	const emptyGraph: GraphResponse = {
		collection_id: graph?.collection_id ?? '',
		nodes: [],
		edges: [],
		truncated: Boolean(graph?.truncated)
	};
	if (!graph) return emptyGraph;

	const maxNodes = Math.max(1, Math.trunc(options.maxNodes ?? 200));
	const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
	const adjacency = buildAdjacency(graph.edges);
	const selectedNodeIds = new Set<string>();

	function addNode(nodeId: string) {
		if (selectedNodeIds.has(nodeId)) return true;
		if (!nodeById.has(nodeId) || selectedNodeIds.size >= maxNodes) return false;
		selectedNodeIds.add(nodeId);
		return true;
	}

	for (const node of orderedKeyChainBackboneNodes(graph.nodes)) {
		if (!addNode(node.id)) break;
	}

	for (const evidenceNode of orderedKeyChainEvidenceNodes(graph.nodes, adjacency, nodeById)) {
		if (!addNode(evidenceNode.id)) break;

		for (const neighborId of orderedKeyChainNeighbors(evidenceNode.id, adjacency, nodeById)) {
			addNode(neighborId);
			if (selectedNodeIds.size >= maxNodes) break;
		}
	}

	const nodes = graph.nodes.filter((node) => selectedNodeIds.has(node.id));
	const edges = graph.edges.filter(
		(edge) => selectedNodeIds.has(edge.source) && selectedNodeIds.has(edge.target)
	);

	return {
		collection_id: graph.collection_id,
		nodes,
		edges,
		truncated: Boolean(graph.truncated || selectedNodeIds.size < graph.nodes.length)
	};
}

export function buildCollectionOverviewGraph(
	graph: GraphResponse | null | undefined
): GraphResponse {
	const emptyGraph: GraphResponse = {
		collection_id: graph?.collection_id ?? '',
		nodes: [],
		edges: [],
		truncated: Boolean(graph?.truncated)
	};
	if (!graph) return emptyGraph;

	const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
	const adjacency = buildAdjacency(graph.edges);
	const keptNodes = graph.nodes.filter((node) =>
		isCollectionOverviewNodeType(normalizeGraphNodeType(node.type))
	);
	const keptNodeIds = new Set(keptNodes.map((node) => node.id));
	const relations = new Map<
		string,
		{ source: string; target: string; edgeDescription: string; count: number }
	>();

	function addRelation(source: string, target: string, edgeDescription: string) {
		if (source === target || !keptNodeIds.has(source) || !keptNodeIds.has(target)) return;
		const key = `${source}\n${target}\n${edgeDescription}`;
		const current = relations.get(key);
		if (current) {
			current.count += 1;
			return;
		}
		relations.set(key, { source, target, edgeDescription, count: 1 });
	}

	for (const edge of graph.edges) {
		if (keptNodeIds.has(edge.source) && keptNodeIds.has(edge.target)) {
			addRelation(edge.source, edge.target, edge.edge_description ?? 'overview_relation');
		}
	}

	for (const node of graph.nodes) {
		const type = normalizeGraphNodeType(node.type);
		if (!isOverviewBridgeNodeType(type)) continue;
		const buckets = collectOverviewBuckets(node.id, nodeById, adjacency);

		for (const objectiveId of buckets.objectives) {
			for (const materialId of buckets.materials) {
				addRelation(objectiveId, materialId, 'overview_objective_material');
			}
		}

		for (const logicChainId of buckets.logicChains) {
			for (const materialId of buckets.materials) {
				addRelation(logicChainId, materialId, 'overview_logic_chain_material');
			}
		}

		for (const documentId of buckets.documents) {
			for (const materialId of buckets.materials) {
				addRelation(documentId, materialId, 'overview_document_material');
			}
		}

		for (const materialId of buckets.materials) {
			for (const propertyId of buckets.properties) {
				addRelation(materialId, propertyId, 'overview_material_property');
			}
			for (const contextId of buckets.contexts) {
				addRelation(materialId, contextId, 'overview_material_context');
			}
		}

		if (!buckets.materials.size) {
			for (const objectiveId of buckets.objectives) {
				for (const propertyId of buckets.properties) {
					addRelation(objectiveId, propertyId, 'overview_objective_topic');
				}
				for (const contextId of buckets.contexts) {
					addRelation(objectiveId, contextId, 'overview_objective_topic');
				}
			}
			for (const logicChainId of buckets.logicChains) {
				for (const propertyId of buckets.properties) {
					addRelation(logicChainId, propertyId, 'overview_logic_chain_topic');
				}
				for (const contextId of buckets.contexts) {
					addRelation(logicChainId, contextId, 'overview_logic_chain_topic');
				}
			}
			for (const documentId of buckets.documents) {
				for (const propertyId of buckets.properties) {
					addRelation(documentId, propertyId, 'overview_document_topic');
				}
				for (const contextId of buckets.contexts) {
					addRelation(documentId, contextId, 'overview_document_topic');
				}
			}
		}
	}

	const maxCount = Math.max(1, ...Array.from(relations.values(), (relation) => relation.count));
	const overviewDegrees = new Map<string, number>();
	const edges = Array.from(relations.values()).map((relation, index) => {
		overviewDegrees.set(
			relation.source,
			(overviewDegrees.get(relation.source) ?? 0) + relation.count
		);
		overviewDegrees.set(
			relation.target,
			(overviewDegrees.get(relation.target) ?? 0) + relation.count
		);
		return {
			id: `overview:${index}`,
			source: relation.source,
			target: relation.target,
			weight: relation.count / maxCount,
			edge_description: relation.edgeDescription
		};
	});

	const nodes = keptNodes.map((node) => ({
		...node,
		degree: Math.max(Number(node.degree ?? 0), overviewDegrees.get(node.id) ?? 0)
	}));

	return {
		collection_id: graph.collection_id,
		nodes,
		edges,
		truncated: graph.truncated
	};
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
	return truncateGraphLabel(label, limit);
}

function getNodeDisplayLabel(node: GraphNode | GraphSelectedNode, limit = 34) {
	const label = compactGraphKeyValueLabel(formatGraphLabel(node.label || node.id));
	return truncateGraphLabel(label, limit);
}

function compactGraphKeyValueLabel(label: string) {
	const pairs = label
		.split(';')
		.map((part) => {
			const separatorIndex = part.indexOf(':');
			if (separatorIndex < 0) return null;
			const key = part.slice(0, separatorIndex).trim();
			const value = part.slice(separatorIndex + 1).trim();
			return key && value ? { key, value } : null;
		})
		.filter((pair): pair is { key: string; value: string } => Boolean(pair));

	if (pairs.length < 2) return label;

	const concisePairs = pairs.filter((pair) => {
		const key = pair.key.toLowerCase();
		return key !== 'details' && key !== 'description' && pair.value.length <= 72;
	});
	const methodPair = concisePairs.find((pair) => {
		const key = pair.key.toLowerCase();
		return key === 'method' || key === 'test method';
	});
	if (methodPair) return methodPair.value;

	const summary = concisePairs
		.slice(0, 3)
		.map((pair) => `${pair.key}: ${pair.value}`)
		.join(' / ');
	return summary || label;
}

function truncateGraphLabel(label: string, limit: number) {
	if (label.length <= limit) return label;
	return `${label.slice(0, Math.max(1, limit - 1)).trimEnd()}...`;
}

function isAggregateNodeType(type: GraphNodeType) {
	return (
		type === 'material' ||
		type === 'property' ||
		type === 'process' ||
		type === 'sample' ||
		type === 'test_condition' ||
		type === 'baseline'
	);
}

function graphNodeDimensions(type: GraphNodeType, label: string, degree: number) {
	const aggregate = isAggregateNodeType(type);
	const degreeBoost = Math.min(Math.max(degree, 0), 6);
	if (aggregate) {
		const textWidth = Math.min(176, Math.max(118, label.length * 5.8));
		const textRows = Math.max(1, Math.min(3, Math.ceil(label.length / 22)));
		return {
			width: textWidth + degreeBoost * 4,
			height: 52 + textRows * 16 + degreeBoost * 2,
			textMaxWidth: Math.max(96, textWidth - 18),
			fontSize: 11,
			layoutWeight: 26000
		};
	}

	if (type === 'comparison' || type === 'controlled_comparison') {
		return {
			width: 104 + degreeBoost * 4,
			height: 72 + degreeBoost * 2,
			textMaxWidth: 86,
			fontSize: 10,
			layoutWeight: 20000
		};
	}

	if (
		type === 'objective' ||
		type === 'logic_chain' ||
		type === 'document' ||
		isEvidenceUnitNodeType(type)
	) {
		return {
			width: 108 + degreeBoost * 3,
			height: 58 + degreeBoost * 2,
			textMaxWidth: 88,
			fontSize: 10,
			layoutWeight: 13500
		};
	}

	return {
		width: 104 + degreeBoost * 3,
		height: 58 + degreeBoost * 2,
		textMaxWidth: 84,
		fontSize: 11,
		layoutWeight: 13000
	};
}

export function getNodeDescription(node: GraphNode | GraphSelectedNode) {
	const type = normalizeGraphNodeType(node.type);
	const label = getNodeLabel(node, 72);
	if (type === 'objective') return `${label} is a research objective for this collection.`;
	if (type === 'logic_chain')
		return `${label} is an assembled research logic chain backed by evidence units.`;
	if (type === 'document') return `${label} is a source document in this collection.`;
	if (type === 'evidence') return `${label} is an extracted evidence claim linked to source text.`;
	if (type === 'measurement') return `${label} is an objective-scoped measurement evidence unit.`;
	if (type === 'controlled_comparison')
		return `${label} is an objective-scoped controlled comparison evidence unit.`;
	if (type === 'comparison')
		return `${label} is a comparison row connecting evidence and review context.`;
	if (type === 'material')
		return `${label} is a material or material system shared by collection results.`;
	if (type === 'property') return `${label} is a measured or reported property.`;
	if (type === 'sample') return `${label} is a sample or specimen context.`;
	if (type === 'test_condition') return `${label} is an experimental or evaluation condition.`;
	if (type === 'baseline') return `${label} is a baseline or control reference.`;
	if (type === 'process')
		return `${label} is a method or process context extracted from the collection.`;
	if (type === 'mechanism')
		return `${label} is an author interpretation or mechanism evidence unit.`;
	if (type === 'characterization')
		return `${label} is a characterization observation evidence unit.`;
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
		const fullLabel = formatGraphLabel(node.label || node.id);
		const label = getNodeDisplayLabel(
			node,
			isAggregateNodeType(type) ? 48 : type === 'comparison' ? 30 : 28
		);
		const degree = node.degree ?? 0;
		const dimensions = graphNodeDimensions(type, label, degree);
		elements.push({
			group: 'nodes',
			data: {
				id: node.id,
				label,
				fullLabel,
				displayLabel: label,
				entityType: type,
				typeColor: style.color,
				typeBackground: style.background,
				typeShape: style.shape,
				typeIcon: style.icon,
				degree,
				width: dimensions.width,
				height: dimensions.height,
				textMaxWidth: dimensions.textMaxWidth,
				fontSize: dimensions.fontSize,
				layoutWeight: dimensions.layoutWeight
			},
			position:
				options.previousPositions?.get(node.id) ??
				fallbackPosition(node.id, index, graph.nodes.length)
		});
	}

	for (const edge of graph.edges) {
		if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
		const style = getEdgeTypeStyle(edge.edge_description);
		const sourceType = normalizeGraphNodeType(nodeMap.get(edge.source)?.type);
		const targetType = normalizeGraphNodeType(nodeMap.get(edge.target)?.type);
		const hubEdge =
			isOverviewBridgeNodeType(sourceType) ||
			isOverviewBridgeNodeType(targetType) ||
			isAggregateNodeType(sourceType) ||
			isAggregateNodeType(targetType);
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
				idealLength: hubEdge ? 185 : 132
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
				'underlay-color': 'rgba(37, 99, 235, 0.18)',
				'underlay-opacity': 1,
				'underlay-padding': 8
			}
		},
		{
			selector: 'node.is-selected',
			style: {
				'border-width': 4,
				'border-color': '#2563EB',
				'underlay-color': 'rgba(37, 99, 235, 0.24)',
				'underlay-opacity': 1,
				'underlay-padding': 12
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
	const nodeCount = cy.nodes().length;
	if (nodeCount < 2) return;
	const requestedName =
		layoutName === 'grid' || layoutName === 'circle' || layoutName === 'cose'
			? layoutName
			: 'fcose';
	const name =
		requestedName === 'fcose' && (nodeCount <= 2 || nodeCount > 300) ? 'grid' : requestedName;

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
						name: 'fcose',
						quality: 'proof',
						randomize: false,
						animate: false,
						fit: false,
						padding: 72,
						nodeDimensionsIncludeLabels: true,
						uniformNodeDimensions: false,
						nodeSeparation: 124,
						nodeRepulsion: (node: NodeSingular) => Number(node.data('layoutWeight') ?? 12000),
						idealEdgeLength: (edge: EdgeSingular) => Number(edge.data('idealLength') ?? 132),
						edgeElasticity: 0.18,
						gravity: 0.1,
						gravityRange: 4.4,
						numIter: 3600,
						tile: true,
						tilingPaddingVertical: 34,
						tilingPaddingHorizontal: 34
					} as unknown as LayoutOptions)
				: ({
						name,
						animate: false,
						fit: false,
						padding: 72
					} as LayoutOptions);
		const layout = cy.layout(options);
		layout.on('layoutstop', finish);
		timeoutId = setTimeout(finish, 1600);
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

function isCollectionOverviewNodeType(type: GraphNodeType) {
	return !isOverviewBridgeNodeType(type);
}

function isOverviewContextType(type: GraphNodeType) {
	return (
		type === 'process' ||
		type === 'sample' ||
		type === 'variant' ||
		type === 'test_condition' ||
		type === 'baseline'
	);
}

function isEvidenceUnitNodeType(type: GraphNodeType) {
	return (
		type === 'evidence' ||
		type === 'measurement' ||
		type === 'controlled_comparison' ||
		type === 'mechanism' ||
		type === 'characterization'
	);
}

function isOverviewBridgeNodeType(type: GraphNodeType) {
	return type === 'comparison' || isEvidenceUnitNodeType(type);
}

function buildAdjacency(edges: GraphEdge[]) {
	const adjacency = new Map<string, GraphEdge[]>();
	for (const edge of edges) {
		const sourceEdges = adjacency.get(edge.source) ?? [];
		sourceEdges.push(edge);
		adjacency.set(edge.source, sourceEdges);

		const targetEdges = adjacency.get(edge.target) ?? [];
		targetEdges.push(edge);
		adjacency.set(edge.target, targetEdges);
	}
	return adjacency;
}

function connectedNodeIds(adjacency: Map<string, GraphEdge[]>, nodeId: string) {
	return (adjacency.get(nodeId) ?? []).map((edge) =>
		edge.source === nodeId ? edge.target : edge.source
	);
}

function orderedKeyChainBackboneNodes(nodes: GraphNode[]) {
	return nodes
		.filter((node) => {
			const type = normalizeGraphNodeType(node.type);
			return type === 'objective' || type === 'logic_chain' || type === 'document';
		})
		.sort(sortGraphNodesByDegree);
}

function orderedKeyChainEvidenceNodes(
	nodes: GraphNode[],
	adjacency: Map<string, GraphEdge[]>,
	nodeById: Map<string, GraphNode>
) {
	return nodes
		.filter((node) => isEvidenceUnitNodeType(normalizeGraphNodeType(node.type)))
		.sort((left, right) => {
			const leftScore = keyChainEvidenceScore(left.id, adjacency, nodeById);
			const rightScore = keyChainEvidenceScore(right.id, adjacency, nodeById);
			return rightScore - leftScore || sortGraphNodesByDegree(left, right);
		});
}

function keyChainEvidenceScore(
	nodeId: string,
	adjacency: Map<string, GraphEdge[]>,
	nodeById: Map<string, GraphNode>
) {
	const types = new Set(
		connectedNodeIds(adjacency, nodeId).map((neighborId) =>
			normalizeGraphNodeType(nodeById.get(neighborId)?.type)
		)
	);
	let score = 0;
	if (types.has('objective')) score += 8;
	if (types.has('logic_chain')) score += 8;
	if (types.has('document')) score += 5;
	if (types.has('material')) score += 3;
	if (types.has('property')) score += 3;
	if (types.has('process')) score += 2;
	if (types.has('sample')) score += 1;
	return score;
}

function orderedKeyChainNeighbors(
	nodeId: string,
	adjacency: Map<string, GraphEdge[]>,
	nodeById: Map<string, GraphNode>
) {
	return connectedNodeIds(adjacency, nodeId)
		.filter((neighborId) => {
			const type = normalizeGraphNodeType(nodeById.get(neighborId)?.type);
			return isKeyChainNodeType(type);
		})
		.sort((leftId, rightId) => {
			const left = nodeById.get(leftId);
			const right = nodeById.get(rightId);
			return (
				keyChainNodePriority(normalizeGraphNodeType(left?.type)) -
					keyChainNodePriority(normalizeGraphNodeType(right?.type)) ||
				sortGraphNodesByDegree(left, right)
			);
		});
}

function isKeyChainNodeType(type: GraphNodeType) {
	return (
		type === 'objective' ||
		type === 'logic_chain' ||
		type === 'document' ||
		isEvidenceUnitNodeType(type) ||
		type === 'material' ||
		type === 'property' ||
		type === 'process' ||
		type === 'sample' ||
		type === 'test_condition' ||
		type === 'baseline'
	);
}

function keyChainNodePriority(type: GraphNodeType) {
	if (type === 'objective') return 0;
	if (type === 'logic_chain') return 1;
	if (type === 'document') return 2;
	if (isEvidenceUnitNodeType(type)) return 3;
	if (type === 'material') return 4;
	if (type === 'property') return 5;
	if (type === 'process') return 6;
	if (type === 'sample') return 7;
	if (type === 'test_condition') return 8;
	if (type === 'baseline') return 9;
	return 99;
}

function sortGraphNodesByDegree(left: GraphNode | undefined, right: GraphNode | undefined) {
	return (
		Number(right?.degree ?? 0) - Number(left?.degree ?? 0) ||
		String(left?.label ?? left?.id ?? '').localeCompare(String(right?.label ?? right?.id ?? ''))
	);
}

function collectOverviewBuckets(
	bridgeNodeId: string,
	nodeById: Map<string, GraphNode>,
	adjacency: Map<string, GraphEdge[]>
) {
	const buckets = {
		objectives: new Set<string>(),
		logicChains: new Set<string>(),
		documents: new Set<string>(),
		materials: new Set<string>(),
		properties: new Set<string>(),
		contexts: new Set<string>()
	};

	for (const neighborId of connectedNodeIds(adjacency, bridgeNodeId)) {
		const neighbor = nodeById.get(neighborId);
		const type = normalizeGraphNodeType(neighbor?.type);
		if (type === 'objective') buckets.objectives.add(neighborId);
		if (type === 'logic_chain') buckets.logicChains.add(neighborId);
		if (type === 'document') buckets.documents.add(neighborId);
		if (type === 'material') buckets.materials.add(neighborId);
		if (type === 'property') buckets.properties.add(neighborId);
		if (isOverviewContextType(type)) buckets.contexts.add(neighborId);

		if (isOverviewBridgeNodeType(type)) {
			for (const evidenceNeighborId of connectedNodeIds(adjacency, neighborId)) {
				const evidenceNeighbor = nodeById.get(evidenceNeighborId);
				const evidenceNeighborType = normalizeGraphNodeType(evidenceNeighbor?.type);
				if (evidenceNeighborType === 'objective') {
					buckets.objectives.add(evidenceNeighborId);
				}
				if (evidenceNeighborType === 'logic_chain') {
					buckets.logicChains.add(evidenceNeighborId);
				}
				if (evidenceNeighborType === 'document') {
					buckets.documents.add(evidenceNeighborId);
				}
			}
		}
	}

	return buckets;
}

function normalizeSearch(value?: string | null) {
	return String(value ?? '')
		.toLowerCase()
		.replace(/_+/g, ' ')
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

	const needle = normalizeSearch(
		selected.node.label || selected.node.displayLabel || ref.resourceId
	);
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

function selectedMatchesDocument(
	selected: GraphSelectedObject,
	document: DocumentProfile
): boolean {
	if (selected.kind === 'edge') {
		return (
			selectedMatchesDocument(nodeSelection(selected.edge.source), document) ||
			selectedMatchesDocument(nodeSelection(selected.edge.target), document)
		);
	}

	const ref = parseSelectedNode(selected.node);
	if (ref.kind === 'document') return document.document_id === ref.resourceId;
	const needle = normalizeSearch(
		selected.node.label || selected.node.displayLabel || ref.resourceId
	);
	if (!needle) return false;
	return normalizeSearch(`${document.title ?? ''} ${document.source_filename ?? ''}`).includes(
		needle
	);
}

function parseSelectedNode(node: GraphSelectedNode): GraphNodeRef {
	const parsed = parseGraphNodeId(node.id);
	if (parsed.kind !== 'unknown') return parsed;
	const resourceId = String(node.resourceId ?? node.id).trim();
	const kind = normalizeGraphNodeType(node.kind ?? node.type);
	if (
		kind === 'objective' ||
		kind === 'logic_chain' ||
		kind === 'document' ||
		kind === 'evidence' ||
		kind === 'comparison' ||
		kind === 'measurement' ||
		kind === 'controlled_comparison' ||
		kind === 'material' ||
		kind === 'property' ||
		kind === 'process' ||
		kind === 'sample' ||
		kind === 'test_condition' ||
		kind === 'baseline' ||
		kind === 'mechanism' ||
		kind === 'characterization'
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
	if (kind === 'process') {
		return normalizeSearch(comparison.display.process_normalized) === value;
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
