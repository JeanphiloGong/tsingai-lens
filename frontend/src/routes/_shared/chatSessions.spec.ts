import { describe, expect, it } from 'vitest';
import {
	appendChatProgress,
	formatChatElapsed,
	getChatProgressActions,
	type ChatProgress
} from './chatSessions';

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
});
