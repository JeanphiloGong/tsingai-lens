import { buildApiUrl, requestJson } from './api';

export type GraphNode = {
  id: string;
  label: string;
  type?: string | null;
  description?: string | null;
  degree?: number | null;
  frequency?: number | null;
  x?: number | null;
  y?: number | null;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  weight?: number | null;
  description?: string | null;
  rank?: number | null;
};

export type GraphResponse = {
  collection_id: string;
  output_path?: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  community?: string | null;
};

export type GraphQuery = {
  maxNodes?: number;
  minWeight?: number;
  communityId?: string;
};

function buildQuery(query: GraphQuery = {}) {
  const params = new URLSearchParams();
  params.set('max_nodes', String(query.maxNodes ?? 200));
  params.set('min_weight', String(query.minWeight ?? 0));
  if (query.communityId?.trim()) {
    params.set('community_id', query.communityId.trim());
  }
  return params.toString();
}

export async function fetchCollectionGraph(collectionId: string, query: GraphQuery = {}) {
  return (await requestJson(
    `/collections/${encodeURIComponent(collectionId)}/graph?${buildQuery(query)}`,
    { method: 'GET' }
  )) as GraphResponse;
}

export function buildCollectionGraphmlUrl(collectionId: string, query: GraphQuery = {}) {
  return buildApiUrl(`/collections/${encodeURIComponent(collectionId)}/graphml?${buildQuery(query)}`);
}
