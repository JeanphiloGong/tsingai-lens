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
	await expect(page.getByRole('button', { name: 'Log out', exact: true })).toBeVisible();
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
		await expect(page.getByRole('button', { name: 'Log out', exact: true })).toBeVisible();
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
