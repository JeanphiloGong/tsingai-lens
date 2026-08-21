import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestJson } = vi.hoisted(() => ({
	requestJson: vi.fn()
}));

vi.mock('./api', () => ({ requestJson }));

const {
	buildOverviewPipelineSteps,
	fetchWorkspaceOverview,
	getCollectionWorkspaceState,
	getWorkspaceSurfaceState
} = await import('./workspace');

function buildWorkspacePayload(overrides: Record<string, unknown> = {}) {
	return {
		collection: {
			collection_id: 'col_123',
			name: 'Objective-first collection'
		},
		file_count: 2,
		status_summary: 'ready',
		workflow: {
			documents: { status: 'ready', detail: 'Document profiles are available.' },
			objectives: { status: 'ready', detail: 'Objective candidate discovery is complete.' }
		},
		document_summary: {
			total_documents: 2,
			by_doc_type: { experimental: 2 }
		},
		warnings: [],
		artifacts: {
			source_documents_ready: true,
			document_profiles_ready: true,
			objective_candidates_ready: true,
			updated_at: '2026-08-20T00:00:00Z'
		},
		latest_task: null,
		recent_tasks: [],
		capabilities: {
			can_view_documents: true,
			can_view_objectives: true,
			can_view_comparisons: true
		},
		links: {
			workspace: '/collections/col_123',
			documents: '/collections/col_123/documents',
			objectives: '/collections/col_123/objectives',
			comparisons: '/collections/col_123/comparisons'
		},
		...overrides
	};
}

describe('workspace shared helpers', () => {
	beforeEach(() => requestJson.mockReset());

	it('preserves only maintained workspace artifacts, capabilities, and links', async () => {
		requestJson.mockResolvedValue(buildWorkspacePayload());

		const workspace = await fetchWorkspaceOverview('col_123');

		expect(workspace.artifacts).toEqual({
			source_documents_ready: true,
			document_profiles_ready: true,
			objective_candidates_ready: true,
			updated_at: '2026-08-20T00:00:00Z'
		});
		expect(workspace.capabilities).toEqual({
			can_view_documents: true,
			can_view_objectives: true,
			can_view_comparisons: true
		});
		expect(workspace.links.objectives).toBe('/collections/col_123/objectives');
		expect('graph' in workspace.links).toBe(false);
	});

	it('treats completed Objective discovery as ready even when it produced zero candidates', async () => {
		requestJson.mockResolvedValue(buildWorkspacePayload());

		const workspace = await fetchWorkspaceOverview('col_123');

		expect(getCollectionWorkspaceState(workspace)).toBe('ready');
		expect(getWorkspaceSurfaceState(workspace, 'objectives')).toBe('ready');
		expect(getWorkspaceSurfaceState(workspace, 'comparisons')).toBe('ready');
	});

	it('requires retry when profiles exist but Objective discovery failed', async () => {
		requestJson.mockResolvedValue(
			buildWorkspacePayload({
				status_summary: 'partial_ready',
				workflow: {
					documents: { status: 'ready', detail: 'Document profiles are available.' },
					objectives: { status: 'failed', detail: 'Objective discovery failed.' }
				},
				artifacts: {
					source_documents_ready: true,
					document_profiles_ready: true,
					objective_candidates_ready: false,
					updated_at: '2026-08-20T00:00:00Z'
				},
				capabilities: {
					can_view_documents: true,
					can_view_objectives: false,
					can_view_comparisons: false
				},
				latest_task: {
					task_id: 'task_partial',
					collection_id: 'col_123',
					task_type: 'build',
					status: 'partial_success',
					current_stage: 'artifacts_ready',
					progress_percent: 100,
					errors: ['objective_candidates: provider timeout'],
					warnings: [],
					created_at: '2026-08-20T00:00:00Z',
					updated_at: '2026-08-20T00:01:00Z'
				}
			})
		);

		const workspace = await fetchWorkspaceOverview('col_123');

		expect(getCollectionWorkspaceState(workspace)).toBe('failed');
		expect(getWorkspaceSurfaceState(workspace, 'documents')).toBe('ready');
		expect(getWorkspaceSurfaceState(workspace, 'objectives')).toBe('failed');
	});

	it('shows only upload, document profiling, and Objective discovery in build progress', async () => {
		requestJson.mockResolvedValue(buildWorkspacePayload());
		const workspace = await fetchWorkspaceOverview('col_123');

		expect(buildOverviewPipelineSteps(workspace)).toEqual([
			{ key: 'upload', status: 'completed' },
			{ key: 'documents', status: 'completed' },
			{ key: 'objectives', status: 'completed' }
		]);
	});
});
