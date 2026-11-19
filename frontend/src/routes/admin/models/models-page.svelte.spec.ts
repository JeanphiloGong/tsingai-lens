import { page as browserPage } from 'vitest/browser';
import { beforeEach, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { authState } from '../../_shared/authState';
import { permissionState } from '../../_shared/permissions';
import { language } from '../../_shared/i18n';
const { pageStore, fetchMock } = vi.hoisted(() => ({
	pageStore: {
		subscribe(run: (value: { url: URL }) => void) {
			run({ url: new URL('http://localhost/admin/models?connection_id=lab-a') });
			return () => {};
		}
	},
	fetchMock: vi.fn()
}));
vi.mock('$app/stores', () => ({ page: pageStore }));
vi.mock('$app/navigation', () => ({ beforeNavigate: vi.fn(), goto: vi.fn() }));
const Page = (await import('./+page.svelte')).default;
const saved = {
	connection_id: 'lab-a',
	display_name: 'Laboratory',
	base_url: 'http://localhost/v1',
	model: 'chat',
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
};
beforeEach(() => {
	language.set('en');
	authState.set({
		status: 'authenticated',
		user: { user_id: 'operator', email: 'operator@example.test' }
	});
	permissionState.set({ status: 'ready', userId: 'operator', codes: ['models.manage'] });
	fetchMock.mockReset();
	fetchMock.mockImplementation(
		async (url: string) =>
			new Response(
				JSON.stringify({
					code: 200,
					message: 'success',
					data: url.includes('?')
						? { items: [saved], total: 1, limit: 50, offset: 0 }
						: url.endsWith('/api/v1/model-connections')
							? { items: [] }
							: saved,
					meta: null
				}),
				{ headers: { 'Content-Type': 'application/json' } }
			)
	);
	vi.stubGlobal('fetch', fetchMock);
});
it('clears secret input and content when the account loses its permission', async () => {
	const view = render(Page);
	await expect.element(browserPage.getByLabelText('New API key', { exact: true })).toBeVisible();
	await browserPage.getByLabelText('New API key', { exact: true }).fill('synthetic-draft');
	permissionState.set({ status: 'ready', userId: 'operator', codes: [] });
	await expect.element(browserPage.getByRole('alert')).toHaveTextContent('403');
	await expect
		.element(browserPage.getByLabelText('New API key', { exact: true }))
		.not.toBeInTheDocument();
	await view.unmount();
});
it('does not query model data before permission is known', async () => {
	permissionState.set({ status: 'loading', userId: 'operator', codes: [] });
	const view = render(Page);
	await expect.element(browserPage.getByRole('status')).toHaveTextContent('Loading permissions');
	expect(fetchMock).not.toHaveBeenCalled();
	await view.unmount();
});
