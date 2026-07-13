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

function datasetResponse({
	trainingReady = 1,
	trainingMessages = 1,
	reviewCandidate = 0
} = {}) {
	return {
		schema_version: 'research_understanding_dataset.v1',
		dataset_id: 'dataset_goal_1',
		collection_id: 'col_123',
		scope_type: 'goal',
		scope_id: 'goal_1',
		task_type: 'research_understanding_finding',
		metric_profile: 'research_understanding_v1',
		label_status_filter: null,
		dataset_use_status_filter: null,
		item_count: trainingReady + reviewCandidate,
		label_counts: {
			candidate: reviewCandidate,
			silver: 0,
			gold: trainingReady,
			rejected: 0
		},
		quality_summary: {
			training_ready_sample_count: trainingReady,
			training_message_sample_count: trainingMessages,
			review_candidate_sample_count: reviewCandidate,
			by_dataset_use_status: {
				training_ready: trainingReady,
				review_candidate: reviewCandidate,
				rejected: 0
			},
			by_presentation_bucket: {},
			by_error_category: {}
		},
		warnings: []
	};
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
			if (path === '/api/v1/collections/col_123/research-understanding/dataset' && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse()));
			}
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
						content:
							'Hypothesis: VED changes defect fraction and fatigue strength [Source 1].\n' +
							'Variable matrix: compare L-VED, M-VED, and H-VED builds.\n' +
							'Measurements: defect fraction and fatigue strength.\n' +
							'Controls: keep alloy, powder, and heat treatment fixed.\n' +
							'Risks or limits: single-paper evidence should be validated.',
						answer:
							'Hypothesis: VED changes defect fraction and fatigue strength [Source 1].\n' +
							'Variable matrix: compare L-VED, M-VED, and H-VED builds.\n' +
							'Measurements: defect fraction and fatigue strength.\n' +
							'Controls: keep alloy, powder, and heat treatment fixed.\n' +
							'Risks or limits: single-paper evidence should be validated.',
						source_mode: 'collection_grounded',
						used_evidence_ids: ['ev_1'],
						warnings: [],
						links: {},
						review_gate: 'training_ready_findings',
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
						title: 'Hypothesis: VED changes defect fraction and fatigue strength [Source 1].',
						content:
							'Hypothesis: VED changes defect fraction and fatigue strength [Source 1].\n' +
							'Variable matrix: compare L-VED, M-VED, and H-VED builds.\n' +
							'Measurements: defect fraction and fatigue strength.\n' +
							'Controls: keep alloy, powder, and heat treatment fixed.\n' +
							'Risks or limits: single-paper evidence should be validated.',
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

	it('shows protocol readiness for goals with training-ready message samples', async () => {
		render(Page);

		await expect
			.element(browserPage.getByText('Experiment readiness'))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'1 training-ready finding(s) and 1 message-ready sample(s) are available for traceable protocol drafts.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open goal review' }))
			.toHaveAttribute('href', '/collections/col_123/goals/goal_1');
		await expect
			.element(browserPage.getByRole('button', { name: 'Draft protocol' }))
			.toBeInTheDocument();
	});

	it('shows review backlog before protocol drafts are ready', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);
			if (path === '/api/v1/collections/col_123/research-understanding/dataset' && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 0,
							trainingMessages: 0,
							reviewCandidate: 3
						})
					)
				);
			}
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
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected'));
		});

		render(Page);

		await expect
			.element(
				browserPage.getByText(
					'3 finding(s) still need expert review before protocol drafts can be saved.'
				)
				)
			.toBeInTheDocument();
		await expect.element(browserPage.getByRole('button', { name: 'Draft protocol' })).not.toBeInTheDocument();
	});

	it('shows pending training messages before protocol drafts are ready', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);
			if (path === '/api/v1/collections/col_123/research-understanding/dataset' && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 1,
							trainingMessages: 0,
							reviewCandidate: 0
						})
					)
				);
			}
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
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected'));
		});

		render(Page);

		await expect
			.element(
				browserPage.getByText(
					'1 training-ready finding(s) exist, but only 0 training message sample(s) are exportable. Check dataset export quality before drafting a protocol.'
				)
			)
			.toBeInTheDocument();
		await expect.element(browserPage.getByRole('button', { name: 'Draft protocol' })).not.toBeInTheDocument();
	});

	it('starts a protocol draft from reviewed goal findings', async () => {
		render(Page);

		await browserPage.getByRole('button', { name: 'Draft protocol' }).click();

		const [, messageInit] = fetchMock.mock.calls.find(([input, init]) => {
			return (
				requestPath(input as string | URL | Request) === '/api/v1/goal-sessions/session_1/messages' &&
				requestMethod(input as string | URL | Request, init as RequestInit | undefined) === 'POST'
			);
		}) as [string | URL | Request, RequestInit];
		const payload = JSON.parse(messageInit.body as string);
		expect(payload.message).toContain('training-ready findings');
		expect(payload.message).toContain('Hypothesis');
		expect(payload.message).toContain('Variable matrix');
		expect(payload.message).toContain('Measurements');
		expect(payload.message).toContain('Controls');
		expect(payload.message).toContain('Risks or limits');
		expect(payload.message).toContain('visible source labels');
	});

	it('saves grounded copilot answers as traceable experiment plans', async () => {
		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Ask this collection directly' })).toBeInTheDocument();
		await browserPage.getByLabelText('Message').fill('Draft a next-step validation plan.');
		await browserPage.getByRole('button', { name: 'Send' }).click();

		await expect.element(browserPage.getByText(/VED changes defect fraction/)).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Source 1' }))
			.toHaveAttribute('href', '/collections/col_123/documents/paper-a?evidence_id=ev_1');
		await expect.element(browserPage.getByRole('button', { name: 'Copy answer' })).toBeInTheDocument();
		await expect.element(browserPage.getByRole('button', { name: 'Like answer' })).not.toBeInTheDocument();
		await expect.element(browserPage.getByRole('button', { name: 'Dislike answer' })).not.toBeInTheDocument();

		await browserPage.getByRole('button', { name: 'Save plan' }).click();

		const [, planInit] = fetchMock.mock.calls.find(([input, init]) => {
			return (
				requestPath(input as string | URL | Request) ===
					'/api/v1/collections/col_123/goals/goal_1/experiment-plans' &&
				requestMethod(input as string | URL | Request, init as RequestInit | undefined) === 'POST'
			);
		}) as [string | URL | Request, RequestInit];
		const payload = JSON.parse(planInit.body as string);
		expect(payload.title).toBe(
			'Hypothesis: VED changes defect fraction and fatigue strength [Source 1].'
		);
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
						review_gate: 'training_ready_findings',
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

	it('does not save unstructured grounded answers as experiment plans', async () => {
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
						message_id: 'msg_assistant_unstructured_protocol',
						session_id: 'session_1',
						role: 'assistant',
						content: 'Run 25 C and 150 C LPBF 316L builds [Source 1].',
						answer: 'Run 25 C and 150 C LPBF 316L builds [Source 1].',
						source_mode: 'collection_grounded',
						used_evidence_ids: ['ev_1'],
						warnings: [],
						links: {},
						review_gate: 'training_ready_findings',
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
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected'));
		});

		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Ask this collection directly' })).toBeInTheDocument();
		await browserPage.getByLabelText('Message').fill('Draft a next-step validation plan.');
		await browserPage.getByRole('button', { name: 'Send' }).click();

		await expect.element(browserPage.getByText('Run 25 C and 150 C LPBF 316L builds')).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Save is disabled until the answer includes a hypothesis, variable matrix, measurements, controls, and risks or limits.'
				)
			)
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

	it('explains when a limited answer is missing auditable source citations', async () => {
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
						message_id: 'msg_assistant_missing_source_trace',
						session_id: 'session_1',
						role: 'assistant',
						content:
							'Lens could not verify source citations in the generated answer, so do not treat it as a traceable collection conclusion.',
						answer:
							'Lens could not verify source citations in the generated answer, so do not treat it as a traceable collection conclusion.',
						source_mode: 'collection_limited',
						used_evidence_ids: [],
						warnings: ['goal_copilot_missing_source_citation'],
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

		await expect.element(browserPage.getByText(/could not verify source citations/)).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'This answer is limited because Lens could not verify a visible source citation. Review the findings and evidence before using it for a protocol.'
				)
			)
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

	it('does not save grounded answers without evidence citations as experiment plans', async () => {
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
						message_id: 'msg_assistant_uncited',
						session_id: 'session_1',
						role: 'assistant',
						content: 'This draft links a source but does not cite reviewed evidence [Source 1].',
						answer: 'This draft links a source but does not cite reviewed evidence [Source 1].',
						source_mode: 'collection_grounded',
						used_evidence_ids: [],
						warnings: [],
						links: {},
						review_gate: 'training_ready_findings',
						source_links: [
							{
								kind: 'evidence',
								label: 'Source 1',
								href: '/collections/col_123/documents/paper-a?evidence_id=ev_uncited'
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

		await expect.element(browserPage.getByText(/does not cite reviewed evidence/)).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Save is disabled until the answer cites the exact reviewed evidence used for the plan.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Source 1' }))
			.toHaveAttribute('href', '/collections/col_123/documents/paper-a?evidence_id=ev_uncited');
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

	it('does not save grounded answers without the training-ready review gate', async () => {
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
						message_id: 'msg_assistant_no_review_gate',
						session_id: 'session_1',
						role: 'assistant',
						content: 'Use the accepted finding to plan a validation build [Source 1].',
						answer: 'Use the accepted finding to plan a validation build [Source 1].',
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
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected'));
		});

		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Ask this collection directly' })).toBeInTheDocument();
		await browserPage.getByLabelText('Message').fill('Draft a next-step validation plan.');
		await browserPage.getByRole('button', { name: 'Send' }).click();

		await expect.element(browserPage.getByText(/accepted finding/)).toBeInTheDocument();
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

	it('does not save grounded answers without source label citations as experiment plans', async () => {
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
						message_id: 'msg_assistant_unlabeled',
						session_id: 'session_1',
						role: 'assistant',
						content: 'Use the accepted finding to plan a validation build.',
						answer: 'Use the accepted finding to plan a validation build.',
						source_mode: 'collection_grounded',
						used_evidence_ids: ['ev_1'],
						warnings: [],
						links: {},
						review_gate: 'training_ready_findings',
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
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected'));
		});

		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Ask this collection directly' })).toBeInTheDocument();
		await browserPage.getByLabelText('Message').fill('Draft a next-step validation plan.');
		await browserPage.getByRole('button', { name: 'Send' }).click();

		await expect.element(browserPage.getByText(/accepted finding/)).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Save is disabled until the answer names the visible source label, such as [Source 1].'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Source 1' }))
			.toHaveAttribute('href', '/collections/col_123/documents/paper-a?evidence_id=ev_1');
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

	it('does not save grounded answers when source links do not match evidence citations', async () => {
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
						message_id: 'msg_assistant_mismatch',
						session_id: 'session_1',
						role: 'assistant',
						content: 'Use the accepted finding to plan a validation build [Source 1].',
						answer: 'Use the accepted finding to plan a validation build [Source 1].',
						source_mode: 'collection_grounded',
						used_evidence_ids: ['ev_1'],
						warnings: [],
						links: {},
						review_gate: 'training_ready_findings',
						source_links: [
							{
								kind: 'evidence',
								label: 'Source 1',
								href: '/collections/col_123/documents/paper-a?evidence_id=ev_other'
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

		await expect.element(browserPage.getByText(/accepted finding/)).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Save is disabled until source links match the reviewed evidence citations.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Source 1' }))
			.toHaveAttribute('href', '/collections/col_123/documents/paper-a?evidence_id=ev_other');
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

	it('does not save grounded answers when a used evidence citation has no source link', async () => {
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
						message_id: 'msg_assistant_missing_link',
						session_id: 'session_1',
						role: 'assistant',
						content: 'Use both accepted findings to plan a validation build [Source 1].',
						answer: 'Use both accepted findings to plan a validation build [Source 1].',
						source_mode: 'collection_grounded',
						used_evidence_ids: ['ev_1', 'ev_2'],
						warnings: [],
						links: {},
						review_gate: 'training_ready_findings',
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
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected'));
		});

		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Ask this collection directly' })).toBeInTheDocument();
		await browserPage.getByLabelText('Message').fill('Draft a next-step validation plan.');
		await browserPage.getByRole('button', { name: 'Send' }).click();

		await expect.element(browserPage.getByText(/both accepted findings/)).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Save is disabled until every reviewed evidence citation has a visible source link.'
				)
			)
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
