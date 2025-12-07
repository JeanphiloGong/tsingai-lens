export interface DocumentRecord {
  id: string;
  filename?: string;
  original_filename: string;
  tags: string[];
  metadata: Record<string, unknown>;
  status?: string;
  status_message?: string;
  created_at?: string;
  updated_at?: string;
}

export interface GraphNode {
  id: string;
  label?: string;
  type?: string;
  score?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation?: string;
  weight?: number;
}

export interface GraphData {
  nodes?: GraphNode[];
  edges?: GraphEdge[];
  [k: string]: unknown;
}

export interface GraphSnapshotResponse {
  graph?: GraphData;
  mindmap?: unknown;
}
