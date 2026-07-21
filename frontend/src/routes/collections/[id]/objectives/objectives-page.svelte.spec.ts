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
		goto: vi.fn(),
		fetchMock: vi.fn()
	};
});

vi.mock('$app/stores', () => ({ page: pageStore }));
vi.mock('$app/navigation', () => ({ goto }));
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

function requestMethod(input: string | URL | Request, init?: RequestInit) {
	if (input instanceof Request) return input.method;
	return typeof init?.method === 'string' ? init.method : 'GET';
}

function objectiveListResponse(status = 'candidate') {
	return {
		collection_id: 'col_4c54ffe568ec',
		state: 'partial',
		readiness: {
			objectives_ready: true,
			frames_ready: true,
			routes_ready: true,
			evidence_units_ready: true,
			logic_chain_ready: false
		},
		objectives: [
			{
				objective_id: 'obj_heat_strength',
				question: 'How does heat treatment affect strength?',
				material_scope: ['316L stainless steel'],
				process_axes: ['heat treatment'],
				property_axes: ['yield strength'],
				comparison_intent: 'Compare treated and untreated samples.',
				confidence: 0.82,
				status,
				analysis_error: status === 'failed' ? 'Source extraction failed.' : null,
				analysis_progress: null,
				review_summary: {
					primary_finding_count: 3,
					review_candidate_count: 2
				},
				state: 'ready',
				paper_frame_count: 2,
				evidence_route_count: 2,
				evidence_unit_count: 1,
				logic_chain_count: 0
			}
		],
		warnings: []
	};
}

describe('collections/[id]/objectives/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_4c54ffe568ec' },
			url: new URL('http://localhost/collections/col_4c54ffe568ec/objectives')
		});
		goto.mockReset();
		fetchMock.mockReset();
	});

	it('treats not-ready objectives as a pending workflow state', async () => {
		fetchMock.mockResolvedValue(
			jsonResponse(
				{
					code: 'research_objectives_not_ready',
					message: 'Finish processing first.',
					collection_id: 'col_4c54ffe568ec'
				},
				409,
				'Conflict'
			)
		);

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Research objectives' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research objectives are not ready yet' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText(/409 Conflict/)).not.toBeInTheDocument();
	});

	it('confirms and queues analysis under the same objective identity', async () => {
		const requests: Array<{ path: string; method: string }> = [];
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);
			requests.push({ path, method });

			if (path.endsWith('/objectives') && method === 'GET') {
				return jsonResponse(objectiveListResponse());
			}
			if (path.endsWith('/objectives/obj_heat_strength/confirm') && method === 'POST') {
				return jsonResponse({
					collection_id: 'col_4c54ffe568ec',
					objective: { ...objectiveListResponse().objectives[0], status: 'confirmed' },
					understanding: null,
					warnings: []
				});
			}
			if (path.endsWith('/objectives/obj_heat_strength/analysis') && method === 'POST') {
				return jsonResponse({
					collection_id: 'col_4c54ffe568ec',
					objective: {
						...objectiveListResponse().objectives[0],
						status: 'queued',
						analysis_progress: { phase: 'queued', message: 'Objective analysis is queued.' }
					},
					understanding: null,
					warnings: []
				});
			}
			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);
		await browserPage.getByRole('button', { name: 'Confirm and analyze' }).click();

		await vi.waitFor(() => {
			expect(requests).toContainEqual({
				path: '/api/v1/collections/col_4c54ffe568ec/objectives/obj_heat_strength/confirm',
				method: 'POST'
			});
			expect(requests).toContainEqual({
				path: '/api/v1/collections/col_4c54ffe568ec/objectives/obj_heat_strength/analysis',
				method: 'POST'
			});
			expect(goto).toHaveBeenCalledWith(
				'/collections/col_4c54ffe568ec/objectives/obj_heat_strength'
			);
		});
	});

	it('shows Objective review counts without a second resource lookup', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);
			if (path.endsWith('/objectives')) return jsonResponse(objectiveListResponse('ready'));
			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});

		render(Page);

		await expect.element(browserPage.getByText('How does heat treatment affect strength?')).toBeInTheDocument();
		await expect.element(browserPage.getByText('3 findings')).toBeInTheDocument();
		await expect.element(browserPage.getByText('2 need review')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open objective workspace' }))
			.toHaveAttribute(
				'href',
				'/collections/col_4c54ffe568ec/objectives/obj_heat_strength'
			);
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});
});
