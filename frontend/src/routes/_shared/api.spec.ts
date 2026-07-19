import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, errorMessage, requestJson } from './api';
import { language } from './i18n';

describe('api shared error handling', () => {
	afterEach(() => {
		language.set('en');
		vi.unstubAllGlobals();
	});

	it.each([
		['en', 'Invalid email or password.'],
		['zh', '邮箱或密码错误。']
	] as const)(
		'formats invalid credentials for %s without exposing the raw response',
		(lang, expected) => {
			language.set(lang);
			const error = new ApiError(401, 'Unauthorized', {
				code: 'invalid_credentials',
				message: 'Invalid email or password.'
			});

			expect(errorMessage(error)).toBe(expected);
			expect(errorMessage(error)).not.toContain('401 Unauthorized');
		}
	);

	it('redirects to login when an authenticated request loses its session', async () => {
		const replace = vi.fn();
		vi.stubGlobal('window', {
			location: { pathname: '/collections/col_1', replace }
		});
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(
				new Response(
					JSON.stringify({
						detail: {
							code: 'authentication_required',
							message: 'Authentication is required.'
						}
					}),
					{
						status: 401,
						statusText: 'Unauthorized',
						headers: { 'Content-Type': 'application/json' }
					}
				)
			)
		);

		await expect(requestJson('/collections')).rejects.toMatchObject({
			status: 401
		});
		expect(replace).toHaveBeenCalledWith('/login');
	});

	it('keeps invalid login credentials on the login page', async () => {
		const replace = vi.fn();
		vi.stubGlobal('window', {
			location: { pathname: '/login', replace }
		});
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(
				new Response(
					JSON.stringify({
						detail: {
							code: 'invalid_credentials',
							message: 'Invalid email or password.'
						}
					}),
					{ status: 401, statusText: 'Unauthorized' }
				)
			)
		);

		await expect(
			requestJson('/auth/login', {
				method: 'POST',
				body: JSON.stringify({ email: 'admin@example.com', password: 'wrong' })
			})
		).rejects.toMatchObject({ status: 401 });
		expect(replace).not.toHaveBeenCalled();
	});
});
