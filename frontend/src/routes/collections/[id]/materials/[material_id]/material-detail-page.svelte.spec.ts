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

function requestPaths() {
	return fetchMock.mock.calls.map(([input]) => requestPath(input as string | URL | Request));
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
		understanding: {
			schema_version: 'research_understanding.v1',
			state: 'ready',
			scope: {
				scope_type: 'material',
				collection_id: 'col_123',
				material_id: 'mat_316l',
				objective_id: null,
				document_id: null,
				title: '316L stainless steel'
			},
			claims: [
				{
					claim_id: 'claim_material_hardness',
					claim_type: 'finding',
					statement: 'S001 keeps hardness tied to tensile testing and table evidence.',
					status: 'supported',
					confidence: 0.95,
					strength: null,
					evidence_ref_ids: ['ev_hardness_s001'],
					context_ids: ['ctx_material_scope'],
					source_object_ids: ['finding:S001'],
					warnings: []
				}
			],
			relations: [
				{
					relation_id: 'rel_scan_strategy_hardness',
					relation_type: 'compares',
					subject: 'scan strategy',
					predicate: 'comparable',
					object: 'hardness',
					status: 'supported',
					confidence: null,
					evidence_ref_ids: ['ev_hardness_s001'],
					context_ids: ['ctx_material_scope'],
					source_object_ids: ['grp_1'],
					warnings: []
				}
			],
			evidence_refs: [
				{
					evidence_ref_id: 'ev_hardness_s001',
					document_id: 'doc_1',
					source_kind: 'table',
					label: 'Paper A · Table 2',
					locator: {
						source_ref: 'Table 2'
					},
					fact_ids: ['finding:S001'],
					anchor_ids: [],
					confidence: 0.95,
					traceability_status: 'traceable',
					quote: null,
					href: null
				}
			],
			contexts: [
				{
					context_id: 'ctx_material_scope',
					label: 'Material scope',
					material_scope: ['316L stainless steel'],
					process_context: {
						process_families: ['LPBF/SLM']
					},
					test_condition: {},
					property_scope: ['hardness'],
					limitations: ['S002 is missing test_conditions.']
				}
			],
			warnings: [],
			summary: {
				claim_count: 1,
				relation_count: 1,
				evidence_ref_count: 1,
				context_count: 1
			},
			presentation: {
				summary: {
					title: '316L stainless steel',
					material_scope: ['316L stainless steel'],
					variable_axes: ['scan strategy'],
					property_scope: ['hardness'],
					claim_count: 1,
					relation_count: 1,
					evidence_count: 1,
					context_count: 1,
					review_queue_count: 0,
					primary_finding_count: 1,
					review_queue_finding_count: 0,
					collection_document_count: 1,
					axis_coverage: { variables: [], properties: [] }
				},
				effects: [],
				findings: [
					{
						finding_id: 'finding:S001',
						claim_id: 'claim_material_hardness',
						title: 'S001 hardness finding',
						statement: 'S001 keeps hardness tied to tensile testing and table evidence.',
						variables: ['scan strategy'],
						mediators: [],
						outcomes: ['hardness'],
						direction: 'observed',
						scope_summary: '316L stainless steel, LPBF/SLM',
						support_grade: 'strong',
						review_status: 'reviewed',
						confidence: 0.95,
						paper_count: 1,
						evidence_count: 1,
						evidence_ref_ids: ['ev_hardness_s001'],
						context_ids: ['ctx_material_scope'],
						relation_ids: [],
						relation_chain: [],
						evidence_bundle: {
							direct_result: ['ev_hardness_s001'],
							mechanism: [],
							condition_context: [],
							background: [],
							conflict: [],
							noise: [],
							uncategorized: []
						},
						comparison_summary: null,
						expert_use_status: 'accepted',
						dataset_use_status: 'training_ready',
						generalization_status: 'paper_level_only',
						generalization_note: '',
						evidence_gap_summary: '',
						upgrade_actions: [],
						related_review_finding_ids: [],
						review_reasons: [],
						warnings: [],
						synthesis_status: '',
						common_conditions: [],
						incomparable_conditions: [],
						paper_contributions: []
					}
				],
				evidence_items: [
					{
						evidence_ref_id: 'ev_hardness_s001',
						document_id: 'doc_1',
						title: 'Paper A · Table 2',
						source_label: 'Paper A · Table 2',
						source_kind: 'table',
						source_ref: 'Table 2',
						block_type: 'table',
						heading_path: null,
						page: null,
						quote: null,
						source_text: null,
						value_summary: 'Hardness 215.6',
						table_audit: null,
						traceability_status: 'traceable',
						evidence_role: 'direct_result',
						confidence: 0.95,
						href: null
					}
				],
				context_summaries: []
			}
		}
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
			if (path === '/api/v1/collections/col_123/research-understanding/curations') {
				return jsonResponse({ collection_id: 'col_123', items: [] });
			}
			if (path === '/api/v1/collections/col_123/research-understanding/feedback') {
				return jsonResponse({ collection_id: 'col_123', items: [] });
			}
			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});
	});

	it('renders material profile modules from the material profile endpoint', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: '316L stainless steel', exact: true }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research understanding' }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage
					.getByText('S001 keeps hardness tied to tensile testing and table evidence.')
					.first()
			)
			.toBeInTheDocument();
		await browserPage
			.getByText('S001 keeps hardness tied to tensile testing and table evidence.')
			.first()
			.click();
		await expect.element(browserPage.getByText('Paper A · Table 2').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Material questions' }))
			.toBeInTheDocument();
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
			.element(browserPage.getByRole('button', { name: '95.4%' }).first())
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('215.6').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Research chain map')).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Best parameter chain')).not.toBeInTheDocument();
		expect(requestPaths()).toContain(
			'/api/v1/collections/col_123/materials/mat_316l/research-view'
		);
	});

	it('cleans table-origin labels in the supporting data matrix', async () => {
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
			.element(browserPage.getByRole('heading', { name: 'Supporting data matrix' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('as-SLM(140/100)').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Energy density').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('139 J/mm3').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Laser power').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('140 W').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Scan speed').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('280 mm/s').first()).toBeInTheDocument();
		const matrix = document.querySelector('#performance-results');
		expect(matrix?.textContent).not.toContain('Table 2 (continued)');
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
			.element(browserPage.getByRole('heading', { name: '316L stainless steel', exact: true }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('610 MPa').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Supporting data matrix' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText(/Collection summary: Tensile strength 610 MPa/))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Collection summary').first()).toBeInTheDocument();
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
		expect(requestPaths()).toContain(
			'/api/v1/collections/col_123/materials/mat_316l/research-view'
		);
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
			.element(browserPage.getByRole('heading', { name: '316L stainless steel', exact: true }))
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
			.element(browserPage.getByRole('heading', { name: '316L stainless steel', exact: true }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('S001 · Alternating strategy A').first())
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Low signal 0')).not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('2 sample(s), 5 measured property column(s).'))
			.toBeInTheDocument();
	});

	it('opens evidence details from a performance value', async () => {
		const payload: any = materialProfilePayload();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/materials/mat_316l/research-view') {
				return jsonResponse(payload);
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

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
