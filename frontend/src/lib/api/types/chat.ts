export interface SourceEntry {
  doc_id?: string;
  source?: string;
  page?: number;
  chunk_id?: string;
  snippet?: string;
  edge_id?: string;
  community_id?: string;
  head?: string;
  tail?: string;
  relation?: string;
  score?: number;
  [k: string]: unknown;
}

export interface QueryResponse {
  answer: string;
  sources: SourceEntry[];
}
