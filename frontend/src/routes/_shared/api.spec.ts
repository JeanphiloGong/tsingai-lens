import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	ApiError, errorMessage, requestBlob, requestJson, requestText,
	isApiErrorCode, getApiErrorData
} from './api';
import { language } from './i18n';
import { get } from 'svelte/store';
import { authState } from './auth';

function apiResponse(code: number, data: unknown, message = 'success') {
	return new Response(JSON.stringify({ code, message, data, meta: null }), {
		headers: { 'Content-Type': 'application/json' }
	});
}

describe('API business response contract', () => {
	afterEach(() => {
		language.set('en');
		vi.unstubAllGlobals();
	});

	it('unwraps successful data and sends session credentials', async () => {
		const fetch = vi.fn().mockResolvedValue(apiResponse(200, { collection_id: 'col_1' }));
		vi.stubGlobal('fetch', fetch);
		await expect(requestJson('/collections')).resolves.toEqual({ collection_id: 'col_1' });
		expect(fetch).toHaveBeenCalledWith('/api/v1/collections', expect.objectContaining({ credentials: 'same-origin' }));
	});

	it.each([200100, 200201, 200204, 200205])('rejects business code %s under HTTP 200', async (code) => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(apiResponse(code, { code: 'rejected' }, 'Rejected.')));
		await expect(requestJson('/collections')).rejects.toMatchObject({ code, message: 'Rejected.', data: { code: 'rejected' } });
	});

	it('leaves ordinary network errors outside the business error contract', () => {
		const network = new Error('404 Not Found');
		expect(isApiErrorCode(network, 200201)).toBe(false);
		expect(getApiErrorData(network)).toBeNull();
		expect(errorMessage(network)).toBe(network.message);
	});

	it.each([['en', 'Invalid email or password.'], ['zh', '邮箱或密码错误。']] as const)(
		'formats invalid credentials for %s', (lang, expected) => {
			language.set(lang);
			expect(errorMessage(new ApiError(200301, 'Rejected.', { code: 'invalid_credentials' }))).toBe(expected);
		}
	);

	it.each([['en', 'This file is larger than the 256 MiB upload limit.'], ['zh', '文件超过 256 MiB 上传限制。']] as const)(
		'formats oversized uploads for %s', (lang, expected) => {
			language.set(lang);
			expect(errorMessage(new ApiError(200100, 'Rejected.', { code: 'upload_too_large' }))).toBe(expected);
		}
	);

	it('shows a safe message for server failures', () => {
		expect(errorMessage(new ApiError(200000, 'private diagnostic', {}))).toBe('The request could not be completed. Please try again.');
	});

	it('redirects an expired session to login', async () => {
		const replace = vi.fn();
		authState.set({ status: 'authenticated', user: { user_id: 'user_1', email: 'researcher@example.test' } });
		vi.stubGlobal('window', { location: { pathname: '/collections/col_1', replace } });
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(apiResponse(200301, { code: 'authentication_required' }, 'Authentication is required.')));
		await expect(requestJson('/collections')).rejects.toMatchObject({ code: 200301 });
		expect(replace).toHaveBeenCalledWith('/login');
		expect(get(authState)).toEqual({ status: 'anonymous', user: null });
	});

	it('keeps invalid credentials on the login page', async () => {
		const replace = vi.fn();
		vi.stubGlobal('window', { location: { pathname: '/login', replace } });
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(apiResponse(200301, { code: 'invalid_credentials' }, 'Invalid email or password.')));
		await expect(requestJson('/auth/login')).rejects.toMatchObject({ code: 200301 });
		expect(replace).not.toHaveBeenCalled();
	});

	it('preserves binary downloads and their JSON request content type', async () => {
		const fetch = vi.fn().mockResolvedValue(new Response('archive', { headers: { 'Content-Type': 'application/zip' } }));
		vi.stubGlobal('fetch', fetch);
		expect(await (await requestBlob('/collections/col_1/source-archives', { method: 'POST', body: JSON.stringify({ document_ids: ['doc_1'] }) })).text()).toBe('archive');
		const [, init] = fetch.mock.calls[0] as [string, RequestInit];
		expect(new Headers(init.headers).get('Content-Type')).toBe('application/json');
		expect(init.credentials).toBe('same-origin');
	});

	it('rejects a download error instead of saving its JSON', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(apiResponse(200204, { code: 'export_stale' }, 'Export is stale.')));
		await expect(requestBlob('/exports/one')).rejects.toMatchObject({ code: 200204 });
	});

	it.each(['attachment', 'inline'])('downloads %s JSON files as their original bytes', async (disposition) => {
		const content = '{"code":7,"rows":[1]}';
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(content, { headers: {
			'Content-Type': 'application/json', 'Content-Disposition': `${disposition}; filename="export.json"`
		} })));
		expect(await (await requestBlob('/exports/one')).text()).toBe(content);
	});

	it('downloads an ordinary JSON query as its data', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(apiResponse(200, { items: [1] })));
		expect(JSON.parse(await (await requestBlob('/finding-dataset')).text())).toEqual({ items: [1] });
	});

	it('keeps text responses and rejects JSON failures from text endpoints', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response('# Source', { headers: { 'Content-Type': 'text/markdown' } })).mockResolvedValueOnce(apiResponse(200201, {}, 'Missing source.')));
		await expect(requestText('/markdown')).resolves.toBe('# Source');
		await expect(requestText('/markdown')).rejects.toMatchObject({ code: 200201 });
	});

	it('rejects the retired raw JSON protocol', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"items":[]}')));
		await expect(requestJson('/collections')).rejects.toThrow('error.requestFailed');
	});
});
