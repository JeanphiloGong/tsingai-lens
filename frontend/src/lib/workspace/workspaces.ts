import { writable } from 'svelte/store';
import { requestJson } from '../../routes/_shared/api';
import type { WorkspaceDocument } from '../../routes/_shared/workspaceDocuments';

export type Workspace = {
	workspace_id: string;
	name: string;
	description: string | null;
	status: string;
	paper_count: number;
	created_at: string;
	updated_at: string;
	documents: Pick<
		WorkspaceDocument,
		| 'document_id'
		| 'filename'
		| 'media_type'
		| 'status'
		| 'size_bytes'
		| 'created_at'
		| 'updated_at'
	>[];
};

export type WorkspaceStatusGroup = 'complete' | 'ready' | 'processing' | 'attention' | 'neutral';

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
 * legacy workspace status. Workspace status is only updated on upload in
 * older records, while document preparation records the actual readiness.
 */
export function getWorkspaceStatusGroup(
	workspace: Pick<Workspace, 'status' | 'documents'>
): WorkspaceStatusGroup {
	const normalizedStatus = workspace.status?.toLowerCase() ?? '';
	const documents = workspace.documents ?? [];

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

export const workspaces = writable<Workspace[]>([]);

export async function fetchWorkspaces() {
	const data = (await requestJson('/workspaces', { method: 'GET' })) as { items: Workspace[] };
	const items = data.items;
	workspaces.set(items);
	return items;
}

export async function fetchWorkspace(workspaceId: string) {
	const data = (await requestJson(`/workspaces/${encodeURIComponent(workspaceId)}`, {
		method: 'GET'
	})) as Workspace;
	const workspace = data;
	if (workspace.workspace_id !== workspaceId) {
		throw new Error('Workspace response is missing workspace_id.');
	}

	workspaces.update((items) => {
		const next = items.filter((item) => item.workspace_id !== workspace.workspace_id);
		return [...next, workspace].sort((a, b) => {
			const left = a.updated_at ?? a.created_at ?? '';
			const right = b.updated_at ?? b.created_at ?? '';
			return right.localeCompare(left);
		});
	});

	return workspace;
}

export async function createWorkspace(payload: { name: string; description?: string }) {
	const body = {
		name: payload.name,
		description: payload.description?.trim() || null
	};

	const data = (await requestJson('/workspaces', {
		method: 'POST',
		body: JSON.stringify(body)
	})) as Workspace;

	const workspace = data;

	workspaces.update((items) => [
		workspace,
		...items.filter((item) => item.workspace_id !== workspace.workspace_id)
	]);

	return workspace;
}

export async function deleteWorkspace(workspaceId: string) {
	const data = await requestJson(`/workspaces/${encodeURIComponent(workspaceId)}`, {
		method: 'DELETE'
	});

	const record = data as { workspace_id: string; deleted_at: string };
	if (record.workspace_id !== workspaceId) {
		throw new Error('Workspace deletion response does not match workspace_id.');
	}
	workspaces.update((items) =>
		items.filter((item) => item.workspace_id !== record.workspace_id)
	);
	return record;
}
