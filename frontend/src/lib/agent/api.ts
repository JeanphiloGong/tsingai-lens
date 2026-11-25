import { buildApiUrl, requestJson, throwApiError } from '../../routes/_shared/api';
import {
	conversationPath,
	type Conversation,
	type ChatBranchOptions,
	type ConversationMessage,
	type ChatMessageFeedback
} from '$lib/conversation/api';
import type { ChatResourceRef } from '$lib/document/source-context';

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

export type Operation = {
	operation_id: string;
	task_id: string;
	decision_basis?: 'explicit' | 'scope_grant' | 'registry';
	authorization_revision?: number | null;
	tool_call_id: string;
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
		| 'rejected'
		| 'needs_reconciliation';
	started_at: string | null;
	finished_at: string | null;
	error_code: string | null;
	decision_user_id: string | null;
	decision_arguments_digest: string | null;
	decided_at: string | null;
};

export type AgentTurn = {
	execution_plan?: ChatExecutionPlan | null;
	status: 'completed' | 'approval_required' | 'failed' | 'rejected' | 'cancelled';
	completion_reason:
		| 'model_answer'
		| 'resource_budget'
		| 'no_progress'
		| 'emergency_ceiling'
		| null;
	warnings: string[];
	messages: ConversationMessage[];
	pending_approval: Operation | null;
	error_code: string | null;
};

export type TaskState = {
	items: ConversationMessage[];
	pending_approval: Operation | null;
	retryable_decision?: Operation | null;
	feedback: ChatMessageFeedback[];
	branches: ChatBranchOptions[];
	branch_draft: ConversationMessage | null;
	running: boolean;
	response?: TaskSnapshot | null;
};

export type TaskSnapshot = {
	model_connection_id?: string | null;
	model_connection_name?: string | null;
	task_id: string;
	checkpoint_revision: number;
	started_at: string;
	updated_at: string;
	status: 'accepted' | 'running' | 'completed' | 'approval_required' | 'failed' | 'interrupted' | 'cancelled';
	stop_requested?: boolean;
	message_id: string | null;
	message_created_at: string | null;
	content: string;
	progress: ChatProgress;
	checkpoint_message_id: string | null;
	completion_reason: AgentTurn['completion_reason'];
	error_code: string | null;
	warnings: string[];
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
	retry_count?: number;
	retry_attempt?: number | null;
	retry_delay_ms?: number | null;
	remaining_retry_budget?: number;
	termination_reason?: string | null;
	execution_plan?: ChatExecutionPlan | null;
};

export type ChatExecutionPlanStep = {
	step_id: string;
	action: string;
	status: 'pending' | 'in_progress' | 'completed' | 'blocked';
};

export type ChatExecutionPlan = {
	plan_id: string;
	plan_version: number;
	request?: string;
	status:
		| 'in_progress'
		| 'completed'
		| 'awaiting_approval'
		| 'waiting_for_clarification'
		| 'scientific_refusal'
		| 'permission_denied'
		| 'stalled'
		| 'technical_failure'
		| 'resource_limited'
		| string;
	model_status?: string;
	explanation?: string;
	blocking_reason?: string | null;
	steps: ChatExecutionPlanStep[];
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
		previous.remaining_token_budget === next.remaining_token_budget &&
		previous.retry_count === next.retry_count &&
		previous.retry_attempt === next.retry_attempt &&
		previous.termination_reason === next.termination_reason &&
		previous.execution_plan?.plan_id === next.execution_plan?.plan_id &&
		previous.execution_plan?.plan_version === next.execution_plan?.plan_version &&
		previous.execution_plan?.status === next.execution_plan?.status
	) {
		return history;
	}
	return [...history, next];
}


type TaskDetail = {
	task_id: string;
	checkpoint_revision: number;
	status: TaskSnapshot['status'];
	final_message_id: string | null;
	started_at: string;
	updated_at: string;
	error_code: string | null;
	active_operation: Operation | null;
};

type MessagePath = {
	conversation: Conversation;
	items: Array<ConversationMessage & { my_feedback: ChatMessageFeedback | null }>;
};

export async function fetchTaskState(
	conversationId: string, signal?: AbortSignal, taskId?: string
): Promise<TaskState> {
	const path = (await requestJson(`${conversationPath(conversationId)}/messages`, {
		signal,
		method: 'GET'
	})) as MessagePath;
	const selected = taskId ?? path.conversation?.current_task_id;
	const detail = selected
		? (await requestJson(taskPath(conversationId, selected), { signal })) as TaskDetail
		: null;
	return {
		items: path.items.map(({ my_feedback, ...item }) => ({
			...item,
			conversation_id: conversationId,
			tool_call_id: item.tool_call_id ?? null,
			tool_calls: [],
			tool_result: item.tool_result ?? null,
			source_contexts: item.source_contexts ?? []
		})),
		feedback: path.items.flatMap((item) =>
			item.my_feedback ? [{ ...item.my_feedback, message_id: item.message_id, conversation_id: conversationId }] : []
		),
		pending_approval: detail?.active_operation ?? null,
		branches: [],
		branch_draft: null,
		running: detail?.status === 'accepted' || detail?.status === 'running',
		response: detail ? taskSnapshot(detail) : null
	};
}

export async function stopTask(conversationId: string, taskId: string, signal?: AbortSignal) {
	await requestJson(`${taskPath(conversationId, taskId)}/stop`, {
		signal, method: 'POST', body: JSON.stringify({ request_id: crypto.randomUUID() })
	});
	return (await fetchTaskState(conversationId, signal, taskId)).response!;
}

export async function resumeTask(
	conversationId: string, taskId: string, checkpointRevision: number, signal?: AbortSignal
) {
	await requestJson(`${taskPath(conversationId, taskId)}/resume`, {
		signal,
		method: 'POST',
		body: JSON.stringify({
			request_id: crypto.randomUUID(),
			expected_checkpoint_revision: checkpointRevision
		})
	});
	return readTaskUpdates(conversationId, taskId, checkpointRevision, signal);
}

export async function readTaskUpdates(
	conversationId: string, taskId: string, afterRevision: number, signal?: AbortSignal
): Promise<TaskState> {
	const response = await fetch(
		buildApiUrl(`${taskPath(conversationId, taskId)}/events?after_revision=${afterRevision}`),
		{ signal, credentials: 'same-origin', headers: { Accept: 'text/event-stream' } }
	);
	if (!response.ok || !response.headers.get('Content-Type')?.includes('text/event-stream')) {
		await throwApiError(response);
	}
	await response.text();
	return fetchTaskState(conversationId, signal, taskId);
}

export async function decideOperation(
	conversationId: string, operation: Operation, decision: 'approved' | 'rejected', signal?: AbortSignal
) {
	await requestJson(
		`${taskPath(conversationId, operation.task_id)}/operations/${encodeURIComponent(operation.operation_id)}/decision`,
		{
			signal,
			method: 'POST',
			body: JSON.stringify({
				request_id: crypto.randomUUID(),
				decision,
				arguments_digest: operation.arguments_digest
			})
		}
	);
	return readTaskUpdates(conversationId, operation.task_id, 0, signal);
}

function taskPath(conversationId: string, taskId: string) {
	return `${conversationPath(conversationId)}/tasks/${encodeURIComponent(taskId)}`;
}

function taskSnapshot(task: TaskDetail): TaskSnapshot {
	return {
		task_id: task.task_id,
		checkpoint_revision: task.checkpoint_revision,
		started_at: task.started_at,
		updated_at: task.updated_at,
		status: task.status,
		message_id: task.final_message_id,
		message_created_at: null,
		content: '',
		progress: { phase: task.status },
		checkpoint_message_id: null,
		completion_reason: task.status === 'completed' ? 'model_answer' : null,
		error_code: task.error_code,
		warnings: []
	};
}
