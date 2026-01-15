import { writable } from 'svelte/store';
import { requestJson } from './api';

export type Collection = {
  id: string;
  name?: string;
  created_at?: string;
  updated_at?: string;
  status?: string;
  document_count?: number;
  entity_count?: number;
};

export const collections = writable<Collection[]>([]);

function normalizeCollections(data: unknown): Collection[] {
  if (Array.isArray(data)) {
    return data as Collection[];
  }
  if (data && typeof data === 'object') {
    const record = data as Record<string, unknown>;
    const items = record.items;
    if (Array.isArray(items)) {
      return items as Collection[];
    }
  }
  return [];
}

export async function fetchCollections() {
  const data = await requestJson('/retrieval/collections', { method: 'GET' });
  const items = normalizeCollections(data);
  collections.set(items);
  return items;
}

export async function createCollection(name?: string) {
  const payload: Record<string, unknown> = {};
  if (name) {
    payload.name = name;
  }
  const data = await requestJson('/retrieval/collections', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  return data as Collection;
}
