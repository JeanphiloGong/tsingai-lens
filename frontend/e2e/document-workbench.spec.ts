import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_123';
const documentId = 'doc_1';

function json(body: unknown, status = 200) {
	return { status, contentType: 'application/json', body: JSON.stringify(body) };
}

async function mockPaperReaderApis(page: Page, sourceReady = true) {
	await page.route('**/*', async (route) => {
		const path = new URL(route.request().url()).pathname;
		if (!path.startsWith('/api/v1/')) return route.continue();
		if (path === '/api/v1/auth/me') {
			return route.fulfill(
				json({ user: { user_id: 'user_1', email: 'reader@example.com', display_name: 'Reader' } })
			);
		}
		if (path === `/api/v1/collections/${collectionId}`) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					name: 'LPBF source review',
					status: 'ready',
					documents: [{ document_id: documentId, status: sourceReady ? 'ready' : 'stored' }]
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/content`) {
			if (!sourceReady) return route.fulfill(json({ detail: 'source unavailable' }, 404));
			return route.fulfill(
				json({
					collection_id: collectionId,
					document_id: documentId,
					title: 'Paper A',
					source_filename: 'paper-a.pdf',
					content_text: 'Methods text. Results text.',
					blocks: [
						{
							block_id: 'methods',
							block_type: 'paragraph',
							heading_path: 'Methods',
							heading_level: 2,
							order: 1,
							text: 'The sample was annealed at 700 C.',
							text_unit_ids: ['tu-1'],
							page: 2
						},
						{
							block_id: 'results',
							block_type: 'paragraph',
							heading_path: 'Results',
							heading_level: 2,
							order: 2,
							text: 'Conductivity improved to 12 mS/cm under EIS.',
							text_unit_ids: ['tu-2'],
							page: 3
						}
					],
					warnings: []
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/markdown`) {
			if (!sourceReady) return route.fulfill(json({ detail: 'markdown unavailable' }, 404));
			return route.fulfill(
				json({
					collection_id: collectionId,
					document_id: documentId,
					title: 'Paper A',
					source_filename: 'paper-a.pdf',
					parser: 'docling',
					markdown:
						'# Paper A\n\n## Methods\n\nThe sample was annealed at 700 C.\n\n## Results\n\nConductivity improved to 12 mS/cm under EIS.',
					source_map: [
						{
							markdown_anchor: 'block-results',
							artifact_type: 'block',
							artifact_id: 'results',
							block_id: 'results',
							page: 3,
							heading_path: 'Results',
							text_unit_ids: ['tu-2']
						}
					],
					warnings: []
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/source`) {
			return route.fulfill(json({ detail: 'PDF unavailable in fixture' }, 404));
		}
		return route.fulfill(json({ detail: `unhandled test route: ${path}` }, 404));
	});
}

async function expectNoHorizontalOverflow(page: Page) {
	const overflows = await page.evaluate(
		() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) > innerWidth + 1
	);
	expect(overflows).toBe(false);
}

test('paper reader shows parsed Source and exact Finding source selection', async ({ page }) => {
	await mockPaperReaderApis(page);
	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto(
		`/collections/${collectionId}/documents/${documentId}?view=parsed-paper&source_ref=results&quote=Conductivity+improved+to+12+mS%2Fcm+under+EIS.&return_to=%2Fcollections%2F${collectionId}%2Fobjectives%2Fobj_1`
	);

	await expect(page.getByText('Paper A').first()).toBeVisible();
	await expect(page.getByRole('tab', { name: 'Parsed Paper' })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await expect(page.getByRole('heading', { name: 'Results' })).toBeVisible();
	await expect(page.getByText('Conductivity improved to 12 mS/cm under EIS.')).toBeVisible();
	await expect(page.getByRole('link', { name: 'Documents' }).last()).toHaveAttribute(
		'href',
		`/collections/${collectionId}/objectives/obj_1`
	);
	await expectNoHorizontalOverflow(page);

	await page.setViewportSize({ width: 390, height: 844 });
	await expectNoHorizontalOverflow(page);
});

test('paper reader reports when neither Source projection is available', async ({ page }) => {
	await mockPaperReaderApis(page, false);
	await page.goto(`/collections/${collectionId}/documents/${documentId}`);

	await expect(page.getByRole('heading', { name: 'Source view is unavailable' })).toBeVisible();
});
