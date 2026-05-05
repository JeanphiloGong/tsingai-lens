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

function researchPayload() {
	return {
		collection_id: 'col_123',
		state: 'ready',
		overview: {
			document_count: 2,
			material_systems: ['oxide cathode']
		},
		comparable_groups: [
			{
				group_id: 'grp_1',
				title: 'Anneal temperature vs conductivity',
				material_system: 'oxide cathode',
				process_family: 'annealing',
				variable_axis: 'temperature',
				fixed_conditions: {
					atmosphere: 'air'
				},
				properties: ['conductivity'],
				documents: ['doc_1', 'doc_2'],
				samples: ['S1', 'S2'],
				comparability_status: 'comparable',
				matrix: {
					matrix_id: 'matrix_1',
					group_id: 'grp_1',
					rows: [
						{
							row_id: 'mx_row_1',
							document_id: 'doc_1',
							sample_id: 'S1',
							material: 'oxide cathode',
							process_context: { process: 'annealing' },
							variable_value: '700 C',
							test_condition: 'EIS',
							property: 'conductivity',
							result: {
								display_value: '12 mS/cm',
								status: 'observed',
								evidence_refs: [
									{
										evidence_ref_id: 'ev_1',
										document_id: 'doc_1',
										locator: 'Table 1'
									}
								]
							}
						}
					]
				}
			}
		]
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

			if (url.pathname === '/api/v1/collections/col_123/research-view') {
				return jsonResponse(researchPayload());
			}

			return jsonResponse({ detail: 'collection not found: col_123' }, 404, 'Not Found');
		});
	});

	it('renders comparable groups and cross-paper matrix from research view', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Comparable groups' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Anneal temperature vs conductivity' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByRole('button', { name: '12 mS/cm' })).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('cell', { name: 'process: annealing' }))
			.toBeInTheDocument();
	});
});
