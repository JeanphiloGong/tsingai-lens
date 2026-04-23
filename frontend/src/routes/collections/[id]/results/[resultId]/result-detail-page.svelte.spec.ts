import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type ResultDetailPageState = {
	params: {
		id: string;
		resultId: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: ResultDetailPageState) => void>();
	let current: ResultDetailPageState = {
		params: { id: 'col_123', resultId: 'cres_1' },
		url: new URL('http://localhost/collections/col_123/results/cres_1')
	};

		return {
			pageStore: {
				subscribe(run: (value: ResultDetailPageState) => void) {
					run(current);
					subscribers.add(run);
					return () => subscribers.delete(run);
				}
			},
			setPage(next: ResultDetailPageState) {
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

describe('collections/[id]/results/[resultId]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', resultId: 'cres_1' },
			url: new URL('http://localhost/collections/col_123/results/cres_1')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const rawUrl =
				typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
			const url = new URL(rawUrl, 'http://localhost');

			if (url.pathname === '/api/v1/collections/col_123/workspace') {
				return jsonResponse(buildWorkspacePayload());
			}
			if (url.pathname === '/api/v1/collections/col_123/results/cres_1') {
				return jsonResponse({
					result_id: 'cres_1',
					document: {
						document_id: 'doc_1',
						title: 'Paper A',
						source_filename: 'paper-a.pdf'
					},
					material: {
						label: 'oxide cathode',
						variant_id: 'var_1',
						variant_label: 'Sample A'
					},
					measurement: {
						property: 'conductivity',
						value: 12,
						unit: 'mS/cm',
						result_type: 'scalar',
						summary: '12 mS/cm',
						statistic_type: null,
						uncertainty: null
					},
					context: {
						process: '700 C',
						baseline: 'as-prepared',
						baseline_reference: 'as-prepared',
						test_condition: 'EIS',
						axis_name: null,
						axis_value: null,
						axis_unit: null
					},
					assessment: {
						comparability_status: 'comparable',
						warnings: [],
						basis: [],
						missing_context: [],
						requires_expert_review: false,
						assessment_epistemic_status: 'grounded'
					},
					evidence: [
						{
							evidence_id: 'ev_1',
							traceability_status: 'direct',
							source_type: 'text',
							anchor_ids: ['anc_1']
						}
					],
					actions: {
						open_document: '/collections/col_123/documents/doc_1',
						open_comparisons:
							'/collections/col_123/comparisons?property_normalized=conductivity',
						open_evidence: null
					}
				});
			}

			return jsonResponse({ detail: 'collection not found: col_123' }, 404, 'Not Found');
		});
	});

	it('renders document drilldown and comparison return actions on result detail', async () => {
		render(Page);

		const documentTitle = browserPage.getByText('Paper A');
		await expect.element(documentTitle).toBeInTheDocument();

		const comparisonLink = browserPage.getByRole('link', { name: 'Open comparisons' });
		await expect.element(comparisonLink).toHaveAttribute(
			'href',
			'/collections/col_123/comparisons?property_normalized=conductivity'
		);

		const sourceLink = browserPage.getByRole('link', { name: 'View source evidence' });
		await expect.element(sourceLink).toHaveAttribute(
			'href',
			'/collections/col_123/documents/doc_1?evidence_id=ev_1&return_to=%2Fcollections%2Fcol_123%2Fresults%2Fcres_1'
		);
	});
});
