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
			confidence: 0.91
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

test('objective workspace renders logic-chain screenshots and source links', async ({
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
	await expect(page.getByRole('heading', { name: 'Logic chain' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Evidence units' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'table · table-2 · p. 5' })).toHaveAttribute(
		'href',
		'/collections/col_123/documents/doc_1?page=5&evidence_id=ev_1&anchor_id=anc_1&return_to=%2Fcollections%2Fcol_123%2Fobjectives%2Fobj_1'
	);
	await expectNoHorizontalOverflow(page);
	await page.screenshot({
		path: testInfo.outputPath('objective-workspace-desktop.png'),
		fullPage: true
	});

	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(`/collections/${collectionId}/objectives/${objectiveId}`);
	await expect(page.getByRole('heading', { name: 'Logic chain' })).toBeInViewport();
	await expect(page.getByRole('heading', { name: 'Evidence units' })).toBeVisible();
	await expectNoHorizontalOverflow(page);
	await page.screenshot({
		path: testInfo.outputPath('objective-workspace-mobile.png'),
		fullPage: true
	});
});
