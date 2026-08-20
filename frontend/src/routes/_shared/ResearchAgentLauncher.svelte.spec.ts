import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const { collectionStore, fetchCollectionsMock, setCollections } = vi.hoisted(() => {
	const subscribers = new Set<(value: unknown[]) => void>();
	let items: unknown[] = [];

	return {
		collectionStore: {
			subscribe(run: (value: unknown[]) => void) {
				run(items);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		fetchCollectionsMock: vi.fn(),
		setCollections(nextItems: unknown[]) {
			items = nextItems;
			for (const run of subscribers) run(items);
		}
	};
});

vi.mock('./collections', () => ({
	collections: collectionStore,
	fetchCollections: fetchCollectionsMock
}));

const Launcher = (await import('./ResearchAgentLauncher.svelte')).default;

describe('ResearchAgentLauncher', () => {
	beforeEach(() => {
		setCollections([]);
		fetchCollectionsMock.mockReset();
		fetchCollectionsMock.mockImplementation(async () => {
			const items = [
				{
					id: 'col_123',
					collection_id: 'col_123',
					name: 'LPBF alloy papers',
					status: 'uploaded',
					paper_count: 10
				}
			];
			setCollections(items);
			return items;
		});
	});

	it('links directly to the current Collection Research Agent', async () => {
		render(Launcher, { collectionId: 'col_123' });

		await expect
			.element(browserPage.getByRole('link', { name: 'Research Agent' }))
			.toHaveAttribute('href', '/collections/col_123/assistant');
		expect(fetchCollectionsMock).not.toHaveBeenCalled();
	});

	it('asks for a research workspace before opening a global conversation', async () => {
		render(Launcher);

		await browserPage.getByRole('button', { name: 'Research Agent' }).click();

		await expect
			.element(browserPage.getByRole('dialog', { name: 'Choose a research workspace' }))
			.toBeVisible();
		await expect
			.element(browserPage.getByRole('link', { name: /LPBF alloy papers/ }))
			.toHaveAttribute('href', '/collections/col_123/assistant');
		expect(fetchCollectionsMock).toHaveBeenCalledOnce();
	});
});
