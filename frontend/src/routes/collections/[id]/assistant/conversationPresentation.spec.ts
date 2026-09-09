import { describe, expect, it } from 'vitest';
import type { ChatMessage, ChatToolResult } from '../../../_shared/chatSessions';
import {
	buildChatPresentation,
	getChatSessionActivity,
	getRecoveredChatProgress
} from './conversationPresentation';

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
		tool_call_id: role === 'tool' ? (options.toolCallId ?? null) : null,
		tool_calls:
			role === 'assistant' && options.toolCallId
				? [
						{
							tool_call_id: options.toolCallId,
							name: options.toolName!,
							arguments: {},
							position: 0
						}
					]
				: [],
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
	it('recovers only the current question progress and leaves unknown timing unset', () => {
		const current = message('current', 'user', { content: 'Compare matched tensile conditions' });
		const messages = [
			message('old-question', 'user'),
			message('old-call', 'assistant', { toolCallId: 'old', toolName: 'read_source' }),
			message('old-result', 'tool', { toolResult: result('old') }),
			current,
			message('read-a', 'assistant', { toolCallId: 'a', toolName: 'read_source' }),
			message('read-b', 'assistant', { toolCallId: 'b', toolName: 'read_source' }),
			message('result-a', 'tool', { toolResult: result('a', 'failed') })
		];
		expect(getRecoveredChatProgress(messages, Date.parse(current.created_at) + 65000)).toEqual({
			phase: 'recovering',
			requested_tool_count: 2,
			executed_tool_count: 1,
			elapsed_ms: 65000
		});
		expect(getRecoveredChatProgress([], Date.now())).not.toHaveProperty('elapsed_ms');
	});

	it('distinguishes running, approval, unconfirmed results and idle sessions', () => {
		const request = message('request', 'assistant', {
			toolCallId: 'write',
			toolName: 'create_finding_version'
		});
		expect(getChatSessionActivity([], true, null)).toBe('running');
		expect(getChatSessionActivity([request], false, 'write')).toBe('approval');
		expect(getChatSessionActivity([request], false, null)).toBe('recovering');
		expect(
			getChatSessionActivity(
				[request, message('result', 'tool', { toolResult: result('write') })],
				false,
				null
			)
		).toBe('idle');
	});

	it('shows a partially completed reading group as in progress', () => {
		const items = buildChatPresentation([
			message('read-a', 'assistant', { toolCallId: 'a', toolName: 'query_published_findings' }),
			message('result-a', 'tool', { toolResult: result('a') }),
			message('read-b', 'assistant', { toolCallId: 'b', toolName: 'query_published_findings' })
		]);
		expect(items).toHaveLength(1);
		expect(items[0]).toMatchObject({ kind: 'activity', status: 'in_progress' });
	});

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

	it('keeps Source, draft, quality, derivation, and plan results reviewable', () => {
		const toolNames = [
			'search_sources',
			'read_source',
			'inspect_table',
			'confirm_objective',
			'create_evidence_draft',
			'create_finding_draft',
			'assess_objective_quality',
			'derive_objective',
			'propose_research_plan',
			'create_research_plan'
		];
		const items = buildChatPresentation([
			message('call_context', 'assistant', {
				toolCallId: 'tool_context',
				toolName: 'get_collection_context'
			}),
			message('result_context', 'tool', {
				toolCallId: 'tool_context',
				toolResult: result('tool_context')
			}),
			...toolNames.flatMap((toolName, index) => [
				message(`call_${index}`, 'assistant', {
					toolCallId: `tool_${index}`,
					toolName
				}),
				message(`result_${index}`, 'tool', {
					toolCallId: `tool_${index}`,
					toolResult: result(`tool_${index}`)
				})
			])
		]);

		const activity = items[0];
		expect(activity.kind).toBe('activity');
		if (activity.kind !== 'activity') return;
		expect(activity.artifacts.map((item) => item.toolName)).toEqual(toolNames);
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
