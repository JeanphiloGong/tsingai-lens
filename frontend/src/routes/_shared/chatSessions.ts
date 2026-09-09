import { buildApiUrl, requestJson, throwApiError } from './api';

export type ChatResourceRef = {
	resource_type: string;
	resource_id: string;
	href: string | null;
};

export type ChatSourceContext = {
	resource_ref: ChatResourceRef;
	collection_id: string;
	document_id: string;
	document_title: string;
	source_kind: string;
	source_ref: string;
	page: number | null;
	quote: string;
	heading_path: string | null;
	quote_truncated: boolean;
	source_digest?: string | null;
};

export type ChatToolResult = {
	tool_call_id: string;
	status: 'succeeded' | 'queued' | 'failed';
	data: Record<string, unknown>;
	resource_refs: ChatResourceRef[];
	warnings: string[];
	error_code: string | null;
	error_message: string | null;
};

export type ChatToolRequest = {
	tool_call_id: string;
	name: string;
	arguments: Record<string, unknown>;
	position: number;
};

export type ChatMessage = {
	message_id: string;
	session_id: string;
	role: 'user' | 'assistant' | 'tool';
	content: string;
	created_at: string;
	tool_call_id: string | null;
	tool_calls: ChatToolRequest[];
	tool_result: ChatToolResult | null;
	source_contexts: ChatSourceContext[];
};

export type ChatSession = {
	session_id: string;
	user_id: string;
	collection_id: string;
	created_at: string;
	updated_at: string;
	root_session_id?: string | null;
	parent_session_id?: string | null;
	fork_message_id?: string | null;
	fork_position?: number | null;
	fork_content?: string | null;
};

export type ChatBranchOptions = {
	message_id: string;
	session_ids: string[];
	active_session_id: string;
};

export type ChatToolCall = {
	tool_call_id: string;
	session_id: string;
	assistant_message_id: string;
	position: number;
	name: string;
	arguments: Record<string, unknown>;
	arguments_digest: string;
	risk: 'unknown' | 'read' | 'draft' | 'write';
	status:
		| 'requested'
		| 'approval_required'
		| 'approved'
		| 'running'
		| 'succeeded'
		| 'failed'
		| 'rejected';
	started_at: string | null;
	finished_at: string | null;
	error_code: string | null;
	decision_user_id: string | null;
	decision_arguments_digest: string | null;
	decided_at: string | null;
};

export type ChatTurn = {
	status: 'completed' | 'approval_required' | 'failed' | 'rejected';
	completion_reason:
		| 'model_answer'
		| 'resource_budget'
		| 'no_progress'
		| 'emergency_ceiling'
		| null;
	warnings: string[];
	messages: ChatMessage[];
	pending_approval: ChatToolCall | null;
	error_code: string | null;
};

export type ChatTrajectory = {
	items: ChatMessage[];
	pending_approval: ChatToolCall | null;
	feedback: ChatMessageFeedback[];
	branches: ChatBranchOptions[];
	branch_draft: ChatMessage | null;
	running: boolean;
};

export type ChatFeedbackReason = 'incorrect' | 'incomplete' | 'unclear' | 'other';
export type ChatFeedbackInput = {
	rating: 'helpful' | 'not_helpful' | null;
	reason?: ChatFeedbackReason | null;
	comment?: string | null;
};
export type ChatMessageFeedback = {
	feedback_id: string;
	session_id: string;
	message_id: string;
	user_id: string;
	rating: 'helpful' | 'not_helpful';
	reason: ChatFeedbackReason | null;
	comment: string | null;
	response_digest: string;
	created_at: string;
	updated_at: string;
};
export type ChatFeedbackState = {
	feedback: ChatMessageFeedback | null;
	saving: boolean;
	error: string;
};

export type ChatProgress = {
	phase: string;
	cycle_index?: number;
	selected_capability_names?: string[];
	requested_tool_count?: number;
	executed_tool_count?: number;
	elapsed_ms?: number;
	remaining_tool_budget?: number;
	remaining_token_budget?: number;
};

export function formatChatElapsed(elapsedMs?: number) {
	if (!Number.isFinite(elapsedMs)) return '';
	const totalSeconds = Math.max(0, Math.round(Number(elapsedMs) / 1000));
	const minutes = Math.floor(totalSeconds / 60);
	const seconds = totalSeconds % 60;
	return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

export function getChatProgressActions(progress: ChatProgress) {
	const completed = Number(progress.executed_tool_count);
	const total = Number(progress.requested_tool_count);
	if (!Number.isFinite(completed) || !Number.isFinite(total) || completed < 0 || total <= 0) {
		return null;
	}
	return { completed: Math.min(completed, total), total };
}

export function appendChatProgress(history: ChatProgress[], next: ChatProgress) {
	const previous = history.at(-1);
	if (
		previous &&
		previous.phase === next.phase &&
		previous.cycle_index === next.cycle_index &&
		previous.requested_tool_count === next.requested_tool_count &&
		previous.executed_tool_count === next.executed_tool_count &&
		previous.remaining_tool_budget === next.remaining_tool_budget &&
		previous.remaining_token_budget === next.remaining_token_budget
	) {
		return history;
	}
	return [...history, next];
}

function chatSessionPath(sessionId = '') {
	return `/chat-sessions${sessionId ? `/${encodeURIComponent(sessionId)}` : ''}`;
}

export async function createChatSession(collectionId: string, signal?: AbortSignal) {
	return (await requestJson(chatSessionPath(), {
		signal,
		method: 'POST',
		body: JSON.stringify({ collection_id: collectionId })
	})) as ChatSession;
}

export async function fetchChatSession(sessionId: string, signal?: AbortSignal) {
	return (await requestJson(chatSessionPath(sessionId), {
		signal,
		method: 'GET'
	})) as ChatSession;
}

export async function branchChatMessage(
	sessionId: string,
	messageId: string,
	requestId: string,
	message?: string,
	signal?: AbortSignal
) {
	return (await requestJson(`${chatSessionPath(sessionId)}/branches`, {
		signal,
		method: 'POST',
		body: JSON.stringify({ message_id: messageId, request_id: requestId, message })
	})) as ChatSession;
}

export async function fetchChatTrajectory(sessionId: string, signal?: AbortSignal) {
	return (await requestJson(`${chatSessionPath(sessionId)}/messages`, {
		signal,
		method: 'GET'
	})) as ChatTrajectory;
}

export async function setChatMessageFeedback(
	sessionId: string,
	messageId: string,
	input: ChatFeedbackInput,
	signal?: AbortSignal
) {
	return (await requestJson(
		`${chatSessionPath(sessionId)}/messages/${encodeURIComponent(messageId)}/feedback`,
		{ signal, method: 'PUT', body: JSON.stringify(input) }
	)) as ChatMessageFeedback | null;
}

export async function streamChatMessage(
	sessionId: string,
	message: string,
	onTextDelta: (content: string) => void,
	sourceContexts: ChatSourceContext[] = [],
	onProgress?: (progress: ChatProgress) => void,
	signal?: AbortSignal,
	branchRevision = false
) {
	const response = await fetch(buildApiUrl(`${chatSessionPath(sessionId)}/messages`), {
		signal,
		method: 'POST',
		credentials: 'same-origin',
		headers: {
			Accept: 'text/event-stream',
			'Content-Type': 'application/json'
		},
		body: JSON.stringify({
			message,
			...(branchRevision ? { branch_revision: true } : {}),
			...(sourceContexts.length ? { source_contexts: sourceContexts } : {})
		})
	});
	if (!response.ok) await throwApiError(response);
	if (!response.body) throw new Error('The research response stream is unavailable.');

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';
	let turn: ChatTurn | null = null;
	const consume = (block: string) => {
		const lines = block.replace(/\r\n?/g, '\n').split('\n');
		const event = lines
			.find((line) => line.startsWith('event:'))
			?.slice(6)
			.trim();
		const data = lines
			.filter((line) => line.startsWith('data:'))
			.map((line) => line.slice(5).trimStart())
			.join('\n');
		if (!event || !data) return;
		const payload = JSON.parse(data) as unknown;
		if (event === 'text_delta') {
			if (payload && typeof payload === 'object' && 'content' in payload) {
				onTextDelta(String(payload.content ?? ''));
			}
			return;
		}
		if (event === 'turn') {
			turn = payload as ChatTurn;
			return;
		}
		if (event === 'progress') {
			if (payload && typeof payload === 'object' && 'phase' in payload) {
				onProgress?.(payload as ChatProgress);
			}
			return;
		}
		if (event === 'error') {
			const message =
				payload && typeof payload === 'object' && 'message' in payload
					? String(payload.message)
					: 'The research response could not be completed.';
			throw new Error(message);
		}
	};

	const cancelReader = () => {
		void reader.cancel().catch(() => {});
	};
	signal?.addEventListener('abort', cancelReader, { once: true });
	try {
		signal?.throwIfAborted();
		while (true) {
			const { done, value } = await reader.read();
			signal?.throwIfAborted();
			buffer += decoder.decode(value, { stream: !done });
			let boundary = /\r?\n\r?\n|\r\r/.exec(buffer);
			while (boundary?.index !== undefined) {
				consume(buffer.slice(0, boundary.index));
				buffer = buffer.slice(boundary.index + boundary[0].length);
				boundary = /\r?\n\r?\n|\r\r/.exec(buffer);
			}
			if (done) break;
		}
		if (buffer.trim()) consume(buffer);
		if (turn === null) throw new Error('The research response ended before completion.');
		return turn;
	} finally {
		signal?.removeEventListener('abort', cancelReader);
		await reader.cancel().catch(() => {});
		reader.releaseLock();
	}
}

function sourceContextStorageKey(userId: string, collectionId: string) {
	return `lens.chatSourceContext.${encodeURIComponent(userId)}:${encodeURIComponent(collectionId)}`;
}

export const MAX_CHAT_SOURCE_CONTEXTS = 12;

export function storePendingChatSourceContexts(
	userId: string,
	collectionId: string,
	contexts: ChatSourceContext[],
	submission?: { session_id: string; content: string; after_message_id: string | null }
) {
	if (typeof window === 'undefined') return;
	if (!contexts.length) {
		clearPendingChatSourceContexts(userId, collectionId);
		return;
	}
	window.sessionStorage.setItem(
		sourceContextStorageKey(userId, collectionId),
		JSON.stringify({ contexts, submission })
	);
}

export function readPendingChatSourceContexts(
	userId: string,
	collectionId: string,
	persisted?: { sessionId: string; messages: ChatMessage[] }
): ChatSourceContext[] {
	if (typeof window === 'undefined') return [];
	try {
		const raw = window.sessionStorage.getItem(sourceContextStorageKey(userId, collectionId));
		const value = raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
		const contexts = value?.contexts as ChatSourceContext[] | undefined;
		if (
			!Array.isArray(contexts) ||
			contexts.length > MAX_CHAT_SOURCE_CONTEXTS ||
			contexts.some(
				(item) =>
					!item ||
					item.collection_id !== collectionId ||
					item.resource_ref?.resource_type !== 'source' ||
					typeof item.resource_ref.resource_id !== 'string' ||
					typeof item.document_id !== 'string' ||
					typeof item.document_title !== 'string' ||
					typeof item.source_kind !== 'string' ||
					typeof item.source_ref !== 'string' ||
					typeof item.quote !== 'string'
			)
		) {
			clearPendingChatSourceContexts(userId, collectionId);
			return [];
		}
		const submission = value?.submission as Record<string, unknown> | undefined;
		if (submission && (!persisted || submission.session_id !== persisted.sessionId)) return [];
		if (persisted && submission?.session_id === persisted.sessionId) {
			const afterIndex =
				submission.after_message_id === null
					? -1
					: persisted.messages.findIndex(
							(message) => message.message_id === submission.after_message_id
						);
			const hasAnchor = submission.after_message_id === null || afterIndex >= 0;
			const sent =
				hasAnchor &&
				persisted.messages
					.slice(afterIndex + 1)
					.some(
						(message) =>
							message.role === 'user' &&
							message.content === submission.content &&
							contexts.every((context) =>
								message.source_contexts.some(
									(source) =>
										source.collection_id === collectionId &&
										source.document_id === context.document_id &&
										source.source_kind === context.source_kind &&
										source.source_ref === context.source_ref
								)
							)
					);
			if (sent) {
				clearPendingChatSourceContexts(userId, collectionId);
				return [];
			}
		}
		return contexts.map((value) => ({
			resource_ref: {
				resource_type: 'source',
				resource_id: value.resource_ref.resource_id,
				href: typeof value.resource_ref.href === 'string' ? value.resource_ref.href : null
			},
			collection_id: collectionId,
			document_id: value.document_id,
			document_title: value.document_title,
			source_kind: value.source_kind,
			source_ref: value.source_ref,
			page: typeof value.page === 'number' && value.page >= 1 ? value.page : null,
			quote: value.quote,
			heading_path: typeof value.heading_path === 'string' ? value.heading_path : null,
			quote_truncated: value.quote_truncated === true
		}));
	} catch {
		clearPendingChatSourceContexts(userId, collectionId);
		return [];
	}
}

export function clearPendingChatSourceContexts(userId: string, collectionId: string) {
	if (typeof window === 'undefined') return;
	window.sessionStorage.removeItem(sourceContextStorageKey(userId, collectionId));
}

export async function decideChatToolCall(
	sessionId: string,
	call: ChatToolCall,
	decision: 'approved' | 'rejected',
	signal?: AbortSignal
) {
	return (await requestJson(
		`${chatSessionPath(sessionId)}/tool-calls/${encodeURIComponent(call.tool_call_id)}/decision`,
		{
			signal,
			method: 'POST',
			body: JSON.stringify({
				decision,
				arguments_digest: call.arguments_digest
			})
		}
	)) as ChatTurn;
}
