import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_123';
const documentId = 'doc_1';
const materialId = 'mat_316l';
const objectiveId = 'obj_1';
const resultId = 'cres_1';
const sessionId = 'gs_1';
const screenshotDir = process.env.PAGE_AUDIT_SCREENSHOT_DIR ?? '';

if (screenshotDir) {
	mkdirSync(screenshotDir, { recursive: true });
}

const routes = [
	['/', 'Lens Workbench'],
	['/docs', 'Using Lens'],
	['/system', 'System'],
	['/configs', 'Legacy Config Routes Retired'],
	['/configs/create', 'Legacy Config Create Route Retired'],
	['/configs/list', 'Legacy Config List Route Retired'],
	['/configs/upload', 'Legacy Config Upload Route Retired'],
	['/configs/view', 'Legacy Config View Route Retired'],
	['/export', 'Legacy Export Route Retired'],
	['/index', 'Legacy Index Route Retired'],
	['/index/config', 'Legacy Index Config Route Retired'],
	['/index/upload', 'Legacy Index Upload Route Retired'],
	['/upload', 'Legacy Upload Route Retired'],
	[`/collections/${collectionId}`, 'Research overview'],
	[`/collections/${collectionId}/documents`, 'Paper coverage table'],
	[`/collections/${collectionId}/documents/${documentId}?page=2`, 'Paper scope'],
	[`/collections/${collectionId}/materials`, 'Materials'],
	[`/collections/${collectionId}/materials/${materialId}`, '316L stainless steel'],
	[`/collections/${collectionId}/objectives`, 'Research objectives'],
	[`/collections/${collectionId}/objectives/${objectiveId}`, 'Logic chain'],
	[`/collections/${collectionId}/results`, 'Extracted Results'],
	[`/collections/${collectionId}/results/${resultId}`, 'Evidence chain'],
	[`/collections/${collectionId}/evidence`, 'Evidence Review'],
	[`/collections/${collectionId}/comparisons`, 'Comparable groups'],
	[`/collections/${collectionId}/graph`, 'Collection Knowledge Map'],
	[`/collections/${collectionId}/assistant`, 'Research Copilot']
] as const;

test.describe('page interaction audit', () => {
	test.beforeEach(async ({ page }) => {
		await page.emulateMedia({ reducedMotion: 'reduce' });
		await mockApis(page);
	});

	for (const [path, readyText] of routes) {
		test(`${path} renders usable desktop and mobile viewports`, async ({ page }) => {
			const consoleErrors: string[] = [];
			page.on('console', (message) => {
				if (message.type() === 'error') consoleErrors.push(message.text());
			});
			page.on('pageerror', (error) => consoleErrors.push(error.message));

			await checkViewport(page, path, readyText, { width: 1440, height: 900 });
			await checkViewport(page, path, readyText, { width: 390, height: 844 });

			expect(consoleErrors, `console errors on ${path}`).toEqual([]);
		});
	}
});

async function checkViewport(
	page: Page,
	path: string,
	readyText: string,
	viewport: { width: number; height: number }
) {
	await page.setViewportSize(viewport);
	await page.goto(path);
	await expect(page.getByText(readyText).first()).toBeVisible();
	await waitForVisualReady(page, path);
	await expectVisibleInteractionsHaveNames(page);
	await expectNoHorizontalOverflow(page);
	if (screenshotDir) {
		await page.screenshot({
			path: join(screenshotDir, `${routeScreenshotName(path)}-${viewport.width}.png`),
			fullPage: true
		});
	}
}

async function waitForVisualReady(page: Page, path: string) {
	await page.waitForLoadState('networkidle');
	if (path.endsWith('/graph')) {
		await expect(page.getByText('Graph built').first()).toBeVisible();
	}
}

function routeScreenshotName(path: string) {
	return path
		.replace(/^\//, 'root/')
		.replace(/[^a-z0-9]+/gi, '-')
		.replace(/^-|-$/g, '')
		.toLowerCase();
}

async function expectNoHorizontalOverflow(page: Page) {
	const overflow = await page.evaluate(() => {
		const root = document.querySelector('.document-workbench-root');
		const rootWidth = root instanceof HTMLElement ? root.scrollWidth : 0;
		const width = Math.max(
			document.documentElement.scrollWidth,
			document.body.scrollWidth,
			rootWidth
		);
		return { width, innerWidth: window.innerWidth, overflowing: width > window.innerWidth + 1 };
	});
	expect(overflow.overflowing, `page width ${overflow.width} exceeds ${overflow.innerWidth}`).toBe(
		false
	);
}

async function expectVisibleInteractionsHaveNames(page: Page) {
	const unnamed = await page.evaluate(() => {
		const selector = [
			'a[href]',
			'button:not([disabled])',
			'input:not([disabled])',
			'select:not([disabled])',
			'textarea:not([disabled])',
			'summary'
		].join(',');
		return Array.from(document.querySelectorAll<HTMLElement>(selector))
			.filter((element) => {
				const rect = element.getBoundingClientRect();
				const style = window.getComputedStyle(element);
				return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden';
			})
			.filter((element) => {
				const id = element.id;
				const labelledBy = element.getAttribute('aria-labelledby');
				const label =
					(id && document.querySelector(`label[for="${CSS.escape(id)}"]`)?.textContent?.trim()) ||
					element.closest('label')?.textContent?.trim() ||
					(labelledBy && document.getElementById(labelledBy)?.textContent?.trim()) ||
					element.getAttribute('aria-label')?.trim() ||
					element.getAttribute('title')?.trim() ||
					element.getAttribute('placeholder')?.trim() ||
					element.textContent?.trim();
				return !label;
			})
			.map((element) => element.outerHTML.slice(0, 160));
	});
	expect(unnamed).toEqual([]);
}

async function mockApis(page: Page) {
	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;
		const method = route.request().method();

		if (!path.startsWith('/api/v1/')) return route.continue();

		if (path === '/api/v1/collections') {
			if (method === 'POST') return route.fulfill(json(collection()));
			return route.fulfill(json({ items: [collection()] }));
		}
		if (path === `/api/v1/collections/${collectionId}`) return route.fulfill(json(collection()));
		if (path === `/api/v1/collections/${collectionId}/workspace`)
			return route.fulfill(json(workspace()));
		if (path === `/api/v1/collections/${collectionId}/files`) {
			return route.fulfill(json({ count: 1, items: [uploadedFile()] }));
		}
		if (path === `/api/v1/collections/${collectionId}/tasks/build`) {
			return route.fulfill(json(task()));
		}
		if (path === `/api/v1/collections/${collectionId}/research-view`) {
			return route.fulfill(json(collectionResearchView()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/profiles`) {
			return route.fulfill(json(documentProfiles()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/profile`) {
			return route.fulfill(json(documentProfile()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/content`) {
			return route.fulfill(json(documentContent()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/research-view`) {
			return route.fulfill(json(documentResearchView()));
		}
		if (
			path === `/api/v1/collections/${collectionId}/documents/${documentId}/comparison-semantics`
		) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					document_id: documentId,
					total: 1,
					count: 1,
					items: [],
					variant_dossiers: [variantDossier()]
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/source`) {
			return route.fulfill({ status: 204, body: '' });
		}
		if (path === `/api/v1/collections/${collectionId}/materials`) {
			return route.fulfill(json({ items: [materialSummary()] }));
		}
		if (path === `/api/v1/collections/${collectionId}/materials/${materialId}/research-view`) {
			return route.fulfill(json(materialProfile()));
		}
		if (path === `/api/v1/collections/${collectionId}/materials/${materialId}/review-report`) {
			return route.fulfill(
				json({ status: 'ready', pdf_url: '#', markdown_url: '#', updated_at: now() })
			);
		}
		if (path === `/api/v1/collections/${collectionId}/objectives`) {
			return route.fulfill(json(objectives()));
		}
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}/research-view`) {
			return route.fulfill(json(objectiveView()));
		}
		if (path === `/api/v1/collections/${collectionId}/results`)
			return route.fulfill(json(results()));
		if (path === `/api/v1/collections/${collectionId}/results/${resultId}`) {
			return route.fulfill(json(resultDetail()));
		}
		if (path === `/api/v1/collections/${collectionId}/evidence/cards`) {
			return route.fulfill(
				json({ collection_id: collectionId, total: 1, count: 1, items: [evidence()] })
			);
		}
		if (path === `/api/v1/collections/${collectionId}/evidence/ev_1`) {
			return route.fulfill(json(evidence()));
		}
		if (path === `/api/v1/collections/${collectionId}/evidence/ev_1/traceback`) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					evidence_id: 'ev_1',
					traceback_status: 'ready',
					anchors: evidence().evidence_anchors
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/comparisons`) {
			return route.fulfill(json({ collection_id: collectionId, total: 0, count: 0, items: [] }));
		}
		if (path === `/api/v1/collections/${collectionId}/comparisons/cmp_1`) {
			return route.fulfill(json({ row_id: 'cmp_1', collection_id: collectionId }));
		}
		if (path === `/api/v1/collections/${collectionId}/graph`) return route.fulfill(json(graph()));
		if (path.startsWith(`/api/v1/collections/${collectionId}/graph/nodes/`)) {
			return route.fulfill(json(graph()));
		}
		if (path === `/api/v1/collections/${collectionId}/graphml`) {
			return route.fulfill({
				status: 200,
				contentType: 'application/graphml+xml',
				body: '<graphml />'
			});
		}
		if (path === '/api/v1/goal-sessions') return route.fulfill(json(goalSession(), 201));
		if (path === `/api/v1/goal-sessions/${sessionId}`) return route.fulfill(json(goalSession()));
		if (path === `/api/v1/goal-sessions/${sessionId}/messages`) {
			return route.fulfill(json({ session_id: sessionId, items: [] }));
		}

		return route.fulfill(json({ detail: `unhandled audit route: ${path}` }, 404));
	});
}

function json(body: unknown, status = 200) {
	return { status, contentType: 'application/json', body: JSON.stringify(body) };
}

function now() {
	return '2026-05-14T00:00:00Z';
}

function collection() {
	return {
		collection_id: collectionId,
		id: collectionId,
		name: '316L LPBF evidence set',
		description: 'Interaction audit fixture',
		status: 'ready',
		paper_count: 2,
		created_at: now(),
		updated_at: now()
	};
}

function workspace() {
	return {
		collection: collection(),
		file_count: 2,
		status_summary: 'ready',
		workflow: { documents: 'ready', results: 'ready', evidence: 'ready', comparisons: 'ready' },
		document_summary: {
			total_documents: 2,
			doc_type_counts: { experimental: 2, review: 0, mixed: 0, uncertain: 0 },
			warnings: []
		},
		warnings: [],
		artifacts: {
			documents_ready: true,
			document_profiles_ready: true,
			evidence_cards_ready: true,
			comparable_results_ready: true,
			collection_comparable_results_ready: true,
			comparison_rows_ready: true,
			graph_ready: true,
			graph_stale: false,
			updated_at: now()
		},
		latest_task: null,
		recent_tasks: [],
		capabilities: {
			can_view_documents: true,
			can_view_results: true,
			can_view_evidence: true,
			can_view_comparisons: true,
			can_view_graph: true,
			can_download_graphml: true
		},
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

function uploadedFile() {
	return {
		file_id: 'file_1',
		collection_id: collectionId,
		original_filename: 'paper-a.pdf',
		stored_filename: 'paper-a.pdf',
		stored_path: '/tmp/paper-a.pdf',
		media_type: 'application/pdf',
		status: 'uploaded',
		size_bytes: 2048,
		created_at: now()
	};
}

function task() {
	return {
		task_id: 'task_1',
		collection_id: collectionId,
		task_type: 'build_collection',
		status: 'queued',
		current_stage: 'queued',
		progress_percent: 5,
		output_path: null,
		errors: [],
		warnings: [],
		created_at: now(),
		updated_at: now(),
		started_at: null,
		finished_at: null
	};
}

function evidenceRef() {
	return {
		evidence_ref_id: 'ev_1',
		fact_ids: [],
		anchor_ids: ['anc_1'],
		document_id: documentId,
		source_kind: 'table',
		locator: 'Table 2',
		confidence: 0.95,
		traceability_status: 'direct'
	};
}

function value(displayValue: string) {
	return {
		display_value: displayValue,
		value: null,
		unit: null,
		normalized_value: null,
		normalized_unit: null,
		status: 'observed',
		confidence: 0.95,
		evidence_refs: [evidenceRef()],
		duplicate_count: 0,
		conflict_status: null,
		warnings: []
	};
}

function collectionResearchView() {
	return {
		collection_id: collectionId,
		state: 'ready',
		overview: {
			document_count: 2,
			sample_count: 2,
			measurement_count: 2,
			evidence_count: 1,
			material_systems: ['oxide cathode'],
			process_families: ['annealing'],
			variable_axes: ['temperature'],
			measured_properties: ['conductivity'],
			coverage_quality: 'ready'
		},
		materials: [materialSummary()],
		paper_coverage: [
			{
				document_id: documentId,
				title: 'Paper A',
				state: 'ready',
				sample_count: 2,
				process_param_count: 3,
				measurement_count: 4,
				condition_count: 1,
				evidence_count: 5,
				issue_count: 0,
				primary_warnings: [],
				links: {}
			}
		],
		comparable_groups: [
			{
				group_id: 'grp_1',
				title: 'Anneal temperature vs conductivity',
				material_system: 'oxide cathode',
				process_family: 'annealing',
				variable_axis: 'temperature',
				fixed_conditions: { atmosphere: 'air' },
				properties: ['conductivity'],
				documents: [documentId],
				samples: ['S1'],
				comparability_status: 'comparable',
				matrix: {
					matrix_id: 'matrix_1',
					group_id: 'grp_1',
					columns: [],
					rows: [
						{
							row_id: 'mx_row_1',
							document_id: documentId,
							sample_id: 'S1',
							sample_label: 'Sample A',
							material: 'oxide cathode',
							process_context: { process: 'annealing' },
							variable_value: '700 C',
							test_condition: 'EIS',
							property: 'conductivity',
							result: value('12 mS/cm'),
							evidence_refs: [evidenceRef()],
							warnings: []
						}
					],
					warnings: []
				},
				evidence_refs: [evidenceRef()],
				warnings: []
			}
		],
		cross_paper_matrices: [],
		trend_series: [],
		evidence_links: {},
		debug_links: {},
		warnings: []
	};
}

function materialSummary() {
	return {
		material_id: materialId,
		canonical_name: '316L stainless steel',
		aliases: ['316L'],
		paper_count: 2,
		sample_count: 6,
		process_families: ['LPBF'],
		measured_properties: ['density', 'hardness'],
		comparison_count: 3,
		evidence_coverage: 0.75,
		state: 'ready',
		links: {},
		warnings: []
	};
}

function materialProfile() {
	return {
		collection_id: collectionId,
		material_id: materialId,
		canonical_name: '316L stainless steel',
		aliases: ['316L'],
		state: 'ready',
		overview: {
			paper_count: 1,
			sample_count: 1,
			comparison_count: 1,
			evidence_count: 3,
			process_families: ['LPBF'],
			measured_properties: ['hardness'],
			variable_axes: ['scan strategy']
		},
		papers: [
			{
				document_id: documentId,
				title: 'Paper A',
				source_filename: 'paper-a.pdf',
				state: 'ready',
				sample_count: 1,
				process_families: ['LPBF'],
				measured_properties: ['hardness'],
				evidence_count: 3
			}
		],
		sample_matrix: {
			columns: [{ value_key: 'hardness', label: 'Hardness', unit: 'HV' }],
			rows: [
				{
					row_id: 'row_1',
					sample_id: 'S1',
					sample_label: 'Sample A',
					material: '316L stainless steel',
					process_context: { scan_strategy: 'alternating' },
					values: { hardness: value('215 HV') },
					evidence_refs: [evidenceRef()],
					warnings: []
				}
			]
		},
		comparable_groups: [],
		evidence_links: {},
		warnings: []
	};
}

function documentProfiles() {
	return {
		collection_id: collectionId,
		total: 1,
		count: 1,
		summary: {
			total_documents: 1,
			doc_type_counts: {
				experimental: 1,
				review: 0,
				method: 0,
				computational: 0,
				mixed: 0,
				uncertain: 0
			},
			warnings: []
		},
		items: [documentProfile()]
	};
}

function documentProfile() {
	return {
		document_id: documentId,
		collection_id: collectionId,
		title: 'Paper A',
		source_filename: 'paper-a.txt',
		doc_type: 'experimental',
		parsing_warnings: [],
		confidence: 0.9,
		page_count: 3,
		updated_at: now(),
		processing_status: 'completed'
	};
}

function documentContent() {
	return {
		collection_id: collectionId,
		document_id: documentId,
		title: 'Paper A',
		source_filename: 'paper-a.txt',
		content_text:
			'Abstract\nConductivity improved to 12 mS/cm.\nResults\nConductivity improved to 12 mS/cm under EIS.',
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
				bbox: null
			},
			{
				block_id: 'results',
				block_type: 'results',
				heading_path: 'Results',
				heading_level: 1,
				order: 2,
				text: 'Conductivity improved to 12 mS/cm under EIS.',
				start_offset: 52,
				end_offset: 97,
				text_unit_ids: [],
				page: 3,
				bbox: null
			}
		],
		warnings: []
	};
}

function documentResearchView() {
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
				aliases: [],
				sample_count: 1,
				process_families: ['annealing'],
				measured_properties: ['conductivity'],
				comparison_count: 1,
				warnings: []
			}
		],
		sample_matrix: {
			matrix_id: 'sample_matrix',
			document_id: documentId,
			state: 'ready',
			columns: [{ column_id: 'conductivity', key: 'conductivity', label: 'Conductivity' }],
			rows: [
				{
					row_id: 'row_1',
					document_id: documentId,
					sample_id: 'S1',
					sample_label: 'Sample A',
					material: 'oxide cathode',
					process_context: { anneal: '700 C' },
					variable_axis: null,
					variable_value: null,
					values: { conductivity: value('12 mS/cm') },
					evidence_refs: [evidenceRef()],
					warnings: []
				}
			],
			warnings: []
		},
		condition_series: []
	};
}

function variantDossier() {
	return {
		variant_id: 'var_1',
		variant_label: 'optimized VED + HIP',
		material: { label: 'oxide cathode', composition: 'LiNiO2', host_material_system: null },
		shared_process_state: { anneal_temperature_c: 700 },
		shared_missingness: [],
		series: []
	};
}

function resultItem(id = resultId, material = 'oxide cathode') {
	return {
		result_id: id,
		document_id: documentId,
		document_title: 'Paper A',
		material_label: material,
		variant_label: 'Sample A',
		property: 'conductivity',
		value: 12,
		unit: 'mS/cm',
		summary: '12 mS/cm',
		baseline: 'as-prepared',
		test_condition: 'EIS',
		process: '700 C',
		traceability_status: 'direct',
		comparability_status: 'comparable',
		requires_expert_review: false,
		confidence: 0.9,
		result_type: 'scalar',
		source_evidence_quote: 'conductivity is reported for oxide cathode.',
		source_type: 'table',
		source_section: 'Results',
		source_location: 'Table 2',
		evidence_ids: ['ev_1'],
		anchor_ids: ['anc_1'],
		missing_context: [],
		warnings: [],
		created_at: now(),
		updated_at: now()
	};
}

function results() {
	return {
		collection_id: collectionId,
		total: 2,
		count: 2,
		items: [resultItem(), resultItem('cres_2', 'layered oxide')]
	};
}

function resultDetail() {
	return {
		result_id: resultId,
		document: { document_id: documentId, title: 'Paper A', source_filename: 'paper-a.txt' },
		material: { label: 'oxide cathode', variant_id: 'var_1', variant_label: 'Sample A' },
		measurement: {
			property: 'conductivity',
			value: 12,
			unit: 'mS/cm',
			result_type: 'scalar',
			summary: '12 mS/cm',
			statistic_type: null,
			uncertainty: null
		},
		context: {
			process: '700 C',
			baseline: 'as-prepared',
			baseline_reference: 'same-paper control',
			test_condition: 'EIS',
			axis_name: null,
			axis_value: null,
			axis_unit: null
		},
		assessment: {
			comparability_status: 'comparable',
			warnings: [],
			basis: [],
			missing_context: [],
			requires_expert_review: false,
			assessment_epistemic_status: 'grounded'
		},
		evidence: [
			{
				evidence_id: 'ev_1',
				traceability_status: 'direct',
				source_type: 'text',
				anchor_ids: ['anc_1']
			}
		],
		actions: {
			open_document: `/collections/${collectionId}/documents/${documentId}`,
			open_comparisons: `/collections/${collectionId}/comparisons?property_normalized=conductivity`,
			open_evidence: null
		},
		variant_dossier: variantDossier(),
		test_condition_detail: { test_method: 'EIS', test_temperature_c: 25, environment: 'air' },
		baseline_detail: {
			label: 'as-prepared',
			reference: 'same-paper control',
			baseline_type: 'same_document',
			resolved: true,
			baseline_scope: 'same material'
		},
		structure_support: [
			{
				support_id: 'sf_1',
				support_type: 'phase',
				summary: 'Layered phase retained after annealing.',
				condition: { method: 'XRD' }
			}
		],
		value_provenance: {
			value_origin: 'reported',
			source_value_text: '12',
			source_unit_text: 'mS/cm'
		},
		series_navigation: {
			series_key: 'conductivity:test_temperature_c',
			varying_axis: { axis_name: 'test_temperature_c', axis_unit: 'C' },
			siblings: []
		}
	};
}

function evidence() {
	return {
		evidence_id: 'ev_1',
		document_id: documentId,
		collection_id: collectionId,
		claim_text: 'conductivity is reported for oxide cathode.',
		claim_type: 'result',
		evidence_source_type: 'table',
		evidence_anchors: [
			{
				anchor_id: 'anc_1',
				document_id: documentId,
				locator_type: 'section',
				locator_confidence: 'medium',
				source_type: 'table',
				section_id: 'results',
				char_range: null,
				bbox: null,
				page: 3,
				quote: 'Conductivity improved to 12 mS/cm under EIS.',
				deep_link: null,
				block_id: 'results',
				snippet_id: null,
				figure_or_table: 'Table 2',
				quote_span: null,
				anchor_type: 'direct',
				label: 'Table 2'
			}
		],
		material_system: 'oxide cathode',
		condition_context: { process: ['700 C'], baseline: ['as-prepared'], test: ['EIS'] },
		confidence: 0.94,
		traceability_status: 'direct',
		source_document_title: 'Paper A',
		materials: ['oxide cathode'],
		parameters: ['700 C'],
		tags: ['conductivity'],
		comparable: true,
		comparison_status: 'joinable',
		review_status: null,
		extracted_at: now(),
		updated_at: now()
	};
}

function objectives() {
	return {
		collection_id: collectionId,
		state: 'ready',
		readiness: {
			objectives_ready: true,
			frames_ready: true,
			routes_ready: true,
			evidence_units_ready: true,
			logic_chain_ready: true
		},
		objectives: [
			{
				objective_id: objectiveId,
				question: 'How does heat treatment affect LPBF 316L tensile strength?',
				material_scope: ['316L stainless steel'],
				process_axes: ['heat treatment'],
				property_axes: ['yield strength'],
				comparison_intent: 'Compare as-built and heat-treated LPBF 316L.',
				confidence: 0.91,
				state: 'ready',
				paper_frame_count: 1,
				evidence_route_count: 1,
				evidence_unit_count: 2,
				logic_chain_count: 1
			}
		]
	};
}

function objectiveView() {
	const objective = objectives().objectives[0];
	return {
		...objectives(),
		objective,
		objective_context: {
			objective_id: objectiveId,
			question: objective.question,
			material_scope: ['316L stainless steel'],
			variable_process_axes: ['heat treatment'],
			process_context_axes: [],
			target_property_axes: ['yield strength'],
			excluded_property_axes: [],
			routing_hints: [],
			extraction_guidance: {},
			confidence: 0.88
		},
		paper_frames: [
			{
				frame_id: 'opf_1',
				objective_id: objectiveId,
				document_id: documentId,
				title: 'LPBF 316L heat treatment study',
				source_filename: 'paper-a.txt',
				relevance: 'high',
				paper_role: 'primary_experiment',
				background: 'Reports tensile testing of as-built and heat-treated LPBF 316L.',
				material_match: ['316L stainless steel'],
				changed_variables: ['heat treatment'],
				measured_property_scope: ['yield strength'],
				test_environment_scope: [],
				relevant_sections: ['Results'],
				relevant_tables: ['table-2'],
				excluded_tables: []
			}
		],
		evidence_routes: [],
		evidence_units: [
			{
				evidence_unit_id: 'unit_measure',
				objective_id: objectiveId,
				document_id: documentId,
				unit_kind: 'measurement',
				property_normalized: 'yield strength',
				material_system: {},
				sample_context: { sample: 'HT-SLM' },
				process_context: { heat_treatment: 'annealed' },
				resolved_condition: {},
				test_condition: { method: 'tensile test' },
				value_payload: { statement: 'Yield strength reached 560 MPa.' },
				unit: 'MPa',
				source_refs: [],
				evidence_anchor_ids: [],
				resolution_status: 'resolved',
				confidence: 0.92
			}
		],
		logic_chain: {
			logic_chain_id: 'chain_1',
			objective_id: objectiveId,
			chain_scope: 'objective',
			question: objective.question,
			evidence_unit_ids: ['unit_measure'],
			summary: 'Heat-treated LPBF 316L is supported by tensile evidence.',
			chain_payload: {},
			confidence: 0.83
		}
	};
}

function graph() {
	return {
		collection_id: collectionId,
		nodes: [
			{ id: `doc:${documentId}`, label: 'Paper A', type: 'document', degree: 2 },
			{ id: 'mat:oxide cathode', label: 'oxide cathode', type: 'material', degree: 2 }
		],
		edges: [
			{
				id: 'edge_1',
				source: `doc:${documentId}`,
				target: 'mat:oxide cathode',
				weight: 0.9,
				edge_description: 'overview_document_material'
			}
		],
		truncated: false
	};
}

function goalSession() {
	return {
		session_id: sessionId,
		user_id: 'user_1',
		collection_id: collectionId,
		focused_material_id: null,
		focused_paper_id: null,
		goal_text: null,
		goal_brief_json: {},
		answer_mode: 'hybrid',
		rolling_summary: '',
		last_evidence_ids: [],
		last_material_ids: [],
		last_paper_ids: [],
		collection_data_version: null,
		created_at: now(),
		updated_at: now()
	};
}
