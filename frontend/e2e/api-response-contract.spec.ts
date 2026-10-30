import { expect, test, type Page } from '@playwright/test';

test.use({ baseURL: 'http://localhost:4173', locale: 'en-US' });

const collectionId = 'col_response_contract';
const createdAt = '2026-10-30T00:00:00Z';
const user = { user_id: 'researcher', email: 'researcher@example.test' };
const document = {
	document_id: 'paper',
	original_filename: 'lpbf.txt',
	stored_filename: 'lpbf.txt',
	storage_key: 'lpbf.txt',
	sha256: 'a'.repeat(64),
	media_type: 'text/plain',
	status: 'ready',
	size_bytes: 100,
	created_at: createdAt,
	updated_at: createdAt,
	parser_version: 'test',
	document_analysis_version: 'test',
	source_fingerprint: 'source',
	profile_fingerprint: 'profile',
	preparation_fingerprint: 'prepared'
};
const collection = {
	collection_id: collectionId,
	name: 'LPBF response contract',
	description: null,
	status: 'ready',
	paper_count: 1,
	documents: [document],
	created_at: createdAt,
	updated_at: createdAt
};
const session = {
	session_id: 'chat_response_contract',
	user_id: user.user_id,
	collection_id: collectionId,
	created_at: createdAt,
	updated_at: createdAt
};

async function installApi(page: Page, authenticated = true) {
	const state = {
		authenticated,
		expired: false,
		downloads: 0,
		streams: 0,
		unexpected: [] as string[]
	};
	await page.route('**/api/v1/**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname.slice('/api/v1'.length);
		const reply = (data: unknown, code = 200, message = 'success') =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ code, message, data, meta: null })
			});
		if (path === '/auth/login') {
			state.authenticated = true;
			return reply({ user });
		}
		if (!state.authenticated || state.expired) {
			return reply({ code: 'authentication_required' }, 200301, 'Authentication is required.');
		}
		if (path === '/auth/me') return reply({ user });
		if (path === '/collections') return reply({ items: [collection] });
		if (path === `/collections/${collectionId}`) return reply(collection);
		if (path === `/collections/${collectionId}/documents`)
			return reply({ items: [document], count: 1 });
		if (path === `/collections/${collectionId}/pipeline-runs`)
			return reply({ collection_id: collectionId, items: [], count: 0 });
		if (path === `/collections/${collectionId}/objectives`)
			return reply({ collection_id: collectionId, objectives: [], total: 0 });
		if (path === `/collections/${collectionId}/source-archives`) {
			state.downloads += 1;
			return reply(
				{ code: 'source_archive_unavailable' },
				200205,
				'Source archive is unavailable.'
			);
		}
		if (path === '/chat-sessions') {
			return reply(request.method() === 'POST' ? session : { items: [], limit: 12, offset: 0 });
		}
		if (path === `/chat-sessions/${session.session_id}/permissions`) {
			return reply({ mode: 'confirm', actions: [], expires_at: null, revision: 0 });
		}
		if (path === `/chat-sessions/${session.session_id}/messages`) {
			if (request.method() === 'POST') {
				state.streams += 1;
				return reply(
					{ code: 'chat_tool_approval_pending' },
					200204,
					'Resolve the pending research action before sending another message.'
				);
			}
			return reply({
				items: [],
				feedback: [],
				pending_approval: null,
				running: false,
				response: null
			});
		}
		state.unexpected.push(`${request.method()} ${path}`);
		return reply({}, 200000, 'Unexpected test request.');
	});
	return state;
}

test('login opens a collection and a rejected download creates no file', async ({ page }) => {
	const errors: string[] = [];
	const downloads: string[] = [];
	page.on('pageerror', (error) => errors.push(error.message));
	page.on('download', (download) => downloads.push(download.suggestedFilename()));
	const state = await installApi(page, false);
	await page.goto('/login');
	await page.locator('#auth-email').fill(user.email);
	await page.locator('#auth-password').fill('synthetic-test-password');
	await page.getByRole('button', { name: 'Sign in', exact: true }).click();
	await expect(page).toHaveURL('http://localhost:4173/');
	await page.locator(`a[href="/collections/${collectionId}"]`).first().click();
	await expect(page.getByRole('heading', { name: collection.name, exact: true })).toBeVisible();
	await page.locator('details.export-panel > summary').click();
	await page.getByRole('checkbox', { name: 'Select all papers', exact: true }).check();
	await page.getByRole('button', { name: 'Download source ZIP', exact: true }).click();
	await expect(page.getByRole('alert')).toHaveText('Source archive is unavailable.');
	expect(state.downloads).toBe(1);
	expect(downloads).toEqual([]);
	expect(state.unexpected).toEqual([]);
	expect(errors).toEqual([]);
});

test('an expired session returns the authenticated collection reader to login', async ({
	page
}) => {
	const errors: string[] = [];
	page.on('pageerror', (error) => errors.push(error.message));
	const state = await installApi(page);
	await page.goto(`/collections/${collectionId}`);
	await expect(page.getByRole('heading', { name: collection.name, exact: true })).toBeVisible();
	state.expired = true;
	await page.reload();
	await expect(page).toHaveURL('http://localhost:4173/login');
	await expect(page.locator('#auth-email')).toBeVisible();
	expect(state.unexpected).toEqual([]);
	expect(errors).toEqual([]);
});

test('a JSON refusal of an SSE request shows the business error', async ({ page }) => {
	const errors: string[] = [];
	page.on('pageerror', (error) => errors.push(error.message));
	const state = await installApi(page);
	await page.goto(`/collections/${collectionId}/assistant`);
	await page
		.getByRole('textbox', { name: 'Message', exact: true })
		.fill('Which test conditions should I compare?');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText(
		'Resolve the pending research action before sending another message.'
	);
	expect(state.streams).toBe(1);
	expect(state.unexpected).toEqual([]);
	expect(errors).toEqual([]);
});
