import { requestJson } from './api';

export type CollectionFile = {
  file_id: string;
  collection_id: string;
  original_filename: string;
  stored_filename: string;
  stored_path: string;
  media_type?: string | null;
  status: string;
  size_bytes: number;
  created_at: string;
};

export type CollectionFilesResponse = {
  count: number;
  items: CollectionFile[];
};

function normalizeCollectionFile(item: unknown): CollectionFile | null {
  if (!item || typeof item !== 'object') return null;
  const record = item as Record<string, unknown>;
  const fileId = String(record.file_id ?? '').trim();
  const collectionId = String(record.collection_id ?? '').trim();
  if (!fileId || !collectionId) return null;

  return {
    file_id: fileId,
    collection_id: collectionId,
    original_filename: String(record.original_filename ?? ''),
    stored_filename: String(record.stored_filename ?? ''),
    stored_path: String(record.stored_path ?? ''),
    media_type: typeof record.media_type === 'string' ? record.media_type : null,
    status: String(record.status ?? 'unknown'),
    size_bytes: typeof record.size_bytes === 'number' ? record.size_bytes : Number(record.size_bytes ?? 0),
    created_at: String(record.created_at ?? '')
  };
}

export async function listCollectionFiles(collectionId: string): Promise<CollectionFilesResponse> {
  const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}/files`, {
    method: 'GET'
  });

  const items =
    data && typeof data === 'object' && Array.isArray((data as Record<string, unknown>).items)
      ? ((data as Record<string, unknown>).items as unknown[])
          .map((item) => normalizeCollectionFile(item))
          .filter((item): item is CollectionFile => item !== null)
      : [];

  return {
    count: items.length,
    items
  };
}

export async function uploadCollectionFile(collectionId: string, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}/files`, {
    method: 'POST',
    body: formData
  });

  const uploaded = normalizeCollectionFile(data);
  if (!uploaded) {
    throw new Error('File upload response is missing file_id.');
  }
  return uploaded;
}

export async function uploadCollectionFiles(collectionId: string, files: File[]) {
  const items: CollectionFile[] = [];
  for (const file of files) {
    items.push(await uploadCollectionFile(collectionId, file));
  }

  return {
    count: items.length,
    items
  } satisfies CollectionFilesResponse;
}
