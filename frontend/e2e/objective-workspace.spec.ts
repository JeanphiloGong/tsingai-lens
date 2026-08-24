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
	variables: ['heat treatment'],
	outcomes: ['yield strength'],
	mechanisms: ['precipitate evolution'],
	constraints: ['LPBF 316L'],
	requested_comparator: 'Compare as-built and heat-treated LPBF 316L.',
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
	statement: 'Annealing was associated with higher tensile strength.',
	factors: ['heat treatment'],
	outcome: 'tensile strength',
	direction: 'increase',
	assertion_strength: 'associative',
	attribution_scope: 'isolated_effect',
	synthesis_status: 'insufficient_confirmation',
	certainty: 0.88,
	display_rank: 0,
	mechanisms: [
		{
			source_term: 'annealing',
			relation_type: 'associated_with',
			target_term: 'tensile strength',
			direction: 'increase',
			assertion_strength: 'associative',
			supporting_evidence_ids: ['evidence-mechanism']
		}
	],
	scientific_context: {
		material: [{ name: 'alloy', value: '316L', unit: null }],
		sample: [{ name: 'state', value: 'annealed', unit: null }],
		process: [{ name: 'process', value: 'LPBF', unit: null }],
		test: [{ name: 'method', value: 'tensile test', unit: null }]
	},
	limitations: ['Single paper only.'],
	paper_contributions: [
		{
			document_id: documentId,
			analysis_status: 'analyzed',
			supporting_evidence_ids: ['evidence-1', 'evidence-2', 'evidence-3'],
			contradicting_evidence_ids: [],
			context_evidence_ids: ['evidence-mechanism'],
			condition_boundary_evidence_ids: []
		},
		{
			document_id: 'doc_without_evidence',
			analysis_status: 'failed',
			supporting_evidence_ids: [],
			contradicting_evidence_ids: [],
			context_evidence_ids: [],
			condition_boundary_evidence_ids: []
		}
	]
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
	changed_variables: [
		{
			name: 'heat treatment',
			baseline_value: 'as-built',
			target_value: 'annealed',
			unit: null
		}
	],
	comparison: {
		baseline_label: 'as-built',
		target_label: 'annealed',
		axis_names: ['heat treatment'],
		comparable: true,
		incomparability_reasons: []
	},
	reported_result: {
		outcome: 'tensile strength',
		value: 620,
		baseline_value: 580,
		target_value: 620,
		unit: 'MPa',
		direction: 'increase',
		result_text: 'After annealing, tensile strength increased to 620 MPa.'
	},
	attribution_scope: 'isolated_effect',
	scientific_context: {
		material: [{ name: 'alloy', value: '316L', unit: null }],
		sample: [{ name: 'state', value: 'annealed', unit: null }],
		process: [{ name: 'process', value: 'LPBF', unit: null }],
		test: [{ name: 'method', value: 'tensile test', unit: null }]
	},
	anchor_ids: [],
	resolution_status: 'resolved',
	failure_reason: null,
	confidence: 0.92
};

const additionalTableEvidence = [
	{
		evidence_id: 'evidence-2',
		target_label: 'solution-treated',
		target_value: 600,
		source_excerpt: 'After solution treatment, tensile strength was 600 MPa.'
	},
	{
		evidence_id: 'evidence-3',
		target_label: 'aged',
		target_value: 640,
		source_excerpt: 'After aging, tensile strength increased to 640 MPa.'
	}
].map((item) => ({
	...evidence,
	evidence_id: item.evidence_id,
	source_excerpt: item.source_excerpt,
	changed_variables: [
		{
			name: 'heat treatment',
			baseline_value: 'as-built',
			target_value: item.target_label,
			unit: null
		}
	],
	comparison: {
		baseline_label: 'as-built',
		target_label: item.target_label,
		axis_names: ['heat treatment'],
		comparable: true,
		incomparability_reasons: []
	},
	reported_result: {
		outcome: 'tensile strength',
		value: item.target_value,
		baseline_value: 580,
		target_value: item.target_value,
		unit: 'MPa',
		direction: 'increase',
		result_text: item.source_excerpt
	}
}));

const mechanismEvidence = {
	...evidence,
	evidence_id: 'evidence-mechanism',
	source_kind: 'text_window',
	source_ref: 'block-8',
	source_excerpt: 'Precipitate evolution was associated with increased tensile strength.',
	page_numbers: [8],
	evidence_role: 'mechanism_context',
	selection_reason: 'Mechanism context.',
	changed_variables: [],
	comparison: null,
	reported_result: null,
	attribution_scope: 'not_attributable'
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
				json({
					collection_id: collectionId,
					id: collectionId,
					name: 'LPBF 316L objective set',
					status: 'ready',
					paper_count: 1
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/workspace`) {
			return route.fulfill(
				json({
					collection: {
						collection_id: collectionId,
						id: collectionId,
						name: 'LPBF 316L objective set',
						status: 'ready'
					},
					file_count: 1,
					status_summary: 'ready',
					workflow: {
						documents: { status: 'ready', detail: 'Document profiles are available.' },
						objectives: { status: 'ready', detail: 'Objective discovery is complete.' }
					},
					document_summary: {
						total_documents: 1,
						by_doc_type: { experimental: 1 }
					},
					artifacts: {
						source_documents_ready: true,
						document_profiles_ready: true,
						objective_candidates_ready: true,
						updated_at: '2026-05-14T00:00:00Z'
					},
					latest_task: {
						task_id: 'task-2',
						collection_id: collectionId,
						task_type: 'build',
						status: 'partial_success',
						current_stage: 'artifacts_ready',
						progress_percent: 100,
						errors: ['A later build failed.'],
						warnings: [],
						created_at: null,
						updated_at: null
					},
					recent_tasks: [],
					capabilities: {
						can_view_documents: true,
						can_view_objectives: true,
						can_view_comparisons: true
					},
					links: {
						workspace: `/collections/${collectionId}`,
						documents: `/collections/${collectionId}/documents`,
						objectives: `/collections/${collectionId}/objectives`,
						comparisons: `/collections/${collectionId}/comparisons`
					}
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/documents/profiles`) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					items: [
						{
							document_id: documentId,
							collection_id: collectionId,
							title: 'LPBF 316L tensile study',
							source_filename: 'paper-1.pdf',
							doc_type: 'experimental',
							parsing_warnings: [],
							confidence: 0.95
						}
					],
					total: 1,
					count: 1,
					summary: {
						total_documents: 1,
						doc_type_counts: { experimental: 1 },
						warnings: []
					}
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}/analysis`) {
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
				json({
					collection_id: collectionId,
					objective_id: objectiveId,
					analysis_version: 1,
					items: [finding],
					offset: 0,
					limit: 50,
					total: 1
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}/evidence`) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					objective_id: objectiveId,
					analysis_version: 1,
					finding_id: 'finding-1',
					items: [evidence, ...additionalTableEvidence, mechanismEvidence],
					offset: 0,
					limit: 100,
					total: 4
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/content`) {
			return route.fulfill(json(documentContent()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/markdown`) {
			return route.fulfill(json(documentMarkdown()));
		}
		return route.fulfill(json({ detail: `unhandled test route: ${path}` }, 404));
	});
}

for (const viewport of [
	{ name: 'desktop', width: 1280, height: 720 },
	{ name: 'mobile', width: 390, height: 844 }
]) {
	test(`objective workspace keeps published Findings readable after a failed retry (${viewport.name})`, async ({
		page
	}) => {
		await page.setViewportSize({ width: viewport.width, height: viewport.height });
		await mockApis(page);
		await page.goto(`/collections/${collectionId}/objectives/${objectiveId}`);

		await expect(page.getByText('Evidence extraction failed.')).toBeVisible();
		await expect(page.getByText('正在显示已发布的 v1；重试 v2 失败。')).toBeVisible();
		await expect(page.getByText(finding.statement).first()).toBeVisible();
		await expect(page.getByText('相关联', { exact: true })).toBeVisible();
		await expect(page.getByRole('heading', { name: '证据对比' })).toBeVisible();
		await expect(
			page.getByRole('cell', { name: 'tensile strength: 580 MPa → 620 MPa' })
		).toBeVisible();
		await expect(page.getByRole('link', { name: 'LPBF 316L tensile study · p.7' })).toBeVisible();
		await expect(page.getByRole('link', { name: 'LPBF 316L tensile study · p.8' })).toBeVisible();
		await expect(
			page.getByText('另有 1 篇文献未形成可审计 Evidence：分析失败 1 篇。')
		).toBeVisible();
		await expect(page.getByText('文献 2', { exact: true })).toHaveCount(0);
		await expect(page.getByText('tensile strength', { exact: true }).first()).toBeVisible();
		await expect(page.getByRole('button', { name: '反馈' })).toBeVisible();
		await expect(page.getByText('Single paper only.')).toBeVisible();
		const evidenceScope = page.getByRole('group', { name: '证据范围' });
		await expect(evidenceScope).toContainText('1篇直接文献');
		await expect(evidenceScope).toContainText('2个原文来源');
		await expect(evidenceScope).toContainText('3个结果比较');
		const tableSource = page.getByRole('group', { name: '表格来源 · p.7' });
		await expect(tableSource).not.toHaveAttribute('open');
		await tableSource.getByText('表格来源 · p.7', { exact: true }).click();
		await expect(tableSource).toHaveAttribute('open');
		await expect(tableSource.getByRole('group', { name: '共享参照' })).toContainText('as-built');
		await expect(tableSource.getByRole('group', { name: '共享参照' })).toContainText('580 MPa');
		const sourceMatrix = tableSource.getByRole('table', { name: '共享参照比较' });
		await expect(sourceMatrix.getByRole('row')).toHaveCount(4);
		const annealedRow = sourceMatrix.locator('tbody tr').filter({ hasText: /^annealed/ });
		await expect(annealedRow).toContainText('620 MPa');
		await expect(annealedRow).toContainText('+40 MPa');
		await expect(annealedRow.locator('blockquote')).not.toBeVisible();
		await annealedRow.getByText('查看摘录', { exact: true }).click();
		await expect(annealedRow.locator('blockquote')).toHaveText(evidence.source_excerpt);
		const layout = await page.evaluate(() => {
			const list = document
				.querySelector<HTMLElement>('.findings-sidebar')
				?.getBoundingClientRect();
			const detailElement = document.querySelector<HTMLElement>('.finding-workspace');
			const findingElement = document.querySelector<HTMLElement>('.finding-detail');
			const detail = detailElement?.getBoundingClientRect();
			return {
				viewportWidth: window.innerWidth,
				pageFitsViewport: document.documentElement.scrollWidth <= window.innerWidth + 1,
				detailContentFits:
					!!detailElement &&
					!!findingElement &&
					findingElement.scrollWidth <= detailElement.clientWidth + 1,
				list: list && { x: list.x, y: list.y, width: list.width, height: list.height },
				detail: detail && { x: detail.x, y: detail.y, width: detail.width, height: detail.height }
			};
		});
		expect(layout.pageFitsViewport).toBe(true);
		expect(layout.detailContentFits).toBe(true);
		expect(layout.list).toBeTruthy();
		expect(layout.detail).toBeTruthy();
		expect(layout.detail!.x + layout.detail!.width).toBeLessThanOrEqual(layout.viewportWidth + 1);
		if (viewport.name === 'desktop') {
			expect(layout.list!.x + layout.list!.width).toBeLessThanOrEqual(layout.detail!.x);
		} else {
			expect(layout.list!.y + layout.list!.height).toBeLessThanOrEqual(layout.detail!.y);
		}
		const sourceLink = annealedRow.getByRole('link', { name: /打开原文|Open source/ });
		await expect(sourceLink).toHaveAttribute(
			'href',
			`/collections/${collectionId}/documents/${documentId}?view=parsed-paper&evidence_id=evidence-1&source_ref=${tableSourceRef}&quote=After+annealing%2C+tensile+strength+increased+to+620+MPa.&return_to=%2Fcollections%2F${collectionId}%2Fobjectives%2F${objectiveId}%3Ffinding_id%3Dfinding-1&page=7`
		);
		await page.screenshot({
			path: `test-results/objective-finding-workspace-${viewport.name}.png`,
			fullPage: true
		});

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
					const active = document.querySelector<HTMLElement>(
						'[data-testid="markdown-active-source"]'
					);
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
		expect(sourceApiPaths).toContain(
			`/api/v1/collections/${collectionId}/documents/${documentId}/content`
		);
		expect(sourceApiPaths).toContain(
			`/api/v1/collections/${collectionId}/documents/${documentId}/markdown`
		);
	});
}
