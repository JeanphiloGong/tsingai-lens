import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const { requestJson } = vi.hoisted(() => ({ requestJson: vi.fn() }));
vi.mock('./api', async () => ({
	...(await vi.importActual<typeof import('./api')>('./api')),
	requestJson
}));
const { authState, clearAuthState, fetchCurrentSession, login, logout, startAuthSynchronization } =
	await import('./auth');
const user = { user_id: 'researcher_1', email: 'researcher@example.test' };

describe('account-scoped chat storage', () => {
	beforeEach(() => {
		clearAuthState();
		localStorage.clear();
		sessionStorage.clear();
		requestJson.mockReset();
	});

	it.each([false, true])(
		'waits for an earlier logout before signing in, logout failed: %s',
		async (fails) => {
			requestJson.mockResolvedValueOnce({ user });
			await login(user.email, 'test-only');
			let finish!: () => void;
			requestJson.mockImplementationOnce(
				() =>
					new Promise((resolve, reject) => {
						finish = () => (fails ? reject(new Error('Connection lost')) : resolve({}));
					})
			);
			const signingOut = logout().catch(() => undefined);
			const nextUser = { user_id: 'researcher_2', email: 'second@example.test' };
			requestJson.mockResolvedValueOnce({ user: nextUser });
			const signingIn = login(nextUser.email, 'test-only');
			try {
				expect(requestJson).toHaveBeenCalledTimes(2);
				expect(get(authState).status).toBe('anonymous');
			} finally {
				finish();
				await signingOut;
				await signingIn;
			}
			expect(get(authState).user?.user_id).toBe(nextUser.user_id);
		}
	);

	it.each(['session', 'login'])(
		'ignores a late %s response after another tab signs out',
		async (request) => {
			let complete!: (value: unknown) => void;
			requestJson.mockImplementationOnce(
				() =>
					new Promise((resolve) => {
						complete = resolve;
					})
			);
			const stop = startAuthSynchronization();
			try {
				const session =
					request === 'session' ? fetchCurrentSession() : login(user.email, 'test-only');
				sessionStorage.setItem('lens.chatSourceContext.researcher_1:col_123', 'private Source');
				window.dispatchEvent(
					new StorageEvent('storage', {
						key: 'lens.authInvalidation',
						newValue: 'other-tab-signout'
					})
				);
				complete({ user });
				if (request === 'session') await expect(session).resolves.toBeNull();
				else await expect(session).rejects.toThrow('error.authSessionChanged');
				expect(get(authState).status).toBe('anonymous');
				expect(sessionStorage.getItem('lens.chatSourceContext.researcher_1:col_123')).toBeNull();
			} finally {
				stop();
			}
		}
	);

	it('keeps the authenticated account history on reload and discards unowned cache entries', async () => {
		localStorage.setItem('lens.chatSession.researcher_1:col_123', 'chat_owned');
		localStorage.setItem('lens.chatSessionHistory.researcher_1:col_123', 'owned history');
		localStorage.setItem('lens.chatSessionHistory.researcher_2:col_123', 'other history');
		localStorage.setItem('lens.chatSessionHistory.col_123', 'unscoped history');
		sessionStorage.setItem('lens.chatSourceContext.researcher_1:col_123', 'owned Source');
		sessionStorage.setItem('lens.chatSourceContext.col_123', 'unscoped Source');
		localStorage.setItem('lens.theme', 'dark');
		requestJson.mockResolvedValue({ user });
		await fetchCurrentSession();
		expect(localStorage.getItem('lens.chatSession.researcher_1:col_123')).toBe('chat_owned');
		expect(localStorage.getItem('lens.chatSessionHistory.researcher_1:col_123')).toBe(
			'owned history'
		);
		expect(localStorage.getItem('lens.chatSessionHistory.researcher_2:col_123')).toBeNull();
		expect(localStorage.getItem('lens.chatSessionHistory.col_123')).toBeNull();
		expect(sessionStorage.getItem('lens.chatSourceContext.researcher_1:col_123')).toBe(
			'owned Source'
		);
		expect(sessionStorage.getItem('lens.chatSourceContext.col_123')).toBeNull();
		expect(localStorage.getItem('lens.theme')).toBe('dark');
	});

	it.each([false, true])(
		'clears history and pending Sources when logout fails: %s',
		async (fails) => {
			requestJson.mockResolvedValue({ user });
			await login(user.email, 'test-only');
			localStorage.setItem('lens.chatSessionHistory.researcher_1:col_123', 'private question');
			sessionStorage.setItem('lens.chatSourceContext.researcher_1:col_123', 'private selection');
			if (fails) {
				requestJson.mockRejectedValueOnce(new Error('503 Unavailable'));
				await expect(logout()).rejects.toThrow('503');
			} else {
				await logout();
			}
			expect(get(authState).status).toBe('anonymous');
			expect(localStorage.getItem('lens.chatSessionHistory.researcher_1:col_123')).toBeNull();
			expect(sessionStorage.getItem('lens.chatSourceContext.researcher_1:col_123')).toBeNull();
		}
	);
});
