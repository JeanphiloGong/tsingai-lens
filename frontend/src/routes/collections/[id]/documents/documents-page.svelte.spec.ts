import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type DocumentsPageState = {
	params: {
		id: string;
	};
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

vi.mock('$app/stores', () => ({
	page: pageStore
}));

vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

function jsonResponse(body: unknown, status = 200, statusText = 'OK') {
	return new Response(JSON.stringify(body), {
		status,
		statusText,
		headers: {
			'Content-Type': 'application/json'
		}
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

			if (path === '/api/v1/collections/col_123/research-view') {
				return jsonResponse({
					collection_id: 'col_123',
					state: 'ready',
					paper_coverage: [
						{
							document_id: 'doc_1',
							title: 'Paper A',
							state: 'ready',
							sample_count: 2,
							process_param_count: 3,
							measurement_count: 4,
							condition_count: 1,
							evidence_count: 5,
							issue_count: 0
						}
					]
				});
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});
	});

	it('renders paper coverage directly from the research view endpoint', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Paper coverage table' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Paper A')).toBeInTheDocument();
		await expect.element(browserPage.getByText('doc_1')).toBeInTheDocument();
		expect(
			fetchMock.mock.calls.map(([input]) => requestPath(input as string | URL | Request))
		).toEqual(['/api/v1/collections/col_123/research-view']);
	});
});
