import { afterEach, describe, expect, it } from 'vitest';
import { ApiError, errorMessage } from './api';
import { language } from './i18n';

describe('api shared error handling', () => {
	afterEach(() => {
		language.set('en');
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
});
