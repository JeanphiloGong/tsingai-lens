import { expect, test, type Page } from '@playwright/test';

test.use({ baseURL: 'http://localhost:4173' });

async function administrationApi(page: Page) {
	const state = { authenticated: true, codes: ['users.manage'], permissionStatus: 200 };
	const writes: { path: string; method: string; body: unknown }[] = [];
	const reads: string[] = [];
	const groups = [
		{ code: 'admin', name: 'Administrator', description: '', is_system: true },
		{ code: 'lab', name: 'Laboratory', description: 'Project readers', is_system: false }
	];
	await page.addInitScript(() => localStorage.setItem('retrieval.lang', 'en'));
	await page.route('**/user-api/v1/**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		const method = request.method();
		const respond = (body: unknown, status = 200) =>
			route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
		if (path.endsWith('/me'))
			return state.authenticated
				? respond({ user_id: 'operator', email: 'operator@example.test', display_name: 'Operator' })
				: respond({ code: 'authentication_required' }, 401);
		if (path.endsWith('/me/permissions'))
			return state.permissionStatus === 503
				? respond({ code: 'identity_unavailable' }, 503)
				: respond({ permission_codes: state.codes });
		if (method !== 'GET') {
			writes.push({ path, method, body: request.postDataJSON() });
			return respond({ code: method === 'POST' ? 'already_exists' : 'operation_conflict' }, 409);
		}
		reads.push(path);
		if (path.endsWith('/admin/groups'))
			return respond({ items: groups, total: groups.length, limit: 50, offset: 0 });
		if (path.endsWith('/permissions'))
			return respond({ items: [], total: 0, limit: 50, offset: 0 });
		return respond({ items: [], total: 0, limit: 50, offset: 0 });
	});
	return { state, writes, reads };
}

test('direct administration routes block anonymous and ordinary accounts before reading catalogs', async ({
	page
}) => {
	const { state, reads } = await administrationApi(page);
	state.authenticated = false;
	await page.goto('/admin/users');
	await expect(page).toHaveURL(/\/login$/);
	state.authenticated = true;
	state.codes = [];
	for (const path of ['/admin/users', '/admin/groups', '/admin/permissions']) {
		await page.goto(path);
		await expect(page.getByRole('alert')).toContainText('403');
		await expect(
			page.getByRole('link', { name: 'Users and permissions', exact: true })
		).toHaveCount(0);
		await expect(page.locator('form')).toHaveCount(0);
	}
	expect(reads).toEqual([]);
});

test('permission outages offer retry without presenting an outage as denial', async ({ page }) => {
	const { state } = await administrationApi(page);
	state.permissionStatus = 503;
	await page.goto('/admin/users');
	await expect(page.getByRole('alert')).toContainText('Permission service unavailable');
	await expect(page.getByRole('alert')).not.toContainText('Access denied');
	state.permissionStatus = 200;
	state.codes = [];
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('Access denied');
	state.codes = ['users.manage'];
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(
		page.getByRole('link', { name: 'Users and permissions', exact: true })
	).toBeVisible();
	await expect(page.getByLabel('Page size', { exact: true })).toBeVisible();
});

test('failed catalog writes retain drafts and protected entries cannot be deleted', async ({
	page
}) => {
	const { writes } = await administrationApi(page);
	await page.goto('/admin/groups');
	await page.getByLabel('New group code', { exact: true }).fill('lab');
	await page.getByLabel('New group name', { exact: true }).fill('Draft name');
	await page.getByRole('button', { name: 'Create group', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('This code is already registered');
	await expect(page.getByLabel('New group name', { exact: true })).toHaveValue('Draft name');
	expect(writes[0]).toEqual({
		path: '/user-api/v1/admin/groups',
		method: 'POST',
		body: { code: 'lab', name: 'Draft name', description: '' }
	});
	await page.getByRole('button', { name: 'admin', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Delete group', exact: true })).toBeDisabled();
	await page.getByRole('button', { name: 'lab', exact: true }).click();
	await page.getByLabel('Group name', { exact: true }).fill('Unsaved edit');
	page.once('dialog', (dialog) => dialog.dismiss());
	await page.getByRole('button', { name: 'Delete group', exact: true }).click();
	expect(writes).toHaveLength(1);
	page.once('dialog', (dialog) => dialog.accept());
	await page.getByRole('button', { name: 'Delete group', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('entries still in use cannot be deleted');
	await expect(page.getByLabel('Group name', { exact: true })).toHaveValue('Unsaved edit');
	expect(writes[1].method).toBe('DELETE');
});
