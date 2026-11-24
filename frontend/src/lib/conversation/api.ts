import { requestJson } from '../../routes/_shared/api';
import type { ChatToolRequest, ChatToolResult } from '$lib/agent/api';
import type { ChatSourceContext } from '$lib/document/source-context';

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
	workspace_id: string;
	created_at: string;
	updated_at: string;
	title?: string | null;
	is_pinned: boolean;
	status: 'idle' | 'running' | 'approval';
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

export type ChatTreeNode = {
	message: ChatMessage;
	parent_message_id: string | null;
	answer: string;
	status:
		| 'completed'
		| 'running'
		| 'approval_required'
		| 'failed'
		| 'interrupted'
		| 'cancelled'
		| 'incomplete'
		| 'draft';
	can_branch: boolean;
};

export type ChatTree = {
	root_session_id: string;
	active_path: string[];
	nodes: ChatTreeNode[];
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

export function conversationPath(sessionId = '') {
	return `/conversations${sessionId ? `/${encodeURIComponent(sessionId)}` : ''}`;
}

export async function createChatSession(workspaceId: string, signal?: AbortSignal) {
	return toChatSession(await requestJson(conversationPath(), {
		signal,
		method: 'POST',
		body: JSON.stringify({ workspace_id: workspaceId })
	}));
}

export async function listChatSessions(
	workspaceId: string,
	options: { limit?: number; offset?: number; signal?: AbortSignal } = {}
) {
	const params = new URLSearchParams({ workspace_id: workspaceId });
	if (options.limit !== undefined) params.set('limit', String(options.limit));
	if (options.offset !== undefined) params.set('offset', String(options.offset));
	const page = await requestJson(`${conversationPath()}?${params.toString()}`, {
		signal: options.signal,
		method: 'GET'
	}) as { items: unknown[]; limit: number; offset: number };
	return { ...page, items: page.items.map(toChatSession) };
}

export async function fetchChatSession(sessionId: string, signal?: AbortSignal) {
	return toChatSession(await requestJson(conversationPath(sessionId), {
		signal,
		method: 'GET'
	}));
}

export async function deleteChatSession(sessionId: string, signal?: AbortSignal) {
	await requestJson(conversationPath(sessionId), { signal, method: 'DELETE' });
}

export async function setChatSessionPin(
	sessionId: string,
	isPinned: boolean,
	signal?: AbortSignal
) {
	return toChatSession(await requestJson(`${conversationPath(sessionId)}/pin`, {
		signal,
		method: 'PUT',
		body: JSON.stringify({ is_pinned: isPinned })
	}));
}

export async function setChatSessionTitle(sessionId: string, title: string, signal?: AbortSignal) {
	return toChatSession(await requestJson(`${conversationPath(sessionId)}/title`, {
		signal,
		method: 'PUT',
		body: JSON.stringify({ title })
	}));
}

export async function branchChatMessage(
	sessionId: string,
	messageId: string,
	requestId: string,
	message?: string,
	signal?: AbortSignal,
	mode: 'revise' | 'continue' = 'revise'
) {
	const path =
		mode === 'continue'
			? `${conversationPath(sessionId)}/messages/${encodeURIComponent(messageId)}/regenerations`
			: `${conversationPath(sessionId)}/messages/${encodeURIComponent(messageId)}/edits`;
	const value = await requestJson(path, {
		signal,
		method: 'POST',
		body: JSON.stringify({
			request_id: requestId,
			...(message === undefined ? {} : { message })
		})
	});
	if (value && typeof value === 'object' && 'task_id' in value) {
		return fetchChatSession(sessionId, signal);
	}
	return toChatSession(value);
}

export async function fetchChatTree(sessionId: string, signal?: AbortSignal): Promise<ChatTree> {
	const value = await requestJson(`${conversationPath(sessionId)}/tree`, {
		signal,
		method: 'GET'
	});
	const tree = value as {
		root_conversation_id: string;
		active_path: string[];
		nodes: Array<Record<string, unknown>>;
	};
	return {
		root_session_id: tree.root_conversation_id,
		active_path: tree.active_path,
		nodes: tree.nodes.map((node) => {
			const messageId =
				typeof node.message_id === 'string'
					? node.message_id
					: String(node.node_id);
			const role = node.kind === 'task' ? 'assistant' : 'user';
			return {
				message: {
					message_id: messageId,
					session_id: String(node.conversation_id),
					role,
					content: String(node.preview ?? ''),
					created_at: new Date(0).toISOString(),
					tool_call_id: null,
					tool_calls: [],
					tool_result: null,
					source_contexts: []
				},
				parent_message_id:
					typeof node.parent_node_id === 'string' &&
					node.parent_node_id.startsWith('message:')
						? node.parent_node_id.slice('message:'.length)
						: null,
				answer: String(node.preview ?? ''),
				status: node.kind === 'task' ? 'running' : 'completed',
				can_branch: node.kind === 'message'
			};
		})
	};
}

export async function setChatMessageFeedback(
	sessionId: string,
	messageId: string,
	input: ChatFeedbackInput,
	signal?: AbortSignal
) {
	const data = await requestJson(
		`${conversationPath(sessionId)}/messages/${encodeURIComponent(messageId)}/feedback`,
		input.rating === null
			? { signal, method: 'DELETE' }
			: { signal, method: 'PUT', body: JSON.stringify(input) }
	);
	if (Object.keys(data as object).length === 0) return null;
	return { ...(data as ChatMessageFeedback), session_id: sessionId };
}

function toChatSession(value: unknown): ChatSession {
	const item = value as Record<string, unknown>;
	if (typeof item.conversation_id !== 'string') return value as ChatSession;
	return {
		session_id: item.conversation_id,
		user_id: '',
		workspace_id: String(item.workspace_id ?? ''),
		created_at: String(item.created_at ?? ''),
		updated_at: String(item.updated_at ?? ''),
		title: typeof item.title === 'string' ? item.title : null,
		is_pinned: item.is_pinned === true,
		status:
			item.status === 'running' || item.status === 'approval'
				? item.status
				: 'idle',
		root_session_id: null,
		parent_session_id: null,
		fork_message_id:
			typeof item.forked_from_message_id === 'string'
				? item.forked_from_message_id
				: null
	};
}
