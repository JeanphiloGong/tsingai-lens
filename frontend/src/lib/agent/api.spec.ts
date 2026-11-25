import { describe, expect, it, vi } from 'vitest';
import {
	appendChatProgress,
	formatChatElapsed,
	getChatProgressActions,
	readTaskUpdates,
	type ChatProgress
} from '$lib/agent/api';
import { sendConversationMessage } from '$lib/conversation/api';
import { fetchModelConnections } from '$lib/agent/model-connections';

describe('direct Task API lifecycle', () => {
	it('accepts a message through Conversation and exposes the task identity', async () => {
		const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(
				JSON.stringify({
					code: 200,
					message: 'success',
					data: { task_id: 'task_1', status: 'accepted' },
					meta: null
				})
			)
		);
		try {
			await expect(sendConversationMessage('chat_1', 'Compare the papers', 'msg_0', [], 'lab-b')).resolves.toMatchObject({
				status: 'accepted', task_id: 'task_1'
			});
			expect(fetch).toHaveBeenCalledWith(
				'/api/v1/conversations/chat_1/messages',
				expect.objectContaining({ method: 'POST' })
			);
			expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toMatchObject({
				message: 'Compare the papers', parent_message_id: 'msg_0'
			});
		} finally {
			fetch.mockRestore();
		}
	});

	it('reads the same Task and saved answer after the requested SSE revision', async () => {
		const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
			const path = String(input);
			if (path.endsWith('/events?after_revision=1')) {
				return new Response('event: task.snapshot\ndata: {"task_id":"task_1","revision":2,"status":"completed"}\n\n', {
					headers: { 'Content-Type': 'text/event-stream' }
				});
			}
			const data = path.endsWith('/tasks/task_1')
				? { task_id: 'task_1', status: 'completed', checkpoint_revision: 2, final_message_id: 'msg_2' }
				: { conversation: { current_task_id: 'task_1' }, items: [{ message_id: 'msg_2', role: 'assistant', content: 'Methods report 30 minutes.' }] };
			return Response.json({ code: 200, message: 'success', data, meta: null });
		});
		try {
			const state = await readTaskUpdates('chat_1', 'task_1', 1);
			expect(state.response).toMatchObject({ task_id: 'task_1', status: 'completed', checkpoint_revision: 2 });
			expect(state.items.at(-1)).toMatchObject({ message_id: 'msg_2', content: 'Methods report 30 minutes.' });
			expect(String(fetch.mock.calls[0][0])).toBe(
				'/api/v1/conversations/chat_1/tasks/task_1/events?after_revision=1'
			);
		} finally {
			fetch.mockRestore();
		}
	});
});

describe('chat progress presentation helpers', () => {
	it('formats short and long elapsed durations for the runtime status', () => {
		expect(formatChatElapsed(0)).toBe('0s');
		expect(formatChatElapsed(12_400)).toBe('12s');
		expect(formatChatElapsed(192_000)).toBe('3m 12s');
	});

	it('returns completed and requested research actions when both are present', () => {
		const progress: ChatProgress = {
			phase: 'tools',
			executed_tool_count: 8,
			requested_tool_count: 12
		};

		expect(getChatProgressActions(progress)).toEqual({ completed: 8, total: 12 });
	});

	it('treats requested and executed action counts as cumulative turn totals', () => {
		expect(
			getChatProgressActions({ phase: 'tools', requested_tool_count: 3, executed_tool_count: 3 })
		).toEqual({ completed: 3, total: 3 });
	});

	it('does not render an action count when the stream has no usable total', () => {
		expect(getChatProgressActions({ phase: 'model', executed_tool_count: 2 })).toBeNull();
		expect(
			getChatProgressActions({ phase: 'tools', executed_tool_count: -1, requested_tool_count: 3 })
		).toBeNull();
	});

	it('keeps only observable progress changes in the inline status history', () => {
		const starting: ChatProgress = { phase: 'starting', elapsed_ms: 0 };
		const tools: ChatProgress = {
			phase: 'tools',
			cycle_index: 2,
			executed_tool_count: 2,
			requested_tool_count: 4,
			elapsed_ms: 12_000
		};

		const once = appendChatProgress([starting], tools);
		expect(appendChatProgress(once, { ...tools, elapsed_ms: 13_000 })).toEqual(once);
		expect(appendChatProgress(once, { ...tools, executed_tool_count: 3 })).toHaveLength(3);
	});

	it('keeps a changed execution plan visible in progress history', () => {
		const initial: ChatProgress = {
			phase: 'tools',
			execution_plan: {
				plan_id: 'plan-1',
				plan_version: 1,
				status: 'in_progress',
				model_status: 'in_progress',
				steps: [{ step_id: 'read', action: 'Read the Source', status: 'in_progress' }]
			}
		};
		const updated: ChatProgress = {
			...initial,
			execution_plan: {
				...initial.execution_plan!,
				plan_version: 2,
				status: 'completed',
				steps: [{ step_id: 'read', action: 'Read the Source', status: 'completed' }]
			}
		};

		expect(appendChatProgress([initial], updated)).toHaveLength(2);
		const terminal = {
			...updated,
			execution_plan: { ...updated.execution_plan!, plan_version: 1 }
		};
		expect(appendChatProgress([initial], terminal)).toHaveLength(2);
	});
});

describe('model connection selection', () => {
	it('passes the selected model connection with the Conversation request', async () => {
		const fetch = vi
			.spyOn(globalThis, 'fetch')
			.mockResolvedValue(
				new Response(
					JSON.stringify({
						code: 200,
						message: 'success',
						data: { task_id: 'task_1', status: 'accepted' },
						meta: null
					})
				)
			);
		try {
			await sendConversationMessage('chat_1', 'Compare papers', null, [], 'lab-b');
			expect(String(fetch.mock.calls[0][0])).toBe('/api/v1/conversations/chat_1/messages');
			expect(JSON.parse(String(fetch.mock.calls[0][1]?.body)).model_connection_id).toBe('lab-b');
		} finally {
			fetch.mockRestore();
		}
	});

	it('reads only the same-origin model directory', async () => {
		const fetch = vi
			.spyOn(globalThis, 'fetch')
			.mockResolvedValue(
				new Response(
					JSON.stringify({ code: 200, message: 'success', data: { items: [] }, meta: null })
				)
			);
		try {
			await expect(fetchModelConnections()).resolves.toEqual({ items: [] });
			expect(fetch.mock.calls[0][0]).toBe('/api/v1/model-connections');
		} finally {
			fetch.mockRestore();
		}
	});
});
