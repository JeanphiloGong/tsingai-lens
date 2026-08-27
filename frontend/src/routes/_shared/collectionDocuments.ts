import { requestJson } from './api';

export type CollectionDocument = {
  document_id: string;
  original_filename: string;
  stored_filename: string;
  storage_key: string;
  sha256: string;
  media_type?: string | null;
  status: string;
  size_bytes: number;
  created_at: string;
};

export type CollectionDocumentsResponse = {
  count: number;
  items: CollectionDocument[];
};

function normalizeCollectionDocument(item: unknown): CollectionDocument | null {
  if (!item || typeof item !== 'object') return null;
  const record = item as Record<string, unknown>;
  const documentId = String(record.document_id ?? '').trim();
  if (!documentId) return null;

  return {
    document_id: documentId,
    original_filename: String(record.original_filename ?? ''),
    stored_filename: String(record.stored_filename ?? ''),
    storage_key: String(record.storage_key ?? ''),
    sha256: String(record.sha256 ?? ''),
    media_type: typeof record.media_type === 'string' ? record.media_type : null,
    status: String(record.status ?? 'unknown'),
    size_bytes: typeof record.size_bytes === 'number' ? record.size_bytes : Number(record.size_bytes ?? 0),
    created_at: String(record.created_at ?? '')
  };
}

export async function listCollectionDocuments(
  collectionId: string
): Promise<CollectionDocumentsResponse> {
  const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}/documents`, {
    method: 'GET'
  });

  const items =
    data && typeof data === 'object' && Array.isArray((data as Record<string, unknown>).items)
      ? ((data as Record<string, unknown>).items as unknown[])
          .map((item) => normalizeCollectionDocument(item))
          .filter((item): item is CollectionDocument => item !== null)
      : [];

  return { count: items.length, items };
}

export async function uploadCollectionDocument(collectionId: string, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}/documents`, {
    method: 'POST',
    body: formData
  });

  const uploaded = normalizeCollectionDocument(data);
  if (!uploaded) {
    throw new Error('Document upload response is missing document_id.');
  }
  return uploaded;
}

export async function uploadCollectionDocuments(collectionId: string, files: File[]) {
  const items: CollectionDocument[] = [];
  for (const file of files) {
    items.push(await uploadCollectionDocument(collectionId, file));
  }

  return { count: items.length, items } satisfies CollectionDocumentsResponse;
}
