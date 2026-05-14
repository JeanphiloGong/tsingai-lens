import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type ObjectivesPageState = {
	params: {
		id: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: ObjectivesPageState) => void>();
	let current: ObjectivesPageState = {
		params: { id: 'col_4c54ffe568ec' },
		url: new URL('http://localhost/collections/col_4c54ffe568ec/objectives')
	};

	return {
		pageStore: {
			subscribe(run: (value: ObjectivesPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: ObjectivesPageState) {
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

describe('collections/[id]/objectives/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_4c54ffe568ec' },
			url: new URL('http://localhost/collections/col_4c54ffe568ec/objectives')
		});
		fetchMock.mockReset();
	});

	it('treats not-ready objectives as a pending workflow state', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_4c54ffe568ec/objectives') {
				return jsonResponse(
					{
						code: 'research_objectives_not_ready',
						message:
							'The collection does not have research objectives yet. Finish processing first.',
						collection_id: 'col_4c54ffe568ec'
					},
					409,
					'Conflict'
				);
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Research objectives are pending' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Finish collection processing before reviewing objectives.'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open collection overview' }))
			.toHaveAttribute('href', '/collections/col_4c54ffe568ec');
		await expect.element(browserPage.getByText(/409 Conflict/)).not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText(/research_objectives_not_ready/))
			.not.toBeInTheDocument();
	});
});
