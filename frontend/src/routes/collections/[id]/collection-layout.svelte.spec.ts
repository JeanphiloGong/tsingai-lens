import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type CollectionLayoutPageState = {
	params: {
		id: string;
	};
	url: URL;
};

const {
	pageStore,
	setPage,
	collectionStore,
	setCollectionStatus,
	fetchCollectionMock,
	fetchCollectionsMock
} =
	vi.hoisted(() => {
		const pageSubscribers = new Set<(value: CollectionLayoutPageState) => void>();
		const collectionSubscribers = new Set<(value: unknown[]) => void>();
		let currentPage: CollectionLayoutPageState = {
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123')
		};
		const collectionItems = [
			{
				id: 'col_123',
				name: 'Battery papers',
				description: 'Objective-first collection',
				status: 'ready',
				paper_count: 2,
				updated_at: '2026-01-02T00:00:00Z'
			}
		];
		function emitCollections() {
			for (const run of collectionSubscribers) run(collectionItems);
		}

		return {
			pageStore: {
				subscribe(run: (value: CollectionLayoutPageState) => void) {
					run(currentPage);
					pageSubscribers.add(run);
					return () => pageSubscribers.delete(run);
				}
			},
			setPage(next: CollectionLayoutPageState) {
				currentPage = next;
				for (const run of pageSubscribers) run(next);
			},
			collectionStore: {
				subscribe(run: (value: unknown[]) => void) {
					run(collectionItems);
					collectionSubscribers.add(run);
					return () => collectionSubscribers.delete(run);
				}
			},
			setCollectionStatus(status: string) {
				collectionItems[0].status = status;
				emitCollections();
			},
			fetchCollectionMock: vi.fn(),
			fetchCollectionsMock: vi.fn()
		};
	});

vi.mock('$app/stores', () => ({
	page: pageStore
}));

vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));

vi.mock('../../_shared/collections', () => ({
	collections: collectionStore,
	deleteCollection: vi.fn(),
	fetchCollection: fetchCollectionMock,
	fetchCollections: fetchCollectionsMock
}));

vi.mock('../../_shared/workspace', async (importActual) => {
	const actual = await importActual<typeof import('../../_shared/workspace')>();

	return {
		...actual,
		fetchWorkspaceOverview: vi.fn(async () => {
			throw new Error('workspace unavailable');
		})
	};
});

const Layout = (await import('./+layout.svelte')).default;

describe('collections/[id]/+layout.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123')
		});
		setCollectionStatus('ready');
		fetchCollectionMock.mockReset();
		fetchCollectionsMock.mockReset();
		fetchCollectionMock.mockResolvedValue(null);
		fetchCollectionsMock.mockResolvedValue(null);
	});

	it('places the material dossier entry under the More menu', async () => {
		render(Layout);

		const nav = browserPage.getByRole('navigation', { name: 'Collection navigation' });

		await expect.element(nav.getByRole('link', { name: 'Objectives' })).toBeVisible();

		const primaryTabs = Array.from(document.querySelectorAll('.collection-tabs > a')).map((tab) =>
			tab.textContent?.trim()
		);
		expect(primaryTabs).not.toContain('Materials');
		expect(
			document.querySelector('.collection-tabs__menu a[href="/collections/col_123/materials"]')
		).not.toBeNull();

		await nav.getByText('More').click();

		await expect.element(nav.getByRole('link', { name: 'Materials' })).toBeVisible();
	});

	it('locks downstream navigation until the collection is processed', async () => {
		setCollectionStatus('uploaded');

		render(Layout);

		const nav = browserPage.getByRole('navigation', { name: 'Collection navigation' });
		const objectives = nav.getByRole('link', { name: 'Objectives' });

		await expect.element(objectives).toHaveAttribute('aria-disabled', 'true');
		expect(document.querySelector('a[href="/collections/col_123/objectives"]')?.className).toContain(
			'locked'
		);

		await nav.getByText('More').click();
		await expect.element(nav.getByRole('link', { name: 'Materials' })).toHaveAttribute(
			'aria-disabled',
			'true'
		);
	});

	it('shows a locked surface for direct downstream routes before processing', async () => {
		setCollectionStatus('uploaded');
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/objectives')
		});

		render(Layout);

		await expect.element(browserPage.getByText('Processing required')).toBeVisible();
		await expect.element(browserPage.getByRole('link', { name: 'Back to workspace' })).toHaveAttribute(
			'href',
			'/collections/col_123'
		);
	});

	it('marks More active on material routes', async () => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/materials')
		});

		render(Layout);

		const activeMore = document.querySelector('.collection-tabs__more.active summary');
		const activeMaterialsLink = document.querySelector(
			'a[href="/collections/col_123/materials"].active'
		);

		expect(activeMore?.textContent?.trim()).toBe('More');
		expect(activeMaterialsLink).not.toBeNull();
	});
});
