import { describe, expect, it, vi } from 'vitest';
import {
	setChatMessageFeedback,
	deleteChatSession,
	setChatSessionPin
} from '$lib/conversation/api';

describe('chat session deletion', () => {
	it('uses the same-origin DELETE endpoint with encoded session identity', async () => {
		const fetch = vi
			.spyOn(globalThis, 'fetch')
			.mockResolvedValue(
				new Response(JSON.stringify({ code: 200, message: 'success', data: {}, meta: null }))
			);
		try {
			await deleteChatSession('session/one');
			expect(fetch).toHaveBeenCalledWith(
				'/api/v1/conversations/session%2Fone',
				expect.objectContaining({ method: 'DELETE', credentials: 'same-origin' })
			);
		} finally {
			fetch.mockRestore();
		}
	});
});

describe('chat history pinning', () => {
	it.each([true, false])(
		'saves an explicit pin state %s with an encoded session identity',
		async (isPinned) => {
			const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
				new Response(
					JSON.stringify({
						code: 200,
						message: 'success',
						data: { session_id: 'session/one', is_pinned: isPinned },
						meta: null
					}),
					{
						headers: { 'Content-Type': 'application/json' }
					}
				)
			);
			const controller = new AbortController();
			try {
				await expect(
					setChatSessionPin('session/one', isPinned, controller.signal)
				).resolves.toMatchObject({ is_pinned: isPinned });
				expect(fetch).toHaveBeenCalledWith(
					'/api/v1/conversations/session%2Fone/pin',
					expect.objectContaining({
						method: 'PUT',
						credentials: 'same-origin',
						signal: controller.signal,
						body: JSON.stringify({ is_pinned: isPinned })
					})
				);
			} finally {
				fetch.mockRestore();
			}
		}
	);
});

describe('answer feedback requests', () => {
	it('uses the same-origin API with encoded identities and explicit withdrawal', async () => {
		const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(JSON.stringify({ code: 200, message: 'success', data: {}, meta: null }), {
				headers: { 'Content-Type': 'application/json' }
			})
		);
		const controller = new AbortController();
		try {
			await expect(
				setChatMessageFeedback('session/one', 'message?one', { rating: null }, controller.signal)
			).resolves.toBeNull();
			expect(fetch).toHaveBeenCalledWith(
				'/api/v1/conversations/session%2Fone/messages/message%3Fone/feedback',
				expect.objectContaining({
					method: 'DELETE',
					credentials: 'same-origin',
					signal: controller.signal
				})
			);
		} finally {
			fetch.mockRestore();
		}
	});
});
