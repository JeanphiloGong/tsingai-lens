import { requestJson } from './api';

export type ChatResourceRef = {
	resource_type: string;
	resource_id: string;
	href: string | null;
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

export type ChatMessage = {
	message_id: string;
	session_id: string;
	role: 'user' | 'assistant' | 'tool';
	content: string;
	created_at: string;
	tool_call_id: string | null;
	tool_name: string | null;
	tool_arguments: Record<string, unknown> | null;
	tool_result: ChatToolResult | null;
};

export type ChatSession = {
	session_id: string;
	user_id: string;
	collection_id: string;
	created_at: string;
	updated_at: string;
};

export type ChatToolCall = {
	tool_call_id: string;
	session_id: string;
	assistant_message_id: string;
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
	status: 'completed' | 'approval_required' | 'step_limit_reached' | 'failed' | 'rejected';
	messages: ChatMessage[];
	pending_approval: ChatToolCall | null;
	error_code: string | null;
};

export type ChatTrajectory = {
	items: ChatMessage[];
	pending_approval: ChatToolCall | null;
};

function chatSessionPath(sessionId = '') {
	return `/chat-sessions${sessionId ? `/${encodeURIComponent(sessionId)}` : ''}`;
}

export async function createChatSession(collectionId: string) {
	return (await requestJson(chatSessionPath(), {
		method: 'POST',
		body: JSON.stringify({ collection_id: collectionId })
	})) as ChatSession;
}

export async function fetchChatSession(sessionId: string) {
	return (await requestJson(chatSessionPath(sessionId), {
		method: 'GET'
	})) as ChatSession;
}

export async function fetchChatTrajectory(sessionId: string) {
	return (await requestJson(`${chatSessionPath(sessionId)}/messages`, {
		method: 'GET'
	})) as ChatTrajectory;
}

export async function postChatMessage(sessionId: string, message: string) {
	return (await requestJson(`${chatSessionPath(sessionId)}/messages`, {
		method: 'POST',
		body: JSON.stringify({ message })
	})) as ChatTurn;
}

export async function decideChatToolCall(
	sessionId: string,
	call: ChatToolCall,
	decision: 'approved' | 'rejected'
) {
	return (await requestJson(
		`${chatSessionPath(sessionId)}/tool-calls/${encodeURIComponent(call.tool_call_id)}/decision`,
		{
			method: 'POST',
			body: JSON.stringify({
				decision,
				arguments_digest: call.arguments_digest
			})
		}
	)) as ChatTurn;
}
