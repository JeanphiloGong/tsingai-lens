import { expect, test, type Page } from '@playwright/test';
test.skip(!process.env.MODEL_ADMIN_LIVE_ORIGIN, 'Start the supplied isolated live stack');
async function login(page: Page, email: string) {
	await page.addInitScript(() => localStorage.setItem('retrieval.lang', 'en'));
	const origin = process.env.MODEL_ADMIN_LIVE_ORIGIN!;
	const response = await page.request.post(`${origin}/user-api/v1/login`, {
		headers: { Origin: origin },
		data: { email, password: 'tutorial-only-password' }
	});
	expect(response.status()).toBe(200);
	await page.goto('/');
	await expect(page.getByRole('button', { name: /^Account menu:/ })).toBeVisible();
}
test('real administrator saves/tests/enables a model, researcher uses it and loses new access on disable', async ({
	page,
	browser,
	baseURL
}) => {
	const errors: string[] = [];
	page.on('pageerror', (error) => errors.push(error.message));
	await login(page, 'operator@example.test');
	await page.goto('/admin/models?connection_id=new');
	await page.getByLabel('Name', { exact: true }).fill('Tutorial local model');
	await page.getByLabel('API base URL', { exact: true }).fill('http://127.0.0.1:19011/v1');
	await page.getByLabel('Model', { exact: true }).fill('tutorial-chat');
	await page.getByLabel('New API key', { exact: true }).fill('tutorial-provider-key');
	const firstSave = page.waitForResponse(
		(response) =>
			response.request().method() === 'POST' && response.url().endsWith('/admin/model-connections')
	);
	await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
	await firstSave;
	await expect(page.getByRole('heading', { level: 2, name: 'Tutorial local model' })).toBeVisible();
	await expect(page.getByLabel('New API key', { exact: true })).toHaveValue('');
	page.once('dialog', (dialog) => dialog.accept());
	await page.getByRole('button', { name: 'Test saved connection', exact: true }).click();
	await expect(page.getByRole('status')).toContainText('Connection test succeeded');
	await page.getByRole('checkbox', { name: 'Enabled', exact: true }).check();
	const enabledSave = page.waitForResponse(
		(response) =>
			response.request().method() === 'PATCH' &&
			response.url().includes('/admin/model-connections/')
	);
	await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
	await enabledSave;
	await expect(
		page.getByRole('button', { name: 'Save configuration', exact: true })
	).toBeDisabled();
	const context = await browser.newContext({ baseURL });
	const researcher = await context.newPage();
	researcher.on('pageerror', (error) => errors.push(error.message));
	await login(researcher, 'researcher@example.test');
	await researcher.goto('/admin/models');
	await expect(researcher.getByRole('alert')).toContainText('403');
	const catalog = (await (await researcher.request.get('/api/v1/model-connections')).json()).data
		.items;
	expect(catalog).toHaveLength(1);
	expect(Object.keys(catalog[0]).sort()).toEqual(['connection_id', 'display_name', 'model']);
	const created = (
		await (
			await researcher.request.post('/api/v1/collections', {
				data: { name: 'Synthetic model tutorial' }
			})
		).json()
	).data;
	const collectionID = created.collection_id;
	expect(collectionID).toBeTruthy();
	await researcher.goto(`/collections/${collectionID}/assistant`);
	await expect(researcher.getByTestId('model-connection-picker')).toContainText(
		'Tutorial local model'
	);
	// Exercise the existing authenticated Chat entrypoint with the selected ID.
	const session = (
		await (
			await researcher.request.post('/api/v1/conversations', {
				data: { collection_id: collectionID }
			})
		).json()
	).data;
	const answer = await researcher.request.post(
		`/api/v1/conversations/${session.session_id}/messages`,
		{
			data: {
				message: 'Respond without tools for this synthetic connectivity check.',
				model_connection_id: catalog[0].connection_id
			}
		}
	);
	const response = await answer.json();
	expect(response.code).toBe(200);
	expect(JSON.stringify(response)).toContain('Synthetic local model response');
	expect(JSON.stringify(response)).not.toContain('tutorial-provider-key');
	await page.getByRole('checkbox', { name: 'Enabled', exact: true }).uncheck();
	const disabledSave = page.waitForResponse(
		(response) =>
			response.request().method() === 'PATCH' &&
			response.url().includes('/admin/model-connections/')
	);
	await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
	await disabledSave;
	await expect(
		page.getByRole('button', { name: 'Save configuration', exact: true })
	).toBeDisabled();
	expect(
		(await (await researcher.request.get('/api/v1/model-connections')).json()).data.items
	).toEqual([]);
	const refused = await researcher.request.get('/api/v1/admin/model-connections');
	expect(refused.status()).toBe(403);
	await page.screenshot({ path: 'test-results/model-admin-live.png', fullPage: true });
	expect(errors).toEqual([]);
	await context.close();
});
