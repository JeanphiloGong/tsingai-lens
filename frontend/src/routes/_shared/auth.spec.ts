import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const { requestJson } = vi.hoisted(() => ({
	requestJson: vi.fn()
}));

vi.mock('./api', async () => {
	const actual = await vi.importActual<typeof import('./api')>('./api');
	return {
		...actual,
		requestJson
	};
});

const { authState, clearAuthState, fetchCurrentSession, login } = await import('./auth');

describe('auth shared helper', () => {
	beforeEach(() => {
		requestJson.mockReset();
		clearAuthState();
	});

	it('loads the current authenticated user', async () => {
		requestJson.mockResolvedValue({
			user: {
				user_id: 'user_1',
				email: 'admin@example.com',
				display_name: 'Admin'
			}
		});

		const user = await fetchCurrentSession();

		expect(requestJson).toHaveBeenCalledWith('/auth/me', { method: 'GET' });
		expect(user).toEqual({
			user_id: 'user_1',
			email: 'admin@example.com',
			display_name: 'Admin'
		});
		expect(get(authState)).toMatchObject({
			status: 'authenticated',
			user: {
				user_id: 'user_1',
				email: 'admin@example.com'
			}
		});
	});

	it('sets anonymous state on a missing session', async () => {
		requestJson.mockRejectedValue(new Error('401 Unauthorized'));

		const user = await fetchCurrentSession();

		expect(user).toBeNull();
		expect(get(authState)).toEqual({
			status: 'anonymous',
			user: null
		});
	});

	it('submits login credentials through the same auth endpoint', async () => {
		requestJson.mockResolvedValue({
			user: {
				user_id: 'user_2',
				email: 'researcher@example.com'
			}
		});

		const user = await login('researcher@example.com', 'secret');

		expect(requestJson).toHaveBeenCalledWith('/auth/login', {
			method: 'POST',
			body: JSON.stringify({
				email: 'researcher@example.com',
				password: 'secret'
			})
		});
		expect(user).toMatchObject({
			user_id: 'user_2',
			email: 'researcher@example.com'
		});
	});
});
