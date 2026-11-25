import { describe, expect, it, vi } from 'vitest';
import { stopTask } from '$lib/agent/api';
import { getTurnNotice } from '$lib/research/conversationPresentation';

describe('stopping research responses', () => {
	it('targets an exact response through the same-origin stop endpoint', async () => {
		const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
			const data = String(input).endsWith('/messages')
				? { conversation: { current_task_id: 'task/one' }, items: [] }
				: { task_id: 'task/one', status: 'interrupted', checkpoint_revision: 3 };
			return Response.json({ code: 200, message: 'success', data, meta: null });
		});
		try {
			await expect(stopTask('session/one', 'task/one')).resolves.toMatchObject({
				status: 'interrupted'
			});
			expect(fetch).toHaveBeenCalledWith(
				'/api/v1/conversations/session%2Fone/tasks/task%2Fone/stop',
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
