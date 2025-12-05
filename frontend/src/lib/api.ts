import { PUBLIC_API_BASE } from '$env/static/public';
import type {
  DocumentDetailResponse,
  DocumentRecord,
  QueryResponse,
  UploadResponse
} from './types';

export const apiBase = (PUBLIC_API_BASE || 'http://localhost:8000').replace(/\/$/, '');

async function handleResponse<T>(res: Response): Promise<T> {
  const contentType = res.headers.get('Content-Type') || '';
  const isJson = contentType.includes('application/json');
  const payload = isJson ? await res.json() : await res.text();

  if (!res.ok) {
    const detail = isJson && payload?.detail ? payload.detail : res.statusText;
    throw new Error(detail || '请求失败');
  }

  return payload as T;
}

export async function healthCheck(): Promise<{ status: string }> {
  const res = await fetch(`${apiBase}/health`);
  return handleResponse(res);
}

export async function uploadDocument(params: {
  file: File;
  tags?: string;
  metadata?: string;
}): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', params.file);
  if (params.tags?.trim()) formData.append('tags', params.tags.trim());
  if (params.metadata?.trim()) formData.append('metadata', params.metadata.trim());

  const res = await fetch(`${apiBase}/documents`, {
    method: 'POST',
    body: formData
  });
  return handleResponse(res);
}

export async function listDocuments(): Promise<{ items: DocumentRecord[] }> {
  const res = await fetch(`${apiBase}/documents`);
  return handleResponse(res);
}

export async function fetchDocumentDetail(docId: string): Promise<DocumentDetailResponse> {
  const res = await fetch(`${apiBase}/documents/${docId}`);
  return handleResponse(res);
}

export async function fetchDocumentKeywords(docId: string): Promise<{ keywords: string[] }> {
  const res = await fetch(`${apiBase}/documents/${docId}/keywords`);
  return handleResponse(res);
}

export async function fetchDocumentGraph(docId: string): Promise<{ graph: unknown; mindmap: unknown }> {
  const res = await fetch(`${apiBase}/documents/${docId}/graph`);
  return handleResponse(res);
}

export async function runQuery(question: string, topK = 4): Promise<QueryResponse> {
  const res = await fetch(`${apiBase}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: question, top_k: topK })
  });
  return handleResponse(res);
}
