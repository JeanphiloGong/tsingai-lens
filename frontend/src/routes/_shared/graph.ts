import { buildApiUrl, requestJson } from './api';

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
