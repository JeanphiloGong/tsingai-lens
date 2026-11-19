import { expect, test, type Page } from '@playwright/test';

test.use({ baseURL: 'http://localhost:4173' });

async function mockAccountApi(page: Page, authenticated = false) {
	const writes: { path: string; body: Record<string, unknown> }[] = [];
	const state = { authenticated, passwordStatus: 200, challengeStatus: 202 };
	await page.addInitScript(() => localStorage.setItem('retrieval.lang', 'en'));
	await page.route('**/user-api/v1/**', async (route) => {
		const path = new URL(route.request().url()).pathname;
		const respond = (body: unknown, status = 200) =>
			route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
		if (route.request().method() === 'POST')
			writes.push({ path, body: route.request().postDataJSON() ?? {} });
		if (path.endsWith('/me'))
			return state.authenticated
				? respond({
						user_id: 'researcher',
						email: 'researcher@example.test',
						display_name: 'Researcher'
					})
				: respond({ code: 'authentication_required' }, 401);
		if (path.endsWith('/me/permissions')) return respond({ permission_codes: [] });
		if (path.endsWith('/email-challenges'))
			return state.challengeStatus === 429
				? respond({ code: 'rate_limited', retry_after: 1 }, 429)
				: respond({ challenge_id: 'proof-1', expires_in: 600, retry_after: 60 }, 202);
		if (path.endsWith('/register'))
			return respond(
				{ user_id: 'new-researcher', email: 'new@example.test', display_name: 'New' },
				201
			);
		if (path.endsWith('/me/password')) {
			if (state.passwordStatus !== 200)
				return respond(
					{
						code: state.passwordStatus === 401 ? 'authentication_required' : 'identity_unavailable'
					},
					state.passwordStatus
				);
			state.authenticated = false;
		}
		return respond({ ok: true });
	});
	await page.route('**/api/v1/**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ code: 200, message: 'success', data: { items: [] }, meta: null })
		})
	);
	return { writes, state };
}

for (const width of [320, 768, 1024, 1440]) {
	test(`personal menu supports preferences, account navigation and logout at ${width}px`, async ({
		page
	}, testInfo) => {
		const { writes } = await mockAccountApi(page, true);
		await page.setViewportSize({ width, height: 900 });
		const errors: string[] = [];
		page.on('pageerror', (error) => errors.push(error.message));
		await page.goto('/');
		const trigger = page.getByRole('button', { name: 'Account menu: Researcher', exact: true });
		const menu = page.getByRole('group', { name: 'Account menu', exact: true });
		await expect(trigger).toHaveAttribute('aria-expanded', 'false');
		await expect(page.getByRole('link', { name: 'Account settings', exact: true })).toHaveCount(0);
		await expect(page.getByRole('button', { name: /^Appearance/ })).toHaveCount(0);
		await expect(page.getByRole('button', { name: /^Language/ })).toHaveCount(0);
		const headerBox = (await page.getByRole('banner').boundingBox())!;
		expect(headerBox.height).toBeLessThanOrEqual(80);
		if (width <= 720) await expect(trigger.locator('.session-name')).toBeHidden();
		else await expect(trigger.locator('.session-name')).toBeVisible();
		await trigger.click();
		await expect(menu.getByText('Researcher', { exact: true })).toBeVisible();
		await expect(menu.getByText('researcher@example.test', { exact: true })).toBeVisible();
		await expect(menu.getByRole('link', { name: 'Administration', exact: true })).toHaveCount(0);
		const box = (await menu.boundingBox())!;
		expect(box.x).toBeGreaterThanOrEqual(0);
		expect(box.x + box.width).toBeLessThanOrEqual(width);
		await page.screenshot({ path: testInfo.outputPath(`personal-menu-light-${width}.png`) });
		await trigger.click();
		await expect(menu).toHaveCount(0);
		await trigger.click();
		await page.mouse.click(2, 2);
		await expect(menu).toHaveCount(0);
		await trigger.click();
		const appearance = menu.getByRole('button', { name: /^Appearance / });
		await appearance.click();
		await expect(menu.getByRole('button', { name: 'System', exact: true })).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		await expect(menu.getByRole('button', { name: 'System', exact: true })).toBeFocused();
		await page.screenshot({ path: testInfo.outputPath(`personal-menu-appearance-${width}.png`) });
		await page.keyboard.press('Escape');
		await expect(menu).toHaveCount(0);
		await expect(trigger).toBeFocused();
		await trigger.click();
		await expect(menu.getByRole('link', { name: 'Account settings', exact: true })).toBeVisible();
		await appearance.click();
		await menu.getByRole('button', { name: 'Back to account menu', exact: true }).click();
		await expect(appearance).toBeFocused();
		await trigger.click();
		await trigger.press('Enter');
		const account = menu.getByRole('link', { name: 'Account settings', exact: true });
		await page.keyboard.press('Tab');
		await expect(account).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(menu).toHaveCount(0);
		await expect(trigger).toBeFocused();
		await trigger.press('Enter');
		await page.keyboard.press('Tab');
		await page.keyboard.press('Tab');
		await expect(appearance).toBeFocused();
		await page.keyboard.press('Tab');
		await expect(menu.getByRole('button', { name: /^Language / })).toBeFocused();
		await page.keyboard.press('Tab');
		await expect(menu.getByRole('button', { name: 'Log out', exact: true })).toBeFocused();
		await page.keyboard.press('Tab');
		await expect(menu).toHaveCount(0);
		await trigger.click();
		await account.click();
		await expect(page).toHaveURL(/\/account$/);
		await expect(menu).toHaveCount(0);
		const password = page.getByLabel('Current password', { exact: true });
		await password.fill('unsaved-password-input');
		await trigger.click();
		await appearance.click();
		await menu.getByRole('button', { name: 'Dark', exact: true }).click();
		await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
		await expect(appearance).toBeFocused();
		await expect(password).toHaveValue('unsaved-password-input');
		await menu.getByRole('button', { name: /^Language / }).click();
		await expect(menu.getByRole('button', { name: 'English', exact: true })).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		await page.screenshot({ path: testInfo.outputPath(`personal-menu-language-${width}.png`) });
		await menu.getByRole('button', { name: '简体中文', exact: true }).click();
		await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
		await expect(page.getByRole('button', { name: /^语言 / })).toBeFocused();
		await expect(page.getByLabel('当前密码', { exact: true })).toHaveValue(
			'unsaved-password-input'
		);
		await expect(page.getByRole('link', { name: '账号设置', exact: true })).toBeVisible();
		expect(writes).toHaveLength(0);
		await page.screenshot({ path: testInfo.outputPath(`personal-menu-dark-${width}.png`) });
		await page.getByRole('button', { name: '退出', exact: true }).click();
		await expect(page).toHaveURL(/\/login$/);
		await expect(page.getByRole('button', { name: /^个人菜单:/ })).toHaveCount(0);
		expect(writes.map((write) => write.path)).toEqual(['/user-api/v1/logout']);
		expect(errors).toEqual([]);
	});
}

test('personal menu keeps long account details and actions reachable on a short mobile screen', async ({
	page
}) => {
	await mockAccountApi(page, true);
	const displayName = '负责跨论文材料研究与实验结果比较的科研工作者';
	await page.route('**/user-api/v1/me', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				user_id: 'researcher',
				email: 'researcher.with.a.long.email.address@example.test',
				display_name: displayName
			})
		})
	);
	await page.setViewportSize({ width: 320, height: 360 });
	await page.goto('/account');
	const trigger = page.getByRole('button', { name: `Account menu: ${displayName}`, exact: true });
	await trigger.click();
	const menu = page.getByRole('group', { name: 'Account menu', exact: true });
	await expect(menu.getByText(displayName, { exact: true })).toBeVisible();
	const bounds = (await menu.boundingBox())!;
	expect(bounds.x).toBeGreaterThanOrEqual(0);
	expect(bounds.x + bounds.width).toBeLessThanOrEqual(320);
	expect(bounds.y + bounds.height).toBeLessThanOrEqual(360);
	await menu.getByRole('button', { name: 'Log out', exact: true }).scrollIntoViewIfNeeded();
	await expect(menu.getByRole('button', { name: 'Log out', exact: true })).toBeInViewport();
	await page.keyboard.press('Escape');
	await expect(trigger).toBeFocused();
});

for (const route of ['register', 'forgot-password'] as const) {
	test(`${route} rejects mismatched passwords, preserves code strings and returns to login`, async ({
		page
	}) => {
		const { writes } = await mockAccountApi(page);
		await page.goto(`/${route}`);
		await expect(page).toHaveURL(new RegExp(`/${route}$`));
		await page.getByLabel('Email', { exact: true }).fill('new@example.test');
		await page.getByRole('button', { name: 'Send code', exact: true }).click();
		await expect(page.getByRole('status')).toContainText('eligible');
		await page.getByLabel('Email code', { exact: true }).fill('001234');
		await page
			.getByLabel('New password (12 characters minimum)', { exact: true })
			.fill('replacement-password');
		await page.getByLabel('Confirm new password', { exact: true }).fill('different-password');
		const button = page.getByRole('button', {
			name: route === 'register' ? 'Create account' : 'Reset password',
			exact: true
		});
		if (route === 'register') {
			await expect(
				page.getByLabel('Confirm new password', { exact: true })
			).toHaveAccessibleDescription('The new passwords do not match.');
			await expect(button).toBeDisabled();
		} else {
			await button.click();
			await expect(page.getByRole('alert')).toHaveText('The new passwords do not match.');
		}
		expect(writes).toHaveLength(1);
		await page.getByLabel('Confirm new password', { exact: true }).fill('replacement-password');
		await button.click();
		await expect(page).toHaveURL(
			new RegExp(`/login\\?${route === 'register' ? 'registered' : 'passwordReset'}=1$`)
		);
		await expect(page.getByRole('status')).toContainText(
			route === 'register' ? 'Account created' : 'Password reset'
		);
		expect(writes[1].body).toEqual({
			email: 'new@example.test',
			challenge_id: 'proof-1',
			code: '001234',
			password: 'replacement-password',
			...(route === 'register' ? { display_name: '' } : {})
		});
		await expect(page.locator('#auth-password')).toHaveValue('');
		await expect(page.getByRole('button', { name: 'Log out' })).toHaveCount(0);
	});
}

test('register explains short passwords and the remaining fields before submission', async ({
	page
}) => {
	const { writes } = await mockAccountApi(page);
	await page.goto('/register');
	await page.getByLabel('Email', { exact: true }).fill('new@example.test');
	await expect(
		page.getByText('Request a code on this page. After a refresh, request a new code.')
	).toBeVisible();
	await page.getByRole('button', { name: 'Send code', exact: true }).click();
	await expect(page.getByRole('status')).toContainText('eligible');
	await expect(page.getByText('Enter the 6-digit code from your email.')).toBeVisible();
	await page.getByLabel('Email code', { exact: true }).fill('001234');
	const password = page.getByLabel('New password (12 characters minimum)', { exact: true });
	const confirmation = page.getByLabel('Confirm new password', { exact: true });
	const submit = page.getByRole('button', { name: 'Create account', exact: true });
	await password.fill('12345678901');
	await confirmation.fill('12345678901');
	await expect(password).toHaveAttribute('aria-invalid', 'true');
	await expect(password).toHaveAccessibleDescription('Use at least 12 characters; currently 11.');
	await expect(submit).toBeDisabled();
	await password.fill('123456789012');
	await expect(confirmation).toHaveAccessibleDescription('The new passwords do not match.');
	await expect(submit).toBeDisabled();
	await confirmation.fill('123456789012');
	await expect(password).toHaveAttribute('aria-invalid', 'false');
	await expect(submit).toBeEnabled();
	await page.getByLabel('Email code', { exact: true }).fill('abcdef');
	await expect(page.getByLabel('Email code', { exact: true })).toHaveAccessibleDescription(
		'Enter the 6-digit code from your email.'
	);
	await expect(submit).toBeDisabled();
	await page.getByLabel('Email code', { exact: true }).fill('001234');
	await expect(submit).toBeEnabled();
	expect(writes).toHaveLength(1);
	await submit.click();
	await expect(page).toHaveURL(/\/login\?registered=1$/);
	expect(writes[1].body.password).toBe('123456789012');
});

test('register explains missing proof after a refresh and localizes password guidance', async ({
	page
}) => {
	await mockAccountApi(page);
	await page.goto('/register');
	await page.getByLabel('Email', { exact: true }).fill('new@example.test');
	await page.getByRole('button', { name: 'Send code', exact: true }).click();
	await expect(page.getByRole('status')).toContainText('eligible');
	await page.reload();
	await page.getByRole('combobox').selectOption('zh');
	await expect(page.getByText('请先在本页发送验证码；刷新页面后需要重新获取。')).toBeVisible();
	const password = page.getByLabel('新密码（至少12位）', { exact: true });
	await password.fill('12345678901');
	await expect(password).toHaveAccessibleDescription('至少 12 个字符，当前 11 个。');
	await expect(page.getByRole('button', { name: '创建账号', exact: true })).toBeDisabled();
});

test('429 disables resend until the server retry period ends', async ({ page }) => {
	const { state } = await mockAccountApi(page);
	state.challengeStatus = 429;
	await page.goto('/register');
	await page.getByLabel('Email', { exact: true }).fill('new@example.test');
	await page.getByRole('button', { name: 'Send code', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('Too many attempts');
	await expect(page.getByRole('button', { name: /Send code/ })).toBeDisabled();
	state.challengeStatus = 202;
	await expect(page.getByRole('button', { name: 'Send code', exact: true })).toBeEnabled();
	await page.getByRole('button', { name: 'Send code', exact: true }).click();
	await expect(page.getByRole('status')).toContainText('eligible');
});

test('editing the email discards the old proof and code', async ({ page }) => {
	await mockAccountApi(page);
	await page.goto('/register');
	await page.getByLabel('Email', { exact: true }).fill('first@example.test');
	await page.getByRole('button', { name: 'Send code', exact: true }).click();
	await expect(page.getByRole('status')).toContainText('eligible');
	await page.getByLabel('Email code', { exact: true }).fill('001234');
	await page.getByLabel('Email', { exact: true }).fill('second@example.test');
	await expect(page.getByLabel('Email code', { exact: true })).toHaveValue('');
	await expect(page.getByRole('button', { name: 'Create account', exact: true })).toBeDisabled();
	await expect(page.getByRole('status')).toHaveCount(0);
});

test('account password errors retain login; confirmation stays local and success signs out', async ({
	page
}) => {
	const { writes, state } = await mockAccountApi(page, true);
	await page.goto('/account');
	await expect(page.getByRole('button', { name: /^Account menu:/ })).toBeVisible();
	await page.getByLabel('Current password', { exact: true }).fill('current-password');
	await page
		.getByLabel('New password (12 characters minimum)', { exact: true })
		.fill('replacement-password');
	await page.getByLabel('Confirm new password', { exact: true }).fill('different-password');
	const button = page.getByRole('button', { name: 'Change password', exact: true });
	await button.click();
	await expect(page.getByRole('alert')).toContainText('do not match');
	expect(writes).toHaveLength(0);
	await page.getByLabel('Confirm new password', { exact: true }).fill('replacement-password');
	for (const status of [401, 503]) {
		state.passwordStatus = status;
		await button.click();
		await expect(page.getByRole('alert')).toContainText(
			status === 401 ? 'current password is incorrect' : 'unavailable'
		);
		await expect(page).toHaveURL(/\/account$/);
		await expect(page.getByRole('button', { name: /^Account menu:/ })).toBeVisible();
	}
	state.passwordStatus = 200;
	await button.click();
	await expect(page).toHaveURL(/\/login\?passwordChanged=1$/);
	await expect(page.getByRole('status')).toContainText('Password changed');
	expect(writes.at(-1)?.body).toEqual({
		old_password: 'current-password',
		password: 'replacement-password'
	});
});

for (const width of [320, 768, 1440]) {
	test(`account forms fit the viewport and support Chinese at ${width}px`, async ({
		page
	}, testInfo) => {
		await mockAccountApi(page, true);
		await page.setViewportSize({ width, height: 900 });
		for (const path of ['/register', '/forgot-password', '/account']) {
			await page.goto(path);
			await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
			if (path === '/account')
				await expect(
					page.getByRole('button', { name: 'Change password', exact: true })
				).toBeEnabled();
			expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
				true
			);
			if (path !== '/account') {
				await page.getByRole('combobox').selectOption('zh');
				await expect(page.getByLabel('再次输入新密码', { exact: true })).toBeVisible();
			}
			await page.screenshot({
				path: testInfo.outputPath(`${path.slice(1)}-${width}.png`),
				fullPage: true
			});
		}
	});
}

test('a late registration response cannot navigate away from a new account page', async ({
	page
}) => {
	await mockAccountApi(page);
	let finish!: () => void;
	const responseReady = new Promise<void>((resolve) => {
		finish = resolve;
	});
	await page.route('**/user-api/v1/register', async (route) => {
		await responseReady;
		await route.fulfill({
			status: 201,
			contentType: 'application/json',
			body: JSON.stringify({ user_id: 'new-researcher', email: 'new@example.test' })
		});
	});
	await page.goto('/register');
	await page.getByLabel('Email', { exact: true }).fill('new@example.test');
	await page.getByRole('button', { name: 'Send code', exact: true }).click();
	await expect(page.getByRole('status')).toContainText('eligible');
	await page.getByLabel('Email code', { exact: true }).fill('001234');
	await page
		.getByLabel('New password (12 characters minimum)', { exact: true })
		.fill('replacement-password');
	await page.getByLabel('Confirm new password', { exact: true }).fill('replacement-password');
	await page.getByRole('button', { name: 'Create account', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Please wait', exact: true })).toBeDisabled();
	await page.getByRole('link', { name: 'Back to sign in', exact: true }).click();
	await page.getByRole('link', { name: 'Reset password', exact: true }).click();
	await expect(page).toHaveURL(/\/forgot-password$/);
	const received = page.waitForResponse((response) =>
		response.url().endsWith('/user-api/v1/register')
	);
	finish();
	await (await received).finished();
	await page.evaluate(() => new Promise(requestAnimationFrame));
	await expect(page).toHaveURL(/\/forgot-password$/);
});

test('recovery proof and service errors retain the form and never display success', async ({
	page
}) => {
	await mockAccountApi(page);
	let status = 422;
	await page.route('**/user-api/v1/password-resets', (route) =>
		route.fulfill({
			status,
			contentType: 'application/json',
			body: JSON.stringify({
				code: status === 422 ? 'invalid_email_proof' : 'identity_unavailable'
			})
		})
	);
	await page.goto('/forgot-password');
	await page.getByLabel('Email', { exact: true }).fill('new@example.test');
	await page.getByRole('button', { name: 'Send code', exact: true }).click();
	await expect(page.getByRole('status')).toContainText('eligible');
	await page.getByLabel('Email code', { exact: true }).fill('001234');
	await page
		.getByLabel('New password (12 characters minimum)', { exact: true })
		.fill('replacement-password');
	await page.getByLabel('Confirm new password', { exact: true }).fill('replacement-password');
	for (const expected of ['The code is invalid', 'unavailable']) {
		await page.getByRole('button', { name: 'Reset password', exact: true }).click();
		await expect(page.getByRole('alert')).toContainText(expected);
		await expect(page).toHaveURL(/\/forgot-password$/);
		await expect(page.getByLabel('Email code', { exact: true })).toHaveValue('001234');
		status = 503;
	}
});
