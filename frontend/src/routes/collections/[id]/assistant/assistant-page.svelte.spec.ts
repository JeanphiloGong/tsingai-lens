import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { authState, fetchCurrentSession, login, logout } from '../../../_shared/auth';

import type {
	ChatMessage,
	ChatToolCall,
	ChatToolResult,
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
		tool_calls: [],

		tool_result: null,
		source_contexts: [],
		...overrides
	};
}

function baseToolResult(toolCallId: string): ChatToolResult {
	return {
		tool_call_id: toolCallId,
		status: 'succeeded',
		data: {},
		resource_refs: [],
		warnings: [],
		error_code: null,
		error_message: null
	};
}

function pendingCall(overrides: Partial<ChatToolCall> = {}): ChatToolCall {
	return {
		tool_call_id: 'call_write_1',
		session_id: session.session_id,
		assistant_message_id: 'msg_call_write',
		position: 0,
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
	trajectory = { feedback: [], items: [], pending_approval: null },
	messageTurn,
	messageDeltas = [],
	messageDelayMs = 0,
	decisionTurn,
	uploadDocument,
	prepareDocument
}: {
	trajectory?: ChatTrajectory;
	messageTurn?: ChatTurn;
	messageDeltas?: string[];
	messageDelayMs?: number;
	decisionTurn?: ChatTurn;
	uploadDocument?: (file: File) => Response | Promise<Response>;
	prepareDocument?: (documentId: string) => Response | Promise<Response>;
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
		if (path === '/api/v1/collections/col_123/documents' && method === 'POST') {
			const file = init?.body instanceof FormData ? init.body.get('file') : null;
			return uploadDocument && file instanceof File
				? Promise.resolve(uploadDocument(file))
				: Promise.resolve(jsonResponse({ detail: 'Unexpected document upload' }, 500));
		}
		const preparationMatch = path.match(
			/^\/api\/v1\/collections\/col_123\/documents\/([^/]+)\/preparation$/
		);
		if (preparationMatch && method === 'POST') {
			return prepareDocument
				? Promise.resolve(prepareDocument(decodeURIComponent(preparationMatch[1])))
				: Promise.resolve(jsonResponse({ detail: 'Unexpected document preparation' }, 500));
		}
		return Promise.resolve(jsonResponse({ detail: `Unexpected ${method} ${path}` }, 500));
	});
}

function uploadedDocument(file: File, documentId = 'doc_upload_1') {
	return {
		document_id: documentId,
		original_filename: file.name,
		stored_filename: `${documentId}.pdf`,
		storage_key: `col_123/input/${documentId}.pdf`,
		sha256: 'a'.repeat(64),
		media_type: file.type,
		status: 'stored',
		size_bytes: file.size,
		created_at: createdAt,
		updated_at: createdAt,
		parser_version: null,
		document_analysis_version: null,
		source_fingerprint: null,
		profile_fingerprint: null,
		preparation_fingerprint: null
	};
}

function queuedPreparation(documentId = 'doc_upload_1') {
	return {
		run_id: `run_${documentId}`,
		collection_id: 'col_123',
		pipeline_name: 'document_preparation',
		scope_type: 'document',
		scope_id: documentId,
		mode: 'standard',
		input_fingerprint: null,
		status: 'queued',
		current_node: 'queued',
		progress_percent: 0,
		progress_detail: { phase: 'queued' },
		nodes: {},
		errors: [],
		warnings: [],
		stats: {},
		context: {},
		created_at: createdAt,
		updated_at: createdAt,
		started_at: null,
		finished_at: null
	};
}

async function renderReady() {
	render(Page);
	const composer = browserPage.getByLabelText('Message');
	await expect.element(composer).toBeEnabled();
	return composer;
}

async function send(text: string, composer?: Awaited<ReturnType<typeof renderReady>>) {
	const activeComposer = composer ?? (await renderReady());
	await activeComposer.fill(text);
	await browserPage.getByRole('button', { name: 'Send' }).click();
}

describe('collections/[id]/assistant Research Agent', () => {
	beforeEach(() => {
		localStorage.clear();
		sessionStorage.clear();
		authState.set({
			status: 'authenticated',
			user: { user_id: session.user_id, email: 'researcher@example.test' }
		});
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/assistant')
		});
		fetchMock.mockReset();
	});

	it.each(['collection', 'account'])(
		'aborts pending feedback and ignores its response after changing %s',
		async (scope) => {
			localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);
			installApi({
				trajectory: {
					items: [message('answer', 'assistant', 'Compare matching tensile test conditions.')],
					pending_approval: null,
					feedback: []
				}
			});
			const original = fetchMock.getMockImplementation()!;
			let finish!: (response: Response) => void;
			const pending = new Promise<Response>((resolve) => {
				finish = resolve;
			});
			let signal: AbortSignal | undefined;
			fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
				if (requestPath(input).endsWith('/feedback')) {
					signal = init?.signal ?? undefined;
					return pending;
				}
				if (requestPath(input) === '/api/v1/chat-sessions')
					return Promise.resolve(
						jsonResponse({
							...session,
							session_id: 'chat_new',
							collection_id: scope === 'collection' ? 'col_456' : 'col_123',
							user_id: scope === 'account' ? 'researcher_2' : session.user_id
						})
					);
				return original(input, init);
			});
			render(Page);
			await browserPage.getByRole('button', { name: 'Helpful', exact: true }).click();
			await expect.element(browserPage.getByText('Saving...', { exact: true })).toBeVisible();
			if (scope === 'collection')
				setPage({
					params: { id: 'col_456' },
					url: new URL('http://localhost/collections/col_456/assistant')
				});
			else
				authState.set({
					status: 'authenticated',
					user: { user_id: 'researcher_2', email: 'other@example.test' }
				});
			await expect.element(browserPage.getByLabelText('Message')).toBeEnabled();
			expect(signal?.aborted).toBe(true);
			finish(jsonResponse({ detail: 'Previous feedback failed' }, 503));
			await new Promise(requestAnimationFrame);
			await expect
				.element(browserPage.getByText('Could not save feedback. Please try again.'))
				.not.toBeInTheDocument();
			await expect
				.element(browserPage.getByRole('button', { name: 'Helpful', exact: true }))
				.not.toBeInTheDocument();
		}
	);

	it.each([503, 403, 'offline'] as const)(
		'retains the selected conversation after %s and retries it',
		async (failure) => {
			localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);
			const history = [
				{
					session_id: session.session_id,
					title: 'Compare LPBF grain morphology',
					updated_at: createdAt
				}
			];
			localStorage.setItem('lens.chatSessionHistory.researcher_1:col_123', JSON.stringify(history));
			installApi({
				trajectory: {
					feedback: [],
					items: [message('restored', 'assistant', 'Original conversation recovered')],
					pending_approval: null
				}
			});
			const original = fetchMock.getMockImplementation()!;
			let unavailable = true;
			fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
				if (requestPath(input) === '/api/v1/chat-sessions/chat_1' && unavailable)
					return failure === 'offline'
						? Promise.reject(new TypeError('Failed to fetch'))
						: Promise.resolve(jsonResponse({ detail: 'Temporarily unavailable' }, failure));
				return original(input, init);
			});
			render(Page);
			await expect.element(browserPage.getByRole('alert')).toBeInTheDocument();
			expect(localStorage.getItem('lens.chatSession.researcher_1:col_123')).toBe(
				session.session_id
			);
			expect(
				JSON.parse(localStorage.getItem('lens.chatSessionHistory.researcher_1:col_123')!)
			).toEqual(history);
			expect(
				fetchMock.mock.calls.some(([input, init]) => requestMethod(input, init) === 'POST')
			).toBe(false);
			unavailable = false;
			await browserPage.getByRole('button', { name: 'Retry conversation' }).click();
			await expect
				.element(browserPage.getByText('Original conversation recovered'))
				.toBeInTheDocument();
			await expect.element(browserPage.getByLabelText('Message')).toBeEnabled();
		}
	);

	it('removes a missing session only after an explicit not-found response', async () => {
		localStorage.setItem('lens.chatSession.researcher_1:col_123', 'missing');
		localStorage.setItem(
			'lens.chatSessionHistory.researcher_1:col_123',
			JSON.stringify([
				{ session_id: 'missing', title: 'Missing conversation', updated_at: createdAt }
			])
		);
		installApi();
		const original = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) =>
			requestPath(input).endsWith('/missing')
				? Promise.resolve(jsonResponse({ detail: 'Not found' }, 404))
				: original(input, init)
		);
		await renderReady();
		expect(localStorage.getItem('lens.chatSession.researcher_1:col_123')).toBe(session.session_id);
		await expect.element(browserPage.getByText('Missing conversation')).not.toBeInTheDocument();
	});

	it('clears private conversation data on logout and isolates the next account', async () => {
		const privateTitle = 'Unpublished alloy treatment result';
		localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);
		localStorage.setItem(
			'lens.chatSessionHistory.researcher_1:col_123',
			JSON.stringify([
				{ session_id: session.session_id, title: privateTitle, updated_at: createdAt }
			])
		);
		installApi({
			trajectory: {
				feedback: [],
				items: [message('private', 'user', privateTitle)],
				pending_approval: null
			}
		});
		const original = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			if (path.endsWith('/auth/logout')) return Promise.resolve(jsonResponse({}));
			if (path.endsWith('/auth/login'))
				return Promise.resolve(
					jsonResponse({ user: { user_id: 'researcher_2', email: 'second@example.test' } })
				);
			if (path === '/api/v1/chat-sessions')
				return Promise.resolve(
					jsonResponse({ ...session, user_id: 'researcher_2', session_id: 'chat_2' }, 201)
				);
			return original(input, init);
		});
		await renderReady();
		await expect.element(browserPage.getByTestId('user-message')).toHaveTextContent(privateTitle);
		await logout();
		await expect.element(browserPage.getByLabelText('Message')).toBeDisabled();
		expect(localStorage.getItem('lens.chatSessionHistory.researcher_1:col_123')).toBeNull();
		await expect.element(browserPage.getByTestId('user-message')).not.toBeInTheDocument();
		await login('second@example.test', 'test-only');
		await expect.element(browserPage.getByLabelText('Message')).toBeEnabled();
		await expect.element(browserPage.getByText(privateTitle)).not.toBeInTheDocument();
		expect(localStorage.getItem('lens.chatSession.researcher_2:col_123')).toBe('chat_2');
	});

	it.each([true, false])(
		'consumes Source handoff only when recovery confirms persistence: %s',
		async (persisted) => {
			const source = {
				resource_ref: { resource_type: 'source', resource_id: 'doc_1:results', href: null },
				collection_id: 'col_123',
				document_id: 'doc_1',
				document_title: 'LPBF alloy study',
				source_kind: 'text_window',
				source_ref: 'results',
				page: 3,
				quote: 'The grain size decreased after heat treatment.',
				heading_path: 'Results',
				quote_truncated: false
			};
			sessionStorage.setItem('lens.chatSourceContext.researcher_1:col_123', JSON.stringify(source));
			const question = 'Explain this grain-size result';
			installApi({
				trajectory: {
					feedback: [],
					items: persisted
						? [
								message('saved_user', 'user', question, { source_contexts: [source] }),
								message('saved_answer', 'assistant', 'Recovered persisted answer')
							]
						: [],
					pending_approval: null
				},
				messageTurn: {
					status: 'completed',
					completion_reason: 'model_answer',
					warnings: [],
					messages: [
						message('next_user', 'user', 'List all papers'),
						message('next_answer', 'assistant', 'Paper list')
					],
					pending_approval: null,
					error_code: null
				}
			});
			const original = fetchMock.getMockImplementation()!;
			let submissions = 0;
			fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
				if (
					requestPath(input).endsWith('/messages') &&
					requestMethod(input, init) === 'POST' &&
					++submissions === 1
				) {
					return Promise.resolve(
						new Response('event: text_delta\ndata: {"content":"Partial answer"}\n\n', {
							headers: { 'Content-Type': 'text/event-stream' }
						})
					);
				}
				return original(input, init);
			});
			const composer = await renderReady();
			await send(question, composer);
			await expect.element(browserPage.getByRole('alert')).toBeInTheDocument();
			await expect.element(composer).toBeEnabled();
			if (persisted) {
				await expect
					.element(browserPage.getByText('Recovered persisted answer'))
					.toBeInTheDocument();
				expect(sessionStorage.getItem('lens.chatSourceContext.researcher_1:col_123')).toBeNull();
				await send('List all papers', composer);
				await expect
					.element(browserPage.getByText('Paper list', { exact: true }))
					.toBeInTheDocument();
				const posts = fetchMock.mock.calls.filter(
					([input, init]) =>
						requestPath(input).endsWith('/messages') && requestMethod(input, init) === 'POST'
				);
				expect(requestBody(posts[1][0], posts[1][1])).not.toHaveProperty('source_contexts');
			} else {
				await expect.element(composer).toHaveValue(question);
				expect(
					JSON.parse(sessionStorage.getItem('lens.chatSourceContext.researcher_1:col_123')!)
				).toEqual(source);
			}
		}
	);

	it('opens with a welcoming research prompt and a top-left workspace return link', async () => {
		installApi();
		await renderReady();

		await expect
			.element(browserPage.getByText('Hello. What would you like to investigate?'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Back to workspace' }))
			.toHaveAttribute('href', '/collections/col_123');
	});

	it.each(['creation', 'trajectory', 'failure'])(
		'ignores a stale session %s after switching collections',
		async (stage) => {
			let finish!: (response: Response) => void;
			const pending = new Promise<Response>((resolve) => {
				finish = resolve;
			});
			if (stage !== 'creation')
				localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);
			fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
				const path = requestPath(input);
				if (path === '/api/v1/chat-sessions') {
					return requestBody(input, init).collection_id === 'col_456'
						? Promise.resolve(
								jsonResponse({ ...session, session_id: 'chat_2', collection_id: 'col_456' })
							)
						: pending;
				}
				if (path.endsWith('/messages') || stage === 'failure') return pending;
				return Promise.resolve(jsonResponse(session));
			});
			render(Page);
			await vi.waitFor(() =>
				expect(fetchMock).toHaveBeenCalledTimes(stage === 'trajectory' ? 2 : 1)
			);
			setPage({
				params: { id: 'col_456' },
				url: new URL('http://localhost/collections/col_456/assistant')
			});
			await expect.element(browserPage.getByLabelText('Message')).toBeEnabled();
			finish(
				stage === 'creation'
					? jsonResponse(session)
					: stage === 'failure'
						? jsonResponse({ detail: 'Old collection unavailable' }, 503)
						: jsonResponse({
								feedback: [],
								items: [message('old', 'assistant', 'Old collection answer')],
								pending_approval: pendingCall()
							})
			);
			await new Promise(requestAnimationFrame);
			await new Promise(requestAnimationFrame);
			expect(localStorage.getItem('lens.chatSession.researcher_1:col_456')).toBe('chat_2');
			expect(
				JSON.parse(localStorage.getItem('lens.chatSessionHistory.researcher_1:col_456')!)[0]
					.session_id
			).toBe('chat_2');
			await expect.element(browserPage.getByText('Old collection answer')).not.toBeInTheDocument();
			await expect.element(browserPage.getByLabelText('Message')).toBeEnabled();
		}
	);

	it.each(['message', 'approval'])(
		'ignores a late %s result in a different collection',
		async (operation) => {
			let finish!: (response: Response) => void;
			const pending = new Promise<Response>((resolve) => {
				finish = resolve;
			});
			localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);
			installApi({
				trajectory: {
					feedback: [],
					items: [],
					pending_approval: operation === 'approval' ? pendingCall() : null
				}
			});
			const original = fetchMock.getMockImplementation()!;
			fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
				if (requestPath(input) === '/api/v1/chat-sessions')
					return Promise.resolve(
						jsonResponse({ ...session, session_id: 'chat_2', collection_id: 'col_456' })
					);
				if (requestMethod(input, init) === 'POST') return pending;
				return original(input, init);
			});
			render(Page);
			if (operation === 'message') {
				await expect.element(browserPage.getByLabelText('Message')).toBeEnabled();
				await send('Compare grain morphology', browserPage.getByLabelText('Message'));
			} else {
				await browserPage.getByRole('button', { name: 'Approve and create', exact: true }).click();
			}
			const request = fetchMock.mock.calls.find(
				([input, init]) => requestMethod(input, init) === 'POST'
			);
			setPage({
				params: { id: 'col_456' },
				url: new URL('http://localhost/collections/col_456/assistant')
			});
			await expect.element(browserPage.getByLabelText('Message')).toBeEnabled();
			expect(request?.[1]?.signal.aborted).toBe(true);
			const turn: ChatTurn = {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
				messages: [message('old', 'assistant', 'Old collection answer')],
				pending_approval: null,
				error_code: null
			};
			finish(operation === 'message' ? streamResponse(turn) : jsonResponse(turn));
			await new Promise(requestAnimationFrame);
			await new Promise(requestAnimationFrame);
			await expect.element(browserPage.getByText('Old collection answer')).not.toBeInTheDocument();
			await expect.element(browserPage.getByLabelText('Message')).toBeEnabled();
			expect(localStorage.getItem('lens.chatSession.researcher_1:col_456')).toBe('chat_2');
		}
	);

	it('finishes an active paper in its original collection without starting remaining uploads after navigation', async () => {
		let finish!: (response: Response) => void;
		const pending = new Promise<Response>((resolve) => {
			finish = resolve;
		});
		installApi({
			uploadDocument: () => pending,
			prepareDocument: (id) => jsonResponse(queuedPreparation(id), 202)
		});
		const original = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			if (
				requestPath(input) === '/api/v1/chat-sessions' &&
				requestBody(input, init)?.collection_id === 'col_456'
			) {
				return Promise.resolve(
					jsonResponse({ ...session, session_id: 'chat_2', collection_id: 'col_456' })
				);
			}
			return original(input, init);
		});
		await renderReady();
		const file = new File(['%PDF-1.7'], 'alloy-study.pdf', { type: 'application/pdf' });
		await browserPage
			.getByLabelText('Choose PDF papers')
			.upload([file, new File(['%PDF-1.7 next'], 'next-study.pdf', { type: 'application/pdf' })]);
		await browserPage.getByRole('button', { name: 'Upload and prepare 2 papers' }).click();
		setPage({
			params: { id: 'col_456' },
			url: new URL('http://localhost/collections/col_456/assistant')
		});
		await expect.element(browserPage.getByLabelText('Message')).toBeEnabled();
		finish(jsonResponse(uploadedDocument(file), 201));
		await vi.waitFor(() =>
			expect(
				fetchMock.mock.calls.some(([input]) =>
					requestPath(input).endsWith('/col_123/documents/doc_upload_1/preparation')
				)
			).toBe(true)
		);
		await new Promise(requestAnimationFrame);
		expect(
			fetchMock.mock.calls.filter(([input]) => requestPath(input).endsWith('/documents'))
		).toHaveLength(1);
		await expect.element(browserPage.getByText('alloy-study.pdf')).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Preparation queued')).not.toBeInTheDocument();
		await expect.element(browserPage.getByRole('button', { name: 'Add papers' })).toBeEnabled();
	});

	it('does not prepare an uploaded paper after the originating account signs out', async () => {
		let finish!: (response: Response) => void;
		const pending = new Promise<Response>((resolve) => {
			finish = resolve;
		});
		installApi({
			uploadDocument: () => pending,
			prepareDocument: (id) => jsonResponse(queuedPreparation(id), 202)
		});
		const original = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) =>
			requestPath(input).endsWith('/auth/logout')
				? Promise.resolve(jsonResponse({}))
				: original(input, init)
		);
		await renderReady();
		const file = new File(['%PDF-1.7'], 'alloy-study.pdf', { type: 'application/pdf' });
		await browserPage.getByLabelText('Choose PDF papers').upload(file);
		await browserPage
			.getByRole('button', { name: 'Upload and prepare 1 paper', exact: true })
			.click();
		await logout();
		await expect.element(browserPage.getByLabelText('Message')).toBeDisabled();
		finish(jsonResponse(uploadedDocument(file), 201));
		await new Promise(requestAnimationFrame);
		await new Promise(requestAnimationFrame);
		expect(
			fetchMock.mock.calls.some(([input]) => requestPath(input).endsWith('/preparation'))
		).toBe(false);
		await expect.element(browserPage.getByText('alloy-study.pdf')).not.toBeInTheDocument();
	});

	it('uploads PDF papers into the current collection and queues preparation outside Chat', async () => {
		installApi({
			uploadDocument: (file) => jsonResponse(uploadedDocument(file), 201),
			prepareDocument: (documentId) => jsonResponse(queuedPreparation(documentId), 202)
		});
		await renderReady();

		const file = new File(['%PDF-1.7 paper content'], 'laser-exposure.pdf', {
			type: 'application/pdf'
		});
		await browserPage.getByLabelText('Choose PDF papers').upload(file);

		await expect.element(browserPage.getByText('laser-exposure.pdf')).toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Upload and prepare 1 paper' }).click();

		await expect.element(browserPage.getByText('Preparation queued')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open collection progress' }))
			.toHaveAttribute('href', '/collections/col_123');
		expect(
			fetchMock.mock.calls.some(
				([input, init]) =>
					requestPath(input as string | URL | Request) ===
						'/api/v1/collections/col_123/documents' &&
					requestMethod(input as string | URL | Request, init as RequestInit) === 'POST'
			)
		).toBe(true);
		expect(
			fetchMock.mock.calls.some(
				([input, init]) =>
					requestPath(input as string | URL | Request) ===
						'/api/v1/collections/col_123/documents/doc_upload_1/preparation' &&
					requestMethod(input as string | URL | Request, init as RequestInit) === 'POST'
			)
		).toBe(true);
		expect(
			fetchMock.mock.calls.filter(
				([input, init]) =>
					requestPath(input as string | URL | Request).endsWith('/messages') &&
					requestMethod(input as string | URL | Request, init as RequestInit) === 'POST'
			)
		).toHaveLength(0);
	});

	it('keeps upload controls disabled while a paper is being stored', async () => {
		let finishUpload: ((response: Response) => void) | undefined;
		const uploadPending = new Promise<Response>((resolve) => {
			finishUpload = resolve;
		});
		installApi({
			uploadDocument: () => uploadPending,
			prepareDocument: (documentId) => jsonResponse(queuedPreparation(documentId), 202)
		});
		await renderReady();

		const file = new File(['%PDF-1.7'], 'pending.pdf', { type: 'application/pdf' });
		await browserPage.getByLabelText('Choose PDF papers').upload(file);
		await browserPage.getByRole('button', { name: 'Upload and prepare 1 paper' }).click();
		await expect
			.element(browserPage.getByRole('button', { name: 'Uploading papers...' }))
			.toBeDisabled();
		await expect.element(browserPage.getByRole('button', { name: 'Add papers' })).toBeDisabled();

		finishUpload?.(jsonResponse(uploadedDocument(file), 201));
		await expect.element(browserPage.getByText('Preparation queued')).toBeInTheDocument();
	});

	it('reports an upload failure beside the paper without hiding the retry path', async () => {
		installApi({
			uploadDocument: () => jsonResponse({ detail: 'PDF exceeds the upload limit' }, 413)
		});
		await renderReady();

		const file = new File(['%PDF-1.7'], 'oversized.pdf', { type: 'application/pdf' });
		await browserPage.getByLabelText('Choose PDF papers').upload(file);
		await browserPage.getByRole('button', { name: 'Upload and prepare 1 paper' }).click();

		await expect.element(browserPage.getByText('Upload failed')).toBeInTheDocument();
		await expect.element(browserPage.getByText(/PDF exceeds the upload limit/)).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Retry failed paper' }))
			.toBeEnabled();
	});

	it('marks a paper already in the collection without presenting it as a retryable failure', async () => {
		installApi({
			uploadDocument: () =>
				jsonResponse({ detail: 'document content already exists in collection' }, 400)
		});
		await renderReady();

		const file = new File(['%PDF-1.7'], 'already-uploaded.pdf', { type: 'application/pdf' });
		await browserPage.getByLabelText('Choose PDF papers').upload(file);
		await browserPage.getByRole('button', { name: 'Upload and prepare 1 paper' }).click();

		await expect
			.element(browserPage.getByText('Already in this collection', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Retry failed paper' }))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('document content already exists in collection'))
			.not.toBeInTheDocument();
	});

	it('retries preparation without uploading the paper a second time', async () => {
		let uploadCalls = 0;
		let preparationCalls = 0;
		installApi({
			uploadDocument: (file) => {
				uploadCalls += 1;
				return jsonResponse(uploadedDocument(file), 201);
			},
			prepareDocument: (documentId) => {
				preparationCalls += 1;
				return preparationCalls === 1
					? jsonResponse({ detail: 'Preparation worker unavailable' }, 503)
					: jsonResponse(queuedPreparation(documentId), 202);
			}
		});
		await renderReady();

		const file = new File(['%PDF-1.7'], 'retry-preparation.pdf', { type: 'application/pdf' });
		await browserPage.getByLabelText('Choose PDF papers').upload(file);
		await browserPage.getByRole('button', { name: 'Upload and prepare 1 paper' }).click();

		await expect
			.element(browserPage.getByText('Uploaded, but preparation could not be queued'))
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Retry failed paper' }).click();
		await expect.element(browserPage.getByText('Preparation queued')).toBeInTheDocument();
		expect(uploadCalls).toBe(1);
		expect(preparationCalls).toBe(2);
	});

	it('rejects non-PDF attachments before they reach the collection API', async () => {
		installApi();
		await renderReady();

		const file = new File(['plain text'], 'notes.txt', { type: 'text/plain' });
		await browserPage.getByLabelText('Choose PDF papers').upload(file);

		await expect
			.element(browserPage.getByText('Only PDF papers can be uploaded here.'))
			.toBeInTheDocument();
		expect(
			fetchMock.mock.calls.some(
				([input, init]) =>
					requestPath(input as string | URL | Request) ===
						'/api/v1/collections/col_123/documents' &&
					requestMethod(input as string | URL | Request, init as RequestInit) === 'POST'
			)
		).toBe(false);
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
			source_kind: 'text_window',
			source_ref: 'results',
			page: 3,
			quote: 'Conductivity improved to 12 mS/cm under EIS.',
			heading_path: 'Results',
			quote_truncated: true
		};
		sessionStorage.setItem(
			'lens.chatSourceContext.researcher_1:col_123',
			JSON.stringify(sourceContext)
		);
		installApi({
			messageTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
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
		expect(sessionStorage.getItem('lens.chatSourceContext.researcher_1:col_123')).toBeNull();
	});

	it('lets the researcher remove handed-off Source context before sending', async () => {
		sessionStorage.setItem(
			'lens.chatSourceContext.researcher_1:col_123',
			JSON.stringify({
				resource_ref: {
					resource_type: 'source',
					resource_id: 'doc_1:results',
					href: '/collections/col_123/documents/doc_1?source_ref=results'
				},
				collection_id: 'col_123',
				document_id: 'doc_1',
				document_title: 'Paper A',
				source_kind: 'text_window',
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
		expect(sessionStorage.getItem('lens.chatSourceContext.researcher_1:col_123')).toBeNull();
	});

	it('handles ordinary conversation without showing capability activity', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
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

	it('keeps a bounded final answer visible without reporting it as a failed turn', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				completion_reason: 'resource_budget',
				warnings: ['Some papers remain unread.'],
				messages: [
					message('msg_user_limited', 'user', 'Compare the papers'),
					message(
						'msg_assistant_limited',
						'assistant',
						'The inspected Sources support a preliminary comparison; two papers remain unread.'
					)
				],
				pending_approval: null,
				error_code: null
			}
		});

		await send('Compare the papers');

		await expect
			.element(
				browserPage.getByText(
					'The inspected Sources support a preliminary comparison; two papers remain unread.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'The Agent reached its reading limit; the answer above is based on the completed inspection.'
				)
			)
			.toBeInTheDocument();
		expect(document.querySelector('[role="alert"]')).toBeNull();
	});

	it('allows a second question after the first turn is persisted', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
				messages: [
					message('msg_user_repeat', 'user', 'First question'),
					message('msg_assistant_repeat', 'assistant', 'First answer')
				],
				pending_approval: null,
				error_code: null
			}
		});

		const composer = await renderReady();
		await send('First question', composer);
		await expect.element(browserPage.getByText('First answer')).toBeInTheDocument();
		await expect.element(browserPage.getByLabelText('Message')).toBeEnabled();
		await send('Follow-up question', composer);
		await expect.element(browserPage.getByText('First answer')).toBeInTheDocument();
		expect(
			fetchMock.mock.calls.filter(
				([input, init]) =>
					requestPath(input as string | URL | Request).endsWith('/messages') &&
					requestMethod(input as string | URL | Request, init as RequestInit) === 'POST'
			)
		).toHaveLength(2);
	});

	it('shows assistant text before the persisted turn finishes streaming', async () => {
		installApi({
			messageDeltas: ['Partial answer', ' complete.'],
			messageDelayMs: 100,
			messageTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
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

	it('updates elapsed time during a live wait and removes progress when the answer finishes', async () => {
		installApi();
		const composer = await renderReady();
		const encoder = new TextEncoder();
		let output!: ReadableStreamDefaultController<Uint8Array>;
		const body = new ReadableStream<Uint8Array>({
			start(controller) {
				output = controller;
			}
		});
		fetchMock.mockResolvedValueOnce(
			new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
		);
		await composer.fill('Check the heat-treatment evidence');
		await browserPage.getByRole('button', { name: 'Send' }).click();
		const progress = browserPage.getByTestId('research-progress');
		try {
			for (const elapsed of [15000, 30000]) {
				output.enqueue(
					encoder.encode(
						`event: progress\ndata: ${JSON.stringify({
							phase: 'waiting',
							cycle_index: 2,
							executed_tool_count: 5,
							elapsed_ms: elapsed
						})}\n\n`
					)
				);
				await expect.element(progress).toHaveTextContent('Waiting for the research model');
				await expect.element(progress).toHaveTextContent(`${elapsed / 1000}s`);
			}
			const turn: ChatTurn = {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
				messages: [
					message(
						'msg_wait_answer',
						'assistant',
						'The evidence needs separate HT and HIP comparisons.'
					)
				],
				pending_approval: null,
				error_code: null
			};
			output.enqueue(encoder.encode(`event: turn\ndata: ${JSON.stringify(turn)}\n\n`));
		} finally {
			output.close();
		}
		await expect.element(progress).not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('The evidence needs separate HT and HIP comparisons.'))
			.toBeInTheDocument();
	});

	it('preserves a researcher-expanded activity while the next answer streams', async () => {
		installApi({
			trajectory: {
				feedback: [],
				items: [
					message('msg_call_1', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: 'call_read_1',
								name: 'query_published_findings',
								arguments: { query: 'energy input' },
								position: 0
							}
						]
					}),
					message('msg_result_1', 'tool', '', {
						tool_call_id: 'call_read_1',
						tool_result: {
							tool_call_id: 'call_read_1',
							status: 'succeeded',
							data: { finding_count: 2, evidence_count: 8 },
							resource_refs: [],
							warnings: [],
							error_code: null,
							error_message: null
						}
					})
				],
				pending_approval: null
			},
			messageDeltas: ['Following up', ' with source context.'],
			messageDelayMs: 100,
			messageTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
				messages: [
					message('msg_user_stream', 'user', 'Explain the first finding'),
					message('msg_assistant_stream', 'assistant', 'Following up with source context.')
				],
				pending_approval: null,
				error_code: null
			}
		});
		localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);

		const composer = await renderReady();
		const activity = document.querySelector<HTMLDetailsElement>(
			'[data-testid="research-activity"]'
		);
		expect(activity?.open).toBe(false);
		activity?.querySelector<HTMLElement>('summary')?.click();
		expect(activity?.open).toBe(true);

		await composer.fill('Explain the first finding');
		await browserPage.getByRole('button', { name: 'Send' }).click();

		await expect
			.element(browserPage.getByText('Following up', { exact: true }))
			.toBeInTheDocument();
		expect(activity?.open).toBe(true);
		await expect
			.element(browserPage.getByText('Following up with source context.', { exact: true }))
			.toBeInTheDocument();
		expect(activity?.open).toBe(true);
	});

	it('renders a read capability result separately from the final answer', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'What findings are available?'),
					message('msg_call_1', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: 'call_read_1',
								name: 'query_published_findings',
								arguments: { query: 'energy input' },
								position: 0
							}
						]
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
							warnings: [],
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

		await expect.element(browserPage.getByTestId('research-activity')).toBeInTheDocument();
		const activity = document.querySelector<HTMLDetailsElement>(
			'[data-testid="research-activity"]'
		);
		expect(document.querySelectorAll('[data-testid="research-activity"]')).toHaveLength(1);
		expect(activity?.open).toBe(false);
		activity?.querySelector<HTMLElement>('summary')?.click();
		await expect
			.element(browserPage.getByText('Published findings completed', { exact: true }))
			.toBeVisible();
		await expect.element(browserPage.getByText('2 findings · 8 evidence records')).toBeVisible();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open finding' }))
			.toHaveAttribute('href', '/collections/col_123/objectives/obj_1?finding_id=finding_1');
		await expect
			.element(browserPage.getByText('Two published findings address this question.'))
			.toBeInTheDocument();
	});

	it('keeps a persisted tool request visible while its result is pending', async () => {
		installApi({
			trajectory: {
				feedback: [],
				items: [
					message('msg_call_1', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: 'call_read_1',
								name: 'query_published_findings',
								arguments: { query: 'energy input' },
								position: 0
							}
						]
					})
				],
				pending_approval: null
			}
		});
		localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);

		await renderReady();

		await expect.element(browserPage.getByTestId('research-activity')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Research action prepared', { exact: true }))
			.toBeVisible();
		await expect
			.element(browserPage.getByText('Published findings', { exact: true }))
			.toBeVisible();
	});

	it('opens routine research activity when a warning needs review', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Check the published findings'),
					message('msg_call_1', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: 'call_read_1',
								name: 'query_published_findings',
								arguments: {},
								position: 0
							}
						]
					}),
					message('msg_result_1', 'tool', '', {
						tool_call_id: 'call_read_1',
						tool_result: {
							tool_call_id: 'call_read_1',
							status: 'succeeded',
							data: { finding_count: 2, evidence_count: 8 },
							resource_refs: [],
							warnings: ['One paper used a different heat treatment.'],
							error_code: null,
							error_message: null
						}
					})
				],
				pending_approval: null,
				error_code: null
			}
		});

		await send('Check the published findings');

		await expect.element(browserPage.getByTestId('research-activity')).toBeInTheDocument();
		const activity = document.querySelector<HTMLDetailsElement>(
			'[data-testid="research-activity"]'
		);
		expect(activity?.open).toBe(true);
		await expect
			.element(browserPage.getByText('One paper used a different heat treatment.'))
			.toBeVisible();
	});

	it('shows one complete published finding and its linked evidence count', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Review this finding'),
					message('msg_call_1', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: 'call_finding_1',
								name: 'inspect_published_finding',
								arguments: {
									objective_id: 'obj_1',
									analysis_version: 2,
									finding_id: 'finding_1'
								},
								position: 0
							}
						]
					}),
					message('msg_result_1', 'tool', '', {
						tool_call_id: 'call_finding_1',
						tool_result: {
							tool_call_id: 'call_finding_1',
							status: 'succeeded',
							data: {
								finding: { statement: 'Higher energy input reduced elongation.' },
								evidence_total: 3
							},
							resource_refs: [],
							warnings: [],
							error_code: null,
							error_message: null
						}
					}),
					message('msg_assistant_2', 'assistant', 'The conclusion is ready for source review.')
				],
				pending_approval: null,
				error_code: null
			}
		});

		await send('Review this finding');

		await expect
			.element(browserPage.getByText('Finding and evidence review completed'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Complete finding · 3 linked evidence records'))
			.toBeInTheDocument();
	});

	it('shows the canonical research process without technical recovery details', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'How far has the collection analysis progressed?'),
					message('msg_call_1', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: 'call_process_1',
								name: 'inspect_research_process',
								arguments: {},
								position: 0
							}
						]
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
				completion_reason: 'model_answer',
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Start understanding these papers'),
					message('msg_call_1', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: 'call_queued_1',
								name: 'start_research_process',
								arguments: {},
								position: 0
							}
						]
					}),
					message('msg_result_1', 'tool', '', {
						tool_call_id: 'call_queued_1',
						tool_result: {
							tool_call_id: 'call_queued_1',
							status: 'queued',
							data: {},
							resource_refs: [
								{
									resource_type: 'pipeline_run',
									resource_id: 'run_1',
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
		await expect.element(browserPage.getByText('In progress')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Run queued. You can continue while it executes.'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open literature analysis' }))
			.toHaveAttribute('href', '/collections/col_123');
	});

	it('shows objective drafts as proposals without creating Core records', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Suggest objectives'),
					message('msg_call_1', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: 'call_draft_1',
								name: 'propose_objective_drafts',
								arguments: { question: 'energy input effects' },
								position: 0
							}
						]
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
		expect(document.querySelectorAll('[data-testid="research-artifact"]')).toHaveLength(1);
		expect(
			fetchMock.mock.calls.some(([input]) =>
				requestPath(input as string | URL | Request).includes('/objectives')
			)
		).toBe(false);
	});

	it('shows Source-grounded drafts and complete table results for review', async () => {
		installApi({
			messageTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Inspect this table and draft evidence'),
					message('msg_call_table', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{ tool_call_id: 'call_table', name: 'inspect_table', arguments: {}, position: 0 }
						]
					}),
					message('msg_result_table', 'tool', '', {
						tool_call_id: 'call_table',
						tool_result: {
							...baseToolResult('call_table'),
							data: {
								data_row_count: 2,
								column_count: 3,
								table_markdown:
									'| Condition | Result | Unit |\n| --- | --- | --- |\n| P150 | 82 | % |'
							}
						}
					}),
					message('msg_call_source', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{ tool_call_id: 'call_source', name: 'read_source', arguments: {}, position: 0 }
						]
					}),
					message('msg_result_source', 'tool', '', {
						tool_call_id: 'call_source',
						tool_result: {
							...baseToolResult('call_source'),
							data: {
								source_ref: 'results_4',
								content: 'The P150 condition reached 82% elongation.',
								content_truncated: true,
								next_offset: 8
							}
						}
					}),
					message('msg_call_draft', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: 'call_draft',
								name: 'create_evidence_draft',
								arguments: {},
								position: 0
							}
						]
					}),
					message('msg_result_draft', 'tool', '', {
						tool_call_id: 'call_draft',
						tool_result: {
							...baseToolResult('call_draft'),
							data: {
								draft: {
									source_ref: 'table_2',
									source_kind: 'table',
									evidence_role: 'direct_result',
									source_excerpt: 'P150 elongation was 82%.',
									changed_variables: [{ name: 'preheat', target_value: 150 }]
								}
							}
						}
					})
				],
				pending_approval: null,
				error_code: null
			}
		});

		await send('Inspect this table and draft evidence');

		await expect.element(browserPage.getByText('Complete Source table')).toBeInTheDocument();
		await expect.element(browserPage.getByText('P150 | 82 | %')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Complete Source content')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('The P150 condition reached 82% elongation.'))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'This Source is bounded; ask the Agent to continue from the returned offset before treating it as complete.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Evidence draft completed' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('table_2')).toBeInTheDocument();
		await expect.element(browserPage.getByText('P150 elongation was 82%.')).toBeInTheDocument();
	});

	it('uses the research-plan approval boundary and wording', async () => {
		const call = pendingCall({
			tool_call_id: 'call_plan',
			name: 'create_research_plan',
			arguments: {
				objective_id: 'obj_1',
				title: 'Validate the preheat effect',
				source_snapshots: [{ finding_id: 'finding_1', analysis_version: 2 }]
			}
		});
		installApi({
			messageTurn: {
				status: 'approval_required',
				completion_reason: null,
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Save the research plan'),
					message('msg_call_plan', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call,
				error_code: null
			}
		});

		await send('Save the research plan');

		await expect
			.element(browserPage.getByText('Save research plan', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Persist this research-plan draft only after checking its Finding and Evidence snapshots. The saved plan remains a researcher-reviewable draft.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and save research plan' }))
			.toBeInTheDocument();
	});

	it('shows exact write arguments and blocks new messages while approval is pending', async () => {
		const call = pendingCall();
		installApi({
			messageTurn: {
				status: 'approval_required',
				completion_reason: null,
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Create the grain objective'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
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
		expect(document.querySelectorAll('[data-testid="research-activity"]')).toHaveLength(0);
		await expect.element(browserPage.getByLabelText('Message')).toBeDisabled();
		await expect.element(browserPage.getByRole('button', { name: 'Reject' })).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and create' }))
			.toBeInTheDocument();
	});

	it('shows exact finding feedback before recording the human review', async () => {
		const call = pendingCall({
			name: 'record_finding_feedback',
			arguments: {
				objective_id: 'obj_1',
				analysis_version: 2,
				finding_id: 'finding_1',
				review_status: 'partial',
				issue_type: 'overclaim',
				note: 'The direction is supported, but the wording is too broad.'
			}
		});
		installApi({
			messageTurn: {
				status: 'approval_required',
				completion_reason: null,
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Record this as partly correct'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call,
				error_code: null
			}
		});

		await send('Record this as partly correct');

		await expect
			.element(browserPage.getByText('Finding feedback', { exact: true }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('partial', { exact: true })).toBeInTheDocument();
		await expect.element(browserPage.getByText('overclaim', { exact: true })).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('The direction is supported, but the wording is too broad.'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and record review' }))
			.toBeInTheDocument();
	});

	it('shows the complete finding revision before reusing the human curation path', async () => {
		const revisedStatement =
			'For the reported conditions, higher energy input was associated with lower elongation.';
		const call = pendingCall({
			name: 'curate_finding',
			arguments: {
				objective_id: 'obj_1',
				analysis_version: 2,
				finding_id: 'finding_1',
				curated_status: 'limited',
				curated_finding: {
					collection_id: 'col_123',
					objective_id: 'obj_1',
					analysis_version: 2,
					finding_id: 'finding_1',
					statement: revisedStatement,
					paper_contributions: [{ document_id: 'doc_1', supporting_evidence_ids: ['ev_1'] }]
				},
				note: 'Narrowed the conclusion to the reported conditions.'
			}
		});
		installApi({
			messageTurn: {
				status: 'approval_required',
				completion_reason: null,
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Narrow this conclusion'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call,
				error_code: null
			}
		});

		await send('Narrow this conclusion');

		await expect
			.element(browserPage.getByText('Finding curation', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText(revisedStatement, { exact: false }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and save revision' }))
			.toBeInTheDocument();
	});

	it('shows the exact evidence-backed Finding before publishing a new version', async () => {
		const statement = 'Higher temperature is associated with greater strength.';
		const call = pendingCall({
			name: 'create_finding_version',
			arguments: {
				objective_id: 'obj_1',
				source_analysis_version: 2,
				statement,
				assertion_strength: 'associative',
				supporting_evidence_ids: ['evidence_1'],
				contradicting_evidence_ids: [],
				context_evidence_ids: ['evidence_2'],
				condition_boundary_evidence_ids: ['evidence_2'],
				limitations: ['Only one paper directly supports this conclusion.'],
				parent_finding_id: null,
				abstention_reason: null
			}
		});
		installApi({
			messageTurn: {
				status: 'approval_required',
				completion_reason: null,
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Create this conclusion'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call,
				error_code: null
			}
		});

		await send('Create this conclusion');

		await expect
			.element(browserPage.getByText('Finding authoring', { exact: true }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText(statement, { exact: true })).toBeInTheDocument();
		await expect.element(browserPage.getByText('evidence_1', { exact: true })).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Publish this conclusion as a new immutable analysis version. The current system result will remain unchanged.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and publish Finding' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByLabelText('Message')).toBeDisabled();
	});

	it('shows Source-grounded Evidence authoring as a distinct approved action', async () => {
		const call = pendingCall({
			name: 'create_evidence_version',
			arguments: {
				objective_id: 'obj_1',
				source_analysis_version: 2,
				document_id: 'doc_1',
				source_kind: 'text_window',
				source_ref: 'block_results',
				source_excerpt: 'Higher temperature increased strength to 620 MPa.',
				source_digest: 'a'.repeat(64),
				evidence_role: 'direct_result',
				changed_variables: [{ name: 'temperature', baseline_value: 400, target_value: 500 }],
				comparison: null,
				reported_result: {
					outcome: 'strength',
					direction: 'increase',
					result_text: 'Higher temperature increased strength to 620 MPa.'
				},
				attribution_scope: 'association_only',
				scientific_context: {
					material: [],
					sample: [],
					process: [],
					test: []
				},
				supersedes_evidence_id: null,
				authoring_note: null
			}
		});
		installApi({
			messageTurn: {
				status: 'approval_required',
				completion_reason: null,
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Record this source as Evidence'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call,
				error_code: null
			}
		});

		await send('Record this source as Evidence');

		await expect
			.element(browserPage.getByText('Evidence authoring', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText('Higher temperature increased strength to 620 MPa.', { exact: true })
			)
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Publish this Source-grounded Evidence as a new immutable analysis version. A revision keeps the previous Evidence and Findings unchanged.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and publish Evidence' }))
			.toBeInTheDocument();
	});

	it('distinguishes Agent-authored paper analysis from automatic analysis', async () => {
		const call = pendingCall({
			name: 'publish_agent_objective_analysis',
			arguments: {
				objective_id: 'obj_1',
				document_ids: ['doc_1'],
				paper_summaries: [
					{
						document_id: 'doc_1',
						relevance: 'high',
						paper_role: 'primary_experiment',
						contribution_summary: 'Reports one source-backed porosity comparison.',
						confidence: 0.9
					}
				],
				evidence_drafts: [
					{
						draft_id: 'draft_1',
						document_id: 'doc_1',
						source_kind: 'text_window',
						source_ref: 'block_results',
						source_excerpt: 'Porosity decreased from 1.8% to 0.7%.',
						source_digest: 'a'.repeat(64),
						evidence_role: 'direct_result',
						changed_variables: [{ name: 'laser power' }],
						comparison: null,
						reported_result: {
							outcome: 'porosity',
							direction: 'decrease',
							result_text: 'Porosity decreased from 1.8% to 0.7%.'
						},
						attribution_scope: 'association_only',
						scientific_context: { material: [], sample: [], process: [], test: [] },
						confidence: 0.9
					}
				]
			}
		});
		installApi({
			messageTurn: {
				status: 'approval_required',
				completion_reason: null,
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Read these papers and analyze the question yourself'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call,
				error_code: null
			}
		});

		await send('Read these papers and analyze the question yourself');

		await expect
			.element(browserPage.getByText('Agent paper analysis', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					"Publish the Agent's complete paper-by-paper analysis after Lens revalidates every Source excerpt and Evidence record. No Finding will be created yet."
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and publish analysis' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByLabelText('Message')).toBeDisabled();
	});

	it('presents evidence abstention without implying that a Finding will be created', async () => {
		const call = pendingCall({
			name: 'create_finding_version',
			arguments: {
				objective_id: 'obj_1',
				source_analysis_version: 2,
				statement: null,
				assertion_strength: null,
				supporting_evidence_ids: [],
				contradicting_evidence_ids: [],
				context_evidence_ids: [],
				condition_boundary_evidence_ids: [],
				limitations: ['The reported test conditions are not comparable.'],
				parent_finding_id: null,
				abstention_reason: 'no_comparable_evidence'
			}
		});
		installApi({
			messageTurn: {
				status: 'approval_required',
				completion_reason: null,
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Record that these results cannot be compared'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call,
				error_code: null
			}
		});

		await send('Record that these results cannot be compared');

		await expect
			.element(
				browserPage.getByText(
					'Publish this evidence abstention as a new immutable analysis version without creating a placeholder Finding.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and publish evidence decision' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve and publish Finding' }))
			.not.toBeInTheDocument();
	});

	it('rejects finding feedback without implying that a review was recorded', async () => {
		const call = pendingCall({
			name: 'record_finding_feedback',
			arguments: {
				objective_id: 'obj_1',
				analysis_version: 2,
				finding_id: 'finding_1',
				review_status: 'unclear',
				issue_type: 'none'
			}
		});
		installApi({
			trajectory: {
				feedback: [],
				items: [
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call
			},
			decisionTurn: {
				status: 'rejected',
				completion_reason: null,
				warnings: [],
				messages: [],
				pending_approval: null,
				error_code: null
			}
		});
		localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);
		render(Page);

		await browserPage.getByRole('button', { name: 'Reject' }).click();

		await expect
			.element(browserPage.getByText('The research conclusion review was not recorded.'))
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
				completion_reason: null,
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Start understanding these papers'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
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
				completion_reason: null,
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Analyze this question'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
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

	it('requires a separate approval to confirm a research question without starting analysis', async () => {
		const call = pendingCall({
			name: 'confirm_objective',
			arguments: { objective_id: 'obj_energy_1' }
		});
		installApi({
			messageTurn: {
				status: 'approval_required',
				completion_reason: null,
				warnings: [],
				messages: [
					message('msg_user_1', 'user', 'Confirm this research question'),
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call,
				error_code: null
			}
		});

		await send('Confirm this research question');

		await expect
			.element(browserPage.getByText('Research question confirmation', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Confirm this reviewed research question without starting its analysis.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Approve confirmation' }))
			.toBeInTheDocument();
	});

	it('records a rejected literature-analysis start without implying that work ran', async () => {
		const call = pendingCall({
			name: 'start_research_process',
			arguments: {}
		});
		installApi({
			trajectory: {
				feedback: [],
				items: [
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call
			},
			decisionTurn: {
				status: 'rejected',
				completion_reason: null,
				warnings: [],
				messages: [],
				pending_approval: null,
				error_code: null
			}
		});
		localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);
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
				feedback: [],
				items: [
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call
			},
			decisionTurn: {
				status: 'rejected',
				completion_reason: null,
				warnings: [],
				messages: [],
				pending_approval: null,
				error_code: null
			}
		});
		localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);
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
				feedback: [],
				items: [
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
					})
				],
				pending_approval: call
			},
			decisionTurn: {
				status: 'completed',
				completion_reason: 'model_answer',
				warnings: [],
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
		localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);
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
		localStorage.setItem('lens.chatSession.researcher_1:col_123', session.session_id);
		installApi({
			trajectory: {
				feedback: [],
				items: [
					message('msg_call_write', 'assistant', '', {
						tool_call_id: null,
						tool_calls: [
							{
								tool_call_id: call.tool_call_id,
								name: call.name,
								arguments: call.arguments,
								position: 0
							}
						]
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
		fetchMock.mockImplementationOnce(() =>
			Promise.resolve(
				jsonResponse({ user: { user_id: session.user_id, email: 'researcher@example.test' } })
			)
		);
		await fetchCurrentSession();

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
