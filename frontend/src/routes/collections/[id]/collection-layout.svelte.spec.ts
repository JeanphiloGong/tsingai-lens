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
	fetchCollectionsMock,
	fetchWorkspaceMock
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
			fetchCollectionsMock: vi.fn(),
			fetchWorkspaceMock: vi.fn()
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
		fetchWorkspaceOverview: fetchWorkspaceMock
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
		fetchWorkspaceMock.mockReset();
		fetchCollectionMock.mockResolvedValue(null);
		fetchCollectionsMock.mockResolvedValue(null);
		fetchWorkspaceMock.mockRejectedValue(new Error('workspace unavailable'));
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

	it('keeps published objective routes open when a later build failed', async () => {
		setCollectionStatus('failed');
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/objectives/obj_1')
		});
		fetchWorkspaceMock.mockResolvedValue({
			collection: { collection_id: 'col_123', name: 'Battery papers', status: 'partial_success' },
			file_count: 2,
			workflow: {
				documents: 'ready',
				results: 'not_started',
				evidence: 'not_started',
				comparisons: 'not_started',
				graph: 'not_started'
			},
			artifacts: { documents_ready: true, document_profiles_ready: true },
			document_summary: { total_documents: 2 },
			warnings: [],
			latest_task: { status: 'partial_success' },
			links: {}
		});

		render(Layout);

		await vi.waitFor(() => {
			expect(document.querySelector('.collection-locked-surface')).toBeNull();
		});
		await expect
			.element(browserPage.getByRole('link', { name: 'Objectives' }))
			.not.toHaveAttribute('aria-disabled');
	});

	it('shows a newly queued build while the loaded workspace is still stale', async () => {
		setCollectionStatus('processing');
		fetchWorkspaceMock.mockResolvedValue({
			collection: { collection_id: 'col_123', name: 'Battery papers', status: 'uploaded' },
			file_count: 2,
			workflow: {
				documents: 'not_started',
				results: 'not_started',
				evidence: 'not_started',
				comparisons: 'not_started',
				graph: 'not_started'
			},
			artifacts: {},
			document_summary: { total_documents: 2 },
			warnings: [],
			latest_task: null,
			links: {}
		});

		render(Layout);

		await vi.waitFor(() => {
			expect(document.querySelector('.collection-meta-row')?.textContent).toContain('Processing');
		});
		await expect
			.element(browserPage.getByRole('link', { name: 'Objectives' }))
			.toHaveAttribute('aria-disabled', 'true');
	});

	it('shows a completed build while the loaded overview workspace is still stale', async () => {
		setCollectionStatus('ready');
		fetchWorkspaceMock.mockResolvedValue({
			collection: { collection_id: 'col_123', name: 'Battery papers', status: 'uploaded' },
			file_count: 2,
			workflow: {
				documents: 'not_started',
				results: 'not_started',
				evidence: 'not_started',
				comparisons: 'not_started',
				graph: 'not_started'
			},
			artifacts: {},
			document_summary: { total_documents: 2 },
			warnings: [],
			latest_task: null,
			links: {}
		});

		render(Layout);

		await vi.waitFor(() => {
			expect(document.querySelector('.collection-meta-row')?.textContent).toContain('Complete');
		});
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
