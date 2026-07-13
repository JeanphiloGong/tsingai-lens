import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type AssistantPageState = {
	params: {
		id: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: AssistantPageState) => void>();
	let current: AssistantPageState = {
		params: { id: 'col_123' },
		url: new URL('http://localhost/collections/col_123/assistant?goal_id=goal_1')
	};

	return {
		pageStore: {
			subscribe(run: (value: AssistantPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: AssistantPageState) {
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

function requestMethod(input: string | URL | Request, init?: RequestInit) {
	return input instanceof Request ? input.method : (init?.method ?? 'GET');
}

describe('collections/[id]/assistant/+page.svelte', () => {
	beforeEach(() => {
		localStorage.clear();
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/assistant?goal_id=goal_1')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);
			if (path === '/api/v1/goal-sessions' && method === 'POST') {
				return Promise.resolve(
					jsonResponse({
						session_id: 'session_1',
						user_id: 'test-user',
						collection_id: 'col_123',
						focused_material_id: null,
						focused_paper_id: null,
						focused_objective_id: null,
						focused_goal_id: 'goal_1',
						goal_text: null,
						goal_brief_json: {},
						answer_mode: 'hybrid',
						rolling_summary: '',
						last_evidence_ids: [],
						last_material_ids: [],
						last_paper_ids: [],
						collection_data_version: null,
						created_at: '2026-07-13T00:00:00+00:00',
						updated_at: '2026-07-13T00:00:00+00:00'
					})
				);
			}
			if (path === '/api/v1/goal-sessions/session_1/messages' && method === 'POST') {
				return Promise.resolve(
					jsonResponse({
						message_id: 'msg_assistant_1',
						session_id: 'session_1',
						role: 'assistant',
						content: 'Use the accepted VED finding to plan a defect-fatigue validation [Source 1].',
						answer: 'Use the accepted VED finding to plan a defect-fatigue validation [Source 1].',
						source_mode: 'collection_grounded',
						used_evidence_ids: ['ev_1'],
						warnings: [],
						links: {},
						source_links: [
							{
								kind: 'evidence',
								label: 'Source 1',
								href: '/collections/col_123/documents/paper-a?evidence_id=ev_1'
							}
						],
						created_at: '2026-07-13T00:01:00+00:00'
					})
				);
			}
			if (path === '/api/v1/collections/col_123/goals/goal_1/experiment-plans' && method === 'POST') {
				return Promise.resolve(
					jsonResponse({
						plan_id: 'plan_1',
						collection_id: 'col_123',
						goal_id: 'goal_1',
						title: 'Use the accepted VED finding to plan a defect-fatigue validation [Source 1].',
						content: 'Use the accepted VED finding to plan a defect-fatigue validation [Source 1].',
						status: 'draft',
						source_message_id: 'msg_assistant_1',
						source_links: [
							{
								kind: 'evidence',
								label: 'Source 1',
								href: '/collections/col_123/documents/paper-a?evidence_id=ev_1'
							}
						],
						metadata: { source: 'goal_copilot', source_mode: 'collection_grounded' },
						created_by: 'test-user',
						created_at: '2026-07-13T00:02:00+00:00',
						updated_at: '2026-07-13T00:02:00+00:00'
					})
				);
			}
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected'));
		});
	});

	it('saves grounded copilot answers as traceable experiment plans', async () => {
		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Ask this collection directly' })).toBeInTheDocument();
		await browserPage.getByLabelText('Message').fill('Draft a next-step validation plan.');
		await browserPage.getByRole('button', { name: 'Send' }).click();

		await expect.element(browserPage.getByText(/accepted VED finding/)).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Source 1' }))
			.toHaveAttribute('href', '/collections/col_123/documents/paper-a?evidence_id=ev_1');

		await browserPage.getByRole('button', { name: 'Save plan' }).click();

		const [, planInit] = fetchMock.mock.calls.find(([input, init]) => {
			return (
				requestPath(input as string | URL | Request) ===
					'/api/v1/collections/col_123/goals/goal_1/experiment-plans' &&
				requestMethod(input as string | URL | Request, init as RequestInit | undefined) === 'POST'
			);
		}) as [string | URL | Request, RequestInit];
		const payload = JSON.parse(planInit.body as string);
		expect(payload.source_message_id).toBe('msg_assistant_1');
		expect(payload.source_links).toEqual([
			{
				kind: 'evidence',
				label: 'Source 1',
				href: '/collections/col_123/documents/paper-a?evidence_id=ev_1'
			}
		]);
		expect(payload.metadata).toEqual({
			source: 'goal_copilot',
			source_mode: 'collection_grounded'
		});
		await expect
			.element(browserPage.getByRole('link', { name: 'Open plan' }))
			.toHaveAttribute(
				'href',
				'/collections/col_123/goals/goal_1?plan_id=plan_1#experiment-plans-title'
			);
	});

	it('does not save grounded answers without visible source links as experiment plans', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);
			if (path === '/api/v1/goal-sessions' && method === 'POST') {
				return Promise.resolve(
					jsonResponse({
						session_id: 'session_1',
						user_id: 'test-user',
						collection_id: 'col_123',
						focused_material_id: null,
						focused_paper_id: null,
						focused_objective_id: null,
						focused_goal_id: 'goal_1',
						goal_text: null,
						goal_brief_json: {},
						answer_mode: 'hybrid',
						rolling_summary: '',
						last_evidence_ids: [],
						last_material_ids: [],
						last_paper_ids: [],
						collection_data_version: null,
						created_at: '2026-07-13T00:00:00+00:00',
						updated_at: '2026-07-13T00:00:00+00:00'
					})
				);
			}
			if (path === '/api/v1/goal-sessions/session_1/messages' && method === 'POST') {
				return Promise.resolve(
					jsonResponse({
						message_id: 'msg_assistant_unlinked',
						session_id: 'session_1',
						role: 'assistant',
						content: 'This grounded draft has no source links.',
						answer: 'This grounded draft has no source links.',
						source_mode: 'collection_grounded',
						used_evidence_ids: [],
						warnings: [],
						links: {},
						source_links: [],
						created_at: '2026-07-13T00:01:00+00:00'
					})
				);
			}
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected'));
		});

		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Ask this collection directly' })).toBeInTheDocument();
		await browserPage.getByLabelText('Message').fill('Draft a next-step validation plan.');
		await browserPage.getByRole('button', { name: 'Send' }).click();

		await expect.element(browserPage.getByText('This grounded draft has no source links.')).toBeInTheDocument();
		await expect.element(browserPage.getByRole('button', { name: 'Save plan' })).not.toBeInTheDocument();
		expect(
			fetchMock.mock.calls.some(([input, init]) => {
				return (
					requestPath(input as string | URL | Request).endsWith('/experiment-plans') &&
					requestMethod(input as string | URL | Request, init as RequestInit | undefined) === 'POST'
				);
			})
		).toBe(false);
	});

	it('does not save grounded answers before focused findings are expert-reviewed', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);
			if (path === '/api/v1/goal-sessions' && method === 'POST') {
				return Promise.resolve(
					jsonResponse({
						session_id: 'session_1',
						user_id: 'test-user',
						collection_id: 'col_123',
						focused_material_id: null,
						focused_paper_id: null,
						focused_objective_id: null,
						focused_goal_id: 'goal_1',
						goal_text: null,
						goal_brief_json: {},
						answer_mode: 'hybrid',
						rolling_summary: '',
						last_evidence_ids: [],
						last_material_ids: [],
						last_paper_ids: [],
						collection_data_version: null,
						created_at: '2026-07-13T00:00:00+00:00',
						updated_at: '2026-07-13T00:00:00+00:00'
					})
				);
			}
			if (path === '/api/v1/goal-sessions/session_1/messages' && method === 'POST') {
				return Promise.resolve(
					jsonResponse({
						message_id: 'msg_assistant_needs_review',
						session_id: 'session_1',
						role: 'assistant',
						content: 'This draft cites unreviewed collection evidence [Source 1].',
						answer: 'This draft cites unreviewed collection evidence [Source 1].',
						source_mode: 'collection_grounded',
						used_evidence_ids: ['ev_unreviewed'],
						warnings: ['curated_research_findings_empty'],
						links: {},
						source_links: [
							{
								kind: 'evidence',
								label: 'Source 1',
								href: '/collections/col_123/documents/paper-a?evidence_id=ev_unreviewed'
							}
						],
						created_at: '2026-07-13T00:01:00+00:00'
					})
				);
			}
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected'));
		});

		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Ask this collection directly' })).toBeInTheDocument();
		await browserPage.getByLabelText('Message').fill('Draft a next-step validation plan.');
		await browserPage.getByRole('button', { name: 'Send' }).click();

		await expect.element(browserPage.getByText(/unreviewed collection evidence/)).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Save is disabled until this goal has expert-reviewed training-ready findings.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByRole('button', { name: 'Save plan' })).not.toBeInTheDocument();
		expect(
			fetchMock.mock.calls.some(([input, init]) => {
				return (
					requestPath(input as string | URL | Request).endsWith('/experiment-plans') &&
					requestMethod(input as string | URL | Request, init as RequestInit | undefined) === 'POST'
				);
			})
		).toBe(false);
	});
});
