import { afterEach, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import OperationPermissions from './OperationPermissions.svelte';

afterEach(() => vi.unstubAllGlobals());

it('saves exact scoped actions and revokes through the authenticated API', async () => {
	let permission = { mode: 'confirm', actions: [] as string[], expires_at: null as string | null, revision: 0 };
	const writes: Record<string, unknown>[] = [];
	vi.stubGlobal('fetch', vi.fn(async (_url, options) => {
		if (options?.method === 'PUT') {
			const input = JSON.parse(options.body);
			writes.push(input);
			permission = { mode: input.mode, actions: input.actions, expires_at: input.expires_at, revision: permission.revision + 1 };
		}
		return new Response(JSON.stringify(permission), { status: 200, headers: { 'Content-Type': 'application/json' } });
	}));
	const screen = render(OperationPermissions, { sessionId: 'session-1' });
	await expect.poll(() => screen.container.querySelector('select')).not.toBeNull();
	(screen.container.querySelector('details') as HTMLDetailsElement).open = true;
	const select = screen.container.querySelector('select') as HTMLSelectElement;
	select.value = 'auto';
	select.dispatchEvent(new Event('change', { bubbles: true }));
	await expect.poll(() => screen.container.querySelectorAll('input[type=checkbox]').length).toBe(6);
	(screen.container.querySelector('input[type=checkbox]') as HTMLInputElement).click();
	await expect.poll(() => (screen.container.querySelector('button') as HTMLButtonElement).disabled).toBe(false);
	(screen.container.querySelector('button') as HTMLButtonElement).click();
	await expect.poll(() => writes.length).toBe(1);
	expect(writes[0].actions).toEqual(['create_evidence_version']);
	expect(writes[0].expected_revision).toBe(0);
	await expect.poll(() => screen.container.querySelectorAll('button').length).toBe(2);
	(screen.container.querySelectorAll('button')[1] as HTMLButtonElement).click();
	await expect.poll(() => writes.length).toBe(2);
	expect(writes[1]).toMatchObject({ mode: 'confirm', actions: [], expires_at: null, expected_revision: 1 });
});
