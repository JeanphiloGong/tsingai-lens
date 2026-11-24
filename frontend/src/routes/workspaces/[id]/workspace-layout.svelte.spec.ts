import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { language } from '../../_shared/i18n';

const { pageStore, workspaceStore, fetchWorkspaceMock, fetchWorkspacesMock } = vi.hoisted(
	() => ({
		pageStore: {
			subscribe(run: (value: { params: { id: string }; url: URL }) => void) {
				run({
					params: { id: 'col_123' },
					url: new URL('http://localhost/workspaces/col_123')
				});
				return () => undefined;
			}
		},
		workspaceStore: {
			subscribe(run: (value: unknown[]) => void) {
				run([
					{
						workspace_id: 'col_123',
						name: 'Battery papers',
						description: 'Current document workspace',
						status: 'uploaded',
						paper_count: 1,
						updated_at: '2026-08-27T00:00:00Z',
						documents: [{ document_id: 'doc_1', status: 'stored' }]
					}
				]);
				return () => undefined;
			}
		},
		fetchWorkspaceMock: vi.fn(),
		fetchWorkspacesMock: vi.fn()
	})
);

vi.mock('$app/stores', () => ({ page: pageStore }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/workspace/workspaces', () => ({
	workspaces: workspaceStore,
	deleteWorkspace: vi.fn(),
	fetchWorkspace: fetchWorkspaceMock,
	fetchWorkspaces: fetchWorkspacesMock
}));

const Layout = (await import('./+layout.svelte')).default;

describe('current workspace layout', () => {
	beforeEach(() => {
		language.set('en');
		fetchWorkspaceMock.mockResolvedValue(null);
		fetchWorkspacesMock.mockResolvedValue(null);
	});

	it('keeps research surfaces reachable while documents prepare independently', async () => {
		render(Layout);
		const navigation = browserPage.getByRole('navigation', { name: 'Workspace navigation' });

		await browserPage.getByText('More', { exact: true }).click();
		for (const name of ['Objectives', 'Evidence Map', 'Papers', 'AI Copilot']) {
			await expect
				.element(navigation.getByRole('link', { name }))
				.not.toHaveAttribute('aria-disabled');
		}
		await expect.element(browserPage.getByText('Stored')).toBeInTheDocument();
	});
});
