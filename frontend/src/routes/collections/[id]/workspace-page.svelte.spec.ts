import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type WorkspacePageState = {
	params: {
		id: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: WorkspacePageState) => void>();
	let current: WorkspacePageState = {
		params: { id: 'col_123' },
		url: new URL('http://localhost/collections/col_123')
	};

	return {
		pageStore: {
			subscribe(run: (value: WorkspacePageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: WorkspacePageState) {
			current = next;
			for (const run of subscribers) run(next);
		},
		fetchMock: vi.fn()
	};
});

vi.mock('$app/stores', () => ({
	page: pageStore
}));

vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

function jsonResponse(body: unknown, status = 200, statusText = 'OK') {
	return new Response(JSON.stringify(body), {
		status,
		statusText,
		headers: {
			'Content-Type': 'application/json'
		}
	});
}

function buildWorkspacePayload(overrides: Record<string, unknown> = {}) {
	return {
		collection: {
			collection_id: 'col_123',
			name: 'Flow coverage collection',
			description: null,
			status: 'ready',
			updated_at: '2026-04-22T00:00:00Z'
		},
		file_count: 2,
		status_summary: 'ready',
		workflow: {
			documents: 'ready',
			objectives: 'ready'
		},
		document_summary: {
			total_documents: 2,
			doc_type_counts: {
				experimental: 2,
				review: 0,
				mixed: 0,
				uncertain: 0
			},
			warnings: []
		},
		warnings: [],
		artifacts: {
			source_documents_ready: true,
			document_profiles_ready: true,
			objective_candidates_ready: true,
			updated_at: '2026-04-22T00:00:00Z'
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

describe('collections/[id]/+page.svelte', () => {
	let workspacePayload: Record<string, unknown>;
	let objectivesPayload: Record<string, unknown> | null;

	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123')
		});
		workspacePayload = buildWorkspacePayload();
		objectivesPayload = null;
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const rawUrl =
				typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
			const url = new URL(rawUrl, 'http://localhost');

			if (url.pathname === '/api/v1/collections/col_123/workspace') {
				return jsonResponse(workspacePayload);
			}
			if (url.pathname === '/api/v1/collections/col_123/documents') {
				return jsonResponse({
					items: []
				});
			}
			if (url.pathname === '/api/v1/collections/col_123/objectives' && objectivesPayload) {
				return jsonResponse(objectivesPayload);
			}

			return jsonResponse({ detail: 'collection not found: col_123' }, 404, 'Not Found');
		});
	});

	it('shows objectives as the primary action when the collection is ready', async () => {
		render(Page);

		const primaryLink = browserPage.getByRole('link', { name: 'Enter objectives' }).first();
		await expect.element(primaryLink).toBeInTheDocument();
	});

	it('keeps objectives as the primary research action when comparisons are unavailable', async () => {
		workspacePayload = buildWorkspacePayload({
			capabilities: {
				can_view_documents: true,
				can_view_objectives: true,
				can_view_comparisons: false
			}
		});

		render(Page);

		const primaryLink = browserPage.getByRole('link', { name: 'Enter objectives' }).first();
		await expect.element(primaryLink).toBeInTheDocument();
	});

	it('requires processing to finish when only document profiles are available', async () => {
		workspacePayload = buildWorkspacePayload({
			workflow: {
				documents: 'ready',
				objectives: 'not_started'
			},
			capabilities: {
				can_view_documents: true,
				can_view_objectives: false,
				can_view_comparisons: false
			}
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('button', { name: 'Start processing' }).first())
			.toBeInTheDocument();
	});

	it('distinguishes a completed build with zero Objective candidates from completed analysis', async () => {
		workspacePayload = buildWorkspacePayload({
			workflow: {
				documents: 'ready',
				objectives: 'ready'
			},
			capabilities: {
				can_view_documents: true,
				can_view_objectives: true,
				can_view_comparisons: true
			}
		});
		objectivesPayload = {
			collection_id: 'col_123',
			objectives: []
		};

		render(Page);

		await vi.waitFor(() => {
			expect(
				fetchMock.mock.calls.some(([input]) =>
					String(input).includes('/collections/col_123/objectives')
				)
			).toBe(true);
		});
		await expect
			.element(browserPage.getByRole('heading', { name: 'No research objective candidates' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText(/Objective Evidence analysis has not started/))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'View evidence' }))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Evidence extraction complete'))
			.not.toBeInTheDocument();
	});

	it('shows build subprogress when the latest task includes progress detail', async () => {
		workspacePayload = buildWorkspacePayload({
			collection: {
				collection_id: 'col_123',
				name: 'Flow coverage collection',
				description: null,
				status: 'running',
				updated_at: '2026-04-22T00:00:00Z'
			},
			workflow: {
				documents: 'processing',
				objectives: 'processing'
			},
			latest_task: {
				task_id: 'task_123',
				collection_id: 'col_123',
				task_type: 'build',
				status: 'running',
				current_stage: 'objective_paper_skim_started',
				progress_percent: 76,
				progress_detail: {
					phase: 'objective_paper_skim_started',
					current: 18,
					total: 1036,
					unit: 'routes',
					message: 'Extracting objective evidence units from routed sources.'
				},
				output_path: null,
				errors: [],
				warnings: [],
				created_at: '2026-04-22T00:00:00Z',
				updated_at: '2026-04-22T00:00:01Z',
				started_at: '2026-04-22T00:00:00Z',
				finished_at: null
			}
		});

		render(Page);

		await expect
			.element(browserPage.getByText('Extracting objective evidence units from routed sources.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('18 / 1036 routes')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Estimated progress')).toBeInTheDocument();
	});

	it('offers retry instead of start when the latest build partially succeeded', async () => {
		workspacePayload = buildWorkspacePayload({
			status_summary: 'partial_ready',
			workflow: {
				documents: 'not_started',
				objectives: 'failed'
			},
			latest_task: {
				task_id: 'task_partial',
				collection_id: 'col_123',
				task_type: 'build',
				status: 'partial_success',
				current_stage: 'artifacts_ready',
				progress_percent: 100,
				progress_detail: {
					phase: 'artifacts_ready',
					unit: 'steps',
					message: 'Build artifacts are ready.'
				},
				output_path: '/tmp/col_123',
				errors: ['document_profiles: Connection error.'],
				warnings: [],
				created_at: '2026-07-19T05:23:33Z',
				updated_at: '2026-07-19T05:24:42Z',
				started_at: '2026-07-19T05:23:33Z',
				finished_at: '2026-07-19T05:24:42Z'
			}
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('button', { name: 'Retry processing' }).first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Start processing' }))
			.not.toBeInTheDocument();
	});

});
