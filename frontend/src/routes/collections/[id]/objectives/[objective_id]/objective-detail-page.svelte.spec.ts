import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type ObjectivePageState = {
	params: {
		id: string;
		objective_id: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: ObjectivePageState) => void>();
	let current: ObjectivePageState = {
		params: { id: 'col_123', objective_id: 'obj_1' },
		url: new URL('http://localhost/collections/col_123/objectives/obj_1')
	};

	return {
		pageStore: {
			subscribe(run: (value: ObjectivePageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: ObjectivePageState) {
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

function objectivePayload() {
	return {
		collection_id: 'col_123',
		state: 'ready',
		objective: {
			objective_id: 'obj_1',
			question: 'How does heat treatment affect LPBF 316L tensile strength?',
			material_scope: ['316L stainless steel'],
			process_axes: ['heat treatment'],
			property_axes: ['yield strength'],
			comparison_intent: 'Compare as-built and heat-treated LPBF 316L.',
			confidence: 0.91
		},
		objective_context: {
			objective_id: 'obj_1',
			question: 'How does heat treatment affect LPBF 316L tensile strength?',
			material_scope: ['316L stainless steel'],
			variable_process_axes: ['heat treatment'],
			target_property_axes: ['yield strength'],
			confidence: 0.88
		},
		readiness: {
			objectives_ready: true,
			frames_ready: true,
			routes_ready: true,
			evidence_units_ready: true,
			logic_chain_ready: true
		},
		paper_frames: [
			{
				frame_id: 'opf_1',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				title: 'LPBF 316L heat treatment study',
				source_filename: 'paper-a.pdf',
				relevance: 'high',
				paper_role: 'primary_experiment',
				background: 'Reports tensile testing of as-built and heat-treated LPBF 316L.',
				material_match: ['316L stainless steel'],
				changed_variables: ['heat treatment'],
				measured_property_scope: ['yield strength'],
				relevant_sections: ['Results'],
				relevant_tables: ['table-2'],
				excluded_tables: ['table-1']
			}
		],
		evidence_routes: [
			{
				route_id: 'route_1',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				source_kind: 'table',
				source_ref: 'table-2',
				role: 'result_table',
				extractable: true,
				table_schema: {
					column_headers: ['Sample', 'Yield strength']
				}
			}
		],
		evidence_units: [
			{
				evidence_unit_id: 'unit_measure',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'measurement',
				property_normalized: 'yield strength',
				sample_context: {
					sample: 'HT-SLM'
				},
				process_context: {
					process: 'LPBF',
					heat_treatment: 'annealed'
				},
				test_condition: {
					method: 'tensile test'
				},
				value_payload: {
					statement: 'Yield strength reached 560 MPa.'
				},
				unit: 'MPa',
				source_refs: [
					{
						document_id: 'doc_1',
						source_kind: 'table',
						source_ref: 'table-2',
						evidence_id: 'ev_1',
						anchor_id: 'anc_1',
						page: 5
					}
				],
				evidence_anchor_ids: ['anc_1'],
				resolution_status: 'unresolved_condition',
				confidence: 0.92
			},
			{
				evidence_unit_id: 'unit_measure_secondary',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'measurement',
				property_normalized: 'yield strength',
				sample_context: {
					sample: 'HT-SLM-2'
				},
				process_context: {
					process: 'LPBF',
					heat_treatment: 'annealed'
				},
				test_condition: {
					method: 'tensile test'
				},
				value_payload: {
					statement: 'Yield strength reached 540 MPa.'
				},
				unit: 'MPa',
				source_refs: [],
				evidence_anchor_ids: [],
				resolution_status: 'unresolved_condition',
				confidence: 0.84
			},
			{
				evidence_unit_id: 'unit_condition',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'test_condition',
				property_normalized: 'yield strength',
				test_condition: {
					method: 'tensile test',
					standard: 'ASTM E8'
				},
				value_payload: {
					statement: 'Tensile testing followed ASTM E8.'
				},
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.86
			},
			{
				evidence_unit_id: 'unit_obs',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'characterization',
				property_normalized: 'microstructure',
				value_payload: {
					observation_text: 'Annealing reduced cellular substructure.'
				},
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.82
			},
			{
				evidence_unit_id: 'unit_compare',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'comparison',
				property_normalized: 'yield strength',
				sample_context: {
					sample: 'HT-SLM'
				},
				baseline_context: {
					evidence_unit_id: 'oeu_internal_baseline',
					sample_context: {
						sample: 'as-built'
					}
				},
				value_payload: {
					statement: 'Heat-treated samples exceeded the as-built baseline.'
				},
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.79
			},
			{
				evidence_unit_id: 'unit_compare_secondary',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'comparison',
				property_normalized: 'yield strength',
				sample_context: {
					sample: 'HT-SLM-2'
				},
				baseline_context: {
					sample_context: {
						sample: 'as-built'
					}
				},
				value_payload: {
					statement: 'A second heat-treated condition also exceeded the as-built baseline.'
				},
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.71
			},
			{
				evidence_unit_id: 'unit_interpretation',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'interpretation',
				property_normalized: 'strength mechanism',
				value_payload: {},
				interpretation:
					'Annealing changes the cellular substructure, which the authors link to the tensile response.',
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.77
			},
			{
				evidence_unit_id: 'unit_numeric_interpretation',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'interpretation',
				property_normalized: 'yield strength',
				value_payload: {},
				interpretation: '440 - 475 MPa',
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.96
			},
			{
				evidence_unit_id: 'unit_scope_interpretation',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'interpretation',
				property_normalized: 'mechanical behavior',
				value_payload: {},
				interpretation:
					'The combined impact of scan strategy rotation angles and build orientations on microstructure and mechanical behavior was investigated.',
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.95
			},
			{
				evidence_unit_id: 'unit_pseudo_interpretation',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'interpretation',
				property_normalized: 'yield strength',
				value_payload: {},
				interpretation: 'Higher yield strength.',
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.94
			},
			{
				evidence_unit_id: 'unit_trend_interpretation',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'interpretation',
				property_normalized: 'tensile response',
				value_payload: {},
				interpretation:
					'The heat treatments induced a decrease in the tensile strength, as well as an increase in the elongation.',
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.93
			}
		],
		logic_chain: {
			logic_chain_id: 'chain_1',
			objective_id: 'obj_1',
			chain_scope: 'objective',
			question: 'How does heat treatment affect LPBF 316L tensile strength?',
			evidence_unit_ids: ['unit_measure', 'unit_condition', 'unit_obs'],
			summary:
				'How does heat treatment affect LPBF 316L tensile strength?: Heat-treated LPBF 316L is supported by tensile and microstructure evidence.',
			chain_payload: {
				cross_paper: {
					gaps: ['unresolved_measurements_present']
				}
			},
			confidence: 0.83
		},
		understanding: {
			schema_version: 'research_understanding.v1',
			state: 'ready',
			scope: {
				scope_type: 'objective',
				collection_id: 'col_123',
				objective_id: 'obj_1',
				material_id: null,
				document_id: null,
				title: 'How does heat treatment affect LPBF 316L tensile strength?'
			},
			claims: [
				{
					claim_id: 'claim_heat_treatment_strength',
					claim_type: 'finding',
					statement: 'Heat treatment changes LPBF 316L tensile response.',
					status: 'supported',
					confidence: 0.9,
					strength: 'moderate',
					evidence_ref_ids: ['evref_table_2'],
					context_ids: ['ctx_objective_scope'],
					source_object_ids: ['unit_measure'],
					warnings: []
				}
			],
			relations: [
				{
					relation_id: 'rel_heat_treatment_strength',
					relation_type: 'increases',
					subject: 'sample: HT-SLM',
					predicate: 'increase',
					object: 'sample: as-built',
					status: 'supported',
					confidence: 0.79,
					evidence_ref_ids: ['evref_table_2'],
					context_ids: ['ctx_objective_scope'],
					source_object_ids: ['unit_compare'],
					warnings: []
				}
			],
			evidence_refs: [
				{
					evidence_ref_id: 'evref_table_2',
					source_kind: 'table',
					document_id: 'doc_1',
					label: 'P001 · Table 2 · p.5',
					locator: {
						source_ref: 'table-2',
						page: 5
					},
					fact_ids: ['unit_measure'],
					anchor_ids: ['anc_1'],
					confidence: 0.92,
					traceability_status: 'traceable',
					quote: null,
					href: null
				}
			],
			contexts: [
				{
					context_id: 'ctx_objective_scope',
					label: 'Objective scope',
					material_scope: ['316L stainless steel'],
					process_context: {
						variable_process_axes: ['heat treatment']
					},
					test_condition: {},
					property_scope: ['yield strength'],
					limitations: []
				}
			],
			warnings: [],
			summary: {
				claim_count: 1,
				relation_count: 1,
				evidence_ref_count: 1,
				context_count: 1
			}
		}
	};
}

describe('collections/[id]/objectives/[objective_id]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', objective_id: 'obj_1' },
			url: new URL('http://localhost/collections/col_123/objectives/obj_1')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/objectives/obj_1/research-view') {
				return jsonResponse(objectivePayload());
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

	it('renders research understanding as the primary view and keeps evidence in audit', async () => {
		render(Page);

		await expect
			.element(
				browserPage.getByRole('heading', {
					name: 'How does heat treatment affect LPBF 316L tensile strength?'
				})
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research understanding' }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage
					.getByRole('region', { name: 'Claims' })
					.getByText('Heat treatment changes LPBF 316L tensile response.')
			)
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('P001 · Table 2 · p.5').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('sample: HT-SLM').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('sample: as-built').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Evidence audit and diagnostics'))
			.toBeInTheDocument();
		await browserPage.getByText('Evidence audit and diagnostics').click();
		await expect
			.element(browserPage.getByText('LPBF 316L heat treatment study').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: /Yield strength reached 560 MPa/ }))
			.toBeInTheDocument();
		expect(requestPaths()).toContain('/api/v1/collections/col_123/objectives/obj_1/research-view');
	});

	it('filters evidence units by kind and updates the inspector', async () => {
		render(Page);

		await browserPage.getByText('Evidence audit and diagnostics').click();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Supporting evidence' }))
			.toBeInTheDocument();
		await browserPage.getByText('All extracted evidence').click();
		await browserPage.getByLabelText('Evidence kind').selectOptions('comparison');

		await expect
			.element(browserPage.getByRole('heading', { name: 'Comparison evidence' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Measurement results' }))
			.not.toBeInTheDocument();
		await expect
			.element(
				browserPage
					.getByRole('complementary', { name: 'Evidence detail' })
					.getByText('Heat-treated samples exceeded the as-built baseline.')
			)
			.toBeInTheDocument();
	});

	it('presents evidence detail as a research chain record', async () => {
		render(Page);

		await browserPage.getByText('Evidence audit and diagnostics').click();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Supporting evidence' }))
			.toBeInTheDocument();
		await browserPage.getByText('All extracted evidence').click();
		await browserPage.getByLabelText('Evidence kind').selectOptions('comparison');

		const inspector = browserPage.getByRole('complementary', { name: 'Evidence detail' });
		await expect.element(inspector.getByRole('heading', { name: 'Finding' })).toBeInTheDocument();
		await expect
			.element(inspector.getByRole('heading', { name: 'Sample and process' }))
			.toBeInTheDocument();
		await expect
			.element(inspector.getByRole('heading', { name: 'Comparison baseline' }))
			.toBeInTheDocument();
		await expect
			.element(inspector.getByRole('heading', { name: 'Source traceback' }))
			.toBeInTheDocument();
		await expect.element(inspector.getByText('sample: HT-SLM')).toBeInTheDocument();
		await expect.element(inspector.getByText('sample: as-built')).toBeInTheDocument();
		await expect.element(inspector.getByText(/oeu_internal_baseline/)).not.toBeInTheDocument();
	});

	it('summarizes evidence context on evidence cards', async () => {
		render(Page);

		await browserPage.getByText('Evidence audit and diagnostics').click();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Supporting evidence' }))
			.toBeInTheDocument();

		const measurementCard = browserPage.getByRole('button', {
			name: /doc_1 · 92%/
		});
		await expect.element(measurementCard.getByText('sample: HT-SLM')).toBeInTheDocument();
		await expect.element(measurementCard.getByText('heat_treatment: annealed')).toBeInTheDocument();
		await expect.element(measurementCard.getByText('method: tensile test')).toBeInTheDocument();

		await browserPage.getByText('All extracted evidence').click();
		await browserPage.getByLabelText('Evidence kind').selectOptions('comparison');
		const comparisonGroup = browserPage.getByRole('region', { name: 'Comparison evidence' });
		const comparisonCard = comparisonGroup.getByRole('button', {
			name: /doc_1 · 79%/
		});
		await expect.element(comparisonCard.getByText('baseline: as-built')).toBeInTheDocument();
		await expect.element(comparisonCard.getByText(/oeu_internal_baseline/)).not.toBeInTheDocument();
	});

	it('renders duplicate evidence fact labels without a keyed each failure', async () => {
		const payload: any = objectivePayload();
		payload.evidence_units = [
			{
				...payload.evidence_units[0],
				evidence_unit_id: 'unit_duplicate_facts',
				sample_context: {
					sample: 'Non-preheated'
				},
				process_context: {
					process: 'Non-preheated',
					heat_treatment: 'annealed'
				},
				test_condition: {
					method: 'tensile test',
					details:
						'Very long tensile testing condition text that belongs in the inspector rather than compact evidence chips.'
				}
			}
		];
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/objectives/obj_1/research-view') {
				return jsonResponse(payload);
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await browserPage.getByText('Evidence audit and diagnostics').click();
		const duplicateCard = browserPage.getByRole('button', {
			name: /doc_1 · 92%/
		});
		await expect.element(duplicateCard.getByText('sample: Non-preheated')).toBeInTheDocument();
		await expect.element(duplicateCard.getByText('process: Non-preheated')).toBeInTheDocument();
		await expect
			.element(duplicateCard.getByText(/Very long tensile testing condition text/))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Supporting evidence' }))
			.toBeInTheDocument();
	});

	it('shortens long document identifiers in compact evidence cards', async () => {
		const payload: any = objectivePayload();
		const longDocumentId =
			'e30598b737366321b28ebd4a9b02b3679d05f35df0a1d8ed204dc55d1eaa9c5233f50b5be9ee26ef7e836237f394e6a016fad25536ef4eb9bd8fa1d8';
		payload.paper_frames[0].document_id = longDocumentId;
		payload.evidence_routes[0].document_id = longDocumentId;
		payload.evidence_units = [
			{
				...payload.evidence_units[0],
				document_id: longDocumentId,
				source_refs: []
			}
		];
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/objectives/obj_1/research-view') {
				return jsonResponse(payload);
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await browserPage.getByText('Evidence audit and diagnostics').click();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Supporting evidence' }))
			.toBeInTheDocument();
		const supportingSection = document.querySelector('.supporting-evidence-list');
		await expect.poll(() => supportingSection?.textContent ?? '').toContain('e30598b737...8fa1d8');
		expect(supportingSection?.textContent).not.toContain(longDocumentId);
	});

	it('previews large evidence groups without rendering every unit at once', async () => {
		const payload: any = objectivePayload();
		payload.evidence_units = Array.from({ length: 8 }, (_, index) => ({
			...payload.evidence_units[0],
			evidence_unit_id: `unit_measure_${index + 1}`,
			value_payload: {
				statement: `Measurement preview ${index + 1}`
			}
		}));
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/objectives/obj_1/research-view') {
				return jsonResponse(payload);
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await browserPage.getByText('Evidence audit and diagnostics').click();
		await browserPage.getByText('All extracted evidence').click();
		await expect.element(browserPage.getByText('Measurement preview 6')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Measurement preview 7')).not.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Showing the first 6 of 8 units for this group. Use filters or the detail panel for focused review.'
				)
			)
			.toBeInTheDocument();
	});

	it('uses evidence readiness controls to focus related evidence', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('button', { name: /Measurement results/ }))
			.toBeInTheDocument();

		await browserPage.getByRole('button', { name: /Measurement results/ }).click();
		await expect.element(browserPage.getByLabelText('Evidence kind')).toHaveValue('measurement');
		await expect
			.element(
				browserPage
					.getByRole('complementary', { name: 'Evidence detail' })
					.getByText('Yield strength reached 560 MPa.')
			)
			.toBeInTheDocument();

		await browserPage.getByRole('button', { name: /^1 Test conditions$/ }).click();
		await expect.element(browserPage.getByLabelText('Evidence kind')).toHaveValue('test_condition');
		await expect
			.element(
				browserPage
					.getByRole('complementary', { name: 'Evidence detail' })
					.getByText('Tensile testing followed ASTM E8.')
			)
			.toBeInTheDocument();
	});
});
