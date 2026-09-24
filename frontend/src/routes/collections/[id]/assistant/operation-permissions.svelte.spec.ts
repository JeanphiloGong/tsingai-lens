import { afterEach, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import OperationPermissions from './OperationPermissions.svelte';

afterEach(() => vi.unstubAllGlobals());

it('saves exact scoped actions and revokes through the authenticated API', async () => {
	let permission = {
		mode: 'confirm',
		actions: [] as string[],
		expires_at: null as string | null,
		revision: 0
	};
	const writes: Record<string, unknown>[] = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (_url, options) => {
			if (options?.method === 'PUT') {
				const input = JSON.parse(options.body);
				writes.push(input);
				permission = {
					mode: input.mode,
					actions: input.actions,
					expires_at: input.expires_at,
					revision: permission.revision + 1
				};
			}
			return new Response(JSON.stringify(permission), {
				status: 200,
				headers: { 'Content-Type': 'application/json' }
			});
		})
	);
	const screen = render(OperationPermissions, { sessionId: 'session-1' });
	await expect.poll(() => screen.container.querySelector('select')).not.toBeNull();
	(screen.container.querySelector('details') as HTMLDetailsElement).open = true;
	const select = screen.container.querySelector('select') as HTMLSelectElement;
	select.value = 'auto';
	select.dispatchEvent(new Event('change', { bubbles: true }));
	await expect
		.poll(() => screen.container.querySelectorAll('input[type=checkbox]').length)
		.toBe(12);
	await expect
		.element(screen.getByText('Select at least one action to enable automatic execution.'))
		.toBeVisible();
	expect((screen.container.querySelector('button') as HTMLButtonElement).disabled).toBe(true);
	(
		screen.container.querySelector(
			'input[type=checkbox][value="create_evidence_version"]'
		) as HTMLInputElement
	).click();
	await expect
		.poll(() => (screen.container.querySelector('button') as HTMLButtonElement).disabled)
		.toBe(false);
	(screen.container.querySelector('button') as HTMLButtonElement).click();
	await expect.poll(() => writes.length).toBe(1);
	expect(writes[0].actions).toEqual(['create_evidence_version']);
	expect(writes[0].expires_at).toBeNull();
	expect(writes[0].expected_revision).toBe(0);
	await expect.poll(() => screen.container.querySelectorAll('button').length).toBe(2);
	(screen.container.querySelectorAll('button')[1] as HTMLButtonElement).click();
	await expect.poll(() => writes.length).toBe(2);
	expect(writes[1]).toMatchObject({
		mode: 'confirm',
		actions: [],
		expires_at: null,
		expected_revision: 1
	});
});

it('restores an existing automatic grant duration and can authorize every write action', async () => {
	const expiresAt = new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString();
	let permission = {
		mode: 'auto' as const,
		actions: ['create_evidence_version'],
		expires_at: expiresAt,
		revision: 3
	};
	const writes: Record<string, unknown>[] = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (_url, options) => {
			if (options?.method === 'PUT') {
				const input = JSON.parse(options.body);
				writes.push(input);
				permission = {
					mode: input.mode,
					actions: input.actions,
					expires_at: input.expires_at,
					revision: permission.revision + 1
				};
			}
			return new Response(JSON.stringify(permission), {
				status: 200,
				headers: { 'Content-Type': 'application/json' }
			});
		})
	);
	const screen = render(OperationPermissions, { sessionId: 'session-1' });
	await expect.poll(() => screen.container.querySelector('select')).not.toBeNull();
	(screen.container.querySelector('details') as HTMLDetailsElement).open = true;
	await expect
		.poll(() => (screen.container.querySelector('input[type=number]') as HTMLInputElement)?.value)
		.toBe('6');
	const all = screen.container.querySelector('input[type=checkbox]') as HTMLInputElement;
	all.click();
	await expect
		.poll(() => screen.container.querySelectorAll('input[type=checkbox]:checked').length)
		.toBe(12);
	(screen.container.querySelector('button') as HTMLButtonElement).click();
	await expect.poll(() => writes.length).toBe(1);
	expect(writes[0].actions).toHaveLength(11);
	expect(writes[0].expires_at).toBe(expiresAt);
});

it('renews an expired automatic grant instead of resubmitting its past expiry', async () => {
	const expiredAt = new Date(Date.now() - 60 * 60 * 1000).toISOString();
	let permission = {
		mode: 'auto' as const,
		actions: ['create_evidence_version'],
		expires_at: expiredAt,
		revision: 4
	};
	const writes: Record<string, unknown>[] = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (_url, options) => {
			if (options?.method === 'PUT') {
				const input = JSON.parse(options.body);
				writes.push(input);
				permission = {
					mode: input.mode,
					actions: input.actions,
					expires_at: input.expires_at,
					revision: permission.revision + 1
				};
			}
			return new Response(JSON.stringify(permission), {
				status: 200,
				headers: { 'Content-Type': 'application/json' }
			});
		})
	);
	const screen = render(OperationPermissions, { sessionId: 'session-1' });
	await expect.poll(() => screen.container.querySelector('select')).not.toBeNull();
	(screen.container.querySelector('details') as HTMLDetailsElement).open = true;
	await expect
		.poll(() => (screen.container.querySelector('input[type=number]') as HTMLInputElement)?.value)
		.toBe('1');
	(screen.container.querySelector('button') as HTMLButtonElement).click();
	await expect.poll(() => writes.length).toBe(1);
	expect(writes[0].expires_at).not.toBe(expiredAt);
	expect(Date.parse(String(writes[0].expires_at))).toBeGreaterThan(Date.now());
});

it('uses the collection settings endpoint for defaults and sends the server expansion flag', async () => {
	let permission = {
		mode: 'confirm' as const,
		actions: [] as string[],
		expires_at: null as string | null,
		revision: 0
	};
	const calls: { url: string; body: Record<string, unknown> | null }[] = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url, options) => {
			const body = options?.body ? JSON.parse(String(options.body)) : null;
			calls.push({ url: String(url), body });
			if (options?.method === 'PUT') {
				permission = {
					mode: body.mode,
					actions: body.actions,
					expires_at: body.expires_at,
					revision: permission.revision + 1
				};
			}
			return new Response(JSON.stringify(permission), {
				status: 200,
				headers: { 'Content-Type': 'application/json' }
			});
		})
	);
	const screen = render(OperationPermissions, {
		collectionId: 'collection-1',
		scope: 'collection',
		standalone: true
	});
	await expect.poll(() => screen.container.querySelector('select')).not.toBeNull();
	const details = screen.container.querySelector('details') as HTMLDetailsElement;
	details.open = true;
	const select = screen.container.querySelector('select') as HTMLSelectElement;
	select.value = 'auto';
	select.dispatchEvent(new Event('change', { bubbles: true }));
	await expect
		.poll(() => screen.container.querySelectorAll('input[type=checkbox]').length)
		.toBe(12);
	(screen.container.querySelector('input[type=checkbox]') as HTMLInputElement).click();
	await expect
		.poll(() => screen.container.querySelectorAll('input[type=checkbox]:checked').length)
		.toBe(12);
	(screen.container.querySelector('button') as HTMLButtonElement).click();
	await expect.poll(() => calls.some((call) => call.body?.all_actions === true)).toBe(true);
	expect(calls[0].url).toContain('/collections/collection-1/agent-permissions');
	const save = calls.find((call) => call.body?.all_actions === true);
	expect(save?.body).toMatchObject({
		mode: 'auto',
		expected_revision: 0,
		all_actions: true
	});
});
