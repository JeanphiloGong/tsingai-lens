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
			comparisons: 'ready',
			protocol: 'not_applicable'
		},
		document_summary: {
			total_documents: 2,
			doc_type_counts: {
				experimental: 2,
				review: 0,
				mixed: 0,
				uncertain: 0
			},
			protocol_extractable_counts: {
				yes: 0,
				partial: 0,
				no: 2,
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
			procedure_blocks_generated: false,
			procedure_blocks_ready: false,
			protocol_steps_generated: false,
			protocol_steps_ready: false,
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
			can_download_graphml: false,
			can_view_protocol_steps: false,
			can_search_protocol: false,
			can_generate_sop: false
		},
		links: {
			workspace: '/collections/col_123',
			documents: '/collections/col_123/documents',
			results: '/collections/col_123/results',
			evidence: '/collections/col_123/evidence',
			comparisons: '/collections/col_123/comparisons',
			protocol: '/collections/col_123/protocol',
			graph: '/collections/col_123/graph'
		},
		...overrides
	};
}

describe('collections/[id]/+page.svelte', () => {
	let workspacePayload: Record<string, unknown>;

	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123')
		});
		workspacePayload = buildWorkspacePayload();
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

			return jsonResponse({ detail: 'collection not found: col_123' }, 404, 'Not Found');
		});
	});

	it('shows comparisons as the primary action when comparisons are available', async () => {
		render(Page);

		const primaryLink = browserPage.getByRole('link', { name: 'Enter comparison view' });
		await expect.element(primaryLink).toBeInTheDocument();
	});

	it('falls back to documents as the primary action when comparisons are unavailable', async () => {
		workspacePayload = buildWorkspacePayload({
			workflow: {
				documents: 'ready',
				results: 'ready',
				evidence: 'ready',
				comparisons: 'not_started',
				protocol: 'not_applicable'
			},
			capabilities: {
				can_view_documents: true,
				can_view_results: true,
				can_view_evidence: true,
				can_view_comparisons: false,
				can_view_graph: false,
				can_download_graphml: false,
				can_view_protocol_steps: false,
				can_search_protocol: false,
				can_generate_sop: false
			}
		});

		render(Page);

		const primaryLink = browserPage.getByRole('link', { name: 'View documents' });
		await expect.element(primaryLink).toBeInTheDocument();
	});

	it('falls back to documents as the primary action when only documents are available', async () => {
		workspacePayload = buildWorkspacePayload({
			workflow: {
				documents: 'ready',
				results: 'not_started',
				evidence: 'ready',
				comparisons: 'not_started',
				protocol: 'not_applicable'
			},
			capabilities: {
				can_view_documents: true,
				can_view_results: false,
				can_view_evidence: true,
				can_view_comparisons: false,
				can_view_graph: false,
				can_download_graphml: false,
				can_view_protocol_steps: false,
				can_search_protocol: false,
				can_generate_sop: false
			}
		});

		render(Page);

		const primaryLink = browserPage.getByRole('link', { name: 'View documents' });
		await expect.element(primaryLink).toBeInTheDocument();
	});
});
