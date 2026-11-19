import { expect, test, type Page } from '@playwright/test';
test.use({ baseURL: 'http://localhost:4173' });
async function fixture(page: Page) {
	const state = {
		codes: ['models.manage'],
		fail: false,
		item: {
			connection_id: 'lab-a',
			display_name: 'Laboratory',
			base_url: 'http://127.0.0.1:9999/v1',
			model: 'local-chat',
			kind: 'chat',
			api_key_configured: true,
			enabled: false,
			priority: 0,
			context_window_tokens: null,
			max_output_tokens: null,
			request_timeout_seconds: null,
			version: 1,
			created_at: '2026-11-14T00:00:00Z',
			updated_at: '2026-11-14T00:00:00Z'
		}
	};
	const writes: { method: string; body: Record<string, unknown> }[] = [];
	const reads: string[] = [];
	const assignmentWrites: Record<string, unknown>[] = [];
	const assignments = new Map<string, { connection_id: string | null; version: number }>();
	await page.addInitScript(() => localStorage.setItem('retrieval.lang', 'en'));
	await page.route('**/user-api/v1/**', (route) =>
		route.fulfill({
			json: route.request().url().endsWith('/me/permissions')
				? { permission_codes: state.codes }
				: { user_id: 'operator', email: 'operator@example.test', display_name: 'Operator' }
		})
	);
	await page.route('**/api/v1/model-connections', (route) =>
		route.fulfill({
			json: {
				code: 200,
				message: 'success',
				data: { items: state.item.enabled ? [state.item] : [] },
				meta: null
			}
		})
	);
	await page.route('**/api/v1/admin/model-assignments/**', (route) => {
		const url = new URL(route.request().url());
		const purpose = url.pathname.split('/').at(-1)!;
		if (purpose === 'choices') {
			const items =
				url.searchParams.get('kind') === 'embedding'
					? [{ connection_id: 'vectors', display_name: 'Vectors', model: 'local-embedding' }]
					: state.item.enabled
						? [state.item]
						: [];
			return route.fulfill({
				json: { code: 200, message: 'success', data: { items }, meta: null }
			});
		}
		let assignment = assignments.get(purpose) ?? { connection_id: null, version: 0 };
		if (route.request().method() === 'PUT') {
			const body = route.request().postDataJSON();
			assignmentWrites.push(body);
			assignment = { connection_id: body.connection_id, version: assignment.version + 1 };
			assignments.set(purpose, assignment);
		}
		return route.fulfill({
			json: { code: 200, message: 'success', data: assignment, meta: null }
		});
	});
	await page.route('**/api/v1/admin/model-connections**', async (route) => {
		const request = route.request();
		if (request.method() === 'GET') {
			reads.push(request.url());
			return route.fulfill({
				json: {
					code: 200,
					message: 'success',
					data: new URL(request.url()).pathname.endsWith('/model-connections')
						? { items: [state.item], total: 1, limit: 50, offset: 0 }
						: state.item,
					meta: null
				}
			});
		}
		const body = request.postDataJSON();
		writes.push({ method: request.method(), body });
		if (state.fail)
			return route.fulfill({
				json: {
					code: 200204,
					message: 'Configuration changed',
					data: { code: 'model_connection_version_conflict' },
					meta: null
				}
			});
		if (request.url().endsWith('/test'))
			return route.fulfill({
				json: {
					code: 200,
					message: 'success',
					data: {
						connection_id: state.item.connection_id,
						tested_version: state.item.version,
						success: true,
						reason: null,
						latency_ms: 12
					},
					meta: null
				}
			});
		if (body.display_name) state.item.display_name = body.display_name;
		if (body.enabled !== undefined) state.item.enabled = body.enabled;
		if ('api_key' in body) state.item.api_key_configured = body.api_key !== null;
		state.item.version++;
		return route.fulfill({ json: { code: 200, message: 'success', data: state.item, meta: null } });
	});
	return { state, writes, reads, assignmentWrites };
}
test('model-only administrator saves settings and key once, then clears explicitly', async ({
	page
}) => {
	const { writes } = await fixture(page);
	await page.goto('/account');
	await page.getByRole('button', { name: /^Account menu:/ }).click();
	await page.getByRole('link', { name: 'Administration', exact: true }).click();
	await expect(page).toHaveURL(/\/admin\/models$/);
	await page.goto('/admin/models?connection_id=lab-a');
	await expect(page.getByRole('heading', { name: 'Model connections', exact: true })).toBeVisible();
	const sidebar = page.getByRole('navigation', { name: 'Administration', exact: true });
	await expect(sidebar.getByRole('link')).toHaveCount(3);
	await expect(sidebar.getByRole('link', { name: 'Model connections' })).toBeVisible();
	await expect(sidebar.getByRole('link', { name: 'Model assignments' })).toBeVisible();
	await expect(sidebar.getByRole('link', { name: 'Model change history' })).toBeVisible();
	await page.getByLabel('Name', { exact: true }).fill('Updated model');
	await page.getByLabel('New API key', { exact: true }).fill('synthetic-new');
	await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
	await expect(page.getByLabel('New API key', { exact: true })).toHaveValue('');
	expect(writes).toEqual([
		{
			method: 'PATCH',
			body: { expected_version: 1, display_name: 'Updated model', api_key: 'synthetic-new' }
		}
	]);
	page.once('dialog', (dialog) => dialog.accept());
	await page.getByRole('button', { name: 'Clear saved key', exact: true }).click();
	expect(writes).toHaveLength(1);
	await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
	await expect.poll(() => writes.length).toBe(2);
	expect(writes[1].body).toEqual({ expected_version: 2, api_key: null });
	await expect(page.getByRole('button', { name: 'Clear saved key', exact: true })).toHaveCount(0);
});

test('administrator assigns the document profile model and ordinary accounts cannot access it', async ({
	page
}) => {
	const { state, assignmentWrites } = await fixture(page);
	state.item.enabled = true;
	await page.setViewportSize({ width: 375, height: 812 });
	await page.goto('/admin/models');
	await page.getByRole('link', { name: 'Model assignments', exact: true }).click();
	const select = page.getByRole('combobox', { name: 'Model connection', exact: true });
	await expect(select).toHaveValue('');
	const save = page.getByRole('button', { name: 'Save assignment', exact: true });
	await expect(save).toBeDisabled();
	await select.selectOption('lab-a');
	await save.click();
	await expect(page.getByRole('status')).toHaveText('Assignment saved for new jobs.');
	expect(assignmentWrites).toEqual([{ connection_id: 'lab-a', expected_version: 0 }]);
	await page.reload();
	await expect(select).toHaveValue('lab-a');
	await expect(save).toBeDisabled();
	expect(await page.locator('body').evaluate((body) => body.scrollWidth <= innerWidth)).toBe(true);
	const purpose = page.getByRole('combobox', { name: 'Processing task' });
	await purpose.selectOption('embedding');
	await expect(select.getByRole('option', { name: 'Laboratory · local-chat' })).toHaveCount(0);
	await select.selectOption('vectors');
	await save.click();
	await expect(page.getByRole('status')).toHaveText('Assignment saved for new jobs.');
	expect(assignmentWrites[1]).toEqual({ connection_id: 'vectors', expected_version: 0 });
	await purpose.selectOption('research_analysis');
	await expect(select).toHaveValue('');
	await purpose.selectOption('feedback');
	await select.selectOption('lab-a');
	await save.click();
	await expect(page.getByRole('status')).toHaveText('Assignment saved for new jobs.');
	expect(assignmentWrites[2]).toEqual({ connection_id: 'lab-a', expected_version: 0 });

	state.codes = ['users.manage'];
	await page.reload();
	await expect(page.getByRole('alert')).toContainText('403');
	await expect(page.getByRole('link', { name: 'Model assignments', exact: true })).toHaveCount(0);
	await expect(select).toHaveCount(0);
});
test('conflict retains ordinary draft and clears the key without retry', async ({ page }) => {
	const { state, writes } = await fixture(page);
	state.fail = true;
	await page.goto('/admin/models?connection_id=lab-a');
	await page.getByLabel('Name', { exact: true }).fill('Unsaved draft');
	await page.getByLabel('New API key', { exact: true }).fill('synthetic-new');
	await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('Reload before saving');
	await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Unsaved draft');
	await expect(page.getByLabel('New API key', { exact: true })).toHaveValue('');
	expect(writes).toHaveLength(1);
});
test('ordinary account is denied before model queries; narrow editor stays operable', async ({
	page
}) => {
	const { state, reads } = await fixture(page);
	state.codes = [];
	await page.goto('/admin/models');
	await expect(page.getByRole('alert')).toContainText('403');
	expect(reads).toEqual([]);
	state.codes = ['models.manage'];
	await page.setViewportSize({ width: 375, height: 812 });
	await page.goto('/admin/models?connection_id=lab-a');
	await expect(page.getByLabel('New API key', { exact: true })).toBeVisible();
	expect(
		await page.locator('body').evaluate((element) => element.scrollWidth <= window.innerWidth)
	).toBe(true);
	await page.getByLabel('Name', { exact: true }).focus();
	await page.keyboard.press('Tab');
	await expect(page.getByLabel('Priority', { exact: true })).toBeFocused();
	await page.screenshot({ path: 'test-results/model-admin-mobile.png', fullPage: true });
});
