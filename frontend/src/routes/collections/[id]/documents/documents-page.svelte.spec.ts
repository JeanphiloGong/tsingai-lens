import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type DocumentsPageState = { params: { id: string }; url: URL };

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: DocumentsPageState) => void>();
	let current: DocumentsPageState = {
		params: { id: 'col_123' },
		url: new URL('http://localhost/collections/col_123/documents')
	};
	return {
		pageStore: {
			subscribe(run: (value: DocumentsPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: DocumentsPageState) {
			current = next;
			for (const run of subscribers) run(next);
		},
		fetchMock: vi.fn()
	};
});

vi.mock('$app/stores', () => ({ page: pageStore }));
vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

function jsonResponse(body: unknown, status = 200, statusText = 'OK') {
	return new Response(JSON.stringify(body), {
		status,
		statusText,
		headers: { 'Content-Type': 'application/json' }
	});
}

function requestPath(input: string | URL | Request) {
	const rawUrl =
		typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
	return new URL(rawUrl, 'http://localhost').pathname;
}

describe('collections/[id]/documents/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/documents')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);
			if (path === '/api/v1/collections/col_123/documents/profiles') {
				return jsonResponse({
					collection_id: 'col_123',
					total: 2,
					count: 2,
					summary: {
						total_documents: 2,
						doc_type_counts: { experimental: 1, review: 1 },
						warnings: []
					},
					items: [
						{
							document_id: 'doc_1',
							collection_id: 'col_123',
							title: 'Paper A',
							source_filename: 'paper-a.pdf',
							doc_type: 'experimental',
							parsing_warnings: [],
							confidence: 0.91,
							page_count: 12,
							processing_status: 'completed'
						},
						{
							document_id: 'abcdef1234567890abcdef1234567890',
							collection_id: 'col_123',
							title: null,
							source_filename: 'review.pdf',
							doc_type: 'review',
							parsing_warnings: ['Missing publication year'],
							confidence: 0.7,
							page_count: 8,
							processing_status: 'completed'
						}
					]
				});
			}
			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});
	});

	it('lists parsed papers directly from document profiles', async () => {
		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Papers' })).toBeInTheDocument();
		await expect.element(browserPage.getByText('Paper A')).toBeInTheDocument();
		await expect.element(browserPage.getByText('paper-a.pdf')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Experimental')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Missing publication year')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open paper' }).first())
			.toHaveAttribute('href', '/collections/col_123/documents/doc_1');
		expect(
			fetchMock.mock.calls.map(([input]) => requestPath(input as string | URL | Request))
		).toEqual(['/api/v1/collections/col_123/documents/profiles']);
	});

	it('uses a short display identifier when title and filename are unavailable', async () => {
		fetchMock.mockImplementation(async () =>
			jsonResponse({
				collection_id: 'col_123',
				total: 1,
				count: 1,
				summary: { total_documents: 1, doc_type_counts: {}, warnings: [] },
				items: [
					{
						document_id: 'abcdef1234567890abcdef1234567890',
						collection_id: 'col_123',
						title: null,
						source_filename: null,
						doc_type: 'uncertain',
						parsing_warnings: [],
						confidence: null,
						processing_status: 'completed'
					}
				]
			})
		);

		render(Page);

		await expect.element(browserPage.getByText('Paper 1')).toBeInTheDocument();
		await expect.element(browserPage.getByText('ID: abcdef123456')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('abcdef1234567890abcdef1234567890'))
			.not.toBeInTheDocument();
	});
});
