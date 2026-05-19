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

function requestMethod(input: string | URL | Request, init?: RequestInit) {
	return input instanceof Request ? input.method : init?.method ?? 'GET';
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
					test_condition: {
						details:
							'This long method paragraph should stay out of the best-parameter chain because it belongs in source evidence rather than the compact result chain.',
						method: 'Tensile testing',
						standard: 'ASTM E8'
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
				document_count: 1,
				evidence_refs: [
					{
						evidence_ref_id: 'ev_density_summary',
						document_id: 'doc_1',
						source_kind: 'text_window',
						locator: 'Section 3.1',
						confidence: 0.86
					}
				]
			},
			{
				property: 'ultimate tensile strength',
				display_range: '610 MPa',
				unit: 'MPa',
				sample_count: 0,
				document_count: 1,
				evidence_refs: [
					{
						evidence_ref_id: 'ev_uts_summary',
						document_id: 'doc_1',
						source_kind: 'text_window',
						locator: 'Section 3.2',
						confidence: 0.9
					}
				]
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
		],
		report_package: {
			schema_version: 'material_report_package.v1',
			status: 'partial',
			title: '316L stainless steel material-state report',
			material_id: 'mat_316l',
			canonical_name: '316L stainless steel',
			summary:
				'316L stainless steel has 2 resolved material-state chains covering density and mechanical response.',
			paper_contributions: [
				{
					document_id: 'doc_1',
					title: 'Paper A',
					source_filename: '316L Stainless Steel Process Study.pdf',
					sample_count: 2,
					measured_properties: ['relative density', 'hardness', 'yield strength'],
					contribution_summary:
						'Paper A contributes 2 material-state sample(s) with relative density, hardness, yield strength measurements.'
				}
			],
			material_state_chains: [
				{
					chain_id: 'material-chain:S001',
					document_id: 'doc_1',
					sample_id: 'S001',
					sample_label: 'S001',
					material: '316L stainless steel',
					material_state: 'S001',
					preparation_context: {
						scan_strategy: 'Alternating strategy A',
						laser_power_w: '200',
						scan_speed_mm_s: '800'
					},
					test_conditions: {
						method: 'Tensile testing',
						standard: 'ASTM E8'
					},
					performance_results: [
						{
							property: 'hardness',
							display_value: '215.6',
							status: 'observed',
							evidence_refs: [
								{
									evidence_ref_id: 'ev_hardness_s001',
									document_id: 'doc_1',
									source_kind: 'table',
									locator: 'Table 2',
									confidence: 0.95
								}
							]
						}
					],
					source_evidence: [
						{
							evidence_ref_id: 'ev_hardness_s001',
							document_id: 'doc_1',
							source_kind: 'table',
							locator: 'Table 2',
							confidence: 0.95
						}
					],
					comparability_boundary: [
						'Compare only within Paper A tensile and hardness conditions.'
					],
					confidence: 0.95,
					unresolved_fields: []
				}
			],
			limitations: ['S002 is missing test_conditions.'],
			source_refs: [
				{
					evidence_ref_id: 'ev_hardness_s001',
					document_id: 'doc_1',
					source_kind: 'table',
					locator: 'Table 2',
					confidence: 0.95
				}
			]
		}
	};
}

function materialReviewReportPayload(overrides: Record<string, unknown> = {}) {
	return {
		report_id: 'mrp_mat_316l',
		collection_id: 'col_123',
		material_id: 'mat_316l',
		status: 'ready',
		message: 'Review draft is ready.',
		title: '316L stainless steel review draft',
		language: 'en',
		report_type: 'review_draft',
		include_appendix: true,
		readiness: 'preliminary',
		readiness_reason: '1 paper and 2 samples are available.',
		data_version: 'material_profile_v1',
		warnings: [],
		created_at: '2026-05-05T15:32:00',
		updated_at: '2026-05-05T15:33:00',
		generated_at: '2026-05-05T15:33:00',
		pdf_url: '/api/v1/collections/col_123/materials/mat_316l/review-report.pdf',
		markdown_url: '/api/v1/collections/col_123/materials/mat_316l/review-report.md',
		...overrides
	};
}

describe('collections/[id]/materials/[material_id]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', material_id: 'mat_316l' },
			url: new URL('http://localhost/collections/col_123/materials/mat_316l')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);

			if (path === '/api/v1/collections/col_123/materials/mat_316l/research-view') {
				return jsonResponse(materialProfilePayload());
			}

			if (
				path === '/api/v1/collections/col_123/materials/mat_316l/review-report' &&
				method === 'GET'
			) {
				return jsonResponse({ detail: { code: 'material_review_report_not_found' } }, 404);
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
			.element(browserPage.getByRole('heading', { name: 'Material report overview' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Representative material states' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Material questions' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Preparation and post-treatment').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText(/Scan strategy Alternating strategy A/).first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText(/studied through LPBF\/SLM/).first())
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('ASTM E8').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('This long method paragraph should stay out'))
			.not.toBeInTheDocument();
		await expect.element(browserPage.getByText('hardness').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('215.6').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Compare only within Paper A tensile and hardness conditions.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Traceback').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Comparable groups' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Supporting data matrix' }))
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
			.element(browserPage.getByRole('heading', { name: 'Densification and porosity' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Strength, ductility, and hardness' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: '95.4%' }).first())
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('+2 more').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Select a material, process variable, sample, property, or finding to reveal related evidence anchors.'))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Performance response').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('215.6').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Research chain map'))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Best parameter chain'))
			.not.toBeInTheDocument();
		expect(
			fetchMock.mock.calls.map(([input]) => requestPath(input as string | URL | Request))
			).toEqual(['/api/v1/collections/col_123/materials/mat_316l/research-view']);
	});

	it('cleans table-origin labels in the representative material state report', async () => {
		const payload: any = materialProfilePayload();
		payload.sample_matrix.rows = [
			{
				row_id: 'row_table_origin',
				sample_id: 'as_slm_140_100',
				sample_label: 'as-SLM(140/ 100)',
				material: '316L stainless steel',
				process_context: {
					'Table 2 (continued) > Laser energy density (J/mm3)': '139',
					'Table 2 (continued) > Laser power (W)': '140',
					'Table 2 (continued) > Scan speed (mm/s)': '280'
				},
				test_condition: {},
				values: {
					hardness: {
						display_value: '198.4 HV',
						value: '198.4',
						status: 'observed',
						confidence: 0.94,
						evidence_refs: [
							{
								evidence_ref_id: 'ev_table_origin_hardness',
								document_id: 'doc_1',
								source_kind: 'table',
								locator: 'Table 2',
								confidence: 0.94
							}
						]
					}
				},
				evidence_refs: []
			}
		];
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/materials/mat_316l/research-view') {
				return jsonResponse(payload);
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Representative material states' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('as-SLM(140/100)').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Energy density').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('139 J/mm3').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Laser power').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('140 W').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Scan speed').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('280 mm/s').first()).toBeInTheDocument();
		const processStep = Array.from(document.querySelectorAll('.chain-step')).find((step) =>
			step.textContent?.includes('Preparation and post-treatment')
		);
		expect(processStep?.textContent).not.toContain('Table 2');
	});

	it('renders top-level measured property evidence when sample rows have no value cells', async () => {
		const payload: any = materialProfilePayload();
		payload.overview.measured_properties = ['elongation', 'ultimate tensile strength'];
		payload.sample_matrix.columns = [];
		payload.sample_matrix.rows = payload.sample_matrix.rows.map((row: Record<string, unknown>) => ({
			...row,
			values: {}
		}));
		payload.measured_properties = [
			{
				property: 'elongation',
				display_range: '33 %',
				unit: '%',
				sample_count: 0,
				document_count: 1,
				evidence_refs: [
					{
						evidence_ref_id: 'ev_elongation_summary',
						document_id: 'doc_1',
						source_kind: 'text_window',
						locator: 'Section 3.1',
						confidence: 0.9
					}
				]
			},
			{
				property: 'ultimate tensile strength',
				display_range: '610 MPa',
				unit: 'MPa',
				sample_count: 0,
				document_count: 1,
				evidence_refs: [
					{
						evidence_ref_id: 'ev_uts_summary',
						document_id: 'doc_1',
						source_kind: 'text_window',
						locator: 'Section 3.2',
						confidence: 0.9
					}
				]
			}
		];
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/materials/mat_316l/research-view') {
				return jsonResponse(payload);
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: '316L stainless steel' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('610 MPa').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Strength, ductility, and hardness' }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(/Collection summary: Tensile strength 610 MPa/)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Collection summary').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Collection summary Elongation' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Collection summary Tensile strength' }))
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Collection summary Elongation' }).click();
		await expect.element(browserPage.getByText('Elongation = 33 %').first()).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Collection-level values are available, but sample-level paired values are not comparable yet:'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Available collection summary values:').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('1 sample(s), 2 measured property column(s).'))
			.toBeInTheDocument();
		expect(
			fetchMock.mock.calls.map(([input]) => requestPath(input as string | URL | Request))
		).toEqual(['/api/v1/collections/col_123/materials/mat_316l/research-view']);
	});

	it('focuses sparse objective-derived material matrices on populated sample values', async () => {
		const payload: any = materialProfilePayload();
		payload.sample_matrix.rows = [
			{
				row_id: 'row_non_preheated',
				sample_id: 'non_preheated',
				sample_label: 'Non-preheated',
				material: '316L stainless steel',
				process_context: {},
				values: {
					yield_strength: {
						display_value: '448 MPa',
						status: 'observed',
						evidence_refs: [{ evidence_ref_id: 'ev_np_yield', document_id: 'doc_1' }]
					},
					elongation: {
						display_value: '72%',
						status: 'observed',
						evidence_refs: [{ evidence_ref_id: 'ev_np_el', document_id: 'doc_1' }]
					}
				},
				evidence_refs: []
			},
			{
				row_id: 'row_preheated',
				sample_id: 'preheated',
				sample_label: 'Preheated',
				material: '316L stainless steel',
				process_context: {},
				values: {
					yield_strength: {
						display_value: '465 MPa',
						status: 'observed',
						evidence_refs: [{ evidence_ref_id: 'ev_p_yield', document_id: 'doc_1' }]
					},
					elongation: {
						display_value: '82%',
						status: 'observed',
						evidence_refs: [{ evidence_ref_id: 'ev_p_el', document_id: 'doc_1' }]
					}
				},
				evidence_refs: []
			},
			...Array.from({ length: 12 }, (_, index) => ({
				row_id: `row_sparse_${index}`,
				sample_id: `sparse_${index}`,
				sample_label: `Sparse sample ${index}`,
				material: '316L stainless steel',
				process_context: {},
				values: {
					[`unselected_property_${index}`]: {
						display_value: `${index}`,
						status: 'observed',
						evidence_refs: [{ evidence_ref_id: `ev_sparse_${index}`, document_id: 'doc_1' }]
					}
				},
				evidence_refs: []
			}))
		];
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/materials/mat_316l/research-view') {
				return jsonResponse(payload);
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: '316L stainless steel' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('448 MPa').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('465 MPa').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Sparse sample 0')).not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('2 sample(s), 4 measured property column(s).'))
			.toBeInTheDocument();
	});

	it('caps large performance matrices to high-signal rows', async () => {
		const payload: any = materialProfilePayload();
		payload.sample_matrix.rows = [
			...payload.sample_matrix.rows,
			...Array.from({ length: 24 }, (_, index) => ({
				row_id: `row_low_signal_${index}`,
				sample_id: `low_signal_${index}`,
				sample_label: `Low signal ${index}`,
				material: '316L stainless steel',
				process_context: {},
				values: {
					relative_density: {
						display_value: `${80 + index / 10}%`,
						status: 'observed',
						evidence_refs: [{ evidence_ref_id: `ev_low_signal_${index}`, document_id: 'doc_1' }]
					}
				},
				evidence_refs: []
			}))
		];
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/materials/mat_316l/research-view') {
				return jsonResponse(payload);
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: '316L stainless steel' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('S001 · Alternating strategy A').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Low signal 0')).not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('2 sample(s), 5 measured property column(s).'))
			.toBeInTheDocument();
	});

	it('does not promote narrative observations with embedded numbers into representative material states', async () => {
		const payload: any = materialProfilePayload();
		payload.sample_matrix.columns = [
			{ value_key: 'elongation', label: 'Elongation', unit: '%' }
		];
		payload.sample_matrix.rows = [
			{
				row_id: 'row_text_observation',
				sample_id: 'text_observation',
				sample_label: '135 W-750 mm/s',
				material: '316L stainless steel',
				process_context: {},
				values: {
					elongation: {
						display_value:
							'The relatively low porosity levels in the 135 W-750 mm/s sample increase ductility by about 10%.',
						status: 'observed',
						confidence: 0.89,
						evidence_refs: [{ evidence_ref_id: 'ev_text_observation', document_id: 'doc_1' }]
					}
				},
				evidence_refs: []
			}
		];
		payload.measured_properties = [];
		payload.report_package = null;
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/materials/mat_316l/research-view') {
				return jsonResponse(payload);
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: '316L stainless steel' }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Material report package has not been generated for this material.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('leading in this matrix · E01'))
			.not.toBeInTheDocument();
	});

	it('generates a material review report and exposes Markdown and PDF artifacts', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);

			if (path === '/api/v1/collections/col_123/materials/mat_316l/research-view') {
				return jsonResponse(materialProfilePayload());
			}

			if (
				path === '/api/v1/collections/col_123/materials/mat_316l/review-report' &&
				method === 'GET'
			) {
				return jsonResponse({ detail: { code: 'material_review_report_not_found' } }, 404);
			}

			if (
				path === '/api/v1/collections/col_123/materials/mat_316l/review-report' &&
				method === 'POST'
			) {
				return jsonResponse(materialReviewReportPayload());
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: '316L stainless steel' }))
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Generate review PDF' }).click();
		await browserPage.getByRole('button', { name: 'Generate review', exact: true }).click();

		await expect
			.element(browserPage.getByRole('heading', { name: 'Material review PDF' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Preview Markdown' }))
			.toHaveAttribute(
				'href',
				'/api/v1/collections/col_123/materials/mat_316l/review-report.md'
			);
		await expect
			.element(browserPage.getByRole('link', { name: 'View PDF' }))
			.toHaveAttribute(
				'href',
				'/api/v1/collections/col_123/materials/mat_316l/review-report.pdf'
			);

		const postCall = fetchMock.mock.calls.find(
			([input, init]) =>
				requestPath(input as string | URL | Request) ===
					'/api/v1/collections/col_123/materials/mat_316l/review-report' &&
				requestMethod(input as string | URL | Request, init as RequestInit | undefined) === 'POST'
		);
		expect(JSON.parse(String((postCall?.[1] as RequestInit | undefined)?.body))).toMatchObject({
			report_type: 'review_draft',
			include_appendix: true,
			force_regenerate: false
		});
	});

	it('renders the narrative research tab from the same material profile data', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: '316L stainless steel' }))
			.toBeInTheDocument();
		await browserPage.getByRole('tab', { name: 'Narrative research' }).click();

		await expect
			.element(browserPage.getByRole('heading', { name: 'What does this literature set study?' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'How are the samples designed?' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'What are the main performance findings?' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText(/mainly through LPBF\/SLM/)).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: /Relative density/ }).first())
			.toBeInTheDocument();
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
