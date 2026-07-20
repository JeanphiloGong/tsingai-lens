import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_123';
const objectiveId = 'obj_1';

function json(body: unknown, status = 200) {
	return {
		status,
		contentType: 'application/json',
		body: JSON.stringify(body)
	};
}

function collectionPayload() {
	return {
		collection_id: collectionId,
		id: collectionId,
		name: 'LPBF 316L objective set',
		description: 'Objective workspace screenshot fixture',
		status: 'ready',
		paper_count: 1,
		updated_at: '2026-05-14T00:00:00Z'
	};
}

function authPayload() {
	return {
		user: {
			user_id: 'user_1',
			email: 'reader@example.com',
			display_name: 'Reader'
		}
	};
}

function workspacePayload() {
	return {
		collection: collectionPayload(),
		file_count: 1,
		status_summary: 'ready',
		workflow: {
			documents: 'ready',
			results: 'ready',
			evidence: 'ready',
			comparisons: 'ready'
		},
		document_summary: {
			total_documents: 1,
			doc_type_counts: { experimental: 1, review: 0, mixed: 0, uncertain: 0 },
			warnings: []
		},
		artifacts: {
			documents_ready: true,
			document_profiles_ready: true,
			evidence_cards_ready: true,
			comparable_results_ready: true,
			comparison_rows_ready: true,
			graph_ready: true,
			updated_at: '2026-05-14T00:00:00Z'
		},
		latest_task: null,
		recent_tasks: [],
		capabilities: {},
		links: {
			workspace: `/collections/${collectionId}`,
			documents: `/collections/${collectionId}/documents`,
			results: `/collections/${collectionId}/results`,
			evidence: `/collections/${collectionId}/evidence`,
			comparisons: `/collections/${collectionId}/comparisons`,
			graph: `/collections/${collectionId}/graph`
		}
	};
}

function objectivePayload() {
	return {
		collection_id: collectionId,
		state: 'ready',
		objective: {
			objective_id: objectiveId,
			question: 'How does heat treatment affect LPBF 316L tensile strength?',
			material_scope: ['316L stainless steel'],
			process_axes: ['heat treatment'],
			property_axes: ['yield strength'],
			comparison_intent: 'Compare as-built and heat-treated LPBF 316L.',
			confidence: 0.91,
			status: 'ready',
			analysis_error: null,
			analysis_progress: null,
			created_at: '2026-05-14T00:00:00Z',
			updated_at: '2026-05-14T00:00:00Z'
		},
		objective_context: {
			objective_id: objectiveId,
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
				objective_id: objectiveId,
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
				objective_id: objectiveId,
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
				objective_id: objectiveId,
				document_id: 'doc_1',
				unit_kind: 'measurement',
				property_normalized: 'yield strength',
				sample_context: { sample: 'HT-SLM' },
				process_context: { process: 'LPBF', heat_treatment: 'annealed' },
				test_condition: { method: 'tensile test' },
				value_payload: { statement: 'Yield strength reached 560 MPa.' },
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
				resolution_status: 'resolved',
				confidence: 0.92
			},
			{
				evidence_unit_id: 'unit_condition',
				objective_id: objectiveId,
				document_id: 'doc_1',
				unit_kind: 'test_condition',
				property_normalized: 'yield strength',
				test_condition: { method: 'tensile test', standard: 'ASTM E8' },
				value_payload: { statement: 'Tensile testing followed ASTM E8.' },
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.86
			},
			{
				evidence_unit_id: 'unit_obs',
				objective_id: objectiveId,
				document_id: 'doc_1',
				unit_kind: 'characterization',
				property_normalized: 'microstructure',
				value_payload: { observation_text: 'Annealing reduced cellular substructure.' },
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.82
			},
			{
				evidence_unit_id: 'unit_compare',
				objective_id: objectiveId,
				document_id: 'doc_1',
				unit_kind: 'comparison',
				property_normalized: 'yield strength',
				sample_context: { sample: 'HT-SLM' },
				baseline_context: { sample: 'as-built' },
				value_payload: { statement: 'Heat-treated samples exceeded the as-built baseline.' },
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.79
			}
		],
		logic_chain: {
			logic_chain_id: 'chain_1',
			objective_id: objectiveId,
			chain_scope: 'objective',
			question: 'How does heat treatment affect LPBF 316L tensile strength?',
			evidence_unit_ids: ['unit_measure', 'unit_condition', 'unit_obs'],
			summary: 'Heat-treated LPBF 316L is supported by tensile and microstructure evidence.',
			chain_payload: {
				cross_paper: {
					gaps: ['No cross-paper comparison unit yet.']
				}
			},
			confidence: 0.83
		},
		understanding: {
			schema_version: 'research_understanding.v1',
			state: 'ready',
			scope: {
				scope_type: 'objective',
				collection_id: collectionId,
				material_id: null,
				objective_id: objectiveId,
				document_id: null,
				title: 'How does heat treatment affect LPBF 316L tensile strength?'
			},
			claims: [
				{
					claim_id: 'claim_measure',
					claim_type: 'measurement',
					statement: 'Yield strength reached 560 MPa.',
					status: 'supported',
					confidence: 0.92,
					strength: null,
					evidence_ref_ids: ['ref_measure'],
					context_ids: ['ctx_objective'],
					source_object_ids: ['unit_measure'],
					warnings: []
				}
			],
			relations: [
				{
					relation_id: 'rel_heat_treatment',
					relation_type: 'improves',
					subject: 'HT-SLM',
					predicate: 'improves',
					object: 'as-built baseline',
					status: 'supported',
					confidence: 0.79,
					evidence_ref_ids: ['ref_measure'],
					context_ids: ['ctx_objective'],
					source_object_ids: ['unit_compare'],
					warnings: []
				}
			],
			evidence_refs: [
				{
					evidence_ref_id: 'ref_measure',
					source_kind: 'table',
					document_id: 'doc_1',
					label: 'table · table-2 · p. 5',
					locator: { source_ref: 'table-2', page: 5 },
					fact_ids: ['unit_measure'],
					anchor_ids: ['anc_1'],
					confidence: 0.92,
					traceability_status: 'resolved',
					quote: 'Yield strength reached 560 MPa.',
					href: null
				}
			],
			contexts: [
				{
					context_id: 'ctx_objective',
					label: 'Objective scope',
					material_scope: ['316L stainless steel'],
					process_context: { variable_process_axes: ['heat treatment'] },
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
			},
			presentation: {
				summary: {
					title: 'How does heat treatment affect LPBF 316L tensile strength?',
					material_scope: ['316L stainless steel'],
					variable_axes: ['heat treatment'],
					property_scope: ['yield strength'],
					claim_count: 1,
					relation_count: 1,
					evidence_count: 1,
					context_count: 1,
					review_queue_count: 1,
					primary_finding_count: 1,
					review_queue_finding_count: 0
				},
				effects: [
					{
						effect_id: 'effect_measure',
						claim_id: 'claim_measure',
						title: 'heat treatment -> yield strength',
						statement: 'Heat-treated LPBF 316L reached a yield strength of 560 MPa.',
						claim_type: 'finding',
						support_status: 'limited',
						confidence: 0.92,
						effect_direction: 'improves',
						variable_axis: 'heat treatment',
						target_property: 'yield strength',
						paper_count: 1,
						evidence_count: 1,
						context_summary: '316L stainless steel, LPBF, tensile test',
						evidence_ref_ids: ['ref_measure'],
						context_ids: ['ctx_objective'],
						relation_ids: ['rel_heat_treatment'],
						needs_review: true,
						warnings: ['needs_expert_review']
					}
				],
				findings: [
					{
						finding_id: 'finding_measure',
						claim_id: 'claim_measure',
						title: 'heat treatment -> yield strength',
						statement: 'Heat-treated LPBF 316L reached a yield strength of 560 MPa.',
						variables: ['heat treatment'],
						mediators: ['cellular substructure'],
						outcomes: ['yield strength'],
						direction: 'improves',
						scope_summary: '316L stainless steel, LPBF, tensile test',
						support_grade: 'partial',
						review_status: 'needs_review',
						confidence: 0.92,
						paper_count: 1,
						evidence_count: 1,
						evidence_ref_ids: ['ref_measure'],
						context_ids: ['ctx_objective'],
						relation_ids: ['rel_heat_treatment'],
						evidence_bundle: {
							direct_result: ['ref_measure'],
							mechanism: [],
							condition_context: [],
							background: [],
							conflict: [],
							noise: [],
							uncategorized: []
						},
						expert_use_status: 'paper_level_finding',
						dataset_use_status: 'review_candidate',
						generalization_status: 'paper_level_only',
						generalization_note:
							'Evidence comes from one paper; use this as a traceable paper-level finding, not a cross-paper conclusion.',
						evidence_gap_summary:
							'Needs independent cross-paper confirmation, support-grade curation, expert review.',
						upgrade_actions: [
							'verify_direct_evidence',
							'add_cross_paper_evidence',
							'curate_support_grade',
							'record_expert_review'
						],
						review_reasons: [
							'single_paper_evidence',
							'needs_cross_paper_confirmation',
							'partial_support',
							'needs_expert_review'
						],
						warnings: ['needs_expert_review']
					}
				],
				primary_findings: [
					{
						finding_id: 'finding_measure',
						claim_id: 'claim_measure',
						title: 'heat treatment -> yield strength',
						statement: 'Heat-treated LPBF 316L reached a yield strength of 560 MPa.',
						variables: ['heat treatment'],
						mediators: ['cellular substructure'],
						outcomes: ['yield strength'],
						direction: 'improves',
						scope_summary: '316L stainless steel, LPBF, tensile test',
						support_grade: 'partial',
						review_status: 'needs_review',
						confidence: 0.92,
						paper_count: 1,
						evidence_count: 1,
						evidence_ref_ids: ['ref_measure'],
						context_ids: ['ctx_objective'],
						relation_ids: ['rel_heat_treatment'],
						evidence_bundle: {
							direct_result: ['ref_measure'],
							mechanism: [],
							condition_context: [],
							background: [],
							conflict: [],
							noise: [],
							uncategorized: []
						},
						expert_use_status: 'paper_level_finding',
						dataset_use_status: 'review_candidate',
						generalization_status: 'paper_level_only',
						generalization_note:
							'Evidence comes from one paper; use this as a traceable paper-level finding, not a cross-paper conclusion.',
						evidence_gap_summary:
							'Needs independent cross-paper confirmation, support-grade curation, expert review.',
						upgrade_actions: [
							'verify_direct_evidence',
							'add_cross_paper_evidence',
							'curate_support_grade',
							'record_expert_review'
						],
						review_reasons: [
							'single_paper_evidence',
							'needs_cross_paper_confirmation',
							'partial_support',
							'needs_expert_review'
						],
						warnings: ['needs_expert_review']
					}
				],
				review_queue_findings: [],
				evidence_items: [
					{
						evidence_ref_id: 'ref_measure',
						document_id: 'doc_1',
						title: 'table · table-2 · p. 5',
						source_label: 'table · table-2 · p. 5',
						source_kind: 'table',
						source_ref: 'table-2',
						block_type: 'table',
						heading_path: 'Results',
						page: '5',
						quote: 'Yield strength reached 560 MPa.',
						source_text: 'Yield strength reached 560 MPa.',
						value_summary: 'Yield strength reached 560 MPa.',
						traceability_status: 'resolved',
						evidence_role: 'direct_result',
						confidence: 0.92,
						href: null
					}
				],
				context_summaries: [
					{
						context_id: 'ctx_objective',
						label: 'Objective scope',
						material_scope: ['316L stainless steel'],
						property_scope: ['yield strength'],
						process_summary: 'heat treatment',
						test_summary: 'tensile test',
						limitations: ['single paper evidence']
					}
				]
			}
		}
	};
}

async function mockObjectiveApis(page: Page) {
	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;

		if (!path.startsWith('/api/v1/')) {
			return route.continue();
		}

		if (path === '/api/v1/auth/me') {
			return route.fulfill(json(authPayload()));
		}
		if (path === '/api/v1/collections') {
			return route.fulfill(json({ items: [collectionPayload()] }));
		}
		if (path === `/api/v1/collections/${collectionId}`) {
			return route.fulfill(json(collectionPayload()));
		}
		if (path === `/api/v1/collections/${collectionId}/workspace`) {
			return route.fulfill(json(workspacePayload()));
		}
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}/research-view`) {
			return route.fulfill(json(objectivePayload()));
		}
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}/experiment-plans`) {
			return route.fulfill(
				json({ collection_id: collectionId, objective_id: objectiveId, items: [] })
			);
		}
		if (path === `/api/v1/collections/${collectionId}/research-understanding/dataset`) {
			return route.fulfill(
				json({
					schema_version: 'research_understanding_dataset.v1',
					dataset_id: 'rud_obj_1',
					collection_id: collectionId,
					objective_id: objectiveId,
					task_type: 'research_understanding_finding',
					metric_profile: 'materials_expert',
					label_status_filter: null,
					item_count: 1,
					label_counts: { candidate: 1, silver: 0, gold: 0, rejected: 0 },
					warnings: []
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/research-understanding/feedback`) {
			return route.fulfill(json({ collection_id: collectionId, items: [] }));
		}
		if (path === `/api/v1/collections/${collectionId}/research-understanding/curations`) {
			return route.fulfill(json({ collection_id: collectionId, items: [] }));
		}

		return route.fulfill(json({ detail: `unhandled test route: ${path}` }, 404));
	});
}

async function mockObjectivesNotReadyApis(page: Page) {
	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;

		if (!path.startsWith('/api/v1/')) {
			return route.continue();
		}

		if (path === '/api/v1/auth/me') {
			return route.fulfill(json(authPayload()));
		}
		if (path === '/api/v1/collections') {
			return route.fulfill(json({ items: [collectionPayload()] }));
		}
		if (path === `/api/v1/collections/${collectionId}`) {
			return route.fulfill(json(collectionPayload()));
		}
		if (path === `/api/v1/collections/${collectionId}/workspace`) {
			return route.fulfill(json(workspacePayload()));
		}
		if (path === `/api/v1/collections/${collectionId}/objectives`) {
			return route.fulfill(
				json(
					{
						code: 'research_objectives_not_ready',
						message:
							'The collection does not have research objectives yet. Finish processing first.',
						collection_id: collectionId
					},
					409
				)
			);
		}

		return route.fulfill(json({ detail: `unhandled test route: ${path}` }, 404));
	});
}

async function expectNoHorizontalOverflow(page: Page) {
	const hasOverflow = await page.evaluate(() => {
		const width = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
		return width > window.innerWidth + 1;
	});
	expect(hasOverflow).toBe(false);
}

test('objective workspace renders research understanding screenshots and source links', async ({
	page
}, testInfo) => {
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await mockObjectiveApis(page);

	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto(`/collections/${collectionId}/objectives/${objectiveId}`);
	await expect(
		page.getByRole('heading', {
			name: 'How does heat treatment affect LPBF 316L tensile strength?'
		})
	).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Research understanding' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Findings' })).toBeVisible();
	await expect(page.getByRole('columnheader', { name: 'Finding' })).toBeVisible();
	await expect(page.getByRole('columnheader', { name: 'Variables' })).toBeVisible();
	await expect(page.getByRole('columnheader', { name: 'Mechanism' })).toBeVisible();
	await expect(page.getByRole('columnheader', { name: 'Result' })).toBeVisible();
	await expect(page.getByRole('columnheader', { name: 'Actions' })).toBeVisible();
	await expect(
		page.getByLabel('Research findings table').getByText('Heat-treated LPBF 316L reached a yield strength of 560 MPa.')
	).toBeVisible();
	await expect(page.getByRole('cell', { name: 'heat treatment', exact: true })).toBeVisible();
	await expect(page.getByRole('cell', { name: 'cellular substructure', exact: true })).toBeVisible();
	await expect(page.getByLabel('Research findings table').getByText('Paper-level finding')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Review evidence' })).toBeVisible();
	await page.getByRole('button', { name: 'Review evidence' }).click();
	await expect(page.getByRole('heading', { name: 'Finding detail' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Direct result evidence' })).toBeVisible();
	await expect(page.getByText('table · table-2 · p. 5').first()).toBeVisible();
	const understandingEvidence = page.getByRole('link', { name: 'Open source' }).first();
	await expect(understandingEvidence).toHaveAttribute(
		'href',
		'/collections/col_123/documents/doc_1?view=parsed-paper&page=5&source_ref=table-2&evidence_id=ref_measure&anchor_id=anc_1&quote=Yield%20strength%20reached%20560%20MPa.&return_to=%2Fcollections%2Fcol_123%2Fobjectives%2Fobj_1'
	);
	await page.getByText('Evidence audit').click();
	await expect(page.getByRole('heading', { name: 'Supporting evidence' })).toBeVisible();
	await expectNoHorizontalOverflow(page);
	await page.screenshot({
		path: testInfo.outputPath('objective-workspace-desktop.png'),
		fullPage: true
	});

	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(`/collections/${collectionId}/objectives/${objectiveId}`);
	const mobileUnderstandingHeading = page.getByRole('heading', { name: 'Research understanding' });
	await mobileUnderstandingHeading.scrollIntoViewIfNeeded();
	await expect(mobileUnderstandingHeading).toBeInViewport();
	await expect(page.getByRole('heading', { name: 'Findings' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Review evidence' })).toBeVisible();
	await page.getByText('Evidence audit').click();
	await expect(page.getByRole('heading', { name: 'Supporting evidence' })).toBeVisible();
	await expectNoHorizontalOverflow(page);
	await page.screenshot({
		path: testInfo.outputPath('objective-workspace-mobile.png'),
		fullPage: true
	});
});

test('objectives page treats not-ready responses as a pending workflow state', async ({ page }) => {
	await mockObjectivesNotReadyApis(page);

	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto(`/collections/${collectionId}/objectives`);
	await expect(page.getByRole('heading', { name: 'Research objectives are not ready yet' })).toBeVisible();
	await expect(
		page.getByText('Finish collection processing before reviewing objectives.')
	).toBeVisible();
	await expect(page.getByRole('link', { name: 'Open collection overview' })).toHaveAttribute(
		'href',
		`/collections/${collectionId}`
	);
	await expect(page.getByText(/409 Conflict/)).toHaveCount(0);
	await expect(page.getByText(/research_objectives_not_ready/)).toHaveCount(0);
	await expectNoHorizontalOverflow(page);
});
