import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type ObjectivesPageState = {
	params: { id: string };
	url: URL;
};

const { pageStore, setPage, goto, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: ObjectivesPageState) => void>();
	let current: ObjectivesPageState = {
		params: { id: 'col_123' },
		url: new URL('http://localhost/collections/col_123/objectives')
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
		goto: vi.fn(),
		fetchMock: vi.fn()
	};
});

vi.mock('$app/stores', () => ({ page: pageStore }));
vi.mock('$app/navigation', () => ({ goto }));
vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

function jsonResponse(body: unknown) {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { 'Content-Type': 'application/json' }
	});
}

function request(input: string | URL | Request, init?: RequestInit) {
	const raw =
		typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
	return {
		path: new URL(raw, 'http://localhost').pathname,
		method: input instanceof Request ? input.method : (init?.method ?? 'GET')
	};
}

function objective(overrides: Record<string, unknown> = {}) {
	return {
		collection_id: 'col_123',
		objective_id: 'obj_heat_strength',
		question: 'How does heat treatment affect strength?',
		material_scope: ['316L stainless steel'],
		variables: ['heat treatment'],
		outcomes: ['yield strength'],
		mechanisms: ['precipitate evolution'],
		constraints: ['LPBF 316L'],
		requested_comparator: 'Compare treated and untreated samples.',
		seed_document_ids: ['paper-1', 'paper-2'],
		excluded_document_ids: [],
		confidence: 0.82,
		reason: null,
		confirmation_status: 'candidate',
		active_analysis_version: null,
		published_analysis_version: null,
		created_at: null,
		updated_at: null,
		...overrides
	};
}

function analysisState(status: 'queued' | 'running' | 'succeeded' | 'failed') {
	return {
		collection_id: 'col_123',
		objective_id: 'obj_heat_strength',
		analysis_version: 1,
		source_build_id: 'build-1',
		pipeline_version: 'objective-analysis-v1',
		model_name: null,
		prompt_versions: {},
		status,
		phase: status === 'running' ? 'evidence_extraction' : status,
		processed_document_count: status === 'running' ? 2 : 0,
		total_document_count: 6,
		current_document_id: status === 'running' ? 'paper-2' : null,
		progress_message: status === 'running' ? 'Extracting evidence.' : null,
		error_code: null,
		error_message: null,
		created_at: null,
		started_at: null,
		completed_at: null
	};
}

describe('collections/[id]/objectives/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/objectives')
		});
		goto.mockReset();
		fetchMock.mockReset();
	});

	it('shows an explicit empty state before Objective candidates exist', async () => {
		fetchMock.mockResolvedValue(jsonResponse({ collection_id: 'col_123', objectives: [] }));

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: '研究目标' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('当前 collection 尚未生成研究目标。'))
			.toBeInTheDocument();
	});

	it('confirms and queues analysis under the same Objective identity', async () => {
		const requests: Array<{ path: string; method: string }> = [];
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			requests.push(current);
			if (current.path.endsWith('/objectives') && current.method === 'GET') {
				return jsonResponse({ collection_id: 'col_123', objectives: [objective()] });
			}
			if (current.path.endsWith('/obj_heat_strength/confirm') && current.method === 'POST') {
				return jsonResponse({
					collection_id: 'col_123',
					objective: objective({ confirmation_status: 'confirmed' }),
					active_analysis: null,
					published_analysis: null,
					warnings: []
				});
			}
			if (current.path.endsWith('/obj_heat_strength/analysis') && current.method === 'POST') {
				return jsonResponse({
					collection_id: 'col_123',
					objective: objective({ confirmation_status: 'confirmed', active_analysis_version: 1 }),
					active_analysis: null,
					published_analysis: null,
					warnings: []
				});
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}`);
		});

		render(Page);
		await browserPage.getByRole('button', { name: '确认并分析' }).click();

		await vi.waitFor(() => {
			expect(requests).toContainEqual({
				path: '/api/v1/collections/col_123/objectives/obj_heat_strength/confirm',
				method: 'POST'
			});
			expect(requests).toContainEqual({
				path: '/api/v1/collections/col_123/objectives/obj_heat_strength/analysis',
				method: 'POST'
			});
			expect(goto).toHaveBeenCalledWith('/collections/col_123/objectives/obj_heat_strength');
		});
	});

	it('shows active analysis progress instead of offering confirmation again', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			if (current.path.endsWith('/objectives') && current.method === 'GET') {
				return jsonResponse({
					collection_id: 'col_123',
					objectives: [
						objective({
							confirmation_status: 'confirmed',
							active_analysis_version: 1
						})
					]
				});
			}
			if (current.path.endsWith('/obj_heat_strength/analysis') && current.method === 'GET') {
				return jsonResponse({
					collection_id: 'col_123',
					objective: objective({
						confirmation_status: 'confirmed',
						active_analysis_version: 1
					}),
					active_analysis: analysisState('running'),
					published_analysis: null,
					warnings: []
				});
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}`);
		});

		render(Page);

		await expect.element(browserPage.getByText('分析中 · 2/6')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: '确认并分析' }))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: '查看状态' }))
			.toBeInTheDocument();
	});

	it('shows the published version without a second result lookup', async () => {
		fetchMock.mockResolvedValue(
			jsonResponse({
				collection_id: 'col_123',
				objectives: [
					objective({
						confirmation_status: 'confirmed',
						active_analysis_version: 2,
						published_analysis_version: 2
					})
				]
			})
		);

		render(Page);

		await expect.element(browserPage.getByText('结果 v2')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: '查看 Findings' }))
			.toHaveAttribute('href', '/collections/col_123/objectives/obj_heat_strength');
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});
});
