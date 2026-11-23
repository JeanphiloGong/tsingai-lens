import { describe, expect, it, vi } from 'vitest';
import { stopChatResponse } from '$lib/agent/api';
import { getTurnNotice } from '$lib/research/conversationPresentation';

describe('stopping research responses', () => {
	it('targets an exact response through the same-origin stop endpoint', async () => {
		const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(
				JSON.stringify({
					code: 200,
					message: 'success',
					meta: null,
					data: { task_id: 'response/one', status: 'interrupted' }
				})
			)
		);
		try {
			await expect(stopChatResponse('session/one', 'response/one')).resolves.toMatchObject({
				status: 'interrupted'
			});
			expect(fetch).toHaveBeenCalledWith(
				'/api/v1/conversations/session%2Fone/tasks/response%2Fone/stop',
				expect.objectContaining({ method: 'POST', credentials: 'same-origin' })
			);
		} finally {
			fetch.mockRestore();
		}
	});

	it('presents an intentional stop without a technical failure or automatic continuation', () => {
		expect(
			getTurnNotice({
				status: 'cancelled',
				completion_reason: null,
				error_code: 'user_cancelled',
				messages: [],
				warnings: [],
				pending_approval: null
			})
		).toEqual({
			messageKey: 'researchAgent.responseStopped',
			titleKey: null,
			isError: false,
			canContinue: false
		});
	});
});
