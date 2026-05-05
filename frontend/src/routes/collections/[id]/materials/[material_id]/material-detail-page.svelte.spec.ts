import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type MaterialDetailPageState = {
	params: {
		id: string;
		material_id: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: MaterialDetailPageState) => void>();
	let current: MaterialDetailPageState = {
		params: { id: 'col_123', material_id: 'mat_316l' },
		url: new URL('http://localhost/collections/col_123/materials/mat_316l')
	};

	return {
		pageStore: {
			subscribe(run: (value: MaterialDetailPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: MaterialDetailPageState) {
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

function requestPath(input: string | URL | Request) {
	const rawUrl =
		typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
	return new URL(rawUrl, 'http://localhost').pathname;
}

function materialProfilePayload() {
	return {
		collection_id: 'col_123',
		material_id: 'mat_316l',
		canonical_name: '316L stainless steel',
		aliases: ['316L'],
		state: 'ready',
		overview: {
			paper_count: 1,
			sample_count: 2,
			comparison_count: 1,
			evidence_count: 4,
			process_families: ['LPBF'],
			measured_properties: ['density'],
			variable_axes: ['scan speed']
		},
		papers: [
			{
				document_id: 'doc_1',
				title: 'Paper A',
				state: 'ready',
				sample_count: 2,
				process_families: ['LPBF'],
				measured_properties: ['density'],
				evidence_count: 4
			}
		],
		sample_matrix: {
			columns: [{ value_key: 'density', label: 'Density' }],
			rows: [
				{
					row_id: 'row_1',
					sample_id: 'S1',
					sample_label: 'Sample A',
					material: '316L stainless steel',
					process_context: { scan_speed: '800 mm/s' },
					values: {
						density: {
							display_value: '99.1%',
							status: 'observed',
							evidence_refs: [{ evidence_ref_id: 'ev_1', document_id: 'doc_1' }]
						}
					}
				}
			]
		},
		process_parameter_ranges: [
			{
				parameter: 'scan speed',
				display_range: '800-1200 mm/s',
				sample_count: 2,
				document_count: 1
			}
		],
		measured_properties: [
			{
				property: 'density',
				display_range: '98-99.1%',
				sample_count: 2,
				document_count: 1
			}
		],
		comparison_groups: [
			{
				group_id: 'grp_1',
				title: 'Scan speed vs density',
				material_system: '316L stainless steel',
				process_family: 'LPBF',
				variable_axis: 'scan speed',
				properties: ['density'],
				comparability_status: 'comparable',
				matrix: {
					matrix_id: 'mx_1',
					group_id: 'grp_1',
					rows: [
						{
							row_id: 'mx_row_1',
							document_id: 'doc_1',
							sample_id: 'S1',
							variable_value: '800 mm/s',
							property: 'density',
							result: { display_value: '99.1%', status: 'observed' }
						}
					]
				}
			}
		]
	};
}

describe('collections/[id]/materials/[material_id]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', material_id: 'mat_316l' },
			url: new URL('http://localhost/collections/col_123/materials/mat_316l')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/materials/mat_316l/research-view') {
				return jsonResponse(materialProfilePayload());
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});
	});

	it('renders material profile modules from the material profile endpoint', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: '316L stainless steel' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Papers using this material' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Sample matrix' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Comparisons for this material' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: '99.1%' }).first())
			.toBeInTheDocument();
		expect(
			fetchMock.mock.calls.map(([input]) => requestPath(input as string | URL | Request))
		).toEqual(['/api/v1/collections/col_123/materials/mat_316l/research-view']);
	});
});
