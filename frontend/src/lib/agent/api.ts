import { ApiError, buildApiUrl, requestJson, throwApiError } from '../../routes/_shared/api';
import {
	conversationPath,
	type ChatBranchOptions,
	type ChatMessage,
	type ChatMessageFeedback
} from '$lib/conversation/api';
import type { ChatResourceRef, ChatSourceContext } from '$lib/document/source-context';

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

export type ChatToolCall = {
	decision_basis?: 'explicit' | 'scope_grant';
	authorization_revision?: number | null;
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
	execution_plan?: ChatExecutionPlan | null;
	status: 'completed' | 'approval_required' | 'failed' | 'rejected' | 'cancelled';
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
	retryable_decision?: ChatToolCall | null;
	feedback: ChatMessageFeedback[];
	branches: ChatBranchOptions[];
	branch_draft: ChatMessage | null;
	running: boolean;
	response?: ChatResponseSnapshot | null;
};

export type ChatResponseSnapshot = {
	model_connection_id?: string | null;
	model_connection_name?: string | null;
	response_id: string;
	sequence: number;
	started_at: string;
	updated_at: string;
	status: 'running' | 'completed' | 'approval_required' | 'failed' | 'interrupted' | 'cancelled';
	stop_requested?: boolean;
	message_id: string | null;
	message_created_at: string | null;
	content: string;
	progress: ChatProgress;
	checkpoint_message_id: string | null;
	completion_reason: ChatTurn['completion_reason'];
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

export async function fetchChatTrajectory(sessionId: string, signal?: AbortSignal) {
	const value = await requestJson(`${conversationPath(sessionId)}/messages`, {
		signal,
		method: 'GET'
	});
	const response = value as {
		items: Array<Record<string, unknown>>;
		active_tasks: Array<Record<string, unknown>>;
	};
	const items = response.items.map((item) => ({
		message_id: String(item.message_id),
		session_id: sessionId,
		role: item.role as ChatMessage['role'],
		content: String(item.content ?? ''),
		created_at: String(item.created_at ?? new Date(0).toISOString()),
		tool_call_id: typeof item.tool_call_id === 'string' ? item.tool_call_id : null,
		tool_calls: Array.isArray(item.tool_requests) ? (item.tool_requests as ChatToolRequest[]) : [],
		tool_result: (item.tool_result as ChatToolResult | null) ?? null,
		source_contexts: Array.isArray(item.source_contexts)
			? (item.source_contexts as ChatSourceContext[])
			: []
	}));
	const active = response.active_tasks ?? [];
	const taskDetails = await Promise.all(
		active.map(async (task) => {
			try {
				return (await requestJson(
					`${conversationPath(sessionId)}/tasks/${encodeURIComponent(String(task.task_id))}`,
					{ signal, method: 'GET' }
				)) as Record<string, unknown>;
			} catch {
				return task;
			}
		})
	);
	const approvalTaskIndex = taskDetails.findIndex(
		(task) =>
			(task.status === 'approval_required' ||
				active[taskDetails.indexOf(task)]?.status === 'approval_required') &&
			task.active_operation
	);
	const approvalTask =
		approvalTaskIndex >= 0 ? taskDetails[approvalTaskIndex] : null;
	const operation = approvalTask?.active_operation as Record<string, unknown> | undefined;
	const pendingApproval = operation
		? ({
				tool_call_id: String(operation.operation_id),
				session_id: String(approvalTask?.task_id ?? ''),
				assistant_message_id: '',
				position: 0,
				name: String(operation.name ?? ''),
				arguments: (operation.arguments ?? {}) as Record<string, unknown>,
				arguments_digest: String(operation.arguments_digest ?? ''),
				risk: operation.risk as ChatToolCall['risk'],
				status: 'approval_required',
				started_at: null,
				finished_at: null,
				error_code: null,
				decision_user_id: null,
				decision_arguments_digest: null,
				decided_at: null
			} satisfies ChatToolCall)
		: null;
	const runningTask = active.find((task) => task.status === 'running' || task.status === 'accepted');
	const trajectory: ChatTrajectory = {
		items,
		pending_approval: pendingApproval,
		feedback: response.items
			.filter((item) => item.my_feedback)
			.map((item) => ({ ...(item.my_feedback as ChatMessageFeedback), session_id: sessionId })),
		branches: [],
		branch_draft: null,
		running: Boolean(runningTask),
		response: runningTask || approvalTask
			? taskSnapshot(
					String((runningTask || approvalTask)?.task_id),
					approvalTask ? 'approval_required' : 'running',
					Number((runningTask || approvalTask)?.checkpoint_revision ?? 0)
				)
			: null
	};
	return trajectory;
}

export async function stopChatResponse(
	sessionId: string,
	responseId: string,
	signal?: AbortSignal
) {
	const value = await requestJson(
		`${conversationPath(sessionId)}/tasks/${encodeURIComponent(responseId)}/stop`,
		{
			method: 'POST',
			signal,
			body: JSON.stringify({ request_id: crypto.randomUUID() })
		}
	);
	return taskSnapshot(responseId, 'interrupted', 0, value);
}

export async function streamChatMessage(
	sessionId: string,
	message: string,
	onTextDelta: (content: string) => void,
	sourceContexts: ChatSourceContext[] = [],
	onProgress?: (progress: ChatProgress) => void,
	signal?: AbortSignal,
	branchRevision = false,
	onSnapshot?: (snapshot: ChatResponseSnapshot) => void,
	onTrajectory?: (trajectory: ChatTrajectory) => void,
	modelConnectionId?: string
) {
	const accepted = (await requestJson(`${conversationPath(sessionId)}/messages`, {
		signal,
		method: 'POST',
		body: JSON.stringify({
			request_id: crypto.randomUUID(),
			parent_message_id: null,
			message,
			source_contexts: sourceContexts,
			...(modelConnectionId ? { model_connection_id: modelConnectionId } : {})
		})
	})) as { task_id: string; status: string };
	const snapshot = taskSnapshot(accepted.task_id, 'running', 0);
	onSnapshot?.(snapshot);
	onProgress?.({ phase: 'accepted', cycle_index: 0, elapsed_ms: 0 });
	return {
		status: 'completed',
		completion_reason: null,
		warnings: [],
		messages: [],
		pending_approval: null,
		error_code: null
	} satisfies ChatTurn;
}

export async function streamChatUpdates(
	sessionId: string,
	responseId: string,
	onSnapshot: (snapshot: ChatResponseSnapshot) => void,
	onTrajectory: (trajectory: ChatTrajectory) => void,
	signal?: AbortSignal
) {
	const response = await fetch(
		buildApiUrl(
			`${conversationPath(sessionId)}/tasks/${encodeURIComponent(responseId)}/events?after_revision=0`
		),
		{ signal, credentials: 'same-origin', headers: { Accept: 'text/event-stream' } }
	);
	if (!response.ok) await throwApiError(response);
	const text = await response.text();
	const match = /data: (.+)/.exec(text);
	if (match) {
		const payload = JSON.parse(match[1]) as {
			task_id: string;
			revision: number;
			status: ChatResponseSnapshot['status'];
		};
		onSnapshot(taskSnapshot(payload.task_id, payload.status, payload.revision));
	}
	onTrajectory(await fetchChatTrajectory(sessionId, signal));
}

async function readChatEvents(
	response: Response,
	callbacks: {
		onTextDelta?: (content: string) => void;
		onProgress?: (progress: ChatProgress) => void;
		onSnapshot?: (snapshot: ChatResponseSnapshot) => void;
		onTrajectory?: (trajectory: ChatTrajectory) => void;
	},
	signal?: AbortSignal
) {
	if (!response.ok || !response.headers.get('Content-Type')?.includes('text/event-stream')) {
		await throwApiError(response);
	}
	if (!response.body) throw new Error('The research response stream is unavailable.');

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let idleTimer: ReturnType<typeof setTimeout> | undefined;
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
				callbacks.onTextDelta?.(String(payload.content ?? ''));
			}
			return;
		}
		if (event === 'turn') {
			turn = payload as ChatTurn;
			return;
		}
		if (event === 'progress') {
			if (payload && typeof payload === 'object' && 'phase' in payload) {
				callbacks.onProgress?.(payload as ChatProgress);
			}
			return;
		}
		if (event === 'snapshot') {
			callbacks.onSnapshot?.(payload as ChatResponseSnapshot);
			return;
		}
		if (event === 'trajectory') {
			callbacks.onTrajectory?.(payload as ChatTrajectory);
			return;
		}
		if (event === 'error') {
			const message =
				payload && typeof payload === 'object' && 'message' in payload
					? String(payload.message)
					: 'The research response could not be completed.';
			throw new ApiError(200205, message, payload);
		}
	};

	const cancelReader = () => {
		void reader.cancel().catch(() => {});
	};
	signal?.addEventListener('abort', cancelReader, { once: true });
	try {
		signal?.throwIfAborted();
		while (true) {
			// The server emits heartbeats during model work. A silent connection
			// must yield to snapshot recovery, without cancelling the research job.
			const { done, value } = await Promise.race([
				reader.read(),
				new Promise<never>((_, reject) => {
					idleTimer = setTimeout(
						() => reject(new Error('error.researchConnectionInactive')),
						30_000
					);
				})
			]);
			clearTimeout(idleTimer);
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
		return turn;
	} finally {
		clearTimeout(idleTimer);
		signal?.removeEventListener('abort', cancelReader);
		await reader.cancel().catch(() => {});
		reader.releaseLock();
	}
}

export async function decideChatToolCall(
	sessionId: string,
	call: ChatToolCall,
	decision: 'approved' | 'rejected',
	signal?: AbortSignal
) {
	await requestJson(
	`${conversationPath(sessionId)}/tasks/${encodeURIComponent(call.session_id)}/operations/${encodeURIComponent(call.tool_call_id)}/decision`,
		{
			signal,
			method: 'POST',
			body: JSON.stringify({
				request_id: crypto.randomUUID(),
				decision,
				arguments_digest: call.arguments_digest
			})
		}
	);
	return {
		status: decision === 'rejected' ? 'rejected' : 'approval_required',
		completion_reason: null,
		warnings: [],
		messages: [],
		pending_approval: null,
		error_code: null
	} satisfies ChatTurn;
}

function taskSnapshot(
	taskId: string,
	status: ChatResponseSnapshot['status'],
	revision: number,
	value?: unknown
): ChatResponseSnapshot {
	const item = (value ?? {}) as Record<string, unknown>;
	return {
		response_id: taskId,
		sequence: revision,
		started_at: new Date().toISOString(),
		updated_at: new Date().toISOString(),
		status,
		message_id: typeof item.final_message_id === 'string' ? item.final_message_id : null,
		message_created_at: null,
		content: '',
		progress: { phase: status, cycle_index: revision },
		checkpoint_message_id: null,
		completion_reason: null,
		error_code: null,
		warnings: []
	};
}
