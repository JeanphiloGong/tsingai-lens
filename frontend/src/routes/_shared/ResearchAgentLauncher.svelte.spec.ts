import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { language } from './i18n';

const { workspaceStore, fetchWorkspacesMock, setWorkspaces } = vi.hoisted(() => {
	const subscribers = new Set<(value: unknown[]) => void>();
	let items: unknown[] = [];

	return {
		workspaceStore: {
			subscribe(run: (value: unknown[]) => void) {
				run(items);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		fetchWorkspacesMock: vi.fn(),
		setWorkspaces(nextItems: unknown[]) {
			items = nextItems;
			for (const run of subscribers) run(items);
		}
	};
});

vi.mock('$lib/workspace/workspaces', () => ({
	workspaces: workspaceStore,
	fetchWorkspaces: fetchWorkspacesMock
}));

const Launcher = (await import('./ResearchAgentLauncher.svelte')).default;

describe('ResearchAgentLauncher', () => {
	beforeEach(() => {
		language.set('en');
		setWorkspaces([]);
		fetchWorkspacesMock.mockReset();
		fetchWorkspacesMock.mockImplementation(async () => {
			const items = [
				{
					id: 'col_123',
					workspace_id: 'col_123',
					name: 'LPBF alloy papers',
					status: 'uploaded',
					paper_count: 10
				}
			];
			setWorkspaces(items);
			return items;
		});
	});

	it('links directly to the current Workspace Research Agent', async () => {
		render(Launcher, { workspaceId: 'col_123' });

		await expect
			.element(browserPage.getByRole('link', { name: 'Research Agent' }))
			.toHaveAttribute('href', '/workspaces/col_123/assistant');
		expect(fetchWorkspacesMock).not.toHaveBeenCalled();
	});

	it('asks for a research workspace before opening a global conversation', async () => {
		render(Launcher);

		await browserPage.getByRole('button', { name: 'Research Agent' }).click();

		await expect
			.element(browserPage.getByRole('dialog', { name: 'Choose a research workspace' }))
			.toBeVisible();
		await expect
			.element(browserPage.getByRole('link', { name: /LPBF alloy papers/ }))
			.toHaveAttribute('href', '/workspaces/col_123/assistant');
		expect(fetchWorkspacesMock).toHaveBeenCalledOnce();
	});
});
