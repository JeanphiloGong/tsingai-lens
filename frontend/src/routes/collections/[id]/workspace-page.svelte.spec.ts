import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const { pageStore, fetchMock } = vi.hoisted(() => ({
	pageStore: {
		subscribe(run: (value: { params: { id: string }; url: URL }) => void) {
			run({
				params: { id: 'col_123' },
				url: new URL('http://localhost/collections/col_123')
			});
			return () => undefined;
		}
	},
	fetchMock: vi.fn()
}));

vi.mock('$app/stores', () => ({ page: pageStore }));
vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

function jsonResponse(body: unknown) {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { 'Content-Type': 'application/json' }
	});
}

const readyDocument = {
	document_id: 'doc_ready',
	original_filename: 'ready-paper.pdf',
	stored_filename: 'ready.pdf',
	storage_key: 'col_123/ready.pdf',
	sha256: 'a'.repeat(64),
	media_type: 'application/pdf',
	status: 'ready',
	size_bytes: 1024,
	created_at: '2026-08-27T00:00:00Z',
	updated_at: '2026-08-27T00:01:00Z',
	parser_version: 'source-runtime.v1',
	document_analysis_version: 'paper-map.v1',
	preparation_fingerprint: 'fingerprint-ready'
};

const storedDocument = {
	...readyDocument,
	document_id: 'doc_stored',
	original_filename: 'stored-paper.pdf',
	status: 'stored',
	preparation_fingerprint: null
};

function task(overrides: Record<string, unknown> = {}) {
	return {
		task_id: 'task_1',
		collection_id: 'col_123',
		document_id: 'doc_stored',
		task_type: 'document_preparation',
		mode: 'standard',
		input_fingerprint: 'fingerprint-stored',
		status: 'running',
		current_stage: 'source_parsing',
		progress_percent: 10,
		progress_detail: { phase: 'source_parsing', message: 'Parsing paper.' },
		errors: [],
		warnings: [],
		created_at: '2026-08-27T00:00:00Z',
		updated_at: '2026-08-27T00:00:01Z',
		started_at: '2026-08-27T00:00:01Z',
		finished_at: null,
		...overrides
	};
}

describe('current collection document workflow', () => {
	beforeEach(() => {
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
			const url = new URL(raw, 'http://localhost');
			const method = input instanceof Request ? input.method : (init?.method ?? 'GET');
			if (url.pathname.endsWith('/documents') && method === 'GET') {
				return jsonResponse({ items: [readyDocument, storedDocument] });
			}
			if (url.pathname.endsWith('/tasks') && method === 'GET') {
				return jsonResponse({ collection_id: 'col_123', count: 1, items: [task()] });
			}
			if (url.pathname.endsWith('/objectives') && method === 'GET') {
				return jsonResponse({ collection_id: 'col_123', objectives: [] });
			}
			if (url.pathname.includes('/preparation') && method === 'POST') {
				return jsonResponse(task({ status: 'queued' }));
			}
			if (url.pathname.endsWith('/objective-discovery') && method === 'POST') {
				return jsonResponse({
					collection_id: 'col_123',
					document_inputs: [
						{ document_id: 'doc_ready', preparation_fingerprint: 'fingerprint-ready' }
					],
					objectives: []
				});
			}
			throw new Error(`unexpected request: ${method} ${url.pathname}`);
		});
	});

	it('keeps upload available while another document is preparing', async () => {
		render(Page);

		await expect.element(browserPage.getByText('Parsing paper.')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Upload documents' }))
			.not.toBeDisabled();
	});

	it('discovers objectives from exactly the checked ready documents', async () => {
		render(Page);
		await browserPage.getByLabelText('Select paper for research scope').first().click();
		await browserPage.getByRole('button', { name: 'Discover objectives from 1' }).click();

		const discoveryCall = fetchMock.mock.calls.find(([input]) =>
			String(input).includes('/objective-discovery')
		);
		expect(discoveryCall).toBeDefined();
		expect(JSON.parse(String(discoveryCall?.[1]?.body))).toEqual({
			document_ids: ['doc_ready']
		});
	});
});
