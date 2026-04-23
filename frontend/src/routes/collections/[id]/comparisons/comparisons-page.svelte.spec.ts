import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type ComparisonsPageState = {
	params: {
		id: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: ComparisonsPageState) => void>();
	let current: ComparisonsPageState = {
		params: { id: 'col_123' },
		url: new URL('http://localhost/collections/col_123/comparisons')
	};

		return {
			pageStore: {
				subscribe(run: (value: ComparisonsPageState) => void) {
					run(current);
					subscribers.add(run);
					return () => subscribers.delete(run);
				}
			},
			setPage(next: ComparisonsPageState) {
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

describe('collections/[id]/comparisons/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/comparisons')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const rawUrl =
				typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
			const url = new URL(rawUrl, 'http://localhost');

			if (url.pathname === '/api/v1/collections/col_123/workspace') {
				return jsonResponse(buildWorkspacePayload());
			}
			if (url.pathname === '/api/v1/collections/col_123/comparisons') {
				return jsonResponse({
					collection_id: 'col_123',
					total: 1,
					count: 1,
					items: [
						{
							row_id: 'row_1',
							result_id: 'cres_1',
							collection_id: 'col_123',
							source_document_id: 'doc_1',
							display: {
								material_system_normalized: 'oxide cathode',
								process_normalized: '700 C anneal',
								variant_id: 'var_1',
								variant_label: 'Sample A',
								variable_axis: null,
								variable_value: null,
								property_normalized: 'conductivity',
								result_type: 'scalar',
								result_summary: '12 mS/cm',
								value: 12,
								unit: 'mS/cm',
								test_condition_normalized: 'EIS',
								baseline_reference: 'as-prepared',
								baseline_normalized: 'as-prepared'
							},
							evidence_bundle: {
								result_source_type: 'text',
								supporting_evidence_ids: ['ev_1'],
								supporting_anchor_ids: ['anc_1'],
								characterization_observation_ids: [],
								structure_feature_ids: []
							},
							assessment: {
								comparability_status: 'comparable',
								comparability_warnings: [],
								comparability_basis: [],
								requires_expert_review: false,
								assessment_epistemic_status: 'grounded'
							},
							uncertainty: {
								missing_critical_context: [],
								unresolved_fields: [],
								unresolved_baseline_link: false,
								unresolved_condition_link: false
							}
						}
					]
				});
			}

			return jsonResponse({ detail: 'collection not found: col_123' }, 404, 'Not Found');
		});
	});

	it('renders result drilldown links from comparison rows', async () => {
		render(Page);

		const resultLink = browserPage.getByRole('link', { name: 'Open results' });
		await expect.element(resultLink).toHaveAttribute('href', '/collections/col_123/results/cres_1');
	});
});
