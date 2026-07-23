import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_upload';

type UploadedFile = {
	file_id: string;
	collection_id: string;
	original_filename: string;
	stored_filename: string;
	stored_path: string;
	media_type: string;
	status: string;
	size_bytes: number;
	created_at: string;
};

type BuildTask = {
	task_id: string;
	collection_id: string;
	task_type: string;
	status: 'queued' | 'running' | 'completed' | 'partial_success' | 'failed';
	current_stage: string;
	progress_percent: number;
	output_path: string | null;
	errors: string[];
	warnings: string[];
	created_at: string;
	updated_at: string;
	started_at: string | null;
	finished_at: string | null;
};

function json(body: unknown, status = 200) {
	return {
		status,
		contentType: 'application/json',
		body: JSON.stringify(body)
	};
}

function collectionPayload(fileCount: number) {
	return {
		collection_id: collectionId,
		id: collectionId,
		name: 'LPBF upload workflow',
		description: 'Upload flow screenshot fixture',
		status: fileCount > 0 ? 'uploaded' : 'created',
		paper_count: fileCount,
		updated_at: '2026-05-14T00:00:00Z',
		created_at: '2026-05-14T00:00:00Z'
	};
}

function taskPayload(status: BuildTask['status'], progressPercent: number): BuildTask {
	return {
		task_id: 'task_upload',
		collection_id: collectionId,
		task_type: 'build_collection',
		status,
		current_stage:
			status === 'queued'
				? 'files_registered'
				: status === 'completed'
					? 'artifacts_ready'
					: 'paper_facts_started',
		progress_percent: progressPercent,
		output_path: null,
		errors: [],
		warnings: [],
		created_at: '2026-05-14T00:00:00Z',
		updated_at: '2026-05-14T00:00:03Z',
		started_at: status === 'queued' ? null : '2026-05-14T00:00:02Z',
		finished_at: status === 'completed' ? '2026-05-14T00:00:08Z' : null
	};
}

function workspacePayload(uploadedFiles: UploadedFile[], activeTask: BuildTask | null) {
	const fileCount = uploadedFiles.length;
	const processing = Boolean(activeTask && activeTask.status !== 'completed');
	const ready = activeTask?.status === 'completed';
	return {
		collection: {
			...collectionPayload(fileCount),
			status: ready ? 'ready' : processing ? 'processing' : collectionPayload(fileCount).status
		},
		file_count: fileCount,
		status_summary: ready ? 'ready' : processing ? 'processing' : fileCount > 0 ? 'ready_to_process' : 'empty',
		workflow: {
			documents: ready ? 'ready' : processing ? 'processing' : 'not_started',
			results: ready ? 'ready' : processing ? 'processing' : 'not_started',
			evidence: ready ? 'ready' : processing ? 'processing' : 'not_started',
			comparisons: ready ? 'ready' : processing ? 'processing' : 'not_started'
		},
		document_summary: {
			total_documents: fileCount,
			doc_type_counts: { experimental: 0, review: 0, mixed: 0, uncertain: fileCount },
			warnings: []
		},
		warnings: [],
		artifacts: {
			documents_ready: ready,
			document_profiles_ready: ready,
			evidence_cards_ready: ready,
			comparable_results_ready: ready,
			collection_comparable_results_ready: ready,
			comparison_rows_ready: ready,
			graph_ready: false,
			graph_stale: false,
			updated_at: '2026-05-14T00:00:00Z'
		},
		latest_task: activeTask,
		recent_tasks: activeTask ? [activeTask] : [],
		capabilities: {
			can_view_documents: ready,
			can_view_results: ready,
			can_view_evidence: ready,
			can_view_comparisons: ready,
			can_view_graph: false,
			can_download_graphml: false
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

function researchViewPayload(uploadedFiles: UploadedFile[]) {
	return {
		collection_id: collectionId,
		state: 'ready',
		overview: {
			document_count: uploadedFiles.length,
			sample_count: 1,
			measurement_count: 1,
			evidence_count: 1,
			material_systems: ['316L stainless steel'],
			process_families: ['LPBF'],
			variable_axes: ['heat treatment'],
			measured_properties: ['yield strength'],
			coverage_quality: 'ready'
		},
		materials: [],
		paper_coverage: [],
		comparable_groups: [],
		cross_paper_matrices: [],
		trend_series: [],
		evidence_links: {},
		debug_links: {},
		warnings: []
	};
}

async function mockUploadApis(page: Page) {
	const uploadedFiles: UploadedFile[] = [];
	let activeTask: BuildTask | null = null;
	let taskPollCount = 0;

	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;

		if (!path.startsWith('/api/v1/')) {
			return route.continue();
		}
		if (path === '/api/v1/auth/me') {
			return route.fulfill(
				json({ user: { user_id: 'user_1', email: 'reader@example.com', display_name: 'Reader' } })
			);
		}

		if (path === '/api/v1/collections' && route.request().method() === 'GET') {
			return route.fulfill(json({ items: [] }));
		}
		if (path === '/api/v1/collections' && route.request().method() === 'POST') {
			return route.fulfill(json(collectionPayload(uploadedFiles.length), 201));
		}
		if (path === `/api/v1/collections/${collectionId}`) {
			return route.fulfill(json(collectionPayload(uploadedFiles.length)));
		}
		if (path === `/api/v1/collections/${collectionId}/workspace`) {
			return route.fulfill(json(workspacePayload(uploadedFiles, activeTask)));
		}
		if (path === `/api/v1/collections/${collectionId}/files` && route.request().method() === 'GET') {
			return route.fulfill(json({ count: uploadedFiles.length, items: uploadedFiles }));
		}
		if (path === `/api/v1/collections/${collectionId}/files` && route.request().method() === 'POST') {
			const nextFile: UploadedFile = {
				file_id: `file_${uploadedFiles.length + 1}`,
				collection_id: collectionId,
				original_filename: 'lpbf-316l-study.pdf',
				stored_filename: 'lpbf-316l-study.pdf',
				stored_path: `/tmp/${collectionId}/lpbf-316l-study.pdf`,
				media_type: 'application/pdf',
				status: 'uploaded',
				size_bytes: 2048,
				created_at: '2026-05-14T00:00:00Z'
			};
			uploadedFiles.push(nextFile);
			return route.fulfill(json(nextFile, 201));
		}
		if (
			path === `/api/v1/collections/${collectionId}/tasks/build` &&
			route.request().method() === 'POST'
		) {
			activeTask = taskPayload('queued', 8);
			return route.fulfill(json(activeTask, 201));
		}
		if (path === '/api/v1/tasks/task_upload') {
			taskPollCount += 1;
			activeTask = taskPollCount >= 2 ? taskPayload('completed', 100) : taskPayload('running', 42);
			return route.fulfill(json(activeTask));
		}
		if (path === `/api/v1/collections/${collectionId}/research-view`) {
			if (activeTask?.status === 'completed') {
				return route.fulfill(json(researchViewPayload(uploadedFiles)));
			}
			return route.fulfill(json({ detail: 'research view not generated yet' }, 404));
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

test('collection upload flow exposes the next usable workspace state', async ({ page }, testInfo) => {
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await mockUploadApis(page);

	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto('/');
	await page.getByRole('button', { name: 'Create collection' }).click();
	await expect(page.getByRole('dialog')).toBeVisible();
	await page.getByLabel('Collection name').fill('LPBF upload workflow');
	await page.getByLabel('Description').fill('Upload flow screenshot fixture');
	await page.getByRole('button', { name: 'Create', exact: true }).click();

	await expect(page).toHaveURL(`/collections/${collectionId}`);
	await expect(page.getByRole('heading', { name: 'This collection has no documents yet' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Add papers to this collection' })).toBeVisible();
	await expectNoHorizontalOverflow(page);
	await page.screenshot({
		path: testInfo.outputPath('collection-upload-empty-desktop.png'),
		fullPage: true
	});

	await page.locator('input[type="file"]').setInputFiles({
		name: 'lpbf-316l-study.pdf',
		mimeType: 'application/pdf',
		buffer: Buffer.from('%PDF-1.4\nfixture\n%%EOF')
	});
	await expect(page.getByText('Selected 1 file(s).')).toBeVisible();
	await page.screenshot({
		path: testInfo.outputPath('collection-upload-selected-desktop.png'),
		fullPage: true
	});

	await page.locator('#upload').getByRole('button', { name: 'Upload' }).click();
	await expect(page.getByText('Upload complete', { exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Collection is waiting for processing' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Start processing' }).first()).toBeEnabled();
	await expect(page.getByText('1 document(s)').first()).toBeVisible();
	await expect(page.getByText('1 document(s) uploaded')).toBeVisible();
	await expect(page.getByText('lpbf-316l-study.pdf')).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Processing needed' })).toBeVisible();
	await expectNoHorizontalOverflow(page);
	await page.screenshot({
		path: testInfo.outputPath('collection-upload-ready-to-process-desktop.png'),
		fullPage: true
	});

	await page.getByRole('button', { name: 'Start processing' }).first().click();
	await expect(page.getByText('Processing started')).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Collection is processing' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Processing in progress' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Enter comparison' })).toHaveCount(0);
	await expect(page.locator('.collection-meta-row').getByText('Processing')).toBeVisible();
	await expect(page.getByText('Estimated progress')).toBeVisible();
	await expect(page.getByText('8%')).toBeVisible();
	await expect(page.locator('#upload').getByRole('button', { name: 'Upload' })).toBeDisabled();
	await expect(page.locator('#upload').getByRole('button', { name: 'Start processing' })).toBeDisabled();
	await expect(page.locator('#upload .dropzone')).toHaveAttribute('aria-disabled', 'true');
	await page.waitForTimeout(2600);
	await expect(page.getByText('42%')).toBeVisible();
	await page.screenshot({
		path: testInfo.outputPath('collection-upload-processing-desktop.png'),
		fullPage: true
	});

	await page.waitForTimeout(2600);
	await expect(page.getByText('Processing complete')).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Collection is ready' })).toBeVisible();
	await expect(page.locator('.collection-meta-row').getByText('Complete')).toBeVisible();
	await expect(page.getByRole('link', { name: 'Enter objectives' }).first()).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Trust reminder' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Research overview' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Add papers to this collection' })).toHaveCount(0);
	await expect(page.locator('.check-list li.complete').filter({ hasText: 'Document parsing complete' })).toBeVisible();
	await expect(page.locator('.check-list li.complete').filter({ hasText: 'Evidence extraction complete' })).toBeVisible();
	await expect(page.locator('.check-list li.complete').filter({ hasText: 'Comparison view available' })).toBeVisible();
	await expect(page.getByText('100%')).toBeVisible();
	await expectNoHorizontalOverflow(page);
	await page.screenshot({
		path: testInfo.outputPath('collection-upload-ready-desktop.png'),
		fullPage: true
	});

	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(`/collections/${collectionId}`);
	await expect(page.getByRole('heading', { name: 'Collection is ready' })).toBeInViewport();
	await expect(page.getByRole('link', { name: 'Enter objectives' }).first()).toBeVisible();
	await expectNoHorizontalOverflow(page);
	await page.screenshot({
		path: testInfo.outputPath('collection-upload-mobile.png'),
		fullPage: true
	});
});
