import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const { pageStore, collectionStore, fetchCollectionMock, fetchCollectionsMock } = vi.hoisted(
	() => ({
		pageStore: {
			subscribe(run: (value: { params: { id: string }; url: URL }) => void) {
				run({
					params: { id: 'col_123' },
					url: new URL('http://localhost/collections/col_123')
				});
				return () => undefined;
			}
		},
		collectionStore: {
			subscribe(run: (value: unknown[]) => void) {
				run([
					{
						id: 'col_123',
						name: 'Battery papers',
						description: 'Current document collection',
						status: 'uploaded',
						paper_count: 1,
						updated_at: '2026-08-27T00:00:00Z',
						documents: [{ document_id: 'doc_1', status: 'stored' }]
					}
				]);
				return () => undefined;
			}
		},
		fetchCollectionMock: vi.fn(),
		fetchCollectionsMock: vi.fn()
	})
);

vi.mock('$app/stores', () => ({ page: pageStore }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('../../_shared/collections', () => ({
	collections: collectionStore,
	deleteCollection: vi.fn(),
	fetchCollection: fetchCollectionMock,
	fetchCollections: fetchCollectionsMock
}));

const Layout = (await import('./+layout.svelte')).default;

describe('current collection layout', () => {
	beforeEach(() => {
		fetchCollectionMock.mockResolvedValue(null);
		fetchCollectionsMock.mockResolvedValue(null);
	});

	it('keeps research surfaces reachable while documents prepare independently', async () => {
		render(Layout);
		const navigation = browserPage.getByRole('navigation', { name: 'Collection navigation' });

		for (const name of ['Objectives', 'Comparisons', 'Evidence Map', 'Papers', 'AI Copilot']) {
			await expect
				.element(navigation.getByRole('link', { name }))
				.not.toHaveAttribute('aria-disabled');
		}
		await expect.element(browserPage.getByText('Stored')).toBeInTheDocument();
	});
});
