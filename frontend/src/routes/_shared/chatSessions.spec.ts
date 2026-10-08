import { describe, expect, it, vi } from 'vitest';
import {
	appendChatProgress,
	formatChatElapsed,
	getChatProgressActions,
	streamChatMessage,
	setChatMessageFeedback,
	deleteChatSession,
	type ChatProgress
} from './chatSessions';

describe('chat session deletion', () => {
	it('uses the same-origin DELETE endpoint with encoded session identity', async () => {
		const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));
		try {
			await deleteChatSession('session/one');
			expect(fetch).toHaveBeenCalledWith(
				'/api/v1/chat-sessions/session%2Fone',
				expect.objectContaining({ method: 'DELETE', credentials: 'same-origin' })
			);
		} finally {
			fetch.mockRestore();
		}
	});
});

describe('answer feedback requests', () => {
	it('uses the same-origin API with encoded identities and explicit withdrawal', async () => {
		const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response('null', {
				headers: { 'Content-Type': 'application/json' }
			})
		);
		const controller = new AbortController();
		try {
			await expect(
				setChatMessageFeedback('session/one', 'message?one', { rating: null }, controller.signal)
			).resolves.toBeNull();
			expect(fetch).toHaveBeenCalledWith(
				'/api/v1/chat-sessions/session%2Fone/messages/message%3Fone/feedback',
				expect.objectContaining({
					method: 'PUT',
					credentials: 'same-origin',
					signal: controller.signal,
					body: '{"rating":null}'
				})
			);
		} finally {
			fetch.mockRestore();
		}
	});
});

describe('chat stream lifecycle', () => {
	it('releases an unfinished response when its conversation is left', async () => {
		const cancel = vi.fn();
		const textDelta = vi.fn();
		const controller = new AbortController();
		const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(
				new ReadableStream({
					start(stream) {
						stream.enqueue(
							new TextEncoder().encode(
								'event: text_delta\ndata: {"content":"Comparing the source conditions"}\n\n'
							)
						);
					},
					cancel
				})
			)
		);
		try {
			const response = streamChatMessage(
				'chat_1',
				'Compare grain morphology',
				textDelta,
				[],
				undefined,
				controller.signal
			);
			const rejected = expect(response).rejects.toMatchObject({ name: 'AbortError' });
			await vi.waitFor(() =>
				expect(textDelta).toHaveBeenCalledWith('Comparing the source conditions')
			);
			controller.abort();
			await rejected;
			expect(cancel).toHaveBeenCalledOnce();
			expect(fetch.mock.calls[0][1]?.signal).toBe(controller.signal);
		} finally {
			fetch.mockRestore();
		}
	});

	it('releases the reader after a malformed stream event', async () => {
		const cancel = vi.fn();
		const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(
				new ReadableStream({
					start(stream) {
						stream.enqueue(new TextEncoder().encode('event: progress\ndata: invalid\n\n'));
					},
					cancel
				})
			)
		);
		try {
			await expect(
				streamChatMessage('chat_1', 'Compare grain morphology', () => {})
			).rejects.toThrow();
			expect(cancel).toHaveBeenCalledOnce();
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
});
