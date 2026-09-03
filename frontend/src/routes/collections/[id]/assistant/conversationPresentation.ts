import type { ChatMessage } from '../../../_shared/chatSessions';

const reviewableResultTools = new Set([
	'create_evidence_version',
	'create_finding_version',
	'create_objective_candidate',
	'inspect_objective_analysis',
	'inspect_published_finding',
	'inspect_research_process',
	'preview_research_scope',
	'propose_objective_drafts',
	'publish_agent_objective_analysis',
	'start_objective_analysis',
	'start_research_process'
]);

export type ToolActivityOperation = {
	toolCallId: string;
	toolName: string | null;
	requestMessage: ChatMessage | null;
	resultMessage: ChatMessage | null;
};

export type ChatPresentationItem =
	| {
			kind: 'message';
			id: string;
			message: ChatMessage;
	  }
	| {
			kind: 'activity';
			id: string;
			operations: ToolActivityOperation[];
			artifacts: ToolActivityOperation[];
			status: 'completed' | 'in_progress' | 'pending' | 'failed';
	  };

function isToolActivity(message: ChatMessage) {
	return Boolean(message.tool_call_id || message.tool_result);
}

function operationsFrom(messages: ChatMessage[]) {
	const operations: ToolActivityOperation[] = [];

	for (const message of messages) {
		const toolCallId = message.tool_result?.tool_call_id ?? message.tool_call_id;
		if (!toolCallId) continue;
		let operation = operations.find((candidate) => candidate.toolCallId === toolCallId);
		if (!operation) {
			operation = {
				toolCallId,
				toolName: message.tool_name,
				requestMessage: null,
				resultMessage: null
			};
			operations.push(operation);
		}
		if (message.role === 'assistant') {
			operation.requestMessage = message;
			operation.toolName = message.tool_name;
		}
		if (message.tool_result) operation.resultMessage = message;
	}

	return operations;
}

function activityStatus(operations: ToolActivityOperation[]) {
	if (operations.some((operation) => operation.resultMessage?.tool_result?.status === 'failed')) {
		return 'failed' as const;
	}
	if (operations.some((operation) => operation.resultMessage?.tool_result?.status === 'queued')) {
		return 'in_progress' as const;
	}
	if (operations.some((operation) => operation.resultMessage === null)) return 'pending' as const;
	return 'completed' as const;
}

export function buildChatPresentation(
	messages: ChatMessage[],
	pendingApprovalToolCallId: string | null = null
): ChatPresentationItem[] {
	const items: ChatPresentationItem[] = [];
	let activityMessages: ChatMessage[] = [];

	const flushActivity = () => {
		if (!activityMessages.length) return;
		const operations = operationsFrom(activityMessages).filter(
			(operation) => operation.toolCallId !== pendingApprovalToolCallId
		);
		if (!operations.length) {
			activityMessages = [];
			return;
		}
		const artifacts = operations.filter(
			(operation) =>
				operation.resultMessage !== null &&
				operation.toolName !== null &&
				reviewableResultTools.has(operation.toolName)
		);
		items.push({
			kind: 'activity',
			id: `activity-${activityMessages[0].message_id}`,
			operations,
			artifacts,
			status: activityStatus(operations.filter((operation) => !artifacts.includes(operation)))
		});
		activityMessages = [];
	};

	for (const message of messages) {
		if (isToolActivity(message)) {
			if (message.role === 'assistant' && message.content.trim()) {
				flushActivity();
				items.push({ kind: 'message', id: `message-${message.message_id}`, message });
			}
			activityMessages.push(message);
			continue;
		}

		flushActivity();
		items.push({ kind: 'message', id: `message-${message.message_id}`, message });
	}

	flushActivity();
	return items;
}
