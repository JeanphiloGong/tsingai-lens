import { apiBase, handle } from './http';
import type { DocumentRecord } from './types/common';
import type { DocumentDetailResponse, GraphResponse } from './types/graph';

// 文档列表
export async function listDocuments() {
  const res = await handle<{ items?: DocumentRecord[] }>(await fetch(`${apiBase}/graph/documents`));
  return res.items ?? [];
}

// 文档详情
export async function fetchDocumentDetail(docId: string) {
  return handle<DocumentDetailResponse>(await fetch(`${apiBase}/graph/documents/${docId}`));
}

// 文档关键词
export async function fetchDocumentKeywords(docId: string) {
  const res = await handle<{ keywords?: string[] }>(
    await fetch(`${apiBase}/graph/documents/${docId}/keywords`)
  );
  return res.keywords ?? [];
}

// 图谱/脑图
export async function fetchDocumentGraph(docId: string) {
  return handle<GraphResponse>(await fetch(`${apiBase}/graph/documents/${docId}/graph`));
}
