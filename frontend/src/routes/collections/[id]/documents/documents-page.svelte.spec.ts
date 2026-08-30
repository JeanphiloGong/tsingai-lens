import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type DocumentsPageState = {
	params: { id: string };
	url: URL;
};

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

function jsonResponse(body: unknown) {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { 'Content-Type': 'application/json' }
	});
}

function profile(index: number) {
	return {
		document_id: `doc-${index}`,
		collection_id: 'col_123',
		title: `Paper ${index}`,
		source_filename: `paper-${index}.pdf`,
		doc_type: 'experimental',
		parsing_warnings: [],
		confidence: 0.9,
		page_count: 10
	};
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
	});

	it('keeps parsed-paper identity, warnings, and Source navigation visible', async () => {
		fetchMock.mockResolvedValue(
			jsonResponse({
				collection_id: 'col_123',
				total: 2,
				count: 2,
				summary: {
					total_documents: 2,
					by_doc_type: { experimental: 1, review: 1 },
					warnings: []
				},
				items: [
					{
						...profile(1),
						document_id: 'doc_1',
						title: 'Paper A',
						source_filename: 'paper-a.pdf',
						confidence: 0.91,
						page_count: 12
					},
					{
						...profile(2),
						document_id: 'abcdef1234567890abcdef1234567890',
						title: null,
						source_filename: 'review.pdf',
						doc_type: 'review',
						parsing_warnings: ['Missing publication year'],
						confidence: 0.7,
						page_count: 8
					}
				]
			})
		);

		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Papers' })).toBeInTheDocument();
		await expect.element(browserPage.getByText('Paper A')).toBeInTheDocument();
		await expect.element(browserPage.getByText('paper-a.pdf')).toBeInTheDocument();
		expect(document.querySelector('.paper-type')?.textContent).toBe('Experimental');
		await expect.element(browserPage.getByText('Missing publication year')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open paper' }).first())
			.toHaveAttribute('href', '/collections/col_123/documents/doc_1');
		expect(requestPath(fetchMock.mock.calls[0]?.[0] as string | URL | Request)).toBe(
			'/api/v1/collections/col_123/documents/profiles'
		);
	});

	it('uses a neutral fallback without exposing internal identifiers', async () => {
		fetchMock.mockResolvedValue(
			jsonResponse({
				collection_id: 'col_123',
				total: 1,
				count: 1,
				summary: { total_documents: 1, by_doc_type: {}, warnings: [] },
				items: [
					{
						...profile(1),
						document_id: 'abcdef1234567890abcdef1234567890',
						title: null,
						source_filename: null,
						doc_type: 'uncertain',
						confidence: null
					}
				]
			})
		);

		render(Page);

		await expect.element(browserPage.getByText('Paper 1')).toBeInTheDocument();
		await expect.element(browserPage.getByText('ID: abcdef123456')).not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('abcdef1234567890abcdef1234567890'))
			.not.toBeInTheDocument();
	});

	it('shows the complete total while rendering one bounded page', async () => {
		fetchMock.mockResolvedValue(
			jsonResponse({
				collection_id: 'col_123',
				total: 131,
				count: 25,
				summary: { total_documents: 131, by_doc_type: { experimental: 131 }, warnings: [] },
				items: Array.from({ length: 25 }, (_, index) => profile(index + 1))
			})
		);

		render(Page);

		await expect.element(browserPage.getByText('131 paper(s)')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Papers 1–25 of 131').first()).toBeInTheDocument();
		expect(document.querySelectorAll('[data-paper-row]')).toHaveLength(25);
		expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
			'/api/v1/collections/col_123/documents/profiles?offset=0&limit=25'
		);
	});

	it('requests the next page with the correct offset', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const url = new URL(String(input), 'http://localhost');
			const offset = Number(url.searchParams.get('offset') ?? 0);
			return jsonResponse({
				collection_id: 'col_123',
				total: 131,
				count: 25,
				summary: { total_documents: 131, by_doc_type: {}, warnings: [] },
				items: Array.from({ length: 25 }, (_, index) => profile(offset + index + 1))
			});
		});

		render(Page);
		await browserPage.getByRole('button', { name: 'Next' }).click();

		await vi.waitFor(() => {
			expect(
				fetchMock.mock.calls.some(([input]) => String(input).includes('offset=25&limit=25'))
			).toBe(true);
		});
		await expect.element(browserPage.getByText('Papers 26–50 of 131').first()).toBeInTheDocument();
	});

	it('searches the collection and resets to the first page', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const url = new URL(String(input), 'http://localhost');
			const query = url.searchParams.get('query');
			return jsonResponse({
				collection_id: 'col_123',
				total: query ? 1 : 131,
				count: query ? 1 : 25,
				summary: { total_documents: 131, by_doc_type: {}, warnings: [] },
				items: query ? [{ ...profile(88), title: 'Laser porosity study' }] : [profile(1)]
			});
		});

		render(Page);
		await browserPage.getByLabelText('Search papers').fill('  laser porosity  ');
		await browserPage.getByRole('button', { name: 'Search' }).click();

		await vi.waitFor(() => {
			expect(
				fetchMock.mock.calls.some(([input]) =>
					String(input).includes('offset=0&limit=25&query=laser+porosity')
				)
			).toBe(true);
		});
		await expect.element(browserPage.getByText('Laser porosity study')).toBeInTheDocument();
		await expect.element(browserPage.getByText('1 matching paper(s)')).toBeInTheDocument();
	});
});
