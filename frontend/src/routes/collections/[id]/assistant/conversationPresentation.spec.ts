import { describe, expect, it } from 'vitest';
import type { ChatMessage, ChatToolResult } from '../../../_shared/chatSessions';
import { buildChatPresentation } from './conversationPresentation';

function message(
	messageId: string,
	role: ChatMessage['role'],
	options: {
		content?: string;
		toolCallId?: string;
		toolName?: string;
		toolResult?: ChatToolResult;
	} = {}
): ChatMessage {
	return {
		message_id: messageId,
		session_id: 'session_1',
		role,
		content: options.content ?? '',
		created_at: '2026-09-03T10:00:00+08:00',
		tool_call_id: options.toolCallId ?? null,
		tool_name: options.toolName ?? null,
		tool_arguments: options.toolCallId ? {} : null,
		tool_result: options.toolResult ?? null,
		source_contexts: []
	};
}

function result(toolCallId: string, status: ChatToolResult['status'] = 'succeeded') {
	return {
		tool_call_id: toolCallId,
		status,
		data: {},
		resource_refs: [],
		warnings: [],
		error_code: null,
		error_message: null
	} satisfies ChatToolResult;
}

describe('buildChatPresentation', () => {
	it('compresses consecutive routine tool calls into one research activity group', () => {
		const items = buildChatPresentation([
			message('user_1', 'user', { content: 'Which findings support this question?' }),
			message('call_1', 'assistant', {
				toolCallId: 'tool_1',
				toolName: 'get_collection_context'
			}),
			message('result_1', 'tool', { toolCallId: 'tool_1', toolResult: result('tool_1') }),
			message('call_2', 'assistant', {
				toolCallId: 'tool_2',
				toolName: 'query_published_findings'
			}),
			message('result_2', 'tool', { toolCallId: 'tool_2', toolResult: result('tool_2') }),
			message('assistant_1', 'assistant', { content: 'Two findings address the question.' })
		]);

		expect(items.map((item) => item.kind)).toEqual(['message', 'activity', 'message']);
		const activity = items[1];
		expect(activity.kind).toBe('activity');
		if (activity.kind !== 'activity') return;
		expect(activity.operations).toHaveLength(2);
		expect(activity.status).toBe('completed');
		expect(activity.artifacts).toEqual([]);
	});

	it('keeps reviewable research outputs available as standalone artifacts', () => {
		const items = buildChatPresentation([
			message('call_1', 'assistant', {
				toolCallId: 'tool_1',
				toolName: 'propose_objective_drafts'
			}),
			message('result_1', 'tool', { toolCallId: 'tool_1', toolResult: result('tool_1') })
		]);

		const activity = items[0];
		expect(activity.kind).toBe('activity');
		if (activity.kind !== 'activity') return;
		expect(activity.artifacts).toHaveLength(1);
		expect(activity.artifacts[0].toolName).toBe('propose_objective_drafts');
	});

	it('marks a failed operation so its details can open automatically', () => {
		const items = buildChatPresentation([
			message('call_1', 'assistant', {
				toolCallId: 'tool_1',
				toolName: 'inspect_document_sources'
			}),
			message('result_1', 'tool', {
				toolCallId: 'tool_1',
				toolResult: result('tool_1', 'failed')
			})
		]);

		const activity = items[0];
		expect(activity.kind).toBe('activity');
		if (activity.kind !== 'activity') return;
		expect(activity.status).toBe('failed');
	});

	it('does not let a standalone artifact failure relabel successful routine work', () => {
		const items = buildChatPresentation([
			message('call_1', 'assistant', {
				toolCallId: 'tool_1',
				toolName: 'get_collection_context'
			}),
			message('result_1', 'tool', { toolCallId: 'tool_1', toolResult: result('tool_1') }),
			message('call_2', 'assistant', {
				toolCallId: 'tool_2',
				toolName: 'propose_objective_drafts'
			}),
			message('result_2', 'tool', {
				toolCallId: 'tool_2',
				toolResult: result('tool_2', 'failed')
			})
		]);

		const activity = items[0];
		expect(activity.kind).toBe('activity');
		if (activity.kind !== 'activity') return;
		expect(activity.artifacts).toHaveLength(1);
		expect(activity.status).toBe('completed');
	});
});
