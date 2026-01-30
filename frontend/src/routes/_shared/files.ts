import { requestJson } from './api';

export type CollectionFile = {
  key: string;
  original_filename?: string;
  stored_path?: string;
  size_bytes?: number;
  created_at?: string;
};

export type CollectionFilesResponse = {
  collection_id?: string;
  count?: number;
  items?: CollectionFile[];
};

export type DeleteCollectionFileResult = {
  collection_id?: string;
  key?: string;
  deleted_at?: string;
  status?: string;
};

export async function listCollectionFiles(collectionId: string) {
  const data = await requestJson(`/retrieval/collections/${encodeURIComponent(collectionId)}/files`, {
    method: 'GET'
  });
  return data as CollectionFilesResponse;
}

export async function uploadCollectionFiles(collectionId: string, files: File[]) {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  const data = await requestJson(`/retrieval/collections/${encodeURIComponent(collectionId)}/files`, {
    method: 'POST',
    body: formData
  });
  return data as CollectionFilesResponse;
}

export async function deleteCollectionFile(collectionId: string, key: string) {
  const params = new URLSearchParams({ key });
  const data = await requestJson(
    `/retrieval/collections/${encodeURIComponent(collectionId)}/files?${params.toString()}`,
    { method: 'DELETE' }
  );
  return data as DeleteCollectionFileResult;
}
