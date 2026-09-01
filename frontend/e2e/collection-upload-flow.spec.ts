import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_upload';
const readyDocumentIds = ['doc_ready_1', 'doc_ready_2'];

function json(body: unknown, status = 200) {
	return {
		status,
		contentType: 'application/json',
		body: JSON.stringify(body)
	};
}

function document(documentId: string, status: string, filename: string) {
	const ready = status === 'ready';
	return {
		document_id: documentId,
		original_filename: filename,
		stored_filename: filename,
		storage_key: `${collectionId}/input/${filename}`,
		sha256: documentId.padEnd(64, 'a').slice(0, 64),
		media_type: 'application/pdf',
		status,
		size_bytes: 2048,
		created_at: '2026-08-27T00:00:00Z',
		updated_at: '2026-08-27T00:01:00Z',
		parser_version: ready ? 'source-runtime.v1' : null,
		document_analysis_version: ready ? 'paper-map.v1' : null,
		source_fingerprint: ready ? `source-${documentId}` : null,
		profile_fingerprint: ready ? `profile-${documentId}` : null,
		preparation_fingerprint: ready ? `fingerprint-${documentId}` : null
	};
}

function preparationTask(documentId: string, status: 'queued' | 'running' | 'failed') {
	return {
		task_id: `task_${documentId}`,
		collection_id: collectionId,
		document_id: documentId,
		task_type: 'document_preparation',
		mode: 'standard',
		input_fingerprint: `input-${documentId}`,
		status,
		current_stage: status === 'failed' ? 'failed' : 'source_parsing',
		progress_percent: status === 'running' ? 42 : 0,
		progress_detail:
			status === 'running' ? { phase: 'source_parsing', message: 'Parsing this paper.' } : null,
		errors: status === 'failed' ? ['The PDF could not be parsed.'] : [],
		warnings: [],
		created_at: '2026-08-27T00:00:00Z',
		updated_at: '2026-08-27T00:01:00Z',
		started_at: status === 'running' ? '2026-08-27T00:00:01Z' : null,
		finished_at: status === 'failed' ? '2026-08-27T00:01:00Z' : null
	};
}

function discoveryTask(status: 'queued' | 'completed') {
	return {
		task_id: 'task_discovery',
		collection_id: collectionId,
		document_id: null,
		task_type: 'objective_discovery',
		mode: 'standard',
		input_fingerprint: 'discovery-scope',
		status,
		current_stage: status === 'completed' ? 'objectives_ready' : 'queued',
		progress_percent: status === 'completed' ? 100 : 0,
		progress_detail: {
			phase: status === 'completed' ? 'objectives_ready' : 'queued',
			message:
				status === 'completed'
					? 'Candidate research questions are ready for review.'
					: 'Research question formation is queued.'
		},
		errors: [],
		warnings: [],
		created_at: '2026-08-27T00:00:00Z',
		updated_at: '2026-08-27T00:01:00Z',
		started_at: status === 'completed' ? '2026-08-27T00:00:01Z' : null,
		finished_at: status === 'completed' ? '2026-08-27T00:01:00Z' : null
	};
}

async function mockCurrentDocumentApis(page: Page) {
	const documents = [
		document(readyDocumentIds[0], 'ready', 'grain-structure.pdf'),
		document(readyDocumentIds[1], 'ready', 'tensile-strength.pdf'),
		document('doc_processing', 'processing', 'elongation.pdf'),
		document('doc_failed', 'failed', 'damaged-scan.pdf')
	];
	let objectives: Record<string, unknown>[] = [];
	const preparationRequests: string[] = [];
	const discoveryBodies: unknown[] = [];

	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;
		const method = route.request().method();
		if (!path.startsWith('/api/v1/')) return route.continue();

		if (path === '/api/v1/auth/me') {
			return route.fulfill(
				json({ user: { user_id: 'user_1', email: 'reader@example.com', display_name: 'Reader' } })
			);
		}
		if (path === '/api/v1/collections') {
			return route.fulfill(json({ items: [] }));
		}
		if (path === `/api/v1/collections/${collectionId}`) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					id: collectionId,
					name: 'Independent paper preparation',
					description: 'Current document workflow fixture',
					status: 'processing',
					paper_count: documents.length,
					documents
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/documents` && method === 'GET') {
			return route.fulfill(json({ count: documents.length, items: documents }));
		}
		if (path === `/api/v1/collections/${collectionId}/tasks` && method === 'GET') {
			return route.fulfill(
				json({
					collection_id: collectionId,
					count: 2,
					items: [
						preparationTask('doc_processing', 'running'),
						preparationTask('doc_failed', 'failed')
					]
				})
			);
		}
		if (
			path === `/api/v1/collections/${collectionId}/documents/doc_failed/preparation` &&
			method === 'POST'
		) {
			preparationRequests.push(path);
			return route.fulfill(json(preparationTask('doc_failed', 'queued'), 202));
		}
		if (path === '/api/v1/tasks/task_doc_failed' && method === 'GET') {
			return route.fulfill(json(preparationTask('doc_failed', 'failed')));
		}
		if (path === '/api/v1/tasks/task_doc_processing' && method === 'GET') {
			return route.fulfill(json(preparationTask('doc_processing', 'running')));
		}
		if (path === '/api/v1/tasks/task_discovery' && method === 'GET') {
			return route.fulfill(json(discoveryTask('completed')));
		}
		if (path === `/api/v1/collections/${collectionId}/objectives` && method === 'GET') {
			return route.fulfill(json({ collection_id: collectionId, objectives }));
		}
		if (path === `/api/v1/collections/${collectionId}/objective-discovery` && method === 'POST') {
			discoveryBodies.push(route.request().postDataJSON());
			objectives = [
				{
					collection_id: collectionId,
					objective_id: 'obj_energy_grain',
					question: 'How does laser energy input affect grain morphology?',
					material_scope: ['Ti-6Al-4V'],
					variables: ['laser energy input'],
					outcomes: ['grain morphology'],
					seed_document_ids: readyDocumentIds,
					confirmation_status: 'candidate'
				}
			];
			return route.fulfill(json(discoveryTask('queued')));
		}

		return route.fulfill(json({ detail: `unhandled test route: ${method} ${path}` }, 404));
	});

	return { discoveryBodies, preparationRequests };
}

async function expectNoHorizontalOverflow(page: Page) {
	const hasOverflow = await page.evaluate(
		() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) > innerWidth + 1
	);
	expect(hasOverflow).toBe(false);
}

test('ready papers remain usable while other papers process or fail', async ({ page }) => {
	await page.emulateMedia({ reducedMotion: 'reduce' });
	const requests = await mockCurrentDocumentApis(page);
	await page.setViewportSize({ width: 1440, height: 900 });

	await page.goto(`/collections/${collectionId}`);

	await expect(page.getByRole('heading', { name: 'Research overview' })).toBeVisible();
	const uploadButton = page.getByRole('button', { name: 'Upload documents' }).last();
	await expect(uploadButton).toBeEnabled();
	await expect(page.getByText('Parsing this paper.')).toBeVisible();
	await page.getByText('1 paper(s) need attention', { exact: true }).click();
	await expect(page.getByText('The PDF could not be parsed.')).toBeVisible();
	await page.getByRole('button', { name: 'Retry' }).click();
	await expect(page.getByText('1 paper preparation task(s) queued.')).toBeVisible();
	expect(requests.preparationRequests).toEqual([
		`/api/v1/collections/${collectionId}/documents/doc_failed/preparation`
	]);

	const discoveryButton = page.getByRole('button', { name: 'Form research questions from 2' });
	await expect(discoveryButton).toBeEnabled();
	await discoveryButton.click();

	expect(requests.discoveryBodies).toEqual([{ document_ids: readyDocumentIds }]);
	await expect(
		page.getByText('Research question formation completed with 1 candidate(s).')
	).toBeVisible();
	await expect(page.getByRole('link', { name: 'Enter research objectives' })).toBeVisible();
	await expect(uploadButton).toBeEnabled();
	await expectNoHorizontalOverflow(page);

	await page.setViewportSize({ width: 390, height: 844 });
	await expect(uploadButton).toBeVisible();
	await expectNoHorizontalOverflow(page);
});
