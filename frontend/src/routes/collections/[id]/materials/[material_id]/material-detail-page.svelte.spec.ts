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
			evidence_count: 18,
			process_families: ['LPBF/SLM'],
			measured_properties: [
				'relative density',
				'hardness',
				'yield strength',
				'tensile strength',
				'elongation'
			],
			variable_axes: ['scan strategy']
		},
		papers: [
			{
				document_id: 'doc_1',
				title: 'Paper A',
				source_filename: '316L Stainless Steel Process Study.pdf',
				state: 'ready',
				sample_count: 2,
				process_families: ['LPBF/SLM'],
				measured_properties: ['relative density', 'hardness', 'yield strength'],
				evidence_count: 18
			}
		],
		sample_matrix: {
			columns: [
				{ value_key: 'relative_density', label: 'Relative density', unit: '%' },
				{ value_key: 'hardness', label: 'Hardness', unit: 'HV' },
				{ value_key: 'yield_strength', label: 'Yield strength', unit: 'MPa' },
				{ value_key: 'tensile_strength', label: 'Tensile strength', unit: 'MPa' },
				{ value_key: 'elongation', label: 'Elongation', unit: '%' }
			],
			rows: [
				{
					row_id: 'row_1',
					sample_id: 'S001',
					sample_label: 'S001',
					material: '316L stainless steel',
					process_context: {
						scan_strategy: 'Alternating strategy A',
						laser_power_w: '200',
						scan_speed_mm_s: '800',
						energy_density_j_mm3: '70',
						layer_thickness_um: '30',
						hatch_spacing_um: '0.12',
						oxygen_level_ppm: '100 ppm'
					},
					values: {
						relative_density: {
							display_value: '95.4%',
							status: 'observed',
							confidence: 0.96,
							evidence_refs: [
								{
									evidence_ref_id: 'ev_density_s001',
									document_id: 'doc_1',
									source_kind: 'table',
									locator: 'Table 2',
									confidence: 0.96
								}
							]
						},
						hardness: {
							display_value: '215.6',
							status: 'observed',
							confidence: 0.95,
							evidence_refs: [
								{
									evidence_ref_id: 'ev_hardness_s001',
									document_id: 'doc_1',
									source_kind: 'table',
									locator: 'Table 2',
									confidence: 0.95
								}
							]
						},
						yield_strength: {
							display_value: '236.65',
							status: 'observed',
							confidence: 0.9,
							evidence_refs: [
								{
									evidence_ref_id: 'ev_yield_s001',
									document_id: 'doc_1',
									source_kind: 'table',
									locator: 'Table 2',
									confidence: 0.9
								}
							]
						},
						tensile_strength: {
							display_value: '375.13',
							status: 'observed',
							confidence: 0.91,
							evidence_refs: [
								{
									evidence_ref_id: 'ev_uts_s001',
									document_id: 'doc_1',
									source_kind: 'table',
									locator: 'Table 2',
									confidence: 0.91
								}
							]
						},
						elongation: {
							display_value: '7.21%',
							status: 'observed',
							confidence: 0.9,
							evidence_refs: [
								{
									evidence_ref_id: 'ev_elongation_s001',
									document_id: 'doc_1',
									source_kind: 'table',
									locator: 'Table 2',
									confidence: 0.9
								}
							]
						}
					}
				},
				{
					row_id: 'row_2',
					sample_id: 'S002',
					sample_label: 'S002',
					material: '316L stainless steel',
					process_context: {
						scan_strategy: 'Island strategy B',
						laser_power_w: '200',
						scan_speed_mm_s: '800',
						energy_density_j_mm3: '70',
						layer_thickness_um: '30',
						hatch_spacing_um: '0.12',
						oxygen_level_ppm: '100 ppm'
					},
					values: {
						relative_density: {
							display_value: '97.7%',
							status: 'observed',
							confidence: 0.94,
							evidence_refs: [
								{
									evidence_ref_id: 'ev_density_s002',
									document_id: 'doc_1',
									source_kind: 'table',
									locator: 'Table 2',
									confidence: 0.94
								}
							]
						},
						hardness: {
							display_value: '192.3',
							status: 'observed',
							confidence: 0.92,
							evidence_refs: [
								{
									evidence_ref_id: 'ev_hardness_s002',
									document_id: 'doc_1',
									source_kind: 'table',
									locator: 'Table 2',
									confidence: 0.92
								}
							]
						},
						yield_strength: {
							display_value: '159.97',
							status: 'observed',
							confidence: 0.89,
							evidence_refs: [
								{
									evidence_ref_id: 'ev_yield_s002',
									document_id: 'doc_1',
									source_kind: 'table',
									locator: 'Table 2',
									confidence: 0.89
								}
							]
						},
						tensile_strength: {
							display_value: '196.78',
							status: 'observed',
							confidence: 0.88,
							evidence_refs: [
								{
									evidence_ref_id: 'ev_uts_s002',
									document_id: 'doc_1',
									source_kind: 'table',
									locator: 'Table 2',
									confidence: 0.88
								}
							]
						},
						elongation: {
							display_value: '1.79%',
							status: 'observed',
							confidence: 0.87,
							evidence_refs: [
								{
									evidence_ref_id: 'ev_elongation_s002',
									document_id: 'doc_1',
									source_kind: 'table',
									locator: 'Table 2',
									confidence: 0.87
								}
							]
						}
					}
				}
			]
		},
		process_parameter_ranges: [
			{
				parameter: 'scan speed',
				display_range: '800 mm/s',
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
				variable_axis: 'scan strategy',
				properties: ['density'],
				comparability_status: 'comparable',
				matrix: {
					matrix_id: 'mx_1',
					group_id: 'grp_1',
					rows: [
						{
							row_id: 'mx_row_1',
							document_id: 'doc_1',
							sample_id: 'S001',
							variable_value: 'Alternating strategy A',
							property: 'density',
							result: { display_value: '95.4%', status: 'observed' }
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
			.element(browserPage.getByRole('heading', { name: 'Key findings' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Trend interpretation' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Supporting data: performance matrix' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Evidence locator' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('S001 · Alternating strategy A').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('S002 · Island strategy B').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Highest density does not align with highest strength'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: '95.4%' }).first())
			.toBeInTheDocument();
		expect(
			fetchMock.mock.calls.map(([input]) => requestPath(input as string | URL | Request))
		).toEqual(['/api/v1/collections/col_123/materials/mat_316l/research-view']);
	});

	it('opens evidence details from a performance value', async () => {
		render(Page);

		const densityValue = browserPage.getByRole('button', { name: '95.4%' }).first();
		await expect.element(densityValue).toBeInTheDocument();
		await densityValue.click({ force: true });

		await expect
			.element(browserPage.getByRole('heading', { name: 'Evidence detail' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Relative density = 95.4%')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Table 2' }).last())
			.toBeInTheDocument();
	});
});
