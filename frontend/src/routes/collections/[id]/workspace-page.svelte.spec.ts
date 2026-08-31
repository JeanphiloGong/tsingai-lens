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
	source_fingerprint: 'source-fingerprint-ready',
	profile_fingerprint: 'profile-fingerprint-ready',
	preparation_fingerprint: 'fingerprint-ready'
};

const storedDocument = {
	...readyDocument,
	document_id: 'doc_stored',
	original_filename: 'stored-paper.pdf',
	status: 'stored',
	source_fingerprint: null,
	profile_fingerprint: null,
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
			.element(browserPage.getByRole('progressbar'))
			.toHaveAttribute('aria-valuenow', '55');
		await expect.element(browserPage.getByText('1 / 2 papers ready')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Upload documents' }))
			.not.toBeDisabled();
	});

	it('discovers objectives from all ready papers without exposing the document selector', async () => {
		render(Page);

		await expect
			.element(browserPage.getByLabelText('Select paper for research scope'))
			.not.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Discover objectives from 1' }).click();

		const discoveryCall = fetchMock.mock.calls.find(([input]) =>
			String(input).includes('/objective-discovery')
		);
		expect(discoveryCall).toBeDefined();
		expect(JSON.parse(String(discoveryCall?.[1]?.body))).toEqual({
			document_ids: ['doc_ready']
		});
	});

	it('leads with existing research objectives instead of the paper management table', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const url = new URL(String(input), 'http://localhost');
			if (url.pathname.endsWith('/documents')) {
				return jsonResponse({ items: [readyDocument] });
			}
			if (url.pathname.endsWith('/tasks')) {
				return jsonResponse({ collection_id: 'col_123', count: 0, items: [] });
			}
			if (url.pathname.endsWith('/objectives')) {
				return jsonResponse({
					collection_id: 'col_123',
					objectives: [{ objective_id: 'obj-1', question: 'How does heat affect strength?' }]
				});
			}
			throw new Error(`unexpected request: ${url.pathname}`);
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('link', { name: 'Enter research objectives' }))
			.toHaveAttribute('href', '/collections/col_123/objectives');
		await expect.element(browserPage.getByText('ready-paper.pdf')).not.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Discover objectives from 1' }))
			.not.toBeInTheDocument();
	});
});
