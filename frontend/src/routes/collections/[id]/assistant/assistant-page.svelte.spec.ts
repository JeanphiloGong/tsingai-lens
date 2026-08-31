import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

import type {
	ChatMessage,
	ChatToolCall,
	ChatTrajectory,
	ChatTurn
} from '../../../_shared/chatSessions';

type AssistantPageState = {
	params: { id: string };
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: AssistantPageState) => void>();
	let current: AssistantPageState = {
		params: { id: 'col_123' },
		url: new URL('http://localhost/collections/col_123/assistant')
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

vi.mock('$app/stores', () => ({ page: pageStore }));
vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

const createdAt = '2026-08-19T08:00:00+00:00';
const session = {
	session_id: 'chat_1',
	user_id: 'researcher_1',
	collection_id: 'col_123',
	created_at: createdAt,
	updated_at: createdAt
};

function jsonResponse(body: unknown, status = 200) {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

function streamResponse(turn: ChatTurn, deltas: string[] = [], delayMs = 0) {
	const encoder = new TextEncoder();
	const event = (name: string, data: unknown) =>
		encoder.encode(`event: ${name}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`);
	if (!delayMs) {
		return new Response(
			new Blob([...deltas.map((content) => event('text_delta', { content })), event('turn', turn)]),
			{ headers: { 'Content-Type': 'text/event-stream' } }
		);
	}
	return new Response(
		new ReadableStream({
			start(controller) {
				const [first = '', ...remaining] = deltas;
				if (first) controller.enqueue(event('text_delta', { content: first }));
				setTimeout(() => {
					for (const content of remaining) {
						controller.enqueue(event('text_delta', { content }));
					}
					controller.enqueue(event('turn', turn));
					controller.close();
				}, delayMs);
			}
		}),
		{ headers: { 'Content-Type': 'text/event-stream' } }
	);
}

function requestPath(input: string | URL | Request) {
	const raw =
		typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
	return new URL(raw, 'http://localhost').pathname;
}

function requestMethod(input: string | URL | Request, init?: RequestInit) {
	return input instanceof Request ? input.method : (init?.method ?? 'GET');
}

function requestBody(input: string | URL | Request, init?: RequestInit) {
	const body = input instanceof Request ? null : init?.body;
	return typeof body === 'string' ? JSON.parse(body) : null;
}

function message(
	messageId: string,
	role: ChatMessage['role'],
	content: string,
	overrides: Partial<ChatMessage> = {}
): ChatMessage {
	return {
		message_id: messageId,
		session_id: session.session_id,
		role,
		content,
		created_at: createdAt,
		tool_call_id: null,
		tool_name: null,
		tool_arguments: null,
		tool_result: null,
		source_contexts: [],
		...overrides
	};
}

function pendingCall(overrides: Partial<ChatToolCall> = {}): ChatToolCall {
	return {
		tool_call_id: 'call_write_1',
		session_id: session.session_id,
		assistant_message_id: 'msg_call_write',
		name: 'create_objective_candidate',
		arguments: {
			question: 'How does energy input affect grain morphology?',
			variables: ['energy input'],
			outcomes: ['grain morphology']
		},
		arguments_digest: 'digest_exact_1',
		risk: 'write',
		status: 'approval_required',
		started_at: null,
		finished_at: null,
		error_code: null,
		decision_user_id: null,
		decision_arguments_digest: null,
		decided_at: null,
		...overrides
	};
}

function installApi({
	trajectory = { items: [], pending_approval: null },
	messageTurn,
	messageDeltas = [],
	messageDelayMs = 0,
	decisionTurn
}: {
	trajectory?: ChatTrajectory;
	messageTurn?: ChatTurn;
	messageDeltas?: string[];
	messageDelayMs?: number;
	decisionTurn?: ChatTurn;
} = {}) {
	fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
		const path = requestPath(input);
		const method = requestMethod(input, init);
		if (path === '/api/v1/chat-sessions' && method === 'POST') {
			return Promise.resolve(jsonResponse(session, 201));
		}
		if (path === `/api/v1/chat-sessions/${session.session_id}` && method === 'GET') {
			return Promise.resolve(jsonResponse(session));
		}
		if (path === `/api/v1/chat-sessions/${session.session_id}/messages` && method === 'GET') {
			return Promise.resolve(jsonResponse(trajectory));
		}
		if (path === `/api/v1/chat-sessions/${session.session_id}/messages` && method === 'POST') {
			return Promise.resolve(streamResponse(messageTurn!, messageDeltas, messageDelayMs));
		}
		if (
			path === `/api/v1/chat-sessions/${session.session_id}/tool-calls/call_write_1/decision` &&
			method === 'POST'
		) {
			return Promise.resolve(jsonResponse(decisionTurn));
		}
		return Promise.resolve(jsonResponse({ detail: `Unexpected ${method} ${path}` }, 500));
	});
}

async function renderReady() {
	render(Page);
	const composer = browserPage.getByLabelText('Message');
	await expect.element(composer).toBeEnabled();
	return composer;
}

async function send(text: string) {
	const composer = await renderReady();
	await composer.fill(text);
	await browserPage.getByRole('button', { name: 'Send' }).click();
}

describe('collections/[id]/assistant Research Agent', () => {
	beforeEach(() => {
		localStorage.clear();
		sessionStorage.clear();
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/assistant')
		});
		fetchMock.mockReset();
	});

	it('reviews a document Source context before sending it with the user message', async () => {
		const sourceContext = {
			resource_ref: {
				resource_type: 'source',
				resource_id: 'doc_1:results',
				href: '/collections/col_123/documents/doc_1?view=parsed-paper&source_ref=results&page=3'
			},
			collection_id: 'col_123',
			document_id: 'doc_1',
			document_title: 'Paper A',
			source_kind: 'paragraph',
			source_ref: 'results',
			page: 3,
			quote: 'Conductivity improved to 12 mS/cm under EIS.',
			heading_path: 'Results',
			quote_truncated: true
		};
		sessionStorage.setItem('lens.chatSourceContext.col_123', JSON.stringify(sourceContext));
		installApi({
			messageTurn: {
				status: 'completed',
				messages: [
					message('msg_source_user', 'user', 'What does this result support?', {
						source_contexts: [sourceContext]
					}),
					message('msg_source_answer', 'assistant', 'It reports a measured conductivity result.')
				],
				pending_approval: null,
				error_code: null
			}
		});

		const composer = await renderReady();
		await expect.element(browserPage.getByText('Paper A', { exact: true })).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Conductivity improved to 12 mS/cm under EIS.'))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText('Excerpt shortened · open the Source for the complete content')
			)
			.toBeInTheDocument();
		expect(
			fetchMock.mock.calls.filter(
				([input, init]) =>
					requestPath(input as string | URL | Request).endsWith('/messages') &&
					requestMethod(input as string | URL | Request, init as RequestInit) === 'POST'
			)
		).toHaveLength(0);

		await composer.fill('What does this result support?');
		await browserPage.getByRole('button', { name: 'Send' }).click();

		await expect
			.poll(() => {
				const call = fetchMock.mock.calls.find(
					([input, init]) =>
						requestPath(input as string | URL | Request).endsWith('/messages') &&
						requestMethod(input as string | URL | Request, init as RequestInit) === 'POST'
				);
				return call ? requestBody(call[0], call[1]) : null;
			})
			.toEqual({
				message: 'What does this result support?',
				source_contexts: [sourceContext]
			});
		await expect
			.element(browserPage.getByText('It reports a measured conductivity result.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Paper A', { exact: true })).toBeInTheDocument();
		expect(sessionStorage.getItem('lens.chatSourceContext.col_123')).toBeNull();
	});

	it('lets the researcher remove handed-off Source context before sending', async () => {
		sessionStorage.setItem(
			'lens.chatSourceContext.col_123',
			JSON.stringify({
				resource_ref: {
					resource_type: 'source',
					resource_id: 'doc_1:results',
					href: '/collections/col_123/documents/doc_1?source_ref=results'
				},
				collection_id: 'col_123',
				document_id: 'doc_1',
				document_title: 'Paper A',
				source_kind: 'paragraph',
				source_ref: 'results',
				page: 3,
				quote: 'Conductivity improved to 12 mS/cm under EIS.',
				heading_path: 'Results',
				quote_truncated: false
			})
		);
		installApi();

		await renderReady();
		await browserPage.getByRole('button', { name: 'Remove source context' }).click();

		await expect.element(browserPage.getByText('Paper A', { exact: true })).not.toBeInTheDocument();
		expect(sessionStorage.getItem('lens.chatSourceContext.col_123')).toBeNull();
	});

	it('handles ordinary conversation without showing capability activity', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				messages: [
					message('msg_user_1', 'user', 'Hello'),
					message('msg_assistant_1', 'assistant', 'Hello. I can help inspect this collection.')
				],
				pending_approval: null,
				error_code: null
			}
		});

		await send('Hello');

		await expect
			.element(browserPage.getByText('Hello. I can help inspect this collection.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByLabelText('Research activity')).not.toBeInTheDocument();
	});

	it('shows assistant text before the persisted turn finishes streaming', async () => {
		installApi({
			messageDeltas: ['Partial answer', ' complete.'],
			messageDelayMs: 100,
			messageTurn: {
				status: 'completed',
				messages: [
					message('msg_user_stream', 'user', 'Begin'),
					message('msg_assistant_stream', 'assistant', 'Partial answer complete.')
				],
				pending_approval: null,
				error_code: null
			}
		});

		const composer = await renderReady();
		await composer.fill('Begin');
		await browserPage.getByRole('button', { name: 'Send' }).click();

		await expect
			.element(browserPage.getByText('Partial answer', { exact: true }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Partial answer complete.')).toBeInTheDocument();
		const post = fetchMock.mock.calls.find(
			([input, init]) =>
				requestPath(input as string | URL | Request).endsWith('/messages') &&
				requestMethod(input as string | URL | Request, init as RequestInit) === 'POST'
		);
		expect(new Headers(post?.[1]?.headers).get('Accept')).toBe('text/event-stream');
	});

	it('renders a read capability result separately from the final answer', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				messages: [
					message('msg_user_1', 'user', 'What findings are available?'),
					message('msg_call_1', 'assistant', '', {
						tool_call_id: 'call_read_1',
						tool_name: 'query_published_findings',
						tool_arguments: { query: 'energy input' }
					}),
					message('msg_result_1', 'tool', '', {
						tool_call_id: 'call_read_1',
						tool_result: {
							tool_call_id: 'call_read_1',
							status: 'succeeded',
							data: { finding_count: 2, evidence_count: 8 },
							resource_refs: [
								{
									resource_type: 'finding',
									resource_id: 'finding_1',
									href: '/collections/col_123/objectives/obj_1?finding_id=finding_1'
								}
							],
							warnings: ['One paper used a different heat treatment.'],
							error_code: null,
							error_message: null
						}
					}),
					message('msg_assistant_2', 'assistant', 'Two published findings address this question.')
				],
				pending_approval: null,
				error_code: null
			}
		});

		await send('What findings are available?');

		await expect.element(browserPage.getByText('Published findings completed')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('2 findings · 8 evidence records'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('One paper used a different heat treatment.'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open finding' }))
			.toHaveAttribute('href', '/collections/col_123/objectives/obj_1?finding_id=finding_1');
		await expect
			.element(browserPage.getByText('Two published findings address this question.'))
			.toBeInTheDocument();
	});

	it('shows the canonical research process without technical recovery details', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				messages: [
					message('msg_user_1', 'user', 'How far has the collection analysis progressed?'),
					message('msg_call_1', 'assistant', '', {
						tool_call_id: 'call_process_1',
						tool_name: 'inspect_research_process',
						tool_arguments: {}
					}),
					message('msg_result_1', 'tool', '', {
						tool_call_id: 'call_process_1',
						tool_result: {
							tool_call_id: 'call_process_1',
							status: 'succeeded',
							data: {
								process: {
									status: 'running',
									current_step: 'research_scope_screening',
									summary: 'Screening paper Sources for research themes.',
									progress_percent: 72,
									document_progress: { current: 3, total: 10 },
									active_document: {
										document_id: 'paper-3',
										title: 'LPBF process review'
									},
									steps: [
										{ step_id: 'source_understanding', status: 'completed' },
										{ step_id: 'paper_classification', status: 'completed' },
										{ step_id: 'research_scope_screening', status: 'running' },
										{ step_id: 'objective_formation', status: 'queued' }
									],
									failures: []
								}
							},
							resource_refs: [
								{
									resource_type: 'collection',
									resource_id: 'col_123',
									href: '/collections/col_123'
								}
							],
							warnings: [],
							error_code: null,
							error_message: null
						}
					}),
					message('msg_assistant_2', 'assistant', 'The collection is currently being screened.')
				],
				pending_approval: null,
				error_code: null
			}
		});

		await send('How far has the collection analysis progressed?');

		await expect
			.element(browserPage.getByText('Literature analysis progress', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Literature analysis is in progress.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Prepare paper contents')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Assess paper type and role')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Identify materials, variables, and results'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Synthesize candidate research questions'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('LPBF process review · paper 3 of 10'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Screening paper Sources for research themes.'))
			.not.toBeInTheDocument();
		await expect.element(browserPage.getByText(/retry|window/i)).not.toBeInTheDocument();
	});

	it('renders a queued capability as started with a traceable resource', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				messages: [
					message('msg_user_1', 'user', 'Start understanding these papers'),
					message('msg_call_1', 'assistant', '', {
						tool_call_id: 'call_queued_1',
						tool_name: 'start_research_process',
						tool_arguments: {}
					}),
					message('msg_result_1', 'tool', '', {
						tool_call_id: 'call_queued_1',
						tool_result: {
							tool_call_id: 'call_queued_1',
							status: 'queued',
							data: {},
							resource_refs: [
								{
									resource_type: 'document_preparation_task',
									resource_id: 'task_1',
									href: '/collections/col_123'
								}
							],
							warnings: [],
							error_code: null,
							error_message: null
						}
					}),
					message('msg_assistant_2', 'assistant', 'The analysis has started.')
				],
				pending_approval: null,
				error_code: null
			}
		});

		await send('Start understanding these papers');

		await expect.element(browserPage.getByText('Literature analysis started')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Task queued. You can continue while it runs.'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open literature analysis' }))
			.toHaveAttribute('href', '/collections/col_123');
	});

	it('shows objective drafts as proposals without creating Core records', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				messages: [
					message('msg_user_1', 'user', 'Suggest objectives'),
					message('msg_call_1', 'assistant', '', {
						tool_call_id: 'call_draft_1',
						tool_name: 'propose_objective_drafts',
						tool_arguments: { question: 'energy input effects' }
					}),
					message('msg_result_1', 'tool', '', {
						tool_call_id: 'call_draft_1',
						tool_result: {
							tool_call_id: 'call_draft_1',
							status: 'succeeded',
							data: {
								draft_count: 1,
								drafts: [
									{
										question: 'How does energy input affect grain morphology?',
										variables: ['energy input'],
										outcomes: ['grain morphology'],
										support_status: 'collection_supported'
									}
								]
							},
							resource_refs: [],
							warnings: [],
							error_code: null,
							error_message: null
						}
					}),
					message('msg_assistant_2', 'assistant', 'I found one focused candidate for review.')
				],
				pending_approval: null,
				error_code: null
			}
		});

		await send('Suggest objectives');

		await expect
			.element(browserPage.getByText('How does energy input affect grain morphology?'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Proposal context: collection_supported'))
			.toBeInTheDocument();
		expect(
			fetchMock.mock.calls.some(([input]) =>
				requestPath(input as string | URL | Request).includes('/objectives')
			)
		).toBe(false);
	});

	it('shows exact write arguments and blocks new messages while approval is pending', async () => {
		const call = pendingCall();
		installApi({
			messageTurn: {
				status: 'approval_required',
				messages: [
					message('msg_user_1', 'user', 'Create the grain objective'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: call.tool_call_id,
						tool_name: call.name,
						tool_arguments: call.arguments
					})
				],
				pending_approval: call,
				error_code: null
			}
		});

		await send('Create the grain objective');

		await expect
			.element(browserPage.getByRole('heading', { name: 'Approval required' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('How does energy input affect grain morphology?'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('energy input', { exact: true }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByLabelText('Message')).toBeDisabled();
		await expect.element(browserPage.getByRole('button', { name: 'Reject' })).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and create' }))
			.toBeInTheDocument();
	});

	it('describes starting literature analysis as an approved action without fake arguments', async () => {
		const call = pendingCall({
			name: 'start_research_process',
			arguments: {}
		});
		installApi({
			messageTurn: {
				status: 'approval_required',
				messages: [
					message('msg_user_1', 'user', 'Start understanding these papers'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: call.tool_call_id,
						tool_name: call.name,
						tool_arguments: call.arguments
					})
				],
				pending_approval: call,
				error_code: null
			}
		});

		await send('Start understanding these papers');

		await expect
			.element(browserPage.getByText('Literature analysis', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Prepare and classify the uploaded papers, build a lightweight Paper Map, and form candidate research questions.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and start' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Proposed values')).not.toBeInTheDocument();
	});

	it('requires a separate approval before analyzing one research question', async () => {
		const call = pendingCall({
			name: 'start_objective_analysis',
			arguments: { objective_id: 'obj_energy_1' }
		});
		installApi({
			messageTurn: {
				status: 'approval_required',
				messages: [
					message('msg_user_1', 'user', 'Analyze this question'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: call.tool_call_id,
						tool_name: call.name,
						tool_arguments: call.arguments
					})
				],
				pending_approval: call,
				error_code: null
			}
		});

		await send('Analyze this question');

		await expect
			.element(browserPage.getByText('Research question evidence analysis', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Inspect the selected papers, extract source-backed facts, and compare the result for this research question.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and analyze' }))
			.toBeInTheDocument();
	});

	it('records a rejected literature-analysis start without implying that work ran', async () => {
		const call = pendingCall({
			name: 'start_research_process',
			arguments: {}
		});
		installApi({
			trajectory: {
				items: [
					message('msg_call_write', 'assistant', '', {
						tool_call_id: call.tool_call_id,
						tool_name: call.name,
						tool_arguments: call.arguments
					})
				],
				pending_approval: call
			},
			decisionTurn: {
				status: 'rejected',
				messages: [],
				pending_approval: null,
				error_code: null
			}
		});
		localStorage.setItem('lens.chatSession.col_123', session.session_id);
		render(Page);

		await browserPage.getByRole('button', { name: 'Reject' }).click();

		await expect
			.element(browserPage.getByText('Literature analysis was not started.'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open literature analysis' }))
			.not.toBeInTheDocument();
	});

	it('records an exact rejection and creates no objective resource', async () => {
		const call = pendingCall();
		installApi({
			trajectory: {
				items: [
					message('msg_call_write', 'assistant', '', {
						tool_call_id: call.tool_call_id,
						tool_name: call.name,
						tool_arguments: call.arguments
					})
				],
				pending_approval: call
			},
			decisionTurn: {
				status: 'rejected',
				messages: [],
				pending_approval: null,
				error_code: null
			}
		});
		localStorage.setItem('lens.chatSession.col_123', session.session_id);
		render(Page);

		await browserPage.getByRole('button', { name: 'Reject' }).click();

		await expect
			.element(
				browserPage.getByText('The proposed write was rejected. No research objective was created.')
			)
			.toBeInTheDocument();
		const decisionRequest = fetchMock.mock.calls.find(
			([input, init]) =>
				requestPath(input as string | URL | Request).endsWith('/decision') &&
				requestMethod(input as string | URL | Request, init as RequestInit) === 'POST'
		);
		expect(requestBody(decisionRequest![0], decisionRequest![1])).toEqual({
			decision: 'rejected',
			arguments_digest: 'digest_exact_1'
		});
		await expect
			.element(browserPage.getByRole('link', { name: 'Open research objective' }))
			.not.toBeInTheDocument();
	});

	it('executes an approved write and links the canonical objective', async () => {
		const call = pendingCall();
		installApi({
			trajectory: {
				items: [
					message('msg_call_write', 'assistant', '', {
						tool_call_id: call.tool_call_id,
						tool_name: call.name,
						tool_arguments: call.arguments
					})
				],
				pending_approval: call
			},
			decisionTurn: {
				status: 'completed',
				messages: [
					message('msg_result_write', 'tool', '', {
						tool_call_id: call.tool_call_id,
						tool_result: {
							tool_call_id: call.tool_call_id,
							status: 'succeeded',
							data: { objective_id: 'obj_new_1' },
							resource_refs: [
								{
									resource_type: 'research_objective',
									resource_id: 'obj_new_1',
									href: '/collections/col_123/objectives/obj_new_1'
								}
							],
							warnings: [],
							error_code: null,
							error_message: null
						}
					}),
					message(
						'msg_final_write',
						'assistant',
						'The objective candidate was created for your review.'
					)
				],
				pending_approval: null,
				error_code: null
			}
		});
		localStorage.setItem('lens.chatSession.col_123', session.session_id);
		render(Page);

		await browserPage.getByRole('button', { name: 'Approve and create' }).click();

		const objectiveLink = browserPage.getByRole('link', { name: 'Open research objective' });
		await expect
			.element(objectiveLink)
			.toHaveAttribute('href', '/collections/col_123/objectives/obj_new_1');
		await expect
			.element(browserPage.getByText('The objective candidate was created for your review.'))
			.toBeInTheDocument();
		const decisionRequest = fetchMock.mock.calls.find(
			([input, init]) =>
				requestPath(input as string | URL | Request).endsWith('/decision') &&
				requestMethod(input as string | URL | Request, init as RequestInit) === 'POST'
		);
		expect(requestBody(decisionRequest![0], decisionRequest![1])).toEqual({
			decision: 'approved',
			arguments_digest: 'digest_exact_1'
		});
	});

	it('restores a persisted pending approval after refresh', async () => {
		const call = pendingCall();
		localStorage.setItem('lens.chatSession.col_123', session.session_id);
		installApi({
			trajectory: {
				items: [
					message('msg_call_write', 'assistant', '', {
						tool_call_id: call.tool_call_id,
						tool_name: call.name,
						tool_arguments: call.arguments
					})
				],
				pending_approval: call
			}
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Approval required' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByLabelText('Message')).toBeDisabled();
		expect(
			fetchMock.mock.calls.some(
				([input, init]) =>
					requestPath(input as string | URL | Request).endsWith('/messages') &&
					requestMethod(input as string | URL | Request, init as RequestInit) === 'GET'
			)
		).toBe(true);
	});

	it('discards stale Goal storage and starts Chat without a compatibility request', async () => {
		localStorage.setItem('lens.goalSession.col_123', 'goal_legacy_1');
		localStorage.setItem('lens.goalSessionHistory.col_123', '[{"session_id":"goal_legacy_1"}]');
		installApi();

		await renderReady();

		expect(localStorage.getItem('lens.goalSession.col_123')).toBeNull();
		expect(localStorage.getItem('lens.goalSessionHistory.col_123')).toBeNull();
		expect(
			fetchMock.mock.calls.some(([input]) =>
				requestPath(input as string | URL | Request).includes('/goal-sessions')
			)
		).toBe(false);
		expect(
			fetchMock.mock.calls.some(
				([input, init]) =>
					requestPath(input as string | URL | Request) === '/api/v1/chat-sessions' &&
					requestMethod(input as string | URL | Request, init as RequestInit) === 'POST'
			)
		).toBe(true);
	});
});
