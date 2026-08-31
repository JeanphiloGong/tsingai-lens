import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_123';
const documentId = 'doc_1';
const screenshotDir = process.env.SOURCE_AGENT_SCREENSHOT_DIR ?? '';

if (screenshotDir) mkdirSync(screenshotDir, { recursive: true });

function json(body: unknown, status = 200) {
	return { status, contentType: 'application/json', body: JSON.stringify(body) };
}

async function mockPaperReaderApis(
	page: Page,
	sourceReady = true,
	onChatMessage: (payload: Record<string, unknown>) => void = () => {}
) {
	await page.route('**/*', async (route) => {
		const path = new URL(route.request().url()).pathname;
		if (!path.startsWith('/api/v1/')) return route.continue();
		if (path === '/api/v1/auth/me') {
			return route.fulfill(
				json({ user: { user_id: 'user_1', email: 'reader@example.com', display_name: 'Reader' } })
			);
		}
		if (path === '/api/v1/collections') {
			return route.fulfill(
				json({
					items: [
						{
							collection_id: collectionId,
							name: 'LPBF source review',
							status: 'ready',
							documents: [{ document_id: documentId, status: 'ready' }]
						}
					]
				})
			);
		}
		if (path === '/api/v1/chat-sessions' && route.request().method() === 'POST') {
			return route.fulfill(
				json(
					{
						session_id: 'chat_source',
						user_id: 'user_1',
						collection_id: collectionId,
						created_at: '2026-08-31T00:00:00+00:00',
						updated_at: '2026-08-31T00:00:00+00:00'
					},
					201
				)
			);
		}
		if (
			path === '/api/v1/chat-sessions/chat_source/messages' &&
			route.request().method() === 'POST'
		) {
			const payload = route.request().postDataJSON() as Record<string, unknown>;
			onChatMessage(payload);
			const sourceContexts = Array.isArray(payload.source_contexts) ? payload.source_contexts : [];
			const turn = {
				status: 'completed',
				messages: [
					{
						message_id: 'msg_source_user',
						session_id: 'chat_source',
						role: 'user',
						content: payload.message,
						created_at: '2026-08-31T00:00:01+00:00',
						tool_call_id: null,
						tool_name: null,
						tool_arguments: null,
						tool_result: null,
						source_contexts: sourceContexts
					},
					{
						message_id: 'msg_source_answer',
						session_id: 'chat_source',
						role: 'assistant',
						content: 'This passage reports a measured conductivity result.',
						created_at: '2026-08-31T00:00:02+00:00',
						tool_call_id: null,
						tool_name: null,
						tool_arguments: null,
						tool_result: null,
						source_contexts: []
					}
				],
				pending_approval: null,
				error_code: null
			};
			return route.fulfill({
				status: 200,
				contentType: 'text/event-stream',
				body: `event: turn\ndata: ${JSON.stringify(turn)}\n\n`
			});
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
							block_type: 'paragraph',
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

test('a selected document Source reaches the same Collection Agent without a Core write', async ({
	page
}) => {
	let postedMessage: Record<string, unknown> | null = null;
	const consoleErrors: string[] = [];
	const failedResponses: string[] = [];
	page.on('console', (message) => {
		if (message.type() === 'error') consoleErrors.push(message.text());
	});
	page.on('pageerror', (error) => consoleErrors.push(error.message));
	page.on('response', (response) => {
		if (response.status() >= 400) {
			failedResponses.push(`${response.status()} ${new URL(response.url()).pathname}`);
		}
	});
	await mockPaperReaderApis(page, true, (payload) => {
		postedMessage = payload;
	});
	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto(`/collections/${collectionId}/documents/${documentId}?view=parsed-paper`);

	const askAction = page.getByTestId('ask-research-agent-source-results');
	await askAction.locator('..').hover();
	await expect(askAction).toBeVisible();
	if (screenshotDir) {
		await page.screenshot({
			path: join(screenshotDir, 'source-action-paper-desktop.png'),
			fullPage: true
		});
	}
	await askAction.click();
	await page.waitForURL(`/collections/${collectionId}/assistant`);

	const pendingContext = page.getByTestId('pending-source-context');
	await expect(pendingContext).toContainText('Paper A');
	await expect(pendingContext).toContainText('Results');
	await expect(pendingContext).toContainText('Page 3');
	await expect(pendingContext).toContainText('Conductivity improved to 12 mS/cm under EIS.');
	await expectNoHorizontalOverflow(page);
	if (screenshotDir) {
		await page.screenshot({
			path: join(screenshotDir, 'source-context-agent-desktop.png'),
			fullPage: true
		});
	}

	await page.setViewportSize({ width: 390, height: 844 });
	await expect(pendingContext).toBeVisible();
	await expectNoHorizontalOverflow(page);
	if (screenshotDir) {
		await page.screenshot({
			path: join(screenshotDir, 'source-context-agent-mobile.png'),
			fullPage: true
		});
	}

	await page.getByLabel('Message').fill('What does this result support?');
	await page.getByRole('button', { name: 'Send' }).click();
	await expect(
		page.getByText('This passage reports a measured conductivity result.')
	).toBeVisible();

	expect(postedMessage).toMatchObject({
		message: 'What does this result support?',
		source_contexts: [
			{
				collection_id: collectionId,
				document_id: documentId,
				source_kind: 'paragraph',
				source_ref: 'results',
				page: 3,
				quote: 'Conductivity improved to 12 mS/cm under EIS.'
			}
		]
	});
	expect(consoleErrors, `failed responses: ${failedResponses.join(', ')}`).toEqual([]);
});
