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
		conclusion_package: {
			schema_version: 'objective_conclusion_package.v1',
			title: 'How does heat treatment affect LPBF 316L tensile strength?',
			objective: {
				objective_id: 'obj_1',
				question: 'How does heat treatment affect LPBF 316L tensile strength?',
				material_scope: ['316L stainless steel'],
				process_axes: ['heat treatment'],
				property_axes: ['yield strength']
			},
			status: 'ready',
			narrative: {
				status: 'ready',
				sections: [
					{
						section_id: 'answer',
						title: 'Answer',
						body:
							'For LPBF 316L, the current evidence package evaluates how heat treatment affects yield strength. The strongest contribution is LPBF 316L heat treatment study because it directly contributes heat treatment evidence tied to yield strength.',
						claims: [],
						evidence_unit_ids: ['unit_measure', 'unit_obs', 'unit_interpretation'],
						source_refs: [
							{
								evidence_unit_id: 'unit_measure',
								document_id: 'doc_1',
								source_kind: 'table',
								source_ref: 'table-2',
								evidence_id: 'ev_1',
								anchor_id: 'anc_1',
								page: 5,
								display_label: 'P001 · Table 2 · p.5'
							}
						]
					},
					{
						section_id: 'key_evidence',
						title: 'Key evidence',
						body:
							'The key evidence table contains 2 measurement rows. Across those rows, yield strength range 540-560 MPa.',
						claims: [
							{
								claim:
									'yield strength spans 540 MPa to 560 MPa across HT-SLM-2 and HT-SLM.',
								evidence_unit_ids: ['unit_measure', 'unit_obs', 'unit_interpretation'],
								source_refs: [
									{
										evidence_unit_id: 'unit_measure',
										document_id: 'doc_1',
										source_kind: 'table',
										source_ref: 'table-2',
										evidence_id: 'ev_1',
										anchor_id: 'anc_1',
										page: 5,
										display_label: 'P001 · Table 2 · p.5'
									}
								],
								strength: 'measured'
							}
						],
						evidence_unit_ids: ['unit_measure', 'unit_obs', 'unit_interpretation'],
						source_refs: [
							{
								evidence_unit_id: 'unit_measure',
								document_id: 'doc_1',
								source_kind: 'table',
								source_ref: 'table-2',
								evidence_id: 'ev_1',
								anchor_id: 'anc_1',
								page: 5
							}
						]
					},
					{
						section_id: 'limitations',
						title: 'Limitations and uncertainties',
						body:
							'Some measurements do not have complete sample and process context, so strict comparison remains limited.',
						claims: [],
						evidence_unit_ids: ['unit_measure', 'unit_measure_secondary'],
						source_refs: [
							{
								evidence_unit_id: 'unit_measure',
								document_id: 'doc_1',
								source_kind: 'table',
								source_ref: 'table-2',
								page: 5,
								display_label: 'P001 · Table 2 · p.5'
							}
						]
					}
				]
			},
			paper_contributions: [
				{
					document_id: 'doc_1',
					title: 'LPBF 316L heat treatment study',
					source_filename: 'paper-a.pdf',
					paper_role: 'primary_experiment',
					relevance: 'high',
					background: 'Reports tensile testing of as-built and heat-treated LPBF 316L.',
					changed_variables: ['heat treatment'],
					measured_property_scope: ['yield strength'],
					evidence_unit_count: 11,
					evidence_unit_ids: ['unit_measure', 'unit_condition', 'unit_obs']
				}
			],
			primary_evidence_tables: [
				{
					table_id: 'measurement-results',
					title: 'Measurement results',
					rows: [
						{
							evidence_unit_id: 'unit_measure',
							document_id: 'doc_1',
							property: 'yield strength',
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
							value: 560,
							source_value_text: '560 MPa',
							unit: 'MPa',
							resolution_status: 'unresolved_condition',
							source_refs: [
								{
									document_id: 'doc_1',
									source_kind: 'table',
									source_ref: 'table-2',
									evidence_id: 'ev_1',
									anchor_id: 'anc_1',
									page: 5
								}
							]
						},
						{
							evidence_unit_id: 'unit_measure_secondary',
							document_id: 'doc_1',
							property: 'yield strength',
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
							value: 540,
							source_value_text: '540 MPa',
							unit: 'MPa',
							resolution_status: 'unresolved_condition',
							source_refs: []
						}
					],
					measurement_value_ranges: [
						{
							property_normalized: 'yield strength',
							min: {
								evidence_unit_id: 'unit_measure_secondary',
								value: 540,
								unit: 'MPa',
								sample_context: {
									sample: 'HT-SLM-2'
								},
								process_context: {
									process: 'LPBF'
								},
								document_id: 'doc_1',
								source_refs: []
							},
							max: {
								evidence_unit_id: 'unit_measure',
								value: 560,
								unit: 'MPa',
								sample_context: {
									sample: 'HT-SLM'
								},
								process_context: {
									process: 'LPBF'
								},
								document_id: 'doc_1',
								source_refs: []
							},
							unit: 'MPa',
							count: 2
						}
					]
				}
			],
			controlled_comparisons: [
				{
					evidence_unit_id: 'unit_compare',
					document_id: 'doc_1',
					property: 'yield strength',
					comparison_axis: 'heat treatment',
					direction: 'increase',
					summary: 'Heat-treated samples exceeded the as-built baseline.',
					sample_context: {
						sample: 'HT-SLM'
					},
					process_context: {
						heat_treatment: 'annealed'
					},
					baseline_context: {
						sample_context: {
							sample: 'as-built'
						}
					},
					source_refs: [],
					validity: 'controlled'
				}
			],
			mechanism_chain: {
				steps: [
					{
						step_role: 'process_to_microstructure',
						label: 'Heat treatment changes cellular substructure.'
					},
					{
						step_role: 'microstructure_to_property',
						label: 'Microstructure changes affect the tensile response.'
					}
				],
				evidence: [
					{
						evidence_unit_id: 'unit_interpretation',
						document_id: 'doc_1',
						unit_kind: 'interpretation',
						property: 'strength mechanism',
						summary:
							'Annealing changes the cellular substructure, which the authors link to the tensile response.',
						source_refs: []
					}
				],
				evidence_unit_ids: ['unit_interpretation']
			},
			conclusions: [
				{
					claim:
						'Heat-treated LPBF 316L is supported by tensile and microstructure evidence.',
					evidence_unit_ids: ['unit_measure', 'unit_obs', 'unit_interpretation'],
					strength: 'measured'
				}
			],
			limitations: [
				{
					code: 'sample_process_context_incomplete',
					message: 'Some measurements do not have complete sample and process context.',
					evidence_unit_ids: ['unit_measure', 'unit_measure_secondary']
				}
			],
			source_refs: [
				{
					evidence_unit_id: 'unit_measure',
					document_id: 'doc_1',
					source_kind: 'table',
					source_ref: 'table-2',
					page: 5,
					display_label: 'P001 · Table 2 · p.5'
				}
			],
			expert_report: {
				schema_version: 'objective_expert_report.v1',
				status: 'ready',
				headline_conclusion:
					'Expert report: heat treatment changes LPBF 316L tensile response, with the current evidence bounded by 540-560 MPa yield-strength measurements.',
				scientific_context:
					'Expert context: this objective compares as-built and heat-treated LPBF 316L under tensile testing, then ties the response to microstructure observations.',
				key_findings: [
					{
						finding_id: 'finding-001',
						statement:
							'Expert finding: yield strength is supported by two heat-treated measurements spanning 540-560 MPa.',
						strength: 'measured',
						evidence_unit_ids: ['unit_measure', 'unit_measure_secondary'],
						source_refs: [
							{
								evidence_unit_id: 'unit_measure',
								document_id: 'doc_1',
								source_kind: 'table',
								source_ref: 'table-2',
								evidence_id: 'ev_1',
								anchor_id: 'anc_1',
								page: 5,
								display_label: 'P001 · Table 2 · p.5'
							}
						]
					}
				],
				evidence_matrix: {
					relevant_paper_count: 1,
					measurement_result_count: 2,
					measurement_property_count: 1,
					controlled_comparison_count: 1,
					mechanism_evidence_count: 1,
					limitation_count: 1,
					source_ref_count: 1,
					measurement_value_ranges: [
						{
							property_normalized: 'yield strength',
							min: {
								evidence_unit_id: 'unit_measure_secondary',
								value: 540,
								unit: 'MPa',
								sample_context: {
									sample: 'HT-SLM-2'
								},
								process_context: {
									process: 'LPBF'
								},
								document_id: 'doc_1',
								source_refs: []
							},
							max: {
								evidence_unit_id: 'unit_measure',
								value: 560,
								unit: 'MPa',
								sample_context: {
									sample: 'HT-SLM'
								},
								process_context: {
									process: 'LPBF'
								},
								document_id: 'doc_1',
								source_refs: []
							},
							unit: 'MPa',
							count: 2
						}
					]
				},
				paper_contribution_map: [
					{
						document_id: 'doc_1',
						paper_label: 'P001',
						display_title: 'P001 - LPBF 316L heat treatment study',
						paper_role: 'primary_experiment',
						relevance: 'high',
						contribution_summary:
							'Expert contribution: P001 provides the tensile measurements, comparison evidence, and microstructure interpretation for this objective.',
						changed_variables: ['heat treatment'],
						measured_property_scope: ['yield strength'],
						evidence_unit_count: 11,
						evidence_unit_ids: ['unit_measure', 'unit_condition', 'unit_obs'],
						source_refs: [
							{
								evidence_unit_id: 'unit_measure',
								document_id: 'doc_1',
								source_kind: 'table',
								source_ref: 'table-2',
								page: 5,
								display_label: 'P001 · Table 2 · p.5'
							}
						]
					}
				],
				controlled_comparisons: [
					{
						comparison_id: 'comparison-001',
						evidence_unit_id: 'unit_compare',
						document_id: 'doc_1',
						property: 'yield strength',
						comparison_axis: 'heat treatment',
						direction: 'increase',
						validity: 'controlled',
						summary:
							'Expert comparison: heat-treated samples exceed the as-built baseline for yield strength.',
						sample_context: {
							sample: 'HT-SLM'
						},
						process_context: {
							heat_treatment: 'annealed'
						},
						baseline_context: {
							sample_context: {
								sample: 'as-built'
							}
						},
						source_refs: []
					}
				],
				mechanism_chain: {
					steps: [
						{
							step_role: 'process_to_microstructure',
							label: 'Expert mechanism step: heat treatment changes cellular substructure.'
						},
						{
							step_role: 'microstructure_to_property',
							label: 'Expert mechanism step: microstructure changes alter tensile response.'
						}
					],
					evidence: [
						{
							evidence_unit_id: 'unit_interpretation',
							document_id: 'doc_1',
							unit_kind: 'interpretation',
							property: 'strength mechanism',
							summary:
								'Expert mechanism evidence: annealing changes cellular substructure and the authors connect it to tensile behavior.',
							sample_context: {},
							process_context: {
								heat_treatment: 'annealed'
							},
							source_refs: []
						}
					],
					evidence_unit_ids: ['unit_interpretation']
				},
				limitations: [
					{
						code: 'sample_process_context_incomplete',
						message:
							'Expert limitation: one measurement remains partially resolved, so the comparison should stay source-bounded.',
						evidence_unit_ids: ['unit_measure_secondary'],
						source_refs: []
					}
				],
				source_traceback: [
					{
						evidence_unit_id: 'unit_measure',
						document_id: 'doc_1',
						source_kind: 'table',
						source_ref: 'table-2',
						page: 5,
						display_label: 'P001 · Table 2 · p.5'
					}
				],
				traceability: {
					status: 'ready',
					traceable_claim_count: 1,
					unsupported_claim_count: 0
				}
			}
		},
		objective_report: {
			collection_id: 'col_123',
			report_id: 'orp_1',
			objective_id: 'obj_1',
			status: 'ready',
			stage: 'ready',
			message: 'Objective report generated.',
			title: 'Research objective report',
			language: 'zh',
			model: 'test-model',
			data_version: 'v1',
			markdown:
				'# 研究目标\n\n' +
				'How does heat treatment affect LPBF 316L tensile strength?\n\n' +
				'## 结论摘要\n\n' +
				'Heat treatment changes LPBF 316L tensile response; yield strength is bounded by 540-560 MPa in the persisted report.\n\n' +
				'## 文献贡献\n\n' +
				'- P001 provides tensile measurements, comparison evidence, and microstructure interpretation.\n\n' +
				'## 支撑数据\n\n' +
				'The report cites P001 Table 2 page 5 for the 560 MPa measurement.',
			warnings: [],
			source_refs: [
				{
					document_id: 'doc_1',
					source_kind: 'table',
					source_ref: 'table-2',
					page: 5,
					display_label: 'P001 · Table 2 · p.5'
				}
			],
			created_at: '2026-05-19T00:00:00+00:00',
			updated_at: '2026-05-19T00:00:01+00:00',
			generated_at: '2026-05-19T00:00:01+00:00'
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

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});
	});

	it('renders the persisted objective report as the primary view and keeps evidence in audit', async () => {
		render(Page);

		await expect
			.element(
				browserPage.getByRole('heading', {
					name: 'How does heat treatment affect LPBF 316L tensile strength?'
				})
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research objective report' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByRole('heading', { name: '结论摘要' })).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Heat treatment changes LPBF 316L tensile response; yield strength is bounded by 540-560 MPa in the persisted report.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('P001 provides tensile measurements, comparison evidence, and microstructure interpretation.'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Expert report: heat treatment changes LPBF 316L tensile response'))
			.not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Evidence audit and diagnostics')).toBeInTheDocument();
		await browserPage.getByText('Evidence audit and diagnostics').click();
		await expect.element(browserPage.getByText('LPBF 316L heat treatment study').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: /Yield strength reached 560 MPa/ }))
			.toBeInTheDocument();
		expect(
			fetchMock.mock.calls.map(([input]) => requestPath(input as string | URL | Request))
		).toEqual(['/api/v1/collections/col_123/objectives/obj_1/research-view']);
	});

	it('requests objective report generation when no persisted report is available', async () => {
		const payload: any = objectivePayload();
		payload.objective_report = null;
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/objectives/obj_1/research-view') {
				return jsonResponse(payload);
			}

			if (path === '/api/v1/collections/col_123/objectives/obj_1/report' && init?.method === 'POST') {
				return jsonResponse({
					collection_id: 'col_123',
					report_id: 'orp_generating',
					objective_id: 'obj_1',
					status: 'generating',
					stage: 'requested',
					message: 'Objective report generation started.',
					title: 'Research objective report',
					language: 'zh',
					model: 'test-model',
					data_version: 'v2',
					markdown: null,
					warnings: [],
					source_refs: [],
					created_at: '2026-05-19T00:00:00+00:00',
					updated_at: '2026-05-19T00:00:00+00:00',
					generated_at: null
				});
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Report has not been generated' })).toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Generate report' }).click();
		await expect.element(browserPage.getByText('Objective report generation started.')).toBeInTheDocument();

		const reportRequest = fetchMock.mock.calls.find(
			([input]) => requestPath(input as string | URL | Request) === '/api/v1/collections/col_123/objectives/obj_1/report'
		);
		expect(reportRequest?.[1]?.method).toBe('POST');
		expect(JSON.parse(String(reportRequest?.[1]?.body))).toEqual({
			language: 'zh',
			force_regenerate: false
		});
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
