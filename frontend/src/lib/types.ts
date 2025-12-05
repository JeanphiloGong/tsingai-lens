export interface DocumentRecord {
  id: string;
  filename: string;
  original_filename: string;
  tags: string[];
  metadata: Record<string, unknown>;
  created_at?: string;
}

export interface GraphNode {
  id: string;
  label?: string;
  type?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  label?: string;
}

export interface GraphPayload {
  nodes?: GraphNode[];
  edges?: GraphEdge[];
}

export interface DocumentMeta {
  keywords?: string[];
  graph?: GraphPayload;
  mindmap?: Record<string, unknown>;
  images?: string[];
  summary?: string;
}

export interface DocumentDetailResponse {
  record: DocumentRecord;
  meta: DocumentMeta;
}

export interface SourceEntry {
  content: string;
  metadata?: Record<string, unknown>;
}

export interface QueryResponse {
  answer: string;
  sources: SourceEntry[];
}

export interface UploadResponse {
  id: string;
  keywords?: string[];
  graph?: GraphPayload;
  mindmap?: Record<string, unknown>;
  summary?: string;
}
