import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type DocumentDetailPageState = {
	params: {
		id: string;
		document_id: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: DocumentDetailPageState) => void>();
	let current: DocumentDetailPageState = {
		params: { id: 'col_123', document_id: 'doc_1' },
		url: new URL('http://localhost/collections/col_123/documents/doc_1')
	};

		return {
			pageStore: {
				subscribe(run: (value: DocumentDetailPageState) => void) {
					run(current);
					subscribers.add(run);
					return () => subscribers.delete(run);
				}
			},
			setPage(next: DocumentDetailPageState) {
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

describe('collections/[id]/documents/[document_id]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', document_id: 'doc_1' },
			url: new URL('http://localhost/collections/col_123/documents/doc_1')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const rawUrl =
				typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
			const url = new URL(rawUrl, 'http://localhost');

			if (url.pathname === '/api/v1/collections/col_123/documents/doc_1/content') {
				return jsonResponse({
					collection_id: 'col_123',
					document_id: 'doc_1',
					title: 'Paper A',
					source_filename: 'paper-a.pdf',
					page_count: 5,
					content_text: 'content',
					sections: [
						{
							section_id: 'results',
							title: 'Results',
							section_type: 'results',
							text: 'Conductivity improved to 12 mS/cm.',
							page: 4,
							order: 1,
							start_offset: 0,
							end_offset: 33,
							text_unit_ids: []
						}
					],
					warnings: []
				});
			}
			if (url.pathname === '/api/v1/collections/col_123/results') {
				return jsonResponse({
					collection_id: 'col_123',
					total: 1,
					count: 1,
					items: [
						{
							result_id: 'cres_1',
							document_id: 'doc_1',
							document_title: 'Paper A',
							material_label: 'oxide cathode',
							variant_label: 'Sample A',
							property: 'conductivity',
							value: 12,
							unit: 'mS/cm',
							summary: '12 mS/cm',
							baseline: 'as-prepared',
							test_condition: 'EIS',
							process: '700 C',
							traceability_status: 'direct',
							comparability_status: 'comparable',
							requires_expert_review: false
						}
					]
				});
			}

			return jsonResponse({ detail: 'collection not found: col_123' }, 404, 'Not Found');
		});
	});

	it('renders related results that drill back into result detail', async () => {
		render(Page);

		const sectionHeading = browserPage.getByRole('heading', { name: 'Results from this document' });
		await expect.element(sectionHeading).toBeInTheDocument();

		const resultLink = browserPage.getByRole('link', { name: 'oxide cathode · conductivity' });
		await expect.element(resultLink).toHaveAttribute('href', '/collections/col_123/results/cres_1');
	});
});
