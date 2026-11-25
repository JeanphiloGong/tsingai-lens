import { requestJson } from '../../routes/_shared/api';
import type { ChatToolRequest, ChatToolResult } from '$lib/agent/api';
import type { ChatSourceContext } from '$lib/document/source-context';

export type ConversationMessage = {
	message_id: string;
	conversation_id: string;
	role: 'user' | 'assistant' | 'tool';
	content: string;
	created_at: string;
	tool_call_id: string | null;
	tool_calls: ChatToolRequest[];
	tool_result: ChatToolResult | null;
	source_contexts: ChatSourceContext[];
};

export type Conversation = {
	conversation_id: string;
	user_id: string;
	workspace_id: string;
	created_at: string;
	updated_at: string;
	title?: string | null;
	is_pinned: boolean;
	status: 'idle' | 'running' | 'approval';
	current_message_id?: string | null;
	current_task_id?: string | null;
	path_revision?: number;
	root_conversation_id?: string | null;
	parent_conversation_id?: string | null;
	forked_from_message_id?: string | null;
	fork_position?: number | null;
	fork_content?: string | null;
};

export type ChatBranchOptions = {
	message_id: string;
	conversation_ids: string[];
	active_conversation_id: string;
};

export type ConversationTreeNode = {
	kind?: 'conversation' | 'message' | 'task';
	task_id?: string | null;
	message: ConversationMessage;
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

export type ConversationTreeData = {
	root_conversation_id: string;
	active_path: string[];
	nodes: ConversationTreeNode[];
};

export type ChatFeedbackReason = 'incorrect' | 'incomplete' | 'unclear' | 'other';

export type ChatFeedbackInput = {
	rating: 'helpful' | 'not_helpful' | null;
	reason?: ChatFeedbackReason | null;
	comment?: string | null;
};

export type ChatMessageFeedback = {
	feedback_id: string;
	conversation_id: string;
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

export async function createConversation(workspaceId: string, signal?: AbortSignal) {
	return toConversation(await requestJson(conversationPath(), {
		signal,
		method: 'POST',
		body: JSON.stringify({ workspace_id: workspaceId })
	}));
}

export async function listConversations(
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
	return { ...page, items: page.items.map(toConversation) };
}

export async function fetchConversation(sessionId: string, signal?: AbortSignal) {
	return toConversation(await requestJson(conversationPath(sessionId), {
		signal,
		method: 'GET'
	}));
}

export async function deleteConversation(sessionId: string, signal?: AbortSignal) {
	await requestJson(conversationPath(sessionId), { signal, method: 'DELETE' });
}

export async function setConversationPin(
	sessionId: string,
	isPinned: boolean,
	signal?: AbortSignal
) {
	return toConversation(await requestJson(`${conversationPath(sessionId)}/pin`, {
		signal,
		method: 'PUT',
		body: JSON.stringify({ is_pinned: isPinned })
	}));
}

export async function setConversationTitle(sessionId: string, title: string, signal?: AbortSignal) {
	return toConversation(await requestJson(`${conversationPath(sessionId)}/title`, {
		signal,
		method: 'PUT',
		body: JSON.stringify({ title })
	}));
}

export type AcceptedTask = {
	task_id: string;
	trigger_message_id: string;
	status: 'accepted';
};

export async function sendConversationMessage(
	conversationId: string,
	message: string,
	parentMessageId: string | null,
	sourceContexts: ChatSourceContext[],
	modelConnectionId: string,
	signal?: AbortSignal
) {
	return (await requestJson(`${conversationPath(conversationId)}/messages`, {
		signal, method: 'POST',
		body: JSON.stringify({
			request_id: crypto.randomUUID(),
			parent_message_id: parentMessageId,
			message,
			source_contexts: sourceContexts,
			model_connection_id: modelConnectionId
		})
	})) as AcceptedTask;
}

export async function branchChatMessage(
	conversationId: string,
	messageId: string,
	requestId: string,
	message: string | undefined,
	signal?: AbortSignal,
	mode: 'revise' | 'continue' = 'revise'
) {
	const action = mode === 'continue' ? 'regenerations' : 'edits';
	return (await requestJson(
		`${conversationPath(conversationId)}/messages/${encodeURIComponent(messageId)}/${action}`,
		{
			signal, method: 'POST',
			body: JSON.stringify({ request_id: requestId, ...(mode === 'revise' ? { message } : {}) })
		}
	)) as AcceptedTask;
}

export async function forkConversation(conversationId: string, messageId: string, signal?: AbortSignal) {
	return toConversation(await requestJson(`${conversationPath(conversationId)}/forks`, {
		signal, method: 'POST', body: JSON.stringify({ message_id: messageId })
	}));
}

export async function selectConversationPath(
	conversationId: string, revision: number, target: { task_id: string } | { tip_message_id: string },
	signal?: AbortSignal
) {
	return toConversation(await requestJson(`${conversationPath(conversationId)}/active-path`, {
		signal, method: 'PUT', body: JSON.stringify({ expected_path_revision: revision, ...target })
	}));
}

export async function fetchConversationTree(sessionId: string, signal?: AbortSignal): Promise<ConversationTreeData> {
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
		root_conversation_id: tree.root_conversation_id,
		active_path: tree.active_path,
		nodes: tree.nodes.map((node) => {
			const messageId =
				typeof node.message_id === 'string'
					? node.message_id
					: String(node.node_id);
			const role = node.kind === 'task' ? 'assistant' : 'user';
			return {
				kind: node.kind as ConversationTreeNode['kind'],
				task_id: node.kind === 'task' ? String(node.task_id) : null,
				message: {
					message_id: messageId,
					conversation_id: String(node.conversation_id),
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
	if (input.rating === null) return null;
	return { ...(data as ChatMessageFeedback), conversation_id: sessionId };
}

function toConversation(value: unknown): Conversation {
	const item = value as Record<string, unknown>;
	return {
		conversation_id: String(item.conversation_id),
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
		current_message_id: item.current_message_id as string | null,
		current_task_id: item.current_task_id as string | null,
		path_revision: item.path_revision as number,
		root_conversation_id: null,
		parent_conversation_id: null,
		forked_from_message_id:
			typeof item.forked_from_message_id === 'string'
				? item.forked_from_message_id
				: null
	};
}
