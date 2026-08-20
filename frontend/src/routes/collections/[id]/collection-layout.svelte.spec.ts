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
} = vi.hoisted(() => {
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
		setCollectionStatus(status: string, updatedAt = collectionItems[0].updated_at) {
			collectionItems[0].status = status;
			collectionItems[0].updated_at = updatedAt;
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
		setCollectionStatus('ready', '2026-01-02T00:00:00Z');
		fetchCollectionMock.mockReset();
		fetchCollectionsMock.mockReset();
		fetchWorkspaceMock.mockReset();
		fetchCollectionMock.mockResolvedValue(null);
		fetchCollectionsMock.mockResolvedValue(null);
		fetchWorkspaceMock.mockRejectedValue(new Error('workspace unavailable'));
	});

	it('shows only the maintained collection workflow in primary navigation', async () => {
		render(Layout);

		const nav = browserPage.getByRole('navigation', { name: 'Collection navigation' });

		const primaryTabs = Array.from(document.querySelectorAll('.collection-tabs > a')).map((tab) =>
			tab.textContent?.trim()
		);
		expect(primaryTabs).toEqual([
			'Overview',
			'Objectives',
			'Comparisons',
			'Evidence Map',
			'Papers',
			'AI Copilot'
		]);
		for (const retiredLabel of ['More', 'Materials', 'Evidence Cards', 'Extracted Facts']) {
			expect(nav.element().textContent).not.toContain(retiredLabel);
		}
		expect(document.querySelector('button[aria-label="Edit collection name"]')).toBeNull();
		expect(document.querySelector('button[aria-label="More actions"]')).toBeNull();
	});

	it('locks downstream navigation until the collection is processed', async () => {
		setCollectionStatus('uploaded');

		render(Layout);

		const nav = browserPage.getByRole('navigation', { name: 'Collection navigation' });
		const objectives = nav.getByRole('link', { name: 'Objectives' });
		const comparisons = nav.getByRole('link', { name: 'Comparisons' });
		const researchAgent = nav.getByRole('link', { name: 'AI Copilot' });

		await expect.element(objectives).toHaveAttribute('aria-disabled', 'true');
		await expect.element(comparisons).toHaveAttribute('aria-disabled', 'true');
		await expect.element(researchAgent).not.toHaveAttribute('aria-disabled');
		await expect.element(researchAgent).toHaveAttribute('href', '/collections/col_123/assistant');
		expect(
			document.querySelector('a[href="/collections/col_123/objectives"]')?.className
		).toContain('locked');
	});

	it('keeps the Research Agent route open before objective discovery is ready', async () => {
		setCollectionStatus('uploaded');
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/assistant')
		});

		render(Layout);

		expect(document.querySelector('.collection-locked-surface')).toBeNull();
	});

	it('shows a locked surface for direct downstream routes before processing', async () => {
		setCollectionStatus('uploaded');
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/objectives')
		});

		render(Layout);

		await expect.element(browserPage.getByText('Processing required')).toBeVisible();
		await expect
			.element(browserPage.getByRole('link', { name: 'Back to workspace' }))
			.toHaveAttribute('href', '/collections/col_123');
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
				objectives: 'ready'
			},
			artifacts: { document_profiles_ready: true, objective_candidates_ready: true },
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
				objectives: 'not_started'
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

	it('uses the loaded workspace instead of a stale collection status', async () => {
		setCollectionStatus('ready');
		fetchWorkspaceMock.mockResolvedValue({
			collection: { collection_id: 'col_123', name: 'Battery papers', status: 'uploaded' },
			file_count: 2,
			workflow: {
				documents: 'not_started',
				objectives: 'not_started'
			},
			artifacts: {},
			document_summary: { total_documents: 2 },
			warnings: [],
			latest_task: null,
			links: {}
		});

		render(Layout);

		await vi.waitFor(() => {
			expect(document.querySelector('.collection-meta-row')?.textContent).toContain(
				'Ready to process'
			);
		});
	});

	it('uses a newer workspace-derived collection snapshot after processing finishes', async () => {
		setCollectionStatus('uploaded', '2026-01-02T00:00:00Z');
		fetchWorkspaceMock.mockResolvedValue({
			collection: {
				collection_id: 'col_123',
				name: 'Battery papers',
				status: 'uploaded',
				updated_at: '2026-01-02T00:00:00Z'
			},
			file_count: 2,
			workflow: {
				documents: { status: 'not_started', detail: 'Document profiling is pending.' },
				objectives: { status: 'not_started', detail: 'Objective discovery is pending.' }
			},
			artifacts: { updated_at: '2026-01-02T00:00:00Z' },
			document_summary: { total_documents: 2 },
			warnings: [],
			latest_task: null,
			links: {}
		});

		render(Layout);

		await vi.waitFor(() => {
			expect(document.querySelector('.collection-meta-row')?.textContent).toContain(
				'Ready to process'
			);
		});

		setCollectionStatus('ready', '2026-01-02T00:00:03Z');

		await vi.waitFor(() => {
			expect(document.querySelector('.collection-meta-row')?.textContent).toContain('Complete');
		});
	});

	it('marks Comparisons active on the published findings route', async () => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/comparisons')
		});

		render(Layout);

		expect(
			document.querySelector('a[href="/collections/col_123/comparisons"].active')
		).not.toBeNull();
	});
});
