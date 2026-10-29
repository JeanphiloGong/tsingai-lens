import { writable } from 'svelte/store';
import { requestJson } from './api';
import type { CollectionDocument } from './collectionDocuments';
import type { AgentPermission } from './chatSessions';

export type Collection = {
	collection_id: string;
	name: string;
	description: string | null;
	status: string;
	paper_count: number;
	created_at: string;
	updated_at: string;
	documents: Pick<CollectionDocument,
		'document_id' | 'original_filename' | 'media_type' | 'status' |
		'size_bytes' | 'created_at' | 'updated_at'>[];
};

export type CollectionStatusGroup = 'complete' | 'ready' | 'processing' | 'attention' | 'neutral';

const PROCESSING_COLLECTION_STATUSES = new Set([
	'processing',
	'running',
	'queued',
	'started',
	'in_progress'
]);
const ATTENTION_COLLECTION_STATUSES = new Set(['attention_required', 'failed', 'partial_success']);
const COMPLETE_COLLECTION_STATUSES = new Set([
	'ready',
	'completed',
	'complete',
	'success',
	'graph_ready',
	'document_profiled',
	'comparison_pending',
	'partial_ready'
]);
const PROCESSING_DOCUMENT_STATUSES = new Set(['processing', 'running', 'queued', 'started']);

/**
 * Derive the list-level state from current documents before trusting the
 * legacy collection status. Collection status is only updated on upload in
 * older records, while document preparation records the actual readiness.
 */
export function getCollectionStatusGroup(
	collection: Pick<Collection, 'status' | 'documents'>
): CollectionStatusGroup {
	const normalizedStatus = collection.status?.toLowerCase() ?? '';
	const documents = collection.documents ?? [];

	if (ATTENTION_COLLECTION_STATUSES.has(normalizedStatus)) return 'attention';
	if (documents.some((document) => document.status.toLowerCase() === 'failed')) {
		return 'attention';
	}

	if (PROCESSING_COLLECTION_STATUSES.has(normalizedStatus)) return 'processing';
	if (
		documents.some((document) => PROCESSING_DOCUMENT_STATUSES.has(document.status.toLowerCase()))
	) {
		return 'processing';
	}

	if (
		documents.length > 0 &&
		documents.every((document) => document.status.toLowerCase() === 'ready')
	) {
		return COMPLETE_COLLECTION_STATUSES.has(normalizedStatus) ? 'complete' : 'ready';
	}

	if (COMPLETE_COLLECTION_STATUSES.has(normalizedStatus)) return 'complete';
	return 'neutral';
}

export const collections = writable<Collection[]>([]);

export async function fetchCollections() {
	const data = await requestJson('/collections', { method: 'GET' }) as { items: Collection[] };
	if (!Array.isArray(data?.items) || data.items.some((item) =>
		!item || typeof item.collection_id !== 'string' || !item.collection_id || !Array.isArray(item.documents))) {
		throw new Error('Collection list response is missing items or collection_id.');
	}
	const items = data.items;
	collections.set(items);
	return items;
}

export async function fetchCollection(collectionId: string) {
	const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}`, {
		method: 'GET'
	}) as Collection;
	const collection = data;

	if (!collection || typeof collection.collection_id !== 'string' || collection.collection_id !== collectionId || !Array.isArray(collection.documents)) {
		throw new Error('Collection response is missing collection_id.');
	}

	collections.update((items) => {
		const next = items.filter((item) => item.collection_id !== collection.collection_id);
		return [...next, collection].sort((a, b) => {
			const left = a.updated_at ?? a.created_at ?? '';
			const right = b.updated_at ?? b.created_at ?? '';
			return right.localeCompare(left);
		});
	});

	return collection;
}

export async function createCollection(payload: { name: string; description?: string }) {
	const body = {
		name: payload.name,
		description: payload.description?.trim() || null
	};

	const data = await requestJson('/collections', {
		method: 'POST',
		body: JSON.stringify(body)
	}) as Collection;

	const collection = data;

	if (!collection || typeof collection.collection_id !== 'string' || !collection.collection_id || !Array.isArray(collection.documents)) {
		throw new Error('Collection response is missing collection_id.');
	}

	collections.update((items) => [collection, ...items.filter((item) => item.collection_id !== collection.collection_id)]);

	return collection;
}

export async function deleteCollection(collectionId: string) {
	const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}`, {
		method: 'DELETE'
	});

	const record = data as { collection_id: string; deleted_at: string };
	if (!record || record.collection_id !== collectionId || typeof record.deleted_at !== 'string') {
		throw new Error('Collection deletion response does not match collection_id.');
	}
	collections.update((items) => items.filter((item) => item.collection_id !== record.collection_id));
	return record;
}

export async function fetchCollectionAgentPermission(collectionId: string) {
	return (await requestJson(`/collections/${encodeURIComponent(collectionId)}/agent-permissions`, {
		method: 'GET'
	})) as AgentPermission;
}

export async function updateCollectionAgentPermission(
	collectionId: string,
	permission: AgentPermission,
	options: { allActions?: boolean } = {}
) {
	return (await requestJson(`/collections/${encodeURIComponent(collectionId)}/agent-permissions`, {
		method: 'PUT',
		body: JSON.stringify({
			mode: permission.mode,
			actions: permission.actions,
			all_actions: options.allActions ?? false,
			expires_at: permission.expires_at,
			expected_revision: permission.revision
		})
	})) as AgentPermission;
}
