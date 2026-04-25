import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type ResultsPageState = {
	params: {
		id: string;
	};
	url: URL;
};

const { pageStore, setPage, goto, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: ResultsPageState) => void>();
	let current: ResultsPageState = {
		params: { id: 'col_123' },
		url: new URL('http://localhost/collections/col_123/results')
	};

	return {
		pageStore: {
			subscribe(run: (value: ResultsPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: ResultsPageState) {
			current = next;
			for (const run of subscribers) run(next);
		},
		goto: vi.fn(),
		fetchMock: vi.fn()
	};
});

vi.mock('$app/stores', () => ({
	page: pageStore
}));

vi.mock('$app/navigation', () => ({
	goto
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

function buildWorkspacePayload() {
	return {
		collection: {
			collection_id: 'col_123',
			name: 'Flow coverage collection'
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
		}
	};
}

describe('collections/[id]/results/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/results')
		});
		goto.mockReset();
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const rawUrl =
				typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
			const url = new URL(rawUrl, 'http://localhost');

			if (url.pathname === '/api/v1/collections/col_123/workspace') {
				return jsonResponse(buildWorkspacePayload());
			}
			if (url.pathname === '/api/v1/collections/col_123/results') {
				return jsonResponse({
					collection_id: 'col_123',
					total: 2,
					count: 2,
					items: [
						{
							result_id: 'cres_1',
							document_id: 'doc_1',
							document_title: 'Paper A',
							material_label: 'oxide cathode',
							variant_label: 'Sample A',
							property: 'conductivity',
							value: 12,
							unit: 'mS/cm',
							summary: '12 mS/cm',
							baseline: 'as-prepared',
							test_condition: 'EIS',
							process: '700 C',
							traceability_status: 'direct',
							comparability_status: 'comparable',
							requires_expert_review: false
						},
						{
							result_id: 'cres_2',
							document_id: 'doc_2',
							document_title: 'Paper B',
							material_label: 'layered oxide',
							variant_label: null,
							property: 'capacity retention',
							value: 91,
							unit: '%',
							summary: '91% after 200 cycles',
							baseline: 'baseline B',
							test_condition: '200 cycles',
							process: 'coated',
							traceability_status: 'direct',
							comparability_status: 'limited',
							requires_expert_review: true
						}
					]
				});
			}

			return jsonResponse({ detail: 'collection not found: col_123' }, 404, 'Not Found');
		});
	});

	it('renders extracted result cards with source and comparison actions', async () => {
		render(Page);

		await expect.element(browserPage.getByText('Extracted Results')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Source evidence').nth(0)).toBeInTheDocument();

		const sourceLink = browserPage.getByRole('link', { name: 'View source' }).nth(0);
		await expect
			.element(sourceLink)
			.toHaveAttribute(
				'href',
				'/collections/col_123/documents/doc_1?result_id=cres_1&return_to=%2Fcollections%2Fcol_123%2Fresults'
			);

		const comparisonLink = browserPage.getByRole('link', { name: 'Enter comparison' }).nth(0);
		await expect
			.element(comparisonLink)
			.toHaveAttribute(
				'href',
				'/collections/col_123/comparisons?material_system_normalized=oxide+cathode&property_normalized=conductivity&baseline_normalized=as-prepared&test_condition_normalized=EIS'
			);
	});

	it('updates the route query when the material filter changes', async () => {
		render(Page);

		const sourceLink = browserPage.getByRole('link', { name: 'View source' }).nth(0);
		await expect.element(sourceLink).toBeInTheDocument();

		const filter = browserPage.getByLabelText('Material system');
		await filter.selectOptions('Layered oxide');

		expect(goto).toHaveBeenCalledWith(
			'/collections/col_123/results?material_system_normalized=Layered+oxide',
			expect.objectContaining({
				keepFocus: true,
				noScroll: true,
				replaceState: true
			})
		);
	});
});
