import { writable } from 'svelte/store';
import { requestJson } from './api';

type CollectionRecord = {
  id?: string;
  collection_id?: string;
  name?: string | null;
  description?: string | null;
  status?: string | null;
  default_method?: string | null;
  paper_count?: number | null;
  document_count?: number | null;
  entity_count?: number | null;
  created_at?: string;
  updated_at?: string;
};

type DeletedCollectionRecord = {
  id?: string;
  collection_id?: string;
  deleted_at?: string;
};

export type Collection = {
  id: string;
  collection_id: string;
  name?: string | null;
  description?: string | null;
  status?: string | null;
  default_method?: string | null;
  paper_count?: number | null;
  entity_count?: number | null;
  created_at?: string;
  updated_at?: string;
};

export const collections = writable<Collection[]>([]);

function normalizeCollection(item: unknown): Collection | null {
  if (!item || typeof item !== 'object') return null;

  const record = item as CollectionRecord;
  const collectionId = String(record.collection_id ?? record.id ?? '').trim();

  if (!collectionId) return null;

  return {
    id: collectionId,
    collection_id: collectionId,
    name: record.name,
    description: record.description,
    status: record.status,
    default_method: record.default_method,
    paper_count: record.paper_count ?? record.document_count,
    entity_count: record.entity_count,
    created_at: record.created_at,
    updated_at: record.updated_at
  };
}

function normalizeCollections(data: unknown): Collection[] {
  const items =
    Array.isArray(data) ? data : data && typeof data === 'object' ? (data as Record<string, unknown>).items : [];

  if (!Array.isArray(items)) return [];

  return items.map((item) => normalizeCollection(item)).filter((item): item is Collection => item !== null);
}

export async function fetchCollections() {
  const data = await requestJson('/collections', { method: 'GET' });
  const items = normalizeCollections(data);
  collections.set(items);
  return items;
}

export async function fetchCollection(collectionId: string) {
  const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}`, { method: 'GET' });
  const collection = normalizeCollection(data);

  if (!collection) {
    throw new Error('Collection response is missing collection_id.');
  }

  collections.update((items) => {
    const next = items.filter((item) => item.id !== collection.id);
    return [...next, collection].sort((a, b) => {
      const left = a.updated_at ?? a.created_at ?? '';
      const right = b.updated_at ?? b.created_at ?? '';
      return right.localeCompare(left);
    });
  });

  return collection;
}

export async function createCollection(payload: {
  name: string;
  description?: string;
  defaultMethod?: string;
}) {
  const body = {
    name: payload.name,
    description: payload.description?.trim() || null,
    default_method: payload.defaultMethod?.trim() || 'standard'
  };

  const data = await requestJson('/collections', {
    method: 'POST',
    body: JSON.stringify(body)
  });

  const collection = normalizeCollection(data);

  if (!collection) {
    throw new Error('Collection response is missing collection_id.');
  }

  collections.update((items) => [collection, ...items.filter((item) => item.id !== collection.id)]);

  return collection;
}

export async function deleteCollection(collectionId: string) {
  const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}`, {
    method: 'DELETE'
  });

  const record = data && typeof data === 'object' ? (data as DeletedCollectionRecord) : null;
  const deletedCollectionId = String(record?.collection_id ?? record?.id ?? collectionId).trim() || collectionId;

  collections.update((items) => items.filter((item) => item.id !== deletedCollectionId));

  return {
    collection_id: deletedCollectionId,
    deleted_at: record?.deleted_at
  };
}
