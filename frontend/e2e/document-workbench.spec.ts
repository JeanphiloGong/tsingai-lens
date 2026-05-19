import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_123';
const documentId = 'doc_1';

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
		name: '316L LPBF evidence set',
		description: 'Document workbench screenshot fixture',
		status: 'ready',
		paper_count: 1,
		updated_at: '2026-05-13T00:00:00Z'
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
			updated_at: '2026-05-13T00:00:00Z'
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

function documentContentPayload() {
	return {
		collection_id: collectionId,
		document_id: documentId,
		title: 'Paper A',
		source_filename: 'paper-a.pdf',
		content_text:
			'Abstract\nConductivity improved to 12 mS/cm.\nMethodology\nThe sample was annealed at 700 C.\nResults\nConductivity improved to 12 mS/cm under EIS.',
		blocks: [
			{
				block_id: 'abstract',
				block_type: 'abstract',
				heading_path: 'Abstract',
				heading_level: 1,
				order: 1,
				text: 'Conductivity improved to 12 mS/cm.',
				start_offset: 9,
				end_offset: 43,
				text_unit_ids: [],
				page: 1,
				bbox: { x0: 18, y0: 20, x1: 82, y1: 24.5, coord_origin: 'percent' }
			},
			{
				block_id: 'methods',
				block_type: 'methods',
				heading_path: 'Methodology',
				heading_level: 1,
				order: 2,
				text: 'The sample was annealed at 700 C.',
				start_offset: 56,
				end_offset: 89,
				text_unit_ids: [],
				page: 2,
				bbox: { x0: 22, y0: 44, x1: 72, y1: 48.5, coord_origin: 'percent' }
			},
			{
				block_id: 'results',
				block_type: 'results',
				heading_path: 'Results',
				heading_level: 1,
				order: 3,
				text: 'Conductivity improved to 12 mS/cm under EIS.',
				start_offset: 98,
				end_offset: 143,
				text_unit_ids: [],
				page: 3,
				bbox: { x0: 18, y0: 62, x1: 76, y1: 66.5, coord_origin: 'percent' }
			}
		],
		warnings: []
	};
}

function researchPayload() {
	return {
		collection_id: collectionId,
		document_id: documentId,
		state: 'ready',
		paper_title: 'Paper A',
		overview: {
			material_systems: ['oxide cathode'],
			sample_variant_count: 1,
			main_process_variables: ['anneal temperature'],
			measured_properties: ['conductivity']
		},
		materials: [
			{
				material_id: 'oxide_cathode',
				canonical_name: 'oxide cathode',
				aliases: ['LiNiO2'],
				sample_count: 1,
				process_families: ['annealing'],
				measured_properties: ['conductivity'],
				comparison_count: 1,
				warnings: []
			}
		],
		sample_matrix: {
			matrix_id: 'sample_matrix',
			columns: [{ column_id: 'conductivity', key: 'conductivity', label: 'Conductivity' }],
			rows: [
				{
					row_id: 'row_1',
					sample_id: 'S1',
					sample_label: 'Sample A',
					material: 'oxide cathode',
					process_context: { anneal: '700 C' },
					values: {
						conductivity: {
							display_value: '12 mS/cm',
							status: 'observed',
							evidence_refs: [{ evidence_ref_id: 'ev_1', locator: 'Results' }]
						}
					}
				}
			]
		},
		condition_series: []
	};
}

function comparisonPayload() {
	return {
		collection_id: collectionId,
		document_id: documentId,
		total: 1,
		count: 1,
		items: [],
		variant_dossiers: [
			{
				variant_id: 'var_1',
				variant_label: 'optimized VED + HIP',
				material: { label: 'oxide cathode', composition: 'LiNiO2' },
				shared_process_state: { anneal_temperature_c: 700 },
				shared_missingness: [],
				series: [
					{
						series_key: 'conductivity:test_temperature_c',
						property_family: 'conductivity',
						test_family: 'EIS',
						varying_axis: { axis_name: 'test_temperature_c', axis_unit: 'C' },
						chains: [
							{
								result_id: 'cres_1',
								source_result_id: 'mr_1',
								measurement: {
									property: 'conductivity',
									value: 12,
									unit: 'mS/cm',
									result_type: 'scalar',
									summary: '12 mS/cm'
								},
								test_condition: { test_method: 'EIS', test_temperature_c: 25 },
								baseline: {
									label: 'as-prepared',
									reference: 'same-paper control',
									baseline_type: 'same_document',
									resolved: true
								},
								assessment: {
									comparability_status: 'comparable',
									warnings: [],
									basis: [],
									missing_context: [],
									requires_expert_review: false,
									assessment_epistemic_status: 'grounded'
								},
								value_provenance: {
									value_origin: 'reported',
									source_value_text: '12',
									source_unit_text: 'mS/cm'
								},
								evidence: {
									evidence_ids: ['ev_1'],
									direct_anchor_ids: ['anc_1'],
									contextual_anchor_ids: [],
									structure_feature_ids: [],
									characterization_observation_ids: [],
									traceability_status: 'direct'
								}
							}
						]
					}
				]
			}
		]
	};
}

async function mockWorkbenchApis(page: Page) {
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
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/content`) {
			return route.fulfill(json(documentContentPayload()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/research-view`) {
			return route.fulfill(json(researchPayload()));
		}
		if (path === `/api/v1/collections/${collectionId}/results`) {
			return route.fulfill({
				...json({
					collection_id: collectionId,
					total: 1,
					count: 1,
					items: []
				})
			});
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/comparison-semantics`) {
			return route.fulfill(json(comparisonPayload()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/source`) {
			return route.fulfill(json({ detail: 'source unavailable' }, 404));
		}

		return route.fulfill(json({ detail: `unhandled test route: ${path}` }, 404));
	});
}

async function expectNoHorizontalOverflow(page: Page) {
	const hasOverflow = await page.evaluate(() => {
		const root = document.querySelector('.document-workbench-root');
		const rootWidth = root instanceof HTMLElement ? root.scrollWidth : 0;
		const width = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth, rootWidth);
		return width > window.innerWidth + 1;
	});
	expect(hasOverflow).toBe(false);
}

test('document workbench renders desktop and mobile verification screenshots', async ({
	page
}, testInfo) => {
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await mockWorkbenchApis(page);

	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto(
		`/collections/${collectionId}/documents/${documentId}?page=2&return_to=/collections/${collectionId}/objectives/obj_1`
	);
	await expect(page.getByRole('heading', { name: 'Paper scope' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Paper A' })).toBeVisible();
	await expect(page.getByTestId('parsed-source-fallback')).toBeVisible();
	await expect(page.getByTestId('pdf-current-page')).toHaveText('2');
	await expectNoHorizontalOverflow(page);
	await page.screenshot({
		path: testInfo.outputPath('document-workbench-desktop.png'),
		fullPage: true
	});

	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(
		`/collections/${collectionId}/documents/${documentId}?page=2&return_to=/collections/${collectionId}/objectives/obj_1`
	);
	await expect(page.getByRole('heading', { name: 'Paper scope' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Paper A' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Paper scope' })).toBeInViewport();
	await expect(page.getByTestId('parsed-source-fallback')).toBeVisible();
	await expectNoHorizontalOverflow(page);
	await page.screenshot({
		path: testInfo.outputPath('document-workbench-mobile.png'),
		fullPage: true
	});
});
