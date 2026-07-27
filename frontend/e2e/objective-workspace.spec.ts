import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_123';
const objectiveId = 'obj_1';
const documentId = 'doc_1';
const tableSourceRef = 'tbl_doc_1_3_table_3';

function json(body: unknown, status = 200) {
	return { status, contentType: 'application/json', body: JSON.stringify(body) };
}

const objective = {
	collection_id: collectionId,
	objective_id: objectiveId,
	question: 'How does heat treatment affect LPBF 316L tensile strength?',
	material_scope: ['316L stainless steel'],
	process_axes: ['heat treatment'],
	property_axes: ['yield strength'],
	comparison_intent: 'Compare as-built and heat-treated LPBF 316L.',
	seed_document_ids: [documentId],
	excluded_document_ids: [],
	confidence: 0.91,
	reason: null,
	confirmation_status: 'confirmed',
	active_analysis_version: 2,
	published_analysis_version: 1,
	created_at: '2026-05-14T00:00:00Z',
	updated_at: '2026-05-14T00:00:00Z'
};

function analysis(status: 'succeeded' | 'failed', version: number) {
	return {
		collection_id: collectionId,
		objective_id: objectiveId,
		analysis_version: version,
		source_build_id: 'build-1',
		pipeline_version: 'objective-analysis.v2',
		model_name: 'model-1',
		prompt_versions: {},
		status,
		phase: status,
		processed_document_count: status === 'succeeded' ? 1 : 0,
		total_document_count: 1,
		current_document_id: null,
		progress_message: null,
		error_code: status === 'failed' ? 'provider_error' : null,
		error_message: status === 'failed' ? 'Evidence extraction failed.' : null,
		created_at: null,
		started_at: null,
		completed_at: null
	};
}

const finding = {
	collection_id: collectionId,
	objective_id: objectiveId,
	analysis_version: 1,
	finding_id: 'finding-1',
	finding_level: 'paper',
	statement: 'Annealing was associated with higher tensile strength.',
	variables: ['heat treatment'],
	mediators: [],
	outcomes: ['tensile strength'],
	direction: 'increase',
	scope_summary: 'LPBF 316L in the reported tensile-test condition.',
	evidence_strength: 'moderate',
	generalization_status: 'paper_level_only',
	paper_count: 1,
	confidence: 0.88,
	display_rank: 0,
	relations: [
		{
			relation_order: 0,
			source_term: 'annealing',
			relation_type: 'associated_with',
			target_term: 'tensile strength',
			direction: 'increase',
			assertion_strength: 'associative',
			supporting_evidence_ids: ['evidence-1']
		}
	],
	context: {
		material_system: { name: '316L' },
		process_conditions: [{ state: 'annealed' }],
		sample_state: {},
		test_conditions: [{ method: 'tensile test' }],
		comparison_baseline: { state: 'as-built' },
		limitations: ['Single paper only.'],
		supporting_evidence_ids: ['evidence-1']
	},
	derivation: {
		synthesis_mode: 'paper',
		comparison_status: 'insufficient_confirmation',
		contributing_document_ids: [documentId],
		supporting_evidence_ids: ['evidence-1'],
		contradicting_evidence_ids: [],
		rationale: 'One direct result supports this paper-level Finding.'
	}
};

const evidence = {
	collection_id: collectionId,
	objective_id: objectiveId,
	analysis_version: 1,
	evidence_id: 'evidence-1',
	document_id: documentId,
	source_kind: 'table',
	source_ref: tableSourceRef,
	source_excerpt: 'After annealing, tensile strength increased to 620 MPa.',
	page_numbers: [7],
	related_source_refs: [],
	evidence_role: 'direct_result',
	selection_status: 'extracted',
	selection_reason: 'Direct result.',
	evidence_kind: 'measurement',
	property_normalized: 'tensile strength',
	material_system: { name: '316L' },
	sample_context: {},
	process_context: {},
	test_condition: {},
	resolved_condition: {},
	value_payload: { value: 620 },
	unit: 'MPa',
	baseline_context: {},
	interpretation: null,
	join_keys: {},
	anchor_ids: [],
	resolution_status: 'resolved',
	failure_reason: null,
	confidence: 0.92
};

function documentContent() {
	return {
		collection_id: collectionId,
		document_id: documentId,
		title: 'LPBF 316L tensile study',
		source_filename: 'paper-1.pdf',
		content_text: 'After annealing, tensile strength increased to 620 MPa.',
		blocks: [],
		warnings: []
	};
}

function documentMarkdown() {
	const filler = Array.from(
		{ length: 48 },
		(_, index) =>
			`Source paragraph ${index + 1}. This bounded paragraph keeps the third table below the initial reader viewport.`
	).join('\n\n');
	return {
		collection_id: collectionId,
		document_id: documentId,
		title: 'LPBF 316L tensile study',
		source_filename: 'paper-1.pdf',
		parser: 'docling',
		markdown: [
			'# LPBF 316L tensile study',
			'## Processing parameters',
			'| Sample | Temperature |\n| --- | --- |\n| A | 450 C |',
			filler,
			'## Baseline properties',
			'| Sample | Tensile strength |\n| --- | --- |\n| As-built | 580 MPa |',
			'## Direct result',
			'| Condition | Tensile strength |\n| --- | --- |\n| Annealed | 620 MPa |',
			'## Supporting result',
			'| Condition | Elongation |\n| --- | --- |\n| Annealed | 28% |'
		].join('\n\n'),
		source_map: [1, 2, 3, 4].map((tableNumber) => ({
			markdown_anchor: `table-tbl-doc-1-${tableNumber}-table-${tableNumber}`,
			artifact_type: 'table',
			artifact_id: `tbl_doc_1_${tableNumber}_table_${tableNumber}`,
			block_id: null,
			table_id: `tbl_doc_1_${tableNumber}_table_${tableNumber}`,
			figure_id: null,
			block_type: null,
			page: tableNumber + 4,
			heading_path: tableNumber === 3 ? 'Direct result' : `Table ${tableNumber}`,
			text_unit_ids: []
		})),
		warnings: []
	};
}

function documentResearchView() {
	return {
		collection_id: collectionId,
		document_id: documentId,
		paper_title: 'LPBF 316L tensile study',
		state: 'empty',
		overview: {},
		materials: [],
		sample_matrix: { rows: [], columns: [] },
		condition_series: [],
		warnings: []
	};
}

async function mockApis(page: Page) {
	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;
		if (!path.startsWith('/api/v1/')) return route.continue();
		if (path === '/api/v1/auth/me') {
			return route.fulfill(
				json({ user: { user_id: 'user_1', email: 'reader@example.com', display_name: 'Reader' } })
			);
		}
		if (path === '/api/v1/collections') return route.fulfill(json({ items: [] }));
		if (path === `/api/v1/collections/${collectionId}`) {
			return route.fulfill(
				json({ collection_id: collectionId, id: collectionId, name: 'LPBF 316L objective set', status: 'failed', paper_count: 1 })
			);
		}
		if (path === `/api/v1/collections/${collectionId}/workspace`) {
			return route.fulfill(
				json({
					collection: { collection_id: collectionId, id: collectionId, name: 'LPBF 316L objective set', status: 'partial_success' },
					file_count: 1,
					status_summary: 'partial_ready',
					workflow: { documents: 'ready', results: 'not_started', evidence: 'not_started', comparisons: 'not_started' },
					document_summary: { total_documents: 1, doc_type_counts: { experimental: 1 }, warnings: [] },
					artifacts: { documents_ready: true, document_profiles_ready: true, evidence_cards_ready: false, comparable_results_ready: false, comparison_rows_ready: false, graph_ready: false },
					latest_task: { task_id: 'task-2', collection_id: collectionId, task_type: 'build', status: 'partial_success', current_stage: 'artifacts_ready', progress_percent: 100, errors: ['A later build failed.'], warnings: [], created_at: null, updated_at: null },
					recent_tasks: [],
					capabilities: {},
					links: {}
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}`) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					objective,
					active_analysis: analysis('failed', 2),
					published_analysis: analysis('succeeded', 1),
					warnings: []
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}/findings`) {
			return route.fulfill(
				json({ collection_id: collectionId, objective_id: objectiveId, analysis_version: 1, items: [finding], offset: 0, limit: 50, total: 1 })
			);
		}
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}/evidence`) {
			return route.fulfill(
				json({ collection_id: collectionId, objective_id: objectiveId, analysis_version: 1, finding_id: 'finding-1', items: [evidence], offset: 0, limit: 100, total: 1 })
			);
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/content`) {
			return route.fulfill(json(documentContent()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/markdown`) {
			return route.fulfill(json(documentMarkdown()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/research-view`) {
			return route.fulfill(json(documentResearchView()));
		}
		return route.fulfill(json({ detail: `unhandled test route: ${path}` }, 404));
	});
}

test('objective workspace keeps published Findings readable after a failed retry', async ({ page }) => {
	await mockApis(page);
	await page.goto(`/collections/${collectionId}/objectives/${objectiveId}`);

	await expect(page.getByText('Evidence extraction failed.')).toBeVisible();
	await expect(page.getByText(finding.statement).first()).toBeVisible();
	await expect(page.getByText(evidence.source_excerpt)).toBeVisible();
	await expect(page.getByText('associated_with')).toBeVisible();
	await expect(page.getByText('Single paper only.')).toBeVisible();
	const sourceLink = page.getByRole('link', { name: /打开原文|Open source/ });
	await expect(sourceLink).toHaveAttribute(
		'href',
		`/collections/${collectionId}/documents/${documentId}?view=parsed-paper&source_ref=${tableSourceRef}&page=7&quote=After+annealing%2C+tensile+strength+increased+to+620+MPa.&return_to=%2Fcollections%2F${collectionId}%2Fobjectives%2F${objectiveId}`
	);
	await page.screenshot({ path: 'test-results/objective-finding-workspace.png', fullPage: true });

	const sourceApiPaths: string[] = [];
	page.on('request', (request) => {
		const path = new URL(request.url()).pathname;
		if (path.includes(`/documents/${documentId}`)) sourceApiPaths.push(path);
	});
	await sourceLink.click();
	await page.waitForURL(`**/documents/${documentId}?view=parsed-paper**`);
	const activeSource = page.getByTestId('markdown-active-source');
	await expect(activeSource).toHaveAttribute('aria-current', 'location');
	await expect(activeSource).toContainText('Annealed');
	await expect(activeSource).toContainText('620 MPa');
	await expect(page.getByTestId('markdown-selected-evidence-quote')).toContainText(
		'After annealing, tensile strength increased to 620 MPa.'
	);
	await expect
		.poll(async () =>
			page.evaluate(() => {
				const body = document.querySelector<HTMLElement>('.markdown-reader__body');
				const active = document.querySelector<HTMLElement>('[data-testid="markdown-active-source"]');
				if (!body || !active) return false;
				const bodyRect = body.getBoundingClientRect();
				const activeRect = active.getBoundingClientRect();
				return (
					body.scrollTop > 0 &&
					activeRect.bottom > bodyRect.top &&
					activeRect.top < bodyRect.bottom
				);
			})
		)
		.toBe(true);
	expect(sourceApiPaths).not.toContain(`/api/v1/collections/${collectionId}/results`);
	expect(sourceApiPaths).not.toContain(
		`/api/v1/collections/${collectionId}/documents/${documentId}/comparison-semantics`
	);
});
