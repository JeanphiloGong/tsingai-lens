import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type MaterialsPageState = {
	params: {
		id: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: MaterialsPageState) => void>();
	let current: MaterialsPageState = {
		params: { id: 'col_123' },
		url: new URL('http://localhost/collections/col_123/materials')
	};

	return {
		pageStore: {
			subscribe(run: (value: MaterialsPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: MaterialsPageState) {
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

describe('collections/[id]/materials/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/materials')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/materials') {
				return jsonResponse({
					items: [
						{
							material_id: 'mat_316l',
							canonical_name: '316L stainless steel',
							aliases: ['316L', 'SS316L'],
							paper_count: 2,
							sample_count: 6,
							process_families: ['LPBF'],
							measured_properties: ['density', 'hardness'],
							comparison_count: 3,
							evidence_coverage: 0.75,
							state: 'ready'
						}
					]
				});
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});
	});

	it('renders material summaries from the material endpoint', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Materials' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: '316L stainless steel' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Aliases: 316L, SS316L')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open material profile' }))
			.toBeInTheDocument();
		expect(
			fetchMock.mock.calls.map(([input]) => requestPath(input as string | URL | Request))
		).toEqual(['/api/v1/collections/col_123/materials']);
	});
});
