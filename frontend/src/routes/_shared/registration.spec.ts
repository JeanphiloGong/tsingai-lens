import { afterEach, describe, expect, it, vi } from 'vitest';
import { issueEmailChallenge, registerAccount, resetPassword } from './auth';
import { requestJson } from './api';

afterEach(() => vi.unstubAllGlobals());
describe('public account HTTP contract', () => {
	it.each([true, false])(
		'preserves top-level429 retry information with header=%s',
		async (withHeader) => {
			vi.stubGlobal(
				'fetch',
				vi
					.fn()
					.mockResolvedValue(
						new Response(JSON.stringify({ code: 'rate_limited', retry_after: 60 }), {
							status: 429,
							headers: withHeader ? { 'Retry-After': '60' } : {}
						})
					)
			);
			await expect(requestJson('/user-api/v1/email-challenges')).rejects.toMatchObject({
				code: 200206,
				data: { code: 'rate_limited', retry_after: 60 }
			});
		}
	);
	it('uses the existing direct identity client for challenge/register/reset', async () => {
		const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
		vi.stubGlobal('fetch', fetch);
		await issueEmailChallenge('a@example.test', 'register');
		const user = { user_id: 'new', email: 'a@example.test', display_name: 'A' };
		fetch.mockResolvedValue(new Response(JSON.stringify(user)));
		await expect(
			registerAccount({
				email: 'a@example.test',
				challenge_id: 'id',
				code: '123456',
				password: 'long-password',
				display_name: 'A'
			})
		).resolves.toEqual(user);
		fetch.mockResolvedValue(new Response(JSON.stringify({ ok: true })));
		await resetPassword({
			email: 'a@example.test',
			challenge_id: 'id',
			code: '123456',
			password: 'new-password'
		});
		expect(fetch.mock.calls.map((c) => c[0])).toEqual([
			'/user-api/v1/email-challenges',
			'/user-api/v1/register',
			'/user-api/v1/password-resets'
		]);
	});
});
