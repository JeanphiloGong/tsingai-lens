import type {
  DocumentRecord,
  GraphSnapshotResponse,
  GraphEdge,
  GraphNode,
  GraphData
} from './common';

export interface DocumentMeta {
  keywords?: string[];
  graph?: GraphData;
  mindmap?: unknown;
  images?: string[];
  info?: Record<string, unknown>;
  summary?: string;
}

export interface DocumentDetailResponse {
  record: DocumentRecord;
  meta: DocumentMeta;
}

export interface GraphResponse extends GraphSnapshotResponse {
  graph?: GraphData;
}
