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
		await page.getByRole('button', { name: /^Account menu:/ }).click();
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
	await page.getByRole('button', { name: /^Account menu:/ }).click();
	await expect(
		page.getByRole('link', { name: 'Users and permissions', exact: true })
	).toBeVisible();
	await expect(page.getByLabel('Page size', { exact: true })).toBeVisible();
});

test('personal menu exposes administration only when the current account has the grant', async ({
	page
}, testInfo) => {
	const { state, reads } = await administrationApi(page);
	await page.goto('/account');
	await page.getByRole('button', { name: /^Account menu:/ }).click();
	const administration = page.getByRole('link', { name: 'Users and permissions', exact: true });
	await expect(administration).toBeVisible();
	expect(reads).toEqual([]);
	await page.screenshot({ path: testInfo.outputPath('personal-menu-administrator.png') });
	await administration.click();
	await expect(page).toHaveURL(/\/admin\/users$/);
	await expect(page.getByRole('group', { name: 'Account menu', exact: true })).toHaveCount(0);
	state.codes = [];
	await page.reload();
	await expect(page.getByRole('alert')).toContainText('Access denied');
	await page.getByRole('button', { name: /^Account menu:/ }).click();
	await expect(administration).toHaveCount(0);
});

test('failed catalog writes retain drafts and protected entries cannot be deleted', async ({
	page
}) => {
	const { writes } = await administrationApi(page);
	await page.goto('/admin/groups');
	await page.getByRole('button', { name: 'Create group', exact: true }).click();
	await expect(page.getByRole('dialog')).toBeVisible();
	await page.getByLabel('New group code', { exact: true }).fill('lab');
	await page.getByLabel('New group name', { exact: true }).fill('Draft name');
	await page.getByRole('dialog').getByRole('button', { name: 'Create group', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('This code is already registered');
	await expect(page.getByLabel('New group name', { exact: true })).toHaveValue('Draft name');
	expect(writes[0]).toEqual({
		path: '/user-api/v1/admin/groups',
		method: 'POST',
		body: { code: 'lab', name: 'Draft name', description: '' }
	});
	await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
	await page.getByRole('button', { name: 'Select group Administrator', exact: true }).click();
	await page.getByRole('button', { name: 'Basic information', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Delete group', exact: true })).toBeDisabled();
	await page.getByRole('button', { name: 'Select group Laboratory', exact: true }).click();
	await page.getByRole('button', { name: 'Basic information', exact: true }).click();
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

test('administration layout uses the current paginated contract without search or type filters', async ({
	page
}) => {
	await administrationApi(page);
	const requests: URL[] = [];
	page.on('request', (request) => {
		if (request.url().includes('/user-api/v1/admin/')) requests.push(new URL(request.url()));
	});
	await page.goto('/admin/groups');
	await expect(
		page.getByRole('navigation', { name: 'Users and permissions', exact: true })
	).toBeVisible();
	await expect(
		page.getByRole('button', { name: 'Select group Administrator', exact: true })
	).toBeVisible();
	await expect(
		page.getByRole('button', { name: 'Group permissions', exact: true })
	).toHaveAttribute('aria-pressed', 'true');
	await expect(page.getByRole('searchbox')).toHaveCount(0);
	await expect(page.locator('form:visible')).toHaveCount(0);
	await page.getByRole('button', { name: 'Create group', exact: true }).click();
	await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
	for (const request of requests) {
		expect([...request.searchParams.keys()].every((key) => ['limit', 'offset'].includes(key))).toBe(
			true
		);
	}
});

async function managementScenario(page: Page) {
	const fixture = await administrationApi(page);
	const user = {
		user_id: 'user_researcher',
		email: 'researcher@example.test',
		display_name: 'Researcher',
		active: true
	};
	const permission = {
		code: 'project.read',
		name: 'Read projects',
		description: 'Read shared project documents',
		is_system: false
	};
	const membership = {
		code: 'lab',
		name: 'Laboratory',
		description: 'Project readers',
		is_system: false
	};
	let assigned = false;
	let granted = false;
	const writes: { method: string; path: string; body: unknown }[] = [];
	await page.route('**/user-api/v1/admin/**', async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		const path = url.pathname;
		const method = request.method();
		const respond = (body: unknown) =>
			route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
		const list = (items: unknown[]) =>
			respond({ items, total: items.length, limit: 50, offset: 0 });
		if (method !== 'GET') {
			writes.push({ method, path, body: request.postDataJSON() });
			if (path.endsWith('/groups/lab') && path.includes('/users/')) assigned = method === 'PUT';
			if (path.endsWith('/permissions/project.read') && path.includes('/groups/'))
				granted = method === 'PUT';
			if (path.endsWith('/status')) user.active = request.postDataJSON().active;
			if (path === '/user-api/v1/admin/permissions/project.read' && method === 'PATCH')
				Object.assign(permission, request.postDataJSON());
			return respond({ ok: true });
		}
		if (path === '/user-api/v1/admin/users') return list([user]);
		if (path === '/user-api/v1/admin/users/user_researcher/groups')
			return list(assigned ? [membership] : []);
		if (path === '/user-api/v1/admin/permissions') return list([permission]);
		if (path === '/user-api/v1/admin/groups/admin/permissions')
			return list(granted ? [permission] : []);
		return route.fallback();
	});
	return { ...fixture, writes, user, permission };
}

test('users can receive and lose a group and be disabled through the existing endpoints', async ({
	page
}) => {
	const { writes } = await managementScenario(page);
	await page.goto('/admin/users');
	await expect(page.getByRole('heading', { name: 'Researcher', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Assign group', exact: true }).click();
	await page.getByLabel('Existing group code', { exact: true }).selectOption('lab');
	await page.getByRole('button', { name: 'Assign group', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Remove group lab', exact: true })).toBeVisible();
	expect(writes[0]).toMatchObject({
		method: 'PUT',
		path: '/user-api/v1/admin/users/user_researcher/groups/lab'
	});
	await page.getByRole('button', { name: 'Remove group lab', exact: true }).click();
	await expect(page.getByText('No group memberships', { exact: true })).toBeVisible();
	expect(writes[1].method).toBe('DELETE');
	page.once('dialog', (dialog) => dialog.accept());
	await page.getByRole('button', { name: 'Disable account', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Enable account', exact: true })).toBeVisible();
	expect(writes[2]).toEqual({
		method: 'PATCH',
		path: '/user-api/v1/admin/users/user_researcher/status',
		body: { active: false }
	});
});

test('group permissions are selected from the directory and removed using stable codes', async ({
	page
}) => {
	const { writes } = await managementScenario(page);
	await page.goto('/admin/groups');
	await page.getByRole('button', { name: 'Add permission', exact: true }).click();
	await page.getByLabel('Existing permission code', { exact: true }).selectOption('project.read');
	await page.locator('form').getByRole('button', { name: 'Add permission', exact: true }).click();
	await expect(
		page.getByRole('button', { name: 'Remove permission project.read', exact: true })
	).toBeVisible();
	expect(writes[0]).toMatchObject({
		method: 'PUT',
		path: '/user-api/v1/admin/groups/admin/permissions/project.read'
	});
	await page.getByRole('button', { name: 'Remove permission project.read', exact: true }).click();
	await expect(page.getByText('No group permissions', { exact: true })).toBeVisible();
	expect(writes[1].method).toBe('DELETE');
});

test('permission metadata saves from the editor and closes after confirmed success', async ({
	page
}) => {
	const { writes } = await managementScenario(page);
	await page.goto('/admin/permissions');
	await page.getByRole('button', { name: 'Edit permission Read projects', exact: true }).click();
	const editor = page.getByRole('dialog');
	await expect(editor).toBeVisible();
	await expect(editor.getByLabel('Code', { exact: true })).toHaveAttribute('readonly', '');
	await editor.getByLabel('Permission name', { exact: true }).fill('Read laboratory projects');
	await editor.getByRole('button', { name: 'Save metadata', exact: true }).click();
	await expect(editor).not.toBeVisible();
	await expect(page.getByText('Read laboratory projects', { exact: true })).toBeVisible();
	expect(writes[0]).toEqual({
		method: 'PATCH',
		path: '/user-api/v1/admin/permissions/project.read',
		body: { name: 'Read laboratory projects', description: 'Read shared project documents' }
	});
});

for (const width of [320, 768, 1440]) {
	test(`administration layouts stay usable in Chinese at ${width}px`, async ({
		page
	}, testInfo) => {
		await managementScenario(page);
		const catalog = [
			{
				code: 'users.manage',
				name: '人员与权限管理',
				description: '管理人员状态、权限组与授权',
				is_system: true
			},
			{
				code: 'research.read_all',
				name: '全库科研只读',
				description: '查看科研集合与原始资料',
				is_system: true
			},
			{
				code: 'annotation.annotate',
				name: '共享标注',
				description: '编辑共享样本的标注内容',
				is_system: true
			},
			{
				code: 'annotation.review',
				name: '标注复核',
				description: '复核并确认标注结果',
				is_system: true
			},
			{
				code: 'dataset.publish',
				name: '数据集发布',
				description: '发布已准备的数据集',
				is_system: true
			},
			{
				code: 'dataset.download',
				name: '数据集下载',
				description: '下载已发布的数据集',
				is_system: true
			}
		];
		const groupCatalog = [
			{ code: 'admin', name: '系统管理员', description: '管理人员与访问权限', is_system: true },
			{
				code: 'annotator',
				name: '标注员',
				description: '读取科研资料并整理共享标注',
				is_system: true
			},
			{
				code: 'reviewer',
				name: '复核员',
				description: '复核共享标注的内容与证据',
				is_system: true
			},
			{
				code: 'publisher',
				name: '数据发布员',
				description: '管理数据集发布与下载',
				is_system: true
			},
			{ code: 'material_lab', name: '材料实验室', description: '实验室协作人员', is_system: false }
		];
		await page.route('**/user-api/v1/admin/**', (route) => {
			const path = new URL(route.request().url()).pathname;
			let items: unknown[];
			if (path === '/user-api/v1/admin/groups') items = groupCatalog;
			else if (path === '/user-api/v1/admin/permissions') items = catalog;
			else if (path === '/user-api/v1/admin/users')
				items = ['陈予', '林晓', '周宁', '顾遥', '叶安', '苏禾', '徐知', '陆澄'].map(
					(name, index) => ({
						user_id: `user_example_${index}`,
						display_name: name,
						email: `researcher${index}@example.test`,
						active: index !== 4 && index !== 7
					})
				);
			else if (path.endsWith('/users/user_example_0/groups')) items = [groupCatalog[1]];
			else if (path.endsWith('/groups/annotator/permissions')) items = [catalog[1], catalog[2]];
			else if (path.endsWith('/groups/admin/permissions')) items = [catalog[0]];
			else return route.fallback();
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items, total: items.length, limit: 50, offset: 0 })
			});
		});
		await page.addInitScript(() => localStorage.setItem('retrieval.lang', 'zh'));
		await page.setViewportSize({ width, height: 1000 });
		const errors: string[] = [];
		page.on('pageerror', (error) => errors.push(error.message));
		for (const section of ['groups', 'users', 'permissions']) {
			await page.goto(`/admin/${section}`);
			await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
			await expect(page.getByLabel('每页数量', { exact: true })).toBeVisible();
			if (section === 'groups') {
				await page.getByRole('button', { name: '选择权限组 标注员', exact: true }).click();
				await expect(
					page.getByRole('button', { name: '移除权限 annotation.annotate', exact: true })
				).toBeVisible();
			}
			expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
				true
			);
			await page.screenshot({
				path: testInfo.outputPath(`${section}-${width}.png`),
				fullPage: true
			});
			if (section === 'permissions') {
				await page.getByRole('button', { name: '新建权限码', exact: true }).click();
				await expect(page.getByRole('dialog')).toBeVisible();
				await expect(page.getByLabel('新权限码', { exact: true })).toBeVisible();
				await page.keyboard.press('Escape');
				await expect(page.getByRole('dialog')).not.toBeVisible();
			}
		}
		expect(errors).toEqual([]);
	});
}

test('group assignment can select a group beyond the first directory page', async ({ page }) => {
	const { writes } = await managementScenario(page);
	const offsets: string[] = [];
	await page.route('**/user-api/v1/admin/groups?*', (route) => {
		const offset = new URL(route.request().url()).searchParams.get('offset') || '0';
		offsets.push(offset);
		return route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				items:
					offset === '0'
						? [{ code: 'admin', name: 'Administrator', description: '', is_system: true }]
						: [{ code: 'lab', name: 'Laboratory', description: '', is_system: false }],
				total: 51,
				limit: 50,
				offset: Number(offset)
			})
		});
	});
	await page.goto('/admin/users');
	await page.getByRole('button', { name: 'Assign group', exact: true }).click();
	await expect(
		page.getByLabel('Existing group code', { exact: true }).locator('option')
	).toHaveCount(2);
	await page.getByRole('button', { name: 'Next options', exact: true }).click();
	await page.getByLabel('Existing group code', { exact: true }).selectOption('lab');
	await page.getByRole('button', { name: 'Assign group', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Remove group lab', exact: true })).toBeVisible();
	expect(offsets).toEqual(['0', '50']);
	expect(writes[0].path).toBe('/user-api/v1/admin/users/user_researcher/groups/lab');
});
