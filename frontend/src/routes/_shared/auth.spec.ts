import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';


import { authState, clearAuthState, fetchCurrentSession, login } from './auth';

const fetch = vi.fn();
function apiResponse(code: number, data: unknown) {
    return new Response(JSON.stringify({ code, message: 'response', data, meta: null }), {
        headers: { 'Content-Type': 'application/json' }
    });
}

describe('auth shared helper', () => {
	beforeEach(() => {
		fetch.mockReset();
		vi.stubGlobal('fetch', fetch);
		clearAuthState();
	});

	afterEach(() => vi.unstubAllGlobals());

	it('loads the current authenticated user', async () => {
		fetch.mockResolvedValue(apiResponse(200, {
			user: {
				user_id: 'user_1',
				email: 'admin@example.com',
				display_name: 'Admin'
			}
		}));

		const user = await fetchCurrentSession();

		expect(fetch).toHaveBeenCalledWith('/api/v1/auth/me', expect.objectContaining({ method: 'GET', credentials: 'same-origin' }));
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
		fetch.mockResolvedValue(apiResponse(200301, { code: 'authentication_required' }));

		const user = await fetchCurrentSession();

		expect(user).toBeNull();
		expect(get(authState)).toEqual({
			status: 'anonymous',
			user: null
		});
	});

	it('submits login credentials through the same auth endpoint', async () => {
		fetch.mockResolvedValue(apiResponse(200, {
			user: {
				user_id: 'user_2',
				email: 'researcher@example.com'
			}
		}));

		const user = await login('researcher@example.com', 'secret');

		expect(fetch).toHaveBeenCalledWith('/api/v1/auth/login', expect.objectContaining({
			method: 'POST',
			body: JSON.stringify({
				email: 'researcher@example.com',
				password: 'secret'
			}),
			credentials: 'same-origin'
		}));
		expect(user).toMatchObject({
			user_id: 'user_2',
			email: 'researcher@example.com'
		});
	});
});
