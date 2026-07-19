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
			results: 'ready',
			evidence: 'ready',
			comparisons: 'ready'
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
			output_path: '/tmp/col_123',
			documents_generated: true,
			documents_ready: true,
			document_profiles_generated: true,
			document_profiles_ready: true,
			evidence_cards_generated: true,
			evidence_cards_ready: true,
			comparable_results_generated: true,
			comparable_results_ready: true,
			collection_comparable_results_generated: true,
			collection_comparable_results_ready: true,
			collection_comparable_results_stale: false,
			comparison_rows_generated: true,
			comparison_rows_ready: true,
			comparison_rows_stale: false,
			graph_generated: false,
			graph_ready: false,
			graph_stale: false,
			updated_at: '2026-04-22T00:00:00Z'
		},
		latest_task: null,
		recent_tasks: [],
		capabilities: {
			can_view_documents: true,
			can_view_results: true,
			can_view_evidence: true,
			can_view_comparisons: true,
			can_view_graph: false,
			can_download_graphml: false
		},
		links: {
			workspace: '/collections/col_123',
			documents: '/collections/col_123/documents',
			results: '/collections/col_123/results',
			evidence: '/collections/col_123/evidence',
			comparisons: '/collections/col_123/comparisons',
			graph: '/collections/col_123/graph'
		},
		...overrides
	};
}

describe('collections/[id]/+page.svelte', () => {
	let workspacePayload: Record<string, unknown>;
	let researchViewPayload: Record<string, unknown> | null;

	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123')
		});
		workspacePayload = buildWorkspacePayload();
		researchViewPayload = null;
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const rawUrl =
				typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
			const url = new URL(rawUrl, 'http://localhost');

			if (url.pathname === '/api/v1/collections/col_123/workspace') {
				return jsonResponse(workspacePayload);
			}
			if (url.pathname === '/api/v1/collections/col_123/files') {
				return jsonResponse({
					count: 0,
					items: []
				});
			}
			if (url.pathname === '/api/v1/collections/col_123/research-view' && researchViewPayload) {
				return jsonResponse(researchViewPayload);
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
			workflow: {
				documents: 'ready',
				results: 'ready',
				evidence: 'ready',
				comparisons: 'not_started'
			},
			capabilities: {
				can_view_documents: true,
				can_view_results: true,
				can_view_evidence: true,
				can_view_comparisons: false,
				can_view_graph: false,
				can_download_graphml: false
			}
		});

		render(Page);

		const primaryLink = browserPage.getByRole('link', { name: 'Enter objectives' }).first();
		await expect.element(primaryLink).toBeInTheDocument();
	});

	it('keeps objectives as the primary research action when only documents are available', async () => {
		workspacePayload = buildWorkspacePayload({
			workflow: {
				documents: 'ready',
				results: 'not_started',
				evidence: 'ready',
				comparisons: 'not_started'
			},
			capabilities: {
				can_view_documents: true,
				can_view_results: false,
				can_view_evidence: true,
				can_view_comparisons: false,
				can_view_graph: false,
				can_download_graphml: false
			}
		});

		render(Page);

		const primaryLink = browserPage.getByRole('link', { name: 'Enter objectives' }).first();
		await expect.element(primaryLink).toBeInTheDocument();
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
				results: 'processing',
				evidence: 'processing',
				comparisons: 'processing'
			},
			latest_task: {
				task_id: 'task_123',
				collection_id: 'col_123',
				task_type: 'build',
				status: 'running',
				current_stage: 'objective_evidence_units_started',
				progress_percent: 76,
				progress_detail: {
					phase: 'objective_evidence_units_started',
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
				results: 'not_started',
				evidence: 'not_started',
				comparisons: 'not_started'
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

	it('summarizes repeated research-view warnings in the overview', async () => {
		researchViewPayload = {
			collection_id: 'col_123',
			state: 'empty',
			overview: {
				document_count: 2,
				sample_count: 0,
				measurement_count: 0,
				evidence_count: 0,
				material_systems: [],
				process_families: [],
				variable_axes: [],
				measured_properties: []
			},
			paper_coverage: [],
			comparable_groups: [],
			warnings: [
				{
					warning_id: 'warning:no_measurement_results:paper:doc_1',
					code: 'no_measurement_results',
					severity: 'warning',
					scope: 'paper',
					message: 'No measurement results were detected for this paper.',
					related_object_ids: ['doc_1']
				},
				{
					warning_id: 'warning:no_measurement_results:paper:doc_2',
					code: 'no_measurement_results',
					severity: 'warning',
					scope: 'paper',
					message: 'No measurement results were detected for this paper.',
					related_object_ids: ['doc_2']
				}
			]
		};

		render(Page);

		await expect
			.element(
				browserPage.getByText('No measurement results were detected for this paper. (2 papers)')
			)
			.toBeInTheDocument();
	});
});
