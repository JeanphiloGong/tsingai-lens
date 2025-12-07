import { apiBase, handle } from './http';
import type { DocumentRecord } from './types/common';
import type { UploadResponse, FileStatusResponse } from './types/file';
import type { DocumentDetailResponse } from './types/graph';

// 上传文件
export async function uploadFile(params: { file: File; tags?: string; metadata?: string }) {
  const fd = new FormData();
  fd.append('file', params.file);
  if (params.tags?.trim()) fd.append('tags', params.tags.trim());
  if (params.metadata?.trim()) fd.append('metadata', params.metadata.trim());
  return handle<UploadResponse>(await fetch(`${apiBase}/file/upload`, { method: 'POST', body: fd }));
}

// 查询文件处理状态
export async function fetchFileStatus(docId: string) {
  return handle<FileStatusResponse>(await fetch(`${apiBase}/file/status/${docId}`));
}

